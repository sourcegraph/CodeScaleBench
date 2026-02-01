/**
 * @file account.h
 *
 * @brief  Domain Model:  Bursar ‑ Ledger Account Aggregate
 *
 * The Account aggregate is the canonical representation of a student’s financial
 * ledger inside the Bursar bounded-context.  It is intentionally persistence-agnostic
 * (Clean Architecture) and contains only business rules.  Orchestration with
 * payments gateways, SQL/NoSQL stores, or message brokers is delegated to the
 * outer “infrastructure” layer.
 *
 * Thread-Safety:
 *  – All mutating functions receive a pointer to the aggregate instance and MUST
 *    be protected by the calling application’s concurrency strategy
 *    (mutex, actor model, etc.).  The domain layer purposefully remains
 *    synchronization-free to avoid bleeding implementation details inward.
 *
 * Monetary Representation:
 *  – Amounts are stored as signed 64-bit integers representing the smallest
 *    denomination (“minor units”, e.g. cents) to avoid floating-point error.
 *  – The currency is an ISO-4217 alpha code held in a fixed-length char array.
 *
 * Copyright © 2024
 * EduPay Ledger Academy – All rights reserved.
 */

#ifndef EDUPAY_LEDGER_ACADEMY_BURSAR_ACCOUNT_H
#define EDUPAY_LEDGER_ACADEMY_BURSAR_ACCOUNT_H

/* ─────────────────────────────────────────────────────────────────────────── */
/*  Standard Library                                                          */
/* ─────────────────────────────────────────────────────────────────────────── */
#include <stdint.h>     /* int64_t                                            */
#include <stdbool.h>    /* bool                                               */
#include <stddef.h>     /* size_t                                             */

/* ─────────────────────────────────────────────────────────────────────────── */
/*  Constants & Macros                                                        */
/* ─────────────────────────────────────────────────────────────────────────── */

#define ACC_MAX_ID_LENGTH          64u
#define ACC_MAX_OWNER_ID_LENGTH    64u
#define ACC_CURRENCY_CODE_LENGTH    3u   /* “USD”, “EUR”, …                  */
#define ACC_TRACE_ID_LENGTH        36u   /* RFC-4122 UUID string             */

/* ─────────────────────────────────────────────────────────────────────────── */
/*  Data Types                                                                */
/* ─────────────────────────────────────────────────────────────────────────── */

/**
 * @brief Result codes returned by all public Account APIs.
 */
typedef enum
{
    ACC_OK                        = 0,
    ACC_ERR_NULL_ARGUMENT         = 1,
    ACC_ERR_INVALID_AMOUNT        = 2,
    ACC_ERR_CURRENCY_MISMATCH     = 3,
    ACC_ERR_OVERFLOW_OR_UNDERFLOW = 4,
    ACC_ERR_INSUFFICIENT_FUNDS    = 5,
    ACC_ERR_ACCOUNT_CLOSED        = 6,
    ACC_ERR_ACCOUNT_SUSPENDED     = 7
} AccountResult;

/**
 * @brief Lifecycle states for an Account.
 */
typedef enum
{
    ACC_STATUS_ACTIVE   = 0,
    ACC_STATUS_SUSPENDED,
    ACC_STATUS_CLOSED
} AccountStatus;

/**
 * @brief Immutable value object representing money.
 */
typedef struct
{
    int64_t amount_minor_units;                        /* e.g. cents          */
    char    currency[ACC_CURRENCY_CODE_LENGTH + 1];    /* null-terminated     */
} Money;

/**
 * @brief Versioning for optimistic concurrency control.
 */
typedef struct
{
    uint32_t revision;     /* Increment on each write                        */
} Version;

/**
 * @brief Aggregate root for the Bursar domain.
 */
typedef struct
{
    char           id[ACC_MAX_ID_LENGTH + 1];          /* Ledger identifier  */
    char           owner_id[ACC_MAX_OWNER_ID_LENGTH + 1];
    Money          balance;
    AccountStatus  status;
    Version        version;
} Account;

/* ─────────────────────────────────────────────────────────────────────────── */
/*  Public API – Lifecycle                                                    */
/* ─────────────────────────────────────────────────────────────────────────── */

/**
 * @brief Initialize a new account with zero balance.
 *
 * @param[out] acct           Destination object (must not be NULL).
 * @param[in]  account_id     UTF-8 string (≤ ACC_MAX_ID_LENGTH).
 * @param[in]  owner_id       Owning student/entity ID.
 * @param[in]  currency_code  ISO-4217 alpha code (3 chars, e.g. “USD”).
 *
 * @return ACC_OK on success, otherwise specific error code.
 */
