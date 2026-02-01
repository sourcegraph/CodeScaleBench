/*
 *  EduPay Ledger Academy
 *  ---------------------------------------------------------------------------
 *  Disburse Stipend Saga Use-Case
 *
 *  File:    financial_aid_service/application/use_cases/disburse_stipend_saga.c
 *  License: MIT
 *
 *  Description:
 *      Implements the Saga-pattern orchestration that disburses student
 *      stipends.  The saga coordinates the following participating services:
 *
 *          1. Compliance/KYC          – FERPA-aware identity & sanction checks
 *          2. Payment Gateway         – Reserve + capture funds
 *          3. Ledger Repository       – Immutable, event-sourced ledger entry
 *          4. Stipend Repository      – Aggregate root for stipend domain
 *          5. Event Bus               – Publishes domain & integration events
 *          6. Audit Logger            – Immutable audit trail
 *
 *      Compensating transactions are issued on failure so that the system
 *      remains eventually consistent across micro-services.
 *
 *  ---------------------------------------------------------------------------
 */

#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "domain/models/stipend_request.h"
#include "domain/events/stipend_events.h"

#include "application/ports/repositories/ledger_repository.h"
#include "application/ports/repositories/stipend_repository.h"

#include "application/ports/services/compliance_service.h"
#include "application/ports/services/payment_gateway.h"

#include "application/ports/messaging/event_bus.h"
#include "application/ports/audit/audit_logger.h"

#include "utils/retry_policy.h"
#include "utils/uuid.h"
#include "utils/timestamp.h"

/* -------------------------------------------------------------------------- */
/*  Constants & Macros                                                        */
/* -------------------------------------------------------------------------- */

#define SAGA_TAG             "DISBURSE_STIPEND_SAGA"
#define SAGA_VERSION         "v1.0.0"
#define SAGA_MAX_STEP_NAME   48

/* -------------------------------------------------------------------------- */
/*  Enumerations                                                              */
/* -------------------------------------------------------------------------- */

typedef enum
{
    SAGA_STATE_NOT_STARTED = 0,
    SAGA_STATE_COMPLIANCE_PASSED,
    SAGA_STATE_FUNDS_RESERVED,
    SAGA_STATE_LEDGER_POSTED,
    SAGA_STATE_DISBURSED,
    SAGA_STATE_ROLLING_BACK,
    SAGA_STATE_FAILED,
    SAGA_STATE_COMPLETED
} saga_state_e;

/* -------------------------------------------------------------------------- */
/*  Data Structures                                                           */
/* -------------------------------------------------------------------------- */

/* Forward declaration of self for step function pointer typedef */
struct disburse_stipend_saga_s;

/* Step/compensation function pointer */
typedef bool (*saga_step_fn)(struct disburse_stipend_saga_s *saga);

/* Step registration */
typedef struct
{
    char         name[SAGA_MAX_STEP_NAME];
    saga_step_fn forward;
    saga_step_fn compensate;
} saga_step_t;

/* Disburse Stipend Saga aggregate */
typedef struct disburse_stipend_saga_s
{
    /* Ports (dependency inversion) */
    compliance_service_t  *compliance;
    payment_gateway_t     *gateway;
    ledger_repository_t   *ledger_repo;
    stipend_repository_t  *stipend_repo;
    event_bus_t           *event_bus;
    audit_logger_t        *audit;

    /* Saga metadata */
    char           saga_id[UUID_STR_LEN];
    saga_state_e   state;
    retry_policy_t retry_policy;
    timestamp_t    started_at;

    /* Domain input */
    const stipend_request_t *request;

    /* Internal workflow */
    size_t        step_count;
    saga_step_t  *steps;
} disburse_stipend_saga_t;

/* -------------------------------------------------------------------------- */
/*  Utility – Error & Audit Helpers                                           */
/* -------------------------------------------------------------------------- */

static void
saga_log_audit(disburse_stipend_saga_t *saga,
               audit_severity_e         severity,
               const char              *fmt,
               ...)
{
    if (!saga || !saga->audit) { return; }

    va_list args;
    va_start(args, fmt);
    audit_logger_vlog(saga->audit, severity, SAGA_TAG, saga->saga_id, fmt, args);
    va_end(args);
}

