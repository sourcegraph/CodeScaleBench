/*
 * EduPay Ledger Academy — Bursar Service / Domain Layer
 * -----------------------------------------------------
 * account.c
 *
 * The Account aggregate-root encapsulates the transactional invariants for a
 * student ledger.  All monetary values are stored in the smallest currency
 * unit (cents, øre, etc.) using signed 64-bit integers.  Every mutating
 * operation appends a domain event to the in-memory event list so that upper
 * application layers can persist or publish them via Event Sourcing / CQRS.
 *
 * The code purposefully avoids external frameworks to comply with Clean
 * Architecture principles; dependencies are limited to libc, libuuid, and
 * pthread for optional in-process concurrency control.
 */

#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <uuid/uuid.h>

#include "account.h"         /* Aggregate root public interface           */
#include "currency.h"        /* ISO-4217 currency metadata                */
#include "ledger_event.h"    /* Domain-event DTOs shared with event store */

/* ---------------------------------------------------------------------- */
/*  Helpers                                                               */
/* ---------------------------------------------------------------------- */

#define UNUSED(x) ((void)(x))
#define LEDGER_EVENT_DESC_MAX 128

/* Safe add / sub wrappers that detect signed 64-bit overflow */
static inline bool safe_add_i64(int64_t a, int64_t b, int64_t *out)
{
#if defined(__has_builtin)
#  if __has_builtin(__builtin_add_overflow)
    return __builtin_add_overflow(a, b, out);
#  endif
#endif
    /* Fallback: portable overflow detection                                */
    int64_t result = a + b;
    *out          = result;
    return ((b > 0) && (result < a)) || ((b < 0) && (result > a));
}

static inline bool safe_sub_i64(int64_t a, int64_t b, int64_t *out)
{
#if defined(__has_builtin)
#  if __has_builtin(__builtin_sub_overflow)
    return __builtin_sub_overflow(a, b, out);
#  endif
#endif
    int64_t result = a - b;
    *out           = result;
    return ((b < 0) && (result < a)) || ((b > 0) && (result > a));
}

/* Get monotonic timestamp (nanoseconds precision) */
static inline void clock_now(struct timespec *ts)
{
#if (_POSIX_TIMERS > 0) && defined(CLOCK_REALTIME)
    clock_gettime(CLOCK_REALTIME, ts);
#else
    /* Fallback: coarse resolution                                           */
    ts->tv_sec  = time(NULL);
    ts->tv_nsec = 0;
#endif
}

/* ---------------------------------------------------------------------- */
/*  Domain Event Utilities                                                */
/* ---------------------------------------------------------------------- */

typedef struct
{
    ledger_event_t *items;
    size_t          size;
    size_t          capacity;
} ledger_event_list_t;

static void event_list_init(ledger_event_list_t *list)
{
    list->items    = NULL;
    list->size     = 0;
    list->capacity = 0;
}

static void event_list_free(ledger_event_list_t *list)
{
    free(list->items);
    list->items    = NULL;
    list->size     = 0;
    list->capacity = 0;
}

static bool event_list_push(ledger_event_list_t *list,
                            const ledger_event_t *event)
{
    if (list->size == list->capacity)
    {
        size_t newcap = list->capacity == 0 ? 4 : list->capacity * 2;
        ledger_event_t *tmp =
            realloc(list->items, newcap * sizeof(ledger_event_t));
        if (!tmp) { return false; }
        list->items    = tmp;
        list->capacity = newcap;
    }
    list->items[list->size++] = *event;
    return true;
}

/* ---------------------------------------------------------------------- */
/*  Account Aggregate                                                     */
/* ---------------------------------------------------------------------- */

struct account
{
    char              id[37];          /* UUID string */
    char              student_id[32];  /* Foreign key to student */
    currency_t        currency;

    int64_t           balance;         /* Total ledger balance           */
    int64_t           available;       /* Spendable balance (excl hold)  */
    int64_t           hold;            /* Funds on administrative hold   */

    uint32_t          version;         /* Optimistic concurrency token   */
    bool              closed;          /* Lifecycle flag                 */

    ledger_event_list_t events;        /* Local event list               */

    pthread_mutex_t   mtx;             /* Optional concurrency guard     */
};

/* Local forward declarations */
static int  emit_event(struct account *acct, ledger_event_type_t type,
                       int64_t amount, const char *descr);
