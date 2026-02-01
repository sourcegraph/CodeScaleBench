/*
 *  LexiLearn MVC Orchestrator – Experiment Tracker
 *  File:    lexilearn_orchestrator/src/model/ml_pipeline/experiment_tracker.h
 *  Author:  LexiLearn Core Team
 *
 *  Description:
 *      A lightweight, dependency–free experiment–tracking module that allows the
 *      Model layer to persist hyper-parameters, metrics, and metadata produced
 *      during training / evaluation.  The tracker can be compiled as a
 *      single-header library by defining LLXP_IMPLEMENTATION in exactly one
 *      translation unit.
 *
 *      Typical usage:
 *
 *          #define LLXP_IMPLEMENTATION
 *          #include "experiment_tracker.h"
 *
 *          ...
 *          llxp_tracker_t tracker;
 *          llxp_init_tracker(&tracker, "bert-summarizer-run-042",
 *                            "BERT-SUM v3.1", "dataset_2024_04");
 *
 *          llxp_add_param(&tracker, "learning_rate", "2e-5");
 *          llxp_add_param(&tracker, "epochs",        "5");
 *
 *          ... training loop ...
 *
 *          llxp_add_metric(&tracker, "val_loss",  0.214);
 *          llxp_add_metric(&tracker, "val_bleu", 28.733);
 *
 *          llxp_complete_tracker(&tracker);
 *          llxp_export_json(&tracker, "./runs/bert-summarizer-run-042.json",
 *                          /* pretty = */ true);
 *          llxp_free(&tracker);
 *
 *  Thread-safety:
 *      All API functions are NOT thread-safe.  If concurrent access is needed,
 *      wrap calls in user-provided mutexes.
 */

#ifndef LEXILEARN_EXPERIMENT_TRACKER_H
#define LEXILEARN_EXPERIMENT_TRACKER_H

/*----------------------------------------------------------*
 *                        Includes                          *
 *----------------------------------------------------------*/
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <time.h>

/*----------------------------------------------------------*
 *                    Version / Macros                      *
 *----------------------------------------------------------*/
#define LLXP_VERSION_MAJOR 1
#define LLXP_VERSION_MINOR 0
#define LLXP_VERSION_PATCH 0

#define LLXP_STRINGIFY(x) #x
#define LLXP_TOSTRING(x)  LLXP_STRINGIFY(x)

#define LLXP_VERSION                                                      \
        LLXP_TOSTRING(LLXP_VERSION_MAJOR) "."                             \
        LLXP_TOSTRING(LLXP_VERSION_MINOR) "."                             \
        LLXP_TOSTRING(LLXP_VERSION_PATCH)

/* Maximum sizes for fixed-size buffers.  These can be overwritten by
 * providing the macro before including this header. */
#ifndef LLXP_MAX_ID_LEN
#   define LLXP_MAX_ID_LEN       64
#endif
#ifndef LLXP_MAX_KEY_LEN
#   define LLXP_MAX_KEY_LEN      64
#endif
#ifndef LLXP_MAX_VALUE_LEN
#   define LLXP_MAX_VALUE_LEN   256
#endif
#ifndef LLXP_MAX_NAME_LEN
#   define LLXP_MAX_NAME_LEN    128
#endif

/*----------------------------------------------------------*
 *                     Error Handling                       *
 *----------------------------------------------------------*/
typedef enum {
    LLXP_OK = 0,
    LLXP_ERR_INVALID_ARGUMENT,
    LLXP_ERR_OUT_OF_MEMORY,
    LLXP_ERR_SERIALIZATION,
    LLXP_ERR_IO
} llxp_status_t;

/* Human-readable string for error codes. */
static inline const char *llxp_status_to_str(llxp_status_t status)
{
    switch (status) {
        case LLXP_OK:                  return "OK";
        case LLXP_ERR_INVALID_ARGUMENT:return "Invalid argument";
        case LLXP_ERR_OUT_OF_MEMORY:   return "Out of memory";
        case LLXP_ERR_SERIALIZATION:   return "Serialization error";
        case LLXP_ERR_IO:              return "I/O error";
        default:                       return "Unknown error";
    }
}

/*----------------------------------------------------------*
 *            Fundamental Data Structures (opaque)          *
 *----------------------------------------------------------*/

/* A key/value pair used for parameters and metrics */
typedef struct {
    char  key  [LLXP_MAX_KEY_LEN];
    char  value[LLXP_MAX_VALUE_LEN];
    double numeric_val;              /* Used when the value represents a metric */
    bool  is_numeric;
} llxp_kv_pair_t;

/* Dynamic array utility used internally */
typedef struct {
    llxp_kv_pair_t *data;
    size_t          size;
    size_t          capacity;
} _llxp_vector_t;

/* The main tracker object */
typedef struct {
    char   experiment_id  [LLXP_MAX_ID_LEN];
    char   experiment_name[LLXP_MAX_NAME_LEN];
    char   model_name     [LLXP_MAX_NAME_LEN];
    char   dataset_version[LLXP_MAX_NAME_LEN];

    time_t start_time;
    time_t end_time;

    _llxp_vector_t params;
    _llxp_vector_t metrics;
} llxp_tracker_t;

