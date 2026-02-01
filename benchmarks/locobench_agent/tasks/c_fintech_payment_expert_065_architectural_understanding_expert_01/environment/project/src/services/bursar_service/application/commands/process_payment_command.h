/*
 *  process_payment_command.h
 *  EduPay Ledger Academy – Bursar Service
 *
 *  Description:
 *      Application-layer command object + helpers used by the Bursar-Service
 *      to request that a new tuition / fee payment be processed.  The command
 *      is intentionally kept framework-agnostic to comply with Clean
 *      Architecture guidelines:  no direct dependency on databases,
 *      queues, or HTTP libraries is introduced here.
 *
 *      The command carries only the data required to execute the use-case and
 *      exposes light-weight validation routines so that the Application
 *      Service can fail fast before delegating to the Domain layer or a
 *      Command-Handler executed in a dedicated worker thread.
 *
 *      NOTE:  This header is self-contained.  All helper functions are `static
 *      inline` so that other translation units can include it without the need
 *      for an accompanying “.c” file.  This trades a small amount of code
 *      bloat for easier portability in a micro-service context.
 *
 *  Copyright:
 *      (c) 2024 EduPay Ledger Academy – All Rights Reserved
 *      SPDX-License-Identifier: MPL-2.0
 */

#ifndef EDUPAY_BURSAR_APP_COMMANDS_PROCESS_PAYMENT_COMMAND_H
#define EDUPAY_BURSAR_APP_COMMANDS_PROCESS_PAYMENT_COMMAND_H

/* ────────────────────────────────────────────────────────────────────────── */
/* System headers                                                            */
#include <stdint.h>     /* int64_t, uint32_t                                 */
#include <stdbool.h>    /* bool                                              */
#include <stddef.h>     /* size_t                                            */
#include <stdlib.h>     /* malloc, free                                      */
#include <string.h>     /* memcpy, memset, strncpy                           */
#include <time.h>       /* time_t, CLOCK_REALTIME                            */
#include <errno.h>      /* EINVAL, ERANGE                                    */

/* ────────────────────────────────────────────────────────────────────────── */
/* Macro utilities                                                           */
#define PPC_STATIC_ASSERT(expr, msg) typedef char msg[(expr) ? 1 : -1]

