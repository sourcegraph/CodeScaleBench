/*
 * EduPay Ledger Academy
 * Shared Kernel / Domain / Money
 *
 * Copyright (c) 2023-2024 EduPay
 *
 * This file defines the canonical Money value-object used across every
 * bounded-context (Admissions, Bursar, Financial-Aid, etc.).  The structure is
 * purposely framework-agnostic so that educators can swap persistence layers,
 * message brokers, or UI shells without impacting business rules.
 *
 * Design notes
 * ------------
 * 1. Amount is stored in the *minor* unit (e.g., cents) as a 64-bit signed
 *    integer to avoid floating-point rounding errors.
 * 2. ISO-4217 alpha-3 currency codes are used.  Validation is built-in so
 *    erroneous codes are rejected early.
 * 3. All operations guarantee currency homogeneity; cross-currency math must
 *    be handled by the FX service in the multi-currency bounded context.
 * 4. Overflow checks leverage compiler intrinsics when available
 *    (__builtin_add_overflow / __builtin_mul_overflow).  Fallback logic is
 *    provided for non-GNU/Clang toolchains.
 * 5. This header is fully self-contained: implementation is declared `static
 *    inline` so that business-rule code can include it directly without
 *    linking.
 */

#ifndef EDUPAY_LEDGER_ACADEMY_SHARED_KERNEL_DOMAIN_MONEY_H
#define EDUPAY_LEDGER_ACADEMY_SHARED_KERNEL_DOMAIN_MONEY_H

/* NOLINTBEGIN (clang-tidy readability-identifier-naming) */

#include <stdint.h>   /* int64_t, uint8_t, etc. */
#include <stdbool.h>  /* bool                    */
#include <stddef.h>   /* size_t                  */
#include <string.h>   /* memcpy, strlen          */
#include <stdio.h>    /* snprintf                */
#include <limits.h>   /* INT64_MAX               */

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------- */
/* Public Types                                                               */
/* -------------------------------------------------------------------------- */

/* Maximum length of an ISO-4217 alpha-3 currency code including null byte. */
#define MONEY_CURRENCY_CODE_LEN 4

/* Forward declaration for internal use. */
struct Money;

/*
 * Result codes for all Money API calls.  Always check the returned status.
 * (Think of these as domain-level exceptions in languages that support them.)
 */
typedef enum
{
    MONEY_OK = 0,
    MONEY_ERR_NULL_ARGUMENT,
    MONEY_ERR_INVALID_CURRENCY,
    MONEY_ERR_CURRENCY_MISMATCH,
    MONEY_ERR_ARITHMETIC_OVERFLOW
} MoneyError;

/*
 * Canonical value-object.  Immutable by convention; all mutating operations
 * return a *new* instance so calling code can remain pure/functional.
 */
typedef struct Money
{
    int64_t amount_minor;                     /* e.g. cents, pence, satoshi   */
    char    currency[MONEY_CURRENCY_CODE_LEN];/* "USD", "EUR", "JPY", …      */
} Money;

/* -------------------------------------------------------------------------- */
/* Utility Macros                                                             */
/* -------------------------------------------------------------------------- */

/* Compiler-agnostic overflow helpers. */
#if defined(__GNUC__) || defined(__clang__)
    #define MONEY_ADD_OVERFLOW(a, b, result) __builtin_add_overflow((a), (b), (result))
    #define MONEY_MUL_OVERFLOW(a, b, result) __builtin_mul_overflow((a), (b), (result))
#else
    /* Portable—though slightly slower—fallbacks. */
    static inline bool MONEY_ADD_OVERFLOW(int64_t a, int64_t b, int64_t *r)
    {
        *r = a + b;
        return ((b > 0) && (a > INT64_MAX - b)) ||
               ((b < 0) && (a < INT64_MIN - b));
    }

    static inline bool MONEY_MUL_OVERFLOW(int64_t a, int64_t b, int64_t *r)
    {
        /* Early outs for 0 and 1 to reduce branch cost. */
        if (a == 0 || b == 0) { *r = 0; return false; }
        if (a == 1)           { *r = b; return false; }
        if (b == 1)           { *r = a; return false; }

        *r = a * b;
        return (a == (*r / b)) ? false : true;
    }
#endif

/* -------------------------------------------------------------------------- */
/* Internal helpers (static inline, not exported)                             */
/* -------------------------------------------------------------------------- */

/* Validates that `code` is an uppercase ISO-4217 alpha-3 currency code. */
static inline bool
_money_is_valid_currency(const char *code)
{
    if (!code) return false;
    size_t len = strlen(code);
    if (len != 3U) return false;

    /* Ensure A-Z characters only. */
    for (size_t i = 0; i < 3; ++i)
    {
        char c = code[i];
        if (c < 'A' || c > 'Z') return false;
    }
    return true;
}

/* Ensures two Money values share the same currency. */
static inline bool
_money_same_currency(const Money *a, const Money *b)
{
    return (a && b) && (strncmp(a->currency, b->currency, 3) == 0);
}

/* -------------------------------------------------------------------------- */
/* API                                                                        */
/* -------------------------------------------------------------------------- */

/*
 * money_create
 *
 * Construct a Money value from minor units (e.g., cents).
 * Example: money_create(&usd, "USD", 12345); // $123.45
 */
static inline MoneyError
money_create(Money *out, const char *currency, int64_t amount_minor)
{
    if (!out || !currency) return MONEY_ERR_NULL_ARGUMENT;
    if (!_money_is_valid_currency(currency)) return MONEY_ERR_INVALID_CURRENCY;

    memcpy(out->currency, currency, 3);
    out->currency[3] = '\0';        /* Null-terminate */
    out->amount_minor = amount_minor;
    return MONEY_OK;
}

