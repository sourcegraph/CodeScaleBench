/**
 * SynestheticCanvas Texture Service
 * =================================
 * File:    texture_service.h
 * Project: SynestheticCanvas API Suite – Texture Micro-service
 * Language: C11
 *
 * Public service-layer interface for “dynamic texture synthesis”.
 *
 * The texture service is responsible for generating, mutating and retrieving
 * real-time texture streams that can be consumed by the upstream API-Gateway
 * (GraphQL or REST).  It encapsulates domain logic, repository access, and I/O
 * pipelines (e.g. WebP / PNG encoders, GPU compute shaders, etc.) behind a
 * minimal but expressive C interface.
 *
 * Each public call is:
 *   • Thread-safe
 *   • Non-blocking (utilises an internal worker pool)
 *   • Configurable through a `texture_service_cfg_t` configuration struct
 *   • Augmented with structured logging (JSON) & monotonic metrics counters
 *
 * NOTE:  This is a header-only *interface* description.  The corresponding
 *        implementation lives in `texture_service.c`.
 */

#ifndef SYNESTHETIC_CANVAS_TEXTURE_SERVICE_H
#define SYNESTHETIC_CANVAS_TEXTURE_SERVICE_H

/* ---- Standard Library --------------------------------------------------- */
#include <stddef.h>     /* size_t               */
#include <stdint.h>     /* uint8_t, uint32_t…   */
#include <stdbool.h>    /* bool                 */

/* ---- Third-Party Dependencies ------------------------------------------- *
 * These are purposely forward-declared to keep the header self-contained.
 * Concrete integration occurs in the *.c implementation file.               */
struct cJSON;          /* Forward declaration (provided by cJSON)            */
struct uv_loop_s;      /* Forward declaration (provided by libuv)            */


/* ========================================================================= *
 * VERSIONING
 * ========================================================================= */

#define TEXTURE_SERVICE_MAJOR  1
#define TEXTURE_SERVICE_MINOR  0
#define TEXTURE_SERVICE_PATCH  3

#define TEXTURE_SERVICE_VERSION_STRING  "1.0.3"

typedef struct {
    uint8_t major;
    uint8_t minor;
    uint8_t patch;
} texture_service_version_t;


/* ========================================================================= *
 * ERROR HANDLING
 * ========================================================================= */

typedef enum {
    TS_OK = 0,                 /* No error                                   */
    TS_ERR_INVALID_ARG,        /* Bad input parameter                        */
    TS_ERR_CFG_INVALID,        /* Invalid configuration                      */
    TS_ERR_NOT_INITIALISED,    /* Service not yet initialised               */
    TS_ERR_ALREADY_RUNNING,    /* Attempted double-initialisation            */
    TS_ERR_REPO_FAILURE,       /* Repository/database error                  */
    TS_ERR_GPU_FAILURE,        /* GPU compute error                          */
    TS_ERR_IO,                 /* I/O (filesystem / network) error           */
    TS_ERR_OOM,                /* Out-of-memory                              */
    TS_ERR_CANCELLED,          /* Operation cancelled by caller              */
    TS_ERR_UNKNOWN             /* Fallback / unspecified error               */
} texture_service_status_t;


/* ========================================================================= *
 * LOGGING & MONITORING
 * ========================================================================= */

/* Log levels compatible with syslog semantics            */
typedef enum {
    TS_LOG_TRACE = 0,
    TS_LOG_DEBUG,
    TS_LOG_INFO,
    TS_LOG_WARN,
    TS_LOG_ERROR,
    TS_LOG_FATAL
} ts_log_level_t;

/* Custom log callback signature */
typedef void (*ts_log_fn)(ts_log_level_t level,
                          const char   *component,
                          const char   *fmt, ...) __attribute__((format(printf,3,4)));

/* Monitoring  (simple counter increment, gauge set, etc.) */
typedef void (*ts_metrics_counter_inc_fn)(const char *name, uint64_t delta);
typedef void (*ts_metrics_gauge_set_fn)(const char *name, double value);


/* ========================================================================= *
 * DATA TYPES
 * ========================================================================= */

/* 128-bit UUID stored as 16 raw bytes                                   */
typedef struct { uint8_t bytes[16]; } ts_uuid_t;

