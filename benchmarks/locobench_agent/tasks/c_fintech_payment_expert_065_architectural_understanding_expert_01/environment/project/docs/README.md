```markdown
# EduPay Ledger Academy  
*Fin-Tech Payment Rails for Higher-Education & Ed-Tech Providers*

[![CI](https://github.com/EduPayLedgerAcademy/fintech_payment/actions/workflows/ci.yml/badge.svg)](https://github.com/EduPayLedgerAcademy/fintech_payment/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/EduPayLedgerAcademy/fintech_payment)](LICENSE)
[![Coverage](https://img.shields.io/codecov/c/github/EduPayLedgerAcademy/fintech_payment)](https://codecov.io/gh/EduPayLedgerAcademy/fintech_payment)

EduPay Ledger Academy (ELA) is a production-grade payment platform written in C and organized with Robert C. Martin’s Clean Architecture.  
Designed as a “living textbook,” ELA enables professors to teach modern back-end patterns—Saga, CQRS/Event-Sourcing, Audit Trail, Security-by-Design—while students operate a real-world payment system tailored for bursars, scholarship funds, and online course marketplaces.

---

## ✨ Key Features
| Domain Context   | Highlighted Capability | Clean-Architecture Layer |
|------------------|------------------------|--------------------------|
| Admissions       | FERPA-aware KYC        | `domain/kyc`             |
| Bursar           | Multi-Currency Ledger  | `domain/ledger`          |
| Financial-Aid    | Fraud Detection ML     | `application/fraud`      |
| Continuing-Ed    | Saga Rollback Labs     | `application/saga`       |

* PCI-DSS & PSD2 compliant tokenization  
* Immutable audit logs for coursework on regulatory reporting  
* Hot-swappable persistence adapters (SQLite, PostgreSQL, MongoDB)  

---

## 📂 Repository Map
```
EduPayLedgerAcademy/
├── cmd/                 # CLI entrypoints
├── configs/             # YAML/JSON configuration files
├── docs/                # Markdown teaching material (← you are here)
├── internal/
│   ├── application/     # Use-cases, orchestrators
│   ├── domain/          # Enterprise business rules (pure C)
│   ├── infrastructure/  # Gateways: DB, message broker, HTTP
│   └── tests/           # BDD scenarios & unit tests (CMocka)
├── scripts/             # Dev-Ops utilities
└── Makefile             # One-command build
```

---

## 🚀 Quick-Start

### 1. Dependencies
* `gcc` ≥ 11 or `clang` ≥ 13  
* `cmake` ≥ 3.20  
* `libpq` (optional: PostgreSQL adapter)  
* `openssl` ≥ 1.1 (TLS & tokenization)  

### 2. Build & Run
```bash
# Clone recursively to fetch lesson submodules
git clone --recurse-submodules https://github.com/EduPayLedgerAcademy/fintech_payment.git
cd fintech_payment

# Configure build
cmake -B build -DCMAKE_BUILD_TYPE=Release

# Compile + run unit tests
cmake --build build --target all
ctest --test-dir build --output-on-failure

# Start the bursar micro-service with SQLite in memory
./build/bin/ela-bursar --config ./configs/dev.sqlite.yml
```

### 3. Saga Pattern Demo
```bash
# Terminal 1 – start all services
docker compose up --build

# Terminal 2 – inject network failures every 15 s
watch -n 15 'docker compose kill --signal=SIGSTOP ela-ledger'

# Terminal 3 – submit tuition payment
scripts/demo/enroll_student.sh  --student-id 42 --amount 5500 --currency USD
```
Watch the output logs for compensating transactions as the Saga orchestrator rewinds the workflow.

---

## 🧩 Embedded Lesson Snippet

Below is an abridged excerpt of the **multi-currency ledger** domain model.  
The full source lives in `internal/domain/ledger`.

```c
/**
 * ledger_entry.h
 * Core immutable record for double-entry bookkeeping.
 *
 * Business Invariant:
 *   1. debit + credit == 0
 *   2. currency must equal ISO-4217 alpha-3 code
 *   3. timestamp is always UTC
 */
#ifndef LEDGER_ENTRY_H
#define LEDGER_ENTRY_H

#include <stdint.h>
#include <time.h>

typedef struct {
    char        journal_id[36];   /* UUID v4 */
    char        account_id[36];   /* UUID v4 */
    int64_t     debit;            /* minor units (e.g., cents) */
    int64_t     credit;           /* minor units */
    char        currency[4];      /* "USD", "EUR", … */
    time_t      posted_at;        /* seconds since epoch */
} ledger_entry_t;

/* Validation errors */
typedef enum {
    LEDGER_OK = 0,
    LEDGER_ERR_BALANCE,
    LEDGER_ERR_CURRENCY,
    LEDGER_ERR_TIME_TRAVEL
} ledger_error_t;

/**
 * validate_entry
 * Ensures all invariants hold.
 *
 * Returns:
 *   LEDGER_OK on success, otherwise reason for failure.
 */
ledger_error_t validate_entry(const ledger_entry_t *entry);

#endif /* LEDGER_ENTRY_H */
```

```c
/* ledger_entry.c */
#include "ledger_entry.h"
#include <string.h>

static int is_iso_4217(const char *code) {
    return strlen(code) == 3 &&
           code[0] >= 'A' && code[0] <= 'Z' &&
           code[1] >= 'A' && code[1] <= 'Z' &&
           code[2] >= 'A' && code[2] <= 'Z';
}

ledger_error_t validate_entry(const ledger_entry_t *e) {
    if (e->debit + e->credit != 0)          return LEDGER_ERR_BALANCE;
    if (!is_iso_4217(e->currency))          return LEDGER_ERR_CURRENCY;
    if (e->posted_at > time(NULL))          return LEDGER_ERR_TIME_TRAVEL;
    return LEDGER_OK;
}
```

These files illustrate how **domain rules remain framework-agnostic**.  
Swapping SQLite for PostgreSQL or adding a REST facade does not change this header or implementation.

---

## 🛡️ Security by Design

1. **Tokenization Layer**: PAN & PII never persist in clear-text.  
2. **Defense-in-Depth**: each micro-service runs with least-privilege containers.  
3. **Static & Dynamic Analysis**:  
   * `clang-tidy` & `cppcheck` during CI  
   * OWASP ZAP tests on REST endpoints  
4. **Compliance Readiness**: PCI-DSS v4 SAQ-D templates included in `/compliance`.

---

## 🧑‍💻 Contributing

We happily accept pull requests that reinforce educational value **and** production rigor.

1. Fork → feature branch (`git switch -c feat/awesome_lesson`)  
2. Follow the existing style:  
   * `clang-format -i $(git ls-files '*.c' '*.h')`  
   * Document header files thoroughly; they are part of the curriculum.  
3. Ensure **100 % test coverage** for new domain logic (`make coverage`).  
4. Open PR with “Lesson Plan” section describing what students learn.

---

## 👩‍🏫 Maintainer Cheat-Sheet

| Task                       | Command                                              |
|----------------------------|------------------------------------------------------|
| Run integration tests      | `make docker-test`                                   |
| Generate API docs (Doxygen)| `make docs`                                          |
| Release new version        | `scripts/release.sh vX.Y.Z`                          |
| Clean build artifacts      | `make clean && rm -rf build coverage/`               |

---

## 📜 License
EduPay Ledger Academy is licensed under the Apache License 2.0.  
See `LICENSE` for the full text.

Happy hacking & teaching! 🚀
```