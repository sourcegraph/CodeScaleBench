/*
 * EduPay Ledger Academy
 * -------------------------------------------------------------
 * Module  : Financial-Aid Service ‑ Use-Cases
 * File    : disburse_stipend_saga.h
 * Author  : EduPay Core Team
 *
 * Synopsis:
 *   Header-only, production-grade implementation of a Saga-Pattern
 *   orchestration for disbursing student stipends.  The code sits in the
 *   Use-Case layer (Clean Architecture) and has zero dependencies on any
 *   concrete frameworks, I/O, or persistence technology.  All side-effects
 *   (ledger writes, payment network calls, etc.) are injected via function
 *   pointers, making the saga deterministic and unit-testable.
 *
 *   ┌───────────────────────────────────────────────────────────┐
 *   │  FinancialAid::DisburseStipendSaga                       │
 *   │-----------------------------------------------------------│
 *   │ validate_eligibility()   ─┐                               │
 *   │ reserve_budget()          ├─► initiate_transfer() ─┐      │
 *   │ record_ledger()           │                         │      │
 *   │ publish_event()           │                         │      │
 *   └───────────────────────────┘                         │      │
 *                                │                        │      │
 *                                ▼                        │      │
 *                         compensation() ◄────────────────┘      │
 *     (release_budget, reverse_transfer, ledger_reversal)        │
 *   └───────────────────────────────────────────────────────────┘
 *
 *   NOTE:
 *     1.  Header-only so that professors can #include it in toy
 *         command-line drivers or embed it in micro-services without
 *         tweaking build systems.
 *     2.  Thread-safe: no global / static mutable state.
 *     3.  Compatible with C89+ (but uses stdint.h & stdbool.h).
 */

#ifndef EDUPAY_LEDGER_ACADEMY_FINANCIAL_AID_DISBURSE_STIPEND_SAGA_H
#define EDUPAY_LEDGER_ACADEMY_FINANCIAL_AID_DISBURSE_STIPEND_SAGA_H

/* -------------------------------------------------------------------------- */
/*  Standard Library Includes                                                 */
/* -------------------------------------------------------------------------- */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <time.h>

/* -------------------------------------------------------------------------- */
/*  Domain Types                                                              */
/* -------------------------------------------------------------------------- */

/*
 * ISO-4217 three-letter currency code.  Stored as a fixed-width char[4]
 * where index 3 must be '\0'.
 */
typedef char iso_currency_code_t[4];

/* Forward-declaration for opaque correlation identifiers (UUID, ULID, etc.). */
typedef struct {
    uint8_t bytes[16];
} correlation_id_t;

/* -------------------------------------------------------------------------- */
/*  Request DTO                                                               */
/* -------------------------------------------------------------------------- */
typedef struct {
    uint64_t         student_id;
    uint64_t         stipend_cents;
    iso_currency_code_t currency;
    char             term[8];         /* e.g., "2024SP" */
    correlation_id_t correlation_id;
    time_t           requested_at_utc;
} stipend_disbursement_request_t;

/* -------------------------------------------------------------------------- */
/*  Error Handling                                                            */
/* -------------------------------------------------------------------------- */
typedef enum {
    SAGA_OK = 0,
    SAGA_ERR_VALIDATION     =  1,
    SAGA_ERR_INSUFFICIENT   =  2,
    SAGA_ERR_TRANSFER_FAIL  =  3,
    SAGA_ERR_LEDGER_FAIL    =  4,
    SAGA_ERR_EVENT_BUS      =  5,
    SAGA_ERR_COMPENSATION   =  6,
    SAGA_ERR_INTERNAL       = 99
} saga_error_code_t;

typedef struct {
    saga_error_code_t code;
    char              message[128]; /* ASCII diagnostics. */
} saga_error_t;

/* Convenience macro for initializing an empty saga_error_t */
#define SAGA_ERROR_INIT() (saga_error_t){ .code = SAGA_OK, .message = "" }

/* -------------------------------------------------------------------------- */
/*  Saga Orchestration – Callback VTable                                      */
/* -------------------------------------------------------------------------- */
/*
 *  The saga never performs I/O directly.  All side-effects are routed through
 *  a set of callbacks supplied by the calling application/service.  Each
 *  callback must be idempotent because the saga might retry crashed steps.
 *
 *  Every callback returns `true` on success.  On failure it returns `false`
 *  and must populate `err_out`.
 */

typedef bool (*validate_eligibility_fn)(
        const stipend_disbursement_request_t *req,
        saga_error_t                         *err_out);

