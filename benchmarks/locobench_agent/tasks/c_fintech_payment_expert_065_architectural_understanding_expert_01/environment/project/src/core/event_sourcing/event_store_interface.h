#ifndef EDUPAY_LEDGER_ACADEMY_CORE_EVENT_SOURCING_EVENT_STORE_INTERFACE_H
#define EDUPAY_LEDGER_ACADEMY_CORE_EVENT_SOURCING_EVENT_STORE_INTERFACE_H
/*
 * EduPay Ledger Academy – Event Store Interface
 *
 * This header specifies a thin, implementation-agnostic façade used by the
 * Core Domain to interact with an Event Store.  Concrete adapters (PostgreSQL,
 * Kafka, Redis Streams, etc.) live in the “infrastructure” layer and satisfy
 * this contract without leaking technology-specific details into business
 * rules.
 *
 * Guidelines
 * ----------
 * •   All functions return an event_store_result_t that MUST be checked by
 *     the caller.
 * •   Ownership of heap memory is explicitly documented; failure to follow the
 *     contract will trigger sanitizers in debug builds.
 * •   The interface is thread-safe if and only if the underlying adapter is
 *     thread-safe.  Adapters MUST document their guarantees.
 *
 * Copyright © 2024 EduPay Ledger Academy
 */

#include <stddef.h>   /* size_t   */
#include <stdint.h>   /* uint*_t  */
#include <stdbool.h>  /* bool     */
#include <time.h>     /* time_t   */

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------- */
/*                         Error / Result  Handling                           */
/* -------------------------------------------------------------------------- */

typedef enum
{
    EVENT_STORE_OK                      = 0,
    EVENT_STORE_ERR_INVALID_ARGUMENT    = 1,
    EVENT_STORE_ERR_STREAM_NOT_FOUND    = 2,
    EVENT_STORE_ERR_CONFLICT            = 3,  /* Optimistic-concurrency failure */
    EVENT_STORE_ERR_OUT_OF_MEMORY       = 4,
    EVENT_STORE_ERR_BACKEND_UNAVAILABLE = 5,
    EVENT_STORE_ERR_INTERNAL            = 6,
    EVENT_STORE_ERR_NOT_IMPLEMENTED     = 7
} event_store_result_t;


/* -------------------------------------------------------------------------- */
/*                           Domain-Independent Types                         */
/* -------------------------------------------------------------------------- */

/* RFC-4122 UUID represented as a canonical 36-byte ASCII string + NULL. */
#define EVENT_STORE_UUID_STRING_LENGTH (36U)
#define EVENT_STORE_UUID_BUFFER_SIZE   (EVENT_STORE_UUID_STRING_LENGTH + 1U)

typedef struct
{
    char value[EVENT_STORE_UUID_BUFFER_SIZE];
} event_store_uuid_t;


/*
 * A single immutable Event as stored in the append-only log.
 *
 * payload
 *     Opaque blob (JSON, MessagePack, Protobuf, etc.).  The consumer owns the
 *     buffer after read_stream/read_all; the caller MUST release it via
 *     event_store_free_records().
 *
 * aggregate_version
 *     Acts as both the event’s “position” within its stream and the optimistic
 *     concurrency token.
 */
typedef struct
{
    event_store_uuid_t event_id;
    char               aggregate_type[64];   /* “StudentAccount”, “Ledger”, …  */
    event_store_uuid_t aggregate_id;
    uint64_t           aggregate_version;
    char               event_type[64];       /* “StudentEnrolled”, …           */
    uint8_t           *payload;
    size_t             payload_size;
    time_t             timestamp_utc;        /* Seconds since Unix epoch       */
} event_store_record_t;


/* Forward declarations for opaque handles */
typedef struct event_store         event_store_t;
typedef struct event_store_subscription event_store_subscription_t;


/* Callback invoked for every event delivered through a live subscription. */
typedef void (*event_store_subscription_cb)(
        const event_store_record_t *record,
        void                       *user_ctx);


/* -------------------------------------------------------------------------- */
/*                                API Surface                                 */
/* -------------------------------------------------------------------------- */

/*
 * Adapters populate this v-table at runtime.  The core domain never calls
 * implementations directly—only through these pointers—allowing Hot-Swap of
 * backends during coursework.
 */
