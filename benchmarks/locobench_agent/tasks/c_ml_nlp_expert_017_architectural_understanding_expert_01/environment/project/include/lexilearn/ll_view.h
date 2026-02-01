#ifndef LEXILEARN_LL_VIEW_H
#define LEXILEARN_LL_VIEW_H
/**
 * @file ll_view.h
 * @author
 *      LexiLearn MVC Orchestrator Team
 * @brief
 *      Public API for the LexiLearn View layer.  This header exposes a low-level
 *      C interface used by controller or third-party plug-ins to publish model
 *      metrics, subscribe to drift events, and render web-socket–friendly
 *      dashboards.
 *
 *      The implementation (see ll_view.c) adheres to MVC principles and hides
 *      all rendering details behind an opaque context handle.  Internally the
 *      View layer may employ high-level libraries such as
 *      ‑ cairo / skia for drawing
 *      ‑ protobuf / flatbuffers for binary transport
 *      ‑ libwebsockets for real-time updates
 *      but none of these are part of the public ABI.
 *
 *      Thread-safety:
 *          All functions are re-entrant and safe to call from multiple threads
 *          as long as each thread operates on a distinct ll_view_t instance.
 *
 *      Lifetime rules:
 *          ‑ ll_view_new() returns a fully configured instance.
 *          ‑ ll_view_free() MUST be invoked exactly once for each
 *            ll_view_t* obtained from ll_view_new() to avoid resource leaks.
 *
 *      Versioning:
 *          A semantic version macro is provided.  Minor/patch revisions will
 *          guarantee backward-binary-compatibility (BBC).  Major bumps may
 *          introduce breaking changes and will be communicated in release
 *          notes.
 */

#include <stddef.h>     /* size_t */
#include <stdint.h>     /* uint64_t */
#include <stdbool.h>    /* bool    */

#ifdef __cplusplus
extern "C" {
#endif

/*---------------------------------------------------------------------------*/
/*  Build / Compiler-switches                                                */
/*---------------------------------------------------------------------------*/

#if defined(LL_VIEW_STATIC)
#   define LL_VIEW_API
#elif defined(_WIN32)
#   ifdef LL_VIEW_EXPORTS
#       define LL_VIEW_API __declspec(dllexport)
#   else
#       define LL_VIEW_API __declspec(dllimport)
#   endif
#else
#   define LL_VIEW_API __attribute__((visibility("default")))
#endif

/*---------------------------------------------------------------------------*/
/*  Semantic Version                                                         */
/*---------------------------------------------------------------------------*/

#define LL_VIEW_VERSION_MAJOR   1
#define LL_VIEW_VERSION_MINOR   0
#define LL_VIEW_VERSION_PATCH   0
#define LL_VIEW_MAKE_VERSION(maj,min,pat) ((maj)*10000 + (min)*100 + (pat))
#define LL_VIEW_VERSION LL_VIEW_MAKE_VERSION(LL_VIEW_VERSION_MAJOR, \
                                             LL_VIEW_VERSION_MINOR, \
                                             LL_VIEW_VERSION_PATCH)

/*---------------------------------------------------------------------------*/
/*  Error Handling                                                           */
/*---------------------------------------------------------------------------*/

/**
 * @enum ll_view_err_t
 * @brief Typed error codes returned by all non-void API calls.
 */
typedef enum ll_view_err_e
{
    LL_VIEW_OK               = 0,   /* No error                                   */
    LL_VIEW_EINVAL           = 1,   /* Invalid argument                            */
    LL_VIEW_ENOMEM           = 2,   /* Allocation failure                          */
    LL_VIEW_EIO              = 3,   /* I/O or serialization error                  */
    LL_VIEW_EINTERNAL        = 4,   /* Unspecified internal failure                */
    LL_VIEW_EVERSION         = 5,   /* Unsupported struct or protocol version      */
    LL_VIEW_EBUSY            = 6,   /* Resource busy / concurrency violation       */
    LL_VIEW_ENOTFOUND        = 7,   /* Requested item not registered               */
    LL_VIEW_ECONN            = 8,   /* Network/socket failure                      */
    LL_VIEW_ETIMEOUT         = 9,   /* Operation timed out                         */
    LL_VIEW_EOS              = 10,  /* End-of-stream                               */
} ll_view_err_t;

/*---------------------------------------------------------------------------*/
/*  Forward Declarations / Opaque Types                                      */
/*---------------------------------------------------------------------------*/

typedef struct ll_view_s ll_view_t;  /* opaque view context */

/**
 * @struct ll_metric_s
 * @brief
 *      Represents a high-level metric to be charted on the dashboard.
 *
 *      The View layer will copy the name/value pairs.  The caller retains
 *      ownership of the pointed-to buffers and MAY free/modify them
 *      immediately after the call returns.
 */
typedef struct ll_metric_s
{
    const char *name;        /* UTF-8 metric name (e.g., "BLEU", "Accuracy")    */
    const double *values;    /* Array of length 'count'                         */
    size_t count;            /* Number of points in 'values'                    */
} ll_metric_t;

/**
 * @enum ll_event_type_t
 * @brief
 *      Event types that the View layer emits.  Observers may subscribe to
 *      any subset by passing a bit-mask during registration.
 */
