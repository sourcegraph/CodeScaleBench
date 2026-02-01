/**
 * ============================================================================
 *  EduPay Ledger Academy
 *  --------------------------------------------------------------------------
 *  File        : stipend.c
 *  License     : MIT (see project root)
 *  Description : Pure domain logic for Financial-Aid “Stipend” sub-context.
 *
 *  This compilation unit purposefully avoids any dependency on I/O, databases,
 *  or third-party frameworks.  All code paths are deterministic and therefore
 *  unit-testable without mocks outside the domain boundary.  Side-effects such
 *  as persistence or messaging are expressed through callback abstractions so
 *  that infrastructure can be wired-in from outer layers without violating the
 *  Clean Architecture rule set.
 * ============================================================================
 */

#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <time.h>
#include <errno.h>

#include "stipend.h"            /* Public header for this component          */
#include "../common/money.h"     /* Domain-level value object                 */
#include "../common/date_util.h" /* Deterministic date arithmetic helpers     */

/* ────────────────────────────────────────────────────────────────────────── */
/*  Compile-time Configuration                                               */
/* ────────────────────────────────────────────────────────────────────────── */

#ifndef STIPEND_MAX_AMOUNT_MINOR
/* Upper bound for a single stipend disbursement (in minor units, e.g. cents) */
#define STIPEND_MAX_AMOUNT_MINOR   (25000LL * 100) /* == 25,000.00 */
#endif

#ifndef STIPEND_FRAUD_THRESHOLD_PERCENT
/* % increase between scheduled period amounts that triggers a fraud alert  */
#define STIPEND_FRAUD_THRESHOLD_PERCENT   50
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/*  Private Helpers                                                          */
/* ────────────────────────────────────────────────────────────────────────── */

/* Safe compare of two currencies (ISO-4217 α-3). Returns 0==equal. */
static inline int _currency_cmp(const char a[4], const char b[4])
{
    return (a[0]-b[0]) | (a[1]-b[1]) | (a[2]-b[2]);
}

/* Issue a domain event through the injected dispatcher if present. */
static inline void _publish_event(const stipend_ctx_t       *ctx,
                                  const stipend_event_t     *evt)
{
    if (ctx && ctx->dispatch && evt) {
        ctx->dispatch(evt, ctx->dispatch_udata);
    }
}

/* Convert Money value into target currency using injected FX adapter. */
static money_t _convert_currency(const stipend_ctx_t *ctx,
                                 money_t               in,
                                 const char            target_iso[4],
                                 int                  *err)
{
    if (_currency_cmp(in.currency, target_iso) == 0) {
        return in; /* Nothing to do */
    }

    if (!ctx || !ctx->fx_convert) {
        if (err) *err = EINVAL;
        return money_zero();
    }

    return ctx->fx_convert(in, target_iso, err);
}

