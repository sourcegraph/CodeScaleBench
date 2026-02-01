```c
/*─────────────────────────────────────────────────────────────────────────────┐
 ─ HoloCanvas – Gallery-Gateway
 ─ api_handler.h
 │
 │ Public interface for the Gallery-Gateway’s HTTP/gRPC façade.  The API
 │ provides a thin, library-agnostic abstraction layer making it possible to
 │ swap out the underlying web-server (libevent, civetweb, envoy side-car,
 │ etc.) without disturbing business logic or unit tests.
 │
 │ Every route is declared once—using gg_api_register_route()—and is mapped to
 │ a user-supplied callback.  The callback receives immutable request details
 │ and produces a mutable response that the framework will serialise and ship
 │ back to the client.  The interface is intentionally synchronous at this
 │ level; asynchronous I/O happens further down in the transport layer.
 │
 │ Copyright (c) 2023-2024  HoloCanvas Contributors
 │ SPDX-License-Identifier: Apache-2.0
 └────────────────────────────────────────────────────────────────────────────*/

#ifndef HOLOCANVAS_GALLERY_GATEWAY_API_HANDLER_H
#define HOLOCANVAS_GALLERY_GATEWAY_API_HANDLER_H

#ifdef __cplusplus
extern "C" {
#endif

/*───────────────────────────── Standard headers ─────────────────────────────*/
#include <stddef.h>     /* size_t  */
#include <stdint.h>     /* uint*_t */
#include <stdbool.h>    /* bool    */

/*─────────────────────────── Export / visibility ────────────────────────────*/
#if defined(_WIN32) && !defined(__MINGW32__)
#  ifdef GALLERY_GATEWAY_EXPORTS
#    define GG_API __declspec(dllexport)
#  else
#    define GG_API __declspec(dllimport)
#  endif
#else
#  define GG_API __attribute__((visibility("default")))
#endif

/*─────────────────────────────── HTTP helpers ───────────────────────────────*/
typedef enum gg_http_method {
    GG_HTTP_GET,
    GG_HTTP_POST,
    GG_HTTP_PUT,
    GG_HTTP_PATCH,
    GG_HTTP_DELETE,
    GG_HTTP_OPTIONS,
    GG_HTTP_HEAD,
    GG_HTTP_UNSUPPORTED       /* Fallback / sentinel                       */
} gg_http_method_t;

/*───────────────────────────── Error-handling ───────────────────────────────*/
/* Error codes are intentionally sparse—fine-grained errors should be
 * expressed at application level via HTTP status codes or gRPC status
 * details. */
typedef enum gg_api_error {
    GG_SUCCESS                     = 0,
    GG_ERR_NOMEM                   = 1,
    GG_ERR_INVALID_ARGUMENT        = 2,
    GG_ERR_NOT_INITIALISED         = 3,
    GG_ERR_ALREADY_RUNNING         = 4,
    GG_ERR_NOT_FOUND               = 5,
    GG_ERR_IO                      = 6,
    GG_ERR_BACKEND_FAILURE         = 7,
    GG_ERR_UNSUPPORTED             = 8,
    GG_ERR_INTERNAL                = 9,
} gg_api_error_t;

/* Convert an error code to human-readable ASCII (thread-safe, never NULL). */
GG_API const char *gg_api_error_string(gg_api_error_t err);

/*──────────────────────────── Request / Response ────────────────────────────*/
typedef struct gg_api_kv_pair {
    const char *key;               /* Null-terminated UTF-8 view             */
    const char *value;             /* Null-terminated UTF-8 view             */
} gg_api_kv_pair_t;

/* All string members are borrowed views—lifetime ends when the request
 * handler returns.  Do not free() or modify them. */
typedef struct gg_api_request {
    gg_http_method_t     method;
    const char          *path;           /*  e.g. "/v1/nfts/42/bids"          */
    const char          *query;          /*  Query string without '?' char    */
    const uint8_t       *body;           /*  MAY be NULL                      */
    size_t               body_len;
    const gg_api_kv_pair_t *headers;     /*  Array of inbound headers         */
    size_t               header_count;
    const gg_api_kv_pair_t *params;      /*  Route parameters, if any         */
    size_t               param_count;
    void                *raw_ctx;        /*  Transport-specific user data     */
} gg_api_request_t;

/* Response buffer is owned by the caller.  If owns_body is true, the framework
 * will free() body after the data is transmitted.  Set owns_body = false when
 * body points to static / read-only memory. */
typedef struct gg_api_response {
    uint16_t             status;         /*  HTTP status code (200, 404, …)   */
    gg_api_kv_pair_t    *headers;        /*  Optional, may be NULL            */
    size_t               header_count;
    uint8_t             *body;           /*  Optional, may be NULL            */
    size_t               body_len;
    bool                 owns_body;
} gg_api_response_t;

/*──────────────────────────── Callback typedef ──────────────────────────────*/
typedef gg_api_error_t
(*gg_api_handler_cb)(const gg_api_request_t  *req,
                     gg_api_response_t       *res,
                     void                    *user_ctx);

/*──────────────────────────────── API surface ───────────────────────────────*/
/* Initialise internal tables & start listener threads.
 *   bind_addr      – IP/IFACE to bind to (NULL → "0.0.0.0")
 *   port           – TCP port to listen on
 *   worker_threads – 0 → auto-detect (≙ #CPU cores)
 *
 * Thread-safety: may be called from main() once; not re-entrant. */
GG_API gg_api_error_t
gg_api_start(const char *bind_addr,
             uint16_t    port,
             size_t      worker_threads);

/* Stop listener threads and flush in-flight requests.
 * Safe to call from a signal handler context (uses async-safe primitives). */
GG_API gg_api_error_t
gg_api_stop(void);

/* Register a new route.  The path supports simple parameter placeholders,
 * e.g., "/v1/nfts/{nft_id}/bids/{bid_id}".  No memory copy is performed on
 * `path`; caller must ensure the string remains valid until shutdown. */
GG_API gg_api_error_t
gg_api_register_route(gg_http_method_t   method,
                      const char        *path,
                      gg_api_handler_cb  cb,
                      void              *user_ctx);

/* Convenience helper for building JSON responses in one shot.
 * (Implemented in api_handler_json.c; uses cJSON behind the scenes.) */
GG_API gg_api_error_t
gg_api_reply_json(gg_api_response_t *res,
                  uint16_t           status_code,
                  const char        *json_utf8,
                  bool               take_ownership);

/*──────────────────────────── Support utilities ─────────────────────────────*/
/* Escape text for safe insertion into HTML/JSON contexts.  Returns NULL on
 * OOM.  Caller must free(). */
GG_API char *
gg_api_html_escape(const char *raw_utf8);

/* Percent-decode a query string fragment.  Decoding stops on '#', '\0' or
 * first invalid escape sequence (in which case NULL is returned). */
GG_API char *
gg_api_url_decode(const char *enc);

/*────────────────────────────────────────────────────────────────────────────*/
#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* HOLOCANVAS_GALLERY_GATEWAY_API_HANDLER_H */
```