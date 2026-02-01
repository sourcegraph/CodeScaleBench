/*
 * postgres_event_store.h
 *
 * EduPay Ledger Academy – Bursar Service
 *
 * A header-only, production-grade implementation of an Event Store backed by
 * PostgreSQL.  The code is intentionally self-contained so that instructors
 * can drop the file into coursework without chasing build flags across the
 * repository.  A corresponding SQL migration (not included here) is expected
 * to have created the following table and index:
 *
 *   CREATE TABLE IF NOT EXISTS bursar_event_store (
 *       aggregate_type  TEXT      NOT NULL,
 *       aggregate_id    TEXT      NOT NULL,
 *       version         INT       NOT NULL,
 *       name            TEXT      NOT NULL,
 *       payload         JSONB     NOT NULL,
 *       metadata        JSONB     NOT NULL,
 *       occurred_at     TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 *       PRIMARY KEY (aggregate_type, aggregate_id, version)
 *   );
 *
 *   CREATE INDEX IF NOT EXISTS bursar_evt_idx ON bursar_event_store
 *       (aggregate_type, aggregate_id, version);
 *
 * Thread-safety:
 *   All public functions are safe to call from multiple threads.  A single
 *   pthread-mutex is used to serialize access to the underlying PG connection
 *   because libpq’s async API is outside the scope of this exercise.
 *
 * Dependencies:
 *   libpq     – PostgreSQL C client library
 *   pthread   – POSIX threads (for the coarse-grained connection mutex)
 */

#ifndef EDUPAY_LEDGER_ACADEMY_BURSAR_POSTGRES_EVENT_STORE_H
#define EDUPAY_LEDGER_ACADEMY_BURSAR_POSTGRES_EVENT_STORE_H

/* ────────── Standard & System Headers ──────────────────────────────────── */
#include <assert.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <libpq-fe.h>

/* ────────── Compile-time Configuration ─────────────────────────────────── */
#ifndef PGEVENTSTORE_MAX_PAYLOAD_SIZE
#define PGEVENTSTORE_MAX_PAYLOAD_SIZE  8192  /* 8 KB JSON blob              */
#endif

#ifndef PGEVENTSTORE_MAX_METADATA_SIZE
#define PGEVENTSTORE_MAX_METADATA_SIZE 1024  /* 1 KB JSON blob              */
#endif

#define PGEVENTSTORE_TABLE_NAME "bursar_event_store"

/* ────────── Public Data Structures ─────────────────────────────────────── */

/* Domain event used by higher layers.  The payload and metadata are expected
 * to contain UTF-8 encoded JSON strings. */
typedef struct edu_domain_event {
    char      aggregate_type[64];
    char      aggregate_id[64];
    char      name[64];     /* e.g., "TuitionInvoiced"                       */
    uint32_t  version;      /* 1-based monotonically increasing              */
    time_t    timestamp;    /* seconds since Epoch                           */
    char      payload[PGEVENTSTORE_MAX_PAYLOAD_SIZE];
    char      metadata[PGEVENTSTORE_MAX_METADATA_SIZE];
} edu_domain_event_t;


/* Opaque handle representing a live connection to the Postgres-backed store.
 * The actual struct is exposed so that instructors can peek under the hood
 * during lessons. */
typedef struct pg_event_store {
    PGconn         *conn;
    pthread_mutex_t mutex;
} pg_event_store_t;


/* ────────── Helper Macros  ─────────────────────────────────────────────── */

#define PGEVENTSTORE_SUCCESS  0
#define PGEVENTSTORE_EINVAL  -1
#define PGEVENTSTORE_EVERSION -2      /* Concurrency violation               */
#define PGEVENTSTORE_EPGERR  -3
#define PGEVENTSTORE_ENOMEM  -4

#define PGEVENTSTORE_IS_OK(code) ((code) == PGEVENTSTORE_SUCCESS)

/* ────────── Internal Utility ------------------------------------------------
 * Not part of the public surface, but kept in the header so that everything
 * is contained in a single translation unit.                                   
 *                                                                           */
static inline void __pg_event_store_log(const char *level,
                                        const char *fmt, ...)
        __attribute__((format(printf, 2, 3)));

