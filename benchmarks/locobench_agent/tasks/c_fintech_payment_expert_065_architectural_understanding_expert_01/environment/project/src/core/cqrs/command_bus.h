#ifndef EDUPAY_LEDGER_ACADEMY_CORE_CQRS_COMMAND_BUS_H
#define EDUPAY_LEDGER_ACADEMY_CORE_CQRS_COMMAND_BUS_H
/*
 * EduPay Ledger Academy
 * ------------------------------------------------------------
 * command_bus.h
 *
 * A minimal yet production-grade Command Bus implementation
 * suitable for CQRS-based, Clean-Architecture C projects.
 *
 * The bus offers:
 *  • Dynamic registration / deregistration of command handlers
 *  • Thread-safe dispatching with read/write locks
 *  • Opaque types and clear error codes for a stable API surface
 *  • No external dependencies beyond POSIX pthreads / libc
 *
 * Copyright (c) 2024
 * SPDX-License-Identifier: MIT
 */

#include <stddef.h>   /* size_t   */
#include <stdint.h>   /* uint32_t */
#include <sys/types.h>

#ifdef __cplusplus
extern "C" {
#endif

/* --------------------------------------------------------------------------
 * Public error codes
 * -------------------------------------------------------------------------- */
typedef enum {
    EDU_CMD_SUCCESS   = 0,   /* No error                                */
    EDU_CMD_EINVAL    = -1,  /* Invalid argument                        */
    EDU_CMD_ENOMEM    = -2,  /* Allocation failure                      */
    EDU_CMD_EEXISTS   = -3,  /* Handler already registered              */
    EDU_CMD_ENOHANDLER= -4,  /* No handler registered for given command */
    EDU_CMD_EHANDLER  = -5   /* Handler returned error                  */
} edu_cmd_status_t;

/* --------------------------------------------------------------------------
 * Command DTO
 * -------------------------------------------------------------------------- */
typedef struct edu_command {
    const char *name;      /* Command name / key, zero-terminated       */
    const void *payload;   /* Optional pointer to immutable payload     */
    size_t      payload_sz;/* Payload size in bytes                     */
} edu_command_t;

/* --------------------------------------------------------------------------
 * Forward declarations
 * -------------------------------------------------------------------------- */
struct edu_command_bus;                     /* Opaque handle */
typedef struct edu_command_bus edu_command_bus_t;

/* Signature every command handler must implement.
 * Return EDU_CMD_SUCCESS or any negative edu_cmd_status_t code.
 */
typedef int (*edu_command_handler_fn)(const edu_command_t *cmd,
                                      void *ctx);

/* --------------------------------------------------------------------------
 * Lifecycle
 * -------------------------------------------------------------------------- */

/* Create a new command bus instance.
 * Returns EDU_CMD_SUCCESS on success, otherwise an error code.
 * On success, *out_bus will be set to a valid handle that must be destroyed
 * with edu_command_bus_destroy().
 */
int edu_command_bus_create(edu_command_bus_t **out_bus);

/* Destroy a command bus and free all associated resources.
 * No-op if bus is NULL.
 */
void edu_command_bus_destroy(edu_command_bus_t *bus);

/* --------------------------------------------------------------------------
 * Registration
 * -------------------------------------------------------------------------- */

/* Register a handler for a given command name.
 * A deep copy of `command_name` is stored internally, so the caller
 * may release it after the call returns.
 *
 * Returns:
 *  • EDU_CMD_SUCCESS  => registration successful
 *  • EDU_CMD_EEXISTS  => a handler for the command already exists
 *  • EDU_CMD_ENOMEM   => allocation failure
 *  • EDU_CMD_EINVAL   => invalid argument(s)
 */
int edu_command_bus_register(edu_command_bus_t     *bus,
                             const char            *command_name,
                             edu_command_handler_fn handler,
                             void                  *ctx);

/* Unregister an existing handler for the command.
 * Returns EDU_CMD_SUCCESS if the handler was removed, or EDU_CMD_ENOHANDLER
 * if none was found.
 */
int edu_command_bus_unregister(edu_command_bus_t *bus,
                               const char        *command_name);

/* --------------------------------------------------------------------------
 * Dispatching
 * -------------------------------------------------------------------------- */

/* Dispatch a command.
 * Looks up the corresponding handler and invokes it with the provided
 * payload. Thread-safe; multiple concurrent dispatchers are allowed.
 *
 * Returns:
 *  • EDU_CMD_SUCCESS     => handler executed and returned success
 *  • EDU_CMD_ENOHANDLER  => no registered handler
 *  • EDU_CMD_EHANDLER    => handler ran but indicated failure
 */
int edu_command_bus_dispatch(edu_command_bus_t *bus,
                             const edu_command_t *cmd);

/* --------------------------------------------------------------------------
 * Utilities
 * -------------------------------------------------------------------------- */

/* Convert an edu_cmd_status_t to a human-readable, static error string. */
const char *edu_command_bus_strerror(int code);

#ifdef __cplusplus
}
#endif

