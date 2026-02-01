```c
/**
 * HoloCanvas – Gallery-Gateway
 * ---------------------------------
 * File:    api_handler.c
 * Author:  HoloCanvas Core Team
 *
 * Description:
 *   Public-facing HTTP/JSON API for the Gallery-Gateway micro-service.
 *   Exposes read/write endpoints for:
 *      • Fetching an NFT artifact’s public state
 *      • Placing a bid on an artifact’s current auction
 *      • Service health-check
 *
 *   Internally, the handler:
 *      • Retrieves artifact metadata from the Artifact-Repository
 *      • Publishes bid events to the global Event-Bus (Kafka)
 *      • Implements robust request parsing, validation, and error handling
 *
 * Build:
 *   gcc -Wall -Werror -std=c11 -O2 \
 *       api_handler.c artifact_repository.c event_bus.c \
 *       -ljansson -lmicrohttpd -lrdkafka -lpthread -o gallery_gateway
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <inttypes.h>
#include <microhttpd.h>
#include <jansson.h>
#include <rdkafka.h>
#include <uuid/uuid.h>
#include "artifact_repository.h"
#include "event_bus.h"
#include "config.h"

/* ------------- Constants & Macros --------------------------------------- */

#define HTTP_PORT          GATEWAY_HTTP_PORT
#define MAX_PAYLOAD_SIZE   (64 * 1024)      /* 64 KiB                            */
#define API_VERSION_PATH   "/v1"
#define JSON_INDENT        4

#define RESP_OK            MHD_HTTP_OK
#define RESP_BAD_REQUEST   MHD_HTTP_BAD_REQUEST
#define RESP_NOT_FOUND     MHD_HTTP_NOT_FOUND
#define RESP_SERVER_ERR    MHD_HTTP_INTERNAL_SERVER_ERROR

/* ------------- Data Structures ----------------------------------------- */

/* Per-connection POST context */
typedef struct {
    char      *payload;          /* dynamically grown buffer           */
    size_t     size;             /* current used size                  */
    size_t     alloc;            /* allocated bytes                    */
} post_ctx_t;

/* Api Handler global context */
typedef struct {
    struct MHD_Daemon *daemon;   /* microhttpd daemon instance         */
    rd_kafka_t        *rk;       /* Kafka producer handle              */
    rd_kafka_topic_t  *topic;    /* Kafka topic handle                 */
} gateway_ctx_t;

/* ------------- Forward Declarations ------------------------------------ */

static int  router_handler (void *cls,
                            struct MHD_Connection *connection,
                            const char *url,
                            const char *method,
                            const char *version,
                            const char *upload_data,
                            size_t *upload_data_size,
                            void **con_cls);

static int  handle_get_artifact (struct MHD_Connection *connection,
                                 const char *artifact_id);

static int  handle_post_bid     (gateway_ctx_t          *gw_ctx,
                                 struct MHD_Connection  *connection,
                                 post_ctx_t             *post_ctx);

static int  http_json_reply     (struct MHD_Connection *connection,
                                 unsigned int status_code,
                                 json_t *body);

static int  http_text_reply     (struct MHD_Connection *connection,
                                 unsigned int status_code,
                                 const char *msg);

static int  validate_uuid       (const char *uuid_str);

/* ------------- Helper Implementations ---------------------------------- */

/**
 * Allocate or grow payload buffer.
 */
static int
post_ctx_append(post_ctx_t *ctx, const char *data, size_t size)
{
    if (!ctx || !data || size == 0) return 0;

    if (ctx->size + size + 1 > ctx->alloc) {
        size_t new_alloc = (ctx->alloc == 0) ? 4096 : ctx->alloc * 2;
        while (new_alloc < ctx->size + size + 1)
            new_alloc *= 2;

        char *tmp = realloc(ctx->payload, new_alloc);
        if (!tmp) return -1;

        ctx->payload = tmp;
        ctx->alloc   = new_alloc;
    }

    memcpy(ctx->payload + ctx->size, data, size);
    ctx->size += size;
    ctx->payload[ctx->size] = '\0';
    return 0;
}

/* ------------- Router / Main HTTP Callback ----------------------------- */

/**
 * Central router callback invoked by libmicrohttpd for every HTTP request
 * and every chunk of upload data.
 */
static int
router_handler(void *cls,
               struct MHD_Connection *connection,
               const char *url,
               const char *method,
               const char *version,
               const char *upload_data,
               size_t *upload_data_size,
               void **con_cls)
{
    gateway_ctx_t *gw_ctx = (gateway_ctx_t *)cls;

    /* NEW CONNECTION ---------------------------------------------------- */
    if (*con_cls == NULL) {
        /* Only allocate POST context for POSTs */
        if (strcmp(method, "POST") == 0) {
            post_ctx_t *pctx = calloc(1, sizeof(*pctx));
            if (!pctx) return MHD_NO;
            *con_cls = pctx;
        }
        return MHD_YES;
    }

    /* DATA CHUNK -------------------------------------------------------- */
    if (strcmp(method, "POST") == 0 && *upload_data_size > 0) {
        post_ctx_t *pctx = *con_cls;
        if (pctx->size + *upload_data_size > MAX_PAYLOAD_SIZE) {
            http_text_reply(connection, RESP_BAD_REQUEST,
                            "Payload too large");
            return MHD_YES;
        }

        if (post_ctx_append(pctx, upload_data, *upload_data_size) < 0) {
            http_text_reply(connection, RESP_SERVER_ERR,
                            "Internal buffer allocation failure");
            return MHD_YES;
        }

        *upload_data_size = 0; /* signal libmicrohttpd we've consumed chunk */
        return MHD_YES;
    }

    /* END OF DATA / ROUTING -------------------------------------------- */
    if (strcmp(method, "GET") == 0) {

        /* /healthz ------------------------------------------------------ */
        if (strcmp(url, "/healthz") == 0) {
            return http_text_reply(connection, RESP_OK, "ok");
        }

        /* /v1/artifacts/<uuid> ----------------------------------------- */
        if (strncmp(url, API_VERSION_PATH"/artifacts/", 18) == 0) {
            const char *artifact_id = url + 18;     /* skip prefix */
            return handle_get_artifact(connection, artifact_id);
        }
    }
    else if (strcmp(method, "POST") == 0 && *upload_data_size == 0) {

        /* /v1/bids ------------------------------------------------------ */
        if (strcmp(url, API_VERSION_PATH"/bids") == 0) {
            post_ctx_t *pctx = *con_cls;
            int ret = handle_post_bid(gw_ctx, connection, pctx);
            free(pctx->payload);
            free(pctx);
            *con_cls = NULL;
            return ret;
        }
    }

    /* Default: not found */
    return http_text_reply(connection, RESP_NOT_FOUND, "Not Found");
}

/* ------------- Endpoint Implementations -------------------------------- */

/**
 * GET /v1/artifacts/{uuid}
 */
static int
handle_get_artifact(struct MHD_Connection *connection,
                    const char *artifact_id)
{
    if (!validate_uuid(artifact_id))
        return http_text_reply(connection, RESP_BAD_REQUEST,
                               "Invalid artifact_id (expect UUID)");

    json_t *artifact = artifact_repo_get_by_id(artifact_id);
    if (!artifact)
        return http_text_reply(connection, RESP_NOT_FOUND,
                               "Artifact not found");

    int rc = http_json_reply(connection, RESP_OK, artifact);
    json_decref(artifact);
    return rc;
}

/**
 * POST /v1/bids
 * Body:
 *   {
 *     "artifact_id": "<uuid>",
 *     "amount"     : <uint64>,    (wei)
 *     "bidder"     : "<wallet-addr-hex>"
 *   }
 */
static int
handle_post_bid(gateway_ctx_t *gw_ctx,
                struct MHD_Connection *connection,
                post_ctx_t *post_ctx)
{
    json_error_t jerr;
    json_t *root = json_loads(post_ctx->payload, JSON_DECODE_ANY, &jerr);
    if (!root) {
        return http_text_reply(connection, RESP_BAD_REQUEST,
                               "Malformed JSON body");
    }

    const char *artifact_id = json_string_value(json_object_get(root, "artifact_id"));
    const char *bidder      = json_string_value(json_object_get(root, "bidder"));
    json_t *amount_node     = json_object_get(root, "amount");

    if (!artifact_id || !bidder || !amount_node ||
        !json_is_string(amount_node) && !json_is_integer(amount_node)) {
        json_decref(root);
        return http_text_reply(connection, RESP_BAD_REQUEST,
                               "Missing or invalid fields");
    }

    if (!validate_uuid(artifact_id)) {
        json_decref(root);
        return http_text_reply(connection, RESP_BAD_REQUEST,
                               "Invalid artifact_id");
    }

    uint64_t amount = 0;
    if (json_is_integer(amount_node)) {
        amount = (uint64_t)json_integer_value(amount_node);
    } else { /* string – parse uint64 */
        const char *s = json_string_value(amount_node);
        if (!s || sscanf(s, "%" SCNu64, &amount) != 1) {
            json_decref(root);
            return http_text_reply(connection, RESP_BAD_REQUEST,
                                   "Invalid amount");
        }
    }

    /* Check artifact existence */
    if (!artifact_repo_exists(artifact_id)) {
        json_decref(root);
        return http_text_reply(connection, RESP_NOT_FOUND,
                               "Artifact not found");
    }

    /* Publish bid event to Kafka */
    json_t *event = json_pack("{s:s, s:s, s:I}",
                              "artifact_id", artifact_id,
                              "bidder",      bidder,
                              "amount",      amount);
    char *event_str = json_dumps(event, JSON_COMPACT);
    rd_kafka_resp_err_t kerr =
        event_bus_produce(gw_ctx->rk, gw_ctx->topic, event_str, strlen(event_str));
    json_decref(event);
    free(event_str);

    if (kerr != RD_KAFKA_RESP_ERR_NO_ERROR) {
        json_decref(root);
        return http_text_reply(connection, RESP_SERVER_ERR,
                               "Failed to publish bid event");
    }

    json_decref(root);
    return http_text_reply(connection, RESP_OK,
                           "Bid received");
}

/* ------------- Utility Functions --------------------------------------- */

static int
http_json_reply(struct MHD_Connection *connection,
                unsigned int status_code,
                json_t *body)
{
    char *dump = json_dumps(body, JSON_INDENT | JSON_ENSURE_ASCII);
    struct MHD_Response *resp = MHD_create_response_from_buffer(
        strlen(dump), (void *)dump, MHD_RESPMEM_MUST_FREE);
    if (!resp) { free(dump); return MHD_NO; }

    MHD_add_response_header(resp, "Content-Type", "application/json");
    int ret = MHD_queue_response(connection, status_code, resp);
    MHD_destroy_response(resp);
    return ret;
}

static int
http_text_reply(struct MHD_Connection *connection,
                unsigned int status_code,
                const char *msg)
{
    struct MHD_Response *resp = MHD_create_response_from_buffer(
        strlen(msg), (void *)msg, MHD_RESPMEM_PERSISTENT);
    if (!resp) return MHD_NO;

    MHD_add_response_header(resp, "Content-Type", "text/plain; charset=utf-8");
    int ret = MHD_queue_response(connection, status_code, resp);
    MHD_destroy_response(resp);
    return ret;
}

/**
 * Validate UUID v4 string (basic check, 36 chars + pattern)
 */
static int
validate_uuid(const char *uuid_str)
{
    if (!uuid_str || strlen(uuid_str) != 36) return 0;
    uuid_t uu;
    return (uuid_parse(uuid_str, uu) == 0);
}

/* ------------- Public API ---------------------------------------------- */

gateway_ctx_t *
gateway_start(void)
{
    gateway_ctx_t *ctx = calloc(1, sizeof(*ctx));
    if (!ctx) {
        fprintf(stderr, "Failed to alloc gateway context\n");
        return NULL;
    }

    /* -------- Event-Bus (Kafka) -------------------------------------- */
    ctx->rk = event_bus_create_producer(CONFIG_KAFKA_BROKERS);
    if (!ctx->rk) {
        fprintf(stderr, "Kafka producer init failed\n");
        free(ctx);
        return NULL;
    }
    ctx->topic = rd_kafka_topic_new(ctx->rk,
                                    CONFIG_KAFKA_TOPIC_EVENTS,
                                    NULL);
    if (!ctx->topic) {
        fprintf(stderr, "Failed to create Kafka topic handle\n");
        rd_kafka_destroy(ctx->rk);
        free(ctx);
        return NULL;
    }

    /* -------- HTTP Server (libmicrohttpd) ---------------------------- */
    ctx->daemon = MHD_start_daemon(
        MHD_USE_AUTO_INTERNAL_THREAD | MHD_USE_SELECT_INTERNALLY,
        HTTP_PORT,
        NULL, NULL,                      /* accept policy: default */
        &router_handler, ctx,            /* request handler + arg  */
        MHD_OPTION_CONNECTION_TIMEOUT, 10,
        MHD_OPTION_END);

    if (!ctx->daemon) {
        fprintf(stderr, "microhttpd failed on port %d\n", HTTP_PORT);
        rd_kafka_topic_destroy(ctx->topic);
        rd_kafka_destroy(ctx->rk);
        free(ctx);
        return NULL;
    }

    printf("[Gateway] HTTP server started on port %d\n", HTTP_PORT);
    return ctx;
}

void
gateway_stop(gateway_ctx_t *ctx)
{
    if (!ctx) return;

    MHD_stop_daemon(ctx->daemon);
    rd_kafka_flush(ctx->rk, 5000);            /* ensure all messages sent */
    rd_kafka_topic_destroy(ctx->topic);
    rd_kafka_destroy(ctx->rk);
    free(ctx);

    printf("[Gateway] Clean shutdown complete\n");
}

/* ------------- Main (for standalone debug) ----------------------------- */

#ifdef DEBUG_GATEWAY
int
main(void)
{
    gateway_ctx_t *gw = gateway_start();
    if (!gw) return EXIT_FAILURE;

    printf("Press ENTER to quit...\n");
    getchar();

    gateway_stop(gw);
    return EXIT_SUCCESS;
}
#endif
```
