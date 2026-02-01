#ifndef EDU_PAY_LEDGER_ACADEMY_DISBURSE_STIPEND_COMMAND_H
#define EDU_PAY_LEDGER_ACADEMY_DISBURSE_STIPEND_COMMAND_H
/**
 * Disburse Stipend Command
 * ---------------------------------------------------------------
 * Located in: services/financial_aid_service/application/commands
 *
 * This header defines an immutable command that instructs the domain
 * model to disburse a stipend to a recipient (student, faculty, or
 * research assistant).  Commands are write-side messages in the CQRS
 * pattern and are ‑ by convention ‑ validated before entering the
 * domain layer.  They are intentionally free of any framework
 * dependencies so that educators can swap adapters without modifying
 * core business rules.
 *
 * The command is purposefully designed for multi-currency support and
 * FERPA-aware audit-trail logging.  All monetary values are expressed
 * in minor units (i.e. cents) to avoid floating-point drift.
 *
 * Thread-Safety:
 *  - Struct is immutable after successful initialization.
 *  - All functions are re-entrant and do not retain global state.
 */

#include <stdint.h>     /* int64_t                            */
#include <stddef.h>     /* size_t                             */
#include <time.h>       /* time_t                             */
#include <errno.h>      /* errno_t for POSIX-style error codes*/

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * Domain-Primitive: uuid_t
 *    A 16-byte RFC-4122 compliant Universally Unique Identifier.
 *    In production, this would live in a shared utility library.
 * -------------------------------------------------------------------------*/
typedef struct
{
    uint8_t bytes[16];
} uuid_t;

/* Generates a version-4 UUID in an opaque manner.  The implementation is
 * platform specific and therefore only declared here.                       */
int uuid_v4_generate(uuid_t *out);
int uuid_is_nil(const uuid_t *id);

/* -------------------------------------------------------------------------
 * Domain-Primitive: money_t
 *    Immutable monetary representation with ISO-4217 alpha currency code.
 * -------------------------------------------------------------------------*/
typedef struct
{
    int64_t  amount;            /* minor units (e.g. cents, satoshi, etc.)  */
    char     currency[4];       /* "USD", "EUR" … NUL-terminated            */
} money_t;

/**
 * Creates a money_t value.  Returns 0 on success, else EINVAL/ERANGE.
 * Currency must be a 3-character ISO-4217 alpha code.
 */
int money_create(int64_t amount_minor,
                 const char currency[4],
                 money_t *out);

/**
 * Validates a money_t instance.  Returns 0 if valid, else EINVAL.
 */
int money_validate(const money_t *m);


/* -------------------------------------------------------------------------
 * Error Codes specific to DisburseStipendCommand
 * -------------------------------------------------------------------------*/
enum disburse_stipend_cmd_error
{
    DSC_OK            = 0,   /* success                                */
    DSC_EINVAL        = EINVAL,
    DSC_EOVERFLOW     = EOVERFLOW,
    DSC_ENULLPTR      = EFAULT,
    DSC_EUUID_NIL     = 2001,/* stipend_id or student_id is nil        */
    DSC_EMONEY        = 2002,/* money_validate failed                  */
    DSC_EPASTDUE_DATE = 2003 /* disbursement_date in the past          */
};

/* -------------------------------------------------------------------------
 * DisburseStipendCommand
 * -------------------------------------------------------------------------*/
typedef struct
{
    uuid_t  stipend_id;        /* idempotency key for duplicates ck       */
    uuid_t  student_id;        /* FERPA PII stored only in audit ledger   */
    money_t amount;            /* multi-currency amount                   */
    time_t  disbursement_date; /* epoch secs (UTC).  Must be >= now.      */
    uuid_t  trace_id;          /* correlated with Audit_Trail event       */
} DisburseStipendCommand;


/* -------------------------------------------------------------------------
 * API
 * -------------------------------------------------------------------------*/

