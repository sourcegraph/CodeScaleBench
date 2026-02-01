```markdown
<!--
######################################################################
# EduPay Ledger Academy – Lesson L04
# Title   : Fraud-Detection Heuristics in a Clean-Architecture C Codebase
# Audience: Senior CS students, FinTech engineers, & security auditors
# Author  : EduPay Curriculum Team
# License : MIT (see root of repository)
######################################################################
-->

# Lesson L04 – Fraud Detection Heuristics  
_“The absence of evidence is not evidence of absence.”_  
— C. T. Hill

Fraud detection is a dynamic, adversarial domain:  
as soon as you codify a rule, fraudsters start probing the edges.  
This lesson walks through the design, implementation, and validation  
of **heuristic-based fraud scoring** inside the EduPay payment rail, all while
adhering to Clean Architecture and Security-by-Design principles.

---

## Table of Contents
1. Learning Objectives
2. Domain Vocabulary
3. Architecture Overview
4. Heuristic Catalogue
5. Reference Implementation (C)
6. Extensibility Hooks
7. Unit-Testing Harness
8. Further Reading

---

## 1. Learning Objectives
After completing this lesson you will be able to:

* Enumerate common fraud-detection heuristics used in higher-education payments.  
* Isolate fraud logic behind a stable interface so that new rules can be A/B tested.  
* Compute an aggregate _Fraud Score_ and decide whether a transaction  
  should **Proceed**, **Review**, or **Reject**.  
* Wire fraud scoring into a Saga-Pattern orchestration without tight coupling.  
* Build a deterministic test harness for security and compliance audits.

---

## 2. Domain Vocabulary
| Term               | Definition                                                                                    |
|--------------------|------------------------------------------------------------------------------------------------|
| TransactionEvent   | Immutable DTO emitted by the payment processor.                                               |
| Fraud Indicator    | Boolean predicate that reveals suspicious behavior (e.g., IP mismatch).                       |
| Fraud Score        | Weighted sum (0–1000) representing the likelihood of malicious activity.                      |
| Decision Threshold | Cut-off points for **Proceed**, **Review**, **Reject** decisions (configurable at runtime).   |

---

## 3. Architecture Overview
```
┌─────────────────────────────────────────┐
│      Domain Layer  (Pure C / No I/O)   │
│                                         │
│  +-------------------------------+       │
│  | IFraudScoringService (iface)  |<─────┐│
│  +-------------------------------+      ││
│  | + compute_score(evt, *score)  |      ││
│  +-------------------------------+      ││
└─────────────────────────────────────────┘│
         ▲                                 │
         │ Dependency Inversion            │
┌────────┴─────────────────────────────────┴───┐
│        Application Layer (Use-Cases)        │
│                                             │
│  +--------------------------------------+    │
│  | FraudAssessmentInteractor            |    │
│  +--------------------------------------+    │
│  | – fraud_svc : IFraudScoringService   |    │
│  | – audit_log  : IAuditTrail           |    │
│  +--------------------------------------+    │
└──────────────────────────────────────────────┘
```

The fraud engine lives **entirely** in the Domain layer.  
No SQL, no Kafka, no HTTP—just pure functions amenable to unit tests.  
Adapters for Redis caches, vector databases, or ML micro-services are
added via the outer layers without polluting the core.

---

## 4. Heuristic Catalogue

| ID  | Name                     | Weight | Description                                                  |
|-----|--------------------------|--------|--------------------------------------------------------------|
| H01 | Velocity Check           | 150    | ≥ 3 payments from same student in < 5 min.                    |
| H02 | Geo-IP Mismatch          | 200    | Card BIN country ≠ client IP geo.                            |
| H03 | Dormant Account Spike    | 120    | No activity for 90 days then sudden purchase > $1 000.       |
| H04 | Night-Owl Activity       | 80     | Transaction between 02:00 – 05:00 campus local time.         |
| H05 | Blacklisted Beneficiary  | 250    | Payout destination on negative list.                         |
| H06 | High-Risk MCC            | 180    | Merchant Category Code flagged by Mastercard/Visa bulletins. |

All weights and thresholds are **runtime-configurable** via the
`fraud_config.toml` artifact to accommodate campus risk appetites.

---

## 5. Reference Implementation (C)

```c
/**
 * @file fraud_scoring.c
 * @brief Pure-C fraud-detection heuristics for EduPay Ledger Academy.
 *
 * Compile with:
 *     cc -std=c17 -Wall -Wextra -pedantic -Os -c fraud_scoring.c
 *
 * Glue-code linking into micro-services is performed in the Application Layer.
 */

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <string.h>
#include <time.h>

