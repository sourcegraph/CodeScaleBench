/**
 * @file ledger.h
 * @author
 *   EduPay Ledger Academy — Bursar Service
 *
 * @brief Domain-level abstractions for the immutable double-entry ledger
 *        maintained by the Bursar bounded-context.
 *
 * The Ledger component is *framework-agnostic* and contains **no** references
 * to databases, loggers, message brokers or HTTP frameworks.  This guarantees
 * that students can swap infrastructure while the core business rules remain
 * stable—a key property of Robert C. Martin’s Clean Architecture.
 *
 * All monetary calculations use fixed-precision integers (minor units) to avoid
 * floating-point rounding errors.  ISO-4217 alpha-3 currency codes are used
 * for multi-currency support.
 *
 * Conventions
 * -----------
 * • All functions return 0 on success, non-zero `ledger_err_t` codes on failure.  
 * • “Immutable” means _append-only_; once an entry is POSTED it can only be
 *   compensated by a REVERSAL entry—never mutated in place.  
 * • Thread-safety: read-only operations are lock-free; mutating operations
 *   require the caller to provide a concurrency control strategy (e.g. external
 *   mutex, optimistic CAS or sequential command bus).
 */

#ifndef EDUPAY_LEDGER_ACADEMY_BURSAR_DOMAIN_LEDGER_H
#define EDUPAY_LEDGER_ACADEMY_BURSAR_DOMAIN_LEDGER_H

/* ───────────── System Headers ───────────── */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <time.h>

