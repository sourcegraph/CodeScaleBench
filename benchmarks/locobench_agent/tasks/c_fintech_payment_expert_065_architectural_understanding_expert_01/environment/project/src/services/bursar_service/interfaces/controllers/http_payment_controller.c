/**
 * EduPay Ledger Academy
 * Bursar Service – HTTP Payment Controller
 *
 * File Path:
 *    EduPayLedgerAcademy/src/services/bursar_service/interfaces/controllers/http_payment_controller.c
 *
 * Description:
 *    Maps inbound HTTP requests to the Payment Use-Case and converts
 *    domain responses into HTTP/JSON.  Follows Clean Architecture: the
 *    controller knows nothing about persistence, network, or crypto
 *    details—it merely orchestrates application-level calls.
 *
 * Compile Flags (example):
 *    cc -std=c11 -Wall -Wextra -pedantic                                               \
 *       -I../../../../include -lcjson -lpthread                                         \
 *       ../application/usecases/payment_usecase.c                                      \
 *       http_payment_controller.c -o bursar_service
 */

#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <cjson/cJSON.h>

#include "../../../../include/http/http_server.h"
#include "../../../../include/logging/logger.h"
#include "../../../../include/common/error_codes.h"
#include "../../../../application/usecases/payment_usecase.h"
#include "../../../../application/dto/payment_dto.h"

/* -------------------------------------------------------------------------- */
/* Constants & Macros                                                         */
/* -------------------------------------------------------------------------- */

#define CONTROLLER_TAG "HTTP_PAYMENT_CONTROLLER"
#define ISO_8601_TIME_BUF 32

/* -------------------------------------------------------------------------- */
/* Forward Declarations                                                       */
/* -------------------------------------------------------------------------- */

static void create_payment_handler(const HttpRequest *req,
                                   HttpResponse *res,
                                   void *ctx);

static void get_payment_status_handler(const HttpRequest *req,
                                       HttpResponse *res,
                                       void *ctx);

static void map_domain_error_to_http(const DomainError *derr,
                                     HttpResponse *res);

static bool json_get_string(const cJSON *json, const char *key,
                            const char **out_val, char *errbuf,
                            size_t errbuf_sz);

static bool json_get_number(const cJSON *json, const char *key,
                            double *out_val, char *errbuf,
                            size_t errbuf_sz);

static void render_payment_receipt(const PaymentReceiptDTO *rcpt,
                                   HttpResponse *res);

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * Registers all payment-related HTTP routes with the embedded server.
 *
 * @param srv            Initialized HTTP server instance
 * @param payment_ucase  Pointer to application layer use-case
 * @return               0 on success, negative errno on failure
 */
int http_payment_controller_register(HttpServer       *srv,
                                     PaymentUseCase   *payment_ucase)
{
    if (!srv || !payment_ucase) {
        return -EINVAL;
    }

    int rc = 0;

    rc = http_server_register_route(srv,
                                    HTTP_POST,
                                    "/payments",
                                    create_payment_handler,
                                    payment_ucase);
    if (rc != 0) {
        LOG_ERROR(CONTROLLER_TAG,
                  "Failed to register POST /payments route (err=%d)", rc);
        return rc;
    }

    rc = http_server_register_route(srv,
                                    HTTP_GET,
                                    "/payments/:id",
                                    get_payment_status_handler,
                                    payment_ucase);
    if (rc != 0) {
        LOG_ERROR(CONTROLLER_TAG,
                  "Failed to register GET /payments/:id route (err=%d)", rc);
        return rc;
    }

    LOG_INFO(CONTROLLER_TAG, "Payment HTTP controller registered.");
    return 0;
}

/* -------------------------------------------------------------------------- */
/* Route ­Handlers                                                            */
/* -------------------------------------------------------------------------- */

/**
 * POST /payments
 *  Body (JSON):
 *    {
 *      "student_id"    : "UUID",
 *      "amount"        : 1234.56,
 *      "currency"      : "USD",
 *      "source_account": "ACH|CARD|WALLET",
 *      "description"   : "Spring 2025 tuition"
 *    }
 */
