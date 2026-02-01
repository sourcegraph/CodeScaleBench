```c
/***********************************************************************
 *  File: transformer_summarizer.c
 *  Project: LexiLearn MVC Orchestrator (ml_nlp)
 *  Description:
 *      Concrete Strategy implementation that wraps a Transformer-
 *      based abstractive summarization model.  Internally the model
 *      is served by a lightweight Python FastAPI micro-service that
 *      performs tokenization and ONNX Runtime inference.  This C module
 *      focuses on orchestration—loading runtime parameters, invoking
 *      the micro-service over HTTP, performing basic error handling,
 *      and exposing a clean Strategy interface to the Controller
 *      pipeline.
 *
 *  Dependencies:
 *      - libcurl      : HTTP client for communicating with micro-service
 *      - cJSON        : Lightweight JSON marshaling/unmarshaling
 *      - pthread      : Thread-safe ref-counting / locking
 *
 *  Build flags example:
 *      gcc -std=c11 -Wall -Wextra -pedantic -lcurl -lpthread -lcjson \
 *          -I./include -c transformer_summarizer.c
 ***********************************************************************/

#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <curl/curl.h>
#include <cjson/cJSON.h>

#include "summarizer_strategy.h"  /* Strategy interface */
#include "transformer_summarizer.h"

/* ---------- Compile-time Constants ---------------------------------- */

#define DEFAULT_SERVICE_URL "http://127.0.0.1:8089"
#define DEFAULT_TIMEOUT_SEC 8L
#define MAX_ERRMSG_SIZE     256

/* ---------- Helper Macros ------------------------------------------- */

#define SAFE_FREE(p)        \
    do {                    \
        if ((p) != NULL) {  \
            free(p);        \
            (p) = NULL;     \
        }                   \
    } while (0)

/* ---------- Data Structures ----------------------------------------- */

/* Model hyper-parameters that influence inference on the Python side. */
typedef struct {
    unsigned int max_tokens;          /* Maximum # tokens in generated summary */
    float        temperature;         /* Softmax temperature               */
    float        top_p;               /* Nucleus sampling                  */
} HyperParams;

/* Concrete TransformerSummarizer "class" */
struct TransformerSummarizer {
    /* Public Strategy interface; must be first for safe casting        */
    SummarizerStrategy iface;

    /* ---- Internal implementation details ---- */
    char          *service_url;      /* REST endpoint of inference svc    */
    HyperParams    hp;               /* Inference hyper-parameters        */

    /* Thread-safety guards                                               */
    pthread_mutex_t ref_lock;
    unsigned int    ref_count;

    /* Diagnostics / metrics                                              */
    unsigned long   total_requests;
    unsigned long   failed_requests;
};

/* ---------- Forward Declarations ------------------------------------ */

static int  ts_init(SummarizerStrategy *self, const SummarizerCfg *cfg);
static void ts_destroy(SummarizerStrategy *self);
static char *ts_summarize(const SummarizerStrategy *self,
                          const char               *doc,
                          size_t                    doc_len);

static size_t curl_write_cb(void *ptr, size_t size, size_t nmemb, void *userdata);
static char *perform_http_request(const TransformerSummarizer *ts,
                                  const char                  *payload_json,
                                  char                        *errbuf,
                                  size_t                       errbuf_sz);
static char *build_request_payload(const TransformerSummarizer *ts,
                                   const char                  *doc,
                                   size_t                       doc_len);

/* ---------- Public Factory ------------------------------------------ */

SummarizerStrategy *transformer_summarizer_create(void)
{
    TransformerSummarizer *ts = calloc(1, sizeof(*ts));
    if (!ts) return NULL;

    /* Populate vtable */
    ts->iface.init      = ts_init;
    ts->iface.destroy   = ts_destroy;
    ts->iface.summarize = ts_summarize;

    /* Defaults */
    ts->service_url = strdup(DEFAULT_SERVICE_URL);
    ts->hp.max_tokens  = 60;
    ts->hp.temperature = 0.8f;
    ts->hp.top_p       = 0.9f;

    pthread_mutex_init(&ts->ref_lock, NULL);
    ts->ref_count = 1;

    return &ts->iface;
}

/* ---------- Strategy Implementation --------------------------------- */

static int ts_init(SummarizerStrategy *self, const SummarizerCfg *cfg)
{
    if (!self) return -EINVAL;

    TransformerSummarizer *ts = (TransformerSummarizer *)self;

    /* Custom service URL from config */
    if (cfg && cfg->endpoint_url) {
        SAFE_FREE(ts->service_url);
        ts->service_url = strdup(cfg->endpoint_url);
    }

    /* Hyper-parameters */
    if (cfg) {
        if (cfg->max_tokens)   ts->hp.max_tokens  = cfg->max_tokens;
        if (cfg->temperature)  ts->hp.temperature = cfg->temperature;
        if (cfg->top_p)        ts->hp.top_p       = cfg->top_p;
    }

    /* Validate URL */
    if (!ts->service_url || strlen(ts->service_url) == 0) {
        fprintf(stderr, "[TransformerSummarizer] Invalid service URL\n");
        return -EINVAL;
    }

    return 0;
}

static void ts_destroy(SummarizerStrategy *self)
{
    if (!self) return;

    TransformerSummarizer *ts = (TransformerSummarizer *)self;

    pthread_mutex_lock(&ts->ref_lock);
    if (--ts->ref_count > 0) {
        pthread_mutex_unlock(&ts->ref_lock);
        return;
    }
    pthread_mutex_unlock(&ts->ref_lock);

    /* Clean-up resources */
    SAFE_FREE(ts->service_url);
    pthread_mutex_destroy(&ts->ref_lock);
    SAFE_FREE(ts);
}

static char *ts_summarize(const SummarizerStrategy *self,
                          const char               *doc,
                          size_t                    doc_len)
{
    if (!self || !doc || doc_len == 0) {
        return NULL;
    }

    const TransformerSummarizer *ts = (const TransformerSummarizer *)self;

    char errbuf[MAX_ERRMSG_SIZE] = {0};

    /* Build request payload */
    char *payload = build_request_payload(ts, doc, doc_len);
    if (!payload) {
        fprintf(stderr, "[TransformerSummarizer] Failed to build request JSON\n");
        return NULL;
    }

    /* Perform HTTP request */
    char *response_json = perform_http_request(ts, payload, errbuf, sizeof(errbuf));
    SAFE_FREE(payload);

    if (!response_json) {
        fprintf(stderr, "[TransformerSummarizer] HTTP request failed: %s\n", errbuf);
        return NULL;
    }

    /* Parse summary from JSON */
    cJSON *root = cJSON_Parse(response_json);
    SAFE_FREE(response_json);
    if (!root) {
        fprintf(stderr, "[TransformerSummarizer] Malformed JSON response\n");
        return NULL;
    }

    const cJSON *summary_node = cJSON_GetObjectItemCaseSensitive(root, "summary");
    if (!cJSON_IsString(summary_node) || (summary_node->valuestring == NULL)) {
        fprintf(stderr, "[TransformerSummarizer] JSON missing 'summary'\n");
        cJSON_Delete(root);
        return NULL;
    }

    char *summary = strdup(summary_node->valuestring);
    cJSON_Delete(root);

    return summary;  /* Caller owns memory */
}

/* ---------- Internal Helper Functions ------------------------------- */

/* Accumulate HTTP response body into a dynamic buffer */
static size_t curl_write_cb(void *ptr, size_t size, size_t nmemb, void *userdata)
{
    size_t        total  = size * nmemb;
    cJSON_Buffer *buf    = (cJSON_Buffer *)userdata;

    char *new_data = realloc(buf->data, buf->size + total + 1);
    if (!new_data) return 0; /* Will trigger CURLE_WRITE_ERROR */

    buf->data = new_data;
    memcpy(buf->data + buf->size, ptr, total);
    buf->size += total;
    buf->data[buf->size] = '\0';

    return total;
}

typedef struct {
    char *data;
    size_t size;
} cJSON_Buffer;

/* Perform synchronous HTTP POST; returns response body or NULL on error. */
static char *perform_http_request(const TransformerSummarizer *ts,
                                  const char                  *payload_json,
                                  char                        *errbuf,
                                  size_t                       errbuf_sz)
{
    CURL *curl = curl_easy_init();
    if (!curl) {
        snprintf(errbuf, errbuf_sz, "curl_easy_init failed");
        return NULL;
    }

    struct curl_slist *headers = NULL;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    cJSON_Buffer resp_buf = {.data = NULL, .size = 0};

    curl_easy_setopt(curl, CURLOPT_URL, ts->service_url);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, payload_json);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, curl_write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &resp_buf);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, DEFAULT_TIMEOUT_SEC);

    /* More robust error reporting */
    CURLcode res = curl_easy_perform(curl);
    if (res != CURLE_OK) {
        snprintf(errbuf, errbuf_sz, "curl_easy_perform: %s", curl_easy_strerror(res));
        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
        SAFE_FREE(resp_buf.data);
        return NULL;
    }

    long http_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    if (http_code != 200) {
        snprintf(errbuf, errbuf_sz, "HTTP %ld from service", http_code);
        SAFE_FREE(resp_buf.data);
        return NULL;
    }

    return resp_buf.data; /* Caller owns memory */
}

/* Build JSON payload for summarization request */
static char *build_request_payload(const TransformerSummarizer *ts,
                                   const char                  *doc,
                                   size_t                       doc_len)
{
    if (!doc || doc_len == 0) return NULL;

    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;

    cJSON_AddStringToObject(root, "document", doc);
    cJSON_AddNumberToObject(root, "max_tokens",   ts->hp.max_tokens);
    cJSON_AddNumberToObject(root, "temperature",  ts->hp.temperature);
    cJSON_AddNumberToObject(root, "top_p",        ts->hp.top_p);

    char *json_str = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return json_str; /* Caller owns */
}

/* ---------- Thread-safe Reference Counting (optional) --------------- */

void transformer_summarizer_retain(SummarizerStrategy *self)
{
    if (!self) return;
    TransformerSummarizer *ts = (TransformerSummarizer *)self;
    pthread_mutex_lock(&ts->ref_lock);
    ++ts->ref_count;
    pthread_mutex_unlock(&ts->ref_lock);
}

void transformer_summarizer_release(SummarizerStrategy *self)
{
    ts_destroy(self);
}

/* ---------- Basic Metrics Reporting --------------------------------- */

void transformer_summarizer_dump_stats(const SummarizerStrategy *self, FILE *out)
{
    if (!self || !out) return;
    const TransformerSummarizer *ts = (const TransformerSummarizer *)self;
    fprintf(out,
            "TransformerSummarizer Stats:\n"
            "  Service URL     : %s\n"
            "  Total Requests  : %lu\n"
            "  Failed Requests : %lu\n",
            ts->service_url,
            ts->total_requests,
            ts->failed_requests);
}
```