static void
saga_publish_event(disburse_stipend_saga_t *saga,
                   const stipend_event_t   *event)
{
    if (!saga || !saga->event_bus || !event) { return; }

    event_bus_publish(saga->event_bus, (const event_base_t *)event);
}

/* -------------------------------------------------------------------------- */
/*  Forward Step Implementations                                              */
/* -------------------------------------------------------------------------- */

/* ---- Step 1: Compliance Check ------------------------------------------- */
static bool
step_compliance_check(disburse_stipend_saga_t *saga)
{
    stipend_event_t ev = {0};

    saga_log_audit(saga, AUDIT_INFO, "Running compliance checks…");

    compliance_result_t res = compliance_service_check(
        saga->compliance,
        &saga->request->student,
        &saga->request->payout_details);

    if (res.status != COMPLIANCE_STATUS_OK)
    {
        saga_log_audit(saga, AUDIT_WARN,
                       "Compliance check failed — reason: %s",
                       res.reason);

        ev.type              = STIPEND_EVENT_COMPLIANCE_FAILED;
        ev.stipend_request   = *saga->request;
        strncpy(ev.reason, res.reason, sizeof(ev.reason) - 1);
        saga_publish_event(saga, &ev);

        errno = EACCES; /* Permission denied / non-compliant */
        return false;
    }

    saga_log_audit(saga, AUDIT_INFO, "Compliance passed.");
    ev.type            = STIPEND_EVENT_COMPLIANCE_PASSED;
    ev.stipend_request = *saga->request;
    saga_publish_event(saga, &ev);

    saga->state = SAGA_STATE_COMPLIANCE_PASSED;
    return true;
}

/* Compensation: no action needed for compliance                            */
static bool
compensate_compliance(__attribute__((unused)) disburse_stipend_saga_t *saga)
{
    return true; /* Idempotent – nothing to undo */
}

/* ---- Step 2: Reserve Funds ---------------------------------------------- */
static bool
step_reserve_funds(disburse_stipend_saga_t *saga)
{
    saga_log_audit(saga, AUDIT_INFO, "Reserving funds…");

    payment_reservation_t reservation = {0};
    int rc = payment_gateway_reserve(
        saga->gateway,
        &saga->request->payout_details,
        &reservation);

    if (rc != 0)
    {
        saga_log_audit(saga, AUDIT_ERROR,
                       "Fund reservation failed (err=%d)", rc);
        errno = rc;
        return false;
    }

    /* Persist reservation token on stipend aggregate for later capture */
    stipend_repository_attach_reservation(
        saga->stipend_repo,
        saga->request->stipend_id,
        &reservation);

    saga->state = SAGA_STATE_FUNDS_RESERVED;
    return true;
}

static bool
compensate_reserve_funds(disburse_stipend_saga_t *saga)
{
    /* Release reservation only if it exists */
    saga_log_audit(saga, AUDIT_INFO, "Releasing reserved funds (rollback)…");

    /* Retrieve token back from stipend aggregate */
    payment_reservation_t token = {0};
    int rc = stipend_repository_get_reservation(
        saga->stipend_repo,
        saga->request->stipend_id,
        &token);

    if (rc != 0)
    {
        saga_log_audit(saga, AUDIT_ERROR,
                       "Failed to fetch reservation token (err=%d)", rc);
        return false;
    }

    rc = payment_gateway_release(saga->gateway, &token);
    if (rc != 0)
    {
        saga_log_audit(saga, AUDIT_ERROR,
                       "Fund release failed (err=%d)", rc);
        return false;
    }
    return true;
}

/* ---- Step 3: Ledger Posting --------------------------------------------- */
static bool
step_ledger_post(disburse_stipend_saga_t *saga)
{
    saga_log_audit(saga, AUDIT_INFO, "Posting ledger entry…");

    ledger_entry_t entry = {
        .entry_id       = "",
        .timestamp      = timestamp_now(),
        .type           = LEDGER_ENTRY_STIPEND_DISBURSEMENT,
        .amount         = saga->request->payout_details.amount,
        .currency       = saga->request->payout_details.currency,
        .student_id     = saga->request->student.student_id,
        .correlation_id = saga->saga_id
    };

    uuid_generate(entry.entry_id, sizeof(entry.entry_id));

    int rc = ledger_repository_append(saga->ledger_repo, &entry);
    if (rc != 0)
    {
        saga_log_audit(saga, AUDIT_ERROR,
                       "Ledger append failed (err=%d)", rc);
        errno = rc;
        return false;
    }

    saga->state = SAGA_STATE_LEDGER_POSTED;
    return true;
}

