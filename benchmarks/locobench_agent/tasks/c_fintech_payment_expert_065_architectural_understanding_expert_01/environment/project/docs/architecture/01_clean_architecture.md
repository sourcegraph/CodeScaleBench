```markdown
# EduPay Ledger Academy  
### docs/architecture/01_clean_architecture.md  
*(Applies to all micro-services in `fintech_payment` repository)*  

---

## 1. What is “Clean Architecture” in C?

Robert C. Martin’s Clean Architecture separates **business rules** from **delivery mechanisms** so that changes to frameworks, databases, or user interfaces have **zero ripple effect** on the core domain.

```
 ┌──────────────────────────────────────┐
 │              Outer Layer            │
 │ ┌──────────┐  ┌────────────┐        │
 │ │  gRPC    │  │  REST API  │ ...    │
 │ └──────────┘  └────────────┘        │
 │              Frameworks             │
 └────────────────────┬────────────────┘
                      │
 ┌────────────────────▼────────────────┐
 │        Interface Adapters           │
 │  Repositories ▸  Message Brokers    │
 │  Presenters    Validators           │
 └────────────────────┬────────────────┘
                      │
 ┌────────────────────▼────────────────┐
 │            Use-Case Layer           │
 │  Payment  Settlement  Fraud Check   │
 │  Saga Coordination  CQRS Commands   │
 └────────────────────┬────────────────┘
                      │
 ┌────────────────────▼────────────────┐
 │            Entity Layer             │
 │   Currency    Account    Ledger     │
 │   Domain Events  Policies  Rules    │
 └──────────────────────────────────────┘
```

* Dependencies point **inward** only.  
* The **Entity Layer** is pure C (`-std=c17`, no libc exceptions).  
* **Use-Cases** depend only on entities and “port” abstractions.  
* **Interface Adapters** hold the “driver” or “driven” implementations (e.g., PostgreSQL-backed repository).  
* **Frameworks** are plugins that can be swapped out during coursework.

---

## 2. Directory Conventions

```
fintech_payment/
├── admissions/                   # Micro-service BC
│   ├── entity/                   # Enterprise-wide kernel
│   │   └── student_account.h
│   ├── use_case/
│   │   └── enroll_student.c
│   ├── interface_adapter/
│   │   └── repo_postgres.c
│   └── framework/
│       └── grpc_server.c
├── bursar/
│   └── ...
├── libs/                         # Re-usable cross-cutting libs
│   ├── event_sourcing/
│   ├── sagas/
│   └── logging/
└── docs/architecture/
    └── 01_clean_architecture.md  # ← you are here
```

---

## 3. Golden Rules

1. An **inner layer** must **never** include headers from an **outer layer**.  
2. Abstractions (pure `*.h`) belong **inside**; implementations (`*.c`) live **outside**.  
3. Cross-cutting concerns (logging, tracing) enter via **dependency injection**.  

---

## 4. Minimal Compile-Time Contract Example

Below is a fully buildable snippet demonstrating how the Bursar service authorizes a payment while obeying the dependency rule.  

### 4.1 Entity (`currency.h`)

```c
#ifndef EDU_PAY_ENTITY_CURRENCY_H
#define EDU_PAY_ENTITY_CURRENCY_H

#include <stdint.h>

/**
 * Simple 3-letter ISO-4217 currency code.
 * Kept POD so that it may be persisted via Event Sourcing with
 * direct `memcpy` into the append-only log.
 */
typedef struct {
    char code[3];     // e.g., "USD", "EUR"
} Currency;

static inline Currency currency_from(const char iso[3]) {
    return (Currency){ .code = { iso[0], iso[1], iso[2] } };
}

#endif /* EDU_PAY_ENTITY_CURRENCY_H */
```

### 4.2 Use-Case Port (`payment_authorizer_port.h`)

```c
#ifndef EDU_PAY_USE_CASE_PAYMENT_AUTHORIZER_PORT_H
#define EDU_PAY_USE_CASE_PAYMENT_AUTHORIZER_PORT_H

#include "../entity/currency.h"
#include <stdint.h>
#include <stdbool.h>

typedef struct {
    uint64_t account_id;
    uint64_t merchant_id;
    uint64_t cents;
    Currency currency;
} PaymentAuthorizationRequest;

typedef struct {
    bool     approved;
    uint64_t authorization_code; // zero if declined
    const char *decline_reason;  // NULL if approved
} PaymentAuthorizationResponse;

/* “Driver” port — implemented by outer layer (e.g., REST handler) */
typedef PaymentAuthorizationResponse
(*PaymentAuthorizer_Handle)(const PaymentAuthorizationRequest *req);