static int  ensure_open(const struct account *acct);

/* ------------------------------------------------------------------ */
/*  Public API — Creation / Destruction                               */
/* ------------------------------------------------------------------ */

account_t *account_create(const char  *student_id,
                          currency_t   currency,
                          const char  *custom_id /* may be NULL */)
{
    account_t *acct = calloc(1, sizeof(*acct));
    if (!acct) { return NULL; }

    /* Generate / copy identifier */
    if (custom_id)
    {
        strncpy(acct->id, custom_id, sizeof(acct->id) - 1);
    }
    else
    {
        uuid_t uuid;
        uuid_generate(uuid);
        uuid_unparse_lower(uuid, acct->id);
    }

    strncpy(acct->student_id, student_id, sizeof(acct->student_id) - 1);
    acct->currency  = currency;
    acct->balance   = 0;
    acct->available = 0;
    acct->hold      = 0;
    acct->version   = 0;
    acct->closed    = false;

    event_list_init(&acct->events);
    pthread_mutex_init(&acct->mtx, NULL);

    /* Emit creation event */
    if (emit_event(acct, LEDGER_EVENT_ACCOUNT_CREATED, 0, "account created") !=
        ACCOUNT_OK)
    {
        account_free(acct);
        return NULL;
    }
    return acct;
}

void account_free(account_t *acct)
{
    if (!acct) { return; }

    event_list_free(&acct->events);
    pthread_mutex_destroy(&acct->mtx);
    free(acct);
}

/* ------------------------------------------------------------------ */
/*  Public API — Query functions                                      */
/* ------------------------------------------------------------------ */

const char *account_id(const account_t *acct) { return acct->id; }
const char *account_student_id(const account_t *acct) { return acct->student_id; }
currency_t account_currency(const account_t *acct) { return acct->currency; }
int64_t    account_balance(const account_t *acct) { return acct->balance; }
int64_t    account_available(const account_t *acct) { return acct->available; }
uint32_t   account_version(const account_t *acct) { return acct->version; }
bool       account_is_closed(const account_t *acct) { return acct->closed; }

size_t account_pending_event_count(const account_t *acct)
{
    return acct->events.size;
}

const ledger_event_t *
account_pending_events(const account_t *acct, size_t *count_out)
{
    if (count_out) { *count_out = acct->events.size; }
    return acct->events.items;
}

void account_clear_pending_events(account_t *acct)
{
    acct->events.size = 0;
}

/* ------------------------------------------------------------------ */
/*  Public API — Mutations                                            */
/* ------------------------------------------------------------------ */

int account_credit(account_t *acct, int64_t amount_cents, const char *memo)
{
    if (!acct || amount_cents <= 0) { return ACCOUNT_ERR_INVALID_ARG; }
    pthread_mutex_lock(&acct->mtx);

    int rc = ensure_open(acct);
    if (rc != ACCOUNT_OK) { goto unlock; }

    int64_t new_balance;
    if (safe_add_i64(acct->balance, amount_cents, &new_balance))
    {
        rc = ACCOUNT_ERR_OVERFLOW;
        goto unlock;
    }

    int64_t new_available;
    if (safe_add_i64(acct->available, amount_cents, &new_available))
    {
        rc = ACCOUNT_ERR_OVERFLOW;
        goto unlock;
    }

    acct->balance   = new_balance;
    acct->available = new_available;
    acct->version++;

    rc = emit_event(acct, LEDGER_EVENT_ACCOUNT_CREDITED, amount_cents, memo);

unlock:
    pthread_mutex_unlock(&acct->mtx);
    return rc;
}

int account_debit(account_t *acct, int64_t amount_cents, const char *memo)
{
    if (!acct || amount_cents <= 0) { return ACCOUNT_ERR_INVALID_ARG; }

    pthread_mutex_lock(&acct->mtx);

    int rc = ensure_open(acct);
    if (rc != ACCOUNT_OK) { goto unlock; }

    if (acct->available < amount_cents)
    {
        rc = ACCOUNT_ERR_INSUFFICIENT_FUNDS;
        goto unlock;
    }

    acct->balance   -= amount_cents;
    acct->available -= amount_cents;
    acct->version++;

    rc = emit_event(acct, LEDGER_EVENT_ACCOUNT_DEBITED, amount_cents, memo);

unlock:
    pthread_mutex_unlock(&acct->mtx);
    return rc;
}

