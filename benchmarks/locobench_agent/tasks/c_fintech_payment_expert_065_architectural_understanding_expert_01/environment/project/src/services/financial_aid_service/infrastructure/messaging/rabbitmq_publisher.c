/*
 * rabbitmq_publisher.c
 *
 * EduPay Ledger Academy – Financial-Aid Service
 * ------------------------------------------------
 * Infrastructure Adapter: RabbitMQ Publisher
 *
 * This module provides a resilient, thread-safe message publisher used by the
 * Financial-Aid bounded-context to broadcast domain events (e.g., “AidGranted”,
 * “DisbursementScheduled”) across the EduPay Ledger Academy event bus.
 *
 * The adapter follows Clean-Architecture guidelines: only pure C and small
 * third-party libraries, no framework-specific code leaks into higher layers.
 *
 * Library dependencies:
 *   – rabbitmq-c          (https://github.com/alanxz/rabbitmq-c)
 *   – libuuid             (RFC-4122, for correlation-ids)
 *
 * Build:
 *   gcc -Wall -Wextra -pedantic -std=c11 \
 *       -lrabbitmq -luuid -pthread \
 *       -I/path/to/rabbitmq-c/include \
 *       rabbitmq_publisher.c -o rabbitmq_publisher
 */

#include <amqp.h>
#include <amqp_framing.h>
#include <amqp_tcp_socket.h>

#include <uuid/uuid.h>

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <time.h>
#include <unistd.h>

/* -------------------------------------------------------------------------- */
/* Internal helper macros                                                     */
/* -------------------------------------------------------------------------- */
#define UNUSED(x) (void)(x)
#define RMQ_CHECK(expr, msg)         \
    do {                             \
        if ((expr) < 0) {            \
            rmq_log(LOG_ERR, msg);   \
            return -1;               \
        }                            \
    } while (0)

#define RMQ_MAX_CORRELATION_ID 36
#define RMQ_DEFAULT_HEARTBEAT  30
#define RMQ_DEFAULT_RECONNECT_DELAY_SEC 5

/* -------------------------------------------------------------------------- */
/* Logging                                                                    */
/* -------------------------------------------------------------------------- */

static void rmq_log(int priority, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsyslog(priority, fmt, ap);
    va_end(ap);
}

/* -------------------------------------------------------------------------- */
/* Publisher configuration                                                    */
/* -------------------------------------------------------------------------- */

typedef struct {
    char  host[256];
    int   port;
    char  vhost[256];
    char  username[128];
    char  password[128];
    char  exchange[256];
    int   heartbeat;
    int   reconnect_delay_seconds;
} rmq_publisher_cfg_t;

/* -------------------------------------------------------------------------- */
/* Publisher runtime state                                                    */
/* -------------------------------------------------------------------------- */

typedef struct {
    rmq_publisher_cfg_t cfg;

    amqp_connection_state_t conn;
    amqp_socket_t          *socket;
    amqp_channel_t          channel;

    pthread_mutex_t         mutex;
    bool                    connected;

    /* Simple metrics */
    uint64_t                published_count;
    uint64_t                reconnect_count;
} rmq_publisher_t;

/* -------------------------------------------------------------------------- */
/* Prototypes                                                                 */
/* -------------------------------------------------------------------------- */

static int  rmq_connect_locked(rmq_publisher_t *pub);
static void rmq_disconnect_locked(rmq_publisher_t *pub);
static int  rmq_declare_exchange_locked(rmq_publisher_t *pub);
static int  rmq_wait_for_confirm(rmq_publisher_t *pub);
static int  rmq_generate_correlation_id(char out[RMQ_MAX_CORRELATION_ID + 1]);

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

/*
 * rmq_publisher_init
 *
 * Initialize the publisher instance with the provided configuration.
 * Memory is owned by the caller; call rmq_publisher_destroy() when done.
 */
rmq_publisher_t *rmq_publisher_init(const rmq_publisher_cfg_t *cfg)
{
    openlog("EduPay.FinAid.RMQPublisher", LOG_PID | LOG_CONS, LOG_USER);

    rmq_publisher_t *pub = calloc(1, sizeof(*pub));
    if (!pub) {
        rmq_log(LOG_ERR, "Failed to allocate publisher: %s", strerror(errno));
        return NULL;
    }

    pub->cfg = *cfg;
    if (pub->cfg.heartbeat <= 0)
        pub->cfg.heartbeat = RMQ_DEFAULT_HEARTBEAT;
    if (pub->cfg.reconnect_delay_seconds <= 0)
        pub->cfg.reconnect_delay_seconds = RMQ_DEFAULT_RECONNECT_DELAY_SEC;

    pthread_mutex_init(&pub->mutex, NULL);
    pub->channel = 1;

    return pub;
}

/*
 * rmq_publisher_destroy
 */
void rmq_publisher_destroy(rmq_publisher_t *pub)
{
    if (!pub)
        return;

    pthread_mutex_lock(&pub->mutex);
    rmq_disconnect_locked(pub);
    pthread_mutex_unlock(&pub->mutex);
    pthread_mutex_destroy(&pub->mutex);
    free(pub);

    closelog();
}