static inline void __pg_event_store_log(const char *level,
                                        const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "[%s] ", level);
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
}

/* Convert struct tm to ISO-8601 timestamp string (UTC). */
static inline void __pg_event_store_iso8601(time_t ts,
                                            char   *out,
                                            size_t  out_len)
{
    struct tm tmp;
    gmtime_r(&ts, &tmp);
    strftime(out, out_len, "%Y-%m-%dT%H:%M:%SZ", &tmp);
}

/* ────────── Connection Life-cycle  ─────────────────────────────────────── */

/* Open a new Postgres connection.  The function returns NULL on failure and
 * prints a diagnostic message to stderr. */
static inline pg_event_store_t *
pg_event_store_connect(const char *pg_conninfo)
{
    if (!pg_conninfo) {
        __pg_event_store_log("ERROR",
            "pg_event_store_connect: conninfo is NULL");
        return NULL;
    }

    pg_event_store_t *store = calloc(1, sizeof(*store));
    if (!store) {
        __pg_event_store_log("ERROR",
            "pg_event_store_connect: out of memory");
        return NULL;
    }

    store->conn = PQconnectdb(pg_conninfo);
    if (PQstatus(store->conn) != CONNECTION_OK) {
        __pg_event_store_log("ERROR",
            "PostgreSQL connection failed: %s",
            PQerrorMessage(store->conn));
        PQfinish(store->conn);
        free(store);
        return NULL;
    }

    pthread_mutex_init(&store->mutex, NULL);
    __pg_event_store_log("INFO",
        "Connected to Postgres backend for Event Store");
    return store;
}

/* Close the connection and free resources. */
static inline void
pg_event_store_disconnect(pg_event_store_t *store)
{
    if (!store) return;
    pthread_mutex_destroy(&store->mutex);
    PQfinish(store->conn);
    free(store);
}

/* ────────── Health-check -------------------------------------------------- */

/* Returns true if the underlying connection is alive. */
static inline bool
pg_event_store_is_healthy(pg_event_store_t *store)
{
    if (!store) return false;

    pthread_mutex_lock(&store->mutex);
    PGresult *res = PQexec(store->conn, "SELECT 1");
    bool ok = (PQresultStatus(res) == PGRES_TUPLES_OK);
    PQclear(res);
    pthread_mutex_unlock(&store->mutex);
    return ok;
}

/* ────────── Append Events  ─────────────────────────────────────────────── */

/* Internal helper to build parameter arrays for bulk insert */
static inline int
__pg_event_store_insert_events(PGconn *conn,
                               const char *aggregate_type,
                               const char *aggregate_id,
                               const edu_domain_event_t *events,
                               size_t event_count)
{
    /* For simplicity we insert events one-by-one; in real production systems
     * you may want to use COPY … FROM STDIN BINARY. */
    for (size_t i = 0; i < event_count; ++i) {
        const edu_domain_event_t *ev = &events[i];

        const char *paramValues[7];
        int         paramLengths[7];
        int         paramFormats[7] = {0};

        char   version_buf[16];
        char   ts_buf[32];

        snprintf(version_buf, sizeof(version_buf), "%" PRIu32, ev->version);
        __pg_event_store_iso8601(ev->timestamp, ts_buf, sizeof(ts_buf));

        paramValues[0] = aggregate_type;
        paramLengths[0] = 0;
        paramValues[1] = aggregate_id;
        paramLengths[1] = 0;
        paramValues[2] = version_buf;
        paramLengths[2] = 0;
        paramValues[3] = ev->name;
        paramLengths[3] = 0;
        paramValues[4] = ev->payload;
        paramLengths[4] = 0;
        paramValues[5] = ev->metadata;
        paramLengths[5] = 0;
        paramValues[6] = ts_buf;
        paramLengths[6] = 0;

        /*
         * Use parameterized query to avoid SQL injection risk. Note that
         * occurred_at is converted back to TIMESTAMPTZ by Postgres.
         */
        PGresult *res = PQexecParams(
            conn,
            "INSERT INTO " PGEVENTSTORE_TABLE_NAME
            " (aggregate_type, aggregate_id, version, name, payload, metadata, occurred_at) "
            "VALUES ($1, $2, $3::INT, $4, $5::JSONB, $6::JSONB, $7::Timestamptz)",
            7,               /* #params   */
            NULL,            /* param types (infer) */
            paramValues,
            paramLengths,
            paramFormats,
            0                /* text format result */
        );

        if (PQresultStatus(res) != PGRES_COMMAND_OK) {
            __pg_event_store_log("ERROR",
                "Insert failed: %s", PQerrorMessage(conn));
            PQclear(res);
            return PGEVENTSTORE_EPGERR;
        }
        PQclear(res);
    }

    return PGEVENTSTORE_SUCCESS;
}

