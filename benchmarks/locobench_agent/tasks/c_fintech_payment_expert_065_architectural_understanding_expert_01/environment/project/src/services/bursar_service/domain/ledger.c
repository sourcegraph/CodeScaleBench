/*
 * EduPay Ledger Academy
 * Bursar Service :: Domain Layer
 *
 * ledger.c
 *
 * This compilation unit implements the core ledger domain model for the
 * Bursar-Service.  It is intentionally free of any infrastructure concerns
 * (databases, message queues, HTTP, etc.) so that professors can swap those
 * technologies without changing these business rules (Clean Architecture).
 *
 * The implementation provides:
 *   • In-memory, thread-safe ledger book
 *   • Idempotent posting of ledger entries
 *   • Multi-currency, minor-unit precision accounting
 *   • Tamper-evident hashing for audit-trail snapshots
 *
 * NOTE:
 *   All monetary amounts are stored as signed 64-bit integers representing the
 *   minor unit of the currency (e.g., cents for USD, satoshi for BTC).
 *
 * Copyright (c) 2024
 */

#include "ledger.h"     /* Local domain header */
#include "currency.h"   /* ISO-4217 currency helpers */
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(LEDGER_USE_OPENSSL)
#include <openssl/sha.h>
#endif

/* -------------------------------------------------------------------------- */
/*  Macros & Constants                                                        */
/* -------------------------------------------------------------------------- */

#define LEDGER_INITIAL_CAPACITY  64U
#define LEDGER_GROWTH_FACTOR     2U
#define MAX_MEMO_LENGTH          255U
#define UUID_STR_LENGTH          36U

/* -------------------------------------------------------------------------- */
/*  Static Helpers                                                            */
/* -------------------------------------------------------------------------- */

static int
ledger__resize(ledger_t *ledger, size_t new_capacity)
{
    assert(ledger);

    ledger_entry_t *tmp =
        realloc(ledger->entries, new_capacity * sizeof *ledger->entries);
    if (!tmp) {
        return ENOMEM;
    }

    ledger->entries  = tmp;
    ledger->capacity = new_capacity;
    return 0;
}

static int
ledger__duplicate_tx_id(const ledger_t *ledger, const char *tx_id)
{
    assert(ledger);
    assert(tx_id);

    for (size_t i = 0; i < ledger->entry_count; ++i) {
        if (strncmp(ledger->entries[i].tx_id, tx_id, UUID_STR_LENGTH) == 0) {
            return 1;
        }
    }
    return 0;
}

/* Compute a digest for the ledger-entry for tamper evidence.
 * We either use SHA-256 (preferred) or a simple XOR checksum fallback. */
static void
ledger__compute_digest(const ledger_entry_t *entry, uint8_t out[LEDGER_DIGEST_SZ])
{
    assert(entry);
    assert(out);

#if defined(LEDGER_USE_OPENSSL)
    SHA256_CTX ctx;
    SHA256_Init(&ctx);
    SHA256_Update(&ctx, entry, sizeof *entry - LEDGER_DIGEST_SZ);
    SHA256_Final(out, &ctx);
#else
    /* Fallback: not cryptographically strong, but avoids external deps. */
    uint8_t xor_chk = 0;
    const uint8_t *ptr = (const uint8_t *)entry;
    for (size_t i = 0; i < sizeof *entry - LEDGER_DIGEST_SZ; ++i) {
        xor_chk ^= ptr[i];
    }
    memset(out, xor_chk, LEDGER_DIGEST_SZ);
#endif
}

static int
ledger__overflow(int64_t a, int64_t b, int64_t *result)
{
    if ((b > 0 && a > INT64_MAX - b) ||
        (b < 0 && a < INT64_MIN - b)) {
        return ERANGE;
    }
    *result = a + b;
    return 0;
}

/* -------------------------------------------------------------------------- */
/*  Public API                                                                */
/* -------------------------------------------------------------------------- */

