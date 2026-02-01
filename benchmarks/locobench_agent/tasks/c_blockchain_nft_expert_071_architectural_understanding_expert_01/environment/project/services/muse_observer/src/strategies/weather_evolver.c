/*
 * HoloCanvas – Muse Observer Service
 * Strategy: weather_evolver
 *
 * File:    weather_evolver.c
 * Author:  HoloCanvas Core Team
 * License: Apache-2.0
 *
 * Description:
 *   A Strategy-Pattern plug-in that reacts to weather-oracle updates and
 *   evolves NFT artifacts in real-time.  The strategy inspects temperature,
 *   wind-speed, precipitation and sunlight indices delivered through the
 *   Oracle-Bridge micro-service (Kafka topic `oracle.weather.v1`).  When a
 *   configured environmental threshold is crossed, an “EVOLVE” command is
 *   produced to the `artist.evolve.v1` topic so that the Mint-Factory can
 *   re-render affected media layers.
 *
 *   The plug-in is hot-loaded by the Muse-Observer at runtime through a
 *   shared library and advertises its interface via
 *   `muse_strategy_get_ops()`.
 */

#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <time.h>

#include "cjson/cJSON.h" /* https://github.com/DaveGamble/cJSON */
#include "kafka/producer.h" /* Project-local thin wrapper around librdkafka */
#include "muse_strategy.h"  /* Framework-level Strategy interface  */

#define MODULE_NAME            "weather_evolver"
#define DEFAULT_ORACLE_TOPIC   "oracle.weather.v1"
#define DEFAULT_EVOLVER_TOPIC  "artist.evolve.v1"
#define LIB_VERSION            "1.2.4"

/* -------------------------------------------------------------------------- */
/* Logging helpers                                                            */
/* -------------------------------------------------------------------------- */

#define LOG_TAG MODULE_NAME

#define LOG_PRI(pri, fmt, ...)                                                      \
    syslog(pri, "[%s] %s:%d " fmt, LOG_TAG, __func__, __LINE__, ##__VA_ARGS__)

#define LOG_INFO(fmt, ...)  LOG_PRI(LOG_INFO, fmt, ##__VA_ARGS__)
#define LOG_ERR(fmt, ...)   LOG_PRI(LOG_ERR , fmt, ##__VA_ARGS__)
#define LOG_DBG(fmt, ...)   LOG_PRI(LOG_DEBUG, fmt, ##__VA_ARGS__)

/* -------------------------------------------------------------------------- */
/* Local data structures                                                      */
/* -------------------------------------------------------------------------- */

typedef struct
{
    char   *oracle_topic;          /* Kafka topic for oracle updates          */
    char   *evolution_topic;       /* Kafka topic to emit evolve commands     */
    double  temp_high_c;           /* Celsius: if >= trigger high evolution   */
    double  temp_low_c;            /* Celsius: if <= trigger low  evolution   */
    double  wind_speed_high;       /* m/s:    strong wind triggers evolution  */
    double  rain_mm_high;          /* mm/hr:  heavy rain evolves water layer  */
    double  uv_index_high;         /* index:  very sunny triggers brightness  */

    kafka_producer_t *producer;    /* Handle to Kafka producer                */
    pthread_mutex_t   mutex;       /* Protects statistics & config reloads    */
    volatile bool     shutting_down;
    uint64_t          events_consumed;
    uint64_t          events_evolved;
} weather_evolver_ctx_t;

/* Forward declarations */
static int  weather_evolver_init   (const cJSON *cfg);
static int  weather_evolver_handle (const char *topic, const char *payload);
static void weather_evolver_stop   (void);
static void weather_evolver_stats  (void);

static weather_evolver_ctx_t g_ctx = { 0 };

/* -------------------------------------------------------------------------- */
/* JSON helpers                                                               */
/* -------------------------------------------------------------------------- */

/* Extract a double from a JSON object, return default_val if not present */
static inline double json_get_double_def(const cJSON *obj,
                                         const char  *key,
                                         double       default_val)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsNumber(item)) return default_val;
    return item->valuedouble;
}

