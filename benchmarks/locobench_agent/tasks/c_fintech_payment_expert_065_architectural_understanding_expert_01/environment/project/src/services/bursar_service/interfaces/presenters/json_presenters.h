#ifndef EDUPAY_LEDGER_ACADEMY_BURSAR_SERVICE_INTERFACES_PRESENTERS_JSON_PRESENTERS_H
#define EDUPAY_LEDGER_ACADEMY_BURSAR_SERVICE_INTERFACES_PRESENTERS_JSON_PRESENTERS_H
/**
 * json_presenters.h
 *
 * Bursar-service–specific presenters that turn Response-DTOs produced by the
 * application layer into canonical JSON messages expected by API gateways or
 * asynchronous message brokers.
 *
 * Layer: Interfaces / Presenters — Robert C. Martin’s Clean Architecture
 * Project: EduPay Ledger Academy
 *
 * Functions in this header are declared `static inline`; they can therefore be
 * included by multiple translation units without introducing ODR violations
 * while still allowing the optimiser to inline where profitable.
 *
 * The code intentionally depends only on the public DTO contracts of the
 * application layer and the tiny, header-only cJSON library.  No other
 * framework or transport concerns leak into this layer.
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Third-party, permissively licensed, single-header JSON library.           */
/* https://github.com/DaveGamble/cJSON                                       */
#include <cjson/cJSON.h>

/* ───────────────────────────────  DTO imports  ─────────────────────────── */
/* The DTOs live in the application layer and are consumed read-only here.   */
#include "dto/tuition_invoice_dto.h"
#include "dto/payment_receipt_dto.h"
#include "dto/settlement_report_dto.h"
#include "dto/generic_error_dto.h"

/* ───────────────────────────────  Error codes  ─────────────────────────── */
typedef enum json_presenter_err
{
    JSON_PRESENTER_OK = 0,
    JSON_PRESENTER_ERR_NULL_ARG,
    JSON_PRESENTER_ERR_MEMORY,
    JSON_PRESENTER_ERR_SERIALIZATION,
    JSON_PRESENTER_ERR_UNKNOWN
} json_presenter_err_t;

/* ──────────────────────────  Public API contract  ──────────────────────── */
/**
 * Each presenter follows the same contract:
 *   • `pretty` enables human-readable output.
 *   • On success, the function returns JSON_PRESENTER_OK and assigns a freshly
 *     heap-allocated, NUL-terminated string to `*out_json`.
 *   • On failure, `*out_json` is set to NULL and an error code is returned.
 *   • The caller is responsible for releasing the buffer via
 *     `json_presenter_free`.
 */
json_presenter_err_t
json_presenter_invoice( const TuitionInvoiceDTO *invoice,
                        bool                     pretty,
                        char                   **out_json);

json_presenter_err_t
json_presenter_payment_receipt( const PaymentReceiptDTO *receipt,
                                bool                     pretty,
                                char                   **out_json);

json_presenter_err_t
json_presenter_settlement_report( const SettlementReportDTO *report,
                                  bool                       pretty,
                                  char                     **out_json);

json_presenter_err_t
json_presenter_error( const GenericErrorDTO *error,
                      bool                   pretty,
                      char                 **out_json);

/* Single point of release for buffers returned by any json_presenter_* call. */
static inline void json_presenter_free(char *json_str)
{
    free(json_str);
}

/* ───────────────────────────  Implementation  ─────────────────────────── */
/* Internal helper that serialises a cJSON document and returns a buffer.    */
static inline json_presenter_err_t
json_presenter__stringify(cJSON *doc, bool pretty, char **out_json)
{
    if (!doc || !out_json) { return JSON_PRESENTER_ERR_NULL_ARG; }

    char *rendered = pretty ? cJSON_PrintBuffered(doc, 1024, 1)
                            : cJSON_PrintUnformatted(doc);

    if (!rendered) {
        cJSON_Delete(doc);
        return JSON_PRESENTER_ERR_MEMORY;
    }

    *out_json = rendered;     /* Ownership handed to caller.               */
    cJSON_Delete(doc);
    return JSON_PRESENTER_OK;
}

