```markdown
<!--
EduPay Ledger Academy – Coursework Guide
========================================

File: docs/guides/coursework_guide.md
Generated: 2024-06-18

This document is part of the public-facing documentation set.
It is written in Markdown but embeds C source snippets that compile
and ship in production.  All code has been simplified for readability,
yet each fragment can be copied into the main repository without change.
-->

# Coursework Guide

Welcome to **EduPay Ledger Academy**—a production-grade payment rail built
for higher-education.  
This guide provides the scaffolding instructors need to transform the
codebase into an interactive syllabus.

1. Prerequisites  
2. Architecture Primer  
3. Hands-On Labs  
4. Assessment Checklist  
5. FAQ & Troubleshooting

> 💡  **Heads-Up**  
> The platform is written in ISO C17.  We rely on **CMake** for builds,
> **Unity** for unit-tests, and **Conan** for dependency management.  
> Students work inside containers shipped with reproducible toolchains.

---

## 1  Prerequisites

| Skill              | Minimum Level |
|--------------------|---------------|
| C programming      | Intermediate  |
| Git workflows      | Basic         |
| SQL fundamentals   | Beginner      |
| Networking (TCP)   | Beginner      |
| Design patterns    | Conceptual    |

Clone the repository:

```sh
git clone https://github.com/EduPay-Labs/EduPayLedgerAcademy.git
cd EduPayLedgerAcademy
conan install . --build=missing
cmake -B build
cmake --build build
```

---

## 2  Architecture Primer

The codebase follows **Robert C. Martin’s Clean Architecture**:

```
┌─────────────────────────┐
│        Entities         │  <- Pure business rules (no libs)
├─────────────────────────┤
│  Use-Cases / Interactors│  <- Orchestrates Entities
├─────────────────────────┤
│ Interface Adapters      │  <- Converters, Presenters, Gateways
├─────────────────────────┤
│  Framework & Drivers    │  <- DBs, Web, CLI, Message-Bus
└─────────────────────────┘
```

Cross-cutting concerns (logging, config, crypto) live inside
`/platform`.

### 2.1 Saga Pattern in Practice

When a tuition payment spans multiple services (Admissions, Bursar,
Scholarship-Office), the system initiates a **Saga** that guarantees
atomic behaviour across microservices via *compensating transactions*.

```c
// payment_saga_orchestrator.c
#include "domain/events.h"
#include "usecases/saga/payment_saga.h"
#include "adapters/message_bus.h"
#include "platform/log.h"

// Timeout for each child transaction (in milliseconds)
#define SAGA_STEP_TIMEOUT_MS  2000UL

/**
 * Run tuition payment saga synchronously.
 * Returns 0 on complete success, or a negative errno-style code.
 */
int execute_payment_saga(const tuition_payment_t *tx)
{
    if (!tx) return -EINVAL;

    saga_ctx_t ctx = {0};
    int rc = saga_init(&ctx, tx->id, SAGA_STEP_TIMEOUT_MS);
    if (rc) return rc;

    // 1. Reserve seat in class roster
    rc = saga_try_step(&ctx,
        admissions_reserve_seat,
        admissions_cancel_seat,
        tx);
    if (rc) goto rollback;

    // 2. Authorize payment
    rc = saga_try_step(&ctx,
        bursar_authorize_payment,
        bursar_refund_payment,
        tx);
    if (rc) goto rollback;

    // 3. Allocate scholarship if applicable
    rc = saga_try_step(&ctx,
        scholarship_allocate_award,
        scholarship_revoke_award,
        tx);
    if (rc) goto rollback;

    log_info("Saga %s succeeded", ctx.id);
    saga_complete(&ctx);
    return 0;

rollback:
    log_warn("Saga %s failed, triggering compensations", ctx.id);
    saga_rollback(&ctx);
    return rc;
}
```

### 2.2 Event Sourcing & CQRS

Each domain event is persisted immutably under
`/data/event_store/<aggregate>/<timestamp>.evt`.

```c
// adapters/event_store/file_event_store.c
static int persist_event(const domain_event_t *evt)
{
    char path[PATH_MAX];
    snprintf(path, sizeof(path),
             "%s/%s/%ld.evt",
             cfg_event_store_root(),
             evt->aggregate_type,
             evt->timestamp);

    FILE *fp = fopen(path, "ab");
    if (!fp) {
        log_error("fopen failed: %s", strerror(errno));
        return -errno;
    }

    size_t n = fwrite(evt, sizeof(*evt), 1, fp);
    fclose(fp);

    if (n != 1) {
        log_error("fwrite failed for %s", path);
        return -EIO;
    }
    return 0;
}
```

---

## 3  Hands-On Labs

### Lab 1: Compile-Time Dependency Injection

1. Open `src/usecases/payment_processor.c`.
2. Inject a fake `risk_assessor_t` that always returns low-risk.
3. Compile & run `ctest -R payment_processor`.

```c
// test/fakes/fake_risk_assessor.c
#include "risk_assessor.h"

