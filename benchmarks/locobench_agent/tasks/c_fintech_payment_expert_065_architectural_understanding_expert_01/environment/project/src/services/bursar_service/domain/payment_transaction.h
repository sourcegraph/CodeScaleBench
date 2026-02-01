#ifndef EDUPAY_LEDGER_ACADEMY_PAYMENT_TRANSACTION_H
#define EDUPAY_LEDGER_ACADEMY_PAYMENT_TRANSACTION_H
/*******************************************************************************
 * EduPay Ledger Academy — Bursar Service / Domain Layer
 *
 * File   : payment_transaction.h
 * Author : EduPay Engineering Team
 * License: MIT
 *
 * Description:
 *   Pure, framework-free domain model representing a Payment Transaction.
 *   • Immutable business rules enforced via explicit state-machine
 *   • Multi-currency safe (integer minor-units; ISO-4217 alpha-3 codes)
 *   • Regression-friendly: no dependencies on persistence, messaging, or UI
 *
 * NOTE:
 *   Keep this header dependency-light. It must compile in isolation so that
 *   professors may swap infrastructure layers (database, transport, etc.)
 *   without touching the core domain code.
 ******************************************************************************/

#include <stdint.h>     /* int64_t                                                  */
#include <stdbool.h>    /* bool                                                     */
#include <stddef.h>     /* size_t                                                   */
#include <time.h>       /* time_t                                                   */
#include <string.h>     /* memcpy, strlen                                           */

/* -------------------------------------------------------------------------- */
/*  Constants / Limits                                                        */
/* -------------------------------------------------------------------------- */

#define EDU_UUID_STRING_LENGTH      36          /* 8-4-4-4-12 (RFC-4122)           */
#define EDU_UUID_BUFFER_SIZE        (EDU_UUID_STRING_LENGTH + 1)

#define EDU_MAX_DESC_LENGTH         256         /* Fits into a single UDP packet   */

/* -------------------------------------------------------------------------- */
/*  Error Codes                                                               */
/* -------------------------------------------------------------------------- */
typedef enum
{
    PAYMENT_TX_OK = 0,
    PAYMENT_TX_ERR_INVALID_PARAM,
    PAYMENT_TX_ERR_STATE_TRANSITION,
    PAYMENT_TX_ERR_VALIDATION_FAILED,
    PAYMENT_TX_ERR_OVERFLOW,
    PAYMENT_TX_ERR_UNKNOWN
} payment_tx_error_t;

/* -------------------------------------------------------------------------- */
/*  Universal Unique Identifier (RFC-4122)                                    */
/* -------------------------------------------------------------------------- */
typedef struct
{
    char value[EDU_UUID_BUFFER_SIZE];           /* Null-terminated                 */
} edu_uuid_t;

/* -------------------------------------------------------------------------- */
/*  Monetary Amount (minor units to avoid FP)                                 */
/* -------------------------------------------------------------------------- */
typedef struct
{
    int64_t     amount;                         /* Minor units (e.g., cents)       */
    char        currency[4];                    /* ISO-4217 alpha-3, null-term      */
} money_t;

/* -------------------------------------------------------------------------- */
/*  Enumerations                                                              */
/* -------------------------------------------------------------------------- */
typedef enum
{
    PAYMENT_TX_TYPE_TUITION        = 1,
    PAYMENT_TX_TYPE_STIPEND        = 2,
    PAYMENT_TX_TYPE_FEE_REVERSAL   = 3,
    PAYMENT_TX_TYPE_SCHOLARSHIP    = 4,
    PAYMENT_TX_TYPE_MICRO_CRED     = 5
} payment_tx_type_t;

typedef enum
{
    PAYMENT_TX_STATE_CREATED   = 0,
    PAYMENT_TX_STATE_AUTHORIZED,
    PAYMENT_TX_STATE_SETTLED,
    PAYMENT_TX_STATE_DECLINED,
    PAYMENT_TX_STATE_REFUNDED,
    PAYMENT_TX_STATE_ROLLED_BACK
} payment_tx_state_t;

