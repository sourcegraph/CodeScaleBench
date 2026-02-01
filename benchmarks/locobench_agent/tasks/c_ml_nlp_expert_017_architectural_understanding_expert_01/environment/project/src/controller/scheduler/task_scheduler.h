/**
 * SPDX-FileCopyrightText: 2024 LexiLearn
 * SPDX-License-Identifier: MIT
 *
 * File:    task_scheduler.h
 * Author:  LexiLearn Orchestrator Team <dev@lexilearn.ai>
 * Brief:   Thread-safe task-scheduling engine used by the Controller layer to
 *          coordinate ingest, training, tuning, and monitoring pipelines.
 *
 * NOTE:
 *      You are looking at the public interface only.  The implementation lives in
 *      task_scheduler.c and is intentionally encapsulated to keep the ABI stable.
 */

#ifndef LEXILEARN_CONTROLLER_SCHEDULER_TASK_SCHEDULER_H
#define LEXILEARN_CONTROLLER_SCHEDULER_TASK_SCHEDULER_H

/*--------------------------------------------------------------------------*/
/*  Standard Library                                                         */
/*--------------------------------------------------------------------------*/
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>

#if __STDC_VERSION__ >= 201112L
#   include <stdatomic.h>   /* Exposed for the user’s convenience           */
#endif

