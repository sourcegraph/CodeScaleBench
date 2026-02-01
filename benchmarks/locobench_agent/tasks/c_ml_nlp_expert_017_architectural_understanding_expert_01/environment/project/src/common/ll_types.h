/******************************************************************************\
 *  File:    ll_types.h
 *  Project: LexiLearn MVC Orchestrator (ml_nlp)
 *  Author:  LexiLearn Engineering
 *
 *  Description:
 *      Common type definitions, enumerations, and small inline helpers shared
 *      across the entire LexiLearn code-base.  This header deliberately avoids
 *      heavy dependencies so that it can be included by both high-level
 *      business logic and low-level platform utilities.
 *
 *  NOTE:
 *      Any change to the public interfaces defined in this header constitutes
 *      an API change and must be reflected in the semantic version below.
\******************************************************************************/

#ifndef LL_TYPES_H_
#define LL_TYPES_H_

#ifdef __cplusplus
extern "C" {
#endif

/* --- Standard Library ---------------------------------------------------- */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

/* --- Symbol Visibility --------------------------------------------------- */
/*  LL_API:       exported  (public) symbol
 *  LL_API_LOCAL: internal   (hidden) symbol
 */
#if defined _WIN32 || defined __CYGWIN__
    #ifdef LL_EXPORTS
        #ifdef __GNUC__
            #define LL_API __attribute__((dllexport))
        #else
            #define LL_API __declspec(dllexport)
        #endif
    #else
        #ifdef __GNUC__
            #define LL_API __attribute__((dllimport))
        #else
            #define LL_API __declspec(dllimport)
        #endif
    #endif
    #define LL_API_LOCAL
#else
    #if __GNUC__ >= 4
        #define LL_API       __attribute__((visibility("default")))
        #define LL_API_LOCAL __attribute__((visibility("hidden")))
    #else
        #define LL_API
        #define LL_API_LOCAL
    #endif
#endif

/* --- Compile-time Assertions -------------------------------------------- */
#ifndef STATIC_ASSERT
    #if defined(__STDC_VERSION__) && (__STDC_VERSION__ >= 201112L)
        #define STATIC_ASSERT(expr, msg) _Static_assert(expr, #msg)
    #else
        /* Pre-C11 fallback — creates invalid typedef on failure */
        #define STATIC_ASSERT(expr, msg) typedef char static_assert_##msg[(expr) ? 1 : -1]
    #endif
#endif

/* --- Versioning ---------------------------------------------------------- */
typedef struct
{
    uint16_t major;
    uint16_t minor;
    uint16_t patch;
} ll_version_t;

/* Macro helper for build-time version literals */
#define LL_VERSION(maj, min, pat) ((ll_version_t){ (maj), (min), (pat) })

/* Current public API version */
#define LL_API_VERSION_MAJOR 1
#define LL_API_VERSION_MINOR 0
#define LL_API_VERSION_PATCH 0
static const ll_version_t LL_API_VERSION = {
    LL_API_VERSION_MAJOR,
    LL_API_VERSION_MINOR,
    LL_API_VERSION_PATCH
};

/* --- UUIDs --------------------------------------------------------------- */
typedef uint64_t ll_uuid_t;

/* Human-readable canonical UUID string length (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx) */
#define LL_UUID_STR_LEN 37U /* 36 chars + '\0' */

/* --- Status / Error Codes ------------------------------------------------ */
typedef enum
{
    LL_STATUS_OK = 0,
    LL_STATUS_INVALID_ARGUMENT,
    LL_STATUS_OUT_OF_MEMORY,
    LL_STATUS_IO_ERROR,
    LL_STATUS_TIMEOUT,
    LL_STATUS_NOT_FOUND,
    LL_STATUS_PERMISSION_DENIED,
    LL_STATUS_MODEL_MISMATCH,
    LL_STATUS_MODEL_DRIFT_DETECTED,
    LL_STATUS_CANCELLED,
    LL_STATUS_UNIMPLEMENTED,
    LL_STATUS_INTERNAL_ERROR,
    LL_STATUS_UNKNOWN_ERROR
} ll_status_e;

/* --- Data Modalities ----------------------------------------------------- */
typedef enum
{
    LL_MODALITY_TEXT = 0,
    LL_MODALITY_AUDIO,
    LL_MODALITY_LMS_LOG,
    LL_MODALITY_IMAGE,
    LL_MODALITY_QUIZ,
    LL_MODALITY_MAX /* keep last */
} ll_modality_e;
STATIC_ASSERT(LL_MODALITY_MAX < 16, modality_enum_exceeds_4bits);

/* --- Model Types --------------------------------------------------------- */
typedef enum
{
    LL_MODEL_TRANSFORMER = 0,
    LL_MODEL_NGRAM,
    LL_MODEL_HYBRID,
    LL_MODEL_EXTERNAL,     /* user-supplied opaque model */
    LL_MODEL_MAX
} ll_model_type_e;

/* --- Quality Metrics ----------------------------------------------------- */
typedef struct
{
    double accuracy;
    double precision;
    double recall;
    double f1_score;
    double perplexity; /* optional — language modeling */
} ll_metrics_t;

/* --- Generic Result Object ---------------------------------------------- */
#define LL_MAX_ERROR_MSG_LEN 256U

typedef struct
{
    ll_status_e status;
    char        message[LL_MAX_ERROR_MSG_LEN];
} ll_result_t;

/* --- Observer / Callback Signatures ------------------------------------- */
typedef void (*ll_progress_cb)(float progress /* 0.0 – 1.0 */, void *user_ctx);
typedef void (*ll_drift_detected_cb)(ll_uuid_t          model_id,
                                     const ll_metrics_t *prev_metrics,
                                     const ll_metrics_t *curr_metrics,
                                     void               *user_ctx);

/* --- Inline Helper Functions -------------------------------------------- */
static inline const char *ll_status_to_str(ll_status_e status)
{
    switch (status)
    {
        case LL_STATUS_OK:                   return "OK";
        case LL_STATUS_INVALID_ARGUMENT:     return "Invalid argument";
        case LL_STATUS_OUT_OF_MEMORY:        return "Out of memory";
        case LL_STATUS_IO_ERROR:             return "I/O error";
        case LL_STATUS_TIMEOUT:              return "Timeout";
        case LL_STATUS_NOT_FOUND:            return "Not found";
        case LL_STATUS_PERMISSION_DENIED:    return "Permission denied";
        case LL_STATUS_MODEL_MISMATCH:       return "Model mismatch";
        case LL_STATUS_MODEL_DRIFT_DETECTED: return "Model drift detected";
        case LL_STATUS_CANCELLED:            return "Cancelled";
        case LL_STATUS_UNIMPLEMENTED:        return "Unimplemented";
        case LL_STATUS_INTERNAL_ERROR:       return "Internal error";
        case LL_STATUS_UNKNOWN_ERROR:        /* fall-through */
        default:                             return "Unknown error";
    }
}

static inline ll_result_t ll_result_ok(void)
{
    ll_result_t res = { LL_STATUS_OK, "Success" };
    return res;
}

static inline ll_result_t ll_result_error(ll_status_e status, const char *msg)
{
    ll_result_t res;
    res.status = status;

    if (msg && *msg)
    {
        /* copy with truncation */
        size_t i = 0U;
        for (; i < LL_MAX_ERROR_MSG_LEN - 1U && msg[i] != '\0'; ++i)
            res.message[i] = (char)msg[i];
        res.message[i] = '\0';
    }
    else
    {
        res.message[0] = '\0';
    }
    return res;
}

/* --- Utility Macros ------------------------------------------------------ */
#define LL_UNUSED(x) ((void)(x))

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LL_TYPES_H_ */