/* A binary blob representing an encoded texture asset.                  */
typedef struct {
    uint8_t *data;          /* Pointer to heap-owned buffer              */
    size_t   size;          /* Number of valid bytes                     */
    char    *mime_type;     /* Ex: "image/webp", "image/png"             */
} ts_texture_blob_t;

/* Texture metadata (persisted in repository)                            */
typedef struct {
    ts_uuid_t id;               /* Primary key                            */
    char     *label;            /* Human-readable name                    */
    uint32_t  width;            /* px                                     */
    uint32_t  height;           /* px                                     */
    uint8_t   channels;         /* 3 (RGB) or 4 (RGBA)                    */
    double    duration_ms;      /* Animated textures (else 0)             */
    uint64_t  created_epoch_ms; /* Unix epoch in ms                       */
    uint64_t  updated_epoch_ms; /* Last modification                      */
} ts_texture_meta_t;

/* Pagination-aware cursor */
typedef struct {
    ts_uuid_t after_id;        /* 0-initialised means "start from first"   */
    size_t    limit;           /* page size                                */
} ts_texture_cursor_t;

/* Iterator result page                                                  */
typedef struct {
    ts_texture_meta_t *items;  /* Array of `limit` elements               */
    size_t             count;  /* Number of valid meta records            */
    bool               has_more;
    ts_uuid_t          next_after_id;
} ts_texture_page_t;


/* ========================================================================= *
 * CONFIGURATION
 * ========================================================================= */

typedef struct {
    /* Repository configuration */
    const char *postgres_dsn;      /* Ex: "postgres://user:pwd@host/db"     */
    const char *bucket_path;       /* File-system or S3-style bucket URI    */

    /* Runtime / event-loop */
    struct uv_loop_s *loop;        /* External libuv loop (optional)        */
    size_t            worker_threads; /* CPU worker pool size (default: #cpu) */

    /* Logging / metrics */
    ts_log_fn                log_cb;         /* Custom log handler          */
    ts_metrics_counter_inc_fn metrics_inc_cb;/* Counter increment handler    */
    ts_metrics_gauge_set_fn   metrics_set_cb;/* Gauge set handler            */

    /* Feature toggles */
    bool enable_gpu_acceleration;
    bool enable_response_cache;

    /* Reserved for future extensions — must be zeroed */
    void *reserved[4];
} texture_service_cfg_t;


/* Opaque service handle — forward-declared here.                         */
typedef struct texture_service_s texture_service_t;


/* ========================================================================= *
 * PUBLIC API
 * ========================================================================= */

/**
 * texture_service_get_version
 * ---------------------------
 * Returns the compile-time version of the texture service library.
 */
texture_service_version_t
texture_service_get_version(void);


/**
 * texture_service_startup
 * -----------------------
 * Initialise global resources (shared TLS contexts, codec lookup tables,
 * GPU runtime, etc.).   Must be called once per process *before* any other
 * texture-service API.
 */
texture_service_status_t
texture_service_startup(void);


/**
 * texture_service_shutdown
 * ------------------------
 * Release global resources acquired during `startup`.
 *
 * Safe to call multiple times; subsequent calls will be ignored.
 */
void
texture_service_shutdown(void);


/**
 * texture_service_create
 * ----------------------
 * Allocates and initialises a dedicated `texture_service_t` instance based
 * on the provided configuration.
 *
 * The returned pointer must be destroyed with `texture_service_destroy`.
 *
 * Thread-safe: yes
 */
texture_service_status_t
texture_service_create(const texture_service_cfg_t *cfg,
                       texture_service_t          **out_service);


/**
 * texture_service_destroy
 * -----------------------
 * Gracefully tears down an instance created via `texture_service_create`.
 *
 * All in-flight asynchronous operations (if any) are cancelled and awaited.
 */
void
texture_service_destroy(texture_service_t *svc);


/**
 * texture_service_generate_async
 * ------------------------------
 * Initiates asynchronous procedural texture generation.
 *
 * Parameters:
 *   svc        – Service handle
 *   seed_json  – User-supplied JSON object describing the algorithm
 *                (e.g., Perlin noise, Voronoi, turbulence parameters).
 *   cb         – Completion callback (invoked on the libuv loop thread)
 *   userdata   – Opaque pointer passed back to `cb`
 *
 * Callback signature:
 *   void (*generate_cb)(texture_service_status_t status,
 *                       const ts_texture_meta_t *meta,
 *                       void                    *userdata);
 *
 * The produced texture blob is persisted to the configured repository/bucket.
 * Ownership of `meta` remains with the service.  If clients require the blob
 * itself, they must call `texture_service_fetch_blob()` afterwards.
 */
