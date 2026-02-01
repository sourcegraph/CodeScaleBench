/**
 * File:    dashboard_server.h
 * Author:  LexiLearn MVC Orchestrator – View Layer Team
 * Brief:   Public interface for the DashboardServer – an HTTP/WebSocket server
 *          responsible for streaming model-performance metrics, classroom
 *          analytics, and explainability artifacts to educator dashboards.
 *
 * Copyright © 2023-2024 LexiLearn.
 *
 * NOTE:    The corresponding implementation is in dashboard_server.c.
 *
 * Thread-Safety:
 * ------------
 * DashboardServer is internally synchronized and can be safely accessed from
 * multiple producer threads (e.g., model-monitor observers, retraining jobs)
 * that publish real-time events to connected dashboard clients.
 *
 * Dependencies:
 * -------------
 *  • libwebsockets   (WebSocket I/O)
 *  • cJSON           (JSON serialization)
 *  • pthread         (concurrency primitives)
 *  • openssl         (optional, TLS)
 */

#ifndef LEXILEARN_VIEW_DASHBOARD_SERVER_H
#define LEXILEARN_VIEW_DASHBOARD_SERVER_H

#ifdef __cplusplus
extern "C" {
#endif

/*─────────────────────────── Standard Includes ─────────────────────────────*/
#include <stddef.h>     /* size_t */
#include <stdint.h>     /* uint16_t */
#include <stdbool.h>    /* bool   */

/*──────────────────────────── Project Includes ─────────────────────────────*/
#include "../common/llog.h"  /* Project-wide logging macros */

/*───────────────────────────── Versioning Info ─────────────────────────────*/
#define DASHBOARD_SERVER_VERSION_MAJOR  1
#define DASHBOARD_SERVER_VERSION_MINOR  0
#define DASHBOARD_SERVER_VERSION_PATCH  0

/*────────────────────────────── Error Codes ────────────────────────────────*/
typedef enum
{
    DB_ERR_OK             = 0,   /* Success                                     */
    DB_ERR_INIT           = 1,   /* Initialization failure                      */
    DB_ERR_BIND           = 2,   /* Port binding error                          */
    DB_ERR_TLS            = 3,   /* TLS/SSL initialization error                */
    DB_ERR_WEBSOCKET      = 4,   /* WebSocket related failure                   */
    DB_ERR_INVALID_ARG    = 5,   /* Bad user input                              */
    DB_ERR_ROUTE_EXISTS   = 6,   /* Handler already registered for route/method */
    DB_ERR_NO_MEM         = 7,   /* Out of memory                               */
    DB_ERR_INTERNAL       = 8    /* Unspecified internal error                  */
} db_err_t;

/*───────────────────────────── Forward Decls ───────────────────────────────*/
struct DashboardServer;

/* Opaque server handle. */
typedef struct DashboardServer DashboardServer;

/*───────────────────────────── Public Typedefs ─────────────────────────────*/
/**
 * Callback prototype for custom HTTP route handlers registered by the
 * Controller layer to expose REST endpoints (e.g., /api/retrain).
 *
 * Parameters
 * ----------
 *  uri            – full request URI (null-terminated)
 *  request_body   – raw request body (may be NULL), not guaranteed to be '\0'
 *  request_len    – byte length of request_body
 *  response_body  – [out] Implementation must allocate and set. The caller
 *                   (DashboardServer) will free via free().
 *  response_len   – [out] Length of *response_body in bytes.
 *  user_ctx       – arbitrary pointer supplied on registration.
 *
 * Returns
 * -------
 *  HTTP status code such as 200, 400, 500, etc.
 */
typedef int (*dashboard_route_cb)(
        const char  *uri,
        const char  *request_body,
        size_t       request_len,
        char       **response_body,
        size_t      *response_len,
        void        *user_ctx);

/*──────────────────────────── Server Options ───────────────────────────────*/
/**
 * DashboardServerOptions – immutable configuration passed at creation time.
 */
typedef struct
{
    uint16_t  port;                 /* TCP port to listen on                   */
    bool      enable_tls;           /* true = HTTPS/WSS, false = HTTP/WS       */
    const char *tls_cert_path;      /* PEM-encoded cert chain (required if TLS)*/
    const char *tls_key_path;       /* PEM-encoded private key (required if TLS)*/
    const char *static_asset_dir;   /* Document root for HTML/JS assets        */
    unsigned   max_clients;         /* Hard limit on concurrent clients (0=∞)  */
    bool       enable_cors;         /* If true, adds Access-Control-Allow-*    */
} DashboardServerOptions;

/*────────────────────────────── API Surface ───────────────────────────────*/
/**
 * Create a new DashboardServer instance.
 *
 * The server is not listening after creation; call dashboard_server_start().
 *
 * Returns
 * -------
 *  • Pointer to a new DashboardServer on success.
 *  • NULL on failure (inspect errno or llog error output).
 */
DashboardServer *dashboard_server_create(const DashboardServerOptions *opts);

/**
 * Start the I/O threads and begin accepting client connections.
 *
 * This call is non-blocking; it spawns internal worker threads and returns.
 */
db_err_t dashboard_server_start(DashboardServer *srv);

/**
 * Register a custom HTTP handler.
 *
 * Example:
 *      dashboard_server_register_route(srv, "POST", "/api/retrain",
 *                                      retrain_handler, my_ctx);
 *
 * Limitations:
 *  • Route string must start with '/'.
 *  • Method is case-insensitive and must be one of GET, POST, PUT, DELETE.
 */
db_err_t dashboard_server_register_route(
        DashboardServer    *srv,
        const char         *method,
        const char         *route,
        dashboard_route_cb  cb,
        void               *user_ctx);

/**
 * Publish a JSON message to a named channel. All WebSocket clients that have
 * subscribed to this channel will receive the message asynchronously.
 *
 * Internally, the function copies `json_payload`; the caller retains ownership.
 */
db_err_t dashboard_server_publish(
        DashboardServer    *srv,
        const char         *channel_name,
        const char         *json_payload);

/**
 * Broadcast a binary blob to every connected WebSocket client, regardless of
 * subscription filtering. Intended for large artifacts like model heat-maps.
 */
db_err_t dashboard_server_broadcast(
        DashboardServer    *srv,
        const void         *data,
        size_t              data_len,
        const char         *mime_type /* e.g., "image/png" */);

/**
 * Gracefully shut down the server: closes all client connections, flushes
 * outbound queues, and joins background threads.
 */
void dashboard_server_stop(DashboardServer *srv);

/**
 * Destroy the server instance and reclaim resources. Safe to call on a NULL
 * pointer. The server MUST be stopped before calling this function.
 */
void dashboard_server_destroy(DashboardServer *srv);

/*────────────────────────── Convenience Utilities ──────────────────────────*/
/**
 * Helper that blocks the caller (usually the main thread) until a termination
 * signal (SIGINT/SIGTERM) is received, at which point it triggers a graceful
 * shutdown on the supplied DashboardServer.
 *
 * Returns DB_ERR_OK when the server terminates cleanly.
 */
db_err_t dashboard_server_block_until_signal(DashboardServer *srv);

/**
 * Retrieve the semantic version string (e.g., "1.0.0").
 * The returned pointer is to a static buffer—do NOT free().
 */
const char *dashboard_server_version(void);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LEXILEARN_VIEW_DASHBOARD_SERVER_H */