/* Detect anomalous stipend jump between consecutive disbursements. */
static bool _is_fraudulent_jump(money_t prev, money_t next)
{
    if (_currency_cmp(prev.currency, next.currency) != 0 || prev.amount == 0)
        return false; /* Different currencies or init case */

    int64_t delta = next.amount - prev.amount;
    if (delta <= 0) return false;

    /* Compute integer percentage */
    int64_t pct = (delta * 100) / prev.amount;
    return pct > STIPEND_FRAUD_THRESHOLD_PERCENT;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Public API Implementation                                                */
/* ────────────────────────────────────────────────────────────────────────── */

int stipend_plan_init(stipend_plan_t      *plan,
                      money_t              amount_per_period,
                      stipend_schedule_e   schedule,
                      struct tm            start_date,
                      struct tm            end_date)
{
    if (!plan)                      return EINVAL;
    if (amount_per_period.amount <= 0)    return ERANGE;
    if (amount_per_period.amount > STIPEND_MAX_AMOUNT_MINOR) return ERANGE;
    if (date_util_cmp(&start_date, &end_date) >= 0)          return EDOM;

    memset(plan, 0, sizeof(*plan));

    plan->amount_per_period = amount_per_period;
    plan->schedule          = schedule;
    plan->start_date        = start_date;
    plan->end_date          = end_date;
    plan->total_disbursed   = money_zero();
    plan->last_disbursed_at = (struct tm){0}; /* Null */

    return 0;
}

bool stipend_is_active(const stipend_plan_t *plan, const struct tm *today)
{
    if (!plan || !today) return false;
    return date_util_cmp(today, &plan->start_date) >= 0 &&
           date_util_cmp(today, &plan->end_date)   <= 0;
}

int stipend_next_due_date(const stipend_plan_t *plan,
                          struct tm            *result)
{
    if (!plan || !result) return EINVAL;

    if (plan->schedule == STIPEND_SCHEDULE_ONE_TIME) {
        *result = plan->start_date;
        return 0;
    }

    /* For recurring payments, compute next period based on last disbursement. */
    struct tm anchor;

    if (plan->last_disbursed_at.tm_year == 0) {
        anchor = plan->start_date;
    } else {
        anchor = plan->last_disbursed_at;
    }

    switch (plan->schedule) {
    case STIPEND_SCHEDULE_MONTHLY:
        date_util_add_months(&anchor, 1, result);
        break;
    case STIPEND_SCHEDULE_WEEKLY:
        date_util_add_days(&anchor, 7, result);
        break;
    case STIPEND_SCHEDULE_BIWEEKLY:
        date_util_add_days(&anchor, 14, result);
        break;
    default:
        return EINVAL;
    }

    return 0;
}

int stipend_process_disbursement(stipend_plan_t      *plan,
                                 const stipend_ctx_t *ctx,
                                 struct tm            today,
                                 stipend_payout_t    *out_payout)
{
    if (!plan || !out_payout) return EINVAL;
    memset(out_payout, 0, sizeof(*out_payout));

    /* 1) Ensure stipend is active today. */
    if (!stipend_is_active(plan, &today))
        return EPERM;

    /* 2) Determine if today is a due date. */
    struct tm next_due;
    int rc = stipend_next_due_date(plan, &next_due);
    if (rc) return rc;

    if (date_util_cmp(&today, &next_due) != 0)
        return EAGAIN; /* Not yet time */

    /* 3) Business rule: detect fraudulent jumps. */
    if (_is_fraudulent_jump(plan->amount_per_period, plan->prev_period_amount)) {
        stipend_event_t alert = {
            .kind = STIPEND_EVT_FRAUD_SUSPECTED,
            .data.fraud = {
                .plan_id      = plan->id,
                .prev_amount  = plan->prev_period_amount,
                .new_amount   = plan->amount_per_period
            }
        };
        _publish_event(ctx, &alert);
    }

    /* 4) Produce payout */
    int err = 0;
    money_t net_amount = plan->amount_per_period; /* Pre-conversion amount    */

    /* Multi-currency settlement scenario */
    if (ctx && ctx->settlement_currency[0] != '\0') {
        net_amount = _convert_currency(ctx,
                                       plan->amount_per_period,
                                       ctx->settlement_currency,
                                       &err);
        if (err) return err;
    }

    /* 5) Populate payout struct */
    out_payout->plan_id   = plan->id;
    out_payout->amount    = net_amount;
    out_payout->value_date= today;

    /* 6) Update plan state */
    plan->total_disbursed = money_add(plan->total_disbursed, net_amount, &err);
    plan->last_disbursed_at = today;
    plan->prev_period_amount = plan->amount_per_period;

    /* 7) Emit domain events */
    stipend_event_t paid_evt = {
        .kind = STIPEND_EVT_DISBURSED,
        .data.disbursed = {
            .plan_id = plan->id,
            .amount  = net_amount,
            .date    = today
        }
    };
    _publish_event(ctx, &paid_evt);

    return 0;
}

/* Update the periodic amount—e.g. scholarship committee increases stipend. */
int stipend_adjust_amount(stipend_plan_t      *plan,
                          const money_t        new_amount,
                          const stipend_ctx_t *ctx)
{
    if (!plan) return EINVAL;
    if (_currency_cmp(new_amount.currency,
                      plan->amount_per_period.currency) != 0) return EDOM;
    if (new_amount.amount <= 0 || new_amount.amount > STIPEND_MAX_AMOUNT_MINOR)
        return ERANGE;

    money_t old_amount = plan->amount_per_period;
    plan->amount_per_period = new_amount;

    stipend_event_t evt = {
        .kind = STIPEND_EVT_AMOUNT_ADJUSTED,
        .data.adjusted = {
            .plan_id    = plan->id,
            .old_amount = old_amount,
            .new_amount = new_amount
        }
    };
    _publish_event(ctx, &evt);

    return 0;
}

/* Cancel stipend plan prematurely—for example, student drops out. */
int stipend_cancel(stipend_plan_t      *plan,
                   const stipend_ctx_t *ctx,
                   struct tm            today)
{
    if (!plan) return EINVAL;

    if (date_util_cmp(&today, &plan->end_date) > 0)
        return EALREADY; /* Already expired */

    plan->end_date = today; /* Close out immediately */

    stipend_event_t evt = {
        .kind = STIPEND_EVT_CANCELLED,
        .data.cancelled = {
            .plan_id = plan->id,
            .date    = today
        }
    };
    _publish_event(ctx, &evt);

    return 0;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Debug Helpers (may be compiled-out in production via NDEBUG)             */
/* ────────────────────────────────────────────────────────────────────────── */
#ifndef NDEBUG
void stipend_debug_print(const stipend_plan_t *plan)
{
    if (!plan) return;

    char start_buf[DATE_UTIL_ISO_DATE_BUFSZ];
    char end_buf[DATE_UTIL_ISO_DATE_BUFSZ];
    char last_buf[DATE_UTIL_ISO_DATE_BUFSZ];

    date_util_fmt_iso(&plan->start_date, start_buf, sizeof start_buf);
    date_util_fmt_iso(&plan->end_date,   end_buf,   sizeof end_buf);

    if (plan->last_disbursed_at.tm_year != 0)
        date_util_fmt_iso(&plan->last_disbursed_at,
                          last_buf, sizeof last_buf);
    else
        strcpy(last_buf, "<never>");

    printf("[StipendPlan] id=%llu amount=%lld %s schedule=%d "
           "start=%s end=%s last=%s total_disbursed=%lld %s\n",
           (unsigned long long)plan->id,
           (long long)plan->amount_per_period.amount,
           plan->amount_per_period.currency,
           plan->schedule,
           start_buf,
           end_buf,
           last_buf,
           (long long)plan->total_disbursed.amount,
           plan->total_disbursed.currency);
}
#endif /* NDEBUG */

/* =============================== END OF FILE ============================= */
