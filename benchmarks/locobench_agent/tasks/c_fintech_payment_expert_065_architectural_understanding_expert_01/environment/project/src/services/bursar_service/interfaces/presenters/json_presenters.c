/**
 * EduPay Ledger Academy - Bursar Service
 * --------------------------------------
 * File:    interfaces/presenters/json_presenters.c
 * Project: fintech_payment
 *
 * JSON presenter implementation that converts Bursar service response/view
 * models into JSON payloads consumable by HTTP or message-bus adapters.
 *
 * This layer contains ZERO business-rule logic.  Its single responsibility is
 * to translate *already-validated* response DTOs into a wire format, while
 * upholding Clean Architecture boundaries.
 *
 * Dependencies
 * ------------
 *  - cJSON (https://github.com/DaveGamble/cJSON) – permissive MIT license
 *
 *  Build flags (example):
 *      gcc -I./include -lcjson -Wall -Wextra -pedantic -c json_presenters.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <errno.h>

#include <cjson/cJSON.h>

#include "json_presenters.h"   /* Public header for this implementation   */
#include "bursar_models.h"     /* Response / view model DTO declarations  */


/* -------------------------------------------------------------------------
 * Internal helpers
 * -------------------------------------------------------------------------*/

/**
 * Safely strdup(3) with errno-aware failure handling.  Returns NULL on OOM.
 */
static char *safe_strdup(const char *src)
{
    if (src == NULL) { return NULL; }

    size_t len = strlen(src) + 1;               /* +1 for NUL byte        */
    char *dst  = (char *)malloc(len);
    if (!dst) {
        /* errno is set by malloc; simply propagate it. */
        return NULL;
    }
    memcpy(dst, src, len);
    return dst;
}


/**
 * Serialise monetary amount to a fixed-precision string (2 decimal places).
 *
 * Using fixed-precision string avoids floating-point rounding anomalies on
 * the consumer side and makes audit logs deterministic.
 */
static bool amount_to_string(double amount,
                             char   *out_buf,
                             size_t  buf_len)
{
    if (!out_buf || buf_len == 0U) { return false; }

    /* Using %.2f to force exactly two decimals (ISO-4217 "minor units"). */
    int written = snprintf(out_buf, buf_len, "%.2f", amount);
    return (written > 0 && (size_t)written < buf_len);
}


/**
 * Convert an array of bursar_line_item_t to a cJSON array.
 */
static cJSON *json_serialize_line_items(const bursar_line_item_t *items,
                                        size_t                    count)
{
    if (!items && count != 0U) { return NULL; }

    cJSON *json_array = cJSON_CreateArray();
    if (!json_array) { return NULL; }

    for (size_t i = 0; i < count; ++i) {
        const bursar_line_item_t *li = &items[i];

        cJSON *li_obj = cJSON_CreateObject();
        if (!li_obj) { cJSON_Delete(json_array); return NULL; }

        /* description */
        cJSON_AddStringToObject(li_obj, "description", li->description);

        /* amount */
        char amt_buf[32] = {0};
        if (!amount_to_string(li->amount, amt_buf, sizeof(amt_buf))) {
            cJSON_Delete(li_obj);
            cJSON_Delete(json_array);
            return NULL;
        }
        cJSON_AddStringToObject(li_obj, "amount", amt_buf);

        /* currency (ISO-4217 three-letter code) */
        cJSON_AddStringToObject(li_obj, "currency", li->currency);

        cJSON_AddItemToArray(json_array, li_obj);
    }

    return json_array;
}


/* -------------------------------------------------------------------------
 * Public API implementation
 * -------------------------------------------------------------------------*/

char *bursar_present_invoice_as_json(
        const bursar_invoice_response_t *resp,
        bursar_json_error_t             *out_err)
{
    if (out_err) { *out_err = BURSAR_JSON_OK; }

    if (!resp) {
        if (out_err) { *out_err = BURSAR_JSON_E_NULLPTR; }
        return NULL;
    }

    cJSON *root = cJSON_CreateObject();
    if (!root) {
        if (out_err) { *out_err = BURSAR_JSON_E_OOM; }
        return NULL;
    }

    /* Top-level scalar fields */
    cJSON_AddStringToObject(root, "invoiceId",  resp->invoice_id);
    cJSON_AddStringToObject(root, "studentId",  resp->student_id);
    cJSON_AddStringToObject(root, "dueDate",    resp->due_date_iso);

    /* Monetary field: amountDue */
    char amt_buf[32] = {0};
    if (!amount_to_string(resp->amount_due, amt_buf, sizeof(amt_buf))) {
        cJSON_Delete(root);
        if (out_err) { *out_err = BURSAR_JSON_E_INTERNAL; }
        return NULL;
    }
    cJSON_AddStringToObject(root, "amountDue", amt_buf);
    cJSON_AddStringToObject(root, "currency", resp->currency);

    /* paid status */
    cJSON_AddBoolToObject(root, "isPaid", resp->is_paid);

    /* Line items */
    cJSON *items_array = json_serialize_line_items(
            resp->line_items, resp->line_item_count);
    if (!items_array && resp->line_item_count != 0U) {
        cJSON_Delete(root);
        if (out_err) { *out_err = BURSAR_JSON_E_OOM; }
        return NULL;
    }
    cJSON_AddItemToObject(root, "lineItems", items_array ?
                          items_array : cJSON_CreateArray());

    /* Render to string */
    char *json_str = cJSON_PrintUnformatted(root);
    if (!json_str) {
        cJSON_Delete(root);
        if (out_err) { *out_err = BURSAR_JSON_E_OOM; }
        return NULL;
    }

    /* Clean up cJSON DOM – string is independent after PrintUnformatted */
    cJSON_Delete(root);
    return json_str;   /* Caller takes ownership and must free(3) */
}


