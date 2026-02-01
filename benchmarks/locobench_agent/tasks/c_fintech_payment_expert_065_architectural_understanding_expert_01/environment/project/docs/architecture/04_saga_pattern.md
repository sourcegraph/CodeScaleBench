```markdown
# EduPay Ledger Academy  
### docs/architecture/04_saga_pattern.md
---
> Version: 1.3  
> Last Reviewed: 2024-05-09  
> Authors: Core Platform Team (@edupay-ledger)  
> Status: ✅ Production  
---

## 1. Why EduPay Uses the Saga Pattern

EduPay processes **millions of distributed, financial micro-transactions** each semester.  
The platform deliberately avoids *single-phase* database transactions because:

* **Micro-services** compose payments from multiple bounded contexts (Admissions, Bursar, Treasury, FX, Fraud).  
* **Heterogeneous data stores** (PostgreSQL, Redis, EventStoreDB) participate in a single business flow.  
* **Resiliency labs** in coursework require controlled failure injection and roll-back.  

A **Saga** slices a long-running business process into a series of *local* ACID transactions plus **compensating steps**.  
If any step fails, the orchestrator triggers rollback actions in **reverse order**, yielding *eventual consistency* without locking global resources.

```
Enrollment_Fee → FX_Conversion → Treasury_Posting → Fraud_Scoring → Receipt_Email
         │                │                │              │
         └────────────────┴────────────────┴──────────────┴─────┐
                       Saga Orchestrator (payment_saga.c)       │
                       • persists state in Audit_Trail          │
                       • broadcasts events over EventBus        │
                       • drives rollbacks on failure ◄──────────┘
```

---

## 2. High-Level Flow

1. **Create** a `payment_saga_t` record in the `audit_trail` stream.  
2. **Send** `SAGA_STEP_BEGIN` for *FX_Conversion* (`fx.c`).  
3. **Local commit** in FX; publish `SAGA_STEP_DONE`.  
4. Orchestrator continues to *Treasury_Posting* (`ledger.c`).  
5. If *Fraud_Scoring* fails, **publish** `SAGA_ABORT`.  
6. Participants receiving `SAGA_ABORT` invoke *compensating* handlers.  
7. Saga ends with `SAGA_ROLLBACK_DONE` or `SAGA_SUCCESS`.

---

## 3. Reference Implementation (C)

All code is kept framework-agnostic, consistent with **Clean Architecture**.  
Dependencies limited to the standard C library (`pthread` for concurrency).

### 3.1. Public Interface – `include/saga.h`

```c
#ifndef EDUPAY_SAGA_H
#define EDUPAY_SAGA_H

#include <stdint.h>
#include <stdbool.h>

/* ---------- Event Bus ---------------------------------------------------- */

typedef enum {
    EVT_SAGA_STEP_BEGIN,
    EVT_SAGA_STEP_DONE,
    EVT_SAGA_ABORT,
    EVT_SAGA_ROLLBACK_DONE,
    EVT_SAGA_SUCCESS
} saga_event_type_t;

typedef struct {
    saga_event_type_t type;
    uint64_t          saga_id;
    const char       *step_name;   /* e.g., "FX_Conversion" */
    void             *payload;     /* opaque domain state   */
} saga_event_t;

/* Subscriber callback signature */
typedef void (*event_handler_f)(const saga_event_t *evt, void *ctx);

/* Registers a handler; returns 0 on success, -1 on error */
int eventbus_subscribe(event_handler_f cb, void *ctx);

/* Broadcasts event to all subscribers; thread-safe */
int eventbus_publish(const saga_event_t *evt);

/* ---------- Saga Orchestrator ------------------------------------------- */

#define SAGA_MAX_STEPS 8
#define SAGA_STEP_NAME_MAX 32

typedef int (*saga_step_f)(uint64_t saga_id, void **payload);
typedef int (*saga_comp_f)(uint64_t saga_id, void *payload);

typedef struct {
    char         name[SAGA_STEP_NAME_MAX];
    saga_step_f  action;
    saga_comp_f  compensate;
} saga_step_def_t;

typedef struct {
    uint64_t        id;
    uint8_t         step_count;
    uint8_t         current;
    saga_step_def_t steps[SAGA_MAX_STEPS];
    bool            aborted;
} payment_saga_t;