#ifdef __cplusplus
extern "C" {
#endif

/*--------------------------------------------------------------------------*/
/*  Constants & Macros                                                      */
/*--------------------------------------------------------------------------*/

/* Maximum length (including terminating '\0') of task identifiers.         */
#define LXL_TASK_ID_MAX     64U
/* Maximum length (including terminating '\0') of a human-readable task name.*/
#define LXL_TASK_NAME_MAX   128U

/* The default number of worker threads if the client passes 0 to _create().*/
#define LXL_SCHED_DEFAULT_WORKERS 4U

/* Forward-declaration helper for opaque scheduler handle.                  */
typedef struct lxl_task_scheduler lxl_task_scheduler_t;

/*--------------------------------------------------------------------------*/
/*  Return codes                                                            */
/*--------------------------------------------------------------------------*/
typedef enum lxl_sched_rc
{
    LXL_SCHED_OK               =  0,  /* Success                            */
    LXL_SCHED_ERR_INVALID_ARG  = -1,  /* Bad input parameter                */
    LXL_SCHED_ERR_NO_MEMORY    = -2,  /* Allocation failure                 */
    LXL_SCHED_ERR_EXISTS       = -3,  /* Task with same ID already exists   */
    LXL_SCHED_ERR_NOT_FOUND    = -4,  /* Unknown task ID                    */
    LXL_SCHED_ERR_INTERNAL     = -5   /* Unexpected internal failure        */
} lxl_sched_rc_e;

/*--------------------------------------------------------------------------*/
/*  Task Execution Callback                                                 */
/*--------------------------------------------------------------------------*/
/**
 * typedef lxl_task_fn_t
 *
 * @brief   User-supplied function that will be executed by the scheduler.
 *          The function MUST be thread-safe.
 *
 * @param   user_ctx    The context pointer provided when the task was scheduled.
 *
 * @note    The callback must not call any blocking scheduler APIs (except the
 *          observer API) to avoid deadlocks.
 */
typedef void (*lxl_task_fn_t)(void *user_ctx);

/*--------------------------------------------------------------------------*/
/*  Event Notifications (Observer Pattern)                                  */
/*--------------------------------------------------------------------------*/
typedef enum lxl_sched_event
{
    LXL_SCHED_EVENT_TASK_START    = 0,
    LXL_SCHED_EVENT_TASK_SUCCESS  = 1,
    LXL_SCHED_EVENT_TASK_FAILURE  = 2,
    LXL_SCHED_EVENT_TASK_CANCEL   = 3
} lxl_sched_event_e;

/**
 * typedef lxl_sched_event_cb_t
 *
 * @brief   Observer callback invoked on task-lifecycle events.
 *
 * @param   task_id     NULL-terminated task identifier.
 * @param   task_name   Human-readable task name (may be empty string).
 * @param   event       One of lxl_sched_event_e.
 * @param   user_ctx    Pointer registered via lxl_task_scheduler_register_observer().
 */
typedef void (*lxl_sched_event_cb_t)(const char      *task_id,
                                     const char      *task_name,
                                     lxl_sched_event_e event,
                                     void            *user_ctx);

/*--------------------------------------------------------------------------*/
/*  Public API                                                              */
/*--------------------------------------------------------------------------*/

/**
 * lxl_task_scheduler_create
 *
 * Create a scheduler instance with the given number of worker threads.
 *
 * @param workers   Number of worker threads (0 → LXL_SCHED_DEFAULT_WORKERS).
 *
 * @return Pointer to scheduler handle on success, NULL on failure (check errno).
 */
lxl_task_scheduler_t *
lxl_task_scheduler_create(size_t workers);

/**
 * lxl_task_scheduler_destroy
 *
 * Destroy the scheduler instance created by _create().  All tasks are first
 * cancelled.  Blocking; waits for worker threads to exit.
 *
 * @param scheduler  Scheduler handle (may be NULL, in which case the call is no-op).
 */
void
lxl_task_scheduler_destroy(lxl_task_scheduler_t *scheduler);

/**
 * lxl_task_scheduler_start
 *
 * Transition the scheduler into the RUNNING state.  Worker threads are spawned
 * (if not already alive) and will begin executing due tasks.
 *
 * @return See lxl_sched_rc_e.
 */
int
lxl_task_scheduler_start(lxl_task_scheduler_t *scheduler);

/**
 * lxl_task_scheduler_stop
 *
 * Gracefully stop or force-stop the scheduler.
 *
 * @param scheduler  Scheduler handle.
 * @param force      true  → Immediately cancel all tasks and stop workers.
 *                   false → Allow running tasks to complete first.
 *
 * @return See lxl_sched_rc_e.
 */
int
lxl_task_scheduler_stop(lxl_task_scheduler_t *scheduler, bool force);

/**
 * lxl_task_scheduler_schedule
 *
 * Schedule a task that repeats at the specified interval.
 *
 * @param scheduler      Scheduler handle.
 * @param task_id        Unique, NULL-terminated identifier (max LXL_TASK_ID_MAX-1).
 * @param task_name      Human-readable name for dashboards/logs.
 * @param cb             Task callback.
 * @param user_ctx       User context passed verbatim to @cb.
 * @param first_run      Epoch timestamp when the task should first execute.
 *                       Pass 0 to run “as soon as possible”.
 * @param interval_sec   Non-zero interval in seconds for recurring execution.
 * @param priority       Higher numbers → executed before lower numbers when queued.
 *
 * @return See lxl_sched_rc_e.
 */
int
lxl_task_scheduler_schedule(lxl_task_scheduler_t *scheduler,
                            const char           *task_id,
                            const char           *task_name,
                            lxl_task_fn_t         cb,
                            void                 *user_ctx,
                            time_t                first_run,
                            uint32_t              interval_sec,
                            int                   priority);

/**
 * lxl_task_scheduler_schedule_once
 *
 * Schedule a one-shot task executed at the given timestamp.
 *
 * @param scheduler   Scheduler handle.
 * @param task_id     Unique ID.
 * @param task_name   Human-readable name.
 * @param cb          Task callback.
 * @param user_ctx    Opaque pointer handed back to @cb.
 * @param run_at      Absolute epoch timestamp; 0 → run immediately.
 * @param priority    Higher numbers → executed before lower numbers when queued.
 *
 * @return See lxl_sched_rc_e.
 */
int
lxl_task_scheduler_schedule_once(lxl_task_scheduler_t *scheduler,
                                 const char           *task_id,
                                 const char           *task_name,
                                 lxl_task_fn_t         cb,
                                 void                 *user_ctx,
                                 time_t                run_at,
                                 int                   priority);

/**
 * lxl_task_scheduler_cancel
 *
 * Remove a task (pending or recurring) from the scheduler.
 *
 * @param scheduler  Scheduler handle.
 * @param task_id    ID of the task to cancel.
 *
 * @return See lxl_sched_rc_e.
 */
int
lxl_task_scheduler_cancel(lxl_task_scheduler_t *scheduler,
                          const char           *task_id);

/**
 * lxl_task_scheduler_register_observer
 *
 * Register an observer for task-lifecycle events.
 *
 * @param scheduler  Scheduler handle.
 * @param cb         Callback invoked on events (must be non-NULL).
 * @param user_ctx   Pointer returned as-is in each event callback.
 *
 * @return See lxl_sched_rc_e.
 *
 * @warning The observer callback executes on the scheduler’s internal thread
 *          context.  Keep processing lightweight to avoid delaying the scheduler.
 */
int
lxl_task_scheduler_register_observer(lxl_task_scheduler_t *scheduler,
                                     lxl_sched_event_cb_t  cb,
                                     void                 *user_ctx);

/**
 * lxl_task_scheduler_get_pending_count
 *
 * Retrieve the number of tasks that are pending (queued or scheduled for the
 * future) but not currently executing.
 *
 * @return Non-negative count on success, negative on failure (see lxl_sched_rc_e).
 */
int
lxl_task_scheduler_get_pending_count(const lxl_task_scheduler_t *scheduler);

/**
 * lxl_task_scheduler_get_running_count
 *
 * Retrieve the number of tasks actively executing.
 *
 * @return Non-negative count on success, negative on failure.
 */
int
lxl_task_scheduler_get_running_count(const lxl_task_scheduler_t *scheduler);

#ifdef __cplusplus
}   /* extern "C" */
#endif

#endif /* LEXILEARN_CONTROLLER_SCHEDULER_TASK_SCHEDULER_H */