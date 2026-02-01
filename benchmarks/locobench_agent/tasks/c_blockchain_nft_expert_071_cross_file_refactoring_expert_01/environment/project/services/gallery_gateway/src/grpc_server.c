```c
/**
 * HoloCanvas – Gallery-Gateway
 * ----------------------------------------
 * Production-grade gRPC server exposing a thin API facade for the on-chain
 * “micro-gallery”.  The service receives high-level gallery requests from
 * web/mobile front-ends, translates them to Kafka events that fan-out to the
 * rest of the mesh, and replies with live views of the artwork catalogue.
 *
 * Build dependencies
 *   – protobuf-c          (≥ 1.4)
 *   – grpc-c              (https://github.com/Juniper/grpc-c)
 *   – librdkafka          (≥ 1.9)
 *   – glib-2.0            (utility/collections)
 *
 * Compile example
 *   cc -Wall -Wextra -O2 -g -pthread                     \
 *      grpc_server.c                                     \
 *      gallery_gateway.pb-c.c gallery_gateway.grpc-c.c   \
 *      -lgrpc-c -lgrpc -lprotobuf-c -lrdkafka -lglib-2.0 \
 *      -o gallery_gateway_server
 */
#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include <glib.h>
#include <grpc-c/grpc-c.h>
#include <librdkafka/rdkafka.h>
#include <protobuf-c/protobuf-c.h>

#include "gallery_gateway.grpc-c.h"
#include "gallery_gateway.pb-c.h"

/* ------------------------------------------------------------------------- *
 *  Constants / Tunables                                                     *
 * ------------------------------------------------------------------------- */
#define DEFAULT_LISTEN_ADDR     "0.0.0.0:51052"
#define DEFAULT_KAFKA_BROKERS   "localhost:9092"
#define DEFAULT_KAFKA_TOPIC     "holo_canvas.gateway.events"
#define ENV_LISTEN_ADDR         "GATEWAY_LISTEN_ADDR"
#define ENV_KAFKA_BROKERS       "KAFKA_BROKERS"
#define ENV_KAFKA_TOPIC         "KAFKA_TOPIC"
#define SHUTDOWN_TIMEOUT_SEC    10

/* ------------------------------------------------------------------------- *
 *  Forward Declarations                                                     *
 * ------------------------------------------------------------------------- */
typedef struct gateway_state_s          gateway_state_t;
static void sigint_handler              (int signo);
static void server_shutdown             (gateway_state_t *state);
static int  kafka_emit_bid_event        (gateway_state_t *state,
                                         const Gallery__BidRequest *req,
                                         const char *tx_id);
static int  load_artwork_catalogue      (gateway_state_t *state,
                                         const char *bootstrap_path);

/* ------------------------------------------------------------------------- *
 *  Global / Singleton state                                                 *
 * ------------------------------------------------------------------------- */
static volatile sig_atomic_t g_stop_requested = 0;

/* ------------------------------------------------------------------------- *
 *  Server-wide state container                                              *
 * ------------------------------------------------------------------------- */
struct gateway_state_s
{
    grpc_c_server_t      *grpc_srv;        /* gRPC-C server handle            */
    rd_kafka_t           *rk;              /* Kafka producer handle           */
    rd_kafka_topic_t     *rk_topic;        /* Cached topic handle             */
    GHashTable           *artwork_cache;   /* id (char*) -> Gallery__Artwork* */
    char                 *listen_addr;     /* Where we bind                   */
    char                 *kafka_brokers;   /* Comma-separated broker list     */
    char                 *kafka_topic;     /* Topic name for event fan-out    */
};

/* ************************************************************************** *
 *  Utility helpers                                                           *
 * ************************************************************************** */

/**
 * strdup wrapper that aborts on OOM – simplifies sample code.
 */
static char *xstrdup(const char *s)
{
    char *dup = strdup(s);
    if (!dup)
    {
        perror("strdup");
        abort();
    }
    return dup;
}

/**
 * Very small helper that converts a protobuf message into a
 * length-prefixed binary blob suitable for Kafka delivery.
 */
static void proto_to_kafka_blob(const ProtobufCMessage *msg,
                                uint8_t               **buf_out,
                                size_t                 *len_out)
{
    *len_out = protobuf_c_message_get_packed_size(msg);
    *buf_out = malloc(*len_out);
    if (!*buf_out)
    {
        perror("malloc");
        abort();
    }
    protobuf_c_message_pack(msg, *buf_out);
}

/* ************************************************************************** *
 *  Kafka initialisation / teardown                                           *
 * ************************************************************************** */
static int kafka_init(gateway_state_t *state)
{
    char errstr[512];

    /* Basic, fire-and-forget producer configuration. */
    rd_kafka_conf_t *conf = rd_kafka_conf_new();
    rd_kafka_conf_set(conf, "bootstrap.servers",
                      state->kafka_brokers, errstr, sizeof(errstr));
    rd_kafka_conf_set(conf, "client.id", "gallery-gateway", NULL, 0);

    state->rk = rd_kafka_new(RD_KAFKA_PRODUCER, conf, errstr, sizeof(errstr));
    if (!state->rk)
    {
        fprintf(stderr, "[kafka] Failed to create producer: %s\n", errstr);
        return -1;
    }

    state->rk_topic = rd_kafka_topic_new(state->rk,
                                         state->kafka_topic, NULL);
    if (!state->rk_topic)
    {
        fprintf(stderr, "[kafka] Failed to create topic \"%s\": %s\n",
                state->kafka_topic,
                rd_kafka_err2str(rd_kafka_last_error()));
        return -1;
    }
    return 0;
}

static void kafka_teardown(gateway_state_t *state)
{
    if (!state || !state->rk) return;

    rd_kafka_flush(state->rk, 3000);
    if (state->rk_topic)
        rd_kafka_topic_destroy(state->rk_topic);
    rd_kafka_destroy(state->rk);
}

/* ************************************************************************** *
 *  Artwork catalogue cache (memory-mapped)                                   *
 * ************************************************************************** */

/**
 * In real production code the cache would be backed by a proper store
 * (RocksDB, Postgres, Redis, …).  For the purpose of this example we read a
 * bootstrap binary file containing a packed repeated ArtworkList message.
 */
static int load_artwork_catalogue(gateway_state_t *state,
                                  const char *bootstrap_path)
{
    FILE *fp = fopen(bootstrap_path, "rb");
    if (!fp)
    {
        fprintf(stderr, "[catalogue] Unable to open \"%s\": %s\n",
                bootstrap_path, strerror(errno));
        return -1;
    }

    fseek(fp, 0, SEEK_END);
    long fsize = ftell(fp);
    rewind(fp);

    uint8_t *buffer = malloc(fsize);
    if (fread(buffer, 1, fsize, fp) != (size_t)fsize)
    {
        fprintf(stderr, "[catalogue] Short read\n");
        fclose(fp);
        free(buffer);
        return -1;
    }
    fclose(fp);

    /* Parsing bootstrap message (Gallery__ArtworkList := repeated Artwork) */
    Gallery__ArtworkList *list =
        gallery__artwork_list__unpack(NULL, fsize, buffer);
    free(buffer);

    if (!list)
    {
        fprintf(stderr, "[catalogue] Failed to unpack bootstrap list\n");
        return -1;
    }

    for (size_t i = 0; i < list->n_artworks; ++i)
    {
        Gallery__Artwork *copy =
            protobuf_c_message_duplicate(NULL, &list->artworks[i].base,
                                         gallery__artwork__get_packed_size,
                                         gallery__artwork__unpack);
        g_hash_table_insert(state->artwork_cache,
                            copy->id, copy); /* id string is owned */
    }

    gallery__artwork_list__free_unpacked(list, NULL);
    fprintf(stdout, "[catalogue] Loaded %u artworks from bootstrap\n",
            (unsigned)g_hash_table_size(state->artwork_cache));
    return 0;
}

/* ************************************************************************** *
 *  gRPC service callbacks                                                    *
 * ************************************************************************** */

static void list_artworks_cb(Gallery__ListArtworksRequest           *req,
                             grpc_c_invoke_ctx_t                    *invoke_ctx,
                             void                                   *userdata)
{
    (void)req;
    gateway_state_t *state = userdata;

    /* Iterate over the cache and stream ArtworkMeta messages. */
    GHashTableIter iter;
    gpointer key, value;
    g_hash_table_iter_init(&iter, state->artwork_cache);

    while (g_hash_table_iter_next(&iter, &key, &value))
    {
        Gallery__Artwork *art = value;

        Gallery__ArtworkMeta meta = GALLERY__ARTWORK_META__INIT;
        meta.id          = art->id;
        meta.title       = art->title;
        meta.artist_name = art->artist_name;
        meta.current_state = art->current_state;

        grpc_c_stream_write(invoke_ctx, &meta, NULL); /* Ignore back-pressure */
    }

    /* Close stream */
    grpc_c_status_t status = { GRPC_STATUS_OK, 0, NULL };
    grpc_c_stream_write_and_finish(invoke_ctx, NULL, &status);
}

static void get_artwork_cb(Gallery__ArtworkId                      *req,
                           grpc_c_invoke_ctx_t                     *invoke_ctx,
                           void                                    *userdata)
{
    gateway_state_t *state = userdata;

    Gallery__Artwork *art =
        g_hash_table_lookup(state->artwork_cache, req->id);

    if (!art)
    {
        /* Not found – respond with NOT_FOUND */
        grpc_c_status_t status = { GRPC_STATUS_NOT_FOUND,
                                   0,
                                   "Artwork not found" };
        grpc_c_stream_write_and_finish(invoke_ctx, NULL, &status);
        return;
    }

    grpc_c_status_t status_ok = { GRPC_STATUS_OK, 0, NULL };
    grpc_c_stream_write(invoke_ctx, art, NULL);
    grpc_c_stream_write_and_finish(invoke_ctx, NULL, &status_ok);
}

static void submit_bid_cb(Gallery__BidRequest                      *req,
                          grpc_c_invoke_ctx_t                      *invoke_ctx,
                          void                                     *userdata)
{
    gateway_state_t *state = userdata;

    /* TODO: real transaction submission to Ledger-Core. Fake it for now. */
    char tx_id[64];
    snprintf(tx_id, sizeof(tx_id), "0x%08X%08X",
             (unsigned)time(NULL), (unsigned)getpid());

    /* Emit Kafka fan-out */
    if (kafka_emit_bid_event(state, req, tx_id) != 0)
    {
        grpc_c_status_t err = { GRPC_STATUS_INTERNAL,
                                0,
                                "Failed to emit bid event" };
        grpc_c_stream_write_and_finish(invoke_ctx, NULL, &err);
        return;
    }

    Gallery__BidResponse resp = GALLERY__BID_RESPONSE__INIT;
    resp.accepted  = true;
    resp.tx_id     = tx_id;
    resp.timestamp = (uint64_t)time(NULL);

    grpc_c_status_t status_ok = { GRPC_STATUS_OK, 0, NULL };
    grpc_c_stream_write(invoke_ctx, &resp, NULL);
    grpc_c_stream_write_and_finish(invoke_ctx, NULL, &status_ok);
}

/* ************************************************************************** *
 *  Kafka helper                                                              *
 * ************************************************************************** */
static int kafka_emit_bid_event(gateway_state_t           *state,
                                const Gallery__BidRequest *req,
                                const char                *tx_id)
{
    /* Wrap the bid + tx_id in an envelope */
    Gallery__BidEvent evt = GALLERY__BID_EVENT__INIT;
    evt.bid       = (Gallery__BidRequest *)req;  /* cast away const */
    evt.tx_id     = (char *)tx_id;
    evt.event_ts  = (uint64_t)time(NULL);

    uint8_t *payload = NULL;
    size_t   len     = 0;
    proto_to_kafka_blob(&evt.base, &payload, &len);

    rd_kafka_resp_err_t err =
        rd_kafka_produce(state->rk_topic,
                         RD_KAFKA_PARTITION_UA,
                         RD_KAFKA_MSG_F_COPY,
                         payload,
                         len,
                         NULL, 0,
                         NULL);
    if (err != RD_KAFKA_RESP_ERR_NO_ERROR)
    {
        fprintf(stderr,
                "[kafka] Failed to queue event: %s\n",
                rd_kafka_err2str(err));
        free(payload);
        return -1;
    }
    /* Ownership transferred */
    return 0;
}

/* ************************************************************************** *
 *  Signal / graceful shutdown                                                *
 * ************************************************************************** */
static void sigint_handler(int signo)
{
    (void)signo;
    g_stop_requested = 1;
}

/* ************************************************************************** *
 *  Main                                                                      *
 * ************************************************************************** */
int main(int argc, char **argv)
{
    (void)argc; (void)argv;

    /* --------------------------------------------------------------------- */
    /*  Bootstrap configuration                                              */
    /* --------------------------------------------------------------------- */
    gateway_state_t state = { 0 };
    state.listen_addr   = xstrdup(getenv(ENV_LISTEN_ADDR)
                                  ? getenv(ENV_LISTEN_ADDR)
                                  : DEFAULT_LISTEN_ADDR);
    state.kafka_brokers = xstrdup(getenv(ENV_KAFKA_BROKERS)
                                  ? getenv(ENV_KAFKA_BROKERS)
                                  : DEFAULT_KAFKA_BROKERS);
    state.kafka_topic   = xstrdup(getenv(ENV_KAFKA_TOPIC)
                                  ? getenv(ENV_KAFKA_TOPIC)
                                  : DEFAULT_KAFKA_TOPIC);

    state.artwork_cache = g_hash_table_new_full(g_str_hash, g_str_equal,
                                                NULL, /* keys are part of message */
                                                (GDestroyNotify)gallery__artwork__free_unpacked);

    if (load_artwork_catalogue(&state, "bootstrap_catalogue.bin") != 0)
        return EXIT_FAILURE;

    if (kafka_init(&state) != 0)
        return EXIT_FAILURE;

    /* --------------------------------------------------------------------- */
    /*  Setup gRPC-C server                                                  */
    /* --------------------------------------------------------------------- */
    grpc_c_init(GRPC_THREADS, NULL);

    state.grpc_srv = grpc_c_server_create(state.listen_addr, NULL);
    if (!state.grpc_srv)
    {
        fprintf(stderr, "[grpc] Unable to bind to %s\n", state.listen_addr);
        return EXIT_FAILURE;
    }

    /* Register service implementation */
    Gallery__Gateway__ServiceDesc *svc_desc =
        gallery__gateway__descriptor_get_service_desc();
    grpc_c_service_t *svc =
        grpc_c_service_create(svc_desc, &state);

    /* Map RPC names to our callbacks */
    grpc_c_service_add_method(svc, "ListArtworks",
                              (grpc_c_method_callback_t)list_artworks_cb);
    grpc_c_service_add_method(svc, "GetArtwork",
                              (grpc_c_method_callback_t)get_artwork_cb);
    grpc_c_service_add_method(svc, "SubmitBid",
                              (grpc_c_method_callback_t)submit_bid_cb);

    grpc_c_server_register_service(state.grpc_srv, svc);

    if (grpc_c_server_start(state.grpc_srv) != 0)
    {
        fprintf(stderr, "[grpc] Failed to start server\n");
        return EXIT_FAILURE;
    }

    fprintf(stdout, "[grpc] Gallery-Gateway listening on %s\n",
            state.listen_addr);

    /* --------------------------------------------------------------------- */
    /*  Main loop                                                            */
    /* --------------------------------------------------------------------- */
    signal(SIGINT,  sigint_handler);
    signal(SIGTERM, sigint_handler);

    while (!g_stop_requested)
        sleep(1);

    fprintf(stdout, "\n[main] Termination requested, shutting down…\n");
    server_shutdown(&state);
    return EXIT_SUCCESS;
}

/* ************************************************************************** *
 *  Cleanup                                                                   *
 * ************************************************************************** */
static void server_shutdown(gateway_state_t *state)
{
    g_assert(state);

    grpc_c_server_shutdown(state->grpc_srv, SHUTDOWN_TIMEOUT_SEC * 1000 /*ms*/);
    grpc_c_server_destroy(state->grpc_srv);

    kafka_teardown(state);

    g_hash_table_destroy(state->artwork_cache);

    free(state->listen_addr);
    free(state->kafka_brokers);
    free(state->kafka_topic);

    grpc_c_shutdown();
}
```