/* ───────────── Project Headers ───────────── */
#ifdef __cplusplus
extern "C" {
#endif

/*==============================================================================
 * Error Handling
 *============================================================================*/

/**
 * @enum ledger_err_t
 * @brief Enumerates domain-level error codes.
 */
typedef enum ledger_err_e {
    LEDGER_OK                         = 0,
    LEDGER_EARGNULL                  = 1,  /* Null argument                       */
    LEDGER_EARGINVAL                 = 2,  /* Invalid argument value              */
    LEDGER_EOVERFLOW                 = 3,  /* Numeric overflow / underflow        */
    LEDGER_EFOREIGN_KEY              = 4,  /* Unknown account, student, etc.      */
    LEDGER_ECONCURRENCY              = 5,  /* Optimistic concurrency violation    */
    LEDGER_EINSUFFICIENT_FUNDS       = 6,  /* Debit exceeds available balance     */
    LEDGER_EVOID_NOT_ALLOWED         = 7,  /* Cannot void posted entry            */
    LEDGER_EALREADY_POSTED           = 8,  /* Entry already posted                */
    LEDGER_ENOT_FOUND                = 9,  /* Entry not found                     */
    LEDGER_EIMMUTABLE               = 10,  /* Attempt to mutate immutable entry   */
    LEDGER_EIO                      = 11,  /* I/O error (e.g., append to WAL)     */
    LEDGER_EINTERNAL                = 99   /* Catch-all; should be logged         */
} ledger_err_t;

/*==============================================================================
 * Value Objects
 *============================================================================*/

/**
 * @struct uuid_t
 * @brief 128-bit Universally Unique Identifier.
 *
 * The struct is opaque to callers; use `uuid_parse()`, `uuid_format()` helpers.
 */
typedef struct {
    uint8_t bytes[16];
} uuid_t;

/**
 * @struct money_t
 * @brief Fixed-precision monetary value in minor units (e.g. cents).
 */
typedef struct {
    int64_t  amount;            /* Signed 64-bit integer, minor units      */
    char     currency[4];       /* ISO-4217 alpha-3 (null-terminated)      */
} money_t;

/*==============================================================================
 * Enumerations
 *============================================================================*/

/**
 * @enum ledger_entry_type_t
 * @brief Business semantics of an entry.
 */
typedef enum {
    LEDGER_ENTRY_DEBIT,          /* Student owes money                      */
    LEDGER_ENTRY_CREDIT,         /* Money moved into student account        */
    LEDGER_ENTRY_ADJUSTMENT,     /* Manual correction (requires approval)   */
    LEDGER_ENTRY_FEE,            /* Service fee                             */
    LEDGER_ENTRY_REVERSAL        /* System-generated compensation entry     */
} ledger_entry_type_t;

/**
 * @enum ledger_entry_status_t
 * @brief Lifecycle state of a ledger entry.
 */
typedef enum {
    LEDGER_ENTRY_PENDING,        /* Awaiting external confirmation          */
    LEDGER_ENTRY_POSTED,         /* Immutable; included in balance          */
    LEDGER_ENTRY_VOIDED          /* Cancelled before posting                */
} ledger_entry_status_t;

/*==============================================================================
 * Ledger Entry Aggregate
 *============================================================================*/

/**
 * @struct ledger_entry_t
 * @brief Immutable record representing a single leg in a double-entry posting.
 */
typedef struct ledger_entry_s {
    uuid_t                 entry_id;        /* Primary identifier                */
    char                   student_id[32];  /* Domain-specific foreign key        */
    char                   account_id[32];  /* Ledger “bucket”, e.g., TUITION     */
    ledger_entry_type_t    type;
    ledger_entry_status_t  status;

    money_t                amount;          /* Always positive; sign is in type   */
    char                   description[256];

    /* Correlation with upstream commands or external systems */
    uuid_t                 correlation_id;  /* Idempotency / saga tracking        */
    uuid_t                 causation_id;    /* Parent command/event id            */

    /* Timestamps (UTC) */
    struct timespec        created_at;
    struct timespec        posted_at;
} ledger_entry_t;

/*==============================================================================
 * Aggregate Root: Ledger
 *============================================================================*/

/**
 * @struct ledger_snapshot_t
 * @brief Materialized view of balances for quick reads.
 */
typedef struct {
    char     account_id[32];
    money_t  balance;
    struct timespec updated_at;
} ledger_snapshot_t;

/**
 * @struct ledger_t
 * @brief In-memory representation of an account ledger.
 *
 * NOTE: The authoritative store is the append-only journal on disk or via
 *       Event Sourcing.  This struct exists solely to enable
 *       domain-level invariants/tests without IO.
 */
typedef struct ledger_s {
    ledger_entry_t *entries;  /* Dynamic array (append-only)               */
    size_t          entry_count;
    size_t          entry_capacity;

    ledger_snapshot_t *snapshots;  /* Per-account balances                 */
    size_t            snapshot_count;
    size_t            snapshot_capacity;
} ledger_t;

/*==============================================================================
 * Public API – Utility Helpers
 *============================================================================*/

/**
 * @brief Initialize an empty ledger in caller-supplied memory.
 *
 * @param[out]   ledger  Pointer to pre-allocated struct
 * @return       LEDGER_OK on success
 */
ledger_err_t ledger_init(ledger_t *ledger);

/**
 * @brief Release internal memory of a ledger.
 *
 *        The caller is responsible for freeing *ledger itself if it was
 *        heap-allocated.
 */
void ledger_destroy(ledger_t *ledger);

/**
 * @brief Create a new ledger entry with status=PENDING.
 *
 * @param[out]  out_entry       Populated entry (caller owns memory)
 * @param[in]   student_id      UTF-8 text; will be truncated if >31
 * @param[in]   account_id      UTF-8 text; will be truncated if >31
 * @param[in]   type            Business type (DEBIT/CREDIT/...)
 * @param[in]   amount          Monetary value (minor units)
 * @param[in]   description     Optional memo field
 * @param[in]   correlation_id  For idempotency / sagas (may be NULL)
 * @return      error code
 */
ledger_err_t ledger_entry_create(ledger_entry_t       *out_entry,
                                 const char           *student_id,
                                 const char           *account_id,
                                 ledger_entry_type_t   type,
                                 money_t               amount,
                                 const char           *description,
                                 const uuid_t         *correlation_id);

/**
 * @brief Post (finalize) a pending ledger entry.
 *
 *        Upon success the entry status transitions to POSTED, the `posted_at`
 *        timestamp is filled, and the in-memory balances are updated.
 *
 * @note   Thread-safe only if the caller synchronizes!
 */
ledger_err_t ledger_post_entry(ledger_t *ledger, ledger_entry_t *entry);

/**
 * @brief Void a pending entry (cannot void POSTED items).
 */
ledger_err_t ledger_void_entry(ledger_entry_t *entry);

/**
 * @brief Reverse a POSTED entry by appending a compensating entry.
 *
 * @param[in,out]  ledger          Ledger aggregate root
 * @param[in]      original_id     Entry to reverse
 * @param[out]     out_reversal_id The id of the generated REVERSAL entry
 */
ledger_err_t ledger_reverse_entry(ledger_t      *ledger,
                                  const uuid_t  *original_id,
                                  uuid_t        *out_reversal_id);

/**
 * @brief Lookup a ledger entry by UUID.
 *
 * @param[in]   ledger     Ledger root
 * @param[in]   id         Entry identifier
 * @return      Pointer to entry or NULL if not found
 */
ledger_entry_t *ledger_find_entry(ledger_t *ledger, const uuid_t *id);

/**
 * @brief Retrieve current balance for an account.
 *
 * @param[in]   ledger        Ledger root
 * @param[in]   account_id    Alphanumeric identifier
 * @param[out]  out_balance   Returned balance (if found)
 * @return      LEDGER_OK on success, LEDGER_ENOT_FOUND otherwise
 */
ledger_err_t ledger_get_balance(const ledger_t *ledger,
                                const char     *account_id,
                                money_t        *out_balance);

/*==============================================================================
 * UUID Helpers (Tiny Implementation)
 *============================================================================*/

/**
 * @brief Parse UUID from canonical string (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx).
 */
ledger_err_t uuid_parse(const char *str, uuid_t *out_uuid);

/**
 * @brief Format UUID to canonical string.
 *
 * @param[in]   uuid      Input uuid
 * @param[out]  strbuf    Buffer of at least 37 bytes (36 + null)
 */
void uuid_format(const uuid_t *uuid, char strbuf[37]);

/**
 * @brief Generate cryptographically secure random UUID (v4).
 */
ledger_err_t uuid_generate(uuid_t *out_uuid);

/*==============================================================================
 * Money Helpers
 *============================================================================*/

/**
 * @brief Validate ISO-4217 currency string (3 uppercase ASCII letters).
 */
bool currency_is_valid(const char currency[4]);

/**
 * @brief Safely add two monetary amounts with overflow checks.
 *
 * @note  Assumes both amounts use identical currency.  Caller must enforce.
 */
ledger_err_t money_add(const money_t *a, const money_t *b, money_t *out);

/**
 * @brief Negate monetary amount (change sign).
 */
money_t money_negate(money_t m);

/**
 * @brief Compare two monetary values (currency + amount).
 *
 * @return 0 if equal; <0 if a < b; >0 if a > b
 */
int money_cmp(const money_t *a, const money_t *b);

/*==============================================================================
 * Regulatory & Compliance Flags
 *============================================================================*/

/**
 * @brief Apply FERPA redaction policy to a description field in-place.
 *
 *        This helper demonstrates “Security by Design” pedagogy and may be
 *        toggled off during instructor-led labs.
 */
void ledger_ferpa_scrub(char description[256]);

#ifdef __cplusplus
}
#endif

#endif /* EDUPAY_LEDGER_ACADEMY_BURSAR_DOMAIN_LEDGER_H */