/**
 * Initializes a DisburseStipendCommand with full validation.
 *
 * On success, the output struct is fully populated and immutable.
 * On failure, the struct contents are undefined and an error code is
 * returned (see enum disburse_stipend_cmd_error).
 *
 * Parameters:
 *  - cmd                : output struct pointer (must not be NULL)
 *  - stipend_id         : non-nil uuid identifying the stipend record
 *  - student_id         : non-nil uuid for recipient
 *  - amount             : pointer to valid money_t instance
 *  - disbursement_date  : UTC epoch seconds when funds will be released
 *  - trace_id           : correlation id for distributed tracing
 *
 * Returns:
 *  - DSC_OK on success
 *  - DSC_E*  on failure
 */
int disburse_stipend_command_init(
        DisburseStipendCommand *cmd,
        const uuid_t           *stipend_id,
        const uuid_t           *student_id,
        const money_t          *amount,
        time_t                  disbursement_date,
        const uuid_t           *trace_id);


/**
 * Validates an already populated DisburseStipendCommand.
 * Use this when a command is (de)serialized across process boundaries.
 *
 * Returns DSC_OK or a DSC_E* error code.
 */
int disburse_stipend_command_validate(const DisburseStipendCommand *cmd);


/* -------------------------------------------------------------------------
 * Inline/Static Implementations
 * -------------------------------------------------------------------------*/
#ifndef DISBURSE_STIPEND_COMMAND_IMPLEMENTATION
#define DISBURSE_STIPEND_COMMAND_IMPLEMENTATION

#include <string.h>   /* memcpy, memset */
#include <limits.h>   /* INT64_MAX      */

static inline int _validate_uuid_non_nil(const uuid_t *id)
{
    return (id == NULL || uuid_is_nil(id)) ? DSC_EUUID_NIL : DSC_OK;
}

static inline int disburse_stipend_command_validate(
        const DisburseStipendCommand *cmd)
{
    if (cmd == NULL) return DSC_ENULLPTR;

    /* Validate UUID fields */
    if (_validate_uuid_non_nil(&cmd->stipend_id) != DSC_OK) return DSC_EUUID_NIL;
    if (_validate_uuid_non_nil(&cmd->student_id) != DSC_OK) return DSC_EUUID_NIL;
    if (_validate_uuid_non_nil(&cmd->trace_id)   != DSC_OK) return DSC_EUUID_NIL;

    /* Validate money */
    int rc = money_validate(&cmd->amount);
    if (rc != 0) return DSC_EMONEY;

    /* Disbursement date must not be in the past (5-min tolerance) */
    time_t now = time(NULL);
    if (now == (time_t)-1) return DSC_EINVAL; /* time failure fall-through  */
    if (cmd->disbursement_date + 300 < now) /* 300 sec grace window */
        return DSC_EPASTDUE_DATE;

    return DSC_OK;
}

static inline int disburse_stipend_command_init(
        DisburseStipendCommand *cmd,
        const uuid_t           *stipend_id,
        const uuid_t           *student_id,
        const money_t          *amount,
        time_t                  disbursement_date,
        const uuid_t           *trace_id)
{
    if (!cmd || !stipend_id || !student_id || !amount || !trace_id)
        return DSC_ENULLPTR;

    /* Shallow validation for incoming args */
    if (_validate_uuid_non_nil(stipend_id) != DSC_OK) return DSC_EUUID_NIL;
    if (_validate_uuid_non_nil(student_id) != DSC_OK) return DSC_EUUID_NIL;
    if (_validate_uuid_non_nil(trace_id)   != DSC_OK) return DSC_EUUID_NIL;

    int rc = money_validate(amount);
    if (rc != 0) return DSC_EMONEY;

    /* Populate struct; memcpy for fixed-size primitives. */
    memcpy(&cmd->stipend_id, stipend_id, sizeof(uuid_t));
    memcpy(&cmd->student_id, student_id, sizeof(uuid_t));
    memcpy(&cmd->trace_id,   trace_id,   sizeof(uuid_t));
    memcpy(&cmd->amount,     amount,     sizeof(money_t));
    cmd->disbursement_date = disbursement_date;

    /* Full validation pass to guarantee invariants */
    return disburse_stipend_command_validate(cmd);
}

#endif /* DISBURSE_STIPEND_COMMAND_IMPLEMENTATION */

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* EDU_PAY_LEDGER_ACADEMY_DISBURSE_STIPEND_COMMAND_H */
