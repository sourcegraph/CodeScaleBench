```c
/**
 * LexiLearn MVC Orchestrator — Dashboard HTTP Server
 *
 * This module belongs to the View layer and exposes a lightweight HTTP
 * endpoint that streams real-time model-monitoring information to
 * JavaScript dashboards.  The server is intentionally kept simple—
 * libmicrohttpd for HTTP, Jansson for JSON encoding, pthreads for the
 * refresh loop—to avoid introducing heavy-weight web frameworks into
 * the C runtime.
 *
 * Build (example):
 *   gcc -Wall -Wextra -pedantic -std=c11 \
 *       -I/usr/include -o dashboard_server \
 *       dashboard_server.c -lmicrohttpd -ljansson -lpthread
 *
 * Production deployments should run this binary behind Nginx or an
 * API-gateway with TLS termination, authentication, and rate-limiting.
 */

#define _POSIX_C_SOURCE 200809L
#include <microhttpd.h>
#include <jansson.h>

#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* --------------------------------------------------------------------------
 * Compilation flags
 * -------------------------------------------------------------------------- */
#ifndef DASHBOARD_HTTP_PORT
#   define DASHBOARD_HTTP_PORT 8080U
#endif

#ifndef METRIC_REFRESH_SEC
#   define METRIC_REFRESH_SEC 5U      /* How often to pull new metrics   */
#endif

#ifndef JSON_MAX_DIGITS
#   define JSON_MAX_DIGITS 64         /* Buffer room for numeric strings */
#endif

/* --------------------------------------------------------------------------
 * Data structures
 * -------------------------------------------------------------------------- */

/* Snapshot of the metrics we show on the dashboard.  Extend as needed.  */
typedef struct
{
    double   average_accuracy;              /* Rolling validation accuracy   */
    double   model_drift;                   /* Population-wide drift metric  */
    char     current_model_id[64];          /* e.g. “transformer-v4.2.1”     */
    time_t   last_retrain_time;             /* UNIX epoch seconds            */
} ll_metrics_t;

/* Opaque server handle */
typedef struct
{
    struct MHD_Daemon *daemon;              /* libmicrohttpd web server      */
    pthread_t          refresh_thread;      /* Periodic metrics puller       */
    pthread_mutex_t    lock;                /* Protects “metrics”            */
    ll_metrics_t       metrics;             /* Latest snapshot               */
    atomic_bool        stop;                /* Cancellation flag             */
    unsigned int       port;                /* TCP listen port               */
} ll_dash_server_t;

/* --------------------------------------------------------------------------
 * Forward declarations
 * -------------------------------------------------------------------------- */
static int         http_request_cb(void *,
                                   struct MHD_Connection *,
                                   const char *,
                                   const char *,
                                   const char *,
                                   const char *,
                                   size_t *,
                                   void **);
static int         serve_metrics_json(struct MHD_Connection *,
                                      const ll_metrics_t *);
static int         serve_root(struct MHD_Connection *);
static int         fetch_latest_metrics(ll_metrics_t *);
static void       *refresh_loop(void *);
static int         dash_server_start(ll_dash_server_t *, unsigned int);
static void        dash_server_stop(ll_dash_server_t *);
static void        terminate(int);

/* --------------------------------------------------------------------------
 * Global (file-scope) variables
 * -------------------------------------------------------------------------- */
static ll_dash_server_t g_srv;              /* Single instance               */

/* --------------------------------------------------------------------------
 * HTTP helpers
 * -------------------------------------------------------------------------- */

/* JSON encoder for /api/metrics */
static int
serve_metrics_json(struct MHD_Connection *connection, const ll_metrics_t *m)
{
    int ret;
    json_t *root = json_object();
    if (!root)
        return MHD_NO;

    json_object_set_new(root, "average_accuracy",
                        json_real(m->average_accuracy));
    json_object_set_new(root, "model_drift",
                        json_real(m->model_drift));
    json_object_set_new(root, "current_model_id",
                        json_string(m->current_model_id));
    json_object_set_new(root, "last_retrain_time",
                        json_integer((json_int_t)m->last_retrain_time));

    char *dump = json_dumps(root, JSON_COMPACT);
    json_decref(root);
    if (!dump)
        return MHD_NO;

    struct MHD_Response *response =
        MHD_create_response_from_buffer(strlen(dump),
                                        (void *)dump,
                                        MHD_RESPMEM_MUST_FREE);
    if (!response)
    {
        free(dump);
        return MHD_NO;
    }

    MHD_add_response_header(response, "Content-Type", "application/json");
    ret = MHD_queue_response(connection, MHD_HTTP_OK, response);
    MHD_destroy_response(response);
    return ret;
}

/* Minimal HTML so cURL or browsers show a useful page at “/” */
static int
serve_root(struct MHD_Connection *connection)
{
    static const char page[] =
        "<html><head><title>LexiLearn Dashboard</title></head>"
        "<body style=\"font-family:sans-serif;\">"
        "<h1>LexiLearn Dashboard Server</h1>"
        "<p>Endpoint <code>/api/metrics</code> returns JSON metrics.</p>"
        "</body></html>";
    struct MHD_Response *response =
        MHD_create_response_from_buffer(sizeof(page) - 1,
                                        (void *)page,
                                        MHD_RESPMEM_PERSISTENT);
    if (!response)
        return MHD_NO;

    int ret = MHD_queue_response(connection, MHD_HTTP_OK, response);
    MHD_destroy_response(response);
    return ret;
}

/* Main libmicrohttpd callback */
static int
http_request_cb(void                *cls,
                struct MHD_Connection *connection,
                const char           *url,
                const char           *method,
                const char           *version,
                const char           *upload_data,
                size_t               *upload_data_size,
                void                **con_cls)
{
    (void)cls; (void)version; (void)upload_data; (void)upload_data_size;
    (void)con_cls; /* unused */

    if (strcmp(method, "GET") != 0)
        return MHD_NO;

    if (strcmp(url, "/") == 0)
        return serve_root(connection);

    if (strcmp(url, "/api/metrics") == 0)
    {
        ll_metrics_t snapshot;
        ll_dash_server_t *srv = &g_srv;
        pthread_mutex_lock(&srv->lock);
        snapshot = srv->metrics;
        pthread_mutex_unlock(&srv->lock);
        return serve_metrics_json(connection, &snapshot);
    }

    /* 404 Not Found */
    const char *err = "404 - Not Found\n";
    struct MHD_Response *resp =
        MHD_create_response_from_buffer(strlen(err),
                                        (void *)err,
                                        MHD_RESPMEM_PERSISTENT);
    if (!resp)
        return MHD_NO;

    int ret = MHD_queue_response(connection, MHD_HTTP_NOT_FOUND, resp);
    MHD_destroy_response(resp);
    return ret;
}

/* --------------------------------------------------------------------------
 * Metrics collection
 * -------------------------------------------------------------------------- */

/**
 * NOTE:  In production this function would communicate with the Controller
 *        layer via ZeroMQ, gRPC, shared-memory, etc.  For now we simulate
 *        a live system by generating random values.
 */
static int
fetch_latest_metrics(ll_metrics_t *out)
{
    if (!out)
        return -EINVAL;

    /* Random numbers for demo purposes */
    static double acc = 0.85;
    static double drift = 0.02;
    acc   += ((rand() % 100) - 50) / 10000.0;   /* ±0.005 */
    drift += ((rand() % 100) - 50) / 10000.0;   /* ±0.005 */
    if (acc   > 1.0) acc   = 1.0;
    if (acc   < 0.0) acc   = 0.0;
    if (drift > 1.0) drift = 1.0;
    if (drift < 0.0) drift = 0.0;

    out->average_accuracy  = acc;
    out->model_drift       = drift;
    snprintf(out->current_model_id,
             sizeof(out->current_model_id),
             "transformer-v%u.%u.%u",
             4U, (rand() % 3) + 1U, (rand() % 10));
    out->last_retrain_time = time(NULL) - (rand() % 86400);

    return 0;
}

/* Thread that periodically pulls metrics from the Controller */
static void *
refresh_loop(void *arg)
{
    ll_dash_server_t *srv = arg;
    while (!atomic_load_explicit(&srv->stop, memory_order_acquire))
    {
        ll_metrics_t tmp;
        if (fetch_latest_metrics(&tmp) == 0)
        {
            pthread_mutex_lock(&srv->lock);
            srv->metrics = tmp;
            pthread_mutex_unlock(&srv->lock);
        }

        for (unsigned i = 0; i < METRIC_REFRESH_SEC * 10
                              && !atomic_load_explicit(&srv->stop,
                                                       memory_order_acquire);
             ++i)
        {
            struct timespec ts = {0, 100 * 1000 * 1000}; /* 100 ms */
            nanosleep(&ts, NULL);
        }
    }
    return NULL;
}

/* --------------------------------------------------------------------------
 * Server lifecycle
 * -------------------------------------------------------------------------- */

static int
dash_server_start(ll_dash_server_t *srv, unsigned int port)
{
    if (!srv)
        return -EINVAL;

    memset(srv, 0, sizeof(*srv));
    srv->port = port;
    pthread_mutex_init(&srv->lock, NULL);
    atomic_init(&srv->stop, false);

    /* Initial metrics populate so the dashboard isn't empty at startup */
    fetch_latest_metrics(&srv->metrics);

    /* Start HTTP daemon (MHD_USE_SELECT_INTERNALLY spawns worker thread) */
    srv->daemon = MHD_start_daemon(MHD_USE_AUTO | MHD_USE_INTERNAL_POLLING_THREAD,
                                   srv->port,
                                   NULL, NULL,
                                   &http_request_cb, srv,
                                   MHD_OPTION_END);
    if (!srv->daemon)
    {
        fprintf(stderr, "Failed to start HTTP server on port %u\n", port);
        return -EIO;
    }

    /* Spawn background refresh thread */
    if (pthread_create(&srv->refresh_thread, NULL, refresh_loop, srv) != 0)
    {
        fprintf(stderr, "Failed to create refresh thread: %s\n",
                strerror(errno));
        MHD_stop_daemon(srv->daemon);
        srv->daemon = NULL;
        return -errno;
    }

    printf("Dashboard server listening on port %u\n", port);
    return 0;
}

static void
dash_server_stop(ll_dash_server_t *srv)
{
    if (!srv || !srv->daemon)
        return;

    atomic_store_explicit(&srv->stop, true, memory_order_release);

    pthread_join(srv->refresh_thread, NULL);
    MHD_stop_daemon(srv->daemon);
    pthread_mutex_destroy(&srv->lock);
    srv->daemon = NULL;
    printf("Dashboard server terminated.\n");
}

/* --------------------------------------------------------------------------
 * Signal handling
 * -------------------------------------------------------------------------- */
static void
terminate(int signum)
{
    (void)signum;
    dash_server_stop(&g_srv);
    /* Restore default handler and re-raise to let shell know exit reason */
    signal(signum, SIG_DFL);
    raise(signum);
}

/* --------------------------------------------------------------------------
 * Stand-alone entry point
 * -------------------------------------------------------------------------- */
int
main(int argc, char **argv)
{
    (void)argc; (void)argv;

    unsigned int port = DASHBOARD_HTTP_PORT;
    const char *env = getenv("LEXILEARN_DASH_PORT");
    if (env)
    {
        char *end = NULL;
        long val = strtol(env, &end, 10);
        if (end && *end == '\0' && val > 0 && val < 65536)
            port = (unsigned int)val;
    }

    /* Seed PRNG for dummy metrics */
    srand((unsigned)time(NULL));

    /* Handle SIGINT / SIGTERM for graceful shutdown */
    signal(SIGINT,  terminate);
    signal(SIGTERM, terminate);

    if (dash_server_start(&g_srv, port) != 0)
        return EXIT_FAILURE;

    /* Main thread blocks until refresh_thread exits (via signal) */
    pthread_join(g_srv.refresh_thread, NULL);
    /* Shouldn't reach here, but be safe */
    dash_server_stop(&g_srv);

    return EXIT_SUCCESS;
}
```