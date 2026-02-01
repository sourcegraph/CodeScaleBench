/*
 * money.c
 * EduPay Ledger Academy - Shared Kernel / Domain
 *
 * A currency-aware “Money” value object that encapsulates monetary arithmetic
 * without floating-point rounding errors. Uses a 64-bit signed integer to
 * store the smallest denomination (cent) and prevents mixing currencies at
 * compile-time through explicit APIs.
 *
 * Copyright (c) 2024  EduPay Ledger Academy
 * SPDX-License-Identifier: MIT
 */

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <inttypes.h>
#include <ctype.h>
#include <math.h>

/* ────────────────────────────────────────────────────────────────────────── */
/* Public API                                                                */
/* ────────────────────────────────────────────────────────────────────────── */

/* The currently supported ISO-4217 currencies.
 * Note: keep the order in sync with currency_code_table[].
 */
typedef enum {
    CUR_INVALID = 0,
    CUR_USD,
    CUR_EUR,
    CUR_GBP,
    CUR_JPY,
    CUR_AUD,
    CUR_CAD,
    CUR_CHF,
    CUR_CNY,
    CUR_INR,
    CUR_MAX_ENUM /* sentinel */
} Currency;

typedef struct {
    int64_t  cents;     /* monetary amount in the smallest denomination */
    Currency currency;  /* ISO-4217 code */
} Money;

/* Error/Status codes returned by this module. */
typedef enum {
    MONEY_OK = 0,
    MONEY_ENULLPTR        = -1,
    MONEY_EOVERFLOW       = -2,
    MONEY_EINVALCURRENCY  = -3,
    MONEY_ECURRMISMATCH   = -4,
    MONEY_EPARSE          = -5,
    MONEY_EDIVZERO        = -6
} MoneyStatus;

/* Constructors / parsers */
MoneyStatus money_create  (int64_t cents, Currency cur, Money *out);
MoneyStatus money_from_double(double amount, Currency cur, Money *out);          /* ex: 10.23 */
MoneyStatus money_parse   (const char *str, Money *out);                         /* ex: "USD 10.23" */

/* Arithmetic */
MoneyStatus money_add     (const Money *lhs, const Money *rhs, Money *out);
MoneyStatus money_sub     (const Money *lhs, const Money *rhs, Money *out);
MoneyStatus money_mul     (const Money *lhs, double factor, Money *out);        /* factor may be negative */
MoneyStatus money_split   (const Money *total, size_t n_parts, Money *parts);   /* fair-share allocation */

/* Comparison */
MoneyStatus money_cmp     (const Money *lhs, const Money *rhs, int *result);    /* result: -1,0,1 */

/* Utilities */
const char *currency_to_string(Currency cur);
Currency     currency_from_string(const char *str);

void         money_print(const Money *m, FILE *stream); /* helper */

/* ────────────────────────────────────────────────────────────────────────── */
/* Implementation                                                            */
/* ────────────────────────────────────────────────────────────────────────── */

/* compile-time assert that int64_t is at least 64 bits */
typedef char static_assert_int64_t_is_64bits[sizeof(int64_t) == 8 ? 1 : -1];

/* Table mapping enum -> 3-letter code. Index must match enum order. */
static const char *currency_code_table[CUR_MAX_ENUM] = {
    "INV", /* CUR_INVALID */
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "AUD",
    "CAD",
    "CHF",
    "CNY",
    "INR"
};

/* internal: safe addition with overflow detection */
static int safe_add_int64(int64_t a, int64_t b, int64_t *out)
{
    if (!out) return -1;
    if ((b > 0 && a > INT64_MAX - b) ||
        (b < 0 && a < INT64_MIN - b)) {
        return -1; /* overflow */
    }
    *out = a + b;
    return 0;
}

/* internal: safe multiplication (int64 * double -> int64) with rounding */
static int safe_mul_int64_double(int64_t cents, double factor, int64_t *out)
{
    if (!out) return -1;
    long double res = (long double)cents * (long double)factor;
    if (res > INT64_MAX || res < INT64_MIN) {
        return -1; /* overflow */
    }
    /* round to nearest cent, away from zero */
    *out = (int64_t) (res > 0 ? res + 0.5L : res - 0.5L);
    return 0;
}

/* currency helpers */
const char *currency_to_string(Currency cur)
{
    if (cur <= CUR_INVALID || cur >= CUR_MAX_ENUM) {
        return "INV";
    }
    return currency_code_table[cur];
}

Currency currency_from_string(const char *str)
{
    if (!str || strlen(str) != 3) return CUR_INVALID;

    char up[4] = {0};
    up[0] = (char)toupper((unsigned char)str[0]);
    up[1] = (char)toupper((unsigned char)str[1]);
    up[2] = (char)toupper((unsigned char)str[2]);

    for (int i = 1; i < (int)CUR_MAX_ENUM; ++i) {
        if (strncmp(up, currency_code_table[i], 3) == 0) {
            return (Currency)i;
        }
    }
    return CUR_INVALID;
}

/* Constructors */

MoneyStatus money_create(int64_t cents, Currency cur, Money *out)
{
    if (!out) return MONEY_ENULLPTR;
    if (cur <= CUR_INVALID || cur >= CUR_MAX_ENUM) return MONEY_EINVALCURRENCY;
    out->cents    = cents;
    out->currency = cur;
    return MONEY_OK;
}

