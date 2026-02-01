#ifndef EDUPAY_LEDGER_ACADEMY_BURSAR_PROCESS_TUITION_PAYMENT_H
#define EDUPAY_LEDGER_ACADEMY_BURSAR_PROCESS_TUITION_PAYMENT_H
/**
 *  EduPay Ledger Academy ‒ Bursar Service
 *
 *  File  : process_tuition_payment.h
 *  Author: EduPay Core Team
 *  Desc. : Clean-Architecture “use-case interactor” responsible for
 *          orchestrating a single tuition-payment transaction.
 *
 *          The interactor is completely framework-agnostic; all volatile
 *          dependencies (DB, message brokers, payment gateways, etc.) are
 *          expressed as function-pointer “ports” that may be replaced at
 *          compile-time or run-time for testing, coursework exercises, or
 *          production deployments.
 *
 *          The header is intentionally implemented in a header-only style
 *          (static inline) so that professors can single-step through the
 *          entire business flow without chasing implementation files.
 *
 *  NOTE   This component is thread-safe provided that the injected ports are
 *         themselves thread-safe or that the caller provides appropriate
 *         synchronisation.
 */

#include <stddef.h>     /* size_t    */
#include <stdint.h>     /* uint64_t  */
#include <stdbool.h>    /* bool      */
#include <time.h>       /* time_t    */
#include <string.h>     /* strlen    */
#include <errno.h>      /* errno_t   */

