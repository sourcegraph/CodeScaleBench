/**
 * @file verify_kyc.c
 * @brief Use-case implementation for verifying KYC (Know Your Customer)
 *        information for a student/payer applying for financial aid.
 *
 *        This lives in the Application layer (Clean Architecture) and
 *        orchestrates domain logic through explicit interfaces.  No concrete
 *        databases, message brokers, or HTTP clients are referenced here—
 *        those live in the Infrastructure layer and are wired-in at run-time.
 *
 *        Responsibilities:
 *          • Look up (or create) a KYC record for the subject.
 *          • Invoke the upstream KYC provider when verification is required.
 *          • Persist the new status atomically inside a transaction.
 *          • Emit a domain event and write an immutable audit-trail entry.
 *
 *        Thread-safety note:
 *          The function does not maintain global state; all side-effects are
 *          delegated to interface ports that must be implemented as safe
 *          under the project’s concurrency model (e.g., actor, mutex, etc.).
 *
 * Copyright:
 *        EduPay Ledger Academy — reference implementation for classroom use.
 */

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>      /* snprintf */
#include <string.h>     /* memset, strncpy */
#include <time.h>       /* struct timespec */

#include "verify_kyc.h"
#include "kyc_repository.h"
#include "kyc_provider_gateway.h"
#include "audit_trail_port.h"
#include "clock_service.h"
#include "domain_event_bus.h"
#include "transaction_manager.h"

/* -------------------------------------------------------------------------- */
/* Local definitions                                                          */
/* -------------------------------------------------------------------------- */

