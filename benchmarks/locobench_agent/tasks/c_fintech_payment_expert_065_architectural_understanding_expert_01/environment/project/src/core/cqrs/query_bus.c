/**
 * @file query_bus.c
 * @brief Thread-safe CQRS Query Bus implementation for EduPay Ledger Academy.
 *
 * The Query Bus is the in-process mediator responsible for dispatching *queries*
 * (read-only requests) to their registered handlers and returning the response
 * (projection) to the caller.  This component lives in the core domain layer,
 * fully isolated from transports, databases, and UI frameworks so that
 * instructors can swap peripherals without touching business rules.
 *
 * Design goals:
 *   • Zero external dependencies (POSIX & C standard libs only)                │
 *   • Thread-safe, lock-protected handler registry                             │
 *   • Fast O(N) lookup (N is usually tiny; a campus rarely has thousands of
 *     query types).  The implementation can be swapped for a hashmap in
 *     coursework focused on data structures or performance tuning.             │
 *   • Production-grade diagnostics via syslog                                  │
 *   • Strong input validation & error propagation                              │
 *
 * Copyright © 2023-2024
 * SPDX-License-Identifier: MIT
 */
#include "query_bus.h"          /* Public API & type declarations            */
#include <errno.h>              /* errno, EINVAL, EEXIST, ENOMEM, ESRCH      */
#include <pthread.h>            /* pthread_mutex_*                           */
#include <stdlib.h>             /* malloc, free, realloc                     */
#include <string.h>             /* memset, memcpy                            */
#include <syslog.h>             /* syslog, openlog                           */

/*--------------- Internal structures ---------------------------------------*/
#define QB_GROWTH_FACTOR 16U    /* How many slots to add when expanding      */

/*
 * Registry entry that ties an opaque query type identifier to its handler
 * function pointer.  Consumers interact with the opaque handle defined
 * in query_bus.h; the internal representation is kept private to maintain
 * encapsulation.
 */
typedef struct
{
    query_type_id_t    type_id; /* User-defined enum or hash of query name   */
    qb_handler_fn      fn;      /* Business logic function pointer           */
} qb_registry_entry_t;

/*--------------- Static (file-scope) state ---------------------------------*/
static qb_registry_entry_t *s_registry     = NULL;
static size_t               s_reg_count    = 0;
static size_t               s_reg_capacity = 0;

static pthread_mutex_t      s_mutex        = PTHREAD_MUTEX_INITIALIZER;
static int                  s_syslog_open  = 0;

/*--------------- Utility helpers ------------------------------------------*/
static void qb_log(int priority, const char *fmt, ...)
{
    if (!s_syslog_open)
    {
        /* Tag program name once per process. */
        openlog("EduPayLedger.QueryBus", LOG_PID | LOG_NDELAY, LOG_USER);
        s_syslog_open = 1;
    }

    va_list ap;
    va_start(ap, fmt);
    vsyslog(priority, fmt, ap);
    va_end(ap);
}

/* Ensure capacity for at least one more entry. */
static int qb_ensure_capacity(size_t needed)
{
    if (s_reg_capacity >= needed)
        return 0;

    size_t new_cap = s_reg_capacity == 0
                         ? QB_GROWTH_FACTOR
                         : s_reg_capacity + QB_GROWTH_FACTOR;

    qb_registry_entry_t *tmp =
        realloc(s_registry, new_cap * sizeof(qb_registry_entry_t));
    if (!tmp)
        return ENOMEM;

    s_registry     = tmp;
    s_reg_capacity = new_cap;
    return 0;
}

/*--------------- Public API implementation --------------------------------*/
int qb_register_handler(query_type_id_t type_id, qb_handler_fn handler)
{
    if (!handler)
        return EINVAL;

    int rc = 0;
    pthread_mutex_lock(&s_mutex);

    /* Reject duplicate registrations */
    for (size_t i = 0; i < s_reg_count; ++i)
    {
        if (s_registry[i].type_id == type_id)
        {
            rc = EEXIST;
            goto unlock;
        }
    }

    /* Grow registry if needed */
    if ((rc = qb_ensure_capacity(s_reg_count + 1)) != 0)
        goto unlock;

    /* Insert new entry */
    s_registry[s_reg_count].type_id = type_id;
    s_registry[s_reg_count].fn      = handler;
    ++s_reg_count;

    qb_log(LOG_INFO, "Registered QueryHandler for type_id=%u (total=%zu)",
           (unsigned)type_id, s_reg_count);

unlock:
    pthread_mutex_unlock(&s_mutex);
    return rc;
}

int qb_execute(query_type_id_t type_id,
               const void     *query,
               void           *response,
               char           *err_buf,
               size_t          err_buf_size)
{
    if (!query || !response)
        return EINVAL;

    pthread_mutex_lock(&s_mutex);

    qb_handler_fn handler = NULL;
    for (size_t i = 0; i < s_reg_count; ++i)
    {
        if (s_registry[i].type_id == type_id)
        {
            handler = s_registry[i].fn;
            break;
        }
    }

    pthread_mutex_unlock(&s_mutex);

    if (!handler)
    {
        if (err_buf && err_buf_size > 0)
        {
            snprintf(err_buf, err_buf_size,
                     "No handler registered for query type %u",
                     (unsigned)type_id);
        }
        qb_log(LOG_ERR, "Dispatch failed: Unknown query type_id=%u",
               (unsigned)type_id);
        return ESRCH;
    }

    /* Business logic may set errno; capture the return code. */
    int rc = handler(query, response, err_buf, err_buf_size);

    if (rc != 0)
    {
        qb_log(LOG_WARNING,
               "Query handler for type_id=%u returned error=%d ('%s')",
               (unsigned)type_id, rc,
               (err_buf && err_buf_size > 0) ? err_buf : "no message");
    }

    return rc;
}

void qb_shutdown(void)
{
    pthread_mutex_lock(&s_mutex);

    free(s_registry);
    s_registry     = NULL;
    s_reg_count    = 0;
    s_reg_capacity = 0;

    pthread_mutex_unlock(&s_mutex);

    if (s_syslog_open)
    {
        qb_log(LOG_INFO, "QueryBus shutdown, registry cleared");
        closelog();
        s_syslog_open = 0;
    }
}

/*--------------- Optional convenience bootstrap ---------------------------*/
/**
 * @brief Register multiple handlers in one call.
 *
 * The typical usage scenario in unit tests or service startup code.
 */
int qb_register_handlers(const qb_handler_binding_t *bindings, size_t count)
{
    if (!bindings && count > 0)
        return EINVAL;

    int rc;
    for (size_t i = 0; i < count; ++i)
    {
        rc = qb_register_handler(bindings[i].type_id, bindings[i].fn);
        if (rc != 0)
            return rc;
    }
    return 0;
}

/*--------------- End of file ----------------------------------------------*/