static void create_payment_handler(const HttpRequest *req,
                                   HttpResponse *res,
                                   void *ctx)
{
    PaymentUseCase *ucase = ctx;
    assert(ucase);

    DomainError derr = {.code = DOMAIN_ERR_NONE};

    /* Parse request body --------------------------------------------------- */
    cJSON *body = cJSON_ParseWithLength(req->body, req->body_len);
    if (!body) {
        res->status = HTTP_STATUS_BAD_REQUEST;
        res->body   = strdup("{\"error\":\"invalid_json\"}");
        res->body_len = strlen(res->body);
        return;
    }

    char errbuf[128] = {0};

    const char *student_id = NULL;
    const char *currency   = NULL;
    const char *src_acc    = NULL;
    const char *description= NULL;
    double amount          = 0.0;

    bool ok =
        json_get_string(body, "student_id",    &student_id, errbuf, sizeof errbuf) &&
        json_get_number(body, "amount",        &amount,     errbuf, sizeof errbuf) &&
        json_get_string(body, "currency",      &currency,   errbuf, sizeof errbuf) &&
        json_get_string(body, "source_account",&src_acc,    errbuf, sizeof errbuf);

    /* description is optional */
    if (ok) {
        json_get_string(body, "description", &description, errbuf, sizeof errbuf);
    }

    if (!ok) {
        res->status   = HTTP_STATUS_BAD_REQUEST;
        cJSON *errj   = cJSON_CreateObject();
        cJSON_AddStringToObject(errj, "error", "validation_error");
        cJSON_AddStringToObject(errj, "detail", errbuf);
        res->body     = cJSON_PrintUnformatted(errj);
        res->body_len = strlen(res->body);
        cJSON_Delete(errj);
        cJSON_Delete(body);
        return;
    }

    PaymentRequestDTO dto = {
        .student_id     = student_id,
        .amount         = amount,
        .currency       = currency,
        .source_account = src_acc,
        .description    = description
    };

    /* Invoke application layer -------------------------------------------- */
    PaymentReceiptDTO rcpt = {0};

    if (!payment_usecase_create_payment(ucase, &dto, &rcpt, &derr)) {
        map_domain_error_to_http(&derr, res);
        cJSON_Delete(body);
        return;
    }

    /* Render success ------------------------------------------------------- */
    render_payment_receipt(&rcpt, res);
    cJSON_Delete(body);
}

/**
 * GET /payments/:id
 */
static void get_payment_status_handler(const HttpRequest *req,
                                       HttpResponse *res,
                                       void *ctx)
{
    PaymentUseCase *ucase = ctx;
    assert(ucase);

    DomainError derr = {.code = DOMAIN_ERR_NONE};

    const char *payment_id = http_request_path_param(req, "id");
    if (!payment_id) {
        res->status = HTTP_STATUS_BAD_REQUEST;
        res->body   = strdup("{\"error\":\"missing_payment_id\"}");
        res->body_len = strlen(res->body);
        return;
    }

    PaymentStatusDTO status = {0};

    if (!payment_usecase_get_status(ucase, payment_id, &status, &derr)) {
        map_domain_error_to_http(&derr, res);
        return;
    }

    cJSON *json = cJSON_CreateObject();
    cJSON_AddStringToObject(json, "payment_id", status.payment_id);
    cJSON_AddStringToObject(json, "state",      payment_state_to_string(status.state));
    cJSON_AddNumberToObject(json, "amount",     status.amount);
    cJSON_AddStringToObject(json, "currency",   status.currency);

    char iso_buf[ISO_8601_TIME_BUF];
    if (strftime(iso_buf, sizeof iso_buf, "%Y-%m-%dT%H:%M:%SZ",
                 gmtime(&status.updated_at))) {
        cJSON_AddStringToObject(json, "updated_at", iso_buf);
    }

    res->status   = HTTP_STATUS_OK;
    res->body     = cJSON_PrintUnformatted(json);
    res->body_len = strlen(res->body);

    cJSON_Delete(json);
}

