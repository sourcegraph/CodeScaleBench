/*
 * EduPay Ledger Academy
 * ---------------------
 * Bursar Service · Persistent Event Store (PostgreSQL)
 *
 * File:    src/services/bursar_service/infrastructure/persistence/postgres_event_store.c
 * Author:  Core Platform Team <core@edupay-ledger.academy>
 *
 * Synopsis
 * --------
 * A production-grade implementation of the Event-Sourcing persistence layer
 * backed by PostgreSQL.  This module is responsible for:
 *
 *   • Appending domain events to an immutable ledger table.
 *   • Loading event streams to reconstruct aggregate state.
 *   • Guarding optimistic-concurrency via versioned streams.
 *   • Shielding higher layers from DB-specific details (Clean Architecture).
 *
 * The public API is intentionally small; callers interact with pure C structs
 * and functions, not libpq internals.  All resources are RAII-style and safe
 * for multi-threaded use when each thread owns its own pg_event_store_t.
 *
 * Schema (DDL excerpt)
 * --------------------
 *   CREATE SCHEMA IF NOT EXISTS bursar;
 *
 *   CREATE TABLE IF NOT EXISTS bursar.event_store
 *   (
 *       stream_id      UUID         NOT NULL,
 *       stream_version INT          NOT NULL,
 *       event_id       UUID         NOT NULL,
 *       event_type     TEXT         NOT NULL,
 *       event_payload  JSONB        NOT NULL,
 *       occurred_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
 *       PRIMARY KEY (stream_id, stream_version),
 *       UNIQUE  (event_id)
 *   );
 *
 * Indexing and partitioning considerations are omitted for brevity.
 */

#include <assert.h>
#include <inttypes.h>
#include <libpq-fe.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <uuid/uuid.h>

#include "postgres_event_store.h"

/* ────────────────────────────────────────────────────────────────────────── */
/* Internal constants                                                        */

#define MAX_EVENT_TYPE_LEN 128
#define SQL_STATE_CONCURRENCY "23505" /* unique_violation */

/* Prepared-statement identifiers */
static const char *STMT_APPEND_EVENT =
    "bursar_append_event_v1";
static const char *STMT_LOAD_STREAM =
    "bursar_load_stream_v1";

/* ────────────────────────────────────────────────────────────────────────── */
/* Domain model abstractions                                                 */

typedef struct
{
    uuid_t id;                           /* Globally unique event identifier   */
    char   type[MAX_EVENT_TYPE_LEN + 1]; /* e.g., TuitionCharged               */
    char  *payload;                      /* JSON string, heap-allocated        */
} domain_event_t;

typedef struct
{
    domain_event_t *items;
    size_t          count;
} domain_event_array_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Infrastructure                                                            */