/* --------------------------------------------------------------------------
 * Implementation
 * -------------------------------------------------------------------------- */
#ifdef EDUPAY_COMMAND_BUS_IMPLEMENTATION
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

/* --- Internal helpers ---------------------------------------------------- */
static char *edu__strdup(const char *src)
{
#if defined(_POSIX_C_SOURCE) && _POSIX_C_SOURCE >= 200809L
    return src ? strdup(src) : NULL;
#else
    if (!src) return NULL;
    size_t len = strlen(src) + 1;
    char *dst  = (char *)malloc(len);
    if (dst) memcpy(dst, src, len);
    return dst;
#endif
}

/* Linked-list node mapping command_name → handler                       */
typedef struct edu_cmd_subscription {
    char                         *command_name;
    edu_command_handler_fn        handler;
    void                         *ctx;
    struct edu_cmd_subscription  *next;
} edu_cmd_subscription_t;

struct edu_command_bus {
    edu_cmd_subscription_t *subs;  /* Head of linked list               */
    pthread_rwlock_t        lock;  /* Guards subs list                  */
};

/* ------------------------------------------------------------------------ */
int edu_command_bus_create(edu_command_bus_t **out_bus)
{
    if (!out_bus) return EDU_CMD_EINVAL;

    edu_command_bus_t *bus = (edu_command_bus_t *)calloc(1, sizeof(*bus));
    if (!bus) return EDU_CMD_ENOMEM;

    if (pthread_rwlock_init(&bus->lock, NULL) != 0) {
        free(bus);
        return EDU_CMD_ENOMEM;
    }

    *out_bus = bus;
    return EDU_CMD_SUCCESS;
}

/* ------------------------------------------------------------------------ */
static void edu__free_subscriptions(edu_cmd_subscription_t *node)
{
    while (node) {
        edu_cmd_subscription_t *next = node->next;
        free(node->command_name);
        free(node);
        node = next;
    }
}

void edu_command_bus_destroy(edu_command_bus_t *bus)
{
    if (!bus) return;

    pthread_rwlock_wrlock(&bus->lock);
    edu__free_subscriptions(bus->subs);
    bus->subs = NULL;
    pthread_rwlock_unlock(&bus->lock);

    pthread_rwlock_destroy(&bus->lock);
    free(bus);
}