/* -------------------------------------------------------------------------- */
/* Helper ­Functions                                                          */
/* -------------------------------------------------------------------------- */

/**
 * Converts a domain-level error into an HTTP response.
 */
static void map_domain_error_to_http(const DomainError *derr,
                                     HttpResponse *res)
{
    assert(derr && res);

    int http_status     = HTTP_STATUS_INTERNAL_SERVER_ERROR;
    const char *err_key = "unknown_error";

    switch (derr->code) {
        case DOMAIN_ERR_NONE:
            http_status = HTTP_STATUS_OK;
            err_key     = "none";
            break;
        case DOMAIN_ERR_NOT_FOUND:
            http_status = HTTP_STATUS_NOT_FOUND;
            err_key     = "not_found";
            break;
        case DOMAIN_ERR_VALIDATION:
            http_status = HTTP_STATUS_BAD_REQUEST;
            err_key     = "validation_error";
            break;
        case DOMAIN_ERR_CONFLICT:
            http_status = HTTP_STATUS_CONFLICT;
            err_key     = "conflict";
            break;
        case DOMAIN_ERR_RATE_LIMIT:
            http_status = HTTP_STATUS_TOO_MANY_REQUESTS;
            err_key     = "rate_limited";
            break;
        default:
            http_status = HTTP_STATUS_INTERNAL_SERVER_ERROR;
            err_key     = "internal_error";
            break;
    }

    cJSON *jerr = cJSON_CreateObject();
    cJSON_AddStringToObject(jerr, "error",  err_key);
    if (derr->message[0]) {
        cJSON_AddStringToObject(jerr, "detail", derr->message);
    }

    res->status   = http_status;
    res->body     = cJSON_PrintUnformatted(jerr);
    res->body_len = strlen(res->body);
    cJSON_Delete(jerr);
}

/**
 * Reads a required string field from JSON.
 */
static bool json_get_string(const cJSON *json, const char *key,
                            const char **out_val, char *errbuf,
                            size_t errbuf_sz)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(json, key);
    if (!cJSON_IsString(item) || (item->valuestring == NULL)) {
        snprintf(errbuf, errbuf_sz,
                 "Field '%s' must be a non-empty string.", key);
        return false;
    }
    *out_val = item->valuestring;
    return true;
}

/**
 * Reads a required numeric field from JSON.
 */
static bool json_get_number(const cJSON *json, const char *key,
                            double *out_val, char *errbuf,
                            size_t errbuf_sz)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(json, key);
    if (!cJSON_IsNumber(item)) {
        snprintf(errbuf, errbuf_sz,
                 "Field '%s' must be numeric.", key);
        return false;
    }
    *out_val = item->valuedouble;
    return true;
}

/**
 * Serializes a PaymentReceiptDTO into the HTTP response.
 */
static void render_payment_receipt(const PaymentReceiptDTO *rcpt,
                                   HttpResponse *res)
{
    cJSON *json = cJSON_CreateObject();

    cJSON_AddStringToObject(json, "payment_id", rcpt->payment_id);
    cJSON_AddStringToObject(json, "student_id", rcpt->student_id);
    cJSON_AddNumberToObject(json, "amount",     rcpt->amount);
    cJSON_AddStringToObject(json, "currency",   rcpt->currency);
    cJSON_AddStringToObject(json, "state",
                            payment_state_to_string(rcpt->state));

    char iso_buf[ISO_8601_TIME_BUF];
    if (strftime(iso_buf, sizeof iso_buf, "%Y-%m-%dT%H:%M:%SZ",
                 gmtime(&rcpt->created_at))) {
        cJSON_AddStringToObject(json, "created_at", iso_buf);
    }

    res->status   = HTTP_STATUS_CREATED;
    res->body     = cJSON_PrintUnformatted(json);
    res->body_len = strlen(res->body);

    cJSON_Delete(json);
}

/* -------------------------------------------------------------------------- */
/* End of File                                                                */
/* -------------------------------------------------------------------------- */
