```c
/**
 * SynestheticCanvas – Audio Service
 * ---------------------------------
 * Entry point for the audio micro-service.  Exposes a small REST interface
 * consumed by the API-Gateway.  Features:
 *
 *   • /health                – Liveness/readiness probe  (GET)
 *   • /audio/analyze         – Light-weight audio analysis (POST JSON)
 *
 * This file is self-contained for demo purposes; in production the helpers
 * would live in dedicated translation units.
 *
 * Build:
 *   cc -Wall -Wextra -O2 -std=c11 -o audio-service \
 *      main.c -lmicrohttpd -ljansson
 */

#define _POSIX_C_SOURCE 200809L
#include <microhttpd.h>
#include <jansson.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* --------------------------------------------------------------------------
 *  Compile-time constants
 * -------------------------------------------------------------------------- */
#define SERVICE_VERSION   "1.2.0"
#define DEFAULT_PORT      8084
#define POST_BUFFER_SIZE  (64 * 1024)     /* 64 KiB             */
#define MAX_SAMPLE_COUNT  (48 * 1000)     /* 1 second @ 48 kHz  */

/* --------------------------------------------------------------------------
 *  Utility ‑ Logging
 * -------------------------------------------------------------------------- */
typedef enum { LOG_ERROR = 0, LOG_WARN, LOG_INFO, LOG_DEBUG } log_level_t;
static log_level_t g_log_level = LOG_INFO;

/* Return current UTC ISO-8601 timestamp. */
static void iso_timestamp(char *buf, size_t len)
{
    time_t     now = time(NULL);
    struct tm  tm  = *gmtime(&now);
    strftime(buf, len, "%Y-%m-%dT%H:%M:%SZ", &tm);
}

__attribute__((format(printf, 3, 4)))
static void logger(log_level_t lvl, const char *tag, const char *fmt, ...)
{
    if (lvl > g_log_level) return;

    static const char *lvl_str[] = { "ERROR", "WARN ", "INFO ", "DEBUG" };
    char ts[32];
    iso_timestamp(ts, sizeof ts);

    fprintf((lvl == LOG_ERROR) ? stderr : stdout, "[%s] [%s] [%s] ", ts,
            lvl_str[lvl], tag);

    va_list ap;
    va_start(ap, fmt);
    vfprintf((lvl == LOG_ERROR) ? stderr : stdout, fmt, ap);
    va_end(ap);
    fputc('\n', (lvl == LOG_ERROR) ? stderr : stdout);
}

/* --------------------------------------------------------------------------
 *  Configuration
 * -------------------------------------------------------------------------- */
typedef struct {
    uint16_t    port;
    const char *log_level_env;
} app_config_t;

static void load_config(app_config_t *cfg)
{
    const char *port_env = getenv("SC_AUDIO_PORT");
    cfg->port = (uint16_t) (port_env ? atoi(port_env) : DEFAULT_PORT);

    cfg->log_level_env = getenv("SC_AUDIO_LOG_LEVEL");
    if (cfg->log_level_env) {
        if (strcasecmp(cfg->log_level_env, "DEBUG") == 0)
            g_log_level = LOG_DEBUG;
        else if (strcasecmp(cfg->log_level_env, "INFO") == 0)
            g_log_level = LOG_INFO;
        else if (strcasecmp(cfg->log_level_env, "WARN") == 0)
            g_log_level = LOG_WARN;
        else if (strcasecmp(cfg->log_level_env, "ERROR") == 0)
            g_log_level = LOG_ERROR;
    }
}

/* --------------------------------------------------------------------------
 *  Signal handling – Graceful shutdown
 * -------------------------------------------------------------------------- */
static volatile sig_atomic_t g_terminate = 0;

static void handle_signal(int sig)
{
    (void)sig;
    g_terminate = 1;
}

/* --------------------------------------------------------------------------
 *  Endpoint: /health
 * -------------------------------------------------------------------------- */
static int reply_health(struct MHD_Connection *conn)
{
    int ret;
    json_t *root = json_pack("{s:s, s:s}", "status", "ok",
                             "version", SERVICE_VERSION);

    char *json_buf = json_dumps(root, JSON_COMPACT);
    json_decref(root);

    struct MHD_Response *resp = MHD_create_response_from_buffer(
        strlen(json_buf), json_buf, MHD_RESPMEM_MUST_FREE);

    if (!resp) {
        free(json_buf);
        return MHD_NO;
    }
    MHD_add_response_header(resp, "Content-Type", "application/json");
    ret = MHD_queue_response(conn, MHD_HTTP_OK, resp);
    MHD_destroy_response(resp);
    return ret;
}

/* --------------------------------------------------------------------------
 *  Endpoint: /audio/analyze
 * -------------------------------------------------------------------------- */
typedef struct {
    char *data;
    size_t size;
} post_accumulator_t;

static int post_iterator(void *coninfo_cls, enum MHD_ValueKind kind,
                         const char *key, const char *filename,
                         const char *content_type, const char *transfer_encoding,
                         const char *data, uint64_t off, size_t size)
{
    (void)kind; (void)key; (void)filename; (void)content_type;
    (void)transfer_encoding; (void)off;

    post_accumulator_t *acc = coninfo_cls;
    if (size == 0) return MHD_YES;

    if (acc->size + size > POST_BUFFER_SIZE) {
        logger(LOG_WARN, "POST", "Payload exceeded buffer limit.");
        return MHD_NO;
    }

    memcpy(acc->data + acc->size, data, size);
    acc->size += size;
    return MHD_YES;
}

static double rms(const double *samples, size_t n)
{
    double sumsq = 0.0;
    for (size_t i = 0; i < n; ++i)
        sumsq += samples[i] * samples[i];
    return n ? sqrt(sumsq / n) : 0.0;
}

static int reply_audio_analyze(struct MHD_Connection *conn,
                               const char *payload, size_t payload_size)
{
    json_error_t jerr;
    json_t *root = json_loadb(payload, payload_size, 0, &jerr);
    if (!root || !json_is_object(root)) {
        logger(LOG_WARN, "JSON", "Invalid JSON payload: %s", jerr.text);
        json_decref(root);
        return MHD_queue_response(conn, MHD_HTTP_BAD_REQUEST,
                                  MHD_create_response_from_buffer(0, NULL,
                                  MHD_RESPMEM_PERSISTENT));
    }

    json_t *samples_arr = json_object_get(root, "samples");
    if (!samples_arr || !json_is_array(samples_arr)) {
        json_decref(root);
        return MHD_queue_response(conn, MHD_HTTP_BAD_REQUEST,
                                  MHD_create_response_from_buffer(0, NULL,
                                  MHD_RESPMEM_PERSISTENT));
    }

    size_t n_samples = json_array_size(samples_arr);
    if (n_samples == 0 || n_samples > MAX_SAMPLE_COUNT) {
        json_decref(root);
        return MHD_queue_response(conn, MHD_HTTP_BAD_REQUEST,
                                  MHD_create_response_from_buffer(0, NULL,
                                  MHD_RESPMEM_PERSISTENT));
    }

    double *samples = malloc(sizeof(double) * n_samples);
    if (!samples) {
        json_decref(root);
        return MHD_queue_response(conn, MHD_HTTP_INTERNAL_SERVER_ERROR,
                                  MHD_create_response_from_buffer(0, NULL,
                                  MHD_RESPMEM_PERSISTENT));
    }

    for (size_t i = 0; i < n_samples; ++i) {
        json_t *val = json_array_get(samples_arr, i);
        if (!json_is_number(val)) {
            free(samples);
            json_decref(root);
            return MHD_queue_response(conn, MHD_HTTP_BAD_REQUEST,
                                      MHD_create_response_from_buffer(0, NULL,
                                      MHD_RESPMEM_PERSISTENT));
        }
        samples[i] = json_number_value(val);
    }
    double res_rms = rms(samples, n_samples);
    free(samples);
    json_decref(root);

    json_t *resp_root = json_pack("{s:f}", "rms", res_rms);
    char *json_buf = json_dumps(resp_root, JSON_COMPACT);
    json_decref(resp_root);

    struct MHD_Response *resp = MHD_create_response_from_buffer(
        strlen(json_buf), json_buf, MHD_RESPMEM_MUST_FREE);
    if (!resp) {
        free(json_buf);
        return MHD_NO;
    }
    MHD_add_response_header(resp, "Content-Type", "application/json");
    int ret = MHD_queue_response(conn, MHD_HTTP_OK, resp);
    MHD_destroy_response(resp);
    return ret;
}

/* --------------------------------------------------------------------------
 *  Routing
 * -------------------------------------------------------------------------- */
static int on_request(void *cls, struct MHD_Connection *conn,
                      const char *url, const char *method,
                      const char *version, const char *upload_data,
                      size_t *upload_data_size, void **con_cls)
{
    (void)cls; (void)version;

    if (strcmp(url, "/health") == 0 && strcmp(method, "GET") == 0) {
        return reply_health(conn);
    }

    /* POST /audio/analyze */
    if (strcmp(url, "/audio/analyze") == 0) {
        if (strcmp(method, "POST") != 0)
            return MHD_queue_response(conn, MHD_HTTP_METHOD_NOT_ALLOWED,
                                      MHD_create_response_from_buffer(0, NULL,
                                      MHD_RESPMEM_PERSISTENT));

        /* 1st call: allocate per-connection storage. */
        if (*con_cls == NULL) {
            post_accumulator_t *acc = calloc(1, sizeof(*acc));
            if (!acc) return MHD_NO;
            acc->data = calloc(1, POST_BUFFER_SIZE);
            if (!acc->data) {
                free(acc);
                return MHD_NO;
            }
            *con_cls = acc;
            return MHD_YES;
        }

        post_accumulator_t *acc = *con_cls;

        if (*upload_data_size != 0) {
            /* streaming data chunk */
            if (post_iterator(acc, MHD_POSTDATA_KIND, NULL, NULL, NULL, NULL,
                              upload_data, 0, *upload_data_size) == MHD_NO) {
                return MHD_queue_response(conn, MHD_HTTP_PAYLOAD_TOO_LARGE,
                                          MHD_create_response_from_buffer(0,
                                          NULL, MHD_RESPMEM_PERSISTENT));
            }
            *upload_data_size = 0;
            return MHD_YES;
        }

        /* No more data – generate response. */
        int ret = reply_audio_analyze(conn, acc->data, acc->size);
        free(acc->data);
        free(acc);
        *con_cls = NULL;
        return ret;
    }

    /* Fallback – 404 */
    return MHD_queue_response(conn, MHD_HTTP_NOT_FOUND,
                              MHD_create_response_from_buffer(0, NULL,
                              MHD_RESPMEM_PERSISTENT));
}

/* --------------------------------------------------------------------------
 *  Main
 * -------------------------------------------------------------------------- */
int main(void)
{
    app_config_t cfg = {0};
    load_config(&cfg);

    struct sigaction sa = { .sa_handler = handle_signal };
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    logger(LOG_INFO, "BOOT", "Starting Audio Service v%s on port %u",
           SERVICE_VERSION, cfg.port);

    struct MHD_Daemon *daemon = MHD_start_daemon(
        MHD_USE_AUTO_INTERNAL_THREAD
        | MHD_USE_DUAL_STACK
        | MHD_USE_DEBUG,   /* enable internal debugging */
        cfg.port,
        NULL, NULL,        /* accept policy callback */
        &on_request, NULL, /* request handler */
        MHD_OPTION_CONNECTION_TIMEOUT, (unsigned int)10,
        MHD_OPTION_END);

    if (!daemon) {
        logger(LOG_ERROR, "BOOT", "Failed to start HTTP daemon.");
        return EXIT_FAILURE;
    }

    while (!g_terminate) {
        /* Could add metrics collection, etc. */
        sleep(1);
    }

    logger(LOG_INFO, "SHUTDOWN", "Graceful stop requested.");
    MHD_stop_daemon(daemon);
    logger(LOG_INFO, "SHUTDOWN", "Audio Service stopped.");
    return EXIT_SUCCESS;
}
```