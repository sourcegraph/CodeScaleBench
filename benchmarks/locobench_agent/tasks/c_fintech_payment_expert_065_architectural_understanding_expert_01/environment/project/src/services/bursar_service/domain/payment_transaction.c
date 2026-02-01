/**
 * EduPay Ledger Academy
 * Bursar Service :: Domain Layer
 *
 * File: payment_transaction.c
 *
 * Description:
 *     Pure-domain implementation of the PaymentTransaction aggregate.
 *     Contains business rules for constructing, validating, authorizing,
 *     settling, reversing, and auditing tuition-related payments while
 *     remaining agnostic of persistence, messaging, or UI concerns.
 *
 *     No external dependencies are introduced—only the C standard library.
 *     Integration with infrastructure (database, message broker, etc.)
 *     must occur in the application/service layers via the header-level
 *     abstractions exposed here.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <time.h>
#include <errno.h>
#include <inttypes.h>

#include "payment_transaction.h"

/* ────────────────────────────────────────────────────────────────────────── *
 *  Internal helpers                                                         *
 * ────────────────────────────────────────────────────────────────────────── */

/* Initial number of lines allocated for a transaction */
#define PT_INITIAL_LINE_CAPACITY 4U

/* Maximum absolute value for a _single_ line in minor units (e.g., cents).
 * Used for a simplistic fraud-detection heuristic in the domain layer.     */
#define PT_MAX_LINE_AMOUNT_MINOR  (5000000000LL) /* => 50,000.00 in a 1/100 currency */

/* Convert timespec to unix epoch milliseconds */
static int64_t _pt_timespec_to_epoch_ms(const struct timespec *ts)
{
    return (int64_t)ts->tv_sec * 1000LL + ts->tv_nsec / 1000000LL;
}

/* Generate a pseudo-UUID (version 4 like) suitable for *local* uniqueness. 
 * NOTE: Domain layer avoids pulling external crypto/random libs; cryptographic
 *       strength is NOT guaranteed. Infrastructure can override through the
 *       factory API.                                                         */
static void _pt_generate_uuid(char out_uuid[PT_UUID_STR_LEN])
{
    static const char *hex = "0123456789abcdef";

    unsigned char rnd[16];
    for (size_t i = 0; i < sizeof(rnd); ++i)
        rnd[i] = (unsigned char)rand();

    /* Set version (4) and variant bits per RFC 4122 */
    rnd[6] = (rnd[6] & 0x0F) | 0x40;
    rnd[8] = (rnd[8] & 0x3F) | 0x80;

    snprintf(out_uuid, PT_UUID_STR_LEN,
        "%c%c%c%c%c%c%c%c-%c%c%c%c-%c%c%c%c-%c%c%c%c-%c%c%c%c%c%c%c%c%c%c%c%c",
        hex[rnd[0] >> 4],  hex[rnd[0] & 0x0F],
        hex[rnd[1] >> 4],  hex[rnd[1] & 0x0F],
        hex[rnd[2] >> 4],  hex[rnd[2] & 0x0F],
        hex[rnd[3] >> 4],  hex[rnd[3] & 0x0F],
        hex[rnd[4] >> 4],  hex[rnd[4] & 0x0F],
        hex[rnd[5] >> 4],  hex[rnd[5] & 0x0F],
        hex[rnd[6] >> 4],  hex[rnd[6] & 0x0F],
        hex[rnd[7] >> 4],  hex[rnd[7] & 0x0F],
        hex[rnd[8] >> 4],  hex[rnd[8] & 0x0F],
        hex[rnd[9] >> 4],  hex[rnd[9] & 0x0F],
        hex[rnd[10] >> 4], hex[rnd[10] & 0x0F],
        hex[rnd[11] >> 4], hex[rnd[11] & 0x0F],
        hex[rnd[12] >> 4], hex[rnd[12] & 0x0F],
        hex[rnd[13] >> 4], hex[rnd[13] & 0x0F],
        hex[rnd[14] >> 4], hex[rnd[14] & 0x0F],
        hex[rnd[15] >> 4], hex[rnd[15] & 0x0F]);
}

/* Validate ISO-4217 currency code */
static bool _pt_is_currency_code_valid(const char *code)
{
    if (!code) return false;
    size_t len = strlen(code);
    if (len != 3) return false;
    for (size_t i = 0; i < 3; ++i)
        if (code[i] < 'A' || code[i] > 'Z')
            return false;
    return true;
}

/* ────────────────────────────────────────────────────────────────────────── *
 *  Public API implementation                                                *
 * ────────────────────────────────────────────────────────────────────────── */

