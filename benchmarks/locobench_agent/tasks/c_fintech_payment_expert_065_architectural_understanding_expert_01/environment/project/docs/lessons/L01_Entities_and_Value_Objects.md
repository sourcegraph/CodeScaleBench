```markdown
<!--
EduPay Ledger Academy – Internal Curriculum
Lesson: L01 – Entities and Value Objects
Generation Date: 2024-06-11
Author: EduPay Curriculum Team
-->

# L01 — Entities & Value Objects  
_Clean Architecture, Robust Payments, and Pedagogical Design_

---

## 1  Learning Objectives
By the end of this lesson, learners will be able to:

1. Differentiate **Entities** from **Value Objects** in the context of Robert C. Martin’s Clean Architecture.  
2. Implement domain rules as portable, framework-agnostic C code.  
3. Preserve business invariants (e.g., currency integrity, idempotency) via **compile-time** and **run-time** constraints.  
4. Write self-documenting tests that validate domain rules independently of persistence, messaging, or UI concerns.

---

## 2  Domain Story: Tuition Ledger Settlement

> “When a bursar posts a tuition charge in USD and a scholarship fund posts a credit in EUR, the *money* being transferred is a **Value Object** while the *student ledger* that owns the business identity is an **Entity**.”

| Event | Aggregate Root | Invariant Enforced |
|-------|---------------|--------------------|
| `POST_TUITION` | `StudentLedger` | `balance ≥ 0` after scholarships applied |
| `APPLY_SCHOLARSHIP` | `StudentLedger` | `currency(credit) = currency(debit)` during netting |
| `ISSUE_REFUND` | `Disbursement` | `refund ≤ overpayment` |

---

## 3  Why Entities & Value Objects in C?

C lacks classes, but *behavior + data* can still be modeled explicitly:

* **Entity** ⇒ `struct` + identifier + mutation functions  
* **Value Object** ⇒ `struct` + no identity + pure functions + immutability contract

The result is *tight business logic* that can be lifted into any infrastructure (SQL, Kafka, REST, gRPC) with zero code changes.

---

## 4  Implementation Walkthrough

### 4.1  Value Object: `Money`

`money.h`
```c
#ifndef EDU_PAY_MONEY_H
#define EDU_PAY_MONEY_H

#include <stdint.h>
#include <stdbool.h>

/* SAFETY: ISO-4217 currency codes are max 3 chars + NUL */
#define CURRENCY_CODE_MAX 4

/* Compile-time checks for common type mis-use */
_Static_assert(sizeof(long long) >= 8, "int64_t not 64-bit on this platform");

/**
 * A Value Object representing a monetary amount in a specific currency.
 * Immutable by convention—never expose writable fields outside this header.
 */
typedef struct {
    int64_t amount;                    /* In *minor* units (e.g., cents) */
    char    currency[CURRENCY_CODE_MAX];
} Money;

/* Constructors */
Money money_from_minor(int64_t amount, const char *iso4217);
Money money_from_major(double major_units, const char *iso4217);

/* Semantic operations */
Money money_add(Money a, Money b);
Money money_sub(Money a, Money b);
bool  money_eq(Money a, Money b);
bool  money_currency_eq(Money a, Money b);

/* Serialization helpers */
int   money_to_string(Money m, char *buf, size_t buf_sz);

#endif /* EDU_PAY_MONEY_H */
```

`money.c`
```c
#include "money.h"
#include <stdio.h>
#include <string.h>
#include <math.h>

static bool is_valid_currency(const char *code) {
    return code && strlen(code) == 3;
}

Money money_from_minor(int64_t amount, const char *iso4217) {
    Money m = { .amount = amount, .currency = {0} };
    if (!is_valid_currency(iso4217)) {
        /* Fallback to “XXX” per ISO 4217 private-use */
        strncpy(m.currency, "XXX", sizeof(m.currency));
    } else {
        strncpy(m.currency, iso4217, sizeof(m.currency));
    }
    return m;
}

Money money_from_major(double major_units, const char *iso4217) {
    /* Guard against floating-point precision loss */
    double rounded = round(major_units * 100.0);
    return money_from_minor((int64_t)rounded, iso4217);
}

bool money_currency_eq(Money a, Money b) {
    return strncmp(a.currency, b.currency, CURRENCY_CODE_MAX) == 0;
}

Money money_add(Money a, Money b) {
    if (!money_currency_eq(a, b)) {
        /* In production, bubble up an error (enum or errno) */
        return money_from_minor(0, "XXX");
    }
    return money_from_minor(a.amount + b.amount, a.currency);
}