risk_level_t risk_assessor_score(const payment_t *pmt)
{
    (void)pmt;   // unused
    return RISK_LOW;
}
```

### Lab 2: Multi-Currency Settlement

Task: Extend `multi_currency_settlement.c` to support **JPY**.

Acceptance criteria:
- Maximum rounding error ≤ 0.5 Yen.
- Unit test `test_settlement_jpy` passes.

Hint: Use banker's rounding for ¥.

### Lab 3: Distributed Rollback Debugging

Enable **Saga Pattern Demonstration Mode** in `config/core.yaml`:

```yaml
saga:
  demo_mode: true
  chaos_monkey:
    outage_probability: 0.20
```

Run:

```sh
./bin/ledger_demo --scenario tuition_outage
```

Observe audits in `logs/rollback_trace.log`.  
Submit a patch that eliminates *double-refund* defect.

---

## 4  Assessment Checklist

- [ ] **Unit Tests** > 95 % pass rate  
- [ ] Implements new compliance rule RFC-FERPA-0624  
- [ ] Adds JPY support in settlement engine  
- [ ] No new `cppcheck` or `clang-tidy` warnings  
- [ ] All commits signed (`git config --global commit.gpgsign true`)

---

## 5  FAQ & Troubleshooting

**Q:** Build fails: `undefined reference to 'sodium_*'`  
**A:** Run `conan install . --build=missing` to pull **libsodium**.

**Q:** Saga stuck in *Pending*?  
**A:** Verify each compensating function is **idempotent** and returns
`0` when called multiple times.

---

## Appendix A — Minimal Payment Entity

```c
// domain/entities/payment.h
#ifndef EDUPAY_DOMAIN_PAYMENT_H
#define EDUPAY_DOMAIN_PAYMENT_H

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    CURR_USD,
    CURR_EUR,
    CURR_GBP,
    CURR_JPY,
    CURR_MAX
} currency_code_t;

typedef struct {
    uint64_t     id;
    uint64_t     student_id;
    uint64_t     amount_minor;   // cents, pence, yen, etc.
    currency_code_t currency;
    bool         scholarship_applied;
} payment_t;

#endif // EDUPAY_DOMAIN_PAYMENT_H
```

---

## Appendix B — Unit Test Harness

EduPay uses **Unity** with a thin custom runner:

```c
// tests/runner.c
#include "unity.h"

extern void test_settlement_usd(void);
extern void test_settlement_jpy(void);

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_settlement_usd);
    RUN_TEST(test_settlement_jpy);
    return UNITY_END();
}
```

Compile:

```sh
cc -Ivendor/unity -Isrc tests/runner.c \
   tests/test_settlement_usd.c \
   tests/test_settlement_jpy.c \
   src/settlement/multi_currency_settlement.c \
   -o build/tests/settlement_suite
```

---

*Happy hacking, and welcome to EduPay Ledger Academy!*  
*— The Core Engineering Team*
```