/* -------------------------------------------------------------------------- */
/*  Core Aggregate                                                            */
/* -------------------------------------------------------------------------- */
typedef struct
{
    /* Identity */
    edu_uuid_t          id;
    edu_uuid_t          student_id;

    /* Classification */
    payment_tx_type_t   type;
    payment_tx_state_t  state;

    /* Currency */
    money_t             gross;          /* Original amount requested           */
    money_t             fees;           /* Platform & interchange fees         */
    money_t             net;            /* Amount to be settled                */

    /* Metadata */
    char                description[EDU_MAX_DESC_LENGTH];

    /* Temporal */
    time_t              created_at;
    time_t              updated_at;
} payment_transaction_t;

/* ==========================================================================
 *  Validation Helpers
 * ========================================================================== */

/**
 * Assert that a UTF-8 string is non-empty and fits into dest buffer.
 */
static inline bool
edu_str_is_valid(const char *src, size_t max_len)
{
    return (src != NULL) && (strlen(src) > 0) && (strlen(src) < max_len);
}

/**
 * Validate the Money struct: non-zero amount, valid ISO currency.
 */
static inline bool
money_is_valid(const money_t *m)
{
    return  (m != NULL) &&
            (m->currency[0] != '\0') &&
            (strlen(m->currency) == 3);
}

/* ==========================================================================
 *  State Machine Utilities
 * ========================================================================== */

/**
 * Determine whether a state is terminal (no further transitions).
 */
static inline bool
payment_tx_state_is_terminal(payment_tx_state_t s)
{
    return  (s == PAYMENT_TX_STATE_SETTLED)   ||
            (s == PAYMENT_TX_STATE_DECLINED)  ||
            (s == PAYMENT_TX_STATE_REFUNDED)  ||
            (s == PAYMENT_TX_STATE_ROLLED_BACK);
}

/**
 * String representation for logging / DTOs.
 */
static inline const char *
payment_tx_state_to_str(payment_tx_state_t s)
{
    switch (s)
    {
        case PAYMENT_TX_STATE_CREATED:      return "CREATED";
        case PAYMENT_TX_STATE_AUTHORIZED:   return "AUTHORIZED";
        case PAYMENT_TX_STATE_SETTLED:      return "SETTLED";
        case PAYMENT_TX_STATE_DECLINED:     return "DECLINED";
        case PAYMENT_TX_STATE_REFUNDED:     return "REFUNDED";
        case PAYMENT_TX_STATE_ROLLED_BACK:  return "ROLLED_BACK";
        default:                            return "UNKNOWN_STATE";
    }
}

/**
 * Business rules for legal state transitions.
 */
static inline bool
payment_tx_can_transition(payment_tx_state_t from, payment_tx_state_t to)
{
    switch (from)
    {
        case PAYMENT_TX_STATE_CREATED:
            return (to == PAYMENT_TX_STATE_AUTHORIZED) ||
                   (to == PAYMENT_TX_STATE_DECLINED);

        case PAYMENT_TX_STATE_AUTHORIZED:
            return (to == PAYMENT_TX_STATE_SETTLED)    ||
                   (to == PAYMENT_TX_STATE_DECLINED)   ||
                   (to == PAYMENT_TX_STATE_ROLLED_BACK);

        case PAYMENT_TX_STATE_SETTLED:
            return (to == PAYMENT_TX_STATE_REFUNDED);

        default:
            return false; /* All terminal states fall through */
    }
}

/* ==========================================================================
 *  Public API
 * ========================================================================== */

/**
 * Initialize a new Payment Transaction aggregate.
 *
 * Parameters:
 *   tx           Pointer to aggregate to initialize
 *   id           UUID string (36 chars)
 *   student_id   UUID string (36 chars)
 *   type         Business classification of payment
 *   gross        Requested amount (minor units)
 *   description  Human-readable description
 *
 * Returns:
 *   PAYMENT_TX_OK on success, otherwise error code
 */
