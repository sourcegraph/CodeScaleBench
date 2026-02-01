/*
 *  File:    ingestion_stage.h
 *  Project: LexiLearn MVC Orchestrator  (ml_nlp)
 *  Author:  LexiLearn Dev Team
 *
 *  Description:
 *      Public interface for the Controller-layer “IngestionStage”, the first
 *      step of the Pipeline Pattern that ingests multimodal classroom data
 *      from Learning-Management System (LMS) APIs and places the data onto an
 *      internal queue for downstream stages (e.g. preprocessing, feature
 *      engineering).
 *
 *      ‑ Thread-safe, back-pressure-aware design
 *      ‑ Prometheus-style metrics hooks
 *      ‑ Observer Pattern hooks for model-drift alarms
 *      ‑ Fully configurable at runtime through `IngestionConfig`
 *
 *  Usage:
 *      IngestionConfig cfg = { .stage_id = "lms_ingest",
 *                              .lms_base_url = "https://canvas.example.edu/api",
 *                              .auth_token   = "<REDACTED>",
 *                              .poll_interval_ms = 30000,
 *                              .queue_capacity   = 4096,
 *                              .concurrency      = 4 };
 *
 *      Logger *log = logger_create(LOG_LEVEL_INFO);
 *      IngestionStage *stage = ingestion_stage_new(&cfg, log);
 *      ingestion_stage_start(stage);
 *      …
 *      ingestion_stage_stop(stage, true);
 *      ingestion_stage_destroy(&stage);
 *
 *  NOTE:
 *      This header ONLY exposes the public API.  The internal representation
 *      of `struct IngestionStage` is intentionally hidden to guarantee
 *      encapsulation.  Link against `liblexilearn_controller.a` to obtain the
 *      implementation.
 */

#ifndef LEXILEARN_CONTROLLER_PIPELINE_INGESTION_STAGE_H
#define LEXILEARN_CONTROLLER_PIPELINE_INGESTION_STAGE_H

#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Standard Library Dependencies                                            */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* ────────────────────────────────────────────────────────────────────────── */
/* Forward Declarations for Cross-Module Types                              */
typedef struct Logger      Logger;       /*  <-- logger.h                    */
typedef struct Observer    Observer;     /*  <-- observer.h                  */
typedef struct ThreadPool  ThreadPool;   /*  <-- thread_pool.h               */
typedef struct RingBuffer  RingBuffer;   /*  <-- ring_buffer.h               */

/* ────────────────────────────────────────────────────────────────────────── */
/* Public Enumerations                                                      */

/*  Run-time state machine of an IngestionStage                             */
typedef enum
{
    INGESTION_STAGE_STATE_INIT = 0,  /* Created but not yet started          */
    INGESTION_STAGE_STATE_RUNNING,   /* Actively polling / ingesting         */
    INGESTION_STAGE_STATE_STOPPING,  /* Graceful shutdown in progress        */
    INGESTION_STAGE_STATE_STOPPED,   /* Stopped successfully                 */
    INGESTION_STAGE_STATE_ERROR      /* Irrecoverable error occurred         */
} IngestionStageState;

/*  Status codes returned by most public APIs                               */
typedef enum
{
    INGESTION_OK = 0,
    INGESTION_ERR_INVALID_ARGUMENT,
    INGESTION_ERR_NETWORK,
    INGESTION_ERR_QUEUE_OVERFLOW,
    INGESTION_ERR_STATE,
    INGESTION_ERR_MEMORY,
    INGESTION_ERR_UNKNOWN
} IngestionStatus;

/* ────────────────────────────────────────────────────────────────────────── */
/* Metric Snapshot Structure                                                */
typedef struct
{
    uint64_t records_ingested;     /* Total number of raw records fetched   */
    uint64_t records_dispatched;   /* Total sent to downstream stages       */
    uint64_t records_dropped;      /* Dropped due to validation / overflow  */

    uint32_t queue_size;           /* Current elements in ring-buffer       */
    uint32_t queue_capacity;       /* Configured capacity                   */

    IngestionStageState current_state;  /* FINITE STATE                       */
} IngestionMetrics;