/*
 * rmq_publisher_publish
 *
 * Thread-safe publish. `payload` data is copied internally by the AMQP
 * library; caller retains ownership.
 *
 * Returns 0 on success, -1 on failure.
 */
int rmq_publisher_publish(rmq_publisher_t *pub,
                          const char *routing_key,
                          const void *payload,
                          size_t payload_len,
                          const char *content_type,
                          const char *correlation_id /* optional, can be NULL */)
{
    if (!pub || !routing_key || !payload || payload_len == 0)
        return -1;

    pthread_mutex_lock(&pub->mutex);

    /* Ensure we have a connection */
    if (!pub->connected) {
        if (rmq_connect_locked(pub) != 0) {
            pthread_mutex_unlock(&pub->mutex);
            return -1;
        }
    }

    /* ------------------------------------------------------------------ */
    /* Properties                                                          */
    /* ------------------------------------------------------------------ */
    amqp_basic_properties_t props;
    memset(&props, 0, sizeof(props));
    props._flags =
        AMQP_BASIC_CONTENT_TYPE_FLAG |
        AMQP_BASIC_DELIVERY_MODE_FLAG |
        AMQP_BASIC_CORRELATION_ID_FLAG |
        AMQP_BASIC_TIMESTAMP_FLAG;

    props.content_type = amqp_cstring_bytes(content_type ? content_type : "application/octet-stream");
    props.delivery_mode = 2; /* persistent */
    props.timestamp = (uint64_t)time(NULL);

    char corr_buf[RMQ_MAX_CORRELATION_ID + 1] = {0};
    if (!correlation_id) {
        rmq_generate_correlation_id(corr_buf);
        correlation_id = corr_buf;
    }
    props.correlation_id = amqp_cstring_bytes(correlation_id);

    /* ------------------------------------------------------------------ */
    /* Publish                                                             */
    /* ------------------------------------------------------------------ */
    amqp_bytes_t body;
    body.len  = payload_len;
    body.bytes = (void *)payload; /* library copies into frame */

    int status = amqp_basic_publish(pub->conn,
                                    pub->channel,
                                    amqp_cstring_bytes(pub->cfg.exchange),
                                    amqp_cstring_bytes(routing_key),
                                    0,      /* mandatory */
                                    0,      /* immediate */
                                    &props,
                                    body);

    if (status < 0) {
        rmq_log(LOG_ERR, "amqp_basic_publish failed: %s",
                amqp_error_string2(status));
        rmq_disconnect_locked(pub); /* force reconnect next time */
        pthread_mutex_unlock(&pub->mutex);
        return -1;
    }

    /* Wait for publisher confirm */
    if (rmq_wait_for_confirm(pub) != 0) {
        rmq_log(LOG_ERR, "Publisher confirm failed, message may be lost");
        rmq_disconnect_locked(pub);
        pthread_mutex_unlock(&pub->mutex);
        return -1;
    }

    pub->published_count++;

    pthread_mutex_unlock(&pub->mutex);
    return 0;
}

/* -------------------------------------------------------------------------- */
/* Internal: Connection lifecycle                                             */
/* -------------------------------------------------------------------------- */

static int rmq_connect_locked(rmq_publisher_t *pub)
{
    /* Re-entry guard */
    if (pub->connected)
        return 0;

    /* Attempt to (re)connect with back-off */
    for (;;) {
        pub->conn = amqp_new_connection();
        if (!pub->conn) {
            rmq_log(LOG_ERR, "amqp_new_connection failed");
            return -1;
        }

        pub->socket = amqp_tcp_socket_new(pub->conn);
        if (!pub->socket) {
            rmq_log(LOG_ERR, "amqp_tcp_socket_new failed");
            amqp_destroy_connection(pub->conn);
            return -1;
        }

        int status = amqp_socket_open(pub->socket, pub->cfg.host, pub->cfg.port);
        if (status) {
            rmq_log(LOG_WARNING, "AMQP socket open failed: %s",
                    amqp_error_string2(status));
            goto retry;
        }

        /* Login */
        amqp_rpc_reply_t reply = amqp_login(pub->conn,
                                            pub->cfg.vhost,
                                            pub->cfg.heartbeat,
                                            131072, /* frame max */
                                            0,
                                            AMQP_SASL_METHOD_PLAIN,
                                            pub->cfg.username,
                                            pub->cfg.password);
        if (reply.reply_type != AMQP_RESPONSE_NORMAL) {
            rmq_log(LOG_WARNING, "AMQP login failed");
            amqp_destroy_connection(pub->conn);
            goto retry;
        }

        amqp_channel_open(pub->conn, pub->channel);
        reply = amqp_get_rpc_reply(pub->conn);
        if (reply.reply_type != AMQP_RESPONSE_NORMAL) {
            rmq_log(LOG_WARNING, "AMQP channel open failed");
            amqp_destroy_connection(pub->conn);
            goto retry;
        }

        /* Enable publisher confirms */
        amqp_confirm_select(pub->conn, pub->channel);
        reply = amqp_get_rpc_reply(pub->conn);
        if (reply.reply_type != AMQP_RESPONSE_NORMAL) {
            rmq_log(LOG_WARNING, "AMQP confirm_select failed");
            amqp_destroy_connection(pub->conn);
            goto retry;
        }

        /* Declare exchange to ensure it exists */
        if (rmq_declare_exchange_locked(pub) != 0) {
            amqp_destroy_connection(pub->conn);
            goto retry;
        }

        pub->connected = true;
        rmq_log(LOG_INFO, "Connected to RabbitMQ %s:%d (vhost=%s, exh=%s)",
                pub->cfg.host, pub->cfg.port, pub->cfg.vhost, pub->cfg.exchange);
        return 0;

    retry:
        pub->reconnect_count++;
        rmq_log(LOG_NOTICE, "Retrying connection in %d seconds...",
                pub->cfg.reconnect_delay_seconds);
        sleep(pub->cfg.reconnect_delay_seconds);
    }

    /* unreached */
}

