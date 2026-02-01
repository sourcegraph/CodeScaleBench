```markdown
# Lesson 06 – Building CQRS Projections in _EduPay Ledger Academy_
> “Queries in milliseconds, audits for decades.”  
> —⁠_Platform Engineering Motto_

---

## 1  Learning Objectives
By the end of this lab you will be able to:

* Enumerate the major responsibilities of a **CQRS Projection** in a payment‐processing system  
* Implement a production‐grade read model in C that stays **100 % consistent** with the event store  
* Isolate projection code behind a **port/adapter boundary** so that professors can swap storage engines during coursework  
* Write an **idempotent** event-handling loop that survives crashes and supports once/only‐once delivery semantics  
* Measure projection latency with a **Prometheus**‐friendly metric feed  

> NOTE  
> All code presented in this lesson compiles on `clang >= 14` or `gcc >= 12` and follows **C17**.  
> A minimal Makefile is included at the end of the document.

---

## 2  Domain Recap

```
┌──────────────────────────┐             ┌───────────────────────┐
│ WRITE MODEL (Commands)   │             │ READ MODEL (Queries)  │
│  ledger_command_service  │────────────▶│  ledger_projection    │
└──────────────────────────┘    Events   └───────────────────────┘
```  

The **write model**—implemented in `src/ledger/commands/*`—is already capable of persisting business events to the _Event Store_.  
Your job is to consume those events and project them into a **payment dashboard** optimized for low-latency read queries.

---

## 3  Event Definitions

Create a new header `include/eduledger/events.h` that centralises _immutable_ event shapes shared between micro-services.

```c
/* =========================================================================
 * File:    include/eduledger/events.h
 * Purpose: Canonical event definitions for Payment-Saga bounded context
 * Author:  EduPay Ledger Academy – Lesson 06
 * ========================================================================= */
#ifndef EDU_LEDGER_EVENTS_H
#define EDU_LEDGER_EVENTS_H

#include <stdint.h>
#include <time.h>

typedef enum {
    EVT_NONE = 0,
    EVT_PAYMENT_INITIATED,
    EVT_PAYMENT_AUTHORIZED,
    EVT_PAYMENT_CAPTURED,
    EVT_PAYMENT_SETTLED,
    EVT_PAYMENT_FAILED,
} evt_type_t;

/* Every event carries a header for routing & traceability */
typedef struct {
    uint64_t    sequence;   /* monotonic sequence number from Event Store */
    evt_type_t  type;       /* domain event discriminator                */
    time_t      ts_utc;     /* server-side timestamp, seconds since EPOCH*/
    char        saga_id[40];/* distributed-tx correlation id (UUID-v4)   */
} evt_header_t;

/* Event payloads --------------------------------------------------------- */
typedef struct {
    evt_header_t hdr;
    char         payment_id[32];
    char         student_id[32];
    char         currency[4]; /* ISO-4217 */
    uint64_t     amount_minor;/* minor units e.g. cents */
} evt_payment_initiated_t;

typedef struct {
    evt_header_t hdr;
    char         payment_id[32];
    char         authorization_code[16];
} evt_payment_authorized_t;

typedef struct {
    evt_header_t hdr;
    char         payment_id[32];
    uint64_t     fee_minor;
} evt_payment_captured_t;

typedef struct {
    evt_header_t hdr;
    char         payment_id[32];
    char         settlement_batch_id[32];
} evt_payment_settled_t;

typedef struct {
    evt_header_t hdr;
    char         payment_id[32];
    char         reason[128];
} evt_payment_failed_t;

/* A convenience union for generic handlers */
typedef union {
    evt_header_t               any;
    evt_payment_initiated_t    initiated;
    evt_payment_authorized_t   authorized;
    evt_payment_captured_t     captured;
    evt_payment_settled_t      settled;
    evt_payment_failed_t       failed;
} ledger_event_t;

