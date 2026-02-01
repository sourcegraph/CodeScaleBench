/*
 * EduPay Ledger Academy
 * File: scholarship_fund.c
 * Bounded-Context : Financial-Aid Service / Domain
 *
 * Description:
 *   Pure domain logic for managing Scholarship Funds.
 *   The code follows Clean Architecture rules—no dependencies on
 *   frameworks, databases, or IO.  External layers communicate solely
 *   through the public API declared in scholarship_fund.h.
 *
 *   Features
 *     • Precise (cent-based) monetary arithmetic
 *     • Multi-currency awareness (ISO-4217 currency codes)
 *     • Defensive invariants & error-codes instead of exceptions
 *     • Pluggable domain-event sink for CQRS / Event-Sourcing
 *
 * Author: EduPay Core Engineering
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <errno.h>

#include "scholarship_fund.h"   /* Public interface */

/*---------------------------------------------------------------
 *  Internal Definitions
 *--------------------------------------------------------------*/

/* Maximum length for IDs and ISO-currency codes */
#define FUND_ID_MAX_LEN      64
#define NAME_MAX_LEN         128
#define STUDENT_ID_MAX_LEN   64
#define DONOR_ID_MAX_LEN     64
#define ISO_CCY_LEN          3    /* e.g. "USD" */
#define MAX_ALLOCATIONS      1024 /* Hard cap – domain rule */

/* Error codes returned by public API */
typedef enum {
    SF_OK                                =  0,
    SF_ERR_NULL_ARGUMENT                 = -1,
    SF_ERR_INVALID_AMOUNT                = -2,
    SF_ERR_CURRENCY_MISMATCH             = -3,
    SF_ERR_INSUFFICIENT_FUNDS            = -4,
    SF_ERR_ALLOCATION_NOT_FOUND          = -5,
    SF_ERR_ALLOCATION_EXISTS             = -6,
    SF_ERR_ALLOCATION_CAP_EXCEEDED       = -7,
    SF_ERR_INTERNAL                      = -500
} sf_error_t;

/* Monetary Amount expressed in (signed) integer cents.
 * This avoids floating-point rounding issues. */
typedef struct {
    char     currency[ISO_CCY_LEN + 1];  /* Null-terminated 3-char code */
    int64_t  cents;                      /* 1 USD  == 100  cents
                                            1 JPY  == 1    "yen-cents" */
} money_t;

/* Scholarship Allocation (reserved amount for a student) */
typedef struct {
    char     student_id[STUDENT_ID_MAX_LEN + 1];
    money_t  amount;
} allocation_t;

/*---------------------------------------------------------------
 *  Private Helpers
 *--------------------------------------------------------------*/

/* Safe string copy that always null-terminates. */
static void strncpy_safe(char *dest, const char *src, size_t dest_sz)
{
    if (dest_sz == 0) return;
    strncpy(dest, src ? src : "", dest_sz - 1);
    dest[dest_sz - 1] = '\0';
}

/* Money addition with overflow detection.
 * Returns SF_OK or SF_ERR_INTERNAL on overflow. */
static int money_add(money_t *target, const money_t *delta)
{
    if (!target || !delta) return SF_ERR_NULL_ARGUMENT;
    if (strcmp(target->currency, delta->currency) != 0)
        return SF_ERR_CURRENCY_MISMATCH;

    /* Signed 64bit overflow detection */
    if ((delta->cents > 0 && target->cents > INT64_MAX - delta->cents) ||
        (delta->cents < 0 && target->cents < INT64_MIN - delta->cents)) {
        return SF_ERR_INTERNAL;
    }
    target->cents += delta->cents;
    return SF_OK;
}

/*---------------------------------------------------------------
 *  Scholarship Fund Aggregate Root
 *--------------------------------------------------------------*/

/* Internal structure – implementation detail hidden from header */
struct scholarship_fund {
    char           fund_id[FUND_ID_MAX_LEN + 1];
    char           name[NAME_MAX_LEN + 1];
    money_t        total_balance;                /* Donations + initial seed */
    money_t        reserved_balance;             /* Sum of all allocations   */

    /* Dynamic array of grant allocations */
    allocation_t  *allocations;
    size_t         allocated_count;
    size_t         allocated_capacity;

    /* Optional event sink (CQRS / ES) */
    domain_event_sink_fn  event_sink;
    void                 *event_sink_ctx;

    /* Audit meta */
    time_t         created_at;
};

/* Forward declarations */
static int          ensure_capacity(scholarship_fund_t *fund);
static allocation_t *find_allocation(scholarship_fund_t *fund,
                                     const char *student_id);

