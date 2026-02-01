/**
 * @file scholarship_fund.h
 * @author
 * @date    2024-05-13
 *
 * @brief   Domain aggregate root representing a Scholarship Fund inside the
 *          Financial-Aid bounded context.  A Scholarship Fund is responsible
 *          for managing donor deposits, validating allocations to student
 *          ledgers, and generating immutable Ledger Events for downstream
 *          Audit-Trail projections.
 *
 *          This header purposefully exposes *only* behaviors that constitute
 *          business rules.  It contains no persistence, no logging, and no
 *          framework dependencies so that professors can swap concrete
 *          implementations during labs without touching the domain.
 *
 *          Thread-safety:  All functions are re-entrant.  However, the caller
 *          is responsible for synchronizing access to a scholarship_fund_t
 *          instance when sharing across threads.
 */

#pragma once

/*───────────────────────────── Public Dependencies ───────────────────────────*/
#include <stddef.h>     /* size_t */
#include <stdint.h>     /* uint64_t */
#include <time.h>       /* time_t  */

#include "core/id/uuid.h"          /* uuid_t                    */
#include "core/money/money.h"      /* money_t, currency_code_t  */
#include "core/audit/ledger_event.h"/* ledger_event_t            */

#ifdef __cplusplus
extern "C" {
#endif

/*─────────────────────────────── Definitions ─────────────────────────────────*/

/* @note Keep aligned with SQL schema and protobuf contract */
#define SCHOLARSHIP_FUND_NAME_MAX    (128u)

/*---------------------------------------------------------------------------*/
/**
 * @enum scholarship_fund_status_e
 *
 * @brief Lifecycle states controlled by compliance workflows.  A fund that is
 *        not ACTIVE will reject allocation and deposit attempts.
 */
typedef enum
{
    SCHOLARSHIP_FUND_STATUS_ACTIVE = 0,
    SCHOLARSHIP_FUND_STATUS_SUSPENDED,
    SCHOLARSHIP_FUND_STATUS_CLOSED
} scholarship_fund_status_e;


/*---------------------------------------------------------------------------*/
/**
 * @enum scholarship_fund_rc_e
 *
 * @brief Domain-level return codes.  No errno pollution.
 */
typedef enum
{
    SCHOLARSHIP_FUND_RC_OK = 0,
    SCHOLARSHIP_FUND_RC_INVALID_ARGUMENT,
    SCHOLARSHIP_FUND_RC_ILLEGAL_STATE,
    SCHOLARSHIP_FUND_RC_INSUFFICIENT_FUNDS,
    SCHOLARSHIP_FUND_RC_CURRENCY_MISMATCH,
    SCHOLARSHIP_FUND_RC_OVERFLOW,
    SCHOLARSHIP_FUND_RC_OUT_OF_MEMORY,
    SCHOLARSHIP_FUND_RC_UNKNOWN
} scholarship_fund_rc_e;


/*---------------------------------------------------------------------------*/
/**
 * @struct scholarship_fund_snapshot_t
 *
 * @brief Immutable read-model for CQRS queries or exporting telemetry without
 *        exposing internal mutability.  Obtained via
 *        scholarship_fund_snapshot().
 */
typedef struct
{
    uuid_t                     id;
    char                       name[SCHOLARSHIP_FUND_NAME_MAX];
    scholarship_fund_status_e  status;
    money_t                    balance;      /* In fund's base currency */
    currency_code_t            base_currency;
    time_t                     created_at_utc;
    time_t                     updated_at_utc;
} scholarship_fund_snapshot_t;


/* Opaque pointer to preserve invariants */
typedef struct scholarship_fund scholarship_fund_t;

/*───────────────────────────── Construction API ─────────────────────────────*/

/**
 * @brief Create a new Scholarship Fund aggregate.
 *
 * @param[out] out_fund         On success, receives newly allocated instance.
 * @param[in]  name             UTF-8 name (truncated if > SCHOLARSHIP_FUND_NAME_MAX-1).
 * @param[in]  base_currency    ISO-4217 currency code used for valuation.
 *
 * @return SCHOLARSHIP_FUND_RC_OK on success, otherwise an error code.
 */
scholarship_fund_rc_e
scholarship_fund_create(scholarship_fund_t **out_fund,
                        const char          *name,
                        currency_code_t      base_currency);

/**
 * @brief Free resources held by a Scholarship Fund.  Safe to pass NULL.
 */
void
scholarship_fund_destroy(scholarship_fund_t *fund);


/*────────────────────────────── Query API ───────────────────────────────────*/

/**
 * @brief Obtain a thread-safe snapshot of the aggregate for read-only use in
 *        presentation layers or diagnostics.
 *
 * @param[in]  fund             Target instance.
 * @param[out] out_snapshot     Caller-allocated buffer receives snapshot.
 *
 * @return SCHOLARSHIP_FUND_RC_OK on success.
 */
scholarship_fund_rc_e
scholarship_fund_snapshot(const scholarship_fund_t *fund,
                          scholarship_fund_snapshot_t *out_snapshot);

/**
 * @brief Convenience helper for balance queries.
 */
scholarship_fund_rc_e
scholarship_fund_get_balance(const scholarship_fund_t *fund,
                             money_t *out_balance);


/*──────────────────────────── Command API ───────────────────────────────────*/

/**
 * @brief Deposit donor money into the fund.  Produces a LedgerEvent for event
 *        sourcing and audit trail projections.
 *
 * @param[in,out] fund          Target instance (must be ACTIVE).
 * @param[in]     amount        Must be non-negative and use fund's base
 *                              currency, else SCHOLARSHIP_FUND_RC_CURRENCY_MISMATCH.
 * @param[out]    out_event     Optional.  On success, populated with immutable
 *                              event data the caller must eventually persist.
 *
 * @return SCHOLARSHIP_FUND_RC_OK on success.
 */
scholarship_fund_rc_e
scholarship_fund_deposit(scholarship_fund_t  *fund,
                         const money_t       *amount,
                         ledger_event_t      *out_event);

/**
 * @brief Allocate funds to a student's tuition ledger.
 *
 * @param[in,out] fund              Target instance (must be ACTIVE).
 * @param[in]     amount            Positive amount in base currency.
 * @param[in]     student_uuid      Recipient student id (for event payload).
 * @param[out]    out_event         Generated LedgerEvent (optional).
 *
 * @return SCHOLARSHIP_FUND_RC_OK or error.
 */
scholarship_fund_rc_e
scholarship_fund_allocate(scholarship_fund_t  *fund,
                          const money_t       *amount,
                          const uuid_t        *student_uuid,
                          ledger_event_t      *out_event);

/**
 * @brief Suspend a fund (temporarily blocks allocations & deposits).
 *
 * @param[in,out] fund              Target instance.
 * @param[in]     reason            Human-readable justification.  May be NULL.
 * @param[out]    out_event         LedgerEvent describing the state change.
 */
scholarship_fund_rc_e
scholarship_fund_suspend(scholarship_fund_t *fund,
                         const char         *reason,
                         ledger_event_t     *out_event);

/**
 * @brief Reactivate a previously suspended fund.
 */
scholarship_fund_rc_e
scholarship_fund_activate(scholarship_fund_t *fund,
                          ledger_event_t     *out_event);

/**
 * @brief Permanently close a fund.  Balance must be zero before calling.
 */
scholarship_fund_rc_e
scholarship_fund_close(scholarship_fund_t *fund,
                       ledger_event_t     *out_event);


/*───────────────────────── Validation Utilities ─────────────────────────────*/

/**
 * @brief Verify whether the fund has sufficient balance for an allocation.
 *
 * @note  This call is pure and does not change state.
 */
scholarship_fund_rc_e
scholarship_fund_can_allocate(const scholarship_fund_t *fund,
                              const money_t            *amount);


/*─────────────────────────────────────────────────────────────────────────────*/

#ifdef __cplusplus
} /* extern "C" */
#endif