static bool
compensate_ledger_post(disburse_stipend_saga_t *saga)
{
    saga_log_audit(saga, AUDIT_INFO, "Reversing ledger entry (rollback)…");

    int rc = ledger_repository_reversal(
        saga->ledger_repo,
        saga->request->student.student_id,
        saga->saga_id); /* correlation_id */

    if (rc != 0)
    {
        saga_log_audit(saga, AUDIT_ERROR,
                       "Ledger reversal failed (err=%d)", rc);
        return false;
    }
    return true;
}

/* ---- Step 4: Capture / Disburse Funds ------------------------------------ */
static bool
step_capture_funds(disburse_stipend_saga_t *saga)
{
    saga_log_audit(saga, AUDIT_INFO,
                   "Capturing reserved funds to student account…");

    payment_reservation_t token = {0};
    int rc = stipend_repository_get_reservation(
        saga->stipend_repo,
        saga->request->stipend_id,
        &token);

    if (rc != 0)
    {
        saga_log_audit(saga, AUDIT_ERROR,
                       "Reservation token missing (err=%d)", rc);
        errno = rc;
        return false;
    }

    rc = payment_gateway_capture(saga->gateway, &token);
    if (rc != 0)
    {
        saga_log_audit(saga, AUDIT_ERROR,
                       "Fund capture failed (err=%d)", rc);
        errno = rc;
        return false;
    }

    saga->state = SAGA_STATE_DISBURSED;
    return true;
}

static bool
compensate_capture_funds(disburse_stipend_saga_t *saga)
{
    /* Attempt refund only if capture was successful */
    saga_log_audit(saga, AUDIT_INFO,
                   "Refunding captured funds (rollback)…");

    payment_reservation_t token = {0};
    int rc = stipend_repository_get_reservation(
        saga->stipend_repo,
        saga->request->stipend_id,
        &token);

    if (rc != 0)
    {
        saga_log_audit(saga, AUDIT_ERROR,
                       "Reservation token missing for refund (err=%d)", rc);
        return false;
    }

    rc = payment_gateway_refund(saga->gateway, &token);
    if (rc != 0)
    {
        saga_log_audit(saga, AUDIT_ERROR,
                       "Refund failed (err=%d)", rc);
        return false;
    }
    return true;
}

/* -------------------------------------------------------------------------- */
/*  Saga Steps Array                                                          */
/* -------------------------------------------------------------------------- */

static saga_step_t g_saga_steps[] = {
    { "COMPLIANCE_CHECK",      step_compliance_check,  compensate_compliance   },
    { "RESERVE_FUNDS",         step_reserve_funds,     compensate_reserve_funds},
    { "LEDGER_POST",           step_ledger_post,       compensate_ledger_post },
    { "CAPTURE_FUNDS",         step_capture_funds,     compensate_capture_funds}
};

#define SAGA_TOTAL_STEPS (sizeof(g_saga_steps) / sizeof(g_saga_steps[0]))

/* -------------------------------------------------------------------------- */
/*  Public API                                                                */
/* -------------------------------------------------------------------------- */

/**
 * disburse_stipend_run
 *
 * Execute the Disburse Stipend Saga for a given stipend request.
 *
 * return: 0 on success, or a negative errno code on failure.
 */