#ifdef __cplusplus
extern "C" {
#endif

/*─────────────────────────────────────────────────────────────────────────────*
 *                     C O N F I G U R A T I O N   M A C R O S
 *─────────────────────────────────────────────────────────────────────────────*/

/* Maximum number of printable characters allocated for IDs / messages. */
#ifndef EDUPAY_MAX_ID_LENGTH
#   define EDUPAY_MAX_ID_LENGTH  64U
#endif

#ifndef EDUPAY_MAX_ERROR_MSG_LENGTH
#   define EDUPAY_MAX_ERROR_MSG_LENGTH 256U
#endif

/*─────────────────────────────────────────────────────────────────────────────*
 *                       D A T A   T R A N S F E R   O B J E C T S
 *─────────────────────────────────────────────────────────────────────────────*/

/**
 * Enumeration of canonical error codes returned by the interactor.
 * Use edu_strerror_tuition() to map each value to a human-readable string.
 */
typedef enum
{
    EDUPAY_TUITION_OK = 0,
    EDUPAY_TUITION_ERR_INVALID_ARG,
    EDUPAY_TUITION_ERR_CURRENCY_UNSUPPORTED,
    EDUPAY_TUITION_ERR_FRAUD_FLAGGED,
    EDUPAY_TUITION_ERR_GATEWAY_DECLINED,
    EDUPAY_TUITION_ERR_LEDGER_FAILURE,
    EDUPAY_TUITION_ERR_AUDIT_FAILURE,
    EDUPAY_TUITION_ERR_UNKNOWN
} edu_tuition_status_t;

/**
 * Payment method types.  Add more as exercise (ACH, Crypto, etc.).
 */
typedef enum
{
    PAYMENT_METHOD_CARD,
    PAYMENT_METHOD_BANK_TRANSFER
} payment_method_type_t;

typedef struct
{
    char      network[8];          /* e.g. "VISA", "MC", "AMEX"        */
    char      last4[5];            /* last four digits, NUL-terminated */
    uint16_t  exp_year;            /* 4-digit year                     */
    uint8_t   exp_month;           /* 1-12                             */
} payment_card_t;

typedef struct
{
    char  routing_number[10];
    char  account_last4[5];
} payment_bank_transfer_t;

/**
 * Discriminated union of payment method details.
 */
typedef struct
{
    payment_method_type_t type;
    union
    {
        payment_card_t          card;
        payment_bank_transfer_t bank;
    };
} payment_method_t;

/**
 * Input DTO representing a tuition payment attempt.
 */
typedef struct
{
    char            student_id[EDUPAY_MAX_ID_LENGTH];
    char            invoice_id[EDUPAY_MAX_ID_LENGTH];
    uint64_t        amount_minor_units;               /* cents, pence, etc.  */
    char            currency[4];                      /* ISO-4217 (3 chars)  */
    time_t          timestamp_utc;                    /* when request made   */
    payment_method_t method;                          /* discriminated union */
} process_tuition_payment_request_t;

/**
 * Output DTO describing the result of a tuition payment attempt.
 */
typedef struct
{
    edu_tuition_status_t status;                      /* canonical status    */
    char                 transaction_id[EDUPAY_MAX_ID_LENGTH];
    char                 error_msg[EDUPAY_MAX_ERROR_MSG_LENGTH];
} process_tuition_payment_response_t;

/*─────────────────────────────────────────────────────────────────────────────*
 *                              P O R T S (SPI)
 *─────────────────────────────────────────────────────────────────────────────*/

/*  The following typedefs describe the “service-provider interface” ports
 *  required by the use case. Production code will inject real implementations
 *  (calls to Stripe, internal ledger DB, etc.) whereas unit tests can inject
 *  mocks / fakes.
 */

/**
 * Fraud-detection port.
 *
 * Returns true if payment is deemed safe, false if suspected fraudulent.
 * Implementations SHOULD populate `reason_out` with a short reason
 * (optional) when returning false.
 */
typedef bool (*port_fraud_check_t)(
        const process_tuition_payment_request_t *request,
        char  /*out*/ reason_out[/*EDUPAY_MAX_ERROR_MSG_LENGTH*/]);

/**
 * Funds-reservation / payment-gateway port.
 *
 * On success, returns true and populates `transaction_id_out`.
 * On failure, returns false and populates `error_out`.
 */
typedef bool (*port_reserve_funds_t)(
        const process_tuition_payment_request_t *request,
        char /*out*/ transaction_id_out[/*EDUPAY_MAX_ID_LENGTH*/],
        char /*out*/ error_out[/*EDUPAY_MAX_ERROR_MSG_LENGTH*/]);

/**
 * Ledger posting port.
 *
 * Persists an immutable event representing the successful payment.
 */
typedef bool (*port_post_ledger_entry_t)(
        const char *transaction_id,
        const process_tuition_payment_request_t *request,
        char /*out*/ error_out[/*EDUPAY_MAX_ERROR_MSG_LENGTH*/]);

/**
 * Audit-trail port.
 *
 * Non-critical; failure should be logged but must not break payment flow.
 */
typedef bool (*port_write_audit_trail_t)(
        const char *event_name,
        const void *payload,
        size_t      payload_size);

/*─────────────────────────────────────────────────────────────────────────────*
 *                    I N T E R A C T O R   D E P E N D E N C Y   B U N D L E
 *─────────────────────────────────────────────────────────────────────────────*/

/**
 * Bundle of dependency ports injected into the interactor.
 */
typedef struct
{
    port_fraud_check_t        fraud_check;
    port_reserve_funds_t      reserve_funds;
    port_post_ledger_entry_t  post_ledger;
    port_write_audit_trail_t  write_audit;    /* optional but recommended */
} process_tuition_payment_interactor_t;

/*─────────────────────────────────────────────────────────────────────────────*
 *                        P U B L I C   A P I   ( U C )
 *─────────────────────────────────────────────────────────────────────────────*/

/**
 * Human-readable error string for edu_tuition_status_t.
 */
static inline const char *edu_strerror_tuition(edu_tuition_status_t st)
{
    switch (st) {
        case EDUPAY_TUITION_OK:                     return "Success";
        case EDUPAY_TUITION_ERR_INVALID_ARG:        return "Invalid argument";
        case EDUPAY_TUITION_ERR_CURRENCY_UNSUPPORTED:return "Unsupported currency";
        case EDUPAY_TUITION_ERR_FRAUD_FLAGGED:      return "Fraud flagged";
        case EDUPAY_TUITION_ERR_GATEWAY_DECLINED:   return "Gateway declined";
        case EDUPAY_TUITION_ERR_LEDGER_FAILURE:     return "Ledger persistence failed";
        case EDUPAY_TUITION_ERR_AUDIT_FAILURE:      return "Audit-trail write failed";
        default:                                    return "Unknown error";
    }
}

/**
 * Main interactor function.
 *
 * Parameters
 * ----------
 *  interactor : bundle of dependency ports (must be non-NULL pointers)
 *  request    : input DTO (must be non-NULL)
 *  response   : output DTO (must be non-NULL; pre-allocated by caller)
 *
 * Returns
 * -------
 *  edu_tuition_status_t : The business-level outcome.  Detailed error
 *  information (gateway messages, fraud reasons, etc.) is copied into
 *  `response->error_msg` for logging / display purposes.
 */
static inline edu_tuition_status_t
process_tuition_payment(
        const process_tuition_payment_interactor_t *interactor,
        const process_tuition_payment_request_t    *request,
        process_tuition_payment_response_t         *response)
{
    /*──────────────────── Argument Validation ────────────────────*/
    if (!interactor || !request || !response ||
        !interactor->fraud_check ||
        !interactor->reserve_funds ||
        !interactor->post_ledger) {
        if (response) {
            response->status = EDUPAY_TUITION_ERR_INVALID_ARG;
            strncpy(response->error_msg,
                    "Null argument passed to process_tuition_payment",
                    EDUPAY_MAX_ERROR_MSG_LENGTH);
        }
        return EDUPAY_TUITION_ERR_INVALID_ARG;
    }

    /* Zero-initialise response */
    memset(response, 0, sizeof(*response));
    response->status = EDUPAY_TUITION_OK;

    /*──────────────────── Currency Whitelist ─────────────────────*/
    const char *supported[] = { "USD", "EUR", "GBP", "JPY", "AUD", NULL };
    bool currency_ok = false;
    for (size_t i = 0; supported[i]; ++i)
        if (strncmp(request->currency, supported[i], 3) == 0) {
            currency_ok = true;
            break;
        }
    if (!currency_ok) {
        response->status = EDUPAY_TUITION_ERR_CURRENCY_UNSUPPORTED;
        snprintf(response->error_msg, EDUPAY_MAX_ERROR_MSG_LENGTH,
                 "Currency %s not supported", request->currency);
        return response->status;
    }

    /*──────────────────── Fraud Detection ────────────────────────*/
    char fraud_reason[EDUPAY_MAX_ERROR_MSG_LENGTH] = {0};
    if (!interactor->fraud_check(request, fraud_reason)) {
        response->status = EDUPAY_TUITION_ERR_FRAUD_FLAGGED;
        snprintf(response->error_msg, EDUPAY_MAX_ERROR_MSG_LENGTH,
                 "Fraud check failed: %s", fraud_reason);
        /* Audit even fraud-blocked attempts.  Swallow failure. */
        if (interactor->write_audit)
            interactor->write_audit("TUITION_PAYMENT_FRAUD_BLOCKED",
                                    request, sizeof(*request));
        return response->status;
    }

    /*──────────────────── Reserve Funds ──────────────────────────*/
    char gateway_error[EDUPAY_MAX_ERROR_MSG_LENGTH] = {0};
    if (!interactor->reserve_funds(request,
            response->transaction_id,
            gateway_error)) {

        response->status = EDUPAY_TUITION_ERR_GATEWAY_DECLINED;
        snprintf(response->error_msg, EDUPAY_MAX_ERROR_MSG_LENGTH,
                 "Payment gateway declined transaction: %s", gateway_error);

        /* Write audit asynchronously; ignore failures */
        if (interactor->write_audit)
            interactor->write_audit("TUITION_PAYMENT_DECLINED",
                                    response, sizeof(*response));
        return response->status;
    }

    /*──────────────────── Ledger Posting ─────────────────────────*/
    char ledger_error[EDUPAY_MAX_ERROR_MSG_LENGTH] = {0};
    if (!interactor->post_ledger(response->transaction_id,
                                 request,
                                 ledger_error)) {
        response->status = EDUPAY_TUITION_ERR_LEDGER_FAILURE;
        snprintf(response->error_msg, EDUPAY_MAX_ERROR_MSG_LENGTH,
                 "Ledger persistence failure: %s", ledger_error);

        /* Attempt compensating action: TODO implement Saga rollback */
        /* For lecture purposes we log but do not roll back funds here. */

        if (interactor->write_audit)
            interactor->write_audit("TUITION_PAYMENT_LEDGER_FAILURE",
                                    response, sizeof(*response));
        return response->status;
    }

    /*──────────────────── Audit Trail ────────────────────────────*/
    if (interactor->write_audit &&
        !interactor->write_audit("TUITION_PAYMENT_COMPLETED",
                                 response, sizeof(*response))) {

        /* Payment still succeeded, but we report audit failure. */
        response->status = EDUPAY_TUITION_ERR_AUDIT_FAILURE;
        snprintf(response->error_msg, EDUPAY_MAX_ERROR_MSG_LENGTH,
                 "Audit trail write failed for txn %s",
                 response->transaction_id);
        /* Do NOT roll back payment on audit failure per PCI guidance. */
    }

    return response->status;
}

#ifdef __cplusplus
}
#endif
#endif /* EDUPAY_LEDGER_ACADEMY_BURSAR_PROCESS_TUITION_PAYMENT_H */