/* ────────────────────────────────────────────────────────────────────────── */
/* Runtime Configuration                                                    */
typedef struct
{
    /* Identification & Networking */
    const char *stage_id;          /* Must be unique within Controller      */
    const char *lms_base_url;      /* e.g. "https://canvas.my.edu/api"      */
    const char *auth_token;        /* Bearer token or OAuth2 credential     */

    /* Performance & Reliability */
    uint32_t poll_interval_ms;     /* Default: 60000 (1 minute)             */
    uint32_t queue_capacity;       /* Default: 8192                         */
    uint16_t concurrency;          /* Worker threads.  Default: 2           */

    /* Feature Flags */
    bool enable_voice_ingest;      /* WAV/MP3 classroom audio               */
    bool enable_text_ingest;       /* Essays, short answers                 */
    bool enable_logs_ingest;       /* Clickstream, LMS logs                 */

    /* Monitoring & Observability */
    bool enable_metrics;           /* Expose Prometheus metrics             */
} IngestionConfig;

/* ────────────────────────────────────────────────────────────────────────── */
/* Opaque Handle (forward-declared)                                         */
typedef struct IngestionStage IngestionStage;

/* ────────────────────────────────────────────────────────────────────────── */
/* Public API                                                               */

/*
 * ingestion_stage_new
 * ------------------------------------------------------------------
 * Allocate and initialise a new ingestion stage with the provided
 * configuration.  Returns NULL on failure (check errno or logger).
 */
IngestionStage *
ingestion_stage_new(const IngestionConfig *cfg,
                    Logger                *logger);

/*
 * ingestion_stage_start
 * ------------------------------------------------------------------
 * Spawn worker threads, begin polling the LMS, and change state to
 * RUNNING.  Returns INGESTION_ERR_STATE if the stage is already
 * running or has been stopped permanently.
 */
IngestionStatus
ingestion_stage_start(IngestionStage *stage);

/*
 * ingestion_stage_stop
 * ------------------------------------------------------------------
 * Request a shutdown.  If `drain` is true the function blocks until
 * the internal queue has been flushed; otherwise it stops immediately
 * and pending items will be dropped.
 */
IngestionStatus
ingestion_stage_stop(IngestionStage *stage,
                     bool           drain);

/*
 * ingestion_stage_push
 * ------------------------------------------------------------------
 *  Manually inject a record into the ingestion queue.  Useful for
 *  unit tests or when data arrives via web-hooks rather than polling.
 *
 *  The payload is copied into an internal buffer; the caller retains
 *  ownership of `data`.
 */
IngestionStatus
ingestion_stage_push(IngestionStage *stage,
                     const void     *data,
                     size_t          len,
                     const char     *content_type);

/*
 * ingestion_stage_register_observer
 * ------------------------------------------------------------------
 * Register an Observer that will receive lifecycle events (state
 * transitions, back-pressure warnings, etc.).
 */
IngestionStatus
ingestion_stage_register_observer(IngestionStage *stage,
                                  Observer       *observer);

/*
 * ingestion_stage_metrics
 * ------------------------------------------------------------------
 * Obtain a snapshot of current counters / gauges.  Can be called from
 * any thread; uses atomic loads under the hood.
 */
IngestionStatus
ingestion_stage_metrics(const IngestionStage *stage,
                        IngestionMetrics     *out_metrics);

/*
 * ingestion_stage_last_status
 * ------------------------------------------------------------------
 * Return the most recent non-OK status for debugging purposes.
 */
IngestionStatus
ingestion_stage_last_status(const IngestionStage *stage);

/*
 * ingestion_stage_destroy
 * ------------------------------------------------------------------
 * Release all resources.  It is illegal to call this while the stage
 * is still RUNNING; stop it first.  The pointer is set to NULL on
 * success to prevent accidental reuse.
 */
void
ingestion_stage_destroy(IngestionStage **stage);

/* ────────────────────────────────────────────────────────────────────────── */
#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* LEXILEARN_CONTROLLER_PIPELINE_INGESTION_STAGE_H */