#define ERR(_fmt, ...)                                           \
    do {                                                         \
        if (error_buf && error_buf_len)                          \
            snprintf(error_buf, error_buf_len, (_fmt), ##__VA_ARGS__); \
    } while (0)

static const char *kyc_status_to_string(KycStatus s)
{
    switch (s) {
        case KYC_STATUS_UNVERIFIED: return "UNVERIFIED";
        case KYC_STATUS_PENDING:    return "PENDING";
        case KYC_STATUS_VERIFIED:   return "VERIFIED";
        case KYC_STATUS_FAILED:     return "FAILED";
        default:                    return "UNKNOWN";
    }
}

/* -------------------------------------------------------------------------- */
/* Use-case implementation                                                    */
/* -------------------------------------------------------------------------- */

void VerifyKycUseCase_init(VerifyKycUseCase       *uc,
                           KycRepository          *repo,
                           KycProviderGateway     *gw,
                           AuditTrailPort         *audit,
                           DomainEventBus         *bus,
                           ClockService           *clock,
                           TransactionManager     *tx)
{
    if (!uc) return;

    uc->kyc_repo   = repo;
    uc->kyc_gw     = gw;
    uc->audit_port = audit;
    uc->bus        = bus;
    uc->clock      = clock;
    uc->tx_manager = tx;
}

/**
 * @brief Run the Verify KYC use-case.
 *
 * @param uc             Initialized use-case struct.
 * @param subject_id     Student/payer identifier (unique within tenant).
 * @param actor_id       Who initiated the verification (admin/cron/etc.).
 * @param force_refresh  If true, always call provider even when status is
 *                       already VERIFIED.
 * @param error_buf      Optional destination for human-readable error.
 * @param error_buf_len  Size of error_buf.
 *
 * @return VerifyKycResult structure describing the outcome.
 */
VerifyKycResult
VerifyKycUseCase_execute(VerifyKycUseCase *uc,
                         const char       *subject_id,
                         const char       *actor_id,
                         bool              force_refresh,
                         char             *error_buf,
                         size_t            error_buf_len)
{
    VerifyKycResult result;
    memset(&result, 0, sizeof(result));

    if (!uc || !subject_id || !actor_id) {
        ERR("invalid argument");
        result.status = VERIFY_KYC_ERROR;
        return result;
    }

    TransactionManager *txm = uc->tx_manager;
    TxHandle            tx  = NULL;

    /* Begin transaction ---------------------------------------------------- */
    if (txm && (tx = txm->begin(txm)) == NULL) {
        ERR("unable to open transaction");
        result.status = VERIFY_KYC_ERROR;
        return result;
    }

    /* 1. Load existing KYC record or create a new one ---------------------- */
    KycRecord rec;
    bool      rec_exists = uc->kyc_repo->find_by_subject(uc->kyc_repo,
                                                         subject_id,
                                                         &rec);

    if (!rec_exists) {
        memset(&rec, 0, sizeof(rec));
        strncpy(rec.subject_id, subject_id, sizeof(rec.subject_id) - 1);
        rec.status = KYC_STATUS_UNVERIFIED;
        rec.created_at = uc->clock->now(uc->clock);
    }

    if (rec.status == KYC_STATUS_VERIFIED && !force_refresh) {
        /* Nothing to do; commit & return early. */
        if (txm) txm->commit(txm, tx);
        result.status         = VERIFY_KYC_ALREADY_VERIFIED;
        result.latest_status  = rec.status;
        result.provider_tx_id[0] = '\0';
        return result;
    }

    /* 2. Mark as PENDING prior to external call to lock the record --------- */
    rec.status      = KYC_STATUS_PENDING;
    rec.updated_at  = uc->clock->now(uc->clock);

    if (!uc->kyc_repo->save(uc->kyc_repo, &rec)) {
        if (txm) txm->rollback(txm, tx);
        ERR("database error while staging KYC record");
        result.status = VERIFY_KYC_ERROR;
        return result;
    }

    /* 3. Call the upstream provider --------------------------------------- */
    KycProviderResponse provider_resp;
    bool gw_ok = uc->kyc_gw->verify(uc->kyc_gw,
                                    subject_id,
                                    &provider_resp,
                                    error_buf,
                                    error_buf_len);

    if (!gw_ok) {
        /* Provider failed; mark KYC as FAILED. */
        rec.status      = KYC_STATUS_FAILED;
        rec.failure_msg[0] = '\0';
        if (error_buf && error_buf_len) {
            /* copy error_buf into record for posterity, truncating */
            strncpy(rec.failure_msg, error_buf, sizeof(rec.failure_msg) - 1);
        }
        rec.updated_at  = uc->clock->now(uc->clock);
        uc->kyc_repo->save(uc->kyc_repo, &rec); /* best-effort */

        if (txm) txm->rollback(txm, tx);
        result.status        = VERIFY_KYC_PROVIDER_FAILURE;
        result.latest_status = rec.status;
        return result;
    }

    /* 4. Update record with provider response ----------------------------- */
    rec.status       = provider_resp.approved ? KYC_STATUS_VERIFIED
                                              : KYC_STATUS_FAILED;
    strncpy(rec.provider_tx_id, provider_resp.transaction_id,
            sizeof(rec.provider_tx_id) - 1);

    if (!provider_resp.approved) {
        strncpy(rec.failure_msg, provider_resp.failure_reason,
                sizeof(rec.failure_msg) - 1);
    }
    rec.updated_at = uc->clock->now(uc->clock);

    if (!uc->kyc_repo->save(uc->kyc_repo, &rec)) {
        if (txm) txm->rollback(txm, tx);
        ERR("unable to persist KYC result");
        result.status = VERIFY_KYC_ERROR;
        return result;
    }

    /* 5. Commit transaction ------------------------------------------------ */
    if (txm && !txm->commit(txm, tx)) {
        ERR("transaction commit failed");
        result.status = VERIFY_KYC_ERROR;
        return result;
    }

    /* 6. Emit domain event ------------------------------------------------- */
    KycVerifiedEvent evt;
    memset(&evt, 0, sizeof(evt));
    strncpy(evt.subject_id,  subject_id,   sizeof(evt.subject_id) - 1);
    strncpy(evt.actor_id,    actor_id,     sizeof(evt.actor_id) - 1);
    strncpy(evt.provider_tx, rec.provider_tx_id, sizeof(evt.provider_tx) - 1);
    evt.status       = rec.status;
    evt.occurred_on  = rec.updated_at;

    uc->bus->publish(uc->bus, DOMAIN_EVENT_TYPE_KYC_VERIFIED, &evt,
                     sizeof(evt));

    /* 7. Write audit-trail ------------------------------------------------- */
    AuditEntry audit;
    memset(&audit, 0, sizeof(audit));
    audit.occurred_on = rec.updated_at;
    strncpy(audit.actor_id,    actor_id,     sizeof(audit.actor_id) - 1);
    strncpy(audit.subject_id,  subject_id,   sizeof(audit.subject_id) - 1);
    audit.operation = AUDIT_OP_KYC_VERIFICATION;
    snprintf(audit.payload, sizeof(audit.payload),
             "{ \"new_status\": \"%s\", \"provider_tx_id\": \"%s\" }",
             kyc_status_to_string(rec.status),
             rec.provider_tx_id);

    uc->audit_port->record(uc->audit_port, &audit);

    /* 8. Populate result --------------------------------------------------- */
    result.status        = (rec.status == KYC_STATUS_VERIFIED)
                           ? VERIFY_KYC_SUCCESS
                           : VERIFY_KYC_REJECTED;
    result.latest_status = rec.status;
    strncpy(result.provider_tx_id, rec.provider_tx_id,
            sizeof(result.provider_tx_id) - 1);

    return result;
}

/* -------------------------------------------------------------------------- */
/* End of file                                                                */
/* -------------------------------------------------------------------------- */
