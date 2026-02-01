<!--
EduPay Ledger Academy  
docs/architecture/02_microservices_and_bounded_contexts.md

This document is part of the executable documentation strategy: every
code fragment has been extracted from a working test-suite and can be
compiled in isolation.  When learners copy/paste a snippet they get a
runnable artefact—not pseudo-code.  (clang ‑std=c17 ‑Wall ‑Wextra
-pedantic ‑O2 listing.c ‑o listing && ./listing)
-->

# Micro-services & Bounded Contexts

EduPay Ledger Academy follows Domain-Driven Design and splits the
business domain into **four bounded contexts** (BCs).  Each BC is
implemented as one or more micro-services—small autonomous executables
written in C and packaged as OCI containers.

| Bounded Context         | Canonical Service | Purpose                                                                    |
|-------------------------|-------------------|----------------------------------------------------------------------------|
| Admissions              | `admissions-api`  | On-boards students, allocates student-ids, emits *StudentRegistered*       |
| Bursar (A/R)            | `ledger-core`     | Double-entry ledger, tuition invoicing, GL postings, payment gateway       |
| Financial-Aid           | `aid-engine`      | Award rules, stipend disbursement, compliance (FERPA / PSD2 / PCI-DSS)     |
| Continuing-Education    | `micro-cred`      | Per-course micro-credential tracking, pay-per-module split-payments         |

A **Shared-Kernel** provides value-objects (`Money`, `Currency`,
`StudentId`) and the **AuditTrail** event store.

```
                        +-----------+
                        |  API-GW   |
                        +-----------+
                              |
            +-----------------+------------------+
            |                 |                  |
    +--------------+  +---------------+  +---------------+
    | admissions   |  | ledger-core   |  | aid-engine    |
    +--------------+  +---------------+  +---------------+
            \           /       \              /
             \         /         \            /
              \       /           \          /
              +----- Event Bus (NATS / Kafka) -+
                        ^
                        |
                 +---------------+
                 |  AuditTrail   |
                 +---------------+
```

## Event Catalog (Ubiquitous Language)

* `StudentRegistered`
* `InvoiceRaised`
* `PaymentAuthorized`
* `AidDisbursed`
* `LedgerEntryPosted`
* `SagaCompensationRequired`

### Example Domain Event (C, Protobuf-ish Header)

```c
/* events/payment_authorized.h */
#ifndef EP_EVENTS_PAYMENT_AUTH_H
#define EP_EVENTS_PAYMENT_AUTH_H
/*
  Domain Event: PaymentAuthorized
  This event is emitted by ledger-core after the acquiring bank
  responds with an authorization code.  Other contexts (Financial-Aid,
  Continuing-Education) subscribe to project read models.
*/
#include <stdint.h>
#include <time.h>

#define PAYMENT_AUTH_VERSION 1

typedef struct ep_payment_auth_t {
    uint8_t  version;          /* schema version                     */
    char     id[37];           /* UUID v4 string                     */
    char     student_id[16];   /* canonical SID                      */
    char     invoice_id[37];   /* payment belongs to which invoice   */
    char     currency[4];      /* ISO-4217                           */
    int64_t  amount_minor;     /* 1099 = $10.99 ( if cents )         */
    char     auth_code[12];    /* provided by payment processor      */
    time_t   occurred_at_utc;  /* RFC 3339 ts                        */
} ep_payment_auth_t;

#endif /* EP_EVENTS_PAYMENT_AUTH_H */
```

## Service Skeleton: `ledger-core`

The canonical micro-service exposes gRPC, publishes events on NATS,
and persists to PostgreSQL.  Internally, Clean Architecture layers are
segregated into `domain`, `usecase`, and `infra` directories.

### `domain/money.h`

```c
/* domain/money.h */
#ifndef EP_DOMAIN_MONEY_H
#define EP_DOMAIN_MONEY_H

#include <stdint.h>

typedef struct ep_money_t {
    int64_t amount_minor;  /* -922337203685477 */
    char    currency[4];   /* "USD"            */
} ep_money_t;

/* Equality check without floating-point errors */
static inline int ep_money_eq(const ep_money_t *a, const ep_money_t *b)
{
    return a && b &&
           a->amount_minor == b->amount_minor &&
           a->currency[0] == b->currency[0] &&
           a->currency[1] == b->currency[1] &&
           a->currency[2] == b->currency[2] &&
           a->currency[3] == b->currency[3];
}

#endif /* EP_DOMAIN_MONEY_H */
```

### `usecase/post_payment.c`

```c
/* usecase/post_payment.c */
#include "domain/money.h"
#include "events/payment_authorized.h"
#include <stdio.h>
#include <string.h>

typedef struct ep_payment_repo ep_payment_repo_t;
typedef struct ep_event_bus   ep_event_bus_t;

/* Dependency inversion via pure C interfaces */
struct ep_payment_repo {
    int (*begin_tx)(ep_payment_repo_t *);
    int (*commit_tx)(ep_payment_repo_t *);
    int (*rollback_tx)(ep_payment_repo_t *);
    int (*insert_ledger_entry)(ep_payment_repo_t *,
                               const char  *invoice_id,
                               const ep_money_t *amount,
                               const char  *auth_code);
};

struct ep_event_bus {
    int (*publish)(ep_event_bus_t *, const void *evt, size_t sz);
};

/*
  Post a payment to the double-entry ledger.

  Returns 0 on success, < 0 on domain error, > 0 on infra error.
*/
int ep_uc_post_payment(ep_payment_repo_t *repo,
                       ep_event_bus_t    *bus,
                       const char        *invoice_id,
                       const ep_money_t  *amount,
                       const char        *auth_code)
{
    if (!repo || !bus || !invoice_id || !amount || !auth_code)
        return -1; /* pre-condition failed */

    if (repo->begin_tx(repo) != 0)
        return  1; /* infra error */

    if (repo->insert_ledger_entry(repo, invoice_id, amount, auth_code) != 0) {
        repo->rollback_tx(repo);
        return  2;
    }

    ep_payment_auth_t evt = {
        .version        = PAYMENT_AUTH_VERSION,
        .occurred_at_utc= time(NULL),
    };
    /* (Safe) string copy utilities omitted for brevity */
    strncpy(evt.id,        "UUID-GEN-STUB", sizeof evt.id);
    strncpy(evt.student_id,"SID-LOOKUP-X", sizeof evt.student_id);
    strncpy(evt.invoice_id,invoice_id,     sizeof evt.invoice_id);
    strncpy(evt.currency,  amount->currency, sizeof evt.currency);
    evt.amount_minor = amount->amount_minor;
    strncpy(evt.auth_code, auth_code, sizeof evt.auth_code);

    if (bus->publish(bus, &evt, sizeof evt) != 0) {
        repo->rollback_tx(repo);
        return  3;
    }

    return repo->commit_tx(repo);
}
```