/* ------------------------------------------------------------------------ */
int edu_command_bus_register(edu_command_bus_t     *bus,
                             const char            *command_name,
                             edu_command_handler_fn handler,
                             void                  *ctx)
{
    if (!bus || !command_name || !handler) return EDU_CMD_EINVAL;

    int rc = pthread_rwlock_wrlock(&bus->lock);
    if (rc != 0) return EDU_CMD_ENOMEM;

    /* Check for duplicates */
    for (edu_cmd_subscription_t *p = bus->subs; p; p = p->next) {
        if (strcmp(p->command_name, command_name) == 0) {
            pthread_rwlock_unlock(&bus->lock);
            return EDU_CMD_EEXISTS;
        }
    }

    edu_cmd_subscription_t *node =
        (edu_cmd_subscription_t *)calloc(1, sizeof(*node));
    if (!node) {
        pthread_rwlock_unlock(&bus->lock);
        return EDU_CMD_ENOMEM;
    }

    node->command_name = edu__strdup(command_name);
    if (!node->command_name) {
        free(node);
        pthread_rwlock_unlock(&bus->lock);
        return EDU_CMD_ENOMEM;
    }

    node->handler = handler;
    node->ctx     = ctx;

    /* Insert at list head for O(1) add */
    node->next    = bus->subs;
    bus->subs     = node;

    pthread_rwlock_unlock(&bus->lock);
    return EDU_CMD_SUCCESS;
}

/* ------------------------------------------------------------------------ */
int edu_command_bus_unregister(edu_command_bus_t *bus,
                               const char        *command_name)
{
    if (!bus || !command_name) return EDU_CMD_EINVAL;

    int rc = pthread_rwlock_wrlock(&bus->lock);
    if (rc != 0) return EDU_CMD_ENOMEM;

    edu_cmd_subscription_t *prev = NULL, *cur = bus->subs;
    while (cur) {
        if (strcmp(cur->command_name, command_name) == 0) {
            if (prev) prev->next = cur->next;
            else      bus->subs  = cur->next;

            free(cur->command_name);
            free(cur);
            pthread_rwlock_unlock(&bus->lock);
            return EDU_CMD_SUCCESS;
        }
        prev = cur;
        cur  = cur->next;
    }

    pthread_rwlock_unlock(&bus->lock);
    return EDU_CMD_ENOHANDLER;
}

/* ------------------------------------------------------------------------ */
int edu_command_bus_dispatch(edu_command_bus_t *bus,
                             const edu_command_t *cmd)
{
    if (!bus || !cmd || !cmd->name) return EDU_CMD_EINVAL;

    int rc = pthread_rwlock_rdlock(&bus->lock);
    if (rc != 0) return EDU_CMD_ENOMEM;

    edu_cmd_subscription_t *sub = NULL;
    for (edu_cmd_subscription_t *p = bus->subs; p; p = p->next) {
        if (strcmp(p->command_name, cmd->name) == 0) {
            sub = p;
            break;
        }
    }

    /* Copy handler/ctx under lock, then release before invocation
     * to avoid deadlocks in case handler re-enters the bus. */
    edu_command_handler_fn handler = NULL;
    void *ctx = NULL;

    if (sub) {
        handler = sub->handler;
        ctx     = sub->ctx;
    }

    pthread_rwlock_unlock(&bus->lock);

    if (!handler) return EDU_CMD_ENOHANDLER;

    int h_rc = handler(cmd, ctx);
    return (h_rc == EDU_CMD_SUCCESS) ? EDU_CMD_SUCCESS : EDU_CMD_EHANDLER;
}

/* ------------------------------------------------------------------------ */
const char *edu_command_bus_strerror(int code)
{
    switch (code) {
        case EDU_CMD_SUCCESS:    return "success";
        case EDU_CMD_EINVAL:     return "invalid argument";
        case EDU_CMD_ENOMEM:     return "out of memory";
        case EDU_CMD_EEXISTS:    return "handler already registered";
        case EDU_CMD_ENOHANDLER: return "no handler registered";
        case EDU_CMD_EHANDLER:   return "handler reported error";
        default:                 return "unknown error";
    }
}

#endif /* EDUPAY_COMMAND_BUS_IMPLEMENTATION */
#endif /* EDUPAY_LEDGER_ACADEMY_CORE_CQRS_COMMAND_BUS_H */