#endif /* EDU_PAY_USE_CASE_PAYMENT_AUTHORIZER_PORT_H */
```

### 4.3 Use-Case Interactor (`payment_authorizer.c`)

```c
#include "payment_authorizer.h"
#include "ports/payment_gateway_port.h"
#include "../entity/currency.h"
#include <stdio.h>

PaymentAuthorizationResponse
payment_authorizer_execute(const PaymentAuthorizationRequest *req,
                           PaymentGatewayPort gateway,
                           AuditTrailPort audit)
{
    /* Business rule: bursar rejects non-USD tuition for domestic campus */
    if (req->currency.code[0]!='U' || req->currency.code[1]!='S' || req->currency.code[2]!='D') {
        audit.emit("PAYMENT_DECLINED_NON_USD", req->account_id);
        return (PaymentAuthorizationResponse){
            .approved = false,
            .authorization_code = 0,
            .decline_reason = "Domestic tuition must be paid in USD"
        };
    }

    /* Delegate to abstraction */
    GatewayAuthorization ga = gateway.authorize(req);
    audit.emit(ga.approved ? "PAYMENT_APPROVED" : "PAYMENT_DECLINED", req->account_id);

    return (PaymentAuthorizationResponse){
        .approved = ga.approved,
        .authorization_code = ga.approved ? ga.auth_code : 0,
        .decline_reason = ga.approved ? NULL : ga.reason
    };
}
```

### 4.4 Outer-Layer Implementation (`framework/payment_gateway_stripe.c`)

```c
#include "ports/payment_gateway_port.h"
#include "third_party/stripe/stripe.h"   // <— framework boundary
#include <string.h>

static GatewayAuthorization stripe_authorize(const PaymentAuthorizationRequest *req)
{
    StripeCharge charge = stripe_charge_create(
        req->account_id, req->merchant_id, req->cents, req->currency.code);

    if (charge.state == STRIPE_CHARGE_APPROVED) {
        return (GatewayAuthorization){
            .approved = true,
            .auth_code = charge.id,
            .reason = NULL
        };
    }
    return (GatewayAuthorization){
        .approved = false,
        .auth_code = 0,
        .reason = stripe_failure_reason(charge.state)
    };
}

PaymentGatewayPort payment_gateway_new_stripe(void)
{
    return (PaymentGatewayPort){ .authorize = stripe_authorize };
}
```

Notice:  
• `payment_authorizer.c` imports **only ports & entities**.  
• `stripe.h` never leaks into use-case headers.  

---

## 5. Event Sourcing & CQRS Projection

Each state-changing command (e.g., `AuthorizePayment`) yields an immutable event (`PaymentAuthorized`).  
Events serialize using the simple schema-first header `libs/event_sourcing/event.h`. Consumers read the append-only log to build read-models (`bursar_read_db.c`) without polluting write-models.

---

## 6. Saga Pattern Demonstration Mode

When `EDUPAY_SAGA_SIMULATION=1`, orchestrators deliberately inject faults after phase 2 (settlement) to force distributed rollbacks. Students can attach **gdb** to witness compensating transactions generated via the `saga_compensator.c` adapter.

---

## 7. Compliance by Design

• **FERPA**: Personally Identifiable Information (PII) lives exclusively in the **identity** micro-service; other services address students by opaque UUIDs.  
• **PCI-DSS**: PAN never flows into our codebase—only tokens from the payment gateway.  
• **PSD2 / SCA**: Two-factor challenge responses are handled by the outer‐layer `framework/oauth_device.c`, driving callbacks into the use-case port `sca_verification_port.h`.

---

## 8. How to Introduce a New Database

1. Create `postgres_student_account_repo.c` in the Interface Adapter layer.  
2. Implement the `StudentAccountRepositoryPort` functions.  
3. Wire it into the composition root (`main.c`) via dependency injection.  
4. No re-compilation required for Entity/Use-Case code. Run unit tests:  

```bash
$ make test ENTITY=student_account
```

---

## 9. Coding Standards

1. `-std=c17`, compile with `-Wall -Wextra -Werror -pedantic`.  
2. No exceptions; functions return error codes or `Result<T>` style structs.  
3. Header guards use `EDU_PAY_<PATH>_<FILE>_H`.  
4. Each public header includes a **single-sentence** Doxygen comment.  

---

## 10. Further Reading

* Robert C. Martin — “Clean Architecture”  
* Eric Evans — “Domain-Driven Design”  
* Martin Fowler — “Patterns of Enterprise Application Architecture”  

---

> “The only sustainable way to keep software from rotting is to build it so that you can change any one part without impacting the rest.”  
> — EduPay Ledger Academy Curriculum

```