typedef struct
{
    /*
     * Append an ordered collection of events to a stream.
     *
     * stream_name
     *     Convention: “<AggregateType>-<AggregateID>”.  Adapters MAY impose
     *     additional constraints (e.g., legal UTF-8, max length).
     *
     * expected_version
     *     Use UINT64_MAX (aka EVENT_STORE_ANY_VERSION) to disable optimistic
     *     concurrency checks.  Otherwise append will succeed only if the
     *     stream’s current version equals the expected value.
     *
     * return
     *     EVENT_STORE_OK on success.  EVENT_STORE_ERR_CONFLICT when the version
     *     check fails.
     */
    event_store_result_t
    (*append_to_stream)(event_store_t          *store,
                        const char             *stream_name,
                        const event_store_record_t *events,
                        size_t                  event_count,
                        uint64_t                expected_version);

    /*
     * Read at most max_count events from the given stream, starting at
     * from_version (inclusive).  Events are ordered by ascending version.
     *
     * On success, *out_records receives a heap-allocated array that MUST be
     * freed using free_records().
     */
    event_store_result_t
    (*read_stream)(event_store_t          *store,
                   const char             *stream_name,
                   uint64_t                from_version,
                   size_t                  max_count,
                   event_store_record_t  **out_records,
                   size_t                 *out_count);

    /*
     * Read across the global log (useful for projections that do not care
     * about stream boundaries).
     */
    event_store_result_t
    (*read_all)(event_store_t          *store,
                uint64_t                from_position,
                size_t                  max_count,
                event_store_record_t  **out_records,
                size_t                 *out_count);

    /*
     * Snapshotting APIs.  Aggregates with long event histories can be hydrated
     * faster by loading the latest snapshot and then replaying events emitted
     * after the snapshot_version.
     */
    event_store_result_t
    (*set_snapshot)(event_store_t          *store,
                    const char             *aggregate_type,
                    const event_store_uuid_t *aggregate_id,
                    const uint8_t          *snapshot_blob,
                    size_t                  snapshot_size,
                    uint64_t                aggregate_version);

    event_store_result_t
    (*get_snapshot)(event_store_t           *store,
                    const char              *aggregate_type,
                    const event_store_uuid_t  *aggregate_id,
                    uint8_t                **out_snapshot_blob,
                    size_t                  *out_snapshot_size,
                    uint64_t               *out_aggregate_version);

    /*
     * Live subscription.  Implementations SHOULD deliver events at-least-once
     * and MUST preserve order for a given stream.
     *
     * The subscription object is opaque; callers cancel via unsubscribe().
     */
    event_store_result_t
    (*subscribe)(event_store_t                    *store,
                 const char                       *stream_name,   /* NULL for all */
                 uint64_t                          from_version,
                 event_store_subscription_cb       callback,
                 void                             *user_ctx,
                 event_store_subscription_t      **out_subscription);

    event_store_result_t
    (*unsubscribe)(event_store_t               *store,
                   event_store_subscription_t  *subscription);

    /*
     * Memory utilities – must be provided because only the adapter knows how
     * the record buffers were allocated.
     */
    void (*free_records)(event_store_t         *store,
                         event_store_record_t  *records,
                         size_t                 record_count);

    /*
     * Gracefully close the connection and release resources.  After this call
     * the event_store_t pointer becomes invalid.
     */
    void (*close)(event_store_t *store);

} event_store_ops_t;


/*
 * Public handle.  Treat as opaque outside the adapter’s translation unit.
 */
struct event_store
{
    void                *impl;   /* adapter-specific state                     */
    event_store_ops_t    vtable; /* function pointers bound at construction    */
};


/* -------------------------------------------------------------------------- */
/*                           Convenience  Wrappers                            */
/* -------------------------------------------------------------------------- */

/* Allows domain services to ignore NULL-checks & vtable indirection clutter. */
static inline event_store_result_t
event_store_append(event_store_t *s, const char *stream,
                   const event_store_record_t *events, size_t n,
                   uint64_t expected_ver)
{
    if (!s || !s->vtable.append_to_stream) return EVENT_STORE_ERR_INVALID_ARGUMENT;
    return s->vtable.append_to_stream(s, stream, events, n, expected_ver);
}

static inline event_store_result_t
event_store_read_stream(event_store_t *s, const char *stream,
                        uint64_t from_ver, size_t max,
                        event_store_record_t **out_recs, size_t *out_cnt)
{
    if (!s || !s->vtable.read_stream) return EVENT_STORE_ERR_INVALID_ARGUMENT;
    return s->vtable.read_stream(s, stream, from_ver, max, out_recs, out_cnt);
}

static inline event_store_result_t
event_store_read_all(event_store_t *s, uint64_t pos, size_t max,
                     event_store_record_t **out_recs, size_t *out_cnt)
{
    if (!s || !s->vtable.read_all) return EVENT_STORE_ERR_INVALID_ARGUMENT;
    return s->vtable.read_all(s, pos, max, out_recs, out_cnt);
}

static inline void
event_store_free_records(event_store_t *s,
                         event_store_record_t *recs, size_t n)
{
    if (s && s->vtable.free_records)
        s->vtable.free_records(s, recs, n);
}

static inline void
event_store_close(event_store_t *s)
{
    if (s && s->vtable.close)
        s->vtable.close(s);
}

/* Omit wrappers for snapshot and subscription APIs to keep the header terse. */


/* -------------------------------------------------------------------------- */
/*                           Utility   Constants                              */
/* -------------------------------------------------------------------------- */

#define EVENT_STORE_ANY_VERSION UINT64_MAX


#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* EDUPAY_LEDGER_ACADEMY_CORE_EVENT_SOURCING_EVENT_STORE_INTERFACE_H */
