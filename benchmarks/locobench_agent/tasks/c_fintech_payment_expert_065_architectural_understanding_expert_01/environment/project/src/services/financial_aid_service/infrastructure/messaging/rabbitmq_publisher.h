#ifndef EDU_PAY_LEDGER_ACADEMY_RABBITMQ_PUBLISHER_H
#define EDU_PAY_LEDGER_ACADEMY_RABBITMQ_PUBLISHER_H
/*
 * EduPay Ledger Academy
 * ---------------------
 * RabbitMQ Publisher – Infrastructure Layer
 *
 * Purpose
 *   Encapsulates low-level AMQP operations required by the Financial Aid
 *   service when emitting domain events or saga-pattern commands.
 *
 * Dependency
 *   librabbitmq-c (https://github.com/alanxz/rabbitmq-c)
 *
 * Clean-Architecture Note
 *   Nothing inside this header leaks Financial-Aid domain concepts.
 *   The service depends on this publisher only through the interface
 *   declared here.  Swapping the transport (e.g., Kafka) requires a new
 *   implementation, not a domain change.
 *
 * Copyright
 *   © 2024 EduPay Ledger Academy – All rights reserved.
 */

#ifdef __cplusplus
extern "C" {
#endif

/* ──────────────────────────────────────────────────────────────────────────
 *  Standard Library
 * ────────────────────────────────────────────────────────────────────────── */
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* ──────────────────────────────────────────────────────────────────────────
 *  RabbitMQ-C
 * ────────────────────────────────────────────────────────────────────────── */
#include <amqp.h>
#include <amqp_framing.h>
#include <amqp_tcp_socket.h>

/* ──────────────────────────────────────────────────────────────────────────
 *  Compile-time Configuration
 * ────────────────────────────────────────────────────────────────────────── */

/* Optional: Allow build pipeline to inject custom default credentials. */
#ifndef EDUPAY_RMQ_DEFAULT_USER
#define EDUPAY_RMQ_DEFAULT_USER     "guest"
#endif

#ifndef EDUPAY_RMQ_DEFAULT_PASSWORD
#define EDUPAY_RMQ_DEFAULT_PASSWORD "guest"
#endif

#ifndef EDUPAY_RMQ_DEFAULT_HOST
#define EDUPAY_RMQ_DEFAULT_HOST     "localhost"
#endif

#ifndef EDUPAY_RMQ_DEFAULT_PORT
#define EDUPAY_RMQ_DEFAULT_PORT     5672
#endif

#ifndef EDUPAY_RMQ_DEFAULT_VHOST
#define EDUPAY_RMQ_DEFAULT_VHOST    "/"
#endif

#ifndef EDUPAY_RMQ_DEFAULT_HEARTBEAT
#define EDUPAY_RMQ_DEFAULT_HEARTBEAT 30 /* seconds */
#endif

/* ──────────────────────────────────────────────────────────────────────────
 *  Error Handling
 * ────────────────────────────────────────────────────────────────────────── */

typedef enum {
    RMQ_OK                         =  0,
    RMQ_ERROR_SOCKET_CREATE        = -1,
    RMQ_ERROR_SOCKET_OPEN          = -2,
    RMQ_ERROR_LOGIN                = -3,
    RMQ_ERROR_CHANNEL_OPEN         = -4,
    RMQ_ERROR_EXCHANGE_DECLARE     = -5,
    RMQ_ERROR_PUBLISH              = -6,
    RMQ_ERROR_ALREADY_OPEN         = -7,
    RMQ_ERROR_NOT_INITIALIZED      = -8,
    RMQ_ERROR_RPC                  = -9
} rmq_status_t;

/* High-level diagnostics record for logging/audit trail */
typedef struct {
    rmq_status_t status;
    char         context[128];
    char         broker_reply[256];
    time_t       timestamp;
} rmq_diagnostic_t;

/* ──────────────────────────────────────────────────────────────────────────
 *  Publisher Object
 * ────────────────────────────────────────────────────────────────────────── */

typedef struct {
    amqp_connection_state_t conn;
    amqp_socket_t          *socket;
    int                     channel_id;
    char                    exchange[128];
    bool                    exchange_declared;
    bool                    is_open;
    rmq_diagnostic_t        last_diag;
} rmq_publisher_t;

/* ──────────────────────────────────────────────────────────────────────────
 *  Public API
 * ────────────────────────────────────────────────────────────────────────── */

/*
 * rmq_publisher_init
 *
 * Establish a TCP and AMQP connection, open channel 1, and (optionally)
 * declare the exchange if it does not yet exist.
 *
 * Parameters
 *   pub             – pointer to uninitialized publisher structure.
 *   host            – broker DNS name or IP.
 *   port            – broker port; use 5671 for TLS off-load terminator.
 *   vhost           – logical virtual host.
 *   user, password  – credentials.
 *   exchange        – exchange name (Fanout/Topic/Direct).
 *   exchange_type   – "fanout", "topic", "direct", or "headers".
 *   declare         – when true, passive declare will create exchange.
 *   heartbeat       – heartbeat interval in seconds (0 = default).
 *
 * Returns
 *   RMQ_OK on success or a negative rmq_status_t on failure.
 */
static inline rmq_status_t
rmq_publisher_init(rmq_publisher_t *pub,
                   const char      *host,
                   int              port,
                   const char      *vhost,
                   const char      *user,
                   const char      *password,
                   const char      *exchange,
                   const char      *exchange_type,
                   bool             declare,
                   int              heartbeat);

/*
 * rmq_publisher_publish_json
 *
 * Sends a UTF-8 JSON payload with content-type "application/json".
 *
 *   delivery_mode:
 *     false – non-persistent (memory queue)
 *     true  – persistent (broker writes to disk)
 */
static inline rmq_status_t
rmq_publisher_publish_json(rmq_publisher_t *pub,
                           const char      *routing_key,
                           const char      *json_payload,
                           bool             persistent);

/*
 * rmq_publisher_publish_bytes
 *
 * Raw payload publishing.  Caller specifies MIME content-type.
 */
static inline rmq_status_t
rmq_publisher_publish_bytes(rmq_publisher_t *pub,
                            const char      *routing_key,
                            const uint8_t   *payload,
                            size_t           len,
                            const char      *content_type,
                            bool             persistent);

/*
 * Gracefully close channel and connection.
 */
static inline void
rmq_publisher_teardown(rmq_publisher_t *pub);

/*
 * Helper: Provide last diagnostic for telemetry dashboards.
 */
static inline const rmq_diagnostic_t*
rmq_publisher_last_diag(const rmq_publisher_t *pub);

/* ──────────────────────────────────────────────────────────────────────────
 *  Implementation (Header-only)
 * ────────────────────────────────────────────────────────────────────────── */

#ifndef EDU_PAY_RABBITMQ_PUBLISHER_HEADER_ONLY_GUARD
#define EDU_PAY_RABBITMQ_PUBLISHER_HEADER_ONLY_GUARD

/* Internal helper – translate rabbitmq-c reply into rmq_status_t */
static inline rmq_status_t
_rmq_parse_reply(amqp_rpc_reply_t reply)
{
    switch (reply.reply_type) {
        case AMQP_RESPONSE_NORMAL:
            return RMQ_OK;

        case AMQP_RESPONSE_LIBRARY_EXCEPTION:
            return (reply.library_error == AMQP_STATUS_CONNECTION_CLOSED)
                   ? RMQ_ERROR_NOT_INITIALIZED
                   : RMQ_ERROR_RPC;

        case AMQP_RESPONSE_SERVER_EXCEPTION:
            /* We treat all server exceptions the same here; caller
             * will introspect diagnostic struct for details. */
            return RMQ_ERROR_RPC;

        default:
            return RMQ_ERROR_RPC;
    }
}

/* Populate diagnostic record */
static inline void
_rmq_set_diag(rmq_publisher_t *pub,
              rmq_status_t     status,
              const char      *ctx,
              amqp_rpc_reply_t reply)
{
    if (!pub) { return; }

    pub->last_diag.status    = status;
    strncpy(pub->last_diag.context, ctx, sizeof(pub->last_diag.context)-1);
    pub->last_diag.context[sizeof(pub->last_diag.context)-1] = '\0';
    pub->last_diag.timestamp = time(NULL);

    if (reply.reply_type == AMQP_RESPONSE_SERVER_EXCEPTION) {
        /* Convert server-exception to human-readable */
        if (reply.reply.id == AMQP_CONNECTION_CLOSE_METHOD) {
            amqp_connection_close_t *m = (amqp_connection_close_t *)reply.reply.decoded;
            snprintf(pub->last_diag.broker_reply,
                     sizeof(pub->last_diag.broker_reply),
                     "CONN_CLOSE: code=%u, text=%.*s",
                     m->reply_code,
                     (int)m->reply_text.len,
                     (char *)m->reply_text.bytes);
        } else if (reply.reply.id == AMQP_CHANNEL_CLOSE_METHOD) {
            amqp_channel_close_t *m = (amqp_channel_close_t *)reply.reply.decoded;
            snprintf(pub->last_diag.broker_reply,
                     sizeof(pub->last_diag.broker_reply),
                     "CHAN_CLOSE: code=%u, text=%.*s",
                     m->reply_code,
                     (int)m->reply_text.len,
                     (char *)m->reply_text.bytes);
        } else {
            snprintf(pub->last_diag.broker_reply,
                     sizeof(pub->last_diag.broker_reply),
                     "SERVER_EXCEPTION id=%u",
                     reply.reply.id);
        }
    } else if (reply.reply_type == AMQP_RESPONSE_LIBRARY_EXCEPTION) {
        snprintf(pub->last_diag.broker_reply,
                 sizeof(pub->last_diag.broker_reply),
                 "LIB_EXCEPTION: %s",
                 amqp_error_string2(reply.library_error));
    } else {
        strncpy(pub->last_diag.broker_reply, "OK", sizeof(pub->last_diag.broker_reply)-1);
    }
}

/* =========================================================================
 *  IMPLEMENTATION OF PUBLIC FUNCTIONS
 * ========================================================================= */

static inline rmq_status_t
rmq_publisher_init(rmq_publisher_t *pub,
                   const char      *host,
                   int              port,
                   const char      *vhost,
                   const char      *user,
                   const char      *password,
                   const char      *exchange,
                   const char      *exchange_type,
                   bool             declare,
                   int              heartbeat)
{
    if (!pub) { return RMQ_ERROR_NOT_INITIALIZED; }

    if (pub->is_open) {
        _rmq_set_diag(pub, RMQ_ERROR_ALREADY_OPEN, "init", (amqp_rpc_reply_t){0});
        return RMQ_ERROR_ALREADY_OPEN;
    }

    memset(pub, 0, sizeof(*pub));
    pub->conn = amqp_new_connection();
    pub->socket = amqp_tcp_socket_new(pub->conn);
    if (!pub->socket) {
        _rmq_set_diag(pub, RMQ_ERROR_SOCKET_CREATE, "tcp_socket_new", (amqp_rpc_reply_t){0});
        return RMQ_ERROR_SOCKET_CREATE;
    }

    if (amqp_socket_open(pub->socket, host ? host : EDUPAY_RMQ_DEFAULT_HOST,
                         port > 0 ? port : EDUPAY_RMQ_DEFAULT_PORT)) {
        _rmq_set_diag(pub, RMQ_ERROR_SOCKET_OPEN, "socket_open", (amqp_rpc_reply_t){0});
        return RMQ_ERROR_SOCKET_OPEN;
    }

    /* Login */
    amqp_rpc_reply_t reply = amqp_login(pub->conn,
                                        vhost ? vhost : EDUPAY_RMQ_DEFAULT_VHOST,
                                        /* channel max */ 0,
                                        /* frame max */    131072,
                                        heartbeat > 0 ? heartbeat : EDUPAY_RMQ_DEFAULT_HEARTBEAT,
                                        AMQP_SASL_METHOD_PLAIN,
                                        user     ? user     : EDUPAY_RMQ_DEFAULT_USER,
                                        password ? password : EDUPAY_RMQ_DEFAULT_PASSWORD);

    rmq_status_t st = _rmq_parse_reply(reply);
    if (st != RMQ_OK) {
        _rmq_set_diag(pub, RMQ_ERROR_LOGIN, "amqp_login", reply);
        return RMQ_ERROR_LOGIN;
    }

    /* Channel */
    pub->channel_id = 1;
    reply = amqp_channel_open(pub->conn, pub->channel_id);
    st = _rmq_parse_reply(reply);
    if (st != RMQ_OK) {
        _rmq_set_diag(pub, RMQ_ERROR_CHANNEL_OPEN, "channel_open", reply);
        return RMQ_ERROR_CHANNEL_OPEN;
    }

    strncpy(pub->exchange, exchange, sizeof(pub->exchange)-1);
    pub->exchange[sizeof(pub->exchange)-1] = '\0';

    if (declare) {
        amqp_exchange_declare(pub->conn, pub->channel_id,
                              amqp_cstring_bytes(exchange),
                              amqp_cstring_bytes(exchange_type ? exchange_type : "topic"),
                              /* passive */ 0,
                              /* durable */ 1,
                              /* auto-delete */ 0,
                              /* internal */ 0,
                              amqp_empty_table);

        reply = amqp_get_rpc_reply(pub->conn);
        st = _rmq_parse_reply(reply);
        if (st != RMQ_OK) {
            _rmq_set_diag(pub, RMQ_ERROR_EXCHANGE_DECLARE, "exchange_declare", reply);
            return RMQ_ERROR_EXCHANGE_DECLARE;
        }
        pub->exchange_declared = true;
    }

    pub->is_open = true;
    _rmq_set_diag(pub, RMQ_OK, "init", reply);
    return RMQ_OK;
}

static inline rmq_status_t
rmq_publisher_publish_json(rmq_publisher_t *pub,
                           const char      *routing_key,
                           const char      *json_payload,
                           bool             persistent)
{
    if (!pub || !pub->is_open) { return RMQ_ERROR_NOT_INITIALIZED; }
    if (!json_payload)        { return RMQ_ERROR_PUBLISH; }

    size_t len = strlen(json_payload);
    return rmq_publisher_publish_bytes(pub,
                                       routing_key,
                                       (const uint8_t*)json_payload,
                                       len,
                                       "application/json",
                                       persistent);
}

static inline rmq_status_t
rmq_publisher_publish_bytes(rmq_publisher_t *pub,
                            const char      *routing_key,
                            const uint8_t   *payload,
                            size_t           len,
                            const char      *content_type,
                            bool             persistent)
{
    if (!pub || !pub->is_open)           { return RMQ_ERROR_NOT_INITIALIZED; }
    if (!payload || len == 0)            { return RMQ_ERROR_PUBLISH; }

    amqp_basic_properties_t props;
    props._flags = AMQP_BASIC_CONTENT_TYPE_FLAG
                 | AMQP_BASIC_DELIVERY_MODE_FLAG
                 | AMQP_BASIC_TIMESTAMP_FLAG;

    props.content_type = amqp_cstring_bytes(content_type ? content_type : "application/octet-stream");
    props.delivery_mode = persistent ? 2 : 1; /* 1 = non-persistent, 2 = persistent */
    props.timestamp = (uint64_t)time(NULL);

    int rc = amqp_basic_publish(pub->conn,
                                pub->channel_id,
                                amqp_cstring_bytes(pub->exchange),
                                amqp_cstring_bytes(routing_key ? routing_key : ""),
                                /* mandatory */ 0,
                                /* immediate */ 0,
                                &props,
                                amqp_bytes_t{ .len = len, .bytes = (void*)payload });

    if (rc != 0) {
        _rmq_set_diag(pub, RMQ_ERROR_PUBLISH, "basic_publish(io)", (amqp_rpc_reply_t){0});
        return RMQ_ERROR_PUBLISH;
    }

    /* For confirmation-mode, we would wait for Basic.Ack here. */
    _rmq_set_diag(pub, RMQ_OK, "publish", (amqp_rpc_reply_t){0});
    return RMQ_OK;
}

static inline void
rmq_publisher_teardown(rmq_publisher_t *pub)
{
    if (!pub || !pub->is_open) { return; }

    /* Close channel */
    amqp_channel_close(pub->conn, pub->channel_id, AMQP_REPLY_SUCCESS);

    /* Close connection */
    amqp_connection_close(pub->conn, AMQP_REPLY_SUCCESS);
    amqp_destroy_connection(pub->conn);

    /* Reset */
    memset(pub, 0, sizeof(*pub));
}

static inline const rmq_diagnostic_t*
rmq_publisher_last_diag(const rmq_publisher_t *pub)
{
    return pub ? &pub->last_diag : NULL;
}

#endif /* EDU_PAY_RABBITMQ_PUBLISHER_HEADER_ONLY_GUARD */

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* EDU_PAY_LEDGER_ACADEMY_RABBITMQ_PUBLISHER_H */
