/**
 * @file get_account_balance_query.h
 *
 * @brief Application-layer query for retrieving the current ledger balance
 *        of a student, department, or scholarship account in the Bursar
 *        bounded-context of EduPay Ledger Academy.
 *
 * The public API in this header follows the “Clean Architecture” style:
 *   • No dependency on frameworks or external IO
 *   • Pure C DTOs (Data-Transfer-Objects) with no memory allocation hidden
 *     inside the boundary
 *   • All concrete infrastructure (database, message bus, etc.) is injected
 *     via an opaque context pointer so that professors can change
 *     implementations without recompiling the core domain.
 *
 * Typical usage from a delivery-mechanism (e.g., HTTP handler):
 *
 *      bursar_query_context_t *ctx = bursar_query_context_create(pg_pool);
 *
 *      get_account_balance_query_t  query  = {
 *          .account_id    = "STU-2024-000123",
 *          .preferred_ccy = "USD"
 *      };
 *
 *      account_balance_dto_t  result;
 *      epay_rc_t rc = get_account_balance_execute(&query, &result, ctx);
 *
 *      if (rc == EPAY_RC_OK) {
 *          render_json(result);
 *      } else {
 *          translate_error(rc);
 *      }
 *
 * The interface is thread-safe as long as the caller guarantees that
 * a given context instance is not used concurrently by multiple threads.
 */

#ifndef EDUPAY_LEDGER_ACADEMY_BURSAR_SERVICE_APPLICATION_QUERIES_GET_ACCOUNT_BALANCE_QUERY_H
#define EDUPAY_LEDGER_ACADEMY_BURSAR_SERVICE_APPLICATION_QUERIES_GET_ACCOUNT_BALANCE_QUERY_H

/* ────────────────────────────────────────────────────────────────────────── */
/* Standard Library                                                          */
#include <stddef.h>     /* size_t */
#include <stdint.h>     /* uint64_t, int32_t */
#include <time.h>       /* time_t */

/* ────────────────────────────────────────────────────────────────────────── */
/* Project-wide Error & Tracing Utilities                                    */
#include "edupay/common/status_codes.h"     /* epay_rc_t, EPAY_RC_xxx */
#include "edupay/common/iso_currency.h"     /* epay_iso_currency_t    */
#include "edupay/common/uuid.h"             /* epay_uuid_t            */

/* Forward declaration of opaque application context.                        */
typedef struct bursar_query_context_s bursar_query_context_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* DTOs (Data-Transfer-Objects)                                              */

/**
 * @struct account_balance_dto_t
 *
 * @brief Serializable representation of an account’s balance projection.
 */
typedef struct account_balance_dto_s
{
    epay_uuid_t    account_id;       /* UUID (canonical 128-bit)            */
    epay_iso_currency_t currency;    /* ISO-4217 currency code              */
    int64_t        available_minor;  /* Minor units (e.g., cents)           */
    int64_t        pending_minor;    /* Authorizations not yet settled      */
    int64_t        on_hold_minor;    /* Compliance, FRAUD, or ACH hold      */
    time_t         last_updated_utc; /* When the projection was refreshed   */
} account_balance_dto_t;

/**
 * @struct get_account_balance_query_t
 *
 * @brief Input parameters validated by the Application layer before being
 *        handed off to the domain service/repository.
 */
typedef struct get_account_balance_query_s
{
    epay_uuid_t         account_id;      /* Mandatory                        */
    epay_iso_currency_t preferred_ccy;   /* Optional hint for cross-ccy UX   */
} get_account_balance_query_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Error Codes specific to this Use-Case                                     */

/**
 * EPAY_RC_DOMAIN_NOT_FOUND    – Account does not exist
 * EPAY_RC_DOMAIN_FORBIDDEN    – Violates FERPA/role rules
 * EPAY_RC_DOMAIN_INTEGRITY    – Ledger corruption detected
 * EPAY_RC_STORAGE_FAILURE     – Database connectivity, etc.
 * EPAY_RC_VALIDATION_FAILED   – Input violates constraints
 */

/* ────────────────────────────────────────────────────────────────────────── */
/* Public API                                                                */

/**
 * @brief Validates and executes the Get-Account-Balance query.
 *
 * @param[in]  query      Pointer to an initialized query DTO.
 * @param[out] result     Caller-allocated DTO to be populated on success.
 * @param[in]  ctx        Opaque context providing repository implementation
 *                        and transactional policies.
 *
 * @return EPAY_RC_OK on success, or one of the error codes documented above.
 *
 * Thread-Safety: safe if @a ctx is not shared concurrently by multiple
 * threads or if the concrete implementation provides its own synchronization.
 */
epay_rc_t
get_account_balance_execute(const get_account_balance_query_t *query,
                            account_balance_dto_t             *result,
                            bursar_query_context_t            *ctx);

/**
 * @brief Convenience helper that performs strict validation only.
 *
 * Use this if you want to fail-fast before allocating DB connections or
 * network sockets. On validation failure, @p error_offset will contain the
 * byte offset within the serialized query (if known) to ease UX feedback.
 *
 * @param[in]  query        Query DTO to validate.
 * @param[out] error_offset Offset of offending field (or SIZE_MAX).
 *
 * @return EPAY_RC_OK if input is well-formed, otherwise EPAY_RC_VALIDATION_FAILED.
 */
epay_rc_t
get_account_balance_validate(const get_account_balance_query_t *query,
                             size_t                            *error_offset);

/* ────────────────────────────────────────────────────────────────────────── */
/* Compile-time Assertions (defensive programming)                           */

#if defined(__STDC_VERSION__) && (__STDC_VERSION__ >= 201112L)
#   include <assert.h>
_Static_assert(sizeof(epay_uuid_t)           == 16, "UUID must be 128-bit");
_Static_assert(sizeof(epay_iso_currency_t)   == 3,  "Currency must be 3 bytes");
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Inline Helpers                                                            */

/**
 * Normalizes the currency field of the result DTO to uppercase ASCII.
 * Provided as an inline to avoid forcing callers to link extra object files
 * when they merely need formatting assistance.
 */
static inline void
account_balance_normalize_currency(account_balance_dto_t *dto)
{
    for (size_t i = 0; i < sizeof(dto->currency); ++i)
    {
        if (dto->currency[i] >= 'a' && dto->currency[i] <= 'z')
        {
            dto->currency[i] = (char)(dto->currency[i] - 32);
        }
    }
}

#endif /* EDUPAY_LEDGER_ACADEMY_BURSAR_SERVICE_APPLICATION_QUERIES_GET_ACCOUNT_BALANCE_QUERY_H */