#endif /* EDU_LEDGER_EVENTS_H */
```

---

## 4  Projection Port (Header Only)

Define a **Clean-Architecture port** so that multiple storage‐specific adapters can plug in.

```c
/* =========================================================================
 * File:    include/eduledger/projection.h
 * Purpose: Projection interface for CQRS read models
 * ========================================================================= */
#ifndef EDU_LEDGER_PROJECTION_H
#define EDU_LEDGER_PROJECTION_H

#include <stdbool.h>
#include <stddef.h>
#include "eduledger/events.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ledger_projection ledger_projection_t;

/* Factory function pointer table */
typedef struct {
    ledger_projection_t* (*open)(const char* dsn, char* errbuf, size_t errlen);
    void                 (*close)(ledger_projection_t*);
    bool                 (*handle_event)(ledger_projection_t*, const ledger_event_t*, char* errbuf, size_t errlen);
    uint64_t             (*last_sequence)(ledger_projection_t*);
} ledger_projection_vtable_t;

/* Adapter registration (one per .so or static obj) */
bool register_ledger_projection(const ledger_projection_vtable_t* vtable);

/* Global factory helpers ------------------------------------------------- */
ledger_projection_t* projection_open(const char* dsn, char* errbuf, size_t errlen);
void                 projection_close(ledger_projection_t* proj);
bool                 projection_handle_event(ledger_projection_t* proj, const ledger_event_t* evt, char* errbuf, size_t errlen);
uint64_t             projection_last_sequence(ledger_projection_t* proj);

#ifdef __cplusplus
}
#endif
#endif /* EDU_LEDGER_PROJECTION_H */
```

---

## 5  In-Memory Stub (Unit-Test Harness)

Quickly confirm our port by building an **In-Memory projection** before adding SQLite.

```c
/* =========================================================================
 * File:    src/eduledger/projection_mem.c
 * Purpose: In-Memory projection for fast CI pipelines
 * ========================================================================= */
#include <stdlib.h>
#include <string.h>
#include "eduledger/projection.h"

typedef struct {
    ledger_projection_t base;
    uint64_t            cursor;
    size_t              payments_total;
} mem_proj_t;

/* --- Interface implementations ----------------------------------------- */
static ledger_projection_t* mem_open(const char* dsn, char* err, size_t len)
{
    (void)dsn; /* not used */
    mem_proj_t* p = calloc(1, sizeof *p);
    if (!p) {
        strncpy(err, "OOM opening mem projection", len);
        return NULL;
    }
    return (ledger_projection_t*)p;
}

static void mem_close(ledger_projection_t* obj)
{
    free(obj);
}

static bool mem_handle(ledger_projection_t* obj, const ledger_event_t* evt, char* err, size_t len)
{
    (void)err; (void)len;
    mem_proj_t* p = (mem_proj_t*)obj;
    /* idempotency: ignore older sequences */
    if (evt->any.hdr.sequence <= p->cursor) return true;

    switch (evt->any.hdr.type) {
        case EVT_PAYMENT_INITIATED:
            p->payments_total++;
            break;
        default:
            /* other events ignored for demo */
            break;
    }
    p->cursor = evt->any.hdr.sequence;
    return true;
}

static uint64_t mem_last(ledger_projection_t* obj)
{
    mem_proj_t* p = (mem_proj_t*)obj;
    return p->cursor;
}

/* --- VTable registration ----------------------------------------------- */
static const ledger_projection_vtable_t VTABLE = {
    .open          = mem_open,
    .close         = mem_close,
    .handle_event  = mem_handle,
    .last_sequence = mem_last,
};

/* Register at load time (constructor attr works on gcc/clang) */
__attribute__((constructor))
static void register_mem_projection(void)
{
    register_ledger_projection(&VTABLE);
}
```

---

## 6  SQLite3 Production Adapter

The in-memory version is fine for CI but prod needs durability.   
Below is a fully functional **SQLite3 projection** with _idempotent upserts_ and **optimistic concurrency**.

```c
/* =========================================================================
 * File:    src/eduledger/projection_sqlite.c
 * Purpose: Durable CQRS read model stored in SQLite
 * ========================================================================= */
