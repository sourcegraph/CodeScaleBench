/*
 * LexiLearn Orchestrator – main.c
 *
 * This is the entry-point of the LexiLearn MVC Orchestrator.  It is responsible
 * for
 *   • Loading runtime configuration
 *   • Initialising application-wide subsystems (logger, model registry, etc.)
 *   • Wiring up Observer hooks
 *   • Spawning background schedulers (model-drift detection, retraining)
 *   • Executing the high-level controller pipeline
 *   • Graceful shutdown on POSIX signals
 *
 * The file is self-contained so that it can be compiled standalone for demo /
 * PoC purposes.  In the real project these helper structs live in dedicated
 * translation units.
 */

#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* ────────────────────────────────────────────────────────────────────────── */
/*                               Logger                                      */
/* ────────────────────────────────────────────────────────────────────────── */

typedef enum
{
    LOG_DEBUG = 0,
    LOG_INFO,
    LOG_WARN,
    LOG_ERROR
} LogLevel;

static const char *LOG_LEVEL_STR[] = { "DEBUG", "INFO", "WARN", "ERROR" };

typedef struct
{
    LogLevel        level;
    FILE           *sink;
    pthread_mutex_t lock;
} Logger;

static Logger g_logger;

static void logger_init(LogLevel level, const char *file_path)
{
    g_logger.level = level;
    g_logger.sink  = file_path ? fopen(file_path, "a") : stderr;
    if (!g_logger.sink)
    {
        /* Fallback to stderr if file cannot be opened */
        g_logger.sink = stderr;
    }
    pthread_mutex_init(&g_logger.lock, NULL);
}

static void logger_shutdown(void)
{
    if (g_logger.sink && g_logger.sink != stderr && g_logger.sink != stdout)
        fclose(g_logger.sink);
    pthread_mutex_destroy(&g_logger.lock);
}

__attribute__((format(printf, 3, 4))) static void logger_log(LogLevel lvl,
                                                             const char *file,
                                                             const char *fmt,
                                                             ...)
{
    if (lvl < g_logger.level)
        return;

    time_t     now = time(NULL);
    struct tm  tm_now;
    char       ts[32];

    localtime_r(&now, &tm_now);
    strftime(ts, sizeof ts, "%Y-%m-%d %H:%M:%S", &tm_now);

    pthread_mutex_lock(&g_logger.lock);

    fprintf(g_logger.sink, "%s [%s] (%s) ", ts, LOG_LEVEL_STR[lvl], file);

    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_logger.sink, fmt, ap);
    va_end(ap);

    fprintf(g_logger.sink, "\n");
    fflush(g_logger.sink);

    pthread_mutex_unlock(&g_logger.lock);
}

#define LOG_DEBUG(fmt, ...) logger_log(LOG_DEBUG, __FILE__, fmt, ##__VA_ARGS__)
#define LOG_INFO(fmt, ...)  logger_log(LOG_INFO, __FILE__, fmt, ##__VA_ARGS__)
#define LOG_WARN(fmt, ...)  logger_log(LOG_WARN, __FILE__, fmt, ##__VA_ARGS__)
#define LOG_ERROR(fmt, ...) logger_log(LOG_ERROR, __FILE__, fmt, ##__VA_ARGS__)

/* ────────────────────────────────────────────────────────────────────────── */
/*                             Configuration                                 */
/* ────────────────────────────────────────────────────────────────────────── */

typedef struct
{
    char lms_api_endpoint[256];
    char feature_store_path[256];
    int  retrain_interval_sec;
    char registry_path[256];
    char strategy[64];
} Config;

static bool parse_config_line(const char *line, char *key, size_t key_sz,
                              char *val, size_t val_sz)
{
    const char *eq = strchr(line, '=');
    if (!eq)
        return false;
    size_t klen = (size_t)(eq - line);
    size_t vlen = strlen(eq + 1);

    if (klen >= key_sz || vlen >= val_sz)
        return false;

    strncpy(key, line, klen);
    key[klen] = '\0';
    strncpy(val, eq + 1, vlen);
    /* trim trailing newline */
    if (val[vlen - 1] == '\n')
        val[vlen - 1] = '\0';
    return true;
}