int
ledger_init(ledger_t *ledger)
{
    if (!ledger) {
        return EINVAL;
    }

    ledger->entries     = calloc(LEDGER_INITIAL_CAPACITY, sizeof *ledger->entries);
    if (!ledger->entries) {
        return ENOMEM;
    }
    ledger->entry_count = 0U;
    ledger->capacity    = LEDGER_INITIAL_CAPACITY;
    pthread_mutex_init(&ledger->mtx, NULL);
    return 0;
}

void
ledger_clear(ledger_t *ledger)
{
    if (!ledger) {
        return;
    }

    pthread_mutex_lock(&ledger->mtx);
    free(ledger->entries);
    ledger->entries     = NULL;
    ledger->entry_count = 0U;
    ledger->capacity    = 0U;
    pthread_mutex_unlock(&ledger->mtx);
    pthread_mutex_destroy(&ledger->mtx);
}

int
ledger_post_entry(ledger_t *ledger,
                  const char *tx_id,
                  const char *account_id,
                  int64_t     minor_units,
                  const char *currency,
                  const char *memo,
                  time_t      timestamp)
{
    if (!ledger || !tx_id || !account_id || !currency) {
        return EINVAL;
    }
    if (strlen(tx_id) != UUID_STR_LENGTH) {
        return EINVAL;
    }
    if (!currency_is_supported(currency)) {
        return EDOM; /* Unknown currency. */
    }

    pthread_mutex_lock(&ledger->mtx);

    /* Idempotency check */
    if (ledger__duplicate_tx_id(ledger, tx_id)) {
        pthread_mutex_unlock(&ledger->mtx);
        return EALREADY;
    }

    /* Grow internal buffer if necessary */
    if (ledger->entry_count == ledger->capacity) {
        int rc = ledger__resize(ledger, ledger->capacity * LEDGER_GROWTH_FACTOR);
        if (rc) {
            pthread_mutex_unlock(&ledger->mtx);
            return rc;
        }
    }

    ledger_entry_t *entry = &ledger->entries[ledger->entry_count];

    /* Populate entry */
    strncpy(entry->tx_id, tx_id, sizeof entry->tx_id);
    entry->tx_id[UUID_STR_LENGTH] = '\0';

    strncpy(entry->account_id, account_id, sizeof entry->account_id - 1);
    entry->account_id[sizeof entry->account_id - 1] = '\0';

    entry->amount.major_minor = minor_units;
    strncpy(entry->amount.currency, currency, sizeof entry->amount.currency);
    entry->amount.currency[3] = '\0';

    entry->timestamp = timestamp ? timestamp : time(NULL);

    if (memo) {
        strncpy(entry->memo, memo, MAX_MEMO_LENGTH);
        entry->memo[MAX_MEMO_LENGTH] = '\0';
    } else {
        entry->memo[0] = '\0';
    }

    /* Compute tamper-evident digest */
    ledger__compute_digest(entry, entry->digest);

    ++ledger->entry_count;
    pthread_mutex_unlock(&ledger->mtx);

    return 0;
}

int
ledger_get_balance(const ledger_t *ledger,
                   const char     *currency,
                   int64_t        *out_minor_units)
{
    if (!ledger || !currency || !out_minor_units) {
        return EINVAL;
    }
    if (!currency_is_supported(currency)) {
        return EDOM;
    }

    pthread_mutex_lock((pthread_mutex_t *)&ledger->mtx);

    int64_t balance = 0;
    for (size_t i = 0; i < ledger->entry_count; ++i) {
        const ledger_entry_t *e = &ledger->entries[i];
        if (strncmp(e->amount.currency, currency, 3) != 0) {
            continue;
        }
        int rc = ledger__overflow(balance, e->amount.major_minor, &balance);
        if (rc) {
            pthread_mutex_unlock((pthread_mutex_t *)&ledger->mtx);
            return rc;
        }
    }

    *out_minor_units = balance;
    pthread_mutex_unlock((pthread_mutex_t *)&ledger->mtx);
    return 0;
}