static void rmq_disconnect_locked(rmq_publisher_t *pub)
{
    if (!pub->connected)
        return;

    amqp_channel_close(pub->conn, pub->channel, AMQP_REPLY_SUCCESS);
    amqp_connection_close(pub->conn, AMQP_REPLY_SUCCESS);
    amqp_destroy_connection(pub->conn);

    pub->conn = NULL;
    pub->socket = NULL;
    pub->connected = false;

    rmq_log(LOG_INFO, "Disconnected from RabbitMQ");
}

static int rmq_declare_exchange_locked(rmq_publisher_t *pub)
{
    /* Exchange declare: durable, topic */
    int status = amqp_exchange_declare(pub->conn,
                                       pub->channel,
                                       amqp_cstring_bytes(pub->cfg.exchange),
                                       amqp_cstring_bytes("topic"),
                                       0,    /* passive  */
                                       1,    /* durable  */
                                       0,    /* auto_del */
                                       0,    /* internal */
                                       amqp_empty_table);

    if (status < 0) {
        rmq_log(LOG_ERR, "Exchange declare failed: %s",
                amqp_error_string2(status));
        return -1;
    }
    return 0;
}

/* -------------------------------------------------------------------------- */
/* Internal: Wait for publisher confirms                                      */
/* -------------------------------------------------------------------------- */

static int rmq_wait_for_confirm(rmq_publisher_t *pub)
{
    amqp_rpc_reply_t reply;
    amqp_frame_t frame;

    while (true) {
        amqp_maybe_release_buffers(pub->conn);
        reply = amqp_simple_wait_frame(pub->conn, &frame);
        if (reply.reply_type != AMQP_RESPONSE_NORMAL) {
            rmq_log(LOG_ERR, "amqp_simple_wait_frame failed");
            return -1;
        }

        if (frame.frame_type != AMQP_FRAME_METHOD)
            continue;

        if (frame.payload.method.id == AMQP_BASIC_ACK_METHOD) {
            /* Basic.Ack received */
            return 0;
        }
        else if (frame.payload.method.id == AMQP_BASIC_NACK_METHOD) {
            rmq_log(LOG_WARNING, "Publisher NACK received");
            return -1;
        }
    }
}

/* -------------------------------------------------------------------------- */
/* Internal: Correlation-Id helper                                            */
/* -------------------------------------------------------------------------- */
static int rmq_generate_correlation_id(char out[RMQ_MAX_CORRELATION_ID + 1])
{
    uuid_t uuid;
    uuid_generate(uuid);
    uuid_unparse_lower(uuid, out);
    return 0;
}

/* -------------------------------------------------------------------------- */
/* Example usage (compile with -DDEBUG_DEMO)                                  */
/* -------------------------------------------------------------------------- */
#ifdef DEBUG_DEMO
int main(void)
{
    rmq_publisher_cfg_t cfg = {
        .host   = "localhost",
        .port   = 5672,
        .vhost  = "/",
        .username = "guest",
        .password = "guest",
        .exchange = "eduledger.events",
        .heartbeat = 30,
        .reconnect_delay_seconds = 3
    };

    rmq_publisher_t *pub = rmq_publisher_init(&cfg);
    if (!pub) {
        fprintf(stderr, "Publisher init failed\n");
        return EXIT_FAILURE;
    }

    const char *payload = "{\"event\":\"AidGranted\",\"amount\":1200}";
    if (rmq_publisher_publish(pub, "financial_aid.aid_granted",
                              payload, strlen(payload), "application/json", NULL) != 0) {
        fprintf(stderr, "Publish failed\n");
    } else {
        printf("Message published successfully\n");
    }

    rmq_publisher_destroy(pub);
    return EXIT_SUCCESS;
}
#endif /* DEBUG_DEMO */

/* -------------------------------------------------------------------------- */
/* End of file                                                                */
/* -------------------------------------------------------------------------- */
