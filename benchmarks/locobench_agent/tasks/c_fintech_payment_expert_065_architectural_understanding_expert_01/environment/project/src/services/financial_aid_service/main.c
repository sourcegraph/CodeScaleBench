/*
 * EduPay Ledger Academy
 * File:    src/services/financial_aid_service/main.c
 * Author:  EduPay Ledger Academy Core Team
 *
 * Description:
 *   Entry-point for the Financial-Aid microservice.  This daemon is responsible
 *   for orchestrating grant and scholarship disbursements, participating in
 *   Saga-based distributed transactions, and emitting audit events in
 *   compliance with FERPA, PCI-DSS, and PSD2 regulations.
 *
 *   The program bootstraps infrastructure concerns (configuration, logging,
 *   database, message bus), then delegates all business rules to the
 *   Application layer through clearly-defined interfaces.
 *
 * Build:
 *   cc -std=c11 -Wall -Wextra -pedantic -O2 \
 *      -I../../include -lpq -lzmq -ljansson -pthread \
 *      -o financial_aid_service main.c
 */

#define _POSIX_C_SOURCE 200809L

#include <jansson.h>            /* JSON configuration                      */
#include <libpq-fe.h>           /* PostgreSQL connection                   */
#include <signal.h>             /* Signal handling                         */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <string.h>
#include <threads.h>            /* C11 threads                             */
#include <time.h>
#include <unistd.h>
#include <zmq.h>                /* ØMQ message bus                         */

/*---------------------------------------------------------------------------
 *  Local configuration model
 *---------------------------------------------------------------------------*/
typedef struct {
    char  db_uri[256];
    char  bus_endpoint[256];
    int   demo_mode;            /* 1 = Saga demonstration with failures    */
    int   enable_saga;          /* 1 = participate in Saga orchestration   */
    int   log_level;            /* 0-5, see logger.h                       */
} config_t;

/*---------------------------------------------------------------------------
 *  Logger (very small adapter around stderr/syslog)
 *---------------------------------------------------------------------------*/
typedef enum { LOG_FATAL, LOG_ERROR, LOG_WARN, LOG_INFO, LOG_DEBUG, LOG_TRACE } log_lvl_t;

static _Atomic int g_log_level = LOG_INFO;

static const char* lvl_txt(log_lvl_t lvl)
{
    static const char* LUT[] = { "FATAL", "ERROR", "WARN ", "INFO ", "DEBUG", "TRACE" };
    return LUT[lvl];
}