/*
 * Append a batch of events to an aggregate stream.
 *
 * aggregate_type  – Logical bounded context (e.g., "StudentAccount")
 * aggregate_id    – Unique identifier (e.g., UUID)
 * events          – Pointer to contiguous array
 * event_count     – Number of events in the batch
 * expected_version– Expected current version before insert; use 0 for new
 *                   aggregates. If the stored version differs, the call
 *                   aborts with PGEVENTSTORE_EVERSION.
 *
 * Return codes:
 *   PGEVENTSTORE_SUCCESS   – success
 *   PGEVENTSTORE_EVERSION  – optimistic concurrency violation
 *   PGEVENTSTORE_EPGERR    – Postgres error
 *   PGEVENTSTORE_EINVAL    – invalid arguments
 */
static inline int
pg_event_store_append(pg_event_store_t        *store,
                      const char              *aggregate_type,
                      const char              *aggregate_id,
                      const edu_domain_event_t *events,
                      size_t                   event_count,
                      uint32_t                 expected_version)
{
    if (!store || !aggregate_type || !aggregate_id ||
        !events || event_count == 0) {
        return PGEVENTSTORE_EINVAL;
    }

    int rc = PGEVENTSTORE_SUCCESS;

    pthread_mutex_lock(&store->mutex);

    /* Begin transaction */
    PGresult *res = PQexec(store->conn, "BEGIN");
    if (PQresultStatus(res) != PGRES_COMMAND_OK) {
        __pg_event_store_log("ERROR", "BEGIN failed: %s",
                             PQerrorMessage(store->conn));
        PQclear(res);
        rc = PGEVENTSTORE_EPGERR;
        goto done_tx;
    }
    PQclear(res);

    /* Check current version */
    const char *parms[2] = { aggregate_type, aggregate_id };
    res = PQexecParams(
        store->conn,
        "SELECT COALESCE(MAX(version), 0) FROM " PGEVENTSTORE_TABLE_NAME
        " WHERE aggregate_type = $1 AND aggregate_id = $2 FOR UPDATE",
        2, NULL, parms, NULL, NULL, 0);

    if (PQresultStatus(res) != PGRES_TUPLES_OK) {
        __pg_event_store_log("ERROR", "Version check failed: %s",
                             PQerrorMessage(store->conn));
        PQclear(res);
        rc = PGEVENTSTORE_EPGERR;
        goto done_tx;
    }

    uint32_t current_version = (uint32_t)strtoul(PQgetvalue(res, 0, 0), NULL, 10);
    PQclear(res);

    if (current_version != expected_version) {
        rc = PGEVENTSTORE_EVERSION;
        goto done_tx;
    }

    /* Insert events */
    rc = __pg_event_store_insert_events(store->conn,
                                        aggregate_type,
                                        aggregate_id,
                                        events,
                                        event_count);
    if (rc != PGEVENTSTORE_SUCCESS)
        goto done_tx;

    /* Commit */
    res = PQexec(store->conn, "COMMIT");
    if (PQresultStatus(res) != PGRES_COMMAND_OK) {
        __pg_event_store_log("ERROR", "COMMIT failed: %s",
                             PQerrorMessage(store->conn));
        PQclear(res);
        rc = PGEVENTSTORE_EPGERR;
        goto done_tx;
    }
    PQclear(res);

done_tx:
    if (rc != PGEVENTSTORE_SUCCESS) {
        PGresult *rollback = PQexec(store->conn, "ROLLBACK");
        PQclear(rollback);
    }
    pthread_mutex_unlock(&store->mutex);
    return rc;
}