/*---------------------------------------------------------------
 *  Public API Implementations
 *--------------------------------------------------------------*/

int scholarship_fund_init(scholarship_fund_t      **out_fund,
                          const char              *fund_id,
                          const char              *name,
                          const char              *currency,
                          int64_t                  initial_cents,
                          domain_event_sink_fn     sink,
                          void                    *sink_ctx)
{
    if (!out_fund || !fund_id || !name || !currency)
        return SF_ERR_NULL_ARGUMENT;

    if (strlen(currency) != ISO_CCY_LEN)
        return SF_ERR_CURRENCY_MISMATCH;

    /* Allocate & zero memory */
    scholarship_fund_t *fund = calloc(1, sizeof(*fund));
    if (!fund) return SF_ERR_INTERNAL;

    /* Initialize identity & meta */
    strncmpi_safe(fund->fund_id, fund_id, sizeof(fund->fund_id));
    strncmpi_safe(fund->name, name, sizeof(fund->name));
    fund->created_at = time(NULL);

    /* Setup currency & seed amount */
    strncpy_safe(fund->total_balance.currency, currency,
                 sizeof(fund->total_balance.currency));
    fund->total_balance.cents = initial_cents;

    strncpy_safe(fund->reserved_balance.currency, currency,
                 sizeof(fund->reserved_balance.currency));
    fund->reserved_balance.cents = 0;

    /* Allocation storage */
    fund->allocated_capacity = 8; /* start small, grow as needed */
    fund->allocations = calloc(fund->allocated_capacity, sizeof(allocation_t));
    if (!fund->allocations) {
        free(fund);
        return SF_ERR_INTERNAL;
    }

    /* Event sink */
    fund->event_sink = sink;
    fund->event_sink_ctx = sink_ctx;

    *out_fund = fund;
    return SF_OK;
}

int scholarship_fund_dispose(scholarship_fund_t *fund)
{
    if (!fund) return SF_ERR_NULL_ARGUMENT;
    free(fund->allocations);
    memset(fund, 0, sizeof(*fund));
    free(fund);
    return SF_OK;
}

int scholarship_fund_record_donation(scholarship_fund_t *fund,
                                     const char         *donor_id,
                                     int64_t             amount_cents)
{
    if (!fund || !donor_id) return SF_ERR_NULL_ARGUMENT;
    if (amount_cents <= 0)   return SF_ERR_INVALID_AMOUNT;

    money_t delta = {0};
    strcpy(delta.currency, fund->total_balance.currency);
    delta.cents = amount_cents;

    int rc = money_add(&fund->total_balance, &delta);
    if (rc != SF_OK) return rc;

    /* Emit domain event */
    if (fund->event_sink) {
        scholarship_fund_event_t ev = {
            .type = SFE_DONATION_RECEIVED,
            .occurred_at = time(NULL)
        };
        strncpy_safe(ev.fund_id, fund->fund_id, sizeof(ev.fund_id));
        strncmpi_safe(ev.party_id, donor_id, sizeof(ev.party_id));
        ev.delta = delta;
        fund->event_sink(&ev, fund->event_sink_ctx);
    }
    return SF_OK;
}

int scholarship_fund_allocate_grant(scholarship_fund_t *fund,
                                    const char         *student_id,
                                    int64_t             amount_cents)
{
    if (!fund || !student_id) return SF_ERR_NULL_ARGUMENT;
    if (amount_cents <= 0)    return SF_ERR_INVALID_AMOUNT;

    money_t delta = {0};
    strcpy(delta.currency, fund->total_balance.currency);
    delta.cents = amount_cents;

    /* Check if student already has an allocation */
    if (find_allocation(fund, student_id))
        return SF_ERR_ALLOCATION_EXISTS;

    /* Business invariant – funds available? */
    int64_t available = scholarship_fund_available_balance(fund);
    if (available < amount_cents)
        return SF_ERR_INSUFFICIENT_FUNDS;

    /* Append allocation (grow vector if needed) */
    int rc = ensure_capacity(fund);
    if (rc != SF_OK) return rc;

    allocation_t *slot = &fund->allocations[fund->allocated_count++];
    memset(slot, 0, sizeof(*slot));
    strncmpi_safe(slot->student_id, student_id, sizeof(slot->student_id));
    slot->amount = delta;

    /* Update reserved balance */
    rc = money_add(&fund->reserved_balance, &delta);
    if (rc != SF_OK) return rc;

    /* Emit event */
    if (fund->event_sink) {
        scholarship_fund_event_t ev = {
            .type = SFE_GRANT_ALLOCATED,
            .occurred_at = time(NULL)
        };
        strncmpi_safe(ev.fund_id, fund->fund_id, sizeof(ev.fund_id));
        strncmpi_safe(ev.party_id, student_id, sizeof(ev.party_id));
        ev.delta = delta;
        fund->event_sink(&ev, fund->event_sink_ctx);
    }
    return SF_OK;
}