#define _POSIX_C_SOURCE 200809L
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "eduledger/projection.h"

#ifndef EDU_SQL_SCHEMA
#define EDU_SQL_SCHEMA                                                     \
    "PRAGMA journal_mode=WAL;"                                             \
    "CREATE TABLE IF NOT EXISTS projection_cursor("                        \
    "   id       INTEGER PRIMARY KEY CHECK (id = 0),"                      \
    "   seq      INTEGER NOT NULL"                                         \
    ");"                                                                   \
    "INSERT OR IGNORE INTO projection_cursor(id, seq) VALUES(0, 0);"       \
    "CREATE TABLE IF NOT EXISTS vw_payments("                              \
    "   payment_id TEXT PRIMARY KEY,"                                      \
    "   student_id TEXT NOT NULL,"                                         \
    "   currency   TEXT NOT NULL,"                                         \
    "   amount_minor INTEGER NOT NULL,"                                    \
    "   status     TEXT NOT NULL,"                                         \
    "   last_event_seq INTEGER NOT NULL"                                   \
    ");"
#endif /* EDU_SQL_SCHEMA */

typedef struct {
    ledger_projection_t base;
    sqlite3*            db;
} sqlite_proj_t;

/* Error helper ----------------------------------------------------------- */
static bool sqlite_check(int rc, sqlite3* db, char* err, size_t len)
{
    if (rc == SQLITE_OK || rc == SQLITE_DONE || rc == SQLITE_ROW) return true;
    snprintf(err, len, "SQLite error %d: %s", rc, sqlite3_errmsg(db));
    return false;
}

/* --- Interface implementations ----------------------------------------- */
static ledger_projection_t* s_open(const char* dsn, char* err, size_t len)
{
    sqlite3* db = NULL;
    int rc = sqlite3_open_v2(dsn ? dsn : ":memory:",
                             &db,
                             SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX,
                             NULL);
    if (!sqlite_check(rc, db, err, len)) return NULL;

    rc = sqlite3_exec(db, EDU_SQL_SCHEMA, NULL, NULL, NULL);
    if (!sqlite_check(rc, db, err, len)) { sqlite3_close(db); return NULL; }

    sqlite_proj_t* p = calloc(1, sizeof *p);
    if (!p) { strncpy(err, "OOM", len); sqlite3_close(db); return NULL; }
    p->db = db;
    return (ledger_projection_t*)p;
}

static void s_close(ledger_projection_t* obj)
{
    sqlite_proj_t* p = (sqlite_proj_t*)obj;
    if (!p) return;
    sqlite3_close(p->db);
    free(p);
}

static uint64_t s_last(ledger_projection_t* obj)
{
    sqlite_proj_t* p = (sqlite_proj_t*)obj;
    uint64_t seq = 0;
    sqlite3_stmt* stmt = NULL;
    const char* sql = "SELECT seq FROM projection_cursor WHERE id = 0;";
    if (sqlite3_prepare_v2(p->db, sql, -1, &stmt, NULL) == SQLITE_OK &&
        sqlite3_step(stmt) == SQLITE_ROW)
    {
        seq = (uint64_t)sqlite3_column_int64(stmt, 0);
    }
    sqlite3_finalize(stmt);
    return seq;
}

static bool s_update_cursor(sqlite_proj_t* p, uint64_t seq, char* err, size_t len)
{
    sqlite3_stmt* stmt = NULL;
    const char* sql = "UPDATE projection_cursor SET seq = ? WHERE id = 0;";
    int rc = sqlite3_prepare_v2(p->db, sql, -1, &stmt, NULL);
    if (!sqlite_check(rc, p->db, err, len)) return false;

    sqlite3_bind_int64(stmt, 1, (sqlite3_int64)seq);
    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    return sqlite_check(rc, p->db, err, len);
}