/* ────────── Load Events  ───────────────────────────────────────────────── */

/*
 * Load events for an aggregate starting from 'from_version' (inclusive).
 * The function allocates an array of events and returns it via *out_events.
 * The caller is responsible for freeing the memory using free().
 *
 * On success, returns number of events read (may be zero).
 * On failure, returns negative error code.
 */
static inline ssize_t
pg_event_store_load(pg_event_store_t   *store,
                    const char         *aggregate_type,
                    const char         *aggregate_id,
                    uint32_t            from_version,
                    edu_domain_event_t **out_events)
{
    if (!store || !aggregate_type || !aggregate_id || !out_events) {
        return PGEVENTSTORE_EINVAL;
    }

    *out_events = NULL;
    ssize_t rows = 0;
    pthread_mutex_lock(&store->mutex);

    const char *parms[3];
    char version_buf[16];
    parms[0] = aggregate_type;
    parms[1] = aggregate_id;
    snprintf(version_buf, sizeof(version_buf), "%" PRIu32, from_version);
    parms[2] = version_buf;

    PGresult *res = PQexecParams(
        store->conn,
        "SELECT version, name, payload::TEXT, metadata::TEXT, "
        "       extract(epoch from occurred_at)::BIGINT "
        "FROM " PGEVENTSTORE_TABLE_NAME " "
        "WHERE aggregate_type = $1 AND aggregate_id = $2 "
        "  AND version >= $3::INT "
        "ORDER BY version ASC",
        3, NULL, parms, NULL, NULL, 0);

    if (PQresultStatus(res) != PGRES_TUPLES_OK) {
        __pg_event_store_log("ERROR",
            "Load failed: %s", PQerrorMessage(store->conn));
        PQclear(res);
        pthread_mutex_unlock(&store->mutex);
        return PGEVENTSTORE_EPGERR;
    }

    rows = (ssize_t)PQntuples(res);
    if (rows == 0) {
        PQclear(res);
        pthread_mutex_unlock(&store->mutex);
        return 0;
    }

    edu_domain_event_t *buffer =
        calloc((size_t)rows, sizeof(edu_domain_event_t));
    if (!buffer) {
        PQclear(res);
        pthread_mutex_unlock(&store->mutex);
        return PGEVENTSTORE_ENOMEM;
    }

    for (ssize_t i = 0; i < rows; ++i) {
        edu_domain_event_t *ev = &buffer[i];
        strncpy(ev->aggregate_type, aggregate_type,
                sizeof(ev->aggregate_type)-1);
        strncpy(ev->aggregate_id, aggregate_id,
                sizeof(ev->aggregate_id)-1);

        ev->version   = (uint32_t)strtoul(PQgetvalue(res, i, 0), NULL, 10);
        strncpy(ev->name, PQgetvalue(res, i, 1), sizeof(ev->name)-1);
        strncpy(ev->payload, PQgetvalue(res, i, 2),
                sizeof(ev->payload)-1);
        strncpy(ev->metadata, PQgetvalue(res, i, 3),
                sizeof(ev->metadata)-1);

        ev->timestamp = (time_t)strtoll(PQgetvalue(res, i, 4), NULL, 10);
    }

    PQclear(res);
    pthread_mutex_unlock(&store->mutex);
    *out_events = buffer;
    return rows;
}

/* ────────── Convenience Utilities  ─────────────────────────────────────── */

/* Dump events to stdout (useful in coursework). */
static inline void
pg_event_store_debug_print(const edu_domain_event_t *events, size_t n)
{
    for (size_t i = 0; i < n; ++i) {
        const edu_domain_event_t *ev = &events[i];
        char ts[32];
        __pg_event_store_iso8601(ev->timestamp, ts, sizeof(ts));
        printf("#%zu v%u  %s  %s  %s\n"
               "    payload : %s\n"
               "    metadata: %s\n",
               i, ev->version, ts, ev->aggregate_type,
               ev->name, ev->payload, ev->metadata);
    }
}

#endif /* EDUPAY_LEDGER_ACADEMY_BURSAR_POSTGRES_EVENT_STORE_H */