/*────────────────────────── Data Structures ──────────────────────────*/

/* ISO-8601 timestamp stored as seconds since epoch (UTC) */
typedef int64_t epoch_t;

/* Currency-agnostic minor units (cent, penny, etc.) */
typedef int64_t money_t;

/**
 * @struct TransactionEvent
 * @brief Immutable Data Transfer Object representing a payment.
 */
typedef struct
{
    char      account_id[36]; /* UUID-v4 string */
    char      student_id[36]; /* UUID-v4 string */
    char      beneficiary_id[36];
    char      card_bin[8];    /* First 6–8 digits of PAN */
    char      ip_addr[46];    /* Supports IPv6 */
    char      mcc[5];         /* 4-digit Merchant Category Code */
    money_t   amount_minor;   /* Minor units */
    epoch_t   ts_created;     /* Transaction creation time */
} TransactionEvent;

/**
 * @enum FraudDecision
 * @brief Final action taken based on fraud score.
 */
typedef enum
{
    FRAUD_DECISION_PROCEED,
    FRAUD_DECISION_REVIEW,
    FRAUD_DECISION_REJECT
} FraudDecision;

/**
 * @struct FraudScore
 * @brief Aggregated fraud analytics for a given transaction.
 */
typedef struct
{
    uint16_t total_score;        /* 0–1000 */
    uint16_t matched_rules;      /* Bitfield of triggered heuristics */
    FraudDecision decision;      /* Proceed, Review, or Reject */
} FraudScore;

/* Bit positions for `matched_rules` (supports up to 16 heuristics) */
enum
{
    FBIT_H01_VELOCITY        = 1u << 0,
    FBIT_H02_GEO_MISMATCH    = 1u << 1,
    FBIT_H03_DORMANT_SPIKE   = 1u << 2,
    FBIT_H04_NIGHT_OWL       = 1u << 3,
    FBIT_H05_NEGATIVE_LIST   = 1u << 4,
    FBIT_H06_RISKY_MCC       = 1u << 5
};

/*────────────────────────── Configuration ───────────────────────────*/

typedef struct
{
    uint16_t weight_H01;
    uint16_t weight_H02;
    uint16_t weight_H03;
    uint16_t weight_H04;
    uint16_t weight_H05;
    uint16_t weight_H06;
    /* Decision thresholds */
    uint16_t threshold_review;   /* >=→ Review */
    uint16_t threshold_reject;   /* >=→ Reject */
} FraudConfig;

/* Default weights – overridden at runtime via adapter layer */
static const FraudConfig FRAUD_CONFIG_DEFAULT = {
    .weight_H01 = 150,
    .weight_H02 = 200,
    .weight_H03 = 120,
    .weight_H04 =  80,
    .weight_H05 = 250,
    .weight_H06 = 180,
    .threshold_review  = 300,
    .threshold_reject  = 600
};

/*────────── Forward declarations for heuristics (pure functions) ─────────*/

static bool
h01_velocity_check(const TransactionEvent *evt);

static bool
h02_geo_ip_mismatch(const TransactionEvent *evt,
                    const char *resolved_country_iso3166);

static bool
h03_dormant_account_spike(const TransactionEvent *evt,
                          const epoch_t *historical_tx_timestamps,
                          size_t historical_count);

static bool
h04_night_owl_activity(const TransactionEvent *evt,
                       int campus_utc_offset_minutes);

static bool
h05_blacklisted_beneficiary(const TransactionEvent *evt,
                            bool (*is_blacklisted)(const char *beneficiary_id));