/*----------------------------------------------------------*
 *                   Public API Prototypes                  *
 *----------------------------------------------------------*/

/* Initialize a tracker with basic metadata. */
llxp_status_t llxp_init_tracker(llxp_tracker_t     *tracker,
                                const char         *experiment_name,
                                const char         *model_name,
                                const char         *dataset_version);

/* Add a string hyper-parameter (key/value). */
llxp_status_t llxp_add_param (llxp_tracker_t *tracker,
                              const char     *key,
                              const char     *value);

/* Add a numeric metric (key/value). */
llxp_status_t llxp_add_metric(llxp_tracker_t *tracker,
                              const char     *key,
                              double          value);

/* Mark the experiment as finished (records end_time). */
llxp_status_t llxp_complete_tracker(llxp_tracker_t *tracker);

/* Serialize the tracker to a JSON file.
 * If pretty == true, the JSON will be indented for readability. */
llxp_status_t llxp_export_json(const llxp_tracker_t *tracker,
                               const char           *destination_path,
                               bool                  pretty);

/* Free any heap memory held by the tracker (safe to call multiple times). */
void llxp_free(llxp_tracker_t *tracker);


/*----------------------------------------------------------*
 *             Optional Header-Only Implementation          *
 *----------------------------------------------------------*/
#ifdef LLXP_IMPLEMENTATION

/*----------------------- Internal helpers -----------------------*/
static void _llxp_vector_init(_llxp_vector_t *vec)
{
    vec->data     = NULL;
    vec->size     = 0;
    vec->capacity = 0;
}

static void _llxp_vector_free(_llxp_vector_t *vec)
{
    free(vec->data);
    vec->data     = NULL;
    vec->size     = 0;
    vec->capacity = 0;
}

static llxp_status_t _llxp_vector_push(_llxp_vector_t *vec,
                                       const llxp_kv_pair_t *kv)
{
    if (vec->size == vec->capacity) {
        size_t new_cap = (vec->capacity == 0) ? 8 : vec->capacity * 2;
        llxp_kv_pair_t *tmp =
            (llxp_kv_pair_t*)realloc(vec->data, new_cap * sizeof(*vec->data));
        if (!tmp) return LLXP_ERR_OUT_OF_MEMORY;
        vec->data     = tmp;
        vec->capacity = new_cap;
    }
    vec->data[vec->size++] = *kv;
    return LLXP_OK;
}

/* Generate pseudo-random UUID-like string (not RFC-4122 compliant but unique
 * enough for logging). */
static void _llxp_generate_id(char out[LLXP_MAX_ID_LEN])
{
    static const char *hex = "0123456789abcdef";
    srand((unsigned)time(NULL) ^ (uintptr_t)&out);
    size_t len = LLXP_MAX_ID_LEN - 1;
    for (size_t i = 0; i < len; ++i)
        out[i] = hex[rand() % 16];
    out[len] = '\0';
}

/* Escape JSON string (very small subset). */
static void _llxp_json_escape(const char *src, char *dst, size_t dst_sz)
{
    size_t j = 0;
    for (size_t i = 0; src[i] && j + 2 < dst_sz; ++i) {
        switch (src[i]) {
            case '\"': if(j+2<dst_sz){dst[j++]='\\';dst[j++]='\"';} break;
            case '\\': if(j+2<dst_sz){dst[j++]='\\';dst[j++]='\\';} break;
            case '\n': if(j+2<dst_sz){dst[j++]='\\';dst[j++]='n';}  break;
            case '\r': if(j+2<dst_sz){dst[j++]='\\';dst[j++]='r';}  break;
            case '\t': if(j+2<dst_sz){dst[j++]='\\';dst[j++]='t';}  break;
            default:   dst[j++] = src[i];                           break;
        }
    }
    dst[j] = '\0';
}

/* Print indentation spaces */
static void _llxp_indent(FILE *fp, int level)
{
    for (int i = 0; i < level; ++i) fputs("    ", fp);
}

/*-------------------- Implementation functions ------------------*/

llxp_status_t llxp_init_tracker(llxp_tracker_t     *tracker,
                                const char         *experiment_name,
                                const char         *model_name,
                                const char         *dataset_version)
{
    if (!tracker || !experiment_name || !model_name || !dataset_version)
        return LLXP_ERR_INVALID_ARGUMENT;

    memset(tracker, 0, sizeof(*tracker));

    _llxp_generate_id(tracker->experiment_id);
    strncpy(tracker->experiment_name, experiment_name,
            sizeof(tracker->experiment_name) - 1);
    strncpy(tracker->model_name,      model_name,
            sizeof(tracker->model_name)      - 1);
    strncpy(tracker->dataset_version, dataset_version,
            sizeof(tracker->dataset_version) - 1);

    tracker->start_time = time(NULL);

    _llxp_vector_init(&tracker->params);
    _llxp_vector_init(&tracker->metrics);

    return LLXP_OK;
}