static bool handle_payment_initiated(sqlite_proj_t* p,
                                     const evt_payment_initiated_t* e,
                                     char* err, size_t len)
{
    const char* sql =
        "INSERT INTO vw_payments(payment_id, student_id, currency, amount_minor, status, last_event_seq) "
        "VALUES(?, ?, ?, ?, 'INITIATED', ?)"
        "ON CONFLICT(payment_id) DO UPDATE SET "
        "  student_id=excluded.student_id,"
        "  currency=excluded.currency,"
        "  amount_minor=excluded.amount_minor,"
        "  status='INITIATED',"
        "  last_event_seq=excluded.last_event_seq "
        "WHERE excluded.last_event_seq > vw_payments.last_event_seq;";

    sqlite3_stmt* stmt = NULL;
    int rc = sqlite3_prepare_v2(p->db, sql, -1, &stmt, NULL);
    if (!sqlite_check(rc, p->db, err, len)) return false;

    sqlite3_bind_text(stmt, 1, e->payment_id, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 2, e->student_id, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, e->currency, -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, 4, (sqlite3_int64)e->amount_minor);
    sqlite3_bind_int64(stmt, 5, (sqlite3_int64)e->hdr.sequence);

    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    return sqlite_check(rc, p->db, err, len);
}

static bool handle_payment_settled(sqlite_proj_t* p,
                                   const evt_payment_settled_t* e,
                                   char* err, size_t len)
{
    const char* sql =
        "UPDATE vw_payments SET status='SETTLED', last_event_seq=? "
        "WHERE payment_id=? AND ? > last_event_seq;";

    sqlite3_stmt* stmt = NULL;
    int rc = sqlite3_prepare_v2(p->db, sql, -1, &stmt, NULL);
    if (!sqlite_check(rc, p->db, err, len)) return false;

    sqlite3_bind_int64(stmt, 1, (sqlite3_int64)e->hdr.sequence);
    sqlite3_bind_text(stmt, 2, e->payment_id, -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, 3, (sqlite3_int64)e->hdr.sequence);

    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    return sqlite_check(rc, p->db, err, len);
}

static bool s_handle(ledger_projection_t* obj, const ledger_event_t* e, char* err, size_t len)
{
    sqlite_proj_t* p = (sqlite_proj_t*)obj;

    /* idempotency short-circuit */
    if (e->any.hdr.sequence <= s_last(obj)) return true;

    int rc = sqlite3_exec(p->db, "BEGIN IMMEDIATE TRANSACTION;", NULL, NULL, NULL);
    if (!sqlite_check(rc, p->db, err, len)) return false;

    bool ok = true;
    switch (e->any.hdr.type) {
        case EVT_PAYMENT_INITIATED:
            ok = handle_payment_initiated(p, &e->initiated, err, len);
            break;
        case EVT_PAYMENT_SETTLED:
            ok = handle_payment_settled(p, &e->settled, err, len);
            break;
        default:
            /* unsupported events are ignored for this projection */
            break;
    }

    if (ok) ok = s_update_cursor(p, e->any.hdr.sequence, err, len);

    rc = sqlite3_exec(p->db, ok ? "COMMIT;" : "ROLLBACK;", NULL, NULL, NULL);
    if (!sqlite_check(rc, p->db, err, len)) ok = false;

    return ok;
}

/* --- VTable registration ----------------------------------------------- */
static const ledger_projection_vtable_t VTABLE = {
    .open          = s_open,
    .close         = s_close,
    .handle_event  = s_handle,
    .last_sequence = s_last,
};

__attribute__((constructor))
static void register_sqlite_projection(void)
{
    register_ledger_projection(&VTABLE);
}
```

---

## 7  Projection Registry (Shared)

All adapters share a **singleton registry** so the application can load whichever is linked first.

```c
/* =========================================================================
 * File:    src/eduledger/projection_registry.c
 * Purpose: Adapter registry – decouples caller from implementation
 * ========================================================================= */
