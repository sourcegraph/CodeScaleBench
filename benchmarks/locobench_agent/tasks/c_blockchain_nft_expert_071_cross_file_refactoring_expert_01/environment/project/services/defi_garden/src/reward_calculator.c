```c
/**
 * HoloCanvas – DeFi-Garden Service
 * --------------------------------
 * reward_calculator.c
 *
 * Production-grade reward computation engine for staking pools that power the
 * artistic micro-economy.  A single compilation unit is provided so that it can
 * be embedded or tested in isolation; nevertheless, the code is written in a
 * modular fashion to facilitate future refactors into separate headers/objs.
 *
 * Copyright (c) 2024
 * SPDX-License-Identifier: MIT
 */

#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <time.h>

#define RC_SUCCESS           0
#define RC_ERR_BAD_ARG      -1
#define RC_ERR_RANGE        -2
#define RC_ERR_INTERNAL     -3

/*––--------------------------------------------------------------------*/
/*  Compile-time configuration                                          */
/*------------------------------------------------------------------------*/

/* Maximum allowed APY (in %) to avoid accidental misconfiguration.      */
#ifndef RC_MAX_APY_PERCENT
#define RC_MAX_APY_PERCENT  200.0
#endif

/* Maximum engagement coefficient multiplier allowed for performance-based
 * reward calculation. Prevents runaway rewards if an oracle misbehaves. */
#ifndef RC_MAX_ENGAGE_COEFF
#define RC_MAX_ENGAGE_COEFF 15.0
#endif

/*––--------------------------------------------------------------------*/
/*  Public type declarations                                            */
/*------------------------------------------------------------------------*/

typedef enum
{
    RC_POLICY_FIXED_APY = 0,     /* Simple rate, yearly compounded.                */
    RC_POLICY_PERFORMANCE,       /* Adjust reward based on engagement metrics.     */
    RC_POLICY_TIERED             /* Progressive tiers — larger stakes earn more.   */
} rc_policy_t;

/* A single staker’s position (NFT fractional shares, LP tokens, etc.)           */
typedef struct
{
    uint64_t  account_id;    /* User identifier (not security-sensitive).         */
    double    stake_amount;  /* Amount in base units (e.g., HCanvas tokens).      */
    time_t    ts_staked;     /* Epoch when position was created.                  */
} rc_position_t;

/* Live metrics tied to an artifact or a liquidity pool.                          */
typedef struct
{
    uint64_t  artifact_id;    /* NFT / Pool identifier.                           */
    double    engagement;     /* Weighted score from 0.0 – 1.0 (likes, votes…).   */
    double    price_delta;    /* 0.05 = 5 % appreciation since stake.             */
} rc_metric_t;

/* Policy parameters loaded from governance-controlled config.                    */
typedef struct
{
    rc_policy_t policy;
    union
    {
        struct           /*–– Fixed APY parameters ––*/
        {
            double apy_percent;      /* Annual percentage yield.                 */
        } fixed;

        struct           /*–– Performance-based parameters ––*/
        {
            double base_apy;         /* Base APY when engagement == 0.0.          */
            double engage_coeff;     /* Multiplier for engagement weight.         */
        } perf;

        struct           /*–– Tiered parameters ––*/
        {
            double tier1_amt;  /* <= tier1_amt → tier1_apy                       */
            double tier1_apy;
            double tier2_amt;  /* <= tier2_amt → tier2_apy                       */
            double tier2_apy;
            double tier3_apy;  /* > tier2_amt                                    */
        } tier;
    };
} rc_policy_cfg_t;

/*––--------------------------------------------------------------------*/
/*  Internal helper utilities                                            */
/*------------------------------------------------------------------------*/

/* Convert seconds of staking to fraction of year (365 days). */
static inline double
seconds_to_years(time_t delta_sec)
{
    return (double)delta_sec / (365.0 * 24.0 * 3600.0);
}

/* Clamp a value between min and max. */
static inline double
clamp_double(double val, double min, double max)
{
    return (val < min) ? min : (val > max) ? max : val;
}

/* Compute compound interest using continuous compounding:
 *
 *     A = P * e^(r * t)
 *     Reward = A - P
 *
 * where:
 *   P = principal
 *   r = annual rate (as decimal)
 *   t = time in years
 */
static double
compound_continuous(double principal, double annual_rate, double years)
{
    return principal * (exp(annual_rate * years) - 1.0);
}

/* Resolve APY based on tiered amounts. */
static double
resolve_tier_apy(const rc_policy_cfg_t *cfg, double amount)
{
    if (amount <= cfg->tier.tier1_amt) return cfg->tier.tier1_apy;
    if (amount <= cfg->tier.tier2_amt) return cfg->tier.tier2_apy;
    return cfg->tier.tier3_apy;
}

/*––--------------------------------------------------------------------*/
/*  Public API                                                           */
/*------------------------------------------------------------------------*/

/**
 * rc_calculate_reward
 *
 * Compute staking reward for a single position, using the supplied policy
 * parameters and (optional) performance metrics.
 *
 * Parameters
 * ----------
 *  pos         – Position descriptor (non-NULL).
 *  metric      – Performance metrics (may be NULL when policy != PERFORMANCE).
 *  cfg         – Policy configuration (non-NULL).
 *  reward_out  – Output pointer where the computed reward is stored.
 *
 * Returns
 * -------
 *  RC_SUCCESS on success, negative error code otherwise.
 */
int
rc_calculate_reward(const rc_position_t *pos,
                    const rc_metric_t   *metric,
                    const rc_policy_cfg_t *cfg,
                    double              *reward_out)
{
    if (!pos || !cfg || !reward_out) return RC_ERR_BAD_ARG;

    /* Ensure stake amount is sane. */
    if (pos->stake_amount <= 0.0 || isnan(pos->stake_amount) ||
        !isfinite(pos->stake_amount))
    {
        return RC_ERR_RANGE;
    }

    /* Time delta validation. */
    time_t now = time(NULL);
    if (pos->ts_staked <= 0 || pos->ts_staked > now)
    {
        return RC_ERR_RANGE;
    }

    /* Duration held in years. */
    double years_held = seconds_to_years(now - pos->ts_staked);
    if (years_held <= 0.0)
    {
        /* Nothing accrued yet — zero reward. */
        *reward_out = 0.0;
        return RC_SUCCESS;
    }

    double apy = 0.0;   /* Annual percentage yield, as decimal (0.04 == 4 %). */

    switch (cfg->policy)
    {
        case RC_POLICY_FIXED_APY:
            apy = cfg->fixed.apy_percent / 100.0;
            break;

        case RC_POLICY_PERFORMANCE:
        {
            if (!metric)
            {
                syslog(LOG_ERR,
                       "PERFORMANCE policy selected but metric == NULL");
                return RC_ERR_BAD_ARG;
            }

            /* Engagement is expected in [0,1]. */
            double engage = clamp_double(metric->engagement, 0.0, 1.0);

            /* price_delta is allowed to be negative (-0.10 = –10 %). */
            double price_factor = 1.0 + metric->price_delta;

            /* Derive effective APY. */
            double coeff =
                clamp_double(cfg->perf.engage_coeff, 0.0, RC_MAX_ENGAGE_COEFF);

            apy = (cfg->perf.base_apy / 100.0) +
                  (engage * coeff / 100.0) * price_factor;
            break;
        }

        case RC_POLICY_TIERED:
            apy = resolve_tier_apy(cfg, pos->stake_amount) / 100.0;
            break;

        default:
            syslog(LOG_ERR, "Unknown policy value: %d", cfg->policy);
            return RC_ERR_BAD_ARG;
    }

    /* Guardrail against unrealistic APY due to config errors. */
    apy = clamp_double(apy, 0.0, RC_MAX_APY_PERCENT / 100.0);

    /* Compute compounded reward. */
    double reward = compound_continuous(pos->stake_amount, apy, years_held);

    /* Final sanity check. */
    if (!isfinite(reward) || reward < 0.0)
    {
        syslog(LOG_ERR, "Reward calculation overflow/underflow");
        return RC_ERR_INTERNAL;
    }

    *reward_out = reward;
    return RC_SUCCESS;
}

/*––--------------------------------------------------------------------*/
/*  Example usage / self-test when compiled standalone                   */
/*------------------------------------------------------------------------*/
#ifdef RC_SELFTEST

static void
run_selftest(void)
{
    rc_position_t pos = {
        .account_id   = 42,
        .stake_amount = 10'000.0,
        .ts_staked    = time(NULL) - 90 * 24 * 3600 /* 90 days ago */
    };

    /* 1. Fixed APY test. */
    rc_policy_cfg_t cfg_fixed = {
        .policy = RC_POLICY_FIXED_APY,
        .fixed  = { .apy_percent = 8.0 }
    };

    double reward = 0.0;
    if (rc_calculate_reward(&pos, NULL, &cfg_fixed, &reward) == RC_SUCCESS)
        printf("[FIXED] reward: %.6f\n", reward);

    /* 2. Performance-based test. */
    rc_metric_t metric = {
        .artifact_id  = 1337,
        .engagement   = 0.75,
        .price_delta  = 0.12
    };

    rc_policy_cfg_t cfg_perf = {
        .policy = RC_POLICY_PERFORMANCE,
        .perf   = {
            .base_apy      = 5.0,
            .engage_coeff  = 7.5
        }
    };

    if (rc_calculate_reward(&pos, &metric, &cfg_perf, &reward) == RC_SUCCESS)
        printf("[PERF ] reward: %.6f\n", reward);

    /* 3. Tiered test. */
    rc_policy_cfg_t cfg_tier = {
        .policy = RC_POLICY_TIERED,
        .tier   = {
            .tier1_amt = 1'000.0,
            .tier1_apy = 5.0,
            .tier2_amt = 5'000.0,
            .tier2_apy = 7.0,
            .tier3_apy = 10.0
        }
    };

    if (rc_calculate_reward(&pos, NULL, &cfg_tier, &reward) == RC_SUCCESS)
        printf("[TIER ] reward: %.6f\n", reward);
}

int
main(void)
{
    openlog("reward_calculator", LOG_PERROR | LOG_PID, LOG_USER);
    run_selftest();
    closelog();
    return EXIT_SUCCESS;
}

#endif /* RC_SELFTEST */
```