int account_place_hold(account_t *acct, int64_t amount_cents, const char *reason)
{
    if (!acct || amount_cents <= 0) { return ACCOUNT_ERR_INVALID_ARG; }

    pthread_mutex_lock(&acct->mtx);
    int rc = ensure_open(acct);
    if (rc != ACCOUNT_OK) { goto unlock; }

    if (acct->available < amount_cents)
    {
        rc = ACCOUNT_ERR_INSUFFICIENT_FUNDS;
        goto unlock;
    }

    acct->available -= amount_cents;
    acct->hold      += amount_cents;
    acct->version++;

    rc = emit_event(acct, LEDGER_EVENT_ACCOUNT_HOLD_PLACED, amount_cents,
                    reason ? reason : "hold placed");

unlock:
    pthread_mutex_unlock(&acct->mtx);
    return rc;
}

int account_release_hold(account_t *acct, int64_t amount_cents, const char *reason)
{
    if (!acct || amount_cents <= 0) { return ACCOUNT_ERR_INVALID_ARG; }

    pthread_mutex_lock(&acct->mtx);
    int rc = ensure_open(acct);
    if (rc != ACCOUNT_OK) { goto unlock; }

    if (acct->hold < amount_cents)
    {
        rc = ACCOUNT_ERR_INVALID_ARG; /* Cannot release more than held */
        goto unlock;
    }

    acct->hold      -= amount_cents;
    acct->available += amount_cents;
    acct->version++;

    rc = emit_event(acct, LEDGER_EVENT_ACCOUNT_HOLD_RELEASED, amount_cents,
                    reason ? reason : "hold released");

unlock:
    pthread_mutex_unlock(&acct->mtx);
    return rc;
}

int account_close(account_t *acct)
{
    if (!acct) { return ACCOUNT_ERR_INVALID_ARG; }

    pthread_mutex_lock(&acct->mtx);

    if (acct->closed)
    {
        pthread_mutex_unlock(&acct->mtx);
        return ACCOUNT_ERR_ALREADY_CLOSED;
    }

    if (acct->balance != 0 || acct->hold != 0)
    {
        pthread_mutex_unlock(&acct->mtx);
        return ACCOUNT_ERR_BALANCE_NOT_ZERO;
    }

    acct->closed = true;
    acct->version++;
    int rc       = emit_event(acct, LEDGER_EVENT_ACCOUNT_CLOSED, 0, "account closed");

    pthread_mutex_unlock(&acct->mtx);
    return rc;
}

/* ------------------------------------------------------------------ */
/*  Private helpers                                                   */
/* ------------------------------------------------------------------ */

static int ensure_open(const struct account *acct)
{
    if (acct->closed) { return ACCOUNT_ERR_ACCOUNT_CLOSED; }
    return ACCOUNT_OK;
}

static int emit_event(struct account        *acct,
                      ledger_event_type_t    type,
                      int64_t                amount,
                      const char            *descr)
{
    ledger_event_t ev = {0};

    ev.type      = type;
    clock_now(&ev.timestamp);
    strncpy(ev.account_id, acct->id, sizeof(ev.account_id) - 1);
    ev.amount    = amount;
    ev.version   = acct->version;
    if (descr)
    {
        strncpy(ev.description, descr, LEDGER_EVENT_DESC_MAX - 1);
    }

    if (!event_list_push(&acct->events, &ev))
    {
        return ACCOUNT_ERR_OOM;
    }
    return ACCOUNT_OK;
}

/* ------------------------------------------------------------------ */
/*  Debug / Diagnostic Helpers (optional)                             */
/* ------------------------------------------------------------------ */

#ifdef EDU_PAY_LEDGER_DEBUG
void account_dump(const account_t *acct, FILE *out)
{
    if (!acct) { return; }
    if (!out) { out = stdout; }

    fprintf(out,
            "Account[%s] student=%s cur=%s balance=%" PRId64
            " available=%" PRId64 " hold=%" PRId64 " ver=%u closed=%d\n",
            acct->id,
            acct->student_id,
            currency_iso(acct->currency),
            acct->balance,
            acct->available,
            acct->hold,
            acct->version,
            acct->closed);
}
#endif /* EDU_PAY_LEDGER_DEBUG */