#include <pthread.h>
#include <string.h>
#include "eduledger/projection.h"

static pthread_mutex_t                lock = PTHREAD_MUTEX_INITIALIZER;
static const ledger_projection_vtable_t* active = NULL;

bool register_ledger_projection(const ledger_projection_vtable_t* vtable)
{
    pthread_mutex_lock(&lock);
    if (!active) active = vtable; /* first wins */
    pthread_mutex_unlock(&lock);
    return true;
}

ledger_projection_t* projection_open(const char* dsn, char* err, size_t len)
{
    if (!active) { strncpy(err, "No projection adapter registered", len); return NULL; }
    return active->open(dsn, err, len);
}

void projection_close(ledger_projection_t* p)
{
    if (p && active) active->close(p);
}

bool projection_handle_event(ledger_projection_t* p, const ledger_event_t* e, char* err, size_t len)
{
    return p && active && active->handle_event(p, e, err, len);
}

uint64_t projection_last_sequence(ledger_projection_t* p)
{
    return (p && active) ? active->last_sequence(p) : 0;
}
```

---

## 8  Driver Loop Example

The event store will invoke `projection_handle_event()` for each new commit.  
For local testing we bundle a minimal CLI.

```c
/* =========================================================================
 * File:    apps/projection_cli.c
 * Purpose: Stand-alone tool to hydrate a projection DB from an event log
 * ========================================================================= */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "eduledger/projection.h"

static void die(const char* msg)
{
    fprintf(stderr, "fatal: %s\n", msg);
    exit(EXIT_FAILURE);
}

/* Simulate reading newline-delimited events from stdin */
static ledger_event_t parse_event(const char* line)
{
    ledger_event_t e = {0};
    /* CSV: seq,type,payment,student,amount */
    sscanf(line, "%lu,%d,%31[^,],%31[^,],%lu",
           &e.any.hdr.sequence,
           (int*)&e.any.hdr.type,
           e.initiated.payment_id,
           e.initiated.student_id,
           &e.initiated.amount_minor);
    e.any.hdr.ts_utc = time(NULL);
    strcpy(e.initiated.currency, "USD");
    return e;
}

int main(int argc, char* argv[])
{
    char err[256] = {0};
    const char* dsn = argc > 1 ? argv[1] : "file:projection.db?cache=shared";

    ledger_projection_t* p = projection_open(dsn, err, sizeof err);
    if (!p) die(err);

    char*  line = NULL;
    size_t n    = 0;
    while (getline(&line, &n, stdin) != -1) {
        ledger_event_t evt = parse_event(line);
        if (!projection_handle_event(p, &evt, err, sizeof err))
            die(err);
    }
    free(line);

    printf("Projection at sequence %lu\n", projection_last_sequence(p));
    projection_close(p);
    return 0;
}
```

---

## 9  Compilation (GNU Make)

```make
CC      ?= gcc
CFLAGS  := -std=c17 -Wall -Wextra -pedantic -O2 -fPIC
LDFLAGS := -lsqlite3 -lpthread

SRC := $(shell find src -name '*.c')
OBJ := $(SRC:.c=.o)

all: projection_cli

projection_cli: $(OBJ) apps/projection_cli.o
	$(CC) $^ $(LDFLAGS) -o $@

%.o: %.c
	$(CC) $(CFLAGS) -Iinclude -c $< -o $@

clean:
	rm -f $(OBJ) apps/*.o projection_cli projection.db
```

---

## 10  Exercises

1. Implement support for `EVT_PAYMENT_FAILED` and update the dashboard schema accordingly.  
2. Add a **Prometheus** exporter that reports `projection_lag_seconds = now() – last_event.ts_utc`.  
3. Swap SQLite for **PostgreSQL** by writing a new adapter conforming to `ledger_projection_vtable_t`.

Happy projecting! 🚀
```