/*
 * money_zero
 *
 * Creates a zero-value Money instance for the given currency.
 */
static inline MoneyError
money_zero(Money *out, const char *currency)
{
    return money_create(out, currency, 0);
}

/*
 * money_add
 *
 * Adds two Money values with identical currency.  `out` may alias `a` or `b`.
 */
static inline MoneyError
money_add(const Money *a, const Money *b, Money *out)
{
    if (!a || !b || !out) return MONEY_ERR_NULL_ARGUMENT;
    if (!_money_same_currency(a, b)) return MONEY_ERR_CURRENCY_MISMATCH;

    int64_t result;
    if (MONEY_ADD_OVERFLOW(a->amount_minor, b->amount_minor, &result))
        return MONEY_ERR_ARITHMETIC_OVERFLOW;

    memcpy(out, a, sizeof(Money));  /* Copy currency as well */
    out->amount_minor = result;
    return MONEY_OK;
}

/*
 * money_subtract
 *
 * Subtracts `b` from `a`.  `out = a - b`
 */
static inline MoneyError
money_subtract(const Money *a, const Money *b, Money *out)
{
    if (!a || !b || !out) return MONEY_ERR_NULL_ARGUMENT;
    if (!_money_same_currency(a, b)) return MONEY_ERR_CURRENCY_MISMATCH;

    int64_t result;
    if (MONEY_ADD_OVERFLOW(a->amount_minor, -b->amount_minor, &result))
        return MONEY_ERR_ARITHMETIC_OVERFLOW;

    memcpy(out, a, sizeof(Money));
    out->amount_minor = result;
    return MONEY_OK;
}

/*
 * money_multiply
 *
 * Multiplies a Money amount by an integer factor.  Fractional scalars should
 * be handled by a dedicated rounding/FX service.
 */
static inline MoneyError
money_multiply(const Money *a, int64_t factor, Money *out)
{
    if (!a || !out) return MONEY_ERR_NULL_ARGUMENT;

    int64_t result;
    if (MONEY_MUL_OVERFLOW(a->amount_minor, factor, &result))
        return MONEY_ERR_ARITHMETIC_OVERFLOW;

    memcpy(out, a, sizeof(Money));
    out->amount_minor = result;
    return MONEY_OK;
}

/*
 * money_compare
 *
 * Lexicographically compares `a` and `b`:
 *   Returns <0 if a < b
 *           0 if a == b
 *           >0 if a > b
 * Currency mismatch results in INT32_MIN as a sentinel error (callers
 * should handle this explicitly).
 */
static inline int
money_compare(const Money *a, const Money *b)
{
    if (!a || !b) return INT32_MIN; /* Treat null as fatal mismatch */
    if (!_money_same_currency(a, b)) return INT32_MIN;

    if (a->amount_minor < b->amount_minor) return -1;
    if (a->amount_minor > b->amount_minor) return 1;
    return 0;
}

/*
 * money_is_zero
 *
 * Convenience helper.
 */
static inline bool
money_is_zero(const Money *value)
{
    return value && (value->amount_minor == 0);
}

/*
 * money_to_string
 *
 * Renders a Money value as human-readable ASCII into `buf`:
 *   Example: "USD 123.45"
 *
 * The buffer must be at least 32 bytes to accommodate INT64_MIN and currency.
 * The function returns MONEY_OK on success or MONEY_ERR_NULL_ARGUMENT.
 */
static inline MoneyError
money_to_string(const Money *value, char *buf, size_t buf_len)
{
    if (!value || !buf) return MONEY_ERR_NULL_ARGUMENT;
    if (buf_len < 32)   return MONEY_ERR_NULL_ARGUMENT; /* caller guarantee */

    /* Minor units to major (assumes 2-decimal currencies; adapt as needed). */
    int64_t abs_minor = value->amount_minor >= 0 ? value->amount_minor
                                                 : -value->amount_minor;
    int64_t major     = abs_minor / 100;
    int64_t minor     = abs_minor % 100;

    int  written = snprintf(buf,
                            buf_len,
                            "%s %s%" PRId64 ".%02" PRId64,
                            value->currency,
                            (value->amount_minor < 0) ? "-" : "",
                            major,
                            minor);

    /* snprintf returns number of chars that *would* have been written. */
    return (written > 0 && (size_t)written < buf_len)
        ? MONEY_OK
        : MONEY_ERR_NULL_ARGUMENT; /* buffer not large enough */
}

/*
 * money_allocate
 *
 * Split `total` into `n` nearly-equal Money parts such that the sum of the
 * parts equals the original total and leftover pennies are distributed to the
 * first buckets.  This is useful when allocating bursary funds across
 * multi-recipient cohorts.
 *
 * Caller must provide an array `out_parts` of length `n`.
 */
static inline MoneyError
money_allocate(const Money *total,
               size_t        n,
               Money        *out_parts /* array[n] */)
{
    if (!total || !out_parts || n == 0) return MONEY_ERR_NULL_ARGUMENT;

    int64_t quotient  = total->amount_minor / (int64_t)n;
    int64_t remainder = total->amount_minor % (int64_t)n;

    MoneyError err;
    for (size_t i = 0; i < n; ++i)
    {
        int64_t share = quotient + ((int64_t)i < remainder ? 1 : 0);
        err = money_create(&out_parts[i], total->currency, share);
        if (err != MONEY_OK) return err;
    }
    return MONEY_OK;
}

#ifdef __cplusplus
} /* extern "C" */
#endif

/* NOLINTEND (clang-tidy readability-identifier-naming) */
#endif /* EDUPAY_LEDGER_ACADEMY_SHARED_KERNEL_DOMAIN_MONEY_H */