Money money_sub(Money a, Money b) {
    if (!money_currency_eq(a, b)) {
        return money_from_minor(0, "XXX");
    }
    return money_from_minor(a.amount - b.amount, a.currency);
}

bool money_eq(Money a, Money b) {
    return money_currency_eq(a, b) && a.amount == b.amount;
}

int money_to_string(Money m, char *buf, size_t buf_sz) {
    /* Example: “USD 123.45” */
    return snprintf(buf, buf_sz, "%.3s %lld.%02lld",
                    m.currency,
                    (long long)(m.amount / 100),
                    (long long)(llabs(m.amount % 100)));
}
```

Unit test excerpt (CMocka):
```c
#include <stdarg.h>
#include <cmocka.h>
#include "money.h"

static void test_money_addition(void **state) {
    Money a = money_from_minor(1000, "USD"); /* $10.00 */
    Money b = money_from_minor(255,  "USD"); /*  $2.55 */
    Money c = money_add(a, b);

    assert_true(money_eq(c, money_from_minor(1255, "USD")));
}

int main(void) {
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_money_addition),
    };
    return cmocka_run_group_tests(tests, NULL, NULL);
}
```

---

### 4.2  Entity: `StudentLedger`

`student_ledger.h`
```c
#ifndef EDU_PAY_STUDENT_LEDGER_H
#define EDU_PAY_STUDENT_LEDGER_H

#include "money.h"
#include <stdbool.h>

#define LEDGER_ID_MAX 37 /* UUID v4 textual representation + NUL */

/* A domain Entity representing a student’s payable/receivable ledger */
typedef struct {
    char  id[LEDGER_ID_MAX];
    Money balance;         /* Invariant: must never cross business-defined limit */
} StudentLedger;

/* Factory */
StudentLedger ledger_open(const char *uuid, Money opening_balance);

/* Commands (state-changing) */
bool ledger_post_debit(StudentLedger *ledger, Money amount);
bool ledger_post_credit(StudentLedger *ledger, Money amount);

/* Queries (read-only) */
Money ledger_get_balance(const StudentLedger *ledger);

#endif /* EDU_PAY_STUDENT_LEDGER_H */
```

`student_ledger.c`
```c
#include "student_ledger.h"
#include <string.h>

static const int64_t LEDGER_NEG_LIMIT = -1000000LL /* −$10,000.00 */;

StudentLedger ledger_open(const char *uuid, Money opening_balance) {
    StudentLedger l = { .id = {0}, .balance = opening_balance };
    strncpy(l.id, uuid, sizeof(l.id));
    return l;
}

static bool can_apply(StudentLedger *ledger, Money delta) {
    if (!money_currency_eq(ledger->balance, delta)) return false;
    int64_t next = ledger->balance.amount + delta.amount;
    return next >= LEDGER_NEG_LIMIT;
}

bool ledger_post_debit(StudentLedger *ledger, Money amount) {
    if (amount.amount <= 0) return false;          /* negatives not allowed */
    Money delta = money_from_minor(-amount.amount, amount.currency);
    if (!can_apply(ledger, delta)) return false;
    ledger->balance = money_add(ledger->balance, delta);
    return true;
}

bool ledger_post_credit(StudentLedger *ledger, Money amount) {
    if (amount.amount <= 0) return false;
    if (!can_apply(ledger, amount)) return false;
    ledger->balance = money_add(ledger->balance, amount);
    return true;
}

Money ledger_get_balance(const StudentLedger *ledger) {
    return ledger->balance;
}
```

---

## 5  Exercise: Refactor “Micro-credential Disbursement”

Use the patterns above to migrate the `MicroCredentialAward` prototype into a full Entity/Value-object pair:

1. Value Object: `CredentialId` (hash + namespace)  
2. Entity: `AwardLog` (identity = composite key `<student_id, credential_id>`)  
3. Ensure idempotent re-processing when the **Saga Pattern demonstration mode** triggers a retry.

---

## 6  Common Pitfalls

* Treating ISO-4217 as an `enum` hard-codes compile-time logic. Prefer string constants until a code-gen step is available.  
* Storing `double` inside `Money` leads to *round-trip* errors; always use integer minor units.  
* Omitting currency comparison in `money_add` causes silent multi-currency netting errors that surface during reconciliation.

---

## 7  Further Reading

* Evans, E. _Domain-Driven Design_ – Chapters 2 & 6  
* Fowler, M. _Patterns of Enterprise Application Architecture_ – Money Pattern  
* Martin, R. C. _Clean Architecture_ – Chapter 20 “Entities”  

---

_Finish Lesson L01._

```