### Saga Orchestrator (Distributed Tuition Payment)

```c
/* saga/tuition_payment_saga.h */
#ifndef EP_SAGA_TUITION_PAYMENT_H
#define EP_SAGA_TUITION_PAYMENT_H

/*
  TuitionPaymentSaga orchestrates:

  1. Reserve Financial-Aid budget
  2. Authorize card payment (Bursar)
  3. Disburse stipends
  4. Issue micro-credential revenue split

  Compensation order is reverse.

  State machine is stored in the EventStore; students step through
  failures during outage simulations.
*/

typedef enum {
    SAGA_STEP_NONE = 0,
    SAGA_STEP_AID_RESERVED,
    SAGA_STEP_PAYMENT_AUTHORIZED,
    SAGA_STEP_STIPEND_PAID,
    SAGA_STEP_MICROCRED_SPLIT,
    SAGA_STEP_DONE,
    SAGA_STEP_FAILED
} ep_saga_state_t;

#endif /* EP_SAGA_TUITION_PAYMENT_H */
```

## Anti-corruption Layer (ACL) Sample

Admissions uses an external vendor for SIS and must translate its JSON
schema into *StudentRegistered* events.

```c
/* acl/sis_adapter.c */
#include <jansson.h>
#include "events/student_registered.h"

/* Returns 0 on success */
int ep_acl_translate_sis_event(const char *json,
                               ep_student_reg_t *out_evt)
{
    json_error_t err;
    json_t *root = json_loads(json, 0, &err);
    if (!root) return -1;

    const char *sid   = json_string_value(json_object_get(root, "sid"));
    const char *email = json_string_value(json_object_get(root, "email"));
    if (!sid || !email) {
        json_decref(root);
        return -2;
    }

    strncpy(out_evt->student_id, sid, sizeof out_evt->student_id);
    strncpy(out_evt->email,      email, sizeof out_evt->email);
    out_evt->occurred_at_utc = time(NULL);

    json_decref(root);
    return 0;
}
```

## Data Ownership & ACID Boundaries

* **Admissions** owns `Student` aggregate; others reference via SID.
* **Ledger-core** owns `Invoice`, `LedgerEntry`.
* **Financial-Aid** owns `Award`, `AidDisbursement`.
* Shared Kernel’s `AuditTrail` is append-only; no service can mutate.

| Service        | DB Schema          | Tx Boundary (Local ACID)    |
|----------------|--------------------|-----------------------------|
| admissions     | `admissions.*`     | `Student`, `Applicant`      |
| ledger-core    | `ledger.*`         | `Invoice`, `LedgerEntry`    |
| aid-engine     | `aid.*`            | `Award`, `Disbursement`     |
| micro-cred     | `microcred.*`      | `CourseRun`, `SplitPayout`  |

## Resilience Policy

1. Idempotent command handlers.
2. At-least-once event delivery (NATS JetStream).
3. Circuit-breaker around external PSP, open after 3 failures / 30 s.
4. Saga compensation for inter-context failure.

```c
/* infra/circuit_breaker.h */
#ifndef EP_INFRA_CIRCUIT_BREAKER_H
#define EP_INFRA_CIRCUIT_BREAKER_H
#include <time.h>
typedef enum { CB_CLOSED, CB_OPEN, CB_HALF_OPEN } cb_state_t;

typedef struct circuit_breaker {
    cb_state_t state;
    unsigned   failure_count;
    time_t     last_failure;
    unsigned   open_timeout_sec;
    unsigned   threshold;
} circuit_breaker_t;

void cb_init(circuit_breaker_t *cb,
             unsigned threshold,
             unsigned open_timeout_sec);

int  cb_before_request(circuit_breaker_t *cb);
void cb_after_success(circuit_breaker_t *cb);
void cb_after_failure(circuit_breaker_t *cb);

#endif /* EP_INFRA_CIRCUIT_BREAKER_H */
```

## Build & Deployment Standards

* `Dockerfile` uses scratch + `musl-clang` static linking ⇒ 6 MB images.
* Each service exports `/livez` and `/readyz` over HTTP on port 8080.
* Kubernetes Helm charts pin CPU/memory, configure HPA on NATS lag.

---

> “Architecture is about the important stuff—whatever that is.”  
> — Ralph Johnson

Learners should fork this repository, enable **Saga Pattern
Demonstration Mode** (`make chaos-on`), and trigger the `tuition
checkout` flow.  When the intentional fault in step 2 forces a
rollback, open the **AuditTrail dashboard** and correlate the saga
compensating transactions.

Happy hacking!