/* Extract a string from JSON, duplicates it or returns default */
static inline char *json_get_strdup_def(const cJSON *obj,
                                        const char  *key,
                                        const char  *def_val)
{
    const cJSON *item = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (!cJSON_IsString(item)) return strdup(def_val);
    return strdup(item->valuestring);
}

/* -------------------------------------------------------------------------- */
/* Business logic                                                             */
/* -------------------------------------------------------------------------- */

/*
 * parse_weather_payload()
 *   Parses the oracle message payload and fills environmental metrics.
 *
 *   Expected format:
 *   {
 *      "timestamp"   : 1663432342,
 *      "temperature" : { "celsius": 27.2 },
 *      "wind"        : { "speed_m_s": 5.4 },
 *      "precip_mm"   : 0.0,
 *      "uv_index"    : 3.2
 *   }
 */
typedef struct
{
    double temp_c;
    double wind_m_s;
    double rain_mm;
    double uv_index;
    time_t ts;
} weather_metrics_t;

static bool parse_weather_payload(const char *json, weather_metrics_t *out)
{
    bool ok = false;
    cJSON *root = cJSON_Parse(json);
    if (!root) {
        LOG_ERR("Invalid JSON payload: %s", json);
        return false;
    }

    /* timestamp is optional */
    const cJSON *ts_item = cJSON_GetObjectItemCaseSensitive(root, "timestamp");
    out->ts = cJSON_IsNumber(ts_item) ? (time_t)ts_item->valuedouble : time(NULL);

    /* Temperature could be nested. */
    const cJSON *temp_obj = cJSON_GetObjectItemCaseSensitive(root, "temperature");
    if (temp_obj && cJSON_IsObject(temp_obj)) {
        out->temp_c = json_get_double_def(temp_obj, "celsius", NAN);
    } else {
        out->temp_c = json_get_double_def(root, "temperature", NAN);
    }

    /* Wind */
    const cJSON *wind_obj = cJSON_GetObjectItemCaseSensitive(root, "wind");
    if (wind_obj && cJSON_IsObject(wind_obj)) {
        out->wind_m_s = json_get_double_def(wind_obj, "speed_m_s", NAN);
    } else {
        out->wind_m_s = json_get_double_def(root, "wind_speed_m_s", NAN);
    }

    out->rain_mm   = json_get_double_def(root, "precip_mm", NAN);
    out->uv_index  = json_get_double_def(root, "uv_index", NAN);

    if (isnan(out->temp_c) ||
        isnan(out->wind_m_s) ||
        isnan(out->rain_mm) ||
        isnan(out->uv_index))
    {
        LOG_ERR("Missing required weather fields");
        goto done;
    }

    ok = true;

done:
    cJSON_Delete(root);
    return ok;
}

/*
 * decide_evolution_action()
 *   Determines which evolution action (if any) should be triggered based on
 *   the received metrics and configured thresholds.
 *
 *   Returns NULL if no evolution should be initiated, or a freshly allocated
 *   JSON string describing the evolve-command.  Caller must free().
 */