static bool
h06_high_risk_mcc(const TransactionEvent *evt,
                  const char *const *high_risk_mccs,
                  size_t mcc_count);

/*────────── Public API ─────────*/

/**
 * @brief Compute fraud score for a transaction.
 *
 * @param evt             Immutable transaction event.
 * @param cfg             Runtime configuration (weights + thresholds).
 * @param outs            Output struct populated by the function.
 * @param dependencies    Pointer to dependency bundle (opaque to Domain).
 *
 * The domain layer remains framework agnostic by accepting **callback
 * functions** and data buffers from the outer layer. This pattern
 * preserves testability while enabling rich integrations.
 */
typedef struct
{
    const char *resolved_country_iso3166; /* Provided by geo-IP adapter */
    const epoch_t *historical_tx_timestamps; /* Sorted ascending */
    size_t historical_count;
    int campus_utc_offset_minutes; /* e.g., ‑300 for EST (-05:00) */
    bool (*is_blacklisted)(const char *beneficiary_id); /* Negative list lookup */
    const char *const *high_risk_mccs; /* Array of MCC strings */
    size_t mcc_count;
} FraudDeps;

void
fraud_compute(const TransactionEvent *evt,
              const FraudConfig     *cfg,
              const FraudDeps       *deps,
              FraudScore            *outs);

/*────────────────────────── Implementation ──────────────────────────*/

static bool
h01_velocity_check(const TransactionEvent *evt)
{
    /* In production, this is implemented in the adapter layer
       using a time-series DB or Redis sorted-set.  Here we
       leave the flag calculation to that external query. */
    (void)evt; /* Unused in domain */
    return false; /* Default – adapter overrides via deps */
}

static bool
h02_geo_ip_mismatch(const TransactionEvent *evt,
                    const char *resolved_country_iso3166)
{
    /* Simple BIN to country prefix comparison. Real implementation
       would consult the ISO-3166 list for each BIN range. */
    if (!resolved_country_iso3166 || strlen(evt->card_bin) < 6)
        return false;

    /* Mock rule: if BIN starts with "40" we assume "US" */
    bool bin_is_us = (strncmp(evt->card_bin, "40", 2) == 0);

    if (bin_is_us && strcmp(resolved_country_iso3166, "US") != 0)
        return true;

    /* Additional mapping omitted for brevity */
    return false;
}

static bool
h03_dormant_account_spike(const TransactionEvent *evt,
                          const epoch_t *historical_tx_timestamps,
                          size_t historical_count)
{
    if (!historical_tx_timestamps || historical_count == 0)
        return false;

    epoch_t last_tx = historical_tx_timestamps[historical_count - 1];
    const int64_t ninety_days_secs = 90LL * 24 * 60 * 60;

    bool dormant = (evt->ts_created - last_tx) > ninety_days_secs;

    /* Threshold > $1 000 – we use minor units: 1000.00 → 100000 */
    bool large_amount = evt->amount_minor >= 100000;

    return dormant && large_amount;
}

static bool
h04_night_owl_activity(const TransactionEvent *evt,
                       int campus_utc_offset_minutes)
{
    time_t raw = (time_t)(evt->ts_created + campus_utc_offset_minutes * 60);
    struct tm tm_local;
#if defined(_POSIX_VERSION)
    gmtime_r(&raw, &tm_local);
#else
    tm_local = *gmtime(&raw);
#endif
    int hour = tm_local.tm_hour;
    return (hour >= 2 && hour < 5);
}

static bool
h05_blacklisted_beneficiary(const TransactionEvent *evt,
                            bool (*is_blacklisted)(const char *beneficiary_id))
{
    if (!is_blacklisted)
        return false;

    return is_blacklisted(evt->beneficiary_id);
}

static bool
h06_high_risk_mcc(const TransactionEvent *evt,
                  const char *const *high_risk_mccs,
                  size_t mcc_count)
{
    for (size_t i = 0; i < mcc_count; ++i)
    {
        if (strncmp(evt->mcc, high_risk_mccs[i], 4) == 0)
            return true;
    }
    return false;
}