/* Initializes a saga with the supplied steps */
void saga_init(payment_saga_t *saga, uint64_t id,
               const saga_step_def_t *steps,
               uint8_t step_count);

/* Executes saga synchronously; returns 0 on success, -1 on failure */
int saga_execute(payment_saga_t *saga);

#endif /* EDUPAY_SAGA_H */
```

### 3.2. Core Implementation – `src/saga.c`

```c
#include "saga.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define BUS_MAX_HANDLERS 16

/* ----------------- Simple In-Process Event Bus -------------------------- */

typedef struct {
    event_handler_f cb;
    void           *ctx;
} handler_entry_t;

static handler_entry_t BUS[BUS_MAX_HANDLERS];
static pthread_mutex_t BUS_LOCK = PTHREAD_MUTEX_INITIALIZER;

int eventbus_subscribe(event_handler_f cb, void *ctx)
{
    pthread_mutex_lock(&BUS_LOCK);
    for (int i = 0; i < BUS_MAX_HANDLERS; ++i) {
        if (BUS[i].cb == NULL) {
            BUS[i].cb  = cb;
            BUS[i].ctx = ctx;
            pthread_mutex_unlock(&BUS_LOCK);
            return 0;
        }
    }
    pthread_mutex_unlock(&BUS_LOCK);
    return -1; /* No slots */
}

int eventbus_publish(const saga_event_t *evt)
{
    pthread_mutex_lock(&BUS_LOCK);
    handler_entry_t handlers[BUS_MAX_HANDLERS];
    memcpy(handlers, BUS, sizeof(handlers));
    pthread_mutex_unlock(&BUS_LOCK);

    for (int i = 0; i < BUS_MAX_HANDLERS; ++i) {
        if (handlers[i].cb)
            handlers[i].cb(evt, handlers[i].ctx);
    }
    return 0;
}

/* ----------------- Saga Orchestration ---------------------------------- */

static void publish_step_event(saga_event_type_t type,
                               const payment_saga_t *saga,
                               const char *step_name,
                               void *payload)
{
    saga_event_t evt = {
        .type      = type,
        .saga_id   = saga->id,
        .step_name = step_name,
        .payload   = payload
    };
    eventbus_publish(&evt);
}

void saga_init(payment_saga_t *s, uint64_t id,
               const saga_step_def_t *steps,
               uint8_t step_count)
{
    memset(s, 0, sizeof(*s));
    s->id         = id;
    s->step_count = step_count > SAGA_MAX_STEPS ? SAGA_MAX_STEPS : step_count;
    memcpy(s->steps, steps, s->step_count * sizeof(saga_step_def_t));
}

static int rollback(payment_saga_t *saga)
{
    for (int i = saga->current; i >= 0; --i) {
        saga_step_def_t *step = &saga->steps[i];
        if (step->compensate) {
            publish_step_event(EVT_SAGA_ABORT, saga, step->name, NULL);
            if (step->compensate(saga->id, NULL) != 0)
                fprintf(stderr, "⚠  Compensation failed at %s\n", step->name);
        }
    }
    saga_event_t done = {
        .type      = EVT_SAGA_ROLLBACK_DONE,
        .saga_id   = saga->id,
        .step_name = "ROLLBACK"
    };
    eventbus_publish(&done);
    return -1;
}

int saga_execute(payment_saga_t *saga)
{
    for (saga->current = 0; saga->current < saga->step_count; ++saga->current) {
        saga_step_def_t *step = &saga->steps[saga->current];

        publish_step_event(EVT_SAGA_STEP_BEGIN, saga, step->name, NULL);

        void *payload = NULL;
        if (step->action(saga->id, &payload) != 0) {
            fprintf(stderr, "❌  Saga %lu failed at step %s\n",
                    saga->id, step->name);
            saga->aborted = true;
            return rollback(saga);
        }

        publish_step_event(EVT_SAGA_STEP_DONE, saga, step->name, payload);
    }

    saga_event_t ok = {
        .type      = EVT_SAGA_SUCCESS,
        .saga_id   = saga->id,
        .step_name = "COMPLETED"
    };
    eventbus_publish(&ok);
    return 0;
}
```

### 3.3. Example Steps – `src/steps_fx.c`, `src/steps_ledger.c`

```c
/* src/steps_fx.c */
#include "saga.h"
#include <stdio.h>

int fx_convert(uint64_t id, void **payload)
{
    (void)payload; /* Not needed for demo */
    printf("💱  FX_Conversion performed for saga %lu\n", id);
    /* simulate success */
    return 0;
}