#define LOG(LVL, FMT, ...)                                                     \
    do {                                                                       \
        if ((LVL) <= g_log_level) {                                            \
            fprintf(                                                           \
                stderr,                                                        \
                "[%s] %s:%d:%s(): " FMT "\n",                                  \
                lvl_txt(LVL),                                                  \
                __FILE__,                                                      \
                __LINE__,                                                      \
                __func__,                                                      \
                ##__VA_ARGS__);                                                \
            fflush(stderr);                                                    \
        }                                                                      \
        if ((LVL) == LOG_FATAL) {                                              \
            exit(EXIT_FAILURE);                                                \
        }                                                                      \
    } while (0)

/*---------------------------------------------------------------------------
 *  Global service state (kept minimal)
 *---------------------------------------------------------------------------*/
static volatile sig_atomic_t gb_shutdown_requested = 0;

typedef struct {
    PGconn *db;
    void   *zmq_ctx;
    void   *zmq_sub;            /* SUB socket: incoming domain events      */
    void   *zmq_pub;            /* PUB socket: outgoing domain events      */
    config_t cfg;
} app_ctx_t;

static app_ctx_t g_app = {0};

/*---------------------------------------------------------------------------
 *  Forward declarations
 *---------------------------------------------------------------------------*/
static void  print_usage(const char *prog);
static bool  load_config(const char *path, config_t *dst);
static bool  init_database(app_ctx_t *ctx);
static bool  init_message_bus(app_ctx_t *ctx);
static bool  run_service(app_ctx_t *ctx);
static void  graceful_shutdown(app_ctx_t *ctx);

/*---------------------------------------------------------------------------
 *  Signal handling
 *---------------------------------------------------------------------------*/
static void on_signal(int sig)
{
    (void)sig;
    gb_shutdown_requested = 1;
}

/*---------------------------------------------------------------------------
 *  Mock domain model interfaces (real implementation lives elsewhere)
 *  Here we only declare the functions to avoid missing-symbol errors when
 *  linking this single compilation unit in isolation from the rest of the
 *  Clean Architecture layers used by the course.
 *---------------------------------------------------------------------------*/
typedef struct {
    char *topic;    /* e.g., "financial-aid.aid-requested"                 */
    char *payload;  /* UTF-8 JSON string                                  */
} bus_msg_t;

/* Domain-layer hook: processes incoming messages */
extern bool aid_disbursement_handle(const bus_msg_t *in,
                                    PGconn            *db,
                                    void              *bus_pub_socket,
                                    int                enable_saga,
                                    char             **err_out);

/*---------------------------------------------------------------------------
 *  Main
 *---------------------------------------------------------------------------*/
int main(int argc, char **argv)
{
    const char *cfg_path = "financial_aid.conf.json";

    /*----------------------------------------------------------
     * Parse command-line options
     *----------------------------------------------------------*/
    int opt;
    while ((opt = getopt(argc, argv, "c:h")) != -1) {
        switch (opt) {
        case 'c':
            cfg_path = optarg;
            break;
        case 'h':
        default:
            print_usage(argv[0]);
            return EXIT_SUCCESS;
        }
    }

    /*----------------------------------------------------------
     * Load configuration
     *----------------------------------------------------------*/
    if (!load_config(cfg_path, &g_app.cfg)) {
        LOG(LOG_FATAL, "Unable to load configuration.");
    }
    g_log_level = g_app.cfg.log_level;

    /*----------------------------------------------------------
     * Install signal handlers for graceful shutdown
     *----------------------------------------------------------*/
    struct sigaction sa = { .sa_handler = on_signal };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    /*----------------------------------------------------------
     * Initialize infrastructure components
     *----------------------------------------------------------*/
    if (!init_database(&g_app) || !init_message_bus(&g_app)) {
        LOG(LOG_FATAL, "Initialization failure, terminating.");
    }

    /*----------------------------------------------------------
     * Run main service loop
     *----------------------------------------------------------*/
    bool ok = run_service(&g_app);

    /*----------------------------------------------------------
     * Clean exit
     *----------------------------------------------------------*/
    graceful_shutdown(&g_app);
    return ok ? EXIT_SUCCESS : EXIT_FAILURE;
}

/*---------------------------------------------------------------------------
 *  Print CLI usage
 *---------------------------------------------------------------------------*/
static void print_usage(const char *prog)
{
    printf("Usage: %s [-c config.json]\n", prog);
    puts("Options:");
    puts("  -c <file>   Path to configuration JSON");
    puts("  -h          Show this help message");
}

/*---------------------------------------------------------------------------
 *  Configuration loader
 *---------------------------------------------------------------------------*/
static bool load_config(const char *path, config_t *dst)
{
    json_error_t jerr;
    json_t *root = json_load_file(path, 0, &jerr);
    if (!root) {
        LOG(LOG_ERROR, "Config parse error (%s:%d): %s", jerr.source,
            jerr.line, jerr.text);
        return false;
    }

    /* Helper macro for safe-fetch */
#define J_GET_STR(KEY, TARGET)                                                 \
    do {                                                                       \
        json_t *_tmp = json_object_get(root, KEY);                             \
        if (!json_is_string(_tmp)) {                                           \
            LOG(LOG_ERROR, "Config key '%s' missing or not a string", KEY);    \
            json_decref(root);                                                 \
            return false;                                                      \
        }                                                                      \
        strncpy((TARGET), json_string_value(_tmp), sizeof(TARGET) - 1);        \
    } while (0)

#define J_GET_INT(KEY, TARGET)                                                 \
    do {                                                                       \
        json_t *_tmp = json_object_get(root, KEY);                             \
        if (!json_is_integer(_tmp)) {                                          \
            LOG(LOG_ERROR, "Config key '%s' missing or not an integer", KEY);  \
            json_decref(root);                                                 \
            return false;                                                      \
        }                                                                      \
        (TARGET) = (int)json_integer_value(_tmp);                              \
    } while (0)

    memset(dst, 0, sizeof(*dst));
    J_GET_STR("db_uri",        dst->db_uri);
    J_GET_STR("bus_endpoint",  dst->bus_endpoint);
    J_GET_INT("demo_mode",     dst->demo_mode);
    J_GET_INT("enable_saga",   dst->enable_saga);
    J_GET_INT("log_level",     dst->log_level);

#undef J_GET_STR
#undef J_GET_INT
    json_decref(root);
    return true;
}

/*---------------------------------------------------------------------------
 *  Database
 *---------------------------------------------------------------------------*/
static bool init_database(app_ctx_t *ctx)
{
    LOG(LOG_INFO, "Connecting to PostgreSQL: %s", ctx->cfg.db_uri);
    ctx->db = PQconnectdb(ctx->cfg.db_uri);

    if (PQstatus(ctx->db) != CONNECTION_OK) {
        LOG(LOG_ERROR, "DB connection failed: %s", PQerrorMessage(ctx->db));
        return false;
    }
    LOG(LOG_INFO, "Database connection established.");
    return true;
}

/*---------------------------------------------------------------------------
 *  Message bus
 *---------------------------------------------------------------------------*/
static bool init_message_bus(app_ctx_t *ctx)
{
    ctx->zmq_ctx = zmq_ctx_new();
    if (!ctx->zmq_ctx) {
        LOG(LOG_ERROR, "ØMQ context creation failed.");
        return false;
    }

    /* PUB socket for outgoing events */
    ctx->zmq_pub = zmq_socket(ctx->zmq_ctx, ZMQ_PUB);
    if (!ctx->zmq_pub) {
        LOG(LOG_ERROR, "Unable to create PUB socket: %s", zmq_strerror(errno));
        return false;
    }

    /* SUB socket for incoming events */
    ctx->zmq_sub = zmq_socket(ctx->zmq_ctx, ZMQ_SUB);
    if (!ctx->zmq_sub) {
        LOG(LOG_ERROR, "Unable to create SUB socket: %s", zmq_strerror(errno));
        return false;
    }

    if (zmq_bind(ctx->zmq_pub, ctx->cfg.bus_endpoint) != 0) {
        LOG(LOG_ERROR, "PUB bind failed: %s", zmq_strerror(errno));
        return false;
    }

    if (zmq_connect(ctx->zmq_sub, ctx->cfg.bus_endpoint) != 0) {
        LOG(LOG_ERROR, "SUB connect failed: %s", zmq_strerror(errno));
        return false;
    }

    /* Subscribe to Financial-Aid topics only */
    if (zmq_setsockopt(ctx->zmq_sub, ZMQ_SUBSCRIBE,
                       "financial-aid.", strlen("financial-aid.")) != 0) {
        LOG(LOG_ERROR, "SUBSCRIBE failed: %s", zmq_strerror(errno));
        return false;
    }

    LOG(LOG_INFO, "Message bus ready at %s", ctx->cfg.bus_endpoint);
    return true;
}

/*---------------------------------------------------------------------------
 *  Dispatch thread – optional, unused in this simple file-scope example.
 *---------------------------------------------------------------------------*/
typedef struct {
    app_ctx_t *app;
    thrd_t     tid;
} worker_t;

/*---------------------------------------------------------------------------
 *  Main service loop
 *---------------------------------------------------------------------------*/
static bool run_service(app_ctx_t *ctx)
{
    LOG(LOG_INFO, "Financial-Aid Service started. (PID=%d)", getpid());

    while (!gb_shutdown_requested) {
        /*------------------------------------------------------------------
         * Poll incoming domain events (non-blocking)
         *------------------------------------------------------------------*/
        zmq_pollitem_t items[] = {
            { ctx->zmq_sub, 0, ZMQ_POLLIN, 0 },
        };

        int rc = zmq_poll(items, 1, 250); /* 250ms heartbeat */
        if (rc < 0 && errno == EINTR) {
            continue; /* Interrupted by signal */
        } else if (rc < 0) {
            LOG(LOG_ERROR, "zmq_poll: %s", zmq_strerror(errno));
            break;
        }

        /*------------------------------------------------------------------
         * Message available
         *------------------------------------------------------------------*/
        if (items[0].revents & ZMQ_POLLIN) {
            char *topic    = NULL;
            char *payload  = NULL;

            zmq_msg_t msg_topic, msg_payload;
            zmq_msg_init(&msg_topic);
            zmq_msg_init(&msg_payload);

            if (zmq_msg_recv(&msg_topic, ctx->zmq_sub, 0) < 0 ||
                zmq_msg_recv(&msg_payload, ctx->zmq_sub, 0) < 0) {
                LOG(LOG_ERROR, "zmq_msg_recv failed: %s", zmq_strerror(errno));
                zmq_msg_close(&msg_topic);
                zmq_msg_close(&msg_payload);
                continue;
            }

            /* Copy message frames into null-terminated buffers */
            topic = strndup((const char*)zmq_msg_data(&msg_topic),
                            zmq_msg_size(&msg_topic));
            payload = strndup((const char*)zmq_msg_data(&msg_payload),
                              zmq_msg_size(&msg_payload));

            zmq_msg_close(&msg_topic);
            zmq_msg_close(&msg_payload);

            if (!topic || !payload) {
                LOG(LOG_ERROR, "Memory allocation failed while copying message");
                free(topic);
                free(payload);
                continue;
            }

            bus_msg_t bus_msg = { .topic = topic, .payload = payload };
            char *err_txt = NULL;

            /*--------------------------------------------------------------
             * Delegate to use-case interactor
             *--------------------------------------------------------------*/
            bool ok = aid_disbursement_handle(&bus_msg,
                                              ctx->db,
                                              ctx->zmq_pub,
                                              ctx->cfg.enable_saga,
                                              &err_txt);
            if (!ok) {
                LOG(LOG_ERROR, "Message handling failure: %s", err_txt ?: "unknown");
                free(err_txt);
            }

            free(topic);
            free(payload);
        } /* if IN */

        /*------------------------------------------------------------------
         * Perform other periodic tasks (metrics heartbeat, demo failures)
         *------------------------------------------------------------------*/
        if (ctx->cfg.demo_mode) {
            static int counter = 0;
            if (++counter % 40 == 0) {  /* every ~10 seconds */
                LOG(LOG_WARN, "Demo-mode fault injection: simulating failure.");
                /* In demo mode we can publish a compensating event to trigger
                 * Saga rollbacks so that students have something to debug.  */
                const char *demo_topic   = "financial-aid.demo.failure-injected";
                const char *demo_payload = "{ \"reason\": \"simulated\" }";
                zmq_send(ctx->zmq_pub, demo_topic,   strlen(demo_topic),   ZMQ_SNDMORE);
                zmq_send(ctx->zmq_pub, demo_payload, strlen(demo_payload), 0);
            }
        }
    }

    LOG(LOG_INFO, "Shutdown requested. Leaving run loop.");
    return true;
}

/*---------------------------------------------------------------------------
 *  Cleanup
 *---------------------------------------------------------------------------*/
static void graceful_shutdown(app_ctx_t *ctx)
{
    LOG(LOG_INFO, "Graceful shutdown initiated.");

    if (ctx->zmq_sub) {
        zmq_close(ctx->zmq_sub);
        ctx->zmq_sub = NULL;
    }
    if (ctx->zmq_pub) {
        zmq_close(ctx->zmq_pub);
        ctx->zmq_pub = NULL;
    }
    if (ctx->zmq_ctx) {
        zmq_ctx_shutdown(ctx->zmq_ctx);
        zmq_ctx_term(ctx->zmq_ctx);
        ctx->zmq_ctx = NULL;
    }
    if (ctx->db) {
        PQfinish(ctx->db);
        ctx->db = NULL;
    }

    LOG(LOG_INFO, "Financial-Aid Service stopped.");
}

/* End of file */