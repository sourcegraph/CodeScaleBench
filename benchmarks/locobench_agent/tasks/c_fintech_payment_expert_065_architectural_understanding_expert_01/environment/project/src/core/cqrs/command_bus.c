/*
 * =====================================================================================
 * EduPay Ledger Academy
 * File:    src/core/cqrs/command_bus.c
 * Author:  EduPay Engineering Team
 *
 * Description:
 *   Production-quality implementation of a thread-safe Command Bus for the CQRS
 *   subsystem.  The bus is able to:
 *     • Register one handler per command type/name
 *     • Dispatch commands synchronously with robust error handling
 *     • Persist an immutable audit record for each dispatch
 *     • Integrate with the optional Saga coordinator when present
 *
 *   The component is intentionally framework-agnostic to satisfy Clean
 *   Architecture rules; nothing here knows about networking, databases, or UI
 *   frameworks.  Only pure C and narrow abstractions are used so that higher
 *   layers can be swapped during coursework.
 *
 *   NOTE:
 *     –  uthash (https://troydhanson.github.io/uthash/) is used for the
 *        in-memory handler registry.  It is a single-header library that is
 *        ubiquitous in C projects and suitable for educational purposes.
 *     –  pthreads is used for coarse-grained synchronization.  If the platform
 *        does not support pthreads, wrap the mutex calls behind your own
 *        abstraction and update the macros below.
 *
 * =====================================================================================
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include <pthread.h>

#include "uthash.h"          /* Header-only hash table                           */
#include "command_bus.h"     /* Public API (exposed to the rest of the core)     */
#include "audit_trail.h"     /* Immutable ledger of domain events                */
#include "saga_coordinator.h"/* Optional distributed-transaction coordinator     */

/*-----------------------------------------------------------------------------
 * Constants & Macros
 *---------------------------------------------------------------------------*/
#define CMD_BUS_SUCCESS             (0)
#define CMD_BUS_ERR_NOMEM           (-1)
#define CMD_BUS_ERR_DUP_HANDLER     (-2)
#define CMD_BUS_ERR_UNKNOWN_CMD     (-3)
#define CMD_BUS_ERR_HANDLER_FAILED  (-4)
#define CMD_BUS_ERR_MUTEX           (-5)

/*----------------------------------------------------------------------------- 
 * Data Structures
 *---------------------------------------------------------------------------*/

/* Forward declaration for the command opaque type.  The struct is defined in
 * command_bus.h but we repeat the definition here for compilation clarity in
 * stand-alone builds. */
#ifndef EDU_PAY_COMMAND_T_DEFINED
#define EDU_PAY_COMMAND_T_DEFINED
typedef struct edu_command {
    const char *name;    /* Case-sensitive command identifier                 */
    void       *payload; /* Arbitrary user data (ownership retained by caller)*/
    size_t      bytes;   /* Size of the payload                               */
    time_t      created; /* Timestamp created w/ time(NULL)                   */
} edu_command_t;
#endif /* EDU_PAY_COMMAND_T_DEFINED */

/* Handler function signature */
typedef int (*edu_cmd_handler_fn)(const edu_command_t *cmd, void *user_ctx);

/* Internal registry entry for uthash */
typedef struct handler_entry {
    char                 *cmd_name;   /* Key: command name                     */
    edu_cmd_handler_fn    handler;    /* Business logic                        */
    UT_hash_handle        hh;         /* uthash handle                         */
} handler_entry_t;

/* Public command bus handle */
struct edu_cmd_bus {
    handler_entry_t  *registry;  /* Hash-map of command->handler               */
    pthread_mutex_t   mutex;     /* Guard for thread-safe registry access      */

    /* Optional dependencies (may be NULL) */
    saga_coord_t     *saga;      /* Distributed transaction coordinator        */
};

/*-----------------------------------------------------------------------------
 * Static helpers
 *---------------------------------------------------------------------------*/

/* Locking helpers hide pthread complexities for clarity */
static inline int bus_lock(edu_cmd_bus_t *bus)
{
    int rc = pthread_mutex_lock(&bus->mutex);
    return (rc == 0) ? CMD_BUS_SUCCESS : CMD_BUS_ERR_MUTEX;
}

static inline int bus_unlock(edu_cmd_bus_t *bus)
{
    int rc = pthread_mutex_unlock(&bus->mutex);
    return (rc == 0) ? CMD_BUS_SUCCESS : CMD_BUS_ERR_MUTEX;
}

/* Centralized function to write audit records.  Best effort; failures here
 * do NOT abort the command as the audit trail is eventually consistent. */
static void audit_dispatch(const edu_command_t *cmd, int handler_rc)
{
    audit_record_t record = {
        .timestamp      = time(NULL),
        .command_name   = cmd->name,
        .payload_size   = cmd->bytes,
        .result_code    = handler_rc
    };
    audit_trail_append(&record); /* fire-and-forget */
}