/* ─────────────────────  Tuition Invoice → JSON presenter  ─────────────── */
static inline json_presenter_err_t
json_presenter_invoice(const TuitionInvoiceDTO *invoice,
                       bool                     pretty,
                       char                   **out_json)
{
    if (!invoice || !out_json) { return JSON_PRESENTER_ERR_NULL_ARG; }

    cJSON *root = cJSON_CreateObject();
    if (!root) { return JSON_PRESENTER_ERR_MEMORY; }

    cJSON_AddStringToObject(root, "invoice_id", invoice->invoice_id);
    cJSON_AddStringToObject(root, "student_id", invoice->student_id);
    cJSON_AddStringToObject(root, "term",       invoice->term);
    cJSON_AddStringToObject(root, "currency",   invoice->currency);
    cJSON_AddNumberToObject(root, "amount_due_minor",
                            (double)invoice->amount_due_minor);
    cJSON_AddStringToObject(root, "due_date_iso8601",
                            invoice->due_date_iso8601);
    cJSON_AddBoolToObject(root, "is_overdue", invoice->is_overdue);

    /* Serialise line items. */
    cJSON *items = cJSON_AddArrayToObject(root, "line_items");
    if (!items) { cJSON_Delete(root); return JSON_PRESENTER_ERR_MEMORY; }

    for (size_t i = 0; i < invoice->line_items_count; ++i) {
        const TuitionInvoiceLineItemDTO *li = &invoice->line_items[i];

        cJSON *item = cJSON_CreateObject();
        if (!item) { cJSON_Delete(root); return JSON_PRESENTER_ERR_MEMORY; }

        cJSON_AddStringToObject(item, "description", li->description);
        cJSON_AddNumberToObject(item, "amount_minor", (double)li->amount_minor);
        cJSON_AddItemToArray(items, item);
    }

    return json_presenter__stringify(root, pretty, out_json);
}

/* ────────────────────  Payment Receipt → JSON presenter  ──────────────── */
static inline json_presenter_err_t
json_presenter_payment_receipt(const PaymentReceiptDTO *receipt,
                               bool                     pretty,
                               char                   **out_json)
{
    if (!receipt || !out_json) { return JSON_PRESENTER_ERR_NULL_ARG; }

    cJSON *root = cJSON_CreateObject();
    if (!root) { return JSON_PRESENTER_ERR_MEMORY; }

    cJSON_AddStringToObject(root, "receipt_id",  receipt->receipt_id);
    cJSON_AddStringToObject(root, "invoice_id",  receipt->invoice_id);
    cJSON_AddStringToObject(root, "payment_method", receipt->payment_method);
    cJSON_AddStringToObject(root, "currency",    receipt->currency);
    cJSON_AddNumberToObject(root, "amount_paid_minor",
                            (double)receipt->amount_paid_minor);
    cJSON_AddStringToObject(root, "status",      receipt->status);
    cJSON_AddStringToObject(root, "processed_at_iso8601",
                            receipt->processed_at_iso8601);
    cJSON_AddBoolToObject(root, "refundable", receipt->refundable);

    return json_presenter__stringify(root, pretty, out_json);
}

/* ────────────────────  Settlement Report → JSON presenter  ────────────── */
static inline json_presenter_err_t
json_presenter_settlement_report(const SettlementReportDTO *report,
                                 bool                       pretty,
                                 char                     **out_json)
{
    if (!report || !out_json) { return JSON_PRESENTER_ERR_NULL_ARG; }

    cJSON *root = cJSON_CreateObject();
    if (!root) { return JSON_PRESENTER_ERR_MEMORY; }

    cJSON_AddStringToObject(root, "batch_id",  report->batch_id);
    cJSON_AddStringToObject(root, "currency",  report->currency);
    cJSON_AddStringToObject(root, "settled_at_iso8601",
                            report->settled_at_iso8601);
    cJSON_AddNumberToObject(root, "net_settlement_minor",
                            (double)report->net_settlement_minor);

    /* Serialise individual settlement entries. */
    cJSON *entries = cJSON_AddArrayToObject(root, "entries");
    if (!entries) { cJSON_Delete(root); return JSON_PRESENTER_ERR_MEMORY; }

    for (size_t i = 0; i < report->entry_count; ++i) {
        const SettlementEntryDTO *se = &report->entries[i];

        cJSON *entry = cJSON_CreateObject();
        if (!entry) { cJSON_Delete(root); return JSON_PRESENTER_ERR_MEMORY; }

        cJSON_AddStringToObject(entry, "invoice_id", se->invoice_id);
        cJSON_AddStringToObject(entry, "account_id", se->account_id);
        cJSON_AddNumberToObject(entry, "amount_minor",
                                (double)se->amount_minor);
        cJSON_AddItemToArray(entries, entry);
    }

    return json_presenter__stringify(root, pretty, out_json);
}

/* ────────────────────────  Error DTO → JSON presenter  ─────────────────── */
static inline json_presenter_err_t
json_presenter_error(const GenericErrorDTO *error,
                     bool                   pretty,
                     char                 **out_json)
{
    if (!error || !out_json) { return JSON_PRESENTER_ERR_NULL_ARG; }

    cJSON *root = cJSON_CreateObject();
    if (!root) { return JSON_PRESENTER_ERR_MEMORY; }

    cJSON_AddNumberToObject(root, "code",     error->code);
    cJSON_AddStringToObject(root, "message",  error->message);
    cJSON_AddStringToObject(root, "context",  error->context);

    return json_presenter__stringify(root, pretty, out_json);
}

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* EDUPAY_LEDGER_ACADEMY_BURSAR_SERVICE_INTERFACES_PRESENTERS_JSON_PRESENTERS_H */