typedef void (*ts_generate_cb)(texture_service_status_t    status,
                               const ts_texture_meta_t    *meta,
                               void                       *userdata);

texture_service_status_t
texture_service_generate_async(texture_service_t   *svc,
                               const struct cJSON  *seed_json,
                               ts_generate_cb       cb,
                               void                *userdata);


/**
 * texture_service_mutate_async
 * ----------------------------
 * Creates a child texture derived from an existing one (“variation”).
 *
 * The mutation JSON can contain operations like:
 *   { "rotate": 45, "blend_with": "<uuid>", "saturation": "+20%" }
 *
 * Callback semantics are identical to `generate_async`.
 */
typedef void (*ts_mutate_cb)(texture_service_status_t    status,
                             const ts_texture_meta_t    *meta,
                             void                       *userdata);

texture_service_status_t
texture_service_mutate_async(texture_service_t   *svc,
                             ts_uuid_t            source_texture_id,
                             const struct cJSON  *mutation_json,
                             ts_mutate_cb         cb,
                             void                *userdata);


/**
 * texture_service_get_meta
 * ------------------------
 * Synchronous fetch of a single texture’s metadata from repository.
 *
 * Caller owns the returned `meta` pointer and must free it with
 * `texture_service_meta_free()`.
 */
texture_service_status_t
texture_service_get_meta(texture_service_t  *svc,
                         ts_uuid_t           id,
                         ts_texture_meta_t **out_meta);


/**
 * texture_service_list_meta
 * -------------------------
 * Paginates over texture metadata.  When finished, caller must free the page
 * resources with `texture_service_page_free()`.
 */
texture_service_status_t
texture_service_list_meta(texture_service_t     *svc,
                          ts_texture_cursor_t    cursor,
                          ts_texture_page_t    **out_page);


/**
 * texture_service_fetch_blob
 * --------------------------
 * Retrieves the encoded binary data for a given texture UUID.
 *
 * The caller owns the returned blob and must free it with
 * `texture_service_blob_free()`.
 */
texture_service_status_t
texture_service_fetch_blob(texture_service_t  *svc,
                           ts_uuid_t           id,
                           ts_texture_blob_t **out_blob);


/**
 * texture_service_delete
 * ----------------------
 * Permanently removes a texture (metadata + blob).
 */
texture_service_status_t
texture_service_delete(texture_service_t *svc,
                       ts_uuid_t          id);


/* ========================================================================= *
 * MEMORY MANAGEMENT HELPERS
 * ========================================================================= */

/* Frees a `ts_texture_meta_t` previously returned by the service.           */
void texture_service_meta_free(ts_texture_meta_t *meta);

/* Frees a `ts_texture_blob_t` previously returned by the service.           */
void texture_service_blob_free(ts_texture_blob_t *blob);

/* Frees a `ts_texture_page_t` and all nested resources.                     */
void texture_service_page_free(ts_texture_page_t *page);


/* ========================================================================= *
 * UTILITY
 * ========================================================================= */

/**
 * ts_uuid_generate
 * ----------------
 * Utility for generating RFC-4122 v4 UUIDs.  Provided as a convenience for
 * callers that need to create client-side identifiers for resources.
 */
ts_uuid_t ts_uuid_generate(void);

/**
 * ts_uuid_to_string / ts_uuid_from_string
 * ---------------------------------------
 * Bidirectional UUID string <--> binary conversion helpers.
 *
 * `to_string` writes a 37-byte NUL-terminated string (including the dash
 * separators).  The buffer must therefore be at least 37 bytes long.
 */
void     ts_uuid_to_string(ts_uuid_t uuid, char out[37]);
bool     ts_uuid_from_string(const char *str, ts_uuid_t *out_uuid);


/**
 * ts_texture_status_string
 * ------------------------
 * Converts an error/status code to a static human-readable string.
 */
const char *ts_texture_status_string(texture_service_status_t status);


/* ------------------------------------------------------------------------- */
#endif /* SYNESTHETIC_CANVAS_TEXTURE_SERVICE_H */