char *bursar_present_transaction_summary_as_json(
        const bursar_transaction_summary_t *summary,
        bursar_json_error_t                *out_err)
{
    if (out_err) { *out_err = BURSAR_JSON_OK; }

    if (!summary) {
        if (out_err) { *out_err = BURSAR_JSON_E_NULLPTR; }
        return NULL;
    }

    cJSON *root = cJSON_CreateObject();
    if (!root) {
        if (out_err) { *out_err = BURSAR_JSON_E_OOM; }
        return NULL;
    }

    cJSON_AddStringToObject(root, "studentId",  summary->student_id);
    cJSON_AddStringToObject(root, "periodFrom", summary->period_start_iso);
    cJSON_AddStringToObject(root, "periodTo",   summary->period_end_iso);
    cJSON_AddNumberToObject(root, "txCount",    (double)summary->transaction_count);

    /* Total amount with fixed-precision string formatting */
    char amt_buf[32] = {0};
    if (!amount_to_string(summary->total_settled_amount, amt_buf, sizeof(amt_buf))) {
        cJSON_Delete(root);
        if (out_err) { *out_err = BURSAR_JSON_E_INTERNAL; }
        return NULL;
    }
    cJSON_AddStringToObject(root, "totalSettledAmount", amt_buf);
    cJSON_AddStringToObject(root, "currency", summary->currency);

    /* Render */
    char *json_str = cJSON_PrintUnformatted(root);
    if (!json_str) {
        cJSON_Delete(root);
        if (out_err) { *out_err = BURSAR_JSON_E_OOM; }
        return NULL;
    }

    cJSON_Delete(root);
    return json_str;
}


char *bursar_present_error_as_json(int error_code,
                                   const char *message)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        /* As a last resort, fall back to static string literal (OOM scenario) */
        return safe_strdup("{\"status\":\"error\",\"code\":500,"
                           "\"message\":\"out_of_memory\"}");
    }

    cJSON_AddStringToObject(root, "status",  "error");
    cJSON_AddNumberToObject(root, "code",    (double)error_code);
    cJSON_AddStringToObject(root, "message", message ? message : "unknown");

    char *json_str = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    if (!json_str) {
        /* Again, fall back if OOM during print */
        return safe_strdup("{\"status\":\"error\",\"code\":500,"
                           "\"message\":\"out_of_memory\"}");
    }
    return json_str;
}


/* -------------------------------------------------------------------------
 * Diagnostics helpers (optional, compile-time guarded)
 * -------------------------------------------------------------------------*/
#ifdef BURSAR_JSON_PRESENTERS_SELFTEST
#include <assert.h>

static void selftest_invoice_serialisation(void)
{
    bursar_line_item_t li[2] = {
        { .description = "Tuition – CompSci 101",
          .amount      = 1500.00,
          .currency    = "USD" },
        { .description = "Lab Fees – CompSci 101",
          .amount      = 85.50,
          .currency    = "USD" }
    };

    bursar_invoice_response_t resp = {
        .invoice_id       = "b8721b1e-d998-4229-97cb-1c3d9d1aabd9",
        .student_id       = "e3cb1020-ef45-4bf0-bd0e-935e3498bbf9",
        .due_date_iso     = "2024-09-01",
        .amount_due       = 1585.50,
        .currency         = "USD",
        .is_paid          = false,
        .line_item_count  = 2,
        .line_items       = li
    };

    bursar_json_error_t err = BURSAR_JSON_OK;
    char *json = bursar_present_invoice_as_json(&resp, &err);
    assert(err == BURSAR_JSON_OK);
    assert(json != NULL);
    puts(json);
    free(json);
}

int main(void)
{
    selftest_invoice_serialisation();
    return 0;
}
#endif /* BURSAR_JSON_PRESENTERS_SELFTEST */
