```markdown
# EduPay Ledger Academy – Developer Guide
_Expert-level C programming meets domain-driven payments_

---

## Table of Contents
1. TL;DR (90-second build)
2. Project Layout
3. Build & Test Pipeline
4. Clean Architecture Primer
5. Hands-On: Creating a Tuition Payment Use-Case
6. Enabling Saga Pattern Demonstration Mode
7. Event Sourcing & CQRS Projections
8. Cross-Cutting Concerns  
   8.1 Security-by-Design Checklist  
   8.2 Fault Tolerance & Observability  
   8.3 Memory Management Strategy
9. Extending the System (New Bounded Contexts)
10. Tooling & Static Analysis
11. Appendix A – Error Code Registry
12. Appendix B – Coding Style Cheatsheet
13. Appendix C – Build Targets

---

## 1. TL;DR (90-second build)

```bash
git clone https://github.com/EduPayLedgerAcademy/fintech_payment.git
cd fintech_payment

# Select a build profile: {dev, test, prod}
export EDL_PROFILE=dev

# Build, lint, test, and spin-up the microservice demo
cmake -S . -B build -DCMAKE_BUILD_TYPE=${EDL_PROFILE}
cmake --build build --target all && \
cmake --build build --target run-lite
```

Requirements: `gcc >= 12`, `CMake >= 3.25`, `protobuf-c >= 1.4`, `libpq`, `libsodium`, `nanomsg`, `utf8proc`.

---

## 2. Project Layout

The repository root is intentionally flat so CS students can grep with ease:

```
├── admissions/                # Domain layer (Clean Architecture)
│   ├── include/               # Public headers (Stable ABI)
│   ├── src/                   # Private implementation
│   └── tests/                 # UT & property-based tests
├── bursar/
├── financial_aid/
├── continuing_education/
├── common/                    # Cross-cutting: logging, crypto, i18n
├── docs/                      # This guide + ADRs
├── scripts/                   # Dev-ops helpers (.sh/.ps1)
└── CMakeLists.txt             # Top-level orchestrator
```

Bounded contexts live side-by-side; each compiles into a static library consumed by thin microservice shells (`services/`).

---

## 3. Build & Test Pipeline

Targets are defined in `cmake/targets.cmake`.

| Target            | Description                           | Command                                    |
|-------------------|---------------------------------------|--------------------------------------------|
| `all`             | Build everything                      | `cmake --build build`                      |
| `check`           | Unit + Integration tests              | `ctest --output-on-failure`                |
| `scan`            | Static analysis via clang-tidy        | `cmake --build build --target clang-tidy`  |
| `format`          | clang-format auto-formatter           | `make format`                              |
| `run-lite`        | Launch in-memory demo (SQLite, NNG)   | `./build/bin/edl-demo-lite`                |

---

## 4. Clean Architecture Primer

Layers (low → high):

```
[ Entities ] ← pure C structs, validated invariants
[ Use-Cases ] ← orchestration & policies
[ Interface Adapters ] ← Repos, Message Ports (compile-time injected)
[ Frameworks / Drivers ] ← Postgres, HTTP, NNG, CLIs (replaceable)
```

Each layer depends **only** on the one inside it—no outward coupling.  
Dependency inversion is enforced via abstract header contracts.

---

## 5. Hands-On: Creating a Tuition Payment Use-Case

We walk through building `ProcessTuitionPayment`, a canonical flow spanning
multi-currency conversion, fraud heuristics, and audit trail emission.

### 5.1 Define Domain Entities (`admissions/include/tuition.h`)

```c
#ifndef EDL_TUITION_H
#define EDL_TUITION_H

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    CURR_USD,
    CURR_EUR,
    CURR_GBP,
    CURR_JPY
} currency_t;

typedef struct {
    int64_t cents;       // always minor units
    currency_t curr;
} money_t;

