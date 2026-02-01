/**
 * EduPay Ledger Academy — Bursar Service
 * File: interfaces/controllers/http_payment_controller.h
 *
 * Description:
 *   HTTP adapter that exposes Payment API endpoints for the Bursar micro-service.
 *   This controller lives in the Interface layer of the Clean Architecture and
 *   acts as an anti-corruption layer between the external HTTP world and the
 *   internal “Create / Refund / Get” payment use-cases.
 *
 *   The controller is intentionally kept free of framework-specific details so
 *   that instructors can swap the underlying HTTP server (libmicrohttpd,
 *   civetweb, FastCGI, etc.) without touching business rules. Only plain-old C
 *   interfaces are exposed.
 *
 *   Thread-safety: All public functions are re-entrant. Mutable state is kept
 *   inside the controller instance and protected by an internal mutex.
 *
 * Copyright:
 *   © 2024 EduPay Ledger Academy — All rights reserved.
 */

#ifndef EDUPAY_BURSAR_HTTP_PAYMENT_CONTROLLER_H
#define EDUPAY_BURSAR_HTTP_PAYMENT_CONTROLLER_H

#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────────
 *  Standard Library
 * ────────────────────────────────────────────────────────────────────────── */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>

/* ────────────────────────────────────────────────────────────────────────────
 *  Forward Declarations (Domain & Cross-Cutting Interfaces)
 * ────────────────────────────────────────────────────────────────────────── */
struct payment_usecase;      /* Defined in application layer             */
struct logger;               /* Cross-cutting logging interface          */
struct metrics_registry;     /* Custom Prometheus-style metrics registry */
struct audit_trail;          /* Immutable audit trail sink               */

/* ────────────────────────────────────────────────────────────────────────────
 *  HTTP Abstractions
 *  (Minimal façade so we do not leak 3rd-party web frameworks)
 * ────────────────────────────────────────────────────────────────────────── */

/* Enum representing common HTTP status codes used by this service. */
typedef enum http_status_code
{
    HTTP_STATUS_OK                 = 200,
    HTTP_STATUS_CREATED            = 201,
    HTTP_STATUS_BAD_REQUEST        = 400,
    HTTP_STATUS_UNAUTHORIZED       = 401,
    HTTP_STATUS_PAYMENT_REQUIRED   = 402,
    HTTP_STATUS_FORBIDDEN          = 403,
    HTTP_STATUS_NOT_FOUND          = 404,
    HTTP_STATUS_CONFLICT           = 409,
    HTTP_STATUS_UNPROCESSABLE      = 422,
    HTTP_STATUS_INTERNAL_ERROR     = 500,
    HTTP_STATUS_SERVICE_UNAVAIL    = 503
} http_status_code_e;

/* Immutable HTTP request. Body is treated as opaque UTF-8 or binary blob. */
typedef struct http_request
{
    const char  *method;        /* "GET", "POST", …                         */
    const char  *path;          /* Full URI path (already stripped of host) */
    const char  *query;         /* Raw querystring (NULL-terminated)        */
    const void  *body;          /* Pointer to request body buffer           */
    size_t       body_len;      /* Length of request body                   */
    const char **header_keys;   /* NULL-terminated array of header names    */
    const char **header_vals;   /* NULL-terminated array of header values   */
    const char  *remote_addr;   /* IP address of caller                     */
    uint16_t     remote_port;   /* TCP port of caller                       */
} http_request_t;

/* Mutable HTTP response written by controller */
typedef struct http_response
{
    http_status_code_e status;
    char              *content_type;  /* "application/json", …                */
    void              *body;          /* Owned buffer to be freed by caller   */
    size_t             body_len;
    /* Additional headers could be appended here in the future.               */
} http_response_t;

/* Error codes returned by controller operations (superset of http statuses) */
typedef enum bursar_controller_rc
{
    BURSAR_CTRL_OK                = 0,
    BURSAR_CTRL_ERR_VALIDATION    = -1,
    BURSAR_CTRL_ERR_AUTH          = -2,
    BURSAR_CTRL_ERR_NOT_FOUND     = -3,
    BURSAR_CTRL_ERR_CONFLICT      = -4,
    BURSAR_CTRL_ERR_INTERNAL      = -5,
    BURSAR_CTRL_ERR_NO_MEMORY     = -6
} bursar_controller_rc_e;

/* ────────────────────────────────────────────────────────────────────────────
 *  HTTP Payment Controller — Opaque Type
 * ────────────────────────────────────────────────────────────────────────── */

typedef struct http_payment_controller http_payment_controller_t;

