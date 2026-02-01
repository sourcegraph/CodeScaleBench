#ifndef EDUPAY_LEDGER_ACADEMY_FINANCIAL_AID_APPLICATION_USE_CASES_VERIFY_KYC_H
#define EDUPAY_LEDGER_ACADEMY_FINANCIAL_AID_APPLICATION_USE_CASES_VERIFY_KYC_H
/*
 * verify_kyc.h
 *
 * EduPay Ledger Academy – Financial-Aid Service
 *
 * Clean-Architecture “use-case interactor” for Know-Your-Customer (KYC)
 * verification.  Sits in the application layer and orchestrates domain
 * operations by delegating to input/output ports supplied at runtime.
 *
 * ┌──────────────────────────────────────┐
 * │         Application Layer           │
 * │  (orchestrates domain operations)   │
 * ├──────────────────┬───────────────────┤
 * │      Ports       │     Interactor    │
 * └──────────────────┴───────────────────┘
 *
 * This header intentionally contains no implementation details specific to
 * storage, transport, or cryptography.  Those concerns are injected through
 * the port interfaces below, keeping the core domain isolated and easily
 * swappable for coursework experiments.
 */

#include <stddef.h>   /* size_t   */
#include <stdint.h>   /* uint64_t */
#include <stdbool.h>  /* bool     */

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------------- */
/*                           Compile-time constants                          */
/* ------------------------------------------------------------------------- */

#define KYC_MAX_NAME_LENGTH          64U
#define KYC_MAX_COUNTRY_CODE_LENGTH   3U   /* ISO-3166-1 alpha-2 or alpha-3 */
#define KYC_MAX_FAILURE_REASON_LEN  256U
#define KYC_SESSION_TRACE_ID_LEN     36U   /* UUID-v4 string */

/* ------------------------------------------------------------------------- */
/*                                Data Types                                 */
/* ------------------------------------------------------------------------- */

/* High-level status returned by the interactor */
typedef enum kyc_status_e
{
    KYC_STATUS_PENDING = 0,   /* Asynchronous vendor call in progress */
    KYC_STATUS_APPROVED,
    KYC_STATUS_REJECTED,
    KYC_STATUS_RETRYABLE_ERROR,
    KYC_STATUS_FATAL_ERROR
} kyc_status_t;

/* Error domain internal to the interactor */
typedef enum kyc_error_e
{
    KYC_ERROR_NONE = 0,
    KYC_ERROR_INVALID_ARGUMENT,
    KYC_ERROR_DEPENDENCY_FAILURE,
    KYC_ERROR_POLICY_VIOLATION,
    KYC_ERROR_UNEXPECTED
} kyc_error_t;

/* Request DTO passed in from controllers / API adapters */
typedef struct kyc_verification_request_s
{
    char    student_id[32];                           /* internal student identifier */
    char    legal_first_name[KYC_MAX_NAME_LENGTH];
    char    legal_last_name[KYC_MAX_NAME_LENGTH];
    char    date_of_birth_iso8601[11];                /* YYYY-MM-DD */
    char    government_id_last4[5];                   /* last 4 digits of SSN / NID */
    char    country_code[KYC_MAX_COUNTRY_CODE_LENGTH];
    char    session_trace_id[KYC_SESSION_TRACE_ID_LEN + 1];
} kyc_verification_request_t;

/* Response DTO returned to controllers / API adapters */
typedef struct kyc_verification_response_s
{
    kyc_status_t status;
    char         failure_reason[KYC_MAX_FAILURE_REASON_LEN];
    /* When status == PENDING, caller may poll or subscribe to the event bus
       for KYC_VERIFICATION_COMPLETED(domain_event) */
} kyc_verification_response_t;

/* ------------------------------------------------------------------------- */
/*                              Output Port (SPI)                            */
/* ------------------------------------------------------------------------- */
/*
 * The interactor depends on the following “secondary ports” to fulfill its
 * use-case.  Implementations live in the infrastructure layer (e.g. REST
 * client to an external KYC vendor, SQL repository, message broker, etc.)
 *
 * All functions must be non-blocking.  If an operation might take longer
 * (e.g. network I/O), call-sites MUST enqueue work onto their own async
 * runtime and return KYC_ERROR_NONE immediately.  (For teaching purposes,
 * a synchronous demo adapter is included elsewhere in the repo.)
 */

typedef struct kyc_output_port_s
{
    /* Check that the student does not appear on OFAC/UN lists                */
    kyc_error_t (*screen_sanctions_and_watchlists)(
        const kyc_verification_request_t *req,
        bool                              *is_clear /* out parameter */
    );

    /* Verify government ID / Date-of-Birth against vendor data               */
    kyc_error_t (*verify_government_id)(
        const kyc_verification_request_t *req,
        bool                              *is_match /* out parameter */
    );

    /* Persist audit trail event  (immutable, append-only)                    */
    kyc_error_t (*append_audit_log)(
        const char *student_id,
        const char *event_name,
        const char *payload_json,
        uint64_t   *out_sequence_number /* monotonically increasing seq-id */
    );

    /* Publish domain event for other bounded contexts / microservices        */
    kyc_error_t (*publish_domain_event)(
        const char *event_name,
        const char *payload_json,
        const char *trace_id
    );
} kyc_output_port_t;

/* ------------------------------------------------------------------------- */
/*                              Input Port (API)                             */
/* ------------------------------------------------------------------------- */
/*
 * The interactor exposes a single, procedural API.  Frameworks such as gRPC,
 * REST, CLI, or GraphQL can adapt to this contract without modifying the
 * core business logic.
 */

typedef struct verify_kyc_interactor_s verify_kyc_interactor_t;

/* Factory: returns NULL on allocation failure */
verify_kyc_interactor_t *
verify_kyc_interactor_create(const kyc_output_port_t *out_port);

/* Dependency Injection (optional hot-swap for unit tests)                   */
void
verify_kyc_interactor_set_output_port(
    verify_kyc_interactor_t   *self,
    const kyc_output_port_t   *out_port
);

/* Main use-case execution.  Thread-safe; no global state.                   */
kyc_error_t
verify_kyc_interactor_execute(
    verify_kyc_interactor_t               *self,
    const kyc_verification_request_t      *request,
    kyc_verification_response_t           *response /* out parameter */
);

/* Clean-up resources */
void
verify_kyc_interactor_destroy(verify_kyc_interactor_t *self);

/* ------------------------------------------------------------------------- */
/*                               Helper Utils                                */
/* ------------------------------------------------------------------------- */
/*
 * Convenience utility for mapping internal error codes to human-readable
 * strings.  Callers MUST NOT free the returned pointer.
 */
const char *
kyc_error_to_string(kyc_error_t err);

/*
 * Translates status codes for logging / telemetry.
 */
const char *
kyc_status_to_string(kyc_status_t status);

#ifdef __cplusplus
}
#endif

#endif /* EDUPAY_LEDGER_ACADEMY_FINANCIAL_AID_APPLICATION_USE_CASES_VERIFY_KYC_H */