static char *decide_evolution_action(const weather_metrics_t *wx,
                                     const weather_evolver_ctx_t *cfg)
{
    const double t_high = cfg->temp_high_c;
    const double t_low  = cfg->temp_low_c;

    /* Deciding factors */
    bool evolve_temp_high = (wx->temp_c >= t_high);
    bool evolve_temp_low  = (wx->temp_c <= t_low);
    bool evolve_wind      = (wx->wind_m_s >= cfg->wind_speed_high);
    bool evolve_rain      = (wx->rain_mm  >= cfg->rain_mm_high);
    bool evolve_sun       = (wx->uv_index >= cfg->uv_index_high);

    if (!evolve_temp_high &&
        !evolve_temp_low  &&
        !evolve_wind      &&
        !evolve_rain      &&
        !evolve_sun)
    {
        return NULL; /* no thresholds crossed */
    }

    /* Compose evolution command */
    cJSON *cmd = cJSON_CreateObject();
    cJSON_AddStringToObject(cmd, "type", "EVOLVE");
    cJSON_AddStringToObject(cmd, "strategy", MODULE_NAME);
    cJSON_AddNumberToObject(cmd, "timestamp", (double)wx->ts);

    cJSON *triggers = cJSON_AddArrayToObject(cmd, "triggers");

    if (evolve_temp_high)
        cJSON_AddItemToArray(triggers, cJSON_CreateString("TEMP_HIGH"));
    if (evolve_temp_low)
        cJSON_AddItemToArray(triggers, cJSON_CreateString("TEMP_LOW"));
    if (evolve_wind)
        cJSON_AddItemToArray(triggers, cJSON_CreateString("WIND_STRONG"));
    if (evolve_rain)
        cJSON_AddItemToArray(triggers, cJSON_CreateString("RAIN_HEAVY"));
    if (evolve_sun)
        cJSON_AddItemToArray(triggers, cJSON_CreateString("UV_HIGH"));

    /* Attach raw measurements for deterministic rendering */
    cJSON *meas = cJSON_AddObjectToObject(cmd, "metrics");
    cJSON_AddNumberToObject(meas, "temp_c",   wx->temp_c);
    cJSON_AddNumberToObject(meas, "wind_m_s", wx->wind_m_s);
    cJSON_AddNumberToObject(meas, "rain_mm",  wx->rain_mm);
    cJSON_AddNumberToObject(meas, "uv_index", wx->uv_index);

    char *encoded = cJSON_PrintUnformatted(cmd);
    cJSON_Delete(cmd);

    return encoded; /* caller frees */
}

/* -------------------------------------------------------------------------- */
/* Kafka interaction                                                          */
/* -------------------------------------------------------------------------- */

static bool kafka_emit_evolution(weather_evolver_ctx_t *ctx,
                                 const char            *json_payload)
{
    assert(ctx && json_payload);

    kafka_msg_t msg = {
        .topic      = ctx->evolution_topic,
        .partition  = KAFKA_PARTITION_UA, /* let librdkafka decide */
        .payload    = json_payload,
        .payload_len= strlen(json_payload),
        .timestamp  = time(NULL)
    };

    int rc = kafka_produce(ctx->producer, &msg);
    if (rc != 0) {
        LOG_ERR("Failed to produce evolve command: %s", strerror(rc));
        return false;
    }

    return true;
}

/* -------------------------------------------------------------------------- */
/* Strategy interface                                                         */
/* -------------------------------------------------------------------------- */

static int weather_evolver_init(const cJSON *cfg_json)
{
    /* Open syslog for this module (once) */
    openlog(LOG_TAG, LOG_PID | LOG_CONS, LOG_USER);
    LOG_INFO("Initializing %s v%s", MODULE_NAME, LIB_VERSION);

    weather_evolver_ctx_t *ctx = &g_ctx;
    memset(ctx, 0, sizeof(*ctx));
    pthread_mutex_init(&ctx->mutex, NULL);

    /* Read configuration */
    ctx->oracle_topic     = json_get_strdup_def(cfg_json, "oracle_topic",
                                                DEFAULT_ORACLE_TOPIC);
    ctx->evolution_topic  = json_get_strdup_def(cfg_json, "evolution_topic",
                                                DEFAULT_EVOLVER_TOPIC);
    ctx->temp_high_c      = json_get_double_def(cfg_json, "temp_high_c", 35.0);
    ctx->temp_low_c       = json_get_double_def(cfg_json, "temp_low_c",   0.0);
    ctx->wind_speed_high  = json_get_double_def(cfg_json, "wind_m_s_high", 9.0);
    ctx->rain_mm_high     = json_get_double_def(cfg_json, "rain_mm_high", 7.5);
    ctx->uv_index_high    = json_get_double_def(cfg_json, "uv_index_high", 8.0);

    /* Initialize Kafka producer */
    kafka_conf_t kcfg = {
        .brokers         = getenv("KAFKA_BROKERS"), /* e.g., "kafka:9092" */
        .client_id       = MODULE_NAME,
        .linger_ms       = 30,
        .enable_idempotence = true
    };
    ctx->producer = kafka_producer_new(&kcfg);
    if (!ctx->producer) {
        LOG_ERR("Failed to init Kafka producer");
        return -1;
    }

    LOG_INFO("Bound to oracle topic '%s', evolution topic '%s'",
             ctx->oracle_topic, ctx->evolution_topic);

    return 0;
}