/*-------------------------------------------------------------------------
 * Public API
 *-----------------------------------------------------------------------*/

int edu_cmd_bus_init(edu_cmd_bus_t **out_bus, saga_coord_t *saga_coord)
{
    if (!out_bus) return CMD_BUS_ERR_NOMEM;

    edu_cmd_bus_t *bus = calloc(1, sizeof(*bus));
    if (!bus) return CMD_BUS_ERR_NOMEM;

    if (pthread_mutex_init(&bus->mutex, NULL) != 0) {
        free(bus);
        return CMD_BUS_ERR_MUTEX;
    }

    bus->registry = NULL;
    bus->saga     = saga_coord;
    *out_bus      = bus;

    return CMD_BUS_SUCCESS;
}

void edu_cmd_bus_destroy(edu_cmd_bus_t *bus)
{
    if (!bus) return;

    /* Free the registry */
    handler_entry_t *current, *tmp;
    HASH_ITER(hh, bus->registry, current, tmp) {
        HASH_DEL(bus->registry, current);
        free(current->cmd_name);
        free(current);
    }

    pthread_mutex_destroy(&bus->mutex);
    free(bus);
}

int edu_cmd_bus_register(edu_cmd_bus_t        *bus,
                         const char           *cmd_name,
                         edu_cmd_handler_fn    handler)
{
    if (!bus || !cmd_name || !handler) return CMD_BUS_ERR_NOMEM;

    /* Allocate registry entry */
    handler_entry_t *entry = NULL;

    /* Synchronize to avoid duplicate registration racing */
    int rc = bus_lock(bus);
    if (rc != CMD_BUS_SUCCESS) return rc;

    HASH_FIND_STR(bus->registry, cmd_name, entry);
    if (entry) {
        bus_unlock(bus);
        return CMD_BUS_ERR_DUP_HANDLER;
    }

    entry = calloc(1, sizeof(*entry));
    if (!entry) {
        bus_unlock(bus);
        return CMD_BUS_ERR_NOMEM;
    }

    entry->cmd_name = strdup(cmd_name);
    entry->handler  = handler;

    HASH_ADD_KEYPTR(hh, bus->registry, entry->cmd_name,
                    strlen(entry->cmd_name), entry);

    bus_unlock(bus);
    return CMD_BUS_SUCCESS;
}

int edu_cmd_bus_dispatch(edu_cmd_bus_t       *bus,
                         const edu_command_t *cmd,
                         void                *user_ctx)
{
    if (!bus || !cmd || !cmd->name) return CMD_BUS_ERR_UNKNOWN_CMD;

    /* Look up handler */
    handler_entry_t *entry = NULL;
    int rc = bus_lock(bus);
    if (rc != CMD_BUS_SUCCESS) return rc;

    HASH_FIND_STR(bus->registry, cmd->name, entry);
    bus_unlock(bus);

    if (!entry) return CMD_BUS_ERR_UNKNOWN_CMD;

    /* Optionally start saga (best effort) */
    saga_txn_t *saga_txn = NULL;
    if (bus->saga) {
        saga_txn = saga_coord_begin(bus->saga, cmd->name, cmd->payload);
    }

    /* Delegate to business logic */
    int handler_rc = entry->handler(cmd, user_ctx);

    /* Saga finalize */
    if (bus->saga && saga_txn) {
        if (handler_rc == CMD_BUS_SUCCESS) {
            saga_coord_commit(bus->saga, saga_txn);
        } else {
            saga_coord_rollback(bus->saga, saga_txn);
        }
    }

    /* Audit trail – do not surface failure to caller */
    audit_dispatch(cmd, handler_rc);

    return (handler_rc == 0) ? CMD_BUS_SUCCESS : CMD_BUS_ERR_HANDLER_FAILED;
}

/*-----------------------------------------------------------------------------
 * Convenience Wrappers for common patterns
 *---------------------------------------------------------------------------*/

/* Dispatch wrapper that auto-builds a command object from raw payload.
 * Intended for ergonomics in unit tests and demos. */
int edu_cmd_bus_dispatch_simple(edu_cmd_bus_t *bus,
                                const char    *cmd_name,
                                void          *payload,
                                size_t         bytes,
                                void          *user_ctx)
{
    edu_command_t cmd = {
        .name    = cmd_name,
        .payload = payload,
        .bytes   = bytes,
        .created = time(NULL)
    };
    return edu_cmd_bus_dispatch(bus, &cmd, user_ctx);
}

/* Quickly check if a handler exists for a given command.  Thread-safe. */
int edu_cmd_bus_has_handler(edu_cmd_bus_t *bus, const char *cmd_name)
{
    if (!bus || !cmd_name) return 0;

    int exists = 0;
    handler_entry_t *entry = NULL;

    if (bus_lock(bus) == CMD_BUS_SUCCESS) {
        HASH_FIND_STR(bus->registry, cmd_name, entry);
        exists = (entry != NULL);
        bus_unlock(bus);
    }
    return exists;
}