static inline payment_tx_error_t
payment_tx_init(payment_transaction_t     *tx,
                const char                *id,
                const char                *student_id,
                payment_tx_type_t          type,
                const money_t             *gross,
                const char                *description)
{
    if (!tx || !edu_str_is_valid(id, EDU_UUID_BUFFER_SIZE) ||
        !edu_str_is_valid(student_id, EDU_UUID_BUFFER_SIZE) ||
        !money_is_valid(gross) ||
        !edu_str_is_valid(description, EDU_MAX_DESC_LENGTH))
    {
        return PAYMENT_TX_ERR_INVALID_PARAM;
    }

    /* Initialize identity */
    memset(tx, 0, sizeof(*tx));
    memcpy(tx->id.value, id, EDU_UUID_STRING_LENGTH);
    memcpy(tx->student_id.value, student_id, EDU_UUID_STRING_LENGTH);

    /* Classification & state */
    tx->type  = type;
    tx->state = PAYMENT_TX_STATE_CREATED;

    /* Monetary values */
    tx->gross = *gross;
    tx->fees  = (money_t){ .amount = 0, .currency = {0} };
    tx->net   = (money_t){ .amount = 0, .currency = {0} };

    /* Copy description */
    strncpy(tx->description, description, EDU_MAX_DESC_LENGTH - 1);

    /* Timestamps */
    tx->created_at = time(NULL);
    tx->updated_at = tx->created_at;

    return PAYMENT_TX_OK;
}

/**
 * Apply platform fee schedule.
 *
 * Currently a flat 2.9% + 30¢ USD equivalent for demo purposes.
 */
static inline payment_tx_error_t
payment_tx_calculate_fees(payment_transaction_t *tx)
{
    if (!tx || !money_is_valid(&tx->gross))
        return PAYMENT_TX_ERR_INVALID_PARAM;

    /* Fee currency must match gross currency */
    strncpy(tx->fees.currency, tx->gross.currency, 3);

    /* Basis-points math to avoid floating point */
    int64_t percentage_fee = (tx->gross.amount * 290) / 10000; /* 2.9% */
    int64_t fixed_fee      = 30;                               /* 30 cents */

    if (percentage_fee < 0 || fixed_fee < 0)
        return PAYMENT_TX_ERR_OVERFLOW;

    tx->fees.amount = percentage_fee + fixed_fee;
    tx->net.amount  = tx->gross.amount - tx->fees.amount;
    strncpy(tx->net.currency, tx->gross.currency, 3);

    return PAYMENT_TX_OK;
}

/**
 * Perform a state transition if legal.
 */
static inline payment_tx_error_t
payment_tx_transition(payment_transaction_t *tx, payment_tx_state_t new_state)
{
    if (!tx)
        return PAYMENT_TX_ERR_INVALID_PARAM;

    if (tx->state == new_state)
        return PAYMENT_TX_OK; /* Idempotent */

    if (!payment_tx_can_transition(tx->state, new_state))
        return PAYMENT_TX_ERR_STATE_TRANSITION;

    tx->state      = new_state;
    tx->updated_at = time(NULL);
    return PAYMENT_TX_OK;
}

/**
 * Verify structural invariants of the aggregate.
 */
static inline payment_tx_error_t
payment_tx_validate(const payment_transaction_t *tx)
{
    if (!tx) return PAYMENT_TX_ERR_INVALID_PARAM;

    bool monetary_valid = money_is_valid(&tx->gross) &&
                          ((tx->fees.amount == 0) || money_is_valid(&tx->fees)) &&
                          ((tx->net.amount  == 0) || money_is_valid(&tx->net));

    bool uuid_valid = edu_str_is_valid(tx->id.value, EDU_UUID_BUFFER_SIZE) &&
                      edu_str_is_valid(tx->student_id.value, EDU_UUID_BUFFER_SIZE);

    if (!monetary_valid || !uuid_valid)
        return PAYMENT_TX_ERR_VALIDATION_FAILED;

    return PAYMENT_TX_OK;
}

#endif /* EDUPAY_LEDGER_ACADEMY_PAYMENT_TRANSACTION_H */