static int weather_evolver_handle(const char *topic, const char *payload)
{
    weather_evolver_ctx_t *ctx = &g_ctx;
    if (ctx->shutting_down) return 0;

    /* Only act on configured oracle topic */
    if (strcmp(topic, ctx->oracle_topic) != 0) return 0;

    pthread_mutex_lock(&ctx->mutex);
    ctx->events_consumed++;
    pthread_mutex_unlock(&ctx->mutex);

    weather_metrics_t wx;
    if (!parse_weather_payload(payload, &wx))
        return -EINVAL;

    char *evo_cmd = decide_evolution_action(&wx, ctx);
    if (!evo_cmd) {
        LOG_DBG("No evolution triggered for ts=%ld", wx.ts);
        return 0;
    }

    /* Emit command to Kafka */
    if (kafka_emit_evolution(ctx, evo_cmd)) {
        pthread_mutex_lock(&ctx->mutex);
        ctx->events_evolved++;
        pthread_mutex_unlock(&ctx->mutex);
        LOG_INFO("Evolution command emitted (triggers=%s)",
                 evo_cmd); /* contains triggers array */
    }
    free(evo_cmd);
    return 0;
}

static void weather_evolver_stop(void)
{
    weather_evolver_ctx_t *ctx = &g_ctx;
    ctx->shutting_down = true;

    weather_evolver_stats();

    if (ctx->producer) {
        kafka_producer_flush(ctx->producer, 5000 /*ms*/);
        kafka_producer_destroy(ctx->producer);
    }

    free(ctx->oracle_topic);
    free(ctx->evolution_topic);

    pthread_mutex_destroy(&ctx->mutex);

    LOG_INFO("Shutdown complete");
    closelog();
}

/* Dump basic runtime statistics */
static void weather_evolver_stats(void)
{
    weather_evolver_ctx_t *ctx = &g_ctx;
    pthread_mutex_lock(&ctx->mutex);
    LOG_INFO("Consumed=%" PRIu64 "  Evolved=%" PRIu64,
             ctx->events_consumed, ctx->events_evolved);
    pthread_mutex_unlock(&ctx->mutex);
}

/* -------------------------------------------------------------------------- */
/* Plug-in registration                                                       */
/* -------------------------------------------------------------------------- */

static struct muse_strategy_ops weather_strategy_ops = {
    .name          = MODULE_NAME,
    .init          = weather_evolver_init,
    .handle_event  = weather_evolver_handle,
    .shutdown      = weather_evolver_stop
};

const struct muse_strategy_ops *muse_strategy_get_ops(void)
{
    return &weather_strategy_ops;
}

/* -------------------------------------------------------------------------- */
/* Unit test harness (compile with -DWEATHER_EVOLVER_TEST)                    */
/* -------------------------------------------------------------------------- */
#ifdef WEATHER_EVOLVER_TEST
#include <unistd.h>

int main(void)
{
    /* Example configuration JSON */
    const char *cfg_json_str =
        "{ \"temp_high_c\": 30, \"wind_m_s_high\": 10 }";

    cJSON *cfg_json = cJSON_Parse(cfg_json_str);
    assert(cfg_json);

    weather_strategy_ops.init(cfg_json);

    const char *payload_good =
        "{ \"timestamp\": 1663432342, \"temperature\": {\"celsius\": 32},"
        "  \"wind\": {\"speed_m_s\": 3.2}, \"precip_mm\" : 0, \"uv_index\": 9 }";

    weather_strategy_ops.handle_event(DEFAULT_ORACLE_TOPIC, payload_good);

    weather_strategy_ops.shutdown();
    cJSON_Delete(cfg_json);
    return 0;
}
#endif /* WEATHER_EVOLVER_TEST */
/* ----------------------------------- EOF ---------------------------------- */