/* ────────────────────────────────────────────────────────────────────────── */
/* Constants                                                                 */
enum
{
    PPC_MAX_ID_LEN          = 64,   /* Student / Account / Correlation IDs          */
    PPC_MAX_TRACE_ID_LEN    = 64,   /* Trace / Span IDs for distributed tracing      */
    PPC_MAX_CCY_LEN         = 4,    /* ISO-4217 (3 letters + NULL)                  */
    PPC_MAX_ERRBUF          = 128   /* Generic error buffer size                    */
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Error Codes specific to ProcessPaymentCommand                             */
typedef enum ppc_error_e
{
    PPC_OK = 0,
    PPC_EINVAL,           /* Generic invalid argument                         */
    PPC_EOVERFLOW,        /* Value out of range                               */
    PPC_EUNSUPPORTED,     /* Unsupported currency / payment type              */
    PPC_EAMOUNT_NEGATIVE  /* Negative amount not allowed                      */
} ppc_error_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Monetary value object (value-semantics, immutable after init)             */
typedef struct ppc_money_s
{
    int64_t     minor_units;                /* For USD cents, EUR cents, etc.        */
    char        currency[PPC_MAX_CCY_LEN];  /* 3-char ISO code, NULL-terminated      */
} ppc_money_t;

static inline ppc_money_t
ppc_money_make(int64_t minor_units, const char *iso_currency)
{
    ppc_money_t m = { .minor_units = minor_units };
    if (iso_currency != NULL)
    {
        strncpy(m.currency, iso_currency, PPC_MAX_CCY_LEN - 1);
        m.currency[PPC_MAX_CCY_LEN - 1] = '\0';
    }
    else
    {
        m.currency[0] = '\0';
    }
    return m;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Flags for optional payment behaviors                                      */
typedef enum ppc_flags_e
{
    PPC_FLAG_NONE              = 0x00000000u,
    PPC_FLAG_MFA_REQUIRED      = 0x00000001u,   /* Multi-Factor Auth required        */
    PPC_FLAG_FORCE_SETTLEMENT  = 0x00000002u,   /* Bypass risk checks (admin only!)  */
    PPC_FLAG_SAGA_STEP         = 0x00000004u    /* Part of ongoing Saga transaction  */
} ppc_flags_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* ProcessPaymentCommand DTO                                                 */
typedef struct process_payment_command_s
{
    char            student_id[PPC_MAX_ID_LEN];
    char            account_id[PPC_MAX_ID_LEN];
    char            correlation_id[PPC_MAX_ID_LEN];
    char            trace_id[PPC_MAX_TRACE_ID_LEN];  /* OpenTelemetry trace linkage */

    ppc_money_t     amount;             /* Immutable monetary value                 */
    time_t          request_ts;         /* Request creation time                    */
    time_t          due_date;           /* Optional future execution (0 = immediate)*/

    uint32_t        flags;              /* See ppc_flags_t                          */
    /* Extensible metadata map could be added here with a pointer ‑ excluded
       to keep the struct POD-like and easy to serialize inside the course.    */
} process_payment_command_t;

/* Validate field size assumptions at compile-time                            */
PPC_STATIC_ASSERT(sizeof(process_payment_command_t) <
                  512, process_payment_command_must_remain_small);

/* ────────────────────────────────────────────────────────────────────────── */
/* Helper Functions (inline for header-only distribution)                    */

/*
 *  ppc_validate_iso_currency():
 *      Minimal ISO-4217 upper-case alpha-3 validation.  This intentionally
 *      does NOT check against a whitelist to avoid hardcoding currencies in
 *      the application layer.  Domain layer will perform full validation.
 */
static inline bool
ppc_validate_iso_currency(const char *ccy)
{
    if (!ccy || strlen(ccy) != 3)
        return false;

    for (size_t i = 0; i < 3; ++i)
    {
        if (ccy[i] < 'A' || ccy[i] > 'Z')
            return false;
    }
    return true;
}

/*
 *  process_payment_command_init():
 *      Populate a command instance and perform light validation so that
 *      callers do not accidentally create malformed objects.
 *
 *      Parameters:
 *          cmd         (out)   Pre-allocated struct to populate
 *          student_id  (in)    Student identifier (NULL-terminated)
 *          account_id  (in)    Ledger / wallet identifier
 *          amount      (in)    Monetary value object
 *          correlation (in)    Correlation ID for idempotency ‑ optional
 *          trace_id    (in)    Distributed tracing ID               ‑ optional
 *          due_date    (in)    Epoch seconds at which payment executes
 *          flags       (in)    Command flags
 *          errbuf      (out)   Optional buffer for human-readable error
 *          errlen      (in)    Size of errbuf
 *
 *      Returns:
 *          PPC_OK on success, otherwise error-code.
 */
static inline ppc_error_t
process_payment_command_init(process_payment_command_t *cmd,
                             const char *student_id,
                             const char *account_id,
                             ppc_money_t amount,
                             const char *correlation,
                             const char *trace_id,
                             time_t due_date,
                             uint32_t flags,
                             char *errbuf,
                             size_t errlen)
{
    if (cmd == NULL || student_id == NULL || account_id == NULL)
        return PPC_EINVAL;

    if (snprintf(cmd->student_id, sizeof(cmd->student_id), "%s", student_id) >=
        (int)sizeof(cmd->student_id))
    {
        if (errbuf && errlen)
            strncpy(errbuf, "student_id too long", errlen - 1);
        return PPC_EOVERFLOW;
    }

    if (snprintf(cmd->account_id, sizeof(cmd->account_id), "%s", account_id) >=
        (int)sizeof(cmd->account_id))
    {
        if (errbuf && errlen)
            strncpy(errbuf, "account_id too long", errlen - 1);
        return PPC_EOVERFLOW;
    }

    if (correlation && *correlation)
    {
        if (snprintf(cmd->correlation_id, sizeof(cmd->correlation_id), "%s",
                     correlation) >= (int)sizeof(cmd->correlation_id))
        {
            if (errbuf && errlen)
                strncpy(errbuf, "correlation_id too long", errlen - 1);
            return PPC_EOVERFLOW;
        }
    }
    else
    {
        cmd->correlation_id[0] = '\0';
    }

    if (trace_id && *trace_id)
    {
        if (snprintf(cmd->trace_id, sizeof(cmd->trace_id), "%s",
                     trace_id) >= (int)sizeof(cmd->trace_id))
        {
            if (errbuf && errlen)
                strncpy(errbuf, "trace_id too long", errlen - 1);
            return PPC_EOVERFLOW;
        }
    }
    else
    {
        cmd->trace_id[0] = '\0';
    }

    /* Monetary sanity checks */
    if (amount.minor_units <= 0)
    {
        if (errbuf && errlen)
            strncpy(errbuf, "amount must be positive", errlen - 1);
        return PPC_EAMOUNT_NEGATIVE;
    }

    if (!ppc_validate_iso_currency(amount.currency))
    {
        if (errbuf && errlen)
            strncpy(errbuf, "invalid ISO-4217 currency", errlen - 1);
        return PPC_EUNSUPPORTED;
    }
    cmd->amount = amount;
    cmd->flags  = flags;
    cmd->due_date = due_date;
    cmd->request_ts = time(NULL);

    return PPC_OK;
}

/*
 *  process_payment_command_is_valid():
 *      Perform additional validation that may be required just before the
 *      command is executed.  This is separated from _init() so that tests
 *      can mutate the command struct (e.g. tamper scenarios) and re-validate
 *      without constructing a new object.
 *
 *      Returns:
 *          true  -> looks sane
 *          false -> invalid; details in errbuf if provided
 */
static inline bool
process_payment_command_is_valid(const process_payment_command_t *cmd,
                                 char *errbuf,
                                 size_t errlen)
{
    if (!cmd)
        return false;

    if (cmd->student_id[0] == '\0')
    {
        if (errbuf && errlen)
            strncpy(errbuf, "missing student_id", errlen - 1);
        return false;
    }

    if (cmd->account_id[0] == '\0')
    {
        if (errbuf && errlen)
            strncpy(errbuf, "missing account_id", errlen - 1);
        return false;
    }

    if (cmd->amount.minor_units <= 0)
    {
        if (errbuf && errlen)
            strncpy(errbuf, "amount must be positive", errlen - 1);
        return false;
    }

    if (!ppc_validate_iso_currency(cmd->amount.currency))
    {
        if (errbuf && errlen)
            strncpy(errbuf, "invalid currency code", errlen - 1);
        return false;
    }

    /* Example business rule:  cannot force settlement AND require MFA */
    if ((cmd->flags & PPC_FLAG_FORCE_SETTLEMENT) &&
        (cmd->flags & PPC_FLAG_MFA_REQUIRED))
    {
        if (errbuf && errlen)
            strncpy(errbuf, "mutually exclusive flags set", errlen - 1);
        return false;
    }

    return true;
}

/*
 *  process_payment_command_clear():
 *      Zero-out all fields to protect sensitive data before freeing or
 *      re-using the struct.  Although most fields are not secret, we teach
 *      students to wipe memory that might contain personally identifiable
 *      information (PII) or payment data.
 */
static inline void
process_payment_command_clear(process_payment_command_t *cmd)
{
    if (cmd)
        memset(cmd, 0, sizeof(*cmd));
}

#endif /* EDUPAY_BURSAR_APP_COMMANDS_PROCESS_PAYMENT_COMMAND_H */
