/**
 * EduPay Ledger Academy - CQRS Query Bus
 *
 * File:    src/core/cqrs/query_bus.h
 * Project: EduPay Ledger Academy (fintech_payment)
 * Language: C11
 *
 * Description
 * -----------
 * A lightweight, framework-agnostic in-memory query bus that enables the Core
 * domain layer to dispatch read-only queries (CQRS) without depending on
 * infrastructure details.  Professors can replace this header-only reference
 * implementation with a message-broker backed version (e.g., NATS, RabbitMQ)
 * by adhering to the same public interface.
 *
 * Design Notes
 * ------------
 * • Header-only:  All logic is `static inline` so that including units do not
 *   need to link against an additional object file.  
 * • Thread-safety:  A C11 `mtx_t` protects the registration table.  
 * • Compile-time extensibility:  `QUERY_BUS_MAX_HANDLERS` can be overridden
 *   via compiler flags (e.g., -DQUERY_BUS_MAX_HANDLERS=64).  
 * • No external dependencies beyond the C11 Standard Library, keeping the
 *   Core layer free of platform or framework coupling.
 *
 * Copyright
 * ---------
 * MIT License – see repository root for full license text.
 */
#ifndef EDUPAY_LEDGER_ACADEMY_CORE_CQRS_QUERY_BUS_H
#define EDUPAY_LEDGER_ACADEMY_CORE_CQRS_QUERY_BUS_H

/* ---- Standard Library --------------------------------------------------- */
#include <stddef.h>     /* size_t   */
#include <stdint.h>     /* uint32_t */
#include <stdbool.h>    /* bool     */
#include <string.h>     /* strcmp   */
#include <threads.h>    /* mtx_t    */
#include <stdlib.h>     /* malloc, free */

/* ------------------------------------------------------------------------- */
/*                              PUBLIC API                                   */
/* ------------------------------------------------------------------------- */

/*
 * Error/Status codes returned by query-bus functions.
 * A zero or positive value indicates success.
 */
enum cqrs_qb_status {
    CQRS_QB_OK                   = 0,
    CQRS_QB_ERR_INVALID_ARG      = -1,
    CQRS_QB_ERR_HANDLER_EXISTS   = -2,
    CQRS_QB_ERR_HANDLER_NOTFOUND = -3,
    CQRS_QB_ERR_TABLE_FULL       = -4,
    CQRS_QB_ERR_INTERNAL         = -5
};

/*
 * Generic query envelope.
 * `payload` must remain valid for the duration of a single dispatch.
 */
typedef struct cqrs_query {
    const char *name;      /* Fully-qualified query name (e.g., "student.balance.by_id") */
    uint32_t    version;   /* Semantic versioning facilitates query evolution           */
    const void *payload;   /* Pointer to immutable query data                           */
} cqrs_query_t;

/*
 * Generic query result envelope.
 * The handler owns the memory behind `payload` and must document how the caller
 * should deallocate it (typically via an exported free function).
 */
typedef struct cqrs_query_result {
    const char *name;      /* Mirrors the query name for logging/tracing                */
    uint32_t    version;   /* Mirrors the query version                                  */
    void       *payload;   /* Pointer to result data                                     */
} cqrs_query_result_t;

/*
 * Function pointer signature for query handlers.
 *
 * Parameters
 * ----------
 * • query      – Incoming query envelope (read-only).
 * • out_result – Result envelope to be populated by the handler.  The handler
 *                must set `payload` to NULL upon failure.
 * • user_ctx   – Optional context pointer supplied at registration time.
 *
 * Returns a `cqrs_qb_status`.
 */
typedef int (*cqrs_query_handler_fn)(
        const cqrs_query_t      *query,
        cqrs_query_result_t     *out_result,
        void                    *user_ctx);

/* Forward declaration for opaque handle. */
typedef struct cqrs_query_bus cqrs_query_bus_t;

/*
 * Create a new query bus instance.
 *
 * Parameters
 * ----------
 * • max_handlers – Capacity of the registration table.  Pass zero to use
 *                  the compile-time constant `QUERY_BUS_MAX_HANDLERS`.
 *
 * Returns
 * -------
 * Pointer to a newly allocated bus, or NULL on allocation failure.
 * Call `cqrs_query_bus_destroy` when done.
 */
static inline cqrs_query_bus_t *
cqrs_query_bus_create(size_t max_handlers);

/*
 * Destroy a query bus instance and release all resources.
 * Registered handlers are NOT invoked during destruction.
 */
static inline void
cqrs_query_bus_destroy(cqrs_query_bus_t *bus);

/*
 * Register a handler for a given query name.
 *
 * A name may be registered only once; attempting to overwrite an existing
 * handler results in `CQRS_QB_ERR_HANDLER_EXISTS`.
 */