typedef bool (*reserve_budget_fn)(
        const stipend_disbursement_request_t *req,
        uint64_t                             *reservation_id_out,
        saga_error_t                         *err_out);

typedef bool (*release_budget_fn)(
        uint64_t       reservation_id,
        saga_error_t  *err_out);

typedef bool (*initiate_transfer_fn)(
        const stipend_disbursement_request_t *req,
        uint64_t                             *network_tx_id_out,
        saga_error_t                         *err_out);

typedef bool (*reverse_transfer_fn)(
        uint64_t       network_tx_id,
        saga_error_t  *err_out);

typedef bool (*record_ledger_entry_fn)(
        const stipend_disbursement_request_t *req,
        const char                           *entry_type,
        uint64_t                              related_id, /* reservation or tx id */
        saga_error_t                         *err_out);

typedef bool (*publish_domain_event_fn)(
        const stipend_disbursement_request_t *req,
        const char                           *event_name,
        saga_error_t                         *err_out);

/* -------------------------------------------------------------------------- */
/*  VTable Container                                                          */
/* -------------------------------------------------------------------------- */
typedef struct {
    validate_eligibility_fn   validate_eligibility;
    reserve_budget_fn         reserve_budget;
    release_budget_fn         release_budget;
    initiate_transfer_fn      initiate_transfer;
    reverse_transfer_fn       reverse_transfer;
    record_ledger_entry_fn    record_ledger_entry;
    publish_domain_event_fn   publish_domain_event;
} stipend_disbursement_callbacks_t;

/* Utility macro to check if a pointer in the vtable is missing at runtime. */
#define _CHECK_CB(cb) do {                                                  \
    if ((cb) == NULL) {                                                     \
        if (err_out) {                                                      \
            err_out->code = SAGA_ERR_INTERNAL;                              \
            snprintf(err_out->message, sizeof(err_out->message),            \
                     "Callback missing: %s", #cb);                          \
        }                                                                   \
        return false;                                                       \
    } } while (0)

/* -------------------------------------------------------------------------- */
/*  Saga Public API                                                           */
/* -------------------------------------------------------------------------- */
static inline
bool disburse_stipend_run(
        const stipend_disbursement_request_t   *req,
        const stipend_disbursement_callbacks_t *cb,
        saga_error_t                           *err_out);

/* -------------------------------------------------------------------------- */
/*  Implementation                                                            */
/* -------------------------------------------------------------------------- */
static inline
bool disburse_stipend_run(
        const stipend_disbursement_request_t   *req,
        const stipend_disbursement_callbacks_t *cb,
        saga_error_t                           *err_out)
{
    /* Defensive programming: never trust caller. */
    if (!req || !cb) {
        if (err_out) {
            err_out->code = SAGA_ERR_INTERNAL;
            snprintf(err_out->message, sizeof(err_out->message),
                     "NULL argument(s) received");
        }
        return false;
    }

    uint64_t reservation_id = 0;
    uint64_t network_tx_id  = 0;

    /* ------------------------------------------------------------------ */
    /* 1. Validate eligibility                                            */
    /* ------------------------------------------------------------------ */
    _CHECK_CB(cb->validate_eligibility);
    if (!cb->validate_eligibility(req, err_out)) {
        return false; /* validation errors are final, no compensation needed */
    }

    /* ------------------------------------------------------------------ */
    /* 2. Reserve budget (Financial-Aid allocation ledger)                */
    /* ------------------------------------------------------------------ */
    _CHECK_CB(cb->reserve_budget);
    if (!cb->reserve_budget(req, &reservation_id, err_out)) {
        return false;
    }

    /* ------------------------------------------------------------------ */
    /* 3. Initiate transfer via payment network                           */
    /* ------------------------------------------------------------------ */
    _CHECK_CB(cb->initiate_transfer);
    if (!cb->initiate_transfer(req, &network_tx_id, err_out)) {

        /* ------------------------------------------------------------------
         * Compensation Path #1: release the budget reservation
         * ------------------------------------------------------------------ */
        _CHECK_CB(cb->release_budget);
        saga_error_t cmp_err = SAGA_ERROR_INIT();
        if (!cb->release_budget(reservation_id, &cmp_err)) {
            /* Fatal: both forward step + compensation failed */
            if (err_out && err_out->code == SAGA_OK) {
                *err_out = cmp_err;
            }
            return false;
        }

        return false; /* original error already populated by initiate_transfer */
    }

    /* ------------------------------------------------------------------ */
    /* 4. Record ledger entry (financial book-keeping)                    */
    /* ------------------------------------------------------------------ */
    _CHECK_CB(cb->record_ledger_entry);
    if (!cb->record_ledger_entry(req, "STIPEND_DISBURSEMENT", network_tx_id, err_out)) {

        /* Compensation Path #2: reverse transfer + release budget */
        _CHECK_CB(cb->reverse_transfer);
        _CHECK_CB(cb->release_budget);

        saga_error_t cmp_err1 = SAGA_ERROR_INIT();
        if (!cb->reverse_transfer(network_tx_id, &cmp_err1)) {
            if (err_out && err_out->code == SAGA_OK) *err_out = cmp_err1;
            /* Deliberately fall through to attempt second compensation */
        }

        saga_error_t cmp_err2 = SAGA_ERROR_INIT();
        if (!cb->release_budget(reservation_id, &cmp_err2)) {
            if (err_out && err_out->code == SAGA_OK) *err_out = cmp_err2;
        }

        return false;
    }

    /* ------------------------------------------------------------------ */
    /* 5. Publish domain event (CQRS / Integration-Event)                 */
    /* ------------------------------------------------------------------ */
    _CHECK_CB(cb->publish_domain_event);
    if (!cb->publish_domain_event(req, "StipendDisbursed", err_out)) {

        /* Compensation Path #3: ledger reversal + reverse transfer + release budget */
        _CHECK_CB(cb->record_ledger_entry);
        _CHECK_CB(cb->reverse_transfer);
        _CHECK_CB(cb->release_budget);

        saga_error_t cmp_err = SAGA_ERROR_INIT();
        cb->record_ledger_entry(req, "STIPEND_DISBURSEMENT_REVERSED", network_tx_id, &cmp_err);
        cb->reverse_transfer(network_tx_id, &cmp_err);
        cb->release_budget(reservation_id, &cmp_err);

        return false;
    }

    /* ------------------------------------------------------------------ */
    /* 6. Success!                                                        */
    /* ------------------------------------------------------------------ */
    if (err_out) {
        *err_out = SAGA_ERROR_INIT(); /* reset to success */
    }
    return true;
}