/* Compile-time assertion to ensure struct size is predictable */
_Static_assert(sizeof(money_t) == 12, "money_t layout changed");

typedef struct {
    char         student_id[16];   // FERPA-compliant opaque ID
    money_t      amount_due;
    money_t      scholarship_offset;
    bool         is_domestic;
} tuition_invoice_t;

#endif /* EDL_TUITION_H */
```

### 5.2 Repository Boundary (`admissions/include/tuition_repo.h`)

```c
#ifndef EDL_TUITION_REPO_H
#define EDL_TUITION_REPO_H

#include "tuition.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct tuition_repo tuition_repo_t;

/* Abstract interface (Dependency Inversion) */
typedef struct {
    int  (*find_by_student)(tuition_repo_t*, const char* student_id,
                            tuition_invoice_t* out);
    int  (*mark_paid)(tuition_repo_t*, const char* student_id,
                      const money_t paid, const char* tx_id);
    void (*destroy)(tuition_repo_t*);
} tuition_repo_vtbl_t;

struct tuition_repo {
    const tuition_repo_vtbl_t* vptr;
    void*                      impl;   // hidden driver ptr
};

#ifdef __cplusplus
}
#endif
#endif /* EDL_TUITION_REPO_H */
```

### 5.3 Use-Case Interactor (`admissions/src/process_tuition.c`)

```c
#include "tuition.h"
#include "tuition_repo.h"
#include "fx_rate.h"
#include "fraud_scanner.h"
#include "audit_trail.h"
#include <stdio.h>

typedef struct {
    tuition_repo_t* repo;
    fx_service_t*   fx;
    fraud_scanner_t* fraud;
    audit_trail_t*  audit;
} process_tuition_ctx_t;

static int validate(const tuition_invoice_t* inv) {
    if (!inv) return EINVAL;
    if (inv->amount_due.cents <= 0) return ERANGE;
    /* additional domain invariants ... */
    return 0;
}

int process_tuition_payment(process_tuition_ctx_t* ctx,
                            const char* student_id,
                            money_t incoming,
                            char* out_tx_id /* uuid-v7 buffer 37B */)
{
    if (!ctx || !student_id || !out_tx_id) return EINVAL;

    tuition_invoice_t inv = {0};
    int rc = ctx->repo->vptr->find_by_student(ctx->repo, student_id, &inv);
    if (rc) return rc;

    if ((rc = validate(&inv))) return rc;

    /* Currency conversion if incoming differs */
    if (incoming.curr != inv.amount_due.curr) {
        rc = ctx->fx->vptr->convert(ctx->fx, incoming, inv.amount_due.curr, &incoming);
        if (rc) return rc;
    }

    /* Fraud check – heuristic threshold differs for cross-border */
    if ((rc = ctx->fraud->vptr->scan(ctx->fraud, student_id, incoming))) {
        return rc; /* flagged as suspicious → propagate */
    }

    /* Apply scholarship */
    if (inv.scholarship_offset.cents > 0) {
        if (incoming.cents < inv.scholarship_offset.cents)
            return EPAYMENT_UNDERFLOW;
        incoming.cents -= inv.scholarship_offset.cents;
    }

    /* Mark as paid within a single DB transaction */
    rc = ctx->repo->vptr->mark_paid(ctx->repo, student_id, incoming, out_tx_id);
    if (rc) return rc;

    /* Write immutable audit record */
    ctx->audit->vptr->emit(ctx->audit, AUDIT_TUITION_PAID, student_id,
                           out_tx_id, &incoming);

    return 0;
}
```

The interactor is **framework-agnostic**; swapping Postgres → MySQL requires only a new `tuition_repo` driver.

---

## 6. Enabling Saga Pattern Demonstration Mode

Saga mode intentionally injects faults (network timeouts, db deadlocks)
and forces learners to perform distributed rollbacks.

```bash
# Compile with the saga demo feature flag
cmake -B build -DSAGA_DEMO=ON && cmake --build build

