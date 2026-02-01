#ifndef EDU_PAY_LEDGER_ACADEMY_SERVICES_FINANCIAL_AID_DOMAIN_STIPEND_H
#define EDU_PAY_LEDGER_ACADEMY_SERVICES_FINANCIAL_AID_DOMAIN_STIPEND_H
/**
 * @file stipend.h
 * @author
 * @brief Domain entity and business-rule interface for Financial-Aid stipends.
 *
 * This header belongs to the innermost Clean-Architecture layer.  NOTHING in
 * this file should depend on infrastructure, frameworks, databases, or
 * serialization libraries.  All constructs are pure business logic so that
 * professors may freely swap out outer layers during coursework.
 */

#include <stdint.h>     /* uint64_t, uint32_t */
#include <stddef.h>     /* size_t              */
#include <stdbool.h>    /* bool                */
#include <time.h>       /* time_t              */

#ifdef __cplusplus
extern "C" {
#endif

/*---------------------------------------------------------------------------*/
/* Public constants                                                          */
/*---------------------------------------------------------------------------*/

#define STIPEND_CURRENCY_CODE_LEN  3  /* ISO-4217 alpha-3 (e.g., "USD")       */
#define STIPEND_ID_MAX_LEN        64  /* UUID v4 or ULID (ASCII)              */
#define STIPEND_STUDENT_ID_LEN    64
#define STIPEND_GHOST_FIELD_BYTES 16  /* Padding for forward compatibility    */

/*---------------------------------------------------------------------------*/
/* Enumerations                                                              */
/*---------------------------------------------------------------------------*/

/**
 * @brief States in the stipend lifecycle.
 *
 * Transitions (happy path):
 *  PENDING -> APPROVED -> DISBURSED
 *
 * Failure & exception paths:
 *  PENDING -> CANCELLED
 *  APPROVED -> FAILED
 */
typedef enum stipend_status_e
{
    STIPEND_STATUS_UNKNOWN   = 0,
    STIPEND_STATUS_PENDING   = 1,
    STIPEND_STATUS_APPROVED  = 2,
    STIPEND_STATUS_DISBURSED = 3,
    STIPEND_STATUS_FAILED    = 4,
    STIPEND_STATUS_CANCELLED = 5
} stipend_status_t;

/**
 * @brief Domain-level error codes.
 *
 * NOTE: Keep this list entirely decoupled from HTTP, gRPC, POSIX errno, etc.
 */
typedef enum stipend_error_e
{
    STIPEND_SUCCESS                = 0,
    STIPEND_ERR_NULL_ARGUMENT      = 1,
    STIPEND_ERR_BAD_STATE          = 2,
    STIPEND_ERR_VALIDATION         = 3,
    STIPEND_ERR_INSUFFICIENT_FUNDS = 4,
    STIPEND_ERR_OVERFLOW           = 5,
    STIPEND_ERR_CONCURRENCY        = 6,
    STIPEND_ERR_UNSUPPORTED        = 7
} stipend_error_t;

/*---------------------------------------------------------------------------*/
/* Value objects                                                             */
/*---------------------------------------------------------------------------*/

/**
 * @brief Monetary value represented in the smallest currency unit (minor unit)
 *        to preserve precision and avoid IEEE-754 rounding errors.
 *
 * Example: USD 1.23  =>  amount_minor = 123, exponent = 2
 */
typedef struct money_s
{
    int64_t  amount_minor;                              /* Signed 64-bit cents  */
    uint8_t  exponent;                                  /* # decimal places     */
    char     currency[STIPEND_CURRENCY_CODE_LEN + 1];   /* NUL-terminated ISO   */
} money_t;

/*---------------------------------------------------------------------------*/
/* Aggregate root: Stipend                                                   */
/*---------------------------------------------------------------------------*/

typedef struct stipend_s
{
    char             stipend_id[STIPEND_ID_MAX_LEN + 1];     /* Primary key   */
    char             student_id[STIPEND_STUDENT_ID_LEN + 1]; /* FK -> Student */
    money_t          value;                                  /* Monetary data */
    stipend_status_t status;

    time_t           disbursement_date;   /* Unix epoch secs; 0 when unset     */
    time_t           created_at;          /* Audit purposes                    */
    time_t           updated_at;

    uint32_t         revision;            /* Optimistic concurrency control    */

    uint8_t          _reserved[STIPEND_GHOST_FIELD_BYTES];   /* Extensibility */
} stipend_t;

/*---------------------------------------------------------------------------*/
/* Business-rule interface                                                   */
/*---------------------------------------------------------------------------*/

/**
 * @brief Initialize a stipend with default values.
 *
 * Callers must pass an already-allocated stipend_t*.
 *
 * @param out_stipend  Non-NULL pointer to stipend_t to be initialized.
 * @return STIPEND_SUCCESS or STIPEND_ERR_NULL_ARGUMENT.
 */
stipend_error_t stipend_init(stipend_t *out_stipend);

/**
 * @brief Validate a stipend entity.
 *
 * Ensures IDs are non-empty, currency conforms to ISO-4217, etc.
 *
 * @param s A pointer to a fully-populated stipend.
 * @return STIPEND_SUCCESS on success, STIPEND_ERR_VALIDATION otherwise.
 */
stipend_error_t stipend_validate(const stipend_t *s);

/**
 * @brief Approve a stipend.
 *
 * Business rule:
 *   PENDING  -> APPROVED   (allowed)
 *   otherwise -> error
 *
 * @param s Pointer to stipend to mutate.
 * @param approved_by_user_id User performing approval (for audit trail).
 */
stipend_error_t stipend_approve(stipend_t *s, const char *approved_by_user_id);

/**
 * @brief Cancel a stipend prior to approval/disbursement.
 *
 * Allowed transitions:
 *   PENDING -> CANCELLED
 *
 * @param s Pointer to stipend to mutate.
 * @param reason Human-readable cancellation reason (optional).
 */
stipend_error_t stipend_cancel(stipend_t *s, const char *reason);

/**
 * @brief Mark a stipend as disbursed.
 *
 * Valid transition:
 *   APPROVED -> DISBURSED
 *
 * Additional rule:
 *   disbursement_date must be <= now + 24 hours (future-dated batch).
 */
stipend_error_t stipend_disburse(
    stipend_t *s,
    time_t     settled_at,              /* Usually `time(NULL)`               */
    const char *transaction_ref         /* Payment rail reference ID          */
);

/**
 * @brief Mark an approved stipend as failed.
 *
 * Valid transition:
 *   APPROVED -> FAILED
 */
stipend_error_t stipend_fail(stipend_t *s, const char *failure_reason);

/**
 * @brief Compute hash-based identifier (e.g., SHA-256 truncated) for idempotency.
 *
 * The resulting digest is implementation-defined and **NOT** a security feature.
 *
 * @param s          Non-NULL pointer to stipend.
 * @param out_digest Buffer to receive digest bytes.
 * @param digest_len IN: length of out_digest; OUT: bytes written.
 */
stipend_error_t stipend_compute_digest(
    const stipend_t *s,
    uint8_t         *out_digest,
    size_t          *digest_len);

/*---------------------------------------------------------------------------*/
/* Inline helpers                                                            */
/*---------------------------------------------------------------------------*/

/**
 * @brief True if stipend is terminal (cannot change state further).
 */
static inline bool stipend_is_terminal(const stipend_t *s)
{
    return s
           && (s->status == STIPEND_STATUS_DISBURSED
               || s->status == STIPEND_STATUS_FAILED
               || s->status == STIPEND_STATUS_CANCELLED);
}

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* EDU_PAY_LEDGER_ACADEMY_SERVICES_FINANCIAL_AID_DOMAIN_STIPEND_H */