PaymentTransaction *pt_create(const char *student_id,
                              const char *source_system,
                              pt_error_t *o_err)
{
    if (!student_id || !source_system) {
        if (o_err) *o_err = PT_ERR_INVALID_ARG;
        return NULL;
    }

    PaymentTransaction *pt = calloc(1, sizeof(*pt));
    if (!pt) {
        if (o_err) *o_err = PT_ERR_OOM;
        return NULL;
    }

    /* Basic scalar initialization */
    pt->line_capacity = PT_INITIAL_LINE_CAPACITY;
    pt->lines         = calloc(pt->line_capacity, sizeof(PaymentLine));
    if (!pt->lines) {
        free(pt);
        if (o_err) *o_err = PT_ERR_OOM;
        return NULL;
    }

    _pt_generate_uuid(pt->id);
    strncpy(pt->student_id,   student_id,   sizeof(pt->student_id) - 1);
    strncpy(pt->source_system, source_system, sizeof(pt->source_system) - 1);
    pt->status = PT_STATUS_PENDING;

    /* timestamps */
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    pt->created_epoch_ms = _pt_timespec_to_epoch_ms(&ts);
    pt->updated_epoch_ms = pt->created_epoch_ms;

    if (o_err) *o_err = PT_OK;
    return pt;
}

void pt_free(PaymentTransaction *pt)
{
    if (!pt) return;

    for (size_t i = 0; i < pt->line_count; ++i) {
        /* zero sensitive data */
        memset(pt->lines[i].description, 0, sizeof(pt->lines[i].description));
    }

    free(pt->lines);
    memset(pt, 0, sizeof(*pt));
    free(pt);
}

pt_error_t pt_add_line(PaymentTransaction *pt,
                       const char *description,
                       int64_t amount_minor,
                       const char *currency_code)
{
    if (!pt || !description || !_pt_is_currency_code_valid(currency_code))
        return PT_ERR_INVALID_ARG;

    if (pt->status != PT_STATUS_PENDING)
        return PT_ERR_STATE_TRANSITION_NOT_ALLOWED;

    /* Defensive check for fraud heuristic soft-limit */
    if (llabs(amount_minor) > PT_MAX_LINE_AMOUNT_MINOR)
        return PT_ERR_AMOUNT_EXCEEDS_LIMIT;

    /* Ensure capacity */
    if (pt->line_count == pt->line_capacity) {
        size_t new_cap = pt->line_capacity * 2;
        PaymentLine *tmp = realloc(pt->lines, new_cap * sizeof(PaymentLine));
        if (!tmp) return PT_ERR_OOM;
        pt->lines = tmp;
        pt->line_capacity = new_cap;
    }

    /* Populate line */
    PaymentLine *line = &pt->lines[pt->line_count++];
    memset(line, 0, sizeof(*line));
    strncpy(line->description, description, sizeof(line->description) - 1);
    line->amount_minor = amount_minor;
    strncpy(line->currency, currency_code, 3);

    /* Update modification timestamp */
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    pt->updated_epoch_ms = _pt_timespec_to_epoch_ms(&ts);

    return PT_OK;
}

/* Domain rule: All lines must have same currency and non-zero sum */
pt_error_t pt_validate(const PaymentTransaction *pt)
{
    if (!pt) return PT_ERR_INVALID_ARG;
    if (pt->line_count == 0) return PT_ERR_NO_LINES;

    const char *currency = pt->lines[0].currency;
    int64_t sum = 0;

    for (size_t i = 0; i < pt->line_count; ++i) {
        const PaymentLine *l = &pt->lines[i];

        if (strncmp(l->currency, currency, 3) != 0)
            return PT_ERR_MULTI_CURRENCY_NOT_ALLOWED;

        /* Prevent zero-value lines; they clutter ledger */
        if (l->amount_minor == 0)
            return PT_ERR_ZERO_AMOUNT_LINE;

        sum += l->amount_minor;
    }

    if (sum == 0) return PT_ERR_NET_ZERO_TRANSACTION;

    return PT_OK;
}

pt_error_t pt_authorize(PaymentTransaction *pt)
{
    if (!pt) return PT_ERR_INVALID_ARG;
    if (pt->status != PT_STATUS_PENDING)
        return PT_ERR_STATE_TRANSITION_NOT_ALLOWED;

    pt_error_t val_err = pt_validate(pt);
    if (val_err != PT_OK) return val_err;

    pt->status = PT_STATUS_AUTHORIZED;

    /* timestamp */
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    pt->authorized_epoch_ms = _pt_timespec_to_epoch_ms(&ts);
    pt->updated_epoch_ms    = pt->authorized_epoch_ms;

    return PT_OK;
}

pt_error_t pt_settle(PaymentTransaction *pt)
{
    if (!pt) return PT_ERR_INVALID_ARG;
    if (pt->status != PT_STATUS_AUTHORIZED)
        return PT_ERR_STATE_TRANSITION_NOT_ALLOWED;

    pt->status = PT_STATUS_SETTLED;

    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    pt->settled_epoch_ms = _pt_timespec_to_epoch_ms(&ts);
    pt->updated_epoch_ms = pt->settled_epoch_ms;
    return PT_OK;
}