int scholarship_fund_release_grant(scholarship_fund_t *fund,
                                   const char         *student_id)
{
    if (!fund || !student_id) return SF_ERR_NULL_ARGUMENT;

    /* Find allocation */
    allocation_t *alloc = find_allocation(fund, student_id);
    if (!alloc) return SF_ERR_ALLOCATION_NOT_FOUND;

    money_t delta = alloc->amount; /* positive cents */

    /* Remove allocation by swapping with last element */
    fund->allocations[alloc - fund->allocations] =
        fund->allocations[fund->allocated_count - 1];
    fund->allocated_count--;

    /* Update reserved balance (subtract) */
    delta.cents *= -1; /* negative */
    int rc = money_add(&fund->reserved_balance, &delta);
    if (rc != SF_OK) return rc;

    /* Emit event */
    if (fund->event_sink) {
        delta.cents *= -1; /* Convert back to positive for event payload */
        scholarship_fund_event_t ev = {
            .type = SFE_GRANT_RELEASED,
            .occurred_at = time(NULL)
        };
        strncmpi_safe(ev.fund_id, fund->fund_id, sizeof(ev.fund_id));
        strncmpi_safe(ev.party_id, student_id, sizeof(ev.party_id));
        ev.delta = delta;
        fund->event_sink(&ev, fund->event_sink_ctx);
    }
    return SF_OK;
}

int64_t scholarship_fund_available_balance(const scholarship_fund_t *fund)
{
    if (!fund) return 0;
    return fund->total_balance.cents - fund->reserved_balance.cents;
}

/*---------------------------------------------------------------
 *  Private Helpers Implementation
 *--------------------------------------------------------------*/

/* Ensure vector can hold one more allocation */
static int ensure_capacity(scholarship_fund_t *fund)
{
    if (fund->allocated_count < fund->allocated_capacity)
        return SF_OK;

    if (fund->allocated_capacity >= MAX_ALLOCATIONS)
        return SF_ERR_ALLOCATION_CAP_EXCEEDED;

    size_t new_cap = fund->allocated_capacity * 2;
    if (new_cap > MAX_ALLOCATIONS)
        new_cap = MAX_ALLOCATIONS;

    allocation_t *new_mem =
        realloc(fund->allocations, new_cap * sizeof(allocation_t));
    if (!new_mem) return SF_ERR_INTERNAL;

    fund->allocations = new_mem;
    fund->allocated_capacity = new_cap;
    return SF_OK;
}

/* Linear search – fine for few hundred entries; can switch to
 * hashmap when capacity thresholds exceeded. */
static allocation_t *find_allocation(scholarship_fund_t *fund,
                                     const char *student_id)
{
    if (!fund || !student_id) return NULL;
    for (size_t i = 0; i < fund->allocated_count; ++i) {
        if (strcmp(fund->allocations[i].student_id, student_id) == 0)
            return &fund->allocations[i];
    }
    return NULL;
}

/*---------------------------------------------------------------
 *  Debug/Test Harness (compile with -DSF_STANDALONE_MAIN)
 *--------------------------------------------------------------*/
#ifdef SF_STANDALONE_MAIN
/* Simple stdout event sink */
static void stdout_sink(const scholarship_fund_event_t *ev, void *ctx)
{
    (void)ctx;
    printf("[EVENT] type=%d fund=%s party=%s amount=%lld %s\n",
           ev->type, ev->fund_id, ev->party_id,
           (long long)ev->delta.cents, ev->delta.currency);
}

int main(void)
{
    scholarship_fund_t *fund;
    int rc = scholarship_fund_init(&fund, "FUND-123", "STEM Scholars",
                                   "USD", 1000000, stdout_sink, NULL);
    if (rc != SF_OK) { fprintf(stderr, "Init failed: %d\n", rc); return 1; }

    scholarship_fund_record_donation(fund, "DONOR-A", 250000);
    scholarship_fund_allocate_grant(fund, "STUDENT-42", 500000);
    scholarship_fund_release_grant(fund, "STUDENT-42");

    printf("Available balance: %lld\n",
           (long long)scholarship_fund_available_balance(fund));

    scholarship_fund_dispose(fund);
    return 0;
}
#endif