static inline int
cqrs_query_bus_register(
        cqrs_query_bus_t       *bus,
        const char             *query_name,
        cqrs_query_handler_fn   handler,
        void                   *user_ctx);

/*
 * Dispatch a query synchronously.
 *
 * On success, `out_result` is populated by the handler.
 */
static inline int
cqrs_query_bus_dispatch(
        cqrs_query_bus_t       *bus,
        const cqrs_query_t     *query,
        cqrs_query_result_t    *out_result);


/* ------------------------------------------------------------------------- */
/*                       HEADER-ONLY  IMPLEMENTATION                         */
/* ------------------------------------------------------------------------- */

#ifndef QUERY_BUS_MAX_HANDLERS
#define QUERY_BUS_MAX_HANDLERS 32u
#endif

struct cqrs_query_bus {
    mtx_t  lock;
    size_t capacity;
    size_t count;

    struct handler_entry {
        const char               *name;
        cqrs_query_handler_fn      fn;
        void                      *ctx;
    } *table;
};

/*------------- Internal helpers ------------------------------------------*/
static inline bool
_qb_str_eq(const char *a, const char *b)
{
    return (a == b) || (a && b && strcmp(a, b) == 0);
}

/*------------- Public implementation ------------------------------------*/
static inline cqrs_query_bus_t *
cqrs_query_bus_create(size_t max_handlers)
{
    cqrs_query_bus_t *bus = malloc(sizeof(*bus));
    if (!bus) return NULL;

    bus->capacity = (max_handlers == 0) ? QUERY_BUS_MAX_HANDLERS : max_handlers;
    bus->count    = 0u;
    bus->table    = calloc(bus->capacity, sizeof(*bus->table));
    if (!bus->table) {
        free(bus);
        return NULL;
    }

    if (mtx_init(&bus->lock, mtx_plain) != thrd_success) {
        free(bus->table);
        free(bus);
        return NULL;
    }
    return bus;
}

static inline void
cqrs_query_bus_destroy(cqrs_query_bus_t *bus)
{
    if (!bus) return;

    mtx_destroy(&bus->lock);
    free(bus->table);
    free(bus);
}

static inline int
cqrs_query_bus_register(
        cqrs_query_bus_t       *bus,
        const char             *query_name,
        cqrs_query_handler_fn   handler,
        void                   *user_ctx)
{
    if (!bus || !query_name || !handler) return CQRS_QB_ERR_INVALID_ARG;

    if (mtx_lock(&bus->lock) != thrd_success) return CQRS_QB_ERR_INTERNAL;

    /* Check for dup */
    for (size_t i = 0; i < bus->count; ++i) {
        if (_qb_str_eq(bus->table[i].name, query_name)) {
            mtx_unlock(&bus->lock);
            return CQRS_QB_ERR_HANDLER_EXISTS;
        }
    }

    if (bus->count >= bus->capacity) {
        mtx_unlock(&bus->lock);
        return CQRS_QB_ERR_TABLE_FULL;
    }

    bus->table[bus->count++] = (struct handler_entry){
        .name = query_name,
        .fn   = handler,
        .ctx  = user_ctx
    };

    mtx_unlock(&bus->lock);
    return CQRS_QB_OK;
}

static inline int
cqrs_query_bus_dispatch(
        cqrs_query_bus_t       *bus,
        const cqrs_query_t     *query,
        cqrs_query_result_t    *out_result)
{
    if (!bus || !query || !out_result) return CQRS_QB_ERR_INVALID_ARG;

    int rc = CQRS_QB_ERR_HANDLER_NOTFOUND;

    /* Defensive initialization */
    *out_result = (cqrs_query_result_t){
        .name    = query->name,
        .version = query->version,
        .payload = NULL
    };

    /* Acquire read access */
    if (mtx_lock(&bus->lock) != thrd_success) return CQRS_QB_ERR_INTERNAL;

    cqrs_query_handler_fn fn   = NULL;
    void                 *ctx  = NULL;
    for (size_t i = 0; i < bus->count; ++i) {
        if (_qb_str_eq(bus->table[i].name, query->name)) {
            fn  = bus->table[i].fn;
            ctx = bus->table[i].ctx;
            break;
        }
    }
    mtx_unlock(&bus->lock);

    if (!fn) {
        return CQRS_QB_ERR_HANDLER_NOTFOUND;
    }

    /* Delegate to handler (no lock held) */
    rc = fn(query, out_result, ctx);
    return rc;
}

#endif /* EDUPAY_LEDGER_ACADEMY_CORE_CQRS_QUERY_BUS_H */