static bool load_config(const char *path, Config *cfg)
{
    FILE *fp = fopen(path, "r");
    if (!fp)
    {
        LOG_ERROR("Failed to open config file '%s': %s", path, strerror(errno));
        return false;
    }

    /* Set sensible defaults */
    memset(cfg, 0, sizeof *cfg);
    strcpy(cfg->lms_api_endpoint, "https://api.example.edu/lms");
    strcpy(cfg->feature_store_path, "/var/lib/lexilearn/features");
    strcpy(cfg->registry_path, "/var/lib/lexilearn/registry");
    cfg->retrain_interval_sec = 3600;
    strcpy(cfg->strategy, "transformer");

    char  line[512];
    char  key[128], val[384];
    while (fgets(line, sizeof line, fp))
    {
        if (line[0] == '#' || line[0] == '\n')
            continue;
        if (!parse_config_line(line, key, sizeof key, val, sizeof val))
            continue;

        if (strcmp(key, "lms_api_endpoint") == 0)
            strncpy(cfg->lms_api_endpoint, val, sizeof cfg->lms_api_endpoint);
        else if (strcmp(key, "feature_store_path") == 0)
            strncpy(cfg->feature_store_path, val,
                    sizeof cfg->feature_store_path);
        else if (strcmp(key, "retrain_interval_sec") == 0)
            cfg->retrain_interval_sec = atoi(val);
        else if (strcmp(key, "registry_path") == 0)
            strncpy(cfg->registry_path, val, sizeof cfg->registry_path);
        else if (strcmp(key, "strategy") == 0)
            strncpy(cfg->strategy, val, sizeof cfg->strategy);
    }

    fclose(fp);
    return true;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                           Model Registry                                  */
/* ────────────────────────────────────────────────────────────────────────── */

typedef struct
{
    char   active_version[64];
    size_t total_versions;
    pthread_mutex_t lock;
} ModelRegistry;

static bool registry_init(ModelRegistry *reg, const char *path)
{
    (void)path; /* Persisted registry omitted in this self-contained example */
    memset(reg, 0, sizeof *reg);
    pthread_mutex_init(&reg->lock, NULL);
    strcpy(reg->active_version, "none");
    return true;
}

static void registry_shutdown(ModelRegistry *reg)
{
    pthread_mutex_destroy(&reg->lock);
}

static void registry_register(ModelRegistry *reg, const char *version_tag)
{
    pthread_mutex_lock(&reg->lock);
    strncpy(reg->active_version, version_tag, sizeof reg->active_version);
    ++reg->total_versions;
    pthread_mutex_unlock(&reg->lock);

    LOG_INFO("Registered new model version: %s (total=%zu)", version_tag,
             reg->total_versions);
}

static void registry_get_active(ModelRegistry *reg, char *buf, size_t sz)
{
    pthread_mutex_lock(&reg->lock);
    strncpy(buf, reg->active_version, sz);
    pthread_mutex_unlock(&reg->lock);
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                          Observer Framework                               */
/* ────────────────────────────────────────────────────────────────────────── */

typedef enum
{
    EVT_MODEL_DRIFT_DETECTED = 0,
    EVT_RETRAIN_COMPLETE,
    EVT_SHUTDOWN
} EventType;

typedef void (*observer_cb)(EventType evt, void *user_data);

#define MAX_OBSERVERS 32
typedef struct
{
    observer_cb  cb;
    void        *user_data;
} Observer;

static Observer g_observers[MAX_OBSERVERS];
static size_t   g_observer_cnt = 0;

static bool observer_register(observer_cb cb, void *user_data)
{
    if (g_observer_cnt >= MAX_OBSERVERS)
        return false;
    g_observers[g_observer_cnt++] = (Observer){ .cb = cb,
                                                .user_data = user_data };
    return true;
}

static void observer_notify(EventType evt)
{
    for (size_t i = 0; i < g_observer_cnt; ++i)
        g_observers[i].cb(evt, g_observers[i].user_data);
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                          Strategy Pattern                                 */
/* ────────────────────────────────────────────────────────────────────────── */

typedef struct
{
    const char *name;
    /* placeholder for strategy-specific state */
    int (*train)(const Config *cfg, const char *dataset_path,
                 char *out_version, size_t out_sz);
    int (*inference)(const char *input, char *output, size_t out_sz);
} ModelStrategy;

/* transformer strategy */
static int transformer_train(const Config *cfg, const char *dataset_path,
                             char *out_version, size_t out_sz)
{
    (void)cfg;
    (void)dataset_path;
    /* In real life we would call Python or ONNX Runtime; here we simulate. */
    snprintf(out_version, out_sz, "transformer-%ld", time(NULL));
    sleep(2); /* pretend it takes some time */
    LOG_INFO("[Strategy:transformer] training complete, version=%s",
             out_version);
    return 0;
}

static int transformer_inference(const char *input, char *output, size_t sz)
{
    snprintf(output, sz, "[transformer] summary of '%s'", input);
    return 0;
}

/* n-gram strategy – simplified */
static int ngram_train(const Config *cfg, const char *dataset_path,
                       char *out_version, size_t out_sz)
{
    (void)cfg;
    (void)dataset_path;
    snprintf(out_version, out_sz, "ngram-%ld", time(NULL));
    sleep(1);
    LOG_INFO("[Strategy:ngram] training complete, version=%s", out_version);
    return 0;
}

static int ngram_inference(const char *input, char *output, size_t sz)
{
    snprintf(output, sz, "[ngram] summary of '%s'", input);
    return 0;
}

static const ModelStrategy STRATEGIES[] = {
    { .name = "transformer",
      .train = transformer_train,
      .inference = transformer_inference },
    { .name = "ngram",
      .train = ngram_train,
      .inference = ngram_inference },
};

static const ModelStrategy *strategy_from_name(const char *name)
{
    for (size_t i = 0; i < sizeof STRATEGIES / sizeof STRATEGIES[0]; ++i)
        if (strcmp(name, STRATEGIES[i].name) == 0)
            return &STRATEGIES[i];
    return NULL;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                          Controller – Pipeline                            */
/* ────────────────────────────────────────────────────────────────────────── */

typedef struct
{
    const Config          *cfg;
    ModelRegistry         *registry;
    const ModelStrategy   *strategy;
} PipelineCtx;

static bool ingest_data(const Config *cfg, char *dataset_path, size_t sz)
{
    /* Pretend to download data from LMS API */
    (void)cfg;
    snprintf(dataset_path, sz, "/tmp/lexilearn_dataset_%ld.csv", time(NULL));
    LOG_INFO("Ingested LMS data to %s", dataset_path);
    return true;
}

static bool evaluate_model(const char *version_tag)
{
    (void)version_tag;
    /* placeholder */
    LOG_INFO("Evaluated model %s – metrics within thresholds", version_tag);
    return true;
}

static void *pipeline_run(void *arg)
{
    PipelineCtx *ctx = arg;

    char dataset_path[256];
    if (!ingest_data(ctx->cfg, dataset_path, sizeof dataset_path))
    {
        LOG_ERROR("Data ingestion failed. Aborting pipeline.");
        return NULL;
    }

    char new_version[64];
    if (ctx->strategy->train(ctx->cfg, dataset_path, new_version,
                             sizeof new_version) != 0)
    {
        LOG_ERROR("Training failed.");
        return NULL;
    }

    if (!evaluate_model(new_version))
    {
        LOG_WARN("Model %s fails eval; not promoting.", new_version);
        return NULL;
    }

    registry_register(ctx->registry, new_version);

    observer_notify(EVT_RETRAIN_COMPLETE);
    return NULL;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                      Scheduler / Model-Drift Monitor                      */
/* ────────────────────────────────────────────────────────────────────────── */

typedef struct
{
    const Config  *cfg;
    PipelineCtx   *pipeline;
    pthread_t      thread;
    bool           running;
} Scheduler;

static void *scheduler_loop(void *arg)
{
    Scheduler *sch = arg;
    LOG_INFO("Scheduler started; retrain interval = %d seconds",
             sch->cfg->retrain_interval_sec);

    while (sch->running)
    {
        sleep(sch->cfg->retrain_interval_sec);

        /* Simulate model drift detection */
        bool drift = (rand() % 100) < 30; /* 30% chance */
        if (drift)
        {
            LOG_WARN("Model drift detected!");
            observer_notify(EVT_MODEL_DRIFT_DETECTED);

            pthread_t worker;
            pthread_create(&worker, NULL, pipeline_run, sch->pipeline);
            pthread_detach(worker);
        }
    }
    return NULL;
}

static bool scheduler_start(Scheduler *sch)
{
    sch->running = true;
    if (pthread_create(&sch->thread, NULL, scheduler_loop, sch) != 0)
        return false;
    return true;
}

static void scheduler_stop(Scheduler *sch)
{
    sch->running = false;
    pthread_join(sch->thread, NULL);
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                        Global Shutdown Handling                            */
/* ────────────────────────────────────────────────────────────────────────── */

static volatile sig_atomic_t g_shutdown_requested = 0;

static void sig_handler(int sig)
{
    (void)sig;
    g_shutdown_requested = 1;
    observer_notify(EVT_SHUTDOWN);
}

/* Observer callback to log events */
static void event_logger(EventType evt, void *ud)
{
    (void)ud;
    switch (evt)
    {
        case EVT_MODEL_DRIFT_DETECTED:
            LOG_INFO("[Observer] Model drift detected – pipeline triggered");
            break;
        case EVT_RETRAIN_COMPLETE:
            LOG_INFO("[Observer] Retraining job complete");
            break;
        case EVT_SHUTDOWN:
            LOG_INFO("[Observer] Shutdown signal received");
            break;
        default:
            break;
    }
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                                main                                        */
/* ────────────────────────────────────────────────────────────────────────── */

static void usage(const char *prog)
{
    fprintf(stderr, "Usage: %s [-c config.ini] [-l loglevel]\n", prog);
    fprintf(stderr, "   loglevel: DEBUG, INFO, WARN, ERROR (default INFO)\n");
}

static LogLevel parse_level(const char *s)
{
    if (strcasecmp(s, "DEBUG") == 0)
        return LOG_DEBUG;
    if (strcasecmp(s, "INFO") == 0)
        return LOG_INFO;
    if (strcasecmp(s, "WARN") == 0)
        return LOG_WARN;
    if (strcasecmp(s, "ERROR") == 0)
        return LOG_ERROR;
    return LOG_INFO;
}

int main(int argc, char **argv)
{
    const char *cfg_path  = "lexilearn.ini";
    LogLevel    log_level = LOG_INFO;

    int opt;
    while ((opt = getopt(argc, argv, "c:l:h")) != -1)
    {
        switch (opt)
        {
            case 'c':
                cfg_path = optarg;
                break;
            case 'l':
                log_level = parse_level(optarg);
                break;
            case 'h':
            default:
                usage(argv[0]);
                return EXIT_FAILURE;
        }
    }

    logger_init(log_level, NULL);
    LOG_INFO("LexiLearn Orchestrator starting…");

    /* Register signal handlers for graceful shutdown */
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = sig_handler;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    Config cfg;
    if (!load_config(cfg_path, &cfg))
    {
        LOG_ERROR("Unable to load configuration.");
        logger_shutdown();
        return EXIT_FAILURE;
    }

    const ModelStrategy *strategy = strategy_from_name(cfg.strategy);
    if (!strategy)
    {
        LOG_ERROR("Unknown strategy '%s'", cfg.strategy);
        logger_shutdown();
        return EXIT_FAILURE;
    }
    LOG_INFO("Using strategy: %s", strategy->name);

    ModelRegistry registry;
    if (!registry_init(&registry, cfg.registry_path))
    {
        LOG_ERROR("Failed to initialise model registry.");
        logger_shutdown();
        return EXIT_FAILURE;
    }

    if (!observer_register(event_logger, NULL))
    {
        LOG_WARN("Could not register event logger observer");
    }

    PipelineCtx pipeline_ctx = { .cfg = &cfg,
                                 .registry = &registry,
                                 .strategy = strategy };

    Scheduler scheduler = { .cfg = &cfg, .pipeline = &pipeline_ctx };
    if (!scheduler_start(&scheduler))
    {
        LOG_ERROR("Failed to start scheduler.");
        registry_shutdown(&registry);
        logger_shutdown();
        return EXIT_FAILURE;
    }

    /* Main loop simply waits for shutdown signal */
    while (!g_shutdown_requested)
        pause();

    LOG_INFO("Shutting down…");
    scheduler_stop(&scheduler);
    registry_shutdown(&registry);
    logger_shutdown();
    return EXIT_SUCCESS;
}

/* End of file */