typedef enum ll_event_type_e
{
    LL_EVENT_UNKNOWN         = 0,
    LL_EVENT_RENDER_COMPLETE = 1 << 0,   /* A frame finished rendering            */
    LL_EVENT_MODEL_UPDATED   = 1 << 1,   /* Model metrics pushed                  */
    LL_EVENT_MODEL_DRIFT     = 1 << 2,   /* Drift detection triggered             */
    LL_EVENT_CLIENT_CONNECT  = 1 << 3,   /* Web client connected                  */
    LL_EVENT_CLIENT_DISCONN  = 1 << 4,   /* Web client disconnected               */
} ll_event_type_t;

/**
 * @brief
 *      Observer callback called by the internal event dispatcher.  Executed
 *      in an implementation-defined worker thread; MUST return quickly.
 * @param ctx      User-defined pointer provided during registration.
 * @param evt      Type of the event fired.
 * @param opaque   Implementation-specific payload (may be NULL).
 */
typedef void (*ll_event_cb)(void *ctx,
                            ll_event_type_t evt,
                            const void *opaque);

/*---------------------------------------------------------------------------*/
/*  Public API                                                               */
/*---------------------------------------------------------------------------*/

/**
 * ll_view_new
 * --------------------------------------------------------------------------
 * Construct a new View context from the provided configuration file.
 *
 * @param out_view     [out] Newly created context.  Set to NULL on failure.
 * @param config_path  [in]  UTF-8 path to a JSON/YAML configuration file.
 * @return             Zero on success, otherwise an ll_view_err_t code.
 *
 * Failure cases include:
 *      LL_VIEW_EINVAL   if out_view or config_path is NULL
 *      LL_VIEW_EIO      if the config file cannot be read/parsed
 *      LL_VIEW_ENOMEM   on allocation failures
 */
LL_VIEW_API
ll_view_err_t
ll_view_new(ll_view_t **out_view,
            const char *config_path);

/**
 * ll_view_free
 * --------------------------------------------------------------------------
 * Destroy the given ll_view_t instance and release all underlying resources.
 * @warning After the call returns, any pointer to the view becomes invalid.
 *
 * @param view         View instance obtained from ll_view_new().  NULL-safe.
 */
LL_VIEW_API
void
ll_view_free(ll_view_t *view);

/**
 * ll_view_publish_metric
 * --------------------------------------------------------------------------
 * Push a metric array to the dashboard.  The View layer may perform internal
 * aggregation or smoothing depending on the configuration.
 *
 * @param view     Target view context
 * @param metric   Metric specification (see ll_metric_t)
 * @return         LL_VIEW_OK on success
 */
LL_VIEW_API
ll_view_err_t
ll_view_publish_metric(ll_view_t       *view,
                       const ll_metric_t *metric);

/**
 * ll_view_trigger_render
 * --------------------------------------------------------------------------
 * Force-render a full dashboard frame regardless of the configured cadence.
 * Primarily used for integration tests or critical UX checkpoints.
 *
 * @param view     Target view context
 * @return         LL_VIEW_OK on success, LL_VIEW_EBUSY if a render is running
 */
LL_VIEW_API
ll_view_err_t
ll_view_trigger_render(ll_view_t *view);

/**
 * ll_view_subscribe_events
 * --------------------------------------------------------------------------
 * Register an observer callback for the given event mask.
 *
 * @param view     Target view context
 * @param mask     Bitwise OR of ll_event_type_t flags
 * @param cb       Callback function pointer.  If NULL, subscription is removed.
 * @param userctx  User-supplied pointer forwarded back to the callback
 * @return         LL_VIEW_OK on success
 */
LL_VIEW_API
ll_view_err_t
ll_view_subscribe_events(ll_view_t          *view,
                         uint32_t            mask,
                         ll_event_cb         cb,
                         void               *userctx);

/**
 * ll_view_push_notification
 * --------------------------------------------------------------------------
 * Send a UTF-8 textual notification to all connected dashboards (e.g.,
 * "Retraining scheduled for midnight").  Large messages are fragmented
 * and transmitted in a streaming fashion.
 *
 * @param view     Target context
 * @param msg      UTF-8 string (NULL-terminated)
 * @return         LL_VIEW_OK on success
 */
LL_VIEW_API
ll_view_err_t
ll_view_push_notification(ll_view_t    *view,
                          const char   *msg);

/**
 * ll_view_flush
 * --------------------------------------------------------------------------
 * Block until all pending frames and network buffers are processed.
 *
 * @param view     View context
 * @param timeout_ms Maximum time to wait in milliseconds. 0 = infinite.
 * @return         LL_VIEW_OK if everything flushed, LL_VIEW_ETIMEOUT otherwise
 */
LL_VIEW_API
ll_view_err_t
ll_view_flush(ll_view_t *view, uint64_t timeout_ms);

/*---------------------------------------------------------------------------*/
/*  Debug / Introspection                                                    */
/*---------------------------------------------------------------------------*/

/**
 * ll_view_get_backend
 * --------------------------------------------------------------------------
 * Retrieve a human-readable identifier of the rendering backend in use
 * (e.g., "cairo", "opengl", "mock").
 *
 * @param view         Target context
 * @return             Const pointer valid until view is freed. Never NULL.
 */
LL_VIEW_API
const char *
ll_view_get_backend(const ll_view_t *view);

/**
 * ll_view_last_error
 * --------------------------------------------------------------------------
 * Fetch the last error string produced by the calling thread.  Provided for
 * debugging purposes only—should NOT be displayed to end-users.
 *
 * @param view     View context (may be NULL for global init failures)
 * @return         UTF-8 null-terminated string.  Owned by library.
 */
LL_VIEW_API
const char *
ll_view_last_error(const ll_view_t *view);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LEXILEARN_LL_VIEW_H */
