```c
/**
 * LexiLearn Orchestrator
 * ----------------------------------------------------
 * File  : ingestion_stage.c
 * Author: LexiLearn Engineering Team
 *
 * Description:
 *     Implements the Pipeline Pattern “Ingestion Stage” for the Controller
 *     layer.  The Ingestion Stage is responsible for:
 *          • Pulling raw, multimodal classroom data from an LMS REST API
 *          • Persisting the data in the shared Feature Store’s landing zone
 *          • Emitting Observer Pattern hooks so that downstream stages
 *            (pre-processing, feature engineering) are triggered only after
 *            successful ingestion
 *          • Logging metadata to the central Model Registry for lineage,
 *            governance, and reproducibility
 *
 *  NOTE:
 *      – The orchestration layer is intentionally decoupled from any specific
 *        ML framework.  Only generic C libraries (POSIX, libcurl, cJSON) and
 *        LexiLearn façade headers are referenced here.
 *      – Thread-safe, fault-tolerant, and retry-aware networking is required
 *        because LMS vendors impose throttling/availability SLAs.
 */

#define _POSIX_C_SOURCE 200809L /* strdup, getline, clock_gettime */
#define _DEFAULT_SOURCE            /* usleep                         */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <stdatomic.h>
#include <time.h>
#include <unistd.h>
#include <errno.h>

#include <curl/curl.h>
#include "cJSON.h"

/* === LexiLearn internal headers ======================================== */
#include "registry/registry_client.h"     /* Model Registry façade           */
#include "util/logger.h"                  /* syslog + printf wrapper         */
#include "observer/event_bus.h"           /* asynchronous hooks              */
#include "controller/pipeline/ingestion_stage.h"

/* =========================================================================
 *                          Compile-time defaults
 * =========================================================================*/
#ifndef INGESTION_REQUEST_TIMEOUT_SECS
#   define INGESTION_REQUEST_TIMEOUT_SECS 30
#endif

#ifndef INGESTION_MAX_RETRY
#   define INGESTION_MAX_RETRY 3
#endif

#ifndef INGESTION_BACKOFF_INITIAL_MS
#   define INGESTION_BACKOFF_INITIAL_MS 200
#endif

#ifndef INGESTION_BACKOFF_MULTIPLIER
#   define INGESTION_BACKOFF_MULTIPLIER 2.0
#endif

/* =========================================================================
 *                          Forward declarations
 * =========================================================================*/
static void  *ingestion_worker(void *arg);
static int    fetch_dataset(const char *endpoint,
                            const char *api_key,
                            char **out_buffer,
                            size_t   *out_size);
static int    persist_to_feature_store(const char *payload,
                                       size_t      size,
                                       const char *storage_dir,
                                       char      **out_filepath);
static void   emit_ingestion_event(const char *filepath);
static int    registry_log_ingestion(RegistryClient *client,
                                     const char     *filepath,
                                     const char     *origin);

/* =========================================================================
 *                             Data structures
 * =========================================================================*/

/* Public config, defined in header */
typedef struct {
    char         *lms_endpoint;
    char         *api_key;
    char         *feature_store_landing_dir;
    unsigned int  max_retry;
    RegistryClient *registry;
} IngestionConfig;

/* Internal handle */
struct IngestionStage {
    IngestionConfig cfg;
    pthread_t       thread;
    atomic_bool     should_stop;
};

/* =========================================================================
 *                             Public API
 * =========================================================================*/
IngestionStage *ingestion_stage_create(const IngestionConfig *user_cfg)
{
    if (!user_cfg || !user_cfg->lms_endpoint || !user_cfg->api_key ||
        !user_cfg->feature_store_landing_dir || !user_cfg->registry) {
        LOG_ERROR("Invalid configuration passed to ingestion_stage_create");
        return NULL;
    }

    IngestionStage *stage = calloc(1, sizeof(*stage));
    if (!stage) {
        LOG_ERROR("calloc failed: %s", strerror(errno));
        return NULL;
    }

    /* Deep-copy strings so we keep ownership */
    stage->cfg.lms_endpoint = strdup(user_cfg->lms_endpoint);
    stage->cfg.api_key      = strdup(user_cfg->api_key);
    stage->cfg.feature_store_landing_dir =
        strdup(user_cfg->feature_store_landing_dir);

    if (!stage->cfg.lms_endpoint || !stage->cfg.api_key ||
        !stage->cfg.feature_store_landing_dir) {
        LOG_ERROR("strdup failed");
        ingestion_stage_destroy(stage);
        return NULL;
    }

    stage->cfg.max_retry = (user_cfg->max_retry == 0)
                               ? INGESTION_MAX_RETRY
                               : user_cfg->max_retry;
    stage->cfg.registry = user_cfg->registry;

    atomic_init(&stage->should_stop, false);
    return stage;
}

int ingestion_stage_start(IngestionStage *stage)
{
    if (!stage) return -1;
    int rc = pthread_create(&stage->thread, NULL, ingestion_worker, stage);
    if (rc != 0) {
        LOG_ERROR("pthread_create failed: %s", strerror(rc));
        return -1;
    }
    return 0;
}

void ingestion_stage_stop(IngestionStage *stage)
{
    if (!stage) return;
    atomic_store(&stage->should_stop, true);
    pthread_join(stage->thread, NULL);
}

void ingestion_stage_destroy(IngestionStage *stage)
{
    if (!stage) return;

    free(stage->cfg.lms_endpoint);
    free(stage->cfg.api_key);
    free(stage->cfg.feature_store_landing_dir);
    /* Registry client is owned by caller */

    free(stage);
}

/* =========================================================================
 *                        Private helper implementation
 * =========================================================================*/

/**
 * ingestion_worker
 * -------------------------------------------------------------------------
 * Dedicated background thread.  Implements adaptive retry with exponential
 * back-off, then sleeps until the next scheduler tick is received via the
 * Event Bus (“cron.ingestion.tick”).
 */
static void *ingestion_worker(void *arg)
{
    IngestionStage *stage = (IngestionStage *)arg;

    EventBus *bus = event_bus_global();
    if (!bus) {
        LOG_CRITICAL("EventBus unavailable; ingestion cannot proceed");
        return NULL;
    }

    while (!atomic_load(&stage->should_stop)) {
        /* Block until cron event or stop */
        Event evt = event_bus_wait(bus, "cron.ingestion.tick", 5000);
        if (evt.type == EVENT_TIMEOUT) {
            continue; /* periodic check for should_stop */
        }
        if (evt.type == EVENT_SHUTDOWN) {
            break;
        }

        /* === 1. LMS fetch =================================================*/
        char  *payload  = NULL;
        size_t payload_sz = 0;
        int    rc        = fetch_dataset(stage->cfg.lms_endpoint,
                                         stage->cfg.api_key,
                                         &payload,
                                         &payload_sz);
        if (rc != 0) {
            LOG_WARN("LMS fetch failed (rc=%d). Skipping this tick.", rc);
            continue;
        }

        /* === 2. Persistence ==============================================*/
        char *filepath = NULL;
        rc = persist_to_feature_store(payload,
                                      payload_sz,
                                      stage->cfg.feature_store_landing_dir,
                                      &filepath);
        free(payload);
        if (rc != 0) {
            LOG_ERROR("Failed to persist dataset (rc=%d).", rc);
            continue;
        }

        /* === 3. Registry logging =========================================*/
        rc = registry_log_ingestion(stage->cfg.registry,
                                    filepath,
                                    stage->cfg.lms_endpoint);
        if (rc != 0) {
            LOG_ERROR("Failed to log ingestion event to registry");
            /* Non-fatal: continue */
        }

        /* === 4. Notify observers =========================================*/
        emit_ingestion_event(filepath);

        free(filepath);
    }

    return NULL;
}

/**
 * fetch_dataset
 * -------------------------------------------------------------------------
 * Perform an authenticated GET request to the LMS endpoint.  Implements
 * exponential back-off retries.  Caller owns *out_buffer (malloc’ed).
 */
static int fetch_dataset(const char *endpoint,
                         const char *api_key,
                         char **out_buffer,
                         size_t *out_size)
{
    if (!endpoint || !api_key || !out_buffer || !out_size) return -1;

    CURL *curl = curl_easy_init();
    if (!curl) {
        LOG_ERROR("curl_easy_init failed");
        return -2;
    }

    struct curl_slist *hdrs = NULL;
    char auth_header[256];
    snprintf(auth_header, sizeof(auth_header), "Authorization: Bearer %s",
             api_key);
    hdrs = curl_slist_append(hdrs, auth_header);
    hdrs = curl_slist_append(hdrs, "Accept: application/json");

    long retry = 0;
    long backoff_ms = INGESTION_BACKOFF_INITIAL_MS;
    int  rc = 0;

    struct {
        char  *ptr;
        size_t len;
    } buf = { .ptr = NULL, .len = 0 };

    /* Curl write callback */
    auto size_t write_cb(char *data, size_t size, size_t nmemb, void *userp) {
        size_t realsize = size * nmemb;
        typeof(buf) *mem = (typeof(buf) *)userp;

        char *tmp = realloc(mem->ptr, mem->len + realsize + 1);
        if (!tmp) {
            return 0; /* will cause CURLE_WRITE_ERROR */
        }
        mem->ptr = tmp;
        memcpy(&(mem->ptr[mem->len]), data, realsize);
        mem->len += realsize;
        mem->ptr[mem->len] = '\0';
        return realsize;
    }

    curl_easy_setopt(curl, CURLOPT_URL, endpoint);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, INGESTION_REQUEST_TIMEOUT_SECS);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &buf);

    do {
        CURLcode cres = curl_easy_perform(curl);
        if (cres == CURLE_OK) {
            long http_code = 0;
            curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
            if (http_code >= 200 && http_code < 300) {
                *out_buffer = buf.ptr;
                *out_size   = buf.len;
                rc = 0;
                break;
            } else {
                LOG_WARN("HTTP error %ld from LMS", http_code);
                rc = -4;
            }
        } else {
            LOG_WARN("Curl error: %s", curl_easy_strerror(cres));
            rc = -3;
        }

        /* Retry logic */
        retry++;
        if (retry <= INGESTION_MAX_RETRY) {
            LOG_INFO("Retrying (%ld/%d) after %ld ms", retry,
                     INGESTION_MAX_RETRY, backoff_ms);
            usleep(backoff_ms * 1000);
            backoff_ms *= INGESTION_BACKOFF_MULTIPLIER;
        }

    } while (retry <= INGESTION_MAX_RETRY);

    if (rc != 0 && buf.ptr) free(buf.ptr);

    curl_slist_free_all(hdrs);
    curl_easy_cleanup(curl);
    return rc;
}

/**
 * persist_to_feature_store
 * -------------------------------------------------------------------------
 * Writes the fetched payload to the Feature Store landing zone, naming the
 * file using a high-precision timestamp to avoid collisions.
 */
static int persist_to_feature_store(const char *payload,
                                    size_t      size,
                                    const char *storage_dir,
                                    char      **out_filepath)
{
    if (!payload || size == 0 || !storage_dir || !out_filepath) return -1;

    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);

    char filename[256];
    snprintf(filename, sizeof(filename),
             "ingest_%lld%03ld.json",
             (long long)ts.tv_sec,
             ts.tv_nsec / 1000000); /* ms precision */

    size_t pathlen = strlen(storage_dir) + 1 + strlen(filename) + 1;
    char *fullpath = malloc(pathlen);
    if (!fullpath) {
        LOG_ERROR("malloc failed: %s", strerror(errno));
        return -2;
    }

    snprintf(fullpath, pathlen, "%s/%s", storage_dir, filename);

    FILE *fp = fopen(fullpath, "wb");
    if (!fp) {
        LOG_ERROR("fopen(%s) failed: %s", fullpath, strerror(errno));
        free(fullpath);
        return -3;
    }

    if (fwrite(payload, 1, size, fp) != size) {
        LOG_ERROR("fwrite failed: %s", strerror(errno));
        fclose(fp);
        unlink(fullpath);
        free(fullpath);
        return -4;
    }
    fclose(fp);

    *out_filepath = fullpath;
    return 0;
}

/**
 * emit_ingestion_event
 * -------------------------------------------------------------------------
 * Publish a message on the global Event Bus so that downstream observers
 * (Pre-Processing Stage, Drift Detector, etc.) can react.
 */
static void emit_ingestion_event(const char *filepath)
{
    EventBus *bus = event_bus_global();
    if (!bus) {
        LOG_WARN("Unable to obtain EventBus");
        return;
    }
    event_bus_publish(bus, "data.ingested", filepath, (int)strlen(filepath));
}

/**
 * registry_log_ingestion
 * -------------------------------------------------------------------------
 * Persists metadata for lineage and MLOps governance.
 */
static int registry_log_ingestion(RegistryClient *client,
                                  const char     *filepath,
                                  const char     *origin)
{
    if (!client || !filepath || !origin) return -1;

    cJSON *entry = cJSON_CreateObject();
    cJSON_AddStringToObject(entry, "filepath", filepath);
    cJSON_AddStringToObject(entry, "source",   origin);

    char *json = cJSON_PrintUnformatted(entry);
    cJSON_Delete(entry);
    if (!json) return -2;

    int rc = registry_client_log_event(client, "ingestion", json);
    free(json);
    if (rc != 0) {
        LOG_WARN("Registry log failed (rc=%d)", rc);
    }
    return rc;
}
```