/* ────────────────────────────────────────────────────────────────────────────
 *  Construction & Destruction
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * Constructs a new HTTP Payment Controller.
 *
 * @param usecase           Pointer to Payment Use-Case interactor (mandatory)
 * @param logger            Optional cross-cutting logger (can be NULL)
 * @param metrics           Optional metrics registry  (can be NULL)
 * @param audit_trail       Optional audit trail sink (can be NULL)
 *
 * @return Pointer to controller instance on success, NULL on memory failure.
 */
http_payment_controller_t *
http_payment_controller_create(struct payment_usecase  *usecase,
                               struct logger          *logger,
                               struct metrics_registry *metrics,
                               struct audit_trail     *audit_trail);

/**
 * Destroys a controller instance and releases all owned resources.
 * Safe to pass NULL.
 */
void http_payment_controller_destroy(http_payment_controller_t *controller);

/* ────────────────────────────────────────────────────────────────────────────
 *  Public API — Endpoint Handlers
 *  (Each function is side-effect-free with regard to global state)
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * POST /v1/payments
 *
 * Expected JSON body:
 * {
 *   "student_id"     : "S12345678",
 *   "amount_minor"   : 125000,             // amount in minor units (e.g., cents)
 *   "currency"       : "USD",
 *   "line_items"     : [{…}]
 * }
 *
 * Returns:
 *   201 Created on success with JSON payload of Payment aggregate.
 */
bursar_controller_rc_e
http_payment_controller_post_payment(http_payment_controller_t *controller,
                                     const http_request_t      *req,
                                     http_response_t           *rsp);

/**
 * GET /v1/payments/{payment_id}
 */
bursar_controller_rc_e
http_payment_controller_get_payment(http_payment_controller_t *controller,
                                    const http_request_t      *req,
                                    http_response_t           *rsp);

/**
 * POST /v1/payments/{payment_id}/refund
 *
 * Expected JSON body:
 * {
 *   "reason_code"    : "DUPLICATE",
 *   "amount_minor"   : 125000
 * }
 */
bursar_controller_rc_e
http_payment_controller_post_refund(http_payment_controller_t *controller,
                                    const http_request_t      *req,
                                    http_response_t           *rsp);

/* ────────────────────────────────────────────────────────────────────────────
 *  Utility Helpers (for embedder)
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * Parses a JWT from the Authorization header, validates signature/exp claim,
 * and extracts the subject (student) identifier. On failure `out_subject`
 * remains untouched.
 *
 * This helper is exposed so that an HTTP framework adapter may re-use token
 * parsing logic in middlewares.
 *
 * @param auth_header  Full value of the Authorization header.
 * @param out_subject  Buffer receiving NULL-terminated student ID.
 * @param max_len      Size of output buffer.
 *
 * @return true on success, false on validation error.
 */
bool
http_payment_controller_extract_subject_from_jwt(const char *auth_header,
                                                 char       *out_subject,
                                                 size_t      max_len);

/* ────────────────────────────────────────────────────────────────────────────
 *  Micro-Framework Agnostic Route Registration
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * Signature for callback used by external frameworks to register a route.
 *
 * Example integration (pseudo-code):
 *
 *    void register_cb(const char *method,
 *                     const char *path,
 *                     void (*handler)(const http_request_t*, http_response_t*, void*),
 *                     void *user_data);
 *
 * The adapter will wrap the low-level framework request object into our
 * http_request_t abstraction and call the registered handler.
 */
typedef void (*route_register_fn)(
        const char *method,
        const char *path,
        void (*handler)(const http_request_t *, http_response_t *, void *user_data),
        void *user_data);

/**
 * Registers all Payment routes with the provided function pointer. The
 * `user_data` will be re-passed to each handler invocation (typically the
 * controller pointer).
 */
void
http_payment_controller_register_routes(http_payment_controller_t *controller,
                                        route_register_fn          register_fn,
                                        void                      *user_data);

/* ────────────────────────────────────────────────────────────────────────────
 *  Convenience Initialiser for Unit Tests
 * ────────────────────────────────────────────────────────────────────────── */
#ifdef EDUPAY_UNIT_TEST
/**
 * Builds a fully wired test controller with in-memory stubs for every
 * dependency. Intended for white-box unit tests.
 */
http_payment_controller_t *http_payment_controller_create_test_instance(void);
#endif

/* ──────────────────────────────────────────────────────────────────────────── */

#ifdef __cplusplus
}  /* extern "C" */
#endif

#endif /* EDUPAY_BURSAR_HTTP_PAYMENT_CONTROLLER_H */