/* -------------------------------------------------------------------------- */
/*  Example: Default No-Op Callbacks for Unit-Testing                         */
/* -------------------------------------------------------------------------- */
#ifdef EDUPAY_STIPEND_SAGA_ENABLE_NOOP_CALLBACKS

#include <string.h>

/* These compile-time helpers allow professors to run the saga in a REPL
 * without wiring external systems.  Each callback prints to stdout and
 * pretends to succeed.
 */

static inline bool noop_validate(const stipend_disbursement_request_t *req, saga_error_t *err) {
    (void)req; (void)err;
    puts("[noop] validate_eligibility");
    return true;
}

static inline bool noop_reserve(const stipend_disbursement_request_t *req,
                                uint64_t *id, saga_error_t *err) {
    (void)req; (void)err;
    puts("[noop] reserve_budget");
    *id = 42;
    return true;
}

static inline bool noop_release(uint64_t id, saga_error_t *err) {
    (void)id; (void)err;
    puts("[noop] release_budget");
    return true;
}

static inline bool noop_transfer(const stipend_disbursement_request_t *req,
                                 uint64_t *id, saga_error_t *err) {
    (void)req; (void)err;
    puts("[noop] initiate_transfer");
    *id = 1337;
    return true;
}

static inline bool noop_reverse(uint64_t id, saga_error_t *err) {
    (void)id; (void)err;
    puts("[noop] reverse_transfer");
    return true;
}

static inline bool noop_ledger(const stipend_disbursement_request_t *req,
                               const char *type, uint64_t rel_id, saga_error_t *err) {
    (void)req; (void)type; (void)rel_id; (void)err;
    puts("[noop] record_ledger_entry");
    return true;
}

static inline bool noop_publish(const stipend_disbursement_request_t *req,
                                const char *name, saga_error_t *err) {
    (void)req; (void)name; (void)err;
    puts("[noop] publish_domain_event");
    return true;
}

static const stipend_disbursement_callbacks_t STIPEND_SAGA_NOOP_CALLBACKS = {
    .validate_eligibility = noop_validate,
    .reserve_budget       = noop_reserve,
    .release_budget       = noop_release,
    .initiate_transfer    = noop_transfer,
    .reverse_transfer     = noop_reverse,
    .record_ledger_entry  = noop_ledger,
    .publish_domain_event = noop_publish
};

#endif /* EDUPAY_STIPEND_SAGA_ENABLE_NOOP_CALLBACKS */

#endif /* EDUPAY_LEDGER_ACADEMY_FINANCIAL_AID_DISBURSE_STIPEND_SAGA_H */
