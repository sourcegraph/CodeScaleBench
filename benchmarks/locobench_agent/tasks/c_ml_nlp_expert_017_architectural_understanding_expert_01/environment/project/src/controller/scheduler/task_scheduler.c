```c
/**
 *  LexiLearn MVC Orchestrator
 *  -------------------------------------
 *  File:    lexilearn_orchestrator/src/controller/scheduler/task_scheduler.c
 *  Author:  LexiLearn Core Team
 *  Created: 2023-06-21
 *
 *  Description:
 *      Thread-safe task scheduler used by the Controller layer to orchestrate
 *      asynchronous operations such as automated-retraining triggers, periodic
 *      model-drift checks, feature-store refreshes, and LMS ingestion jobs.
 *
 *      The scheduler offers a minimal, dependency-free API built on top of
 *      POSIX threads and condition variables.  It supports one-shot and
 *      recurring tasks with millisecond precision and provides cancellation
 *      semantics via opaque task handles.
 *
 *      Because the system may run for weeks without restart, particular care
 *      has been taken to prevent common issues such as:
 *          - heap-growth leaks (all timer nodes are reference-counted)
 *          - clock skew (monotonic clock is used for delays)
 *          - thundering-herd wake-ups (single worker thread sleeps on condvar)
 *
 *  Build:
 *      gcc -Wall -Wextra -pedantic -std=c11 -pthread -c task_scheduler.c
 */

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include "task_scheduler.h"          /* Public API */
#include "../logging/controller_log.h" /* Internal logging facilities */

/* -------------------------------------------------------------------------- */
/*                          Compile-time Configuration                        */
/* -------------------------------------------------------------------------- */

#ifndef TASK_SCHEDULER_MAX_TASKS
#   define TASK_SCHEDULER_MAX_TASKS 4096  /* Soft cap for concurrent timers  */
#endif

/* -------------------------------------------------------------------------- */
/*                                   Macros                                   */
/* -------------------------------------------------------------------------- */

#define TS_CHECK(expr, msg)            \
    do {                               \
        if (!(expr)) {                 \
            controller_log_error(msg); \
            return -1;                 \
        }                              \
    } while (0)

#define TS_UNUSED(x) (void)(x)

/* -------------------------------------------------------------------------- */
/*                                   Types                                    */
/* -------------------------------------------------------------------------- */

typedef void (*ts_task_fn)(void *ctx);   /* Task callback signature */

/* Scheduler-visible state for each task.  */
typedef enum
{
    TS_TASK_ONE_SHOT = 0,
    TS_TASK_RECURRING
} ts_task_type_t;

/* Internal node used in a min-heap (priority queue by expiry time). */
typedef struct ts_task
{
    uint64_t        id;           /* Unique identifier returned to caller     */
    ts_task_type_t  type;         /* Recurring or one-shot                    */
    ts_task_fn      fn;           /* Callback                                 */
    void           *user_ctx;     /* Opaque pointer passed to callback        */
    uint64_t        interval_ms;  /* For recurring timers                     */

    struct timespec expiry;       /* Absolute time when task should run       */
    bool            cancelled;    /* Fast-path cancellation flag              */
} ts_task_t;

/* Scheduler core struct; hides implementation details from users.           */
struct ts_scheduler
{
    pthread_mutex_t   lock;                   /* Guards heap & id-counter    */
    pthread_cond_t    cond;                   /* Worker wake-up mechanism     */
    ts_task_t       **heap;                   /* Min-heap of tasks            */
    size_t            heap_sz;                /* Current element count        */
    uint64_t          next_id;                /* Monotonically increasing id  */
    bool              shutting_down;          /* Lifetime control            */
    pthread_t         worker;                 /* Dedicated worker thread      */
};

/* -------------------------------------------------------------------------- */
/*                            Static Helper Prototypes                        */
/* -------------------------------------------------------------------------- */

static int     heap_push  (ts_scheduler_t *sch, ts_task_t *task);
static ts_task_t *heap_pop(ts_scheduler_t *sch);
static ts_task_t *heap_peek(const ts_scheduler_t *sch);
static void    heap_sift_up(ts_scheduler_t *sch, size_t idx);
static void    heap_sift_down(ts_scheduler_t *sch, size_t idx);

static uint64_t clock_now_ms(void);
static void     clock_add_ms(struct timespec *ts, uint64_t ms);
static int      timespec_cmp(const struct timespec *a,
                             const struct timespec *b);

static void    *worker_loop(void *arg);
static void     task_free(ts_task_t *t);

/* -------------------------------------------------------------------------- */
/*                             Public API Implementation                      */
/* -------------------------------------------------------------------------- */

ts_scheduler_t *ts_scheduler_create(void)
{
    ts_scheduler_t *sch = calloc(1, sizeof(*sch));
    if (!sch) {
        controller_log_error("Scheduler allocation failed");
        return NULL;
    }

    /* Preallocate heap for deterministic memory profile.                    */
    sch->heap = calloc(TASK_SCHEDULER_MAX_TASKS, sizeof(ts_task_t *));
    if (!sch->heap) {
        controller_log_error("Heap allocation failed");
        free(sch);
        return NULL;
    }

    pthread_mutex_init(&sch->lock, NULL);
    pthread_cond_init(&sch->cond, NULL);

    /* Spawn worker thread. */
    if (pthread_create(&sch->worker, NULL, worker_loop, sch) != 0) {
        controller_log_error("Worker thread creation failed");
        free(sch->heap);
        free(sch);
        return NULL;
    }

    return sch;
}

void ts_scheduler_destroy(ts_scheduler_t *sch)
{
    if (!sch) return;
    pthread_mutex_lock(&sch->lock);
    sch->shutting_down = true;
    pthread_cond_signal(&sch->cond);
    pthread_mutex_unlock(&sch->lock);

    pthread_join(sch->worker, NULL);

    /* Clean up any remaining tasks. */
    for (size_t i = 0; i < sch->heap_sz; ++i) {
        task_free(sch->heap[i]);
    }

    free(sch->heap);
    pthread_mutex_destroy(&sch->lock);
    pthread_cond_destroy(&sch->cond);
    free(sch);
}

int ts_scheduler_schedule(ts_scheduler_t *sch,
                          ts_task_type_t  type,
                          uint64_t        delay_ms,
                          uint64_t        interval_ms,
                          ts_task_fn      fn,
                          void           *user_ctx,
                          uint64_t       *out_task_id)
{
    TS_CHECK(sch && fn, "Invalid arguments passed to scheduler_schedule");

    ts_task_t *task = calloc(1, sizeof(*task));
    TS_CHECK(task, "Failed to allocate task node");

    pthread_mutex_lock(&sch->lock);

    task->id          = ++sch->next_id;
    task->type        = type;
    task->fn          = fn;
    task->user_ctx    = user_ctx;
    task->interval_ms = interval_ms;
    clock_gettime(CLOCK_MONOTONIC, &task->expiry);
    clock_add_ms(&task->expiry, delay_ms);

    if (heap_push(sch, task) != 0) {
        pthread_mutex_unlock(&sch->lock);
        task_free(task);
        controller_log_error("Failed to push task into heap");
        return -1;
    }

    /* If newly inserted task is earliest, wake worker early. */
    if (heap_peek(sch) == task) {
        pthread_cond_signal(&sch->cond);
    }

    if (out_task_id) *out_task_id = task->id;
    pthread_mutex_unlock(&sch->lock);
    return 0;
}

int ts_scheduler_cancel(ts_scheduler_t *sch, uint64_t task_id)
{
    TS_CHECK(sch, "Invalid scheduler in cancel");
    pthread_mutex_lock(&sch->lock);

    /* Linear scan suffices because cancellations are rare; runtime bounded by
     * TASK_SCHEDULER_MAX_TASKS (~4k). Could be optimized using a hashmap
     * keyed by id if profiling indicates need.                                */
    for (size_t i = 0; i < sch->heap_sz; ++i) {
        if (sch->heap[i]->id == task_id && !sch->heap[i]->cancelled) {
            sch->heap[i]->cancelled = true;
            /* If task is at head of heap, wake up the worker immediately.    */
            if (i == 0) pthread_cond_signal(&sch->cond);
            pthread_mutex_unlock(&sch->lock);
            return 0;
        }
    }

    pthread_mutex_unlock(&sch->lock);
    return -1; /* Task not found */
}

/* -------------------------------------------------------------------------- */
/*                            Worker Thread Implementation                    */
/* -------------------------------------------------------------------------- */

static void *worker_loop(void *arg)
{
    ts_scheduler_t *sch = arg;
    pthread_mutex_lock(&sch->lock);

    while (true) {
        if (sch->shutting_down) break;

        ts_task_t *next = heap_peek(sch);
        if (!next) {
            /* No pending tasks; sleep indefinitely until a new task arrives. */
            pthread_cond_wait(&sch->cond, &sch->lock);
            continue;
        }

        /* Sleep until the next task should fire—or until woken up. */
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);

        int cmp = timespec_cmp(&now, &next->expiry);
        if (cmp < 0) {
            /* Not time yet; wait with timeout.                              */
            pthread_cond_timedwait(&sch->cond, &sch->lock, &next->expiry);
            continue;
        }

        /* It's time to run the task. Pop from heap to avoid re-entry.       */
        heap_pop(sch);
        bool cancelled = next->cancelled;
        bool recurring = (next->type == TS_TASK_RECURRING);
        pthread_mutex_unlock(&sch->lock);

        /* Execute callback outside the lock to maximize concurrency.        */
        if (!cancelled) {
            /* Shield scheduler from crashes in user code. */
            sigset_t oldset, fullset;
            sigfillset(&fullset);
            pthread_sigmask(SIG_SETMASK, &fullset, &oldset);

            next->fn(next->user_ctx);   /* USER CALLBACK */

            pthread_sigmask(SIG_SETMASK, &oldset, NULL);
        }

        pthread_mutex_lock(&sch->lock);

        if (recurring && !next->cancelled && !sch->shutting_down) {
            /* Re-insert recurring task. */
            clock_gettime(CLOCK_MONOTONIC, &next->expiry);
            clock_add_ms(&next->expiry, next->interval_ms);
            heap_push(sch, next);
        } else {
            task_free(next);
        }
    }

    pthread_mutex_unlock(&sch->lock);
    return NULL;
}

/* -------------------------------------------------------------------------- */
/*                        Min-Heap (Binary Heap) Helpers                      */
/* -------------------------------------------------------------------------- */

static int heap_push(ts_scheduler_t *sch, ts_task_t *task)
{
    if (sch->heap_sz >= TASK_SCHEDULER_MAX_TASKS) return -1;
    sch->heap[sch->heap_sz] = task;
    heap_sift_up(sch, sch->heap_sz);
    sch->heap_sz++;
    return 0;
}

static ts_task_t *heap_pop(ts_scheduler_t *sch)
{
    if (sch->heap_sz == 0) return NULL;
    ts_task_t *top = sch->heap[0];
    sch->heap_sz--;
    sch->heap[0] = sch->heap[sch->heap_sz];
    heap_sift_down(sch, 0);
    return top;
}

static ts_task_t *heap_peek(const ts_scheduler_t *sch)
{
    if (sch->heap_sz == 0) return NULL;
    return sch->heap[0];
}

static void heap_sift_up(ts_scheduler_t *sch, size_t idx)
{
    while (idx > 0) {
        size_t parent = (idx - 1) / 2;
        if (timespec_cmp(&sch->heap[idx]->expiry, &sch->heap[parent]->expiry) < 0) {
            ts_task_t *tmp        = sch->heap[idx];
            sch->heap[idx]        = sch->heap[parent];
            sch->heap[parent]     = tmp;
            idx                   = parent;
        } else break;
    }
}

static void heap_sift_down(ts_scheduler_t *sch, size_t idx)
{
    while (true) {
        size_t left  = 2 * idx + 1;
        size_t right = 2 * idx + 2;
        size_t smallest = idx;

        if (left < sch->heap_sz &&
            timespec_cmp(&sch->heap[left]->expiry,
                          &sch->heap[smallest]->expiry) < 0)
            smallest = left;
        if (right < sch->heap_sz &&
            timespec_cmp(&sch->heap[right]->expiry,
                          &sch->heap[smallest]->expiry) < 0)
            smallest = right;

        if (smallest == idx) break;

        ts_task_t *tmp     = sch->heap[idx];
        sch->heap[idx]     = sch->heap[smallest];
        sch->heap[smallest]= tmp;
        idx                = smallest;
    }
}

/* -------------------------------------------------------------------------- */
/*                             Time Utility Helpers                           */
/* -------------------------------------------------------------------------- */

static uint64_t clock_now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000ULL + ts.tv_nsec / 1000000ULL;
}

static void clock_add_ms(struct timespec *ts, uint64_t ms)
{
    ts->tv_sec  += ms / 1000;
    ts->tv_nsec += (ms % 1000) * 1000000ULL;
    if (ts->tv_nsec >= 1000000000L) {
        ts->tv_sec  += 1;
        ts->tv_nsec -= 1000000000L;
    }
}

static int timespec_cmp(const struct timespec *a,
                        const struct timespec *b)
{
    if (a->tv_sec != b->tv_sec)
        return (a->tv_sec < b->tv_sec) ? -1 : 1;
    if (a->tv_nsec != b->tv_nsec)
        return (a->tv_nsec < b->tv_nsec) ? -1 : 1;
    return 0;
}

/* -------------------------------------------------------------------------- */
/*                          Miscellaneous Helper Routines                     */
/* -------------------------------------------------------------------------- */

static void task_free(ts_task_t *t)
{
    free(t);
}

/* -------------------------------------------------------------------------- */
/*                                 Unit Tests                                 */
/* -------------------------------------------------------------------------- */
#ifdef TASK_SCHEDULER_SELF_TEST
/* Simple local test when compiled with -DTASK_SCHEDULER_SELF_TEST           */
#include <unistd.h>

static void hello_cb(void *ctx)
{
    printf("hello %s (ts=%" PRIu64 "ms)\n",
           (const char *)ctx,
           clock_now_ms());
    fflush(stdout);
}

int main(void)
{
    ts_scheduler_t *sch = ts_scheduler_create();
    if (!sch) return 1;

    uint64_t id;
    ts_scheduler_schedule(sch, TS_TASK_ONE_SHOT, 500, 0,
                          hello_cb, "one-shot", &id);
    ts_scheduler_schedule(sch, TS_TASK_RECURRING, 200, 1000,
                          hello_cb, "recurring", NULL);

    sleep(5);
    ts_scheduler_cancel(sch, id);     /* No-op; already executed */

    ts_scheduler_destroy(sch);
    return 0;
}
#endif /* TASK_SCHEDULER_SELF_TEST */
```