int
ledger_find_entry(const ledger_t *ledger,
                  const char     *tx_id,
                  ledger_entry_t *out_entry)
{
    if (!ledger || !tx_id || !out_entry) {
        return EINVAL;
    }

    pthread_mutex_lock((pthread_mutex_t *)&ledger->mtx);

    for (size_t i = 0; i < ledger->entry_count; ++i) {
        if (strncmp(ledger->entries[i].tx_id, tx_id, UUID_STR_LENGTH) == 0) {
            *out_entry = ledger->entries[i];
            pthread_mutex_unlock((pthread_mutex_t *)&ledger->mtx);
            return 0;
        }
    }

    pthread_mutex_unlock((pthread_mutex_t *)&ledger->mtx);
    return ENOENT;
}

/* Export ledger entries to provided FILE stream as CSV.
 * Caller owns stream (may be stdout or file). */
int
ledger_export_csv(const ledger_t *ledger, FILE *out)
{
    if (!ledger || !out) {
        return EINVAL;
    }

    pthread_mutex_lock((pthread_mutex_t *)&ledger->mtx);

    /* CSV header */
    fputs("tx_id,account_id,minor_units,currency,timestamp,memo,digest\n", out);

    char tsbuf[32];
    for (size_t i = 0; i < ledger->entry_count; ++i) {
        const ledger_entry_t *e = &ledger->entries[i];
        struct tm             tm_snapshot;
        gmtime_r(&e->timestamp, &tm_snapshot);
        strftime(tsbuf, sizeof tsbuf, "%Y-%m-%dT%H:%M:%SZ", &tm_snapshot);

        /* Digest as hex */
        char digest_hex[LEDGER_DIGEST_SZ * 2 + 1];
        for (size_t b = 0; b < LEDGER_DIGEST_SZ; ++b) {
            sprintf(&digest_hex[b * 2], "%02x", e->digest[b]);
        }
        digest_hex[LEDGER_DIGEST_SZ * 2] = '\0';

        fprintf(out,
                "%s,%s,%" PRId64 ",%s,%s,%s,%s\n",
                e->tx_id,
                e->account_id,
                e->amount.major_minor,
                e->amount.currency,
                tsbuf,
                e->memo,
                digest_hex);
    }

    pthread_mutex_unlock((pthread_mutex_t *)&ledger->mtx);
    return 0;
}

/* Verify integrity of all entries by recomputing digests. */
int
ledger_verify_integrity(const ledger_t *ledger)
{
    if (!ledger) {
        return EINVAL;
    }

    pthread_mutex_lock((pthread_mutex_t *)&ledger->mtx);

    for (size_t i = 0; i < ledger->entry_count; ++i) {
        const ledger_entry_t *e = &ledger->entries[i];
        uint8_t               recomputed[LEDGER_DIGEST_SZ];
        ledger__compute_digest(e, recomputed);
        if (memcmp(recomputed, e->digest, LEDGER_DIGEST_SZ) != 0) {
            pthread_mutex_unlock((pthread_mutex_t *)&ledger->mtx);
            return EBADF; /* Tampering detected */
        }
    }

    pthread_mutex_unlock((pthread_mutex_t *)&ledger->mtx);
    return 0;
}

/* -------------------------------------------------------------------------- */
/*  Debug / Unit-Test Helpers (domain layer only)                             */
/* -------------------------------------------------------------------------- */

#ifdef LEDGER_ENABLE_SELFTEST
#include <stdio.h>

static void
selftest(void)
{
    ledger_t ledger;
    assert(ledger_init(&ledger) == 0);

    assert(ledger_post_entry(&ledger,
                             "123e4567-e89b-12d3-a456-426614174000",
                             "tuition-fall-2024",
                             100000, /* $1000.00 */
                             "USD",
                             "Tuition payment",
                             0) == 0);

    int64_t bal = 0;
    assert(ledger_get_balance(&ledger, "USD", &bal) == 0);
    assert(bal == 100000);

    ledger_entry_t found;
    assert(ledger_find_entry(&ledger,
                             "123e4567-e89b-12d3-a456-426614174000",
                             &found) == 0);

    assert(ledger_verify_integrity(&ledger) == 0);

    ledger_export_csv(&ledger, stdout);

    ledger_clear(&ledger);
    puts("Ledger self-test passed.");
}

int
main(void)
{
    selftest();
    return 0;
}
#endif /* LEDGER_ENABLE_SELFTEST */