llxp_status_t llxp_add_param(llxp_tracker_t *tracker,
                             const char     *key,
                             const char     *value)
{
    if (!tracker || !key || !value) return LLXP_ERR_INVALID_ARGUMENT;

    llxp_kv_pair_t kv = {0};
    strncpy(kv.key,   key,   sizeof(kv.key)   - 1);
    strncpy(kv.value, value, sizeof(kv.value) - 1);
    kv.is_numeric = false;

    return _llxp_vector_push(&tracker->params, &kv);
}

llxp_status_t llxp_add_metric(llxp_tracker_t *tracker,
                              const char     *key,
                              double          value)
{
    if (!tracker || !key) return LLXP_ERR_INVALID_ARGUMENT;

    llxp_kv_pair_t kv = {0};
    strncpy(kv.key, key, sizeof(kv.key) - 1);
    kv.numeric_val = value;
    kv.is_numeric  = true;

    /* Also keep string representation for generic display */
    snprintf(kv.value, sizeof(kv.value), "%.10g", value);

    return _llxp_vector_push(&tracker->metrics, &kv);
}

llxp_status_t llxp_complete_tracker(llxp_tracker_t *tracker)
{
    if (!tracker) return LLXP_ERR_INVALID_ARGUMENT;
    tracker->end_time = time(NULL);
    return LLXP_OK;
}

llxp_status_t llxp_export_json(const llxp_tracker_t *tracker,
                               const char           *destination_path,
                               bool                  pretty)
{
    if (!tracker || !destination_path)
        return LLXP_ERR_INVALID_ARGUMENT;

    FILE *fp = fopen(destination_path, "w");
    if (!fp) return LLXP_ERR_IO;

    int indent_lvl = 0;
    #define P(...) do { if(fprintf(fp, __VA_ARGS__) < 0){fclose(fp);return LLXP_ERR_IO;} } while (0)

    P("{%s", pretty ? "\n" : "");

    /* Helper macro for quoting strings */
    #define Q(str) "\"" str "\""

    /* indent macro */
    #define INDENT() do{ if(pretty) _llxp_indent(fp, indent_lvl);}while(0)

    /* Basic metadata */
    indent_lvl++;
    INDENT(); P(Q("experiment_id")   ": " Q("%s")  ",%s",
                tracker->experiment_id, pretty ? "\n" : "");
    INDENT(); P(Q("experiment_name") ": " Q("%s")  ",%s",
                tracker->experiment_name, pretty ? "\n" : "");
    INDENT(); P(Q("model_name")      ": " Q("%s")  ",%s",
                tracker->model_name, pretty ? "\n" : "");
    INDENT(); P(Q("dataset_version") ": " Q("%s")  ",%s",
                tracker->dataset_version, pretty ? "\n" : "");
    INDENT(); P(Q("start_time")      ": %lld,%s",
                (long long)tracker->start_time, pretty ? "\n" : "");
    INDENT(); P(Q("end_time")        ": %lld,%s",
                (long long)tracker->end_time,   pretty ? "\n" : "");

    /* Parameters */
    INDENT(); P(Q("parameters") ": [%s", pretty ? "\n" : "");
    indent_lvl++;
    for (size_t i = 0; i < tracker->params.size; ++i) {
        const llxp_kv_pair_t *kv = &tracker->params.data[i];
        INDENT(); P("{");
        char escaped_val[LLXP_MAX_VALUE_LEN * 2];
        _llxp_json_escape(kv->value, escaped_val, sizeof(escaped_val));

        P(Q("key") ": " Q("%s") ", " Q("value") ": " Q("%s") "}",
          kv->key, escaped_val);

        if (i + 1 < tracker->params.size) P(",");
        P("%s", pretty ? "\n" : "");
    }
    indent_lvl--;
    if (pretty && tracker->params.size) INDENT();
    P("],%s", pretty ? "\n" : "");

    /* Metrics */
    INDENT(); P(Q("metrics") ": [%s", pretty ? "\n" : "");
    indent_lvl++;
    for (size_t i = 0; i < tracker->metrics.size; ++i) {
        const llxp_kv_pair_t *kv = &tracker->metrics.data[i];
        INDENT(); P("{");
        P(Q("key") ": " Q("%s") ", " Q("value") ": %.10g}",
          kv->key, kv->numeric_val);
        if (i + 1 < tracker->metrics.size) P(",");
        P("%s", pretty ? "\n" : "");
    }
    indent_lvl--;
    if (pretty && tracker->metrics.size) INDENT();
    P("]%s", pretty ? "\n" : "");

    indent_lvl--;
    P("}%s", pretty ? "\n" : "");

    #undef P
    #undef INDENT
    #undef Q

    if (fclose(fp) != 0) return LLXP_ERR_IO;

    return LLXP_OK;
}

void llxp_free(llxp_tracker_t *tracker)
{
    if (!tracker) return;
    _llxp_vector_free(&tracker->params);
    _llxp_vector_free(&tracker->metrics);
    memset(tracker, 0, sizeof(*tracker));
}

#endif /* LLXP_IMPLEMENTATION */
#endif /* LEXILEARN_EXPERIMENT_TRACKER_H */