pt_error_t pt_reverse(PaymentTransaction *pt, const char *reason)
{
    if (!pt) return PT_ERR_INVALID_ARG;
    if (pt->status != PT_STATUS_AUTHORIZED &&
        pt->status != PT_STATUS_SETTLED)
        return PT_ERR_STATE_TRANSITION_NOT_ALLOWED;

    pt->status = PT_STATUS_REVERSED;
    strncpy(pt->reversal_reason, reason ? reason : "unspecified",
            sizeof(pt->reversal_reason) - 1);

    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    pt->reversed_epoch_ms = _pt_timespec_to_epoch_ms(&ts);
    pt->updated_epoch_ms  = pt->reversed_epoch_ms;

    return PT_OK;
}

pt_error_t pt_total_amount(const PaymentTransaction *pt,
                           int64_t *o_total_minor,
                           char out_currency[4])
{
    if (!pt || !o_total_minor) return PT_ERR_INVALID_ARG;
    int64_t sum = 0;
    for (size_t i = 0; i < pt->line_count; ++i)
        sum += pt->lines[i].amount_minor;

    *o_total_minor = sum;
    if (out_currency && pt->line_count > 0)
        strncpy(out_currency, pt->lines[0].currency, 3);

    return PT_OK;
}

/* Format a human-readable snapshot into dst (buffersize) */
size_t pt_format_summary(const PaymentTransaction *pt,
                         char *dst, size_t dst_sz)
{
    if (!pt || !dst || dst_sz == 0) return 0;

    int64_t total = 0;
    pt_total_amount(pt, &total, NULL);

    return snprintf(dst, dst_sz,
            "PaymentTransaction{id=%s, student=%s, status=%s, lines=%zu, "
            "total=%" PRId64 " %3.3s}",
            pt->id,
            pt->student_id,
            pt_status_to_str(pt->status),
            pt->line_count,
            total,
            pt->line_count > 0 ? pt->lines[0].currency : "UNK");
}

/* String representation of enum */
const char *pt_status_to_str(pt_status_t st)
{
    switch (st) {
        case PT_STATUS_PENDING:    return "PENDING";
        case PT_STATUS_AUTHORIZED: return "AUTHORIZED";
        case PT_STATUS_SETTLED:    return "SETTLED";
        case PT_STATUS_REVERSED:   return "REVERSED";
        case PT_STATUS_FAILED:     return "FAILED";
        default:                   return "UNKNOWN";
    }
}

/* String representation of error code */
const char *pt_err_to_str(pt_error_t e)
{
    switch (e) {
        case PT_OK:                              return "OK";
        case PT_ERR_OOM:                         return "Out of memory";
        case PT_ERR_INVALID_ARG:                 return "Invalid argument";
        case PT_ERR_NO_LINES:                    return "No payment lines provided";
        case PT_ERR_MULTI_CURRENCY_NOT_ALLOWED:  return "Multiple currencies not allowed";
        case PT_ERR_ZERO_AMOUNT_LINE:            return "Line amount cannot be zero";
        case PT_ERR_NET_ZERO_TRANSACTION:        return "Net amount of transaction is zero";
        case PT_ERR_STATE_TRANSITION_NOT_ALLOWED:return "State transition not allowed";
        case PT_ERR_AMOUNT_EXCEEDS_LIMIT:        return "Amount exceeds configured limit";
        default:                                 return "Unknown error";
    }
}

/* ────────────────────────────────────────────────────────────────────────── *
 *  Simple self-test (may be disabled in production)                          *
 * ────────────────────────────────────────────────────────────────────────── */

#ifdef EDU_PAY_LEDGER_ENABLE_SELFTEST
int main(void)
{
    srand((unsigned)time(NULL));

    pt_error_t err;
    PaymentTransaction *pt = pt_create("student#1234", "registrar_ui", &err);
    if (!pt) {
        fprintf(stderr, "Failed to create transaction: %s\n", pt_err_to_str(err));
        return EXIT_FAILURE;
    }

    pt_add_line(pt, "COMP-SCI 101 Tuition",  500000, "USD");
    pt_add_line(pt, "Lab Materials Fee",      25000, "USD");
    pt_add_line(pt, "Early-Payment Discount",-10000, "USD");

    err = pt_authorize(pt);
    if (err != PT_OK) {
        fprintf(stderr, "Authorize failed: %s\n", pt_err_to_str(err));
        pt_free(pt);
        return EXIT_FAILURE;
    }

    err = pt_settle(pt);
    if (err != PT_OK) {
        fprintf(stderr, "Settle failed: %s\n", pt_err_to_str(err));
        pt_free(pt);
        return EXIT_FAILURE;
    }

    char summary[256];
    pt_format_summary(pt, summary, sizeof(summary));
    puts(summary);

    pt_free(pt);
    return EXIT_SUCCESS;
}
#endif /* EDU_PAY_LEDGER_ENABLE_SELFTEST */