int
disburse_stipend_run(
    const stipend_request_t  *request,
    compliance_service_t     *compliance,
    payment_gateway_t        *gateway,
    ledger_repository_t      *ledger_repo,
    stipend_repository_t     *stipend_repo,
    event_bus_t              *event_bus,
    audit_logger_t           *audit,
    retry_policy_t            retry_policy)
{
    if (!request || !compliance || !gateway || !ledger_repo ||
        !stipend_repo || !event_bus || !audit)
    {
        return EINVAL;
    }

    /* ------------------------------------------------------------------ */
    /*  Instantiate saga context                                           */
    /* ------------------------------------------------------------------ */
    disburse_stipend_saga_t saga = {
        .compliance   = compliance,
        .gateway      = gateway,
        .ledger_repo  = ledger_repo,
        .stipend_repo = stipend_repo,
        .event_bus    = event_bus,
        .audit        = audit,
        .state        = SAGA_STATE_NOT_STARTED,
        .retry_policy = retry_policy,
        .request      = request,
        .steps        = g_saga_steps,
        .step_count   = SAGA_TOTAL_STEPS,
        .started_at   = timestamp_now()
    };
    uuid_generate(saga.saga_id, sizeof(saga.saga_id));

    saga_log_audit(&saga, AUDIT_INFO,
                   "Saga %s (%s) started for Stipend #%s.",
                   saga.saga_id, SAGA_VERSION, request->stipend_id);

    /* ------------------------------------------------------------------ */
    /*  Forward execution                                                 */
    /* ------------------------------------------------------------------ */
    ssize_t current_step = 0;
    for (; current_step < (ssize_t)saga.step_count; ++current_step)
    {
        const saga_step_t *step = &saga.steps[current_step];
        size_t attempt = 0;

        saga_log_audit(&saga, AUDIT_DEBUG, "→ Executing step: %s", step->name);

        while (attempt <= saga.retry_policy.max_retries)
        {
            if (step->forward(&saga))
            {
                /* Success */
                break;
            }

            attempt++;
            if (attempt > saga.retry_policy.max_retries)
            {
                /* Abort forward flow */
                saga_log_audit(&saga, AUDIT_WARN,
                               "Step %s exhausted retry budget.", step->name);
                goto rollback; /* Begin compensation */
            }

            /* Wait before retry */
            uint32_t backoff_ms = retry_policy_backoff(&saga.retry_policy, attempt);
            saga_log_audit(&saga, AUDIT_INFO,
                           "Retrying step %s in %ums (attempt %zu)…",
                           step->name, backoff_ms, attempt);

            retry_policy_sleep(backoff_ms);
        }
    }

    /* ------------------------------------------------------------------ */
    /*  Completed successfully                                            */
    /* ------------------------------------------------------------------ */
    saga.state = SAGA_STATE_COMPLETED;
    saga_log_audit(&saga, AUDIT_INFO,
                   "Saga %s completed successfully.", saga.saga_id);

    stipend_event_t ev = {
        .type            = STIPEND_EVENT_DISBURSED,
        .stipend_request = *request
    };
    saga_publish_event(&saga, &ev);
    return 0;

/* -------------------------------------------------------------------------- */
/*  Compensation / Rollback Flow                                              */
/* -------------------------------------------------------------------------- */
rollback:
    saga.state = SAGA_STATE_ROLLING_BACK;
    saga_log_audit(&saga, AUDIT_WARN,
                   "Initiating rollback of Saga %s…", saga.saga_id);

    for (ssize_t i = current_step; i >= 0; --i)
    {
        const saga_step_t *step = &saga.steps[i];
        saga_log_audit(&saga, AUDIT_DEBUG,
                       "↩ Compensating step: %s", step->name);

        if (!step->compensate(&saga))
        {
            saga_log_audit(&saga, AUDIT_ERROR,
                           "Compensation for step %s failed.", step->name);
            /* Compensation failures are logged, but saga continues */
        }
    }

    saga.state = SAGA_STATE_FAILED;

    stipend_event_t failed_ev = {
        .type            = STIPEND_EVENT_DISBURSEMENT_FAILED,
        .stipend_request = *request
    };
    strncpy(failed_ev.reason, "Saga rollback completed", sizeof(failed_ev.reason) - 1);
    saga_publish_event(&saga, &failed_ev);

    saga_log_audit(&saga, AUDIT_WARN,
                   "Saga %s rolled back. Stipend disbursement aborted.",
                   saga.saga_id);

    /* Preserve original errno set by failing step */
    return errno ? errno : ECANCELED;
}

/* -------------------------------------------------------------------------- */
/*  End of file                                                               */
/* -------------------------------------------------------------------------- */