int fx_reverse(uint64_t id, void *payload)
{
    (void)payload;
    printf("↩  FX_Conversion reversed for saga %lu\n", id);
    return 0;
}
```

```c
/* src/steps_ledger.c */
#include "saga.h"
#include <stdio.h>

int ledger_post(uint64_t id, void **payload)
{
    (void)payload;
    printf("📒  Ledger posting OK for saga %lu\n", id);
    return 0;
}

int ledger_reverse(uint64_t id, void *payload)
{
    (void)payload;
    printf("↩  Ledger posting reversed for saga %lu\n", id);
    return 0;
}
```

### 3.4. Demonstration Driver – `samples/payment_saga.c`

```c
#include "saga.h"
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

/* ---------- Step Implementations --------------------------------------- */
extern int fx_convert(uint64_t, void **);
extern int fx_reverse(uint64_t, void *);

extern int ledger_post(uint64_t, void **);
extern int ledger_reverse(uint64_t, void *);

static int fraud_score(uint64_t id, void **payload)
{
    (void)payload;
    printf("🕵  Fraud scoring started for saga %lu\n", id);

    /* Simulate 30% failure rate for classroom chaos monkeys */
    if (rand() % 10 < 3) {
        fprintf(stderr, "🚨  Fraud scoring FAILED (suspicious)\n");
        return -1;
    }

    printf("✅  Fraud scoring passed\n");
    return 0;
}

static int fraud_reverse(uint64_t id, void *payload)
{
    (void)payload;
    printf("↩  Fraud scoring compensation (unflag) for saga %lu\n", id);
    return 0;
}

/* ---------- Audit Trail Console Subscriber ----------------------------- */
static void audit_logger(const saga_event_t *evt, void *ctx)
{
    (void)ctx;
    const char *type_str[] = {
        "STEP_BEGIN", "STEP_DONE", "ABORT", "ROLLBACK_DONE", "SUCCESS"
    };
    printf("📝  Audit: %s — saga=%lu step=%s\n",
           type_str[evt->type], evt->saga_id, evt->step_name);
}

int main(void)
{
    srand((unsigned)time(NULL));
    eventbus_subscribe(audit_logger, NULL);

    saga_step_def_t steps[] = {
        { "FX_Conversion",   fx_convert,   fx_reverse   },
        { "Ledger_Posting",  ledger_post,  ledger_reverse },
        { "Fraud_Scoring",   fraud_score,  fraud_reverse }
    };

    payment_saga_t saga;
    saga_init(&saga, 42, steps, 3);

    int rc = saga_execute(&saga);
    printf(rc == 0 ? "🎉  Saga completed successfully!\n"
                   : "💔  Saga rolled back.\n");
    return rc;
}
```

Compile & Run:

```bash
gcc -Iinclude src/saga.c src/steps_fx.c src/steps_ledger.c samples/payment_saga.c -lpthread -o bin/payment_saga
./bin/payment_saga
```

Expected terminal output (with occasional induced failure):

```
💱  FX_Conversion performed for saga 42
📒  Ledger posting OK for saga 42
🕵  Fraud scoring started for saga 42
🚨  Fraud scoring FAILED (suspicious)
❌  Saga 42 failed at step Fraud_Scoring
↩  Fraud scoring compensation (unflag) for saga 42
↩  Ledger posting reversed for saga 42
↩  FX_Conversion reversed for saga 42
💔  Saga rolled back.
```

---

## 4. Teaching Notes

* The orchestrator resides **inside** the Payment bounded context, not in an external workflow engine.  
  Code can therefore be debugged with `gdb` by novices.
* Because the event bus is *in-process*, instructors can swap it for a
  real Kafka / NATS adapter during advanced labs without touching business logic.
* Compensations are **idempotent**: every reverse handler can run twice safely,
  a mandatory property in at-least-once delivery environments.

---

## 5. Production Hardening Checklist

- [x] Persist `payment_saga_t` progress to EventStoreDB → replay after crash.  
- [x] Encrypt payloads (`payload_encrypt()`) for PCI-DSS compliance.  
- [x] Emit OpenTelemetry spans for distributed tracing.  
- [ ] Add circuit-breakers around downstream services (coming Q3).  

---

Happy hacking!  
EduPay Ledger Team ✨
```