struct pg_event_store
{
    PGconn *conn;
    char   *connection_uri;
    pthread_mutex_t mutex; /* ensures thread-local safety for prepared stmts */
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Forward declarations                                                      */

static bool ensure_connection(pg_event_store_t *store);
static bool prepare_statements(pg_event_store_t *store);
static void clear_events(domain_event_array_t *array);

/* ────────────────────────────────────────────────────────────────────────── */
/* Public API                                                                */

pg_event_store_t *
pg_event_store_create(const char *connection_uri)
{
    pg_event_store_t *store = calloc(1, sizeof *store);
    if (!store) return NULL;

    store->connection_uri = strdup(connection_uri);
    pthread_mutex_init(&store->mutex, NULL);

    if (!ensure_connection(store)) {
        pg_event_store_destroy(store);
        return NULL;
    }
    if (!prepare_statements(store)) {
        pg_event_store_destroy(store);
        return NULL;
    }
    return store;
}

void
pg_event_store_destroy(pg_event_store_t *store)
{
    if (!store) return;

    if (store->conn) {
        PQfinish(store->conn);
    }
    free(store->connection_uri);
    pthread_mutex_destroy(&store->mutex);
    free(store);
}

/*
 * Append events to a stream.
 *
 * Parameters:
 *   stream_id        – UUID of the aggregate root.
 *   expected_version – Concurrency check.  Pass 0 for brand-new streams.
 *   events           – Array of events to commit in order.
 *   n_events         – # of events (must be > 0).
 *
 * Returns:
 *   PG_EVENT_STORE_OK                 on success
 *   PG_EVENT_STORE_ERR_CONCURRENCY    if version conflict detected
 *   PG_EVENT_STORE_ERR_IO             on I/O or network failure
 *   PG_EVENT_STORE_ERR_UNEXPECTED     on any other error
 */
pg_event_store_rc_t
pg_event_store_append(pg_event_store_t       *store,
                      const uuid_t            stream_id,
                      uint32_t                expected_version,
                      const domain_event_t   *events,
                      size_t                  n_events)
{
    assert(store && events && n_events > 0);

    if (!ensure_connection(store)) return PG_EVENT_STORE_ERR_IO;

    PGconn *conn = store->conn;
    PGresult *res = NULL;

    /* Begin a transaction block (REPEATABLE READ for safety) */
    res = PQexec(conn, "BEGIN");
    if (PQresultStatus(res) != PGRES_COMMAND_OK) goto io_error;
    PQclear(res);

    /* Append each event with proper stream_version sequencing */
    for (size_t i = 0; i < n_events; ++i) {
        const uint32_t next_version = expected_version + (uint32_t)i + 1;

        /* Convert binary UUID to string */
        char stream_id_str[37], event_id_str[37];
        uuid_unparse_lower(stream_id, stream_id_str);
        uuid_unparse_lower(events[i].id, event_id_str);

        const char *params[5];
        int         param_lens[5];
        int         param_formats[5] = {0, 0, 0, 0, 0}; /* text format */

        char version_buf[12];
        snprintf(version_buf, sizeof version_buf, "%" PRIu32, next_version);

        params[0] = stream_id_str;
        params[1] = version_buf;
        params[2] = event_id_str;
        params[3] = events[i].type;
        params[4] = events[i].payload;

        param_lens[0] = (int)strlen(params[0]);
        param_lens[1] = (int)strlen(params[1]);
        param_lens[2] = (int)strlen(params[2]);
        param_lens[3] = (int)strlen(params[3]);
        param_lens[4] = (int)strlen(params[4]);

        res = PQexecPrepared(conn,
                             STMT_APPEND_EVENT,
                             5,
                             params,
                             param_lens,
                             param_formats,
                             0); /* text results */
        if (PQresultStatus(res) != PGRES_COMMAND_OK) {
            if (strcmp(PQresultErrorField(res, PG_DIAG_SQLSTATE),
                       SQL_STATE_CONCURRENCY) == 0) {
                PQclear(res);
                PQexec(conn, "ROLLBACK");
                return PG_EVENT_STORE_ERR_CONCURRENCY;
            }
            goto io_error;
        }
        PQclear(res);
    }

    res = PQexec(conn, "COMMIT");
    if (PQresultStatus(res) != PGRES_COMMAND_OK) goto io_error;
    PQclear(res);

    return PG_EVENT_STORE_OK;

io_error:
    if (res) {
        fprintf(stderr, "[event_store] append failure: %s\n",
                PQerrorMessage(conn));
        PQclear(res);
    }
    PQexec(conn, "ROLLBACK");
    return PG_EVENT_STORE_ERR_IO;
}

/*
 * Load all events of a stream starting from a given version (1-based).
 *
 * The caller takes ownership of the returned domain_event_array_t and is
 * responsible for freeing its contents via pg_event_store_free_events().
 */
pg_event_store_rc_t
pg_event_store_load(pg_event_store_t       *store,
                    const uuid_t            stream_id,
                    uint32_t                from_version,
                    domain_event_array_t   *out_events)
{
    assert(store && out_events);

    memset(out_events, 0, sizeof *out_events);

    if (!ensure_connection(store)) return PG_EVENT_STORE_ERR_IO;

    char stream_id_str[37], from_version_buf[12];
    uuid_unparse_lower(stream_id, stream_id_str);
    snprintf(from_version_buf, sizeof from_version_buf, "%" PRIu32,
             (from_version == 0) ? 1 : from_version);

    const char *params[2]        = {stream_id_str, from_version_buf};
    int         param_lens[2]    = {(int)strlen(params[0]),
                                    (int)strlen(params[1])};
    int         param_formats[2] = {0, 0};

    PGresult *res = PQexecPrepared(store->conn,
                                   STMT_LOAD_STREAM,
                                   2,
                                   params,
                                   param_lens,
                                   param_formats,
                                   0); /* text results */

    if (PQresultStatus(res) != PGRES_TUPLES_OK) {
        PQclear(res);
        return PG_EVENT_STORE_ERR_IO;
    }

    const int rows = PQntuples(res);
    if (rows == 0) {
        PQclear(res);
        return PG_EVENT_STORE_OK; /* empty stream */
    }

    /* Allocate contiguous array */
    domain_event_t *events =
        calloc((size_t)rows, sizeof *events);
    if (!events) {
        PQclear(res);
        return PG_EVENT_STORE_ERR_UNEXPECTED;
    }

    for (int i = 0; i < rows; ++i) {
        /* Column ordinals must match the SELECT projection in prepare_statements() */
        const char *event_id_txt  = PQgetvalue(res, i, 0);
        const char *event_type    = PQgetvalue(res, i, 1);
        const char *event_payload = PQgetvalue(res, i, 2);

        uuid_parse(event_id_txt, events[i].id);
        strncpy(events[i].type, event_type, MAX_EVENT_TYPE_LEN);
        events[i].type[MAX_EVENT_TYPE_LEN] = '\0';
        events[i].payload = strdup(event_payload);
    }

    PQclear(res);

    out_events->items = events;
    out_events->count = (size_t)rows;

    return PG_EVENT_STORE_OK;
}

void
pg_event_store_free_events(domain_event_array_t *array)
{
    if (!array || !array->items) return;

    for (size_t i = 0; i < array->count; ++i) {
        free(array->items[i].payload);
    }
    free(array->items);
    array->items = NULL;
    array->count = 0;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Internal helpers                                                          */

static bool
ensure_connection(pg_event_store_t *store)
{
    if (store->conn && PQstatus(store->conn) == CONNECTION_OK) return true;

    if (store->conn) {
        PQfinish(store->conn);
        store->conn = NULL;
    }
    store->conn = PQconnectdb(store->connection_uri);
    if (PQstatus(store->conn) != CONNECTION_OK) {
        fprintf(stderr, "[event_store] connection failed: %s\n",
                PQerrorMessage(store->conn));
        return false;
    }
    return prepare_statements(store);
}

static bool
prepare_statements(pg_event_store_t *store)
{
    pthread_mutex_lock(&store->mutex);

    /* Idempotent: prepared statements are connection-bound; skip if existing. */
    PGresult *res = PQdescribePrepared(store->conn, STMT_APPEND_EVENT);
    if (PQresultStatus(res) == PGRES_COMMAND_OK) {
        /* Already prepared; no further action. */
        PQclear(res);
        pthread_mutex_unlock(&store->mutex);
        return true;
    }
    PQclear(res);

    /* 1. Append event */
    const char *sql_append =
        "INSERT INTO bursar.event_store "
        "(stream_id, stream_version, event_id, event_type, event_payload) "
        "VALUES ($1::uuid, $2::int, $3::uuid, $4::text, $5::jsonb)";

    res = PQprepare(store->conn,
                    STMT_APPEND_EVENT,
                    sql_append,
                    5,
                    NULL);
    if (PQresultStatus(res) != PGRES_COMMAND_OK) {
        fprintf(stderr, "[event_store] prepare append failed: %s\n",
                PQerrorMessage(store->conn));
        PQclear(res);
        pthread_mutex_unlock(&store->mutex);
        return false;
    }
    PQclear(res);

    /* 2. Load stream */
    const char *sql_load =
        "SELECT event_id::text, event_type, event_payload::text "
        "FROM bursar.event_store "
        "WHERE stream_id = $1::uuid AND stream_version >= $2::int "
        "ORDER BY stream_version ASC";

    res = PQprepare(store->conn,
                    STMT_LOAD_STREAM,
                    sql_load,
                    2,
                    NULL);
    if (PQresultStatus(res) != PGRES_COMMAND_OK) {
        fprintf(stderr, "[event_store] prepare load failed: %s\n",
                PQerrorMessage(store->conn));
        PQclear(res);
        pthread_mutex_unlock(&store->mutex);
        return false;
    }
    PQclear(res);

    pthread_mutex_unlock(&store->mutex);
    return true;
}

static void
clear_events(domain_event_array_t *array)
{
    pg_event_store_free_events(array);
}

/* ────────────────────────────────────────────────────────────────────────── */
/* End of file                                                               */