# At runtime toggle chaos modules
export EDL_CHAOS_FREQ="0.15"      # 15 % of messages are sabotaged
./build/bin/edl-payment-svc
```

Driver code uses `chaos_injector.h`—see `common/src/chaos_injector.c`.

---

## 7. Event Sourcing & CQRS Projections

Domain events are persisted in the `event_store` table:

```
| id | aggregate_id | type               | payload | version | ts  |
---------------------------------------------------------------------
| 42 | STUD-9182    | TuitionPaid        | {...}   | 3       | …   |
| 43 | STUD-9182    | LedgerUpdated      | {...}   | 4       | …   |
```

The **write** model emits immutable events; read-side projections hydrate
materialized views used by dashboards (`projection_tuition_balance`).  
Regenerating projections:

```bash
./build/bin/edl-projection-replay --aggregate admissions
```

---

## 8. Cross-Cutting Concerns

### 8.1 Security-by-Design Checklist
- All personal identifiers are encrypted at rest (libsodium XChaCha20-Poly1305).
- PCI-DSS card data never persists; tokenization via vault microservice.
- `-D_FORTIFY_SOURCE=3` and `-fsanitize=address,undefined` during CI.
- Full stack TLS 1.3, mutual authentication for internal microservices.

### 8.2 Fault Tolerance & Observability
- Circuit breakers (`common/src/circuit_breaker.c`) guard every external call.
- Structured logging (JSON) with correlation IDs.
- Prometheus exporters under `telemetry/`.

### 8.3 Memory Management Strategy
- Ownership rules: “Creator frees” unless annotated with `_TRANSFER`.
- Arena allocators for event sourcing hot path to reduce fragmentation.
- Mandatory use of `VALGRIND=1 make check` in CI.

---

## 9. Extending the System (New Bounded Contexts)

1. `scripts/new_context.sh FinanceOps`
2. Implement domain entities under `finance_ops/include`.
3. Add CMake library:
   ```cmake
   add_library(finance_ops STATIC ${FINANCE_OPS_SOURCES})
   target_link_libraries(finance_ops PUBLIC common)
   ```
4. Register microservice shell in `services/CMakeLists.txt`.
5. Add ADR and doc snippet.

---

## 10. Tooling & Static Analysis

| Tool             | Purpose                        | CI Stage   |
|------------------|--------------------------------|------------|
| clang-tidy       | MISRA & CERT secure rulesets   | `scan`     |
| cppcheck         | Additional linting             | `scan`     |
| valgrind         | Leak & UB detection            | `check`    |
| mold/ld.lld      | Lightning-fast linking         | `build`    |
| gcov + lcov      | Coverage badge                 | `report`   |

---

## 11. Appendix A – Error Code Registry

| Code                    | Value | Meaning                                |
|-------------------------|-------|----------------------------------------|
| `EPAYMENT_UNDERFLOW`    | 8201  | Payment < amount due after discounts   |
| `EFRAUD_SUSPECTED`      | 8300  | Fraud scanner flagged transaction      |
| `EAUDIT_WRITE_FAIL`     | 8400  | Audit trail persistence failure        |
| ...                     | ...   | ...                                    |

`common/include/edl_error.h` centralizes these constants.

---

## 12. Appendix B – Coding Style Cheatsheet
- Snake_case for variables, UpperCamel for types, SCREAMING_SNAKE for macros.
- Line length ≤ 100.
- Always initialize structs with designated initializers.
- No hidden state: **no** file-static variables in core layers.

---

## 13. Appendix C – Build Targets

```make
make help            # Pretty-printed target list
make deploy-prod     # Cross-compile static binaries & build OCI images
make fuzz            # Launch libFuzzer corpus for payment parser
```

---

Happy hacking, and welcome to EduPay Ledger Academy!  
Questions? Open a GitHub Discussion or ping `#edl-dev` on Slack.

```
