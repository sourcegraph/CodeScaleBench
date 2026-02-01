/**
 * EduPay Ledger Academy – Bursar Service
 * --------------------------------------
 * Use-case: Process Tuition Payment
 *
 * Layer : Application (Use-Case)
 * File  : process_tuition_payment.c
 *
 * This module coordinates tuition-invoice settlement against the external
 * payment gateway while invoking fraud checks, multi-currency conversion,
 * audit-trail logging, event dispatching, and saga-style compensating
 * actions.  No business rules leak transport or DB details, thereby honoring
 * Clean Architecture’s dependency inversion.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <pthread.h>
#include <time.h>

/* ────────────────────────────────────────────────────────────────────────── */
/* Forward declarations for Dependency Ports (defined in other bounded contexts)
 * The concrete adapters live elsewhere; for the purpose of this compilation
 * unit we only need the abstract contracts (function pointers).             */

typedef struct PaymentGatewayResponse {
    bool      ok;
    char      gateway_reference[64];
    char      error_msg[128];
} PaymentGatewayResponse;

typedef struct PaymentGatewayPort {
    PaymentGatewayResponse (*charge)(
        const char *token,
        const char *currency_iso4217,
        uint64_t    amount_minor_units,
        const char *idempotency_key
    );
    void (*refund)(
        const char *gateway_reference,
        uint64_t    amount_minor_units
    );
} PaymentGatewayPort;

typedef struct FXQuote {
    bool     ok;
    double   rate; /* invoice_currency → payment_currency */
    char     error_msg[128];
} FXQuote;

typedef struct CurrencyConverterService {
    FXQuote (*get_quote)(const char *from_iso4217, const char *to_iso4217);
    uint64_t (*apply_rate)(uint64_t amount_minor, double rate);
} CurrencyConverterService;

typedef struct FraudDetectionService {
    bool (*is_high_risk_txn)(const char *student_id,
                             const char *payment_token,
                             uint64_t    amount_minor,
                             const char *currency);
} FraudDetectionService;

typedef struct AuditTrailPort {
    void (*record)(const char *actor,
                   const char *action,
                   const char *details_json);
} AuditTrailPort;

typedef struct EventBusPort {
    void (*publish)(const char *topic, const void *event_payload, size_t sz);
} EventBusPort;

typedef struct StudentAccount {
    char     student_id[32];
    uint64_t tuition_due_minor;  /* Always stored in campus base currency */
    bool     tuition_settled;
} StudentAccount;

typedef struct StudentAccountRepository {
    bool (*lock_by_student_id)(const char *student_id, StudentAccount *out);
    bool (*persist)(const StudentAccount *account);
    void (*unlock)(const char *student_id);
} StudentAccountRepository;

/* ────────────────────────────────────────────────────────────────────────── */
/* Domain Events                                                             */

typedef struct TuitionPaymentCompletedEvent {
    char     student_id[32];
    char     invoice_id[32];
    char     currency[4];
    uint64_t amount_minor;
    char     gateway_reference[64];
    time_t   processed_utc;
} TuitionPaymentCompletedEvent;

typedef struct TuitionPaymentRejectedEvent {
    char     student_id[32];
    char     invoice_id[32];
    char     reason[128];
    time_t   processed_utc;
} TuitionPaymentRejectedEvent;

/* ────────────────────────────────────────────────────────────────────────── */
/* Use-case DTOs                                                             */

typedef struct TuitionPaymentCommand {
    const char *student_id;
    const char *invoice_id;
    const char *payment_currency;   /* ISO-4217 e.g. “USD” */
    uint64_t    amount_minor;       /* minor units in payment_currency */
    const char *payment_method_token;
} TuitionPaymentCommand;

typedef enum PaymentStatus {
    PAYMENT_SUCCESS,
    PAYMENT_FRAUD_SUSPECTED,
    PAYMENT_GATEWAY_ERROR,
    PAYMENT_CURRENCY_NOT_SUPPORTED,
    PAYMENT_INSUFFICIENT_FUNDS,
    PAYMENT_CONCURRENCY_CONFLICT,
    PAYMENT_UNKNOWN_ERROR
} PaymentStatus;

typedef struct TuitionPaymentResult {
    PaymentStatus status;
    char          message[256];
} TuitionPaymentResult;

/* ────────────────────────────────────────────────────────────────────────── */
/* Saga Context                                                              */

typedef struct PaymentSagaCtx {
    bool                  payment_charged;
    PaymentGatewayResponse gateway_resp;
} PaymentSagaCtx;