AccountResult account_init(Account          *acct,
                           const char       *account_id,
                           const char       *owner_id,
                           const char       *currency_code);

/**
 * @brief Permanently close the account.
 *
 * The balance must be zero before closure is permitted.
 *
 * @param[in,out] acct Account instance.
 * @return ACC_OK, ACC_ERR_ACCOUNT_SUSPENDED, ACC_ERR_ACCOUNT_CLOSED,
 *         or ACC_ERR_INVALID_AMOUNT if non-zero balance.
 */
AccountResult account_close(Account *acct);

/**
 * @brief Suspend an account from further debits or credits (fraud, compliance).
 *
 * @param[in,out] acct Account instance.
 * @return ACC_OK or ACC_ERR_ACCOUNT_CLOSED.
 */
AccountResult account_suspend(Account *acct);

/**
 * @brief Reactivate a previously suspended account.
 *
 * @param[in,out] acct Account instance.
 * @return ACC_OK, ACC_ERR_ACCOUNT_CLOSED, or ACC_ERR_ACCOUNT_SUSPENDED if
 *         no state change required.
 */
AccountResult account_reactivate(Account *acct);

/* ─────────────────────────────────────────────────────────────────────────── */
/*  Public API – Monetary Operations                                          */
/* ─────────────────────────────────────────────────────────────────────────── */

/**
 * @brief Credit (deposit) funds into the account.
 *
 * @param[in,out] acct       Account instance.
 * @param[in]     amount     Positive amount in minor units.
 * @param[in]     currency   ISO-4217 code (must match account currency).
 * @param[in]     trace_id   UUID used for idempotency & audit trail.
 *
 * @return ACC_OK, ACC_ERR_INVALID_AMOUNT, ACC_ERR_CURRENCY_MISMATCH,
 *         ACC_ERR_ACCOUNT_CLOSED, ACC_ERR_ACCOUNT_SUSPENDED,
 *         ACC_ERR_OVERFLOW_OR_UNDERFLOW.
 */
AccountResult account_credit(Account       *acct,
                             int64_t        amount,
                             const char    *currency,
                             const char    *trace_id);

/**
 * @brief Debit (withdraw) funds from the account.
 *
 * @param[in,out] acct       Account instance.
 * @param[in]     amount     Positive amount in minor units.
 * @param[in]     currency   ISO-4217 code (must match account currency).
 * @param[in]     trace_id   UUID for idempotency & audit trail.
 *
 * @return ACC_OK, ACC_ERR_INVALID_AMOUNT, ACC_ERR_CURRENCY_MISMATCH,
 *         ACC_ERR_INSUFFICIENT_FUNDS, ACC_ERR_ACCOUNT_CLOSED,
 *         ACC_ERR_ACCOUNT_SUSPENDED, ACC_ERR_OVERFLOW_OR_UNDERFLOW.
 */
AccountResult account_debit(Account       *acct,
                            int64_t        amount,
                            const char    *currency,
                            const char    *trace_id);

/* ─────────────────────────────────────────────────────────────────────────── */
/*  Public API – Queries                                                      */
/* ─────────────────────────────────────────────────────────────────────────── */

/**
 * @brief Obtain the current balance.
 *
 * @param[in]  acct     Account instance.
 * @param[out] out      Destination Money struct (must not be NULL).
 *
 * @return ACC_OK or ACC_ERR_NULL_ARGUMENT.
 */
AccountResult account_get_balance(const Account *acct, Money *out);

/**
 * @brief Returns true if balance < 0 (should never happen for student ledgers,
 *        but may occur for certain institutional workflows).
 */
bool account_is_overdrawn(const Account *acct);

/**
 * @brief Retrieve the current lifecycle status.
 */
AccountStatus account_get_status(const Account *acct);

/**
 * @brief Retrieve the current optimistic-locking version.
 */
Version account_get_version(const Account *acct);

/* ─────────────────────────────────────────────────────────────────────────── */
/*  Helpers                                                                   */
/* ─────────────────────────────────────────────────────────────────────────── */

/**
 * @brief Convenience constructor for Money value object.
 *
 * Performs minimal sanity checks.
 *
 * @return ACC_OK or ACC_ERR_INVALID_AMOUNT.
 */
AccountResult money_make(int64_t amount,
                         const char currency[ACC_CURRENCY_CODE_LENGTH + 1],
                         Money *out);

#endif /* EDUPAY_LEDGER_ACADEMY_BURSAR_ACCOUNT_H */