MoneyStatus money_from_double(double amount, Currency cur, Money *out)
{
    if (!out) return MONEY_ENULLPTR;
    if (cur <= CUR_INVALID || cur >= CUR_MAX_ENUM) return MONEY_EINVALCURRENCY;

    /* multiply by 100 to get cents, rounding away from zero */
    long double cents_ld = (long double)amount * 100.0L;
    if (cents_ld > INT64_MAX || cents_ld < INT64_MIN) return MONEY_EOVERFLOW;

    int64_t cents = (int64_t) (cents_ld > 0 ? cents_ld + 0.5L : cents_ld - 0.5L);
    out->cents    = cents;
    out->currency = cur;
    return MONEY_OK;
}

/* Parses "USD 10.23" or "10.23 USD" (whitespace delimited) */
MoneyStatus money_parse(const char *str, Money *out)
{
    if (!str || !out) return MONEY_ENULLPTR;

    char code[4] = {0};
    double amount = 0.0;
    int matched = 0;

    /* Try <CUR> <amount> first */
    matched = sscanf(str, " %3s %lf ", code, &amount);
    if (matched != 2) {
        /* Try <amount> <CUR> */
        matched = sscanf(str, " %lf %3s ", &amount, code);
        if (matched != 2) {
            return MONEY_EPARSE;
        }
    }

    Currency cur = currency_from_string(code);
    if (cur == CUR_INVALID) return MONEY_EINVALCURRENCY;
    return money_from_double(amount, cur, out);
}

/* Arithmetic */

MoneyStatus money_add(const Money *lhs, const Money *rhs, Money *out)
{
    if (!lhs || !rhs || !out) return MONEY_ENULLPTR;
    if (lhs->currency != rhs->currency) return MONEY_ECURRMISMATCH;

    int64_t sum;
    if (safe_add_int64(lhs->cents, rhs->cents, &sum) != 0) {
        return MONEY_EOVERFLOW;
    }

    out->cents    = sum;
    out->currency = lhs->currency;
    return MONEY_OK;
}

MoneyStatus money_sub(const Money *lhs, const Money *rhs, Money *out)
{
    if (!lhs || !rhs || !out) return MONEY_ENULLPTR;
    if (lhs->currency != rhs->currency) return MONEY_ECURRMISMATCH;

    int64_t diff;
    if (safe_add_int64(lhs->cents, -rhs->cents, &diff) != 0) {
        return MONEY_EOVERFLOW;
    }

    out->cents    = diff;
    out->currency = lhs->currency;
    return MONEY_OK;
}

MoneyStatus money_mul(const Money *lhs, double factor, Money *out)
{
    if (!lhs || !out) return MONEY_ENULLPTR;

    int64_t product;
    if (safe_mul_int64_double(lhs->cents, factor, &product) != 0) {
        return MONEY_EOVERFLOW;
    }

    out->cents    = product;
    out->currency = lhs->currency;
    return MONEY_OK;
}

/* Splits total into n_parts fairly (each part >= 0).
 * Remainder cents are distributed to the first buckets.
 */
MoneyStatus money_split(const Money *total, size_t n_parts, Money *parts)
{
    if (!total || !parts) return MONEY_ENULLPTR;
    if (n_parts == 0)     return MONEY_EDIVZERO;

    int64_t base = total->cents / (int64_t)n_parts;
    int64_t rem  = llabs(total->cents % (int64_t)n_parts); /* remainder is positive */

    for (size_t i = 0; i < n_parts; ++i) {
        int64_t share = base;
        /* distribute remainder cents (one cent each) */
        if ((int64_t)i < rem) {
            share += (total->cents >= 0) ? 1 : -1;
        }
        parts[i].cents    = share;
        parts[i].currency = total->currency;
    }
    return MONEY_OK;
}

/* Comparison. result = -1 if lhs < rhs, 0 if equal, 1 if lhs > rhs */
MoneyStatus money_cmp(const Money *lhs, const Money *rhs, int *result)
{
    if (!lhs || !rhs || !result) return MONEY_ENULLPTR;
    if (lhs->currency != rhs->currency) return MONEY_ECURRMISMATCH;

    if (lhs->cents < rhs->cents)      *result = -1;
    else if (lhs->cents == rhs->cents)*result = 0;
    else                              *result = 1;

    return MONEY_OK;
}

/* Debug printer */
void money_print(const Money *m, FILE *stream)
{
    if (!m || !stream) return;
    fprintf(stream, "%s %" PRId64 ".%02" PRId64,
            currency_to_string(m->currency),
            m->cents / 100,
            llabs(m->cents % 100));
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Unit-like internal test (can be removed in production)                    */
/* ────────────────────────────────────────────────────────────────────────── */
#ifdef MONEY_SELF_TEST
#include <assert.h>
int main(void)
{
    Money a, b, c;
    assert(money_from_double(10.23, CUR_USD, &a) == MONEY_OK);
    assert(money_from_double( 5.77, CUR_USD, &b) == MONEY_OK);
    assert(money_add(&a, &b, &c) == MONEY_OK);
    assert(c.cents == 1600);

    int cmp = 0;
    assert(money_cmp(&a, &b, &cmp) == MONEY_OK);
    assert(cmp == 1);

    Money parts[3];
    assert(money_split(&c, 3, parts) == MONEY_OK);

    for (int i = 0; i < 3; ++i) {
        money_print(&parts[i], stdout);
        putchar('\n');
    }
    return 0;
}
#endif