/* ────────────────────────────────────────────────────────────────────────── */
/* BursarServiceContext – aggregate all ports required by the use-case       */

typedef struct BursarServiceContext {
    const PaymentGatewayPort      *payment_gateway;
    const CurrencyConverterService *fx_service;
    const FraudDetectionService   *fraud_service;
    const StudentAccountRepository *student_repo;
    const AuditTrailPort          *audit_trail;
    const EventBusPort            *event_bus;
    pthread_mutex_t               *global_mutex; /* coarse-grained commit lock */
} BursarServiceContext;

/* ────────────────────────────────────────────────────────────────────────── */
/* Utility – JSON escaper (very naive, for demo purposes)                    */

static void json_escape(const char *src, char *dst, size_t dst_sz)
{
    size_t j = 0;
    for (size_t i = 0; src[i] && j + 1 < dst_sz; ++i) {
        if (src[i] == '"' || src[i] == '\\') {
            if (j + 2 >= dst_sz) break;
            dst[j++] = '\\';
        }
        dst[j++] = src[i];
    }
    dst[j] = '\0';
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Compensating transaction for Saga                                         */

static void compensate_charge(const BursarServiceContext *ctx,
                              PaymentSagaCtx            *saga)
{
    if (!saga->payment_charged) return;

    ctx->audit_trail->record(
        "BursarService",
        "COMPENSATE_PAYMENT",
        "{\"msg\":\"Refunding because of mid-saga failure\"}"
    );

    ctx->payment_gateway->refund(
        saga->gateway_resp.gateway_reference,
        0 /* full amount */
    );
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Core Use-case                                                             */

static TuitionPaymentResult do_payment_flow(
        const BursarServiceContext *ctx,
        const TuitionPaymentCommand *cmd)
{
    TuitionPaymentResult res = { PAYMENT_UNKNOWN_ERROR, "Uninitialised" };
    PaymentSagaCtx saga      = { 0 };

    /* 1. Basic command validation */
    if (!cmd || !cmd->student_id || !cmd->invoice_id ||
        !cmd->payment_method_token || !cmd->payment_currency) {
        res.status = PAYMENT_UNKNOWN_ERROR;
        strncpy(res.message, "NULL argument(s) received", sizeof res.message);
        return res;
    }

    /* 2. Concurrency guard (simplified) */
    if (pthread_mutex_lock(ctx->global_mutex) != 0) {
        res.status = PAYMENT_CONCURRENCY_CONFLICT;
        strncpy(res.message, "Unable to obtain global commit lock",
                sizeof res.message);
        return res;
    }

    /* 3. Load student account with pessimistic lock */
    StudentAccount account = { 0 };
    if (!ctx->student_repo->lock_by_student_id(cmd->student_id, &account)) {
        pthread_mutex_unlock(ctx->global_mutex);
        res.status = PAYMENT_UNKNOWN_ERROR;
        snprintf(res.message, sizeof res.message,
                 "Student ID %s not found", cmd->student_id);
        return res;
    }

    if (account.tuition_settled) {
        ctx->student_repo->unlock(cmd->student_id);
        pthread_mutex_unlock(ctx->global_mutex);
        res.status = PAYMENT_SUCCESS;
        snprintf(res.message, sizeof res.message,
                 "Invoice already settled, idempotent acceptance");
        return res;
    }

    /* 4. Fraud Detection */
    if (ctx->fraud_service->is_high_risk_txn(cmd->student_id,
                                             cmd->payment_method_token,
                                             cmd->amount_minor,
                                             cmd->payment_currency)) {
        TuitionPaymentRejectedEvent ev = { 0 };
        strncpy(ev.student_id, cmd->student_id, sizeof ev.student_id);
        strncpy(ev.invoice_id, cmd->invoice_id, sizeof ev.invoice_id);
        strncpy(ev.reason, "High risk transaction flagged", sizeof ev.reason);
        ev.processed_utc = time(NULL);
        ctx->event_bus->publish("TuitionPaymentRejectedEvent",
                                &ev, sizeof ev);

        ctx->student_repo->unlock(cmd->student_id);
        pthread_mutex_unlock(ctx->global_mutex);

        res.status = PAYMENT_FRAUD_SUSPECTED;
        strncpy(res.message, "Fraud detection rejected payment",
                sizeof res.message);
        return res;
    }

    /* 5. Multi-currency conversion (if needed) */
    uint64_t amount_in_invoice_currency = cmd->amount_minor;
    if (strcmp(cmd->payment_currency, "USD") != 0) { /* campus base = USD */
        FXQuote q = ctx->fx_service->get_quote(cmd->payment_currency, "USD");
        if (!q.ok) {
            ctx->student_repo->unlock(cmd->student_id);
            pthread_mutex_unlock(ctx->global_mutex);
            res.status = PAYMENT_CURRENCY_NOT_SUPPORTED;
            snprintf(res.message, sizeof res.message,
                     "FX quote unavailable: %s", q.error_msg);
            return res;
        }
        amount_in_invoice_currency = ctx->fx_service
                ->apply_rate(cmd->amount_minor, q.rate);
    }

    /* Business rule: ensure amount matches outstanding tuition */
    if (amount_in_invoice_currency < account.tuition_due_minor) {
        ctx->student_repo->unlock(cmd->student_id);
        pthread_mutex_unlock(ctx->global_mutex);
        res.status = PAYMENT_INSUFFICIENT_FUNDS;
        strncpy(res.message, "Insufficient amount to cover tuition",
                sizeof res.message);
        return res;
    }

    /* 6. Charge gateway */
    char idem_key[96];
    snprintf(idem_key, sizeof idem_key, "%s-%s-%llu",
             cmd->student_id, cmd->invoice_id,
             (unsigned long long)cmd->amount_minor);

    saga.gateway_resp = ctx->payment_gateway->charge(
            cmd->payment_method_token,
            cmd->payment_currency,
            cmd->amount_minor,
            idem_key);

    if (!saga.gateway_resp.ok) {
        ctx->student_repo->unlock(cmd->student_id);
        pthread_mutex_unlock(ctx->global_mutex);
        res.status = PAYMENT_GATEWAY_ERROR;
        snprintf(res.message, sizeof res.message,
                 "Gateway error: %s", saga.gateway_resp.error_msg);
        return res;
    }
    saga.payment_charged = true;

    /* 7. Update ledger */
    account.tuition_due_minor = 0;
    account.tuition_settled   = true;
    if (!ctx->student_repo->persist(&account)) {
        /* Persistence failure – compensate */
        compensate_charge(ctx, &saga);
        ctx->student_repo->unlock(cmd->student_id);
        pthread_mutex_unlock(ctx->global_mutex);
        res.status = PAYMENT_UNKNOWN_ERROR;
        strncpy(res.message, "Failed to persist ledger state",
                sizeof res.message);
        return res;
    }

    /* 8. Release locks */
    ctx->student_repo->unlock(cmd->student_id);
    pthread_mutex_unlock(ctx->global_mutex);

    /* 9. Audit trail */
    char esc_student_id[64];
    json_escape(cmd->student_id, esc_student_id, sizeof esc_student_id);
    char audit_json[256];
    snprintf(audit_json, sizeof audit_json,
             "{\"student_id\":\"%s\",\"invoice_id\":\"%s\","
             "\"gateway_ref\":\"%s\"}",
             esc_student_id, cmd->invoice_id,
             saga.gateway_resp.gateway_reference);

    ctx->audit_trail->record("BursarService",
                             "TUITION_PAYMENT_COMPLETED",
                             audit_json);

    /* 10. Publish domain event */
    TuitionPaymentCompletedEvent ev = { 0 };
    strncpy(ev.student_id, cmd->student_id, sizeof ev.student_id);
    strncpy(ev.invoice_id, cmd->invoice_id, sizeof ev.invoice_id);
    strncpy(ev.currency, cmd->payment_currency, sizeof ev.currency);
    ev.amount_minor     = cmd->amount_minor;
    strncpy(ev.gateway_reference, saga.gateway_resp.gateway_reference,
            sizeof ev.gateway_reference);
    ev.processed_utc = time(NULL);

    ctx->event_bus->publish("TuitionPaymentCompletedEvent",
                            &ev, sizeof ev);

    /* 11. Done */
    res.status = PAYMENT_SUCCESS;
    strncpy(res.message, "Tuition payment settled successfully",
            sizeof res.message);
    return res;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Public API                                                                */

TuitionPaymentResult process_tuition_payment(
        const BursarServiceContext *ctx,
        const TuitionPaymentCommand *cmd)
{
    if (!ctx) {
        TuitionPaymentResult res = { PAYMENT_UNKNOWN_ERROR,
                                     "NULL service context" };
        return res;
    }
    return do_payment_flow(ctx, cmd);
}

/* ────────────────────────────────────────────────────────────────────────── */
/* End of file                                                               */
/* vim: set ts=4 sw=4 et:                                                    */
