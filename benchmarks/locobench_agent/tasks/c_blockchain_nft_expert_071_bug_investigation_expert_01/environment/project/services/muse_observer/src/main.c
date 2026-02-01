```c
/*
 * HoloCanvas — Muse Observer Service
 * ----------------------------------
 * File: services/muse_observer/src/main.c
 *
 * Description:
 *   The Muse-Observer is an event-driven micro-service that listens to the
 *   HoloCanvas Kafka mesh for artistic triggers (likes, oracle feeds, DAO
 *   votes, etc.).  On each relevant event the observer selects a matching
 *   “strategy plug-in” (shared library placed in plugin_dir) which mutates
 *   the NFT’s media/metadata.  The resulting “evolution recipe” is forwarded
 *   to the Mint-Factory service through gRPC for on-chain execution.
 *
 * Build:
 *   cc -std=c11 -Wall -Wextra -Werror \
 *      -o muse_observer main.c -lrdkafka -ldl -ljansson -lpthread
 *
 *   (grpc is stubbed out here; link with -lgrpc++ when a real client stub is
 *    available.)
 *
 * Copyright:
 *   © 2024 HoloCanvas Contributors.  Licensed under the Apache-2.0 license.
 */

#define _GNU_SOURCE
#include <errno.h>
#include <getopt.h>
#include <jansson.h>
#include <rdkafka/rdkafka.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <unistd.h>
#include <dlfcn.h>

/* ------------------------------------------------------------------------- */
/* Constants & Macros                                                        */
/* ------------------------------------------------------------------------- */
#define MUSE_VERSION      "1.0.0"
#define DEFAULT_BROKERS   "localhost:9092"
#define DEFAULT_TOPIC     "holo.events"
#define DEFAULT_PLUGDIR   "/usr/local/lib/holo/plugins"
#define DEFAULT_GRPC_TGT  "localhost:50051"
#define MAX_PLUGIN_NAME   128
#define POLL_TIMEOUT_MS   500

#define LOG(level, fmt, ...) \
    syslog(level, "[muse] " fmt, ##__VA_ARGS__)

#define DIE(fmt, ...)                        \
    do {                                     \
        LOG(LOG_ERR, fmt, ##__VA_ARGS__);    \
        exit(EXIT_FAILURE);                  \
    } while (0)

/* ------------------------------------------------------------------------- */
/* Global State                                                              */
/* ------------------------------------------------------------------------- */
static volatile sig_atomic_t g_terminate = 0;

/* ------------------------------------------------------------------------- */
/* Configuration Structure                                                   */
/* ------------------------------------------------------------------------- */
typedef struct {
    char *kafka_brokers;
    char *topic;
    char *plugin_dir;
    char *grpc_target;
    int   verbosity;
} muse_cfg_t;

/* ------------------------------------------------------------------------- */
/* Strategy Plug-in Interface                                                */
/* ------------------------------------------------------------------------- */
/* Each strategy plug-in must expose this symbol. */
typedef int (*strategy_fn)(const char *event_json,
                           char      **out_recipe_json);
/* Optionally expose this (for init). */
typedef int (*strategy_init_fn)(void);
typedef void (*strategy_fini_fn)(void);

typedef struct {
    char          name[MAX_PLUGIN_NAME];
    void         *dl_handle;
    strategy_fn   run;
    strategy_fini_fn fini;
} plugin_t;

/* ------------------------------------------------------------------------- */
/* Signal Handling                                                           */
/* ------------------------------------------------------------------------- */
static void muse_on_signal(int signo) {
    (void)signo;
    g_terminate = 1;
}

/* ------------------------------------------------------------------------- */
/* Utility                                                                   */
/* ------------------------------------------------------------------------- */
static char *dup_or_default(const char *src, const char *def) {
    return strdup(src && *src ? src : def);
}

/* ------------------------------------------------------------------------- */
/* Command-line / Environment Parsing                                        */
/* ------------------------------------------------------------------------- */
static void muse_parse_cli(int argc, char **argv, muse_cfg_t *cfg) {
    static struct option long_opts[] = {
        { "brokers",     required_argument, 0, 'b' },
        { "topic",       required_argument, 0, 't' },
        { "plugin-dir",  required_argument, 0, 'p' },
        { "grpc",        required_argument, 0, 'g' },
        { "verbose",     no_argument,       0, 'v' },
        { "version",     no_argument,       0, 'V' },
        { "help",        no_argument,       0, 'h' },
        { 0,             0,                 0,  0  }
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "b:t:p:g:vVh", long_opts, NULL)) != -1) {
        switch (opt) {
        case 'b': free(cfg->kafka_brokers); cfg->kafka_brokers = strdup(optarg); break;
        case 't': free(cfg->topic);         cfg->topic        = strdup(optarg);  break;
        case 'p': free(cfg->plugin_dir);    cfg->plugin_dir   = strdup(optarg);  break;
        case 'g': free(cfg->grpc_target);   cfg->grpc_target  = strdup(optarg);  break;
        case 'v': cfg->verbosity++;                                           break;
        case 'V':
            printf("Muse Observer v%s\n", MUSE_VERSION);
            exit(EXIT_SUCCESS);
        case 'h':
        default:
            printf("Usage: %s [options]\n"
                   "  -b, --brokers    Kafka bootstrap servers (default: %s)\n"
                   "  -t, --topic      Kafka topic to consume   (default: %s)\n"
                   "  -p, --plugin-dir Directory containing strategy plug-ins\n"
                   "                   (default: %s)\n"
                   "  -g, --grpc       Mint-Factory gRPC target (default: %s)\n"
                   "  -v, --verbose    Increase verbosity (can repeat)\n"
                   "  -V, --version    Show version\n"
                   "  -h, --help       Show this help message\n",
                   argv[0], DEFAULT_BROKERS, DEFAULT_TOPIC,
                   DEFAULT_PLUGDIR, DEFAULT_GRPC_TGT);
            exit(opt == 'h' ? EXIT_SUCCESS : EXIT_FAILURE);
        }
    }
}

/* ------------------------------------------------------------------------- */
/* Plug-in Loader                                                            */
/* ------------------------------------------------------------------------- */
static int plugin_open(plugin_t *plg, const char *plugin_dir,
                       const char *strategy_name)
{
    snprintf(plg->name, sizeof(plg->name), "%s", strategy_name);

    char *so_path;
    if (asprintf(&so_path, "%s/lib%s.so", plugin_dir, strategy_name) < 0)
        return -1;

    plg->dl_handle = dlopen(so_path, RTLD_NOW | RTLD_LOCAL);
    free(so_path);

    if (!plg->dl_handle) {
        LOG(LOG_ERR, "dlopen failed for strategy `%s`: %s",
            strategy_name, dlerror());
        return -1;
    }

    /* mandatory */
    plg->run = (strategy_fn)dlsym(plg->dl_handle, "muse_strategy_run");
    if (!plg->run) {
        LOG(LOG_ERR, "Plug-in `%s` missing muse_strategy_run symbol", strategy_name);
        dlclose(plg->dl_handle);
        return -1;
    }

    /* optional init/fini */
    strategy_init_fn init_fn = (strategy_init_fn)dlsym(plg->dl_handle,
                                                       "muse_strategy_init");
    if (init_fn && init_fn() != 0) {
        LOG(LOG_ERR, "Plug-in `%s` failed to initialize", strategy_name);
        dlclose(plg->dl_handle);
        return -1;
    }

    plg->fini = (strategy_fini_fn)dlsym(plg->dl_handle, "muse_strategy_fini");

    LOG(LOG_INFO, "Loaded strategy `%s`", strategy_name);
    return 0;
}

static void plugin_close(plugin_t *plg) {
    if (!plg || !plg->dl_handle) return;
    if (plg->fini) plg->fini();
    dlclose(plg->dl_handle);
    plg->dl_handle = NULL;
}

/* ------------------------------------------------------------------------- */
/* gRPC Mint-Factory Client (stub)                                           */
/* ------------------------------------------------------------------------- */
static int grpc_send_evolution(const char *grpc_target,
                               const char *recipe_json)
{
    /* Placeholder implementation.  In a production build this would use
     * generated gRPC C bindings to call something like
     *   MintFactory::EvolveNFT(EvolutionRecipe)
     */
    (void)grpc_target; /* suppress unused warning */
    LOG(LOG_INFO, "Stub gRPC call sent to Mint-Factory: %s", recipe_json);
    return 0;
}

/* ------------------------------------------------------------------------- */
/* Kafka Consumer                                                            */
/* ------------------------------------------------------------------------- */
static rd_kafka_t *kafka_init_consumer(const muse_cfg_t *cfg)
{
    char errstr[512];

    rd_kafka_conf_t *conf = rd_kafka_conf_new();
    if (rd_kafka_conf_set(conf, "bootstrap.servers",
                          cfg->kafka_brokers, errstr, sizeof(errstr)) !=
        RD_KAFKA_CONF_OK)
        DIE("Kafka conf set failed: %s", errstr);

    /* Auto commit offsets every second */
    if (rd_kafka_conf_set(conf, "enable.auto.commit",
                          "true", errstr, sizeof(errstr)) != RD_KAFKA_CONF_OK)
        DIE("Kafka conf set failed: %s", errstr);

    rd_kafka_t *rk = rd_kafka_new(RD_KAFKA_CONSUMER, conf,
                                  errstr, sizeof(errstr));
    if (!rk)
        DIE("Failed to create Kafka consumer: %s", errstr);

    rd_kafka_poll_set_consumer(rk);

    rd_kafka_topic_partition_list_t *topics =
        rd_kafka_topic_partition_list_new(1);
    rd_kafka_topic_partition_list_add(topics, cfg->topic, -1);

    if (rd_kafka_subscribe(rk, topics))
        DIE("Failed to subscribe to %s", cfg->topic);

    rd_kafka_topic_partition_list_destroy(topics);
    LOG(LOG_INFO, "Kafka consumer ready; brokers=%s, topic=%s",
        cfg->kafka_brokers, cfg->topic);
    return rk;
}

/* ------------------------------------------------------------------------- */
/* Event Dispatcher                                                          */
/* ------------------------------------------------------------------------- */
static int dispatch_event(const muse_cfg_t *cfg,
                          const char       *event_json,
                          plugin_t         *cache)
{
    /* ---------------------------------
     * Strategy selection heuristics:
     *   Input JSON must contain key
     *     "strategy": "rainbow_shift"
     * --------------------------------- */
    json_error_t jerr;
    json_t *root = json_loads(event_json, 0, &jerr);
    if (!root) {
        LOG(LOG_WARNING, "Invalid JSON payload: %s", jerr.text);
        return -1;
    }

    const char *strategy = json_string_value(json_object_get(root, "strategy"));
    if (!strategy) {
        LOG(LOG_INFO, "No strategy specified; ignoring event");
        json_decref(root);
        return 0;
    }

    /* Caching: if last loaded plugin matches, reuse it */
    plugin_t plg  = {0};
    plugin_t *use = &plg;

    if (cache && strcmp(cache->name, strategy) == 0 && cache->dl_handle) {
        use = cache;
    } else {
        /* unload previous */
        if (cache && cache->dl_handle)
            plugin_close(cache);

        /* load new */
        if (plugin_open(&plg, cfg->plugin_dir, strategy) != 0) {
            json_decref(root);
            return -1;
        }
    }

    /* Call strategy */
    char *recipe_json = NULL;
    int rc = use->run(event_json, &recipe_json);
    if (rc != 0 || !recipe_json) {
        LOG(LOG_ERR, "Strategy `%s` failed (rc=%d)", strategy, rc);
        json_decref(root);
        if (use == &plg) plugin_close(&plg);
        return -1;
    }

    /* Send evolution to Mint-Factory */
    rc = grpc_send_evolution(cfg->grpc_target, recipe_json);
    free(recipe_json);

    /* Cache plugin for reuse */
    if (use == &plg && rc == 0 && cache) {
        *cache = plg; /* shallow copy of handles */
    } else if (use == &plg) {
        plugin_close(&plg);
    }

    json_decref(root);
    return rc;
}

/* ------------------------------------------------------------------------- */
/* Main Event Loop                                                           */
/* ------------------------------------------------------------------------- */
static int muse_event_loop(const muse_cfg_t *cfg)
{
    rd_kafka_t *consumer = kafka_init_consumer(cfg);
    int exit_code = EXIT_SUCCESS;
    plugin_t cache = {0}; /* last-used plugin cache */

    while (!g_terminate) {
        rd_kafka_message_t *rkmsg = rd_kafka_consumer_poll(consumer,
                                                           POLL_TIMEOUT_MS);
        if (!rkmsg)
            continue; /* timeout */

        if (rkmsg->err) {
            if (rkmsg->err == RD_KAFKA_RESP_ERR__PARTITION_EOF) {
                /* not a real error */
            } else {
                LOG(LOG_ERR, "Kafka error: %s", rd_kafka_message_errstr(rkmsg));
            }
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        /* The payload is not zero-terminated.  Allocate +1 char. */
        char *payload = malloc(rkmsg->len + 1);
        if (!payload) DIE("malloc failed");
        memcpy(payload, rkmsg->payload, rkmsg->len);
        payload[rkmsg->len] = '\0';

        if (dispatch_event(cfg, payload, &cache) != 0) {
            LOG(LOG_WARNING, "Event processing failed");
            /* keep running */
        }

        free(payload);
        rd_kafka_message_destroy(rkmsg);
    }

    LOG(LOG_INFO, "Shutting down…");

    /* Graceful teardown */
    if (cache.dl_handle)
        plugin_close(&cache);

    rd_kafka_consumer_close(consumer);
    rd_kafka_destroy(consumer);
    rd_kafka_wait_destroyed(2000);

    return exit_code;
}

/* ------------------------------------------------------------------------- */
/* Entry Point                                                               */
/* ------------------------------------------------------------------------- */
int main(int argc, char **argv)
{
    openlog("holo-muse", LOG_PID | LOG_CONS, LOG_DAEMON);

    muse_cfg_t cfg = {
        .kafka_brokers = dup_or_default(getenv("MUSE_KAFKA_BROKERS"),
                                        DEFAULT_BROKERS),
        .topic         = dup_or_default(getenv("MUSE_TOPIC"),      DEFAULT_TOPIC),
        .plugin_dir    = dup_or_default(getenv("MUSE_PLUGIN_DIR"), DEFAULT_PLUGDIR),
        .grpc_target   = dup_or_default(getenv("MUSE_GRPC_TARGET"),DEFAULT_GRPC_TGT),
        .verbosity     = 0
    };

    muse_parse_cli(argc, argv, &cfg);

    /* Adjust syslog verbosity */
    setlogmask(LOG_UPTO(cfg.verbosity ? LOG_DEBUG : LOG_INFO));

    LOG(LOG_INFO, "Muse Observer v%s starting…", MUSE_VERSION);

    /* Install signals */
    struct sigaction sa = {
        .sa_handler = muse_on_signal,
        .sa_flags   = 0
    };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    int rc = muse_event_loop(&cfg);

    free(cfg.kafka_brokers);
    free(cfg.topic);
    free(cfg.plugin_dir);
    free(cfg.grpc_target);

    closelog();
    return rc;
}
```