void
fraud_compute(const TransactionEvent *evt,
              const FraudConfig     *cfg,
              const FraudDeps       *deps,
              FraudScore            *outs)
{
    if (!evt || !cfg || !deps || !outs)
        return;

    uint16_t score = 0;
    uint16_t rule_bits = 0;

    if (h01_velocity_check(evt))
    {
        score += cfg->weight_H01;
        rule_bits |= FBIT_H01_VELOCITY;
    }
    if (h02_geo_ip_mismatch(evt, deps->resolved_country_iso3166))
    {
        score += cfg->weight_H02;
        rule_bits |= FBIT_H02_GEO_MISMATCH;
    }
    if (h03_dormant_account_spike(evt,
                                  deps->historical_tx_timestamps,
                                  deps->historical_count))
    {
        score += cfg->weight_H03;
        rule_bits |= FBIT_H03_DORMANT_SPIKE;
    }
    if (h04_night_owl_activity(evt, deps->campus_utc_offset_minutes))
    {
        score += cfg->weight_H04;
        rule_bits |= FBIT_H04_NIGHT_OWL;
    }
    if (h05_blacklisted_beneficiary(evt, deps->is_blacklisted))
    {
        score += cfg->weight_H05;
        rule_bits |= FBIT_H05_NEGATIVE_LIST;
    }
    if (h06_high_risk_mcc(evt, deps->high_risk_mccs, deps->mcc_count))
    {
        score += cfg->weight_H06;
        rule_bits |= FBIT_H06_RISKY_MCC;
    }

    FraudDecision decision = FRAUD_DECISION_PROCEED;
    if (score >= cfg->threshold_reject)
        decision = FRAUD_DECISION_REJECT;
    else if (score >= cfg->threshold_review)
        decision = FRAUD_DECISION_REVIEW;

    outs->total_score   = score;
    outs->matched_rules = rule_bits;
    outs->decision      = decision;
}
```

---

## 6. Extensibility Hooks

1. **Dynamic Weighting via TOML**  
   The adapter layer parses `fraud_config.toml` at boot.  
   Hot-reload events are published via `CFG_UPDATED` on NATS.

2. **ML Feature Flag**  
   If `feature.ml_score=true`, the `IFraudScoringService` decorator
   blends heuristic and ML scores using a weighted average.

3. **Audit Trail**  
   All `FraudScore` structs are serialized to the immutable audit log,
   with PII fields tokenized in transit using Format-Preserving Encryption.

---

## 7. Unit-Testing Harness

```c
#include "unity.h"
#include "fraud_scoring.h"

static bool dummy_negative_list(const char *id)
{
    return strcmp(id, "benny-1337") == 0;
}

void test_geo_ip_mismatch(void)
{
    TransactionEvent evt = {
        .card_bin = "401288",
        .ip_addr  = "185.199.108.153",
        .ts_created = 1693500000
    };
    FraudDeps deps = {
        .resolved_country_iso3166 = "GB",
        .campus_utc_offset_minutes = 0,
        .is_blacklisted = dummy_negative_list
    };
    FraudScore out;
    fraud_compute(&evt, &FRAUD_CONFIG_DEFAULT, &deps, &out);
    TEST_ASSERT_TRUE(out.matched_rules & FBIT_H02_GEO_MISMATCH);
    TEST_ASSERT_EQUAL_UINT16(FRAUD_DECISION_REVIEW, out.decision);
}

int main(void)
{
    UNITY_BEGIN();
    RUN_TEST(test_geo_ip_mismatch);
    return UNITY_END();
}
```

Run with:

```
$ cc -std=c17 -Wall -I../unity -o fraud_tests \
      fraud_scoring.c fraud_tests.c ../unity/unity.c
$ ./fraud_tests
```

---

## 8. Further Reading
* _Franklin, J._ “Real-Time Card-not-Present Fraud Detection,” ACM SIGSAC, 2023.  
* PCI-DSS v4.0 §10 “Fraud Monitoring and Detection.”  
* OWASP Cheat Sheet Series – Business Logic Security.  

---  

Happy hacking & stay vigilant!  
— EduPay Ledger Academy Curriculum Team
```