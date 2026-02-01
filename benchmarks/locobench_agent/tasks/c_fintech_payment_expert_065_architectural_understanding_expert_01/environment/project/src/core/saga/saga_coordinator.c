/*
 * EduPay Ledger Academy - Saga Coordinator
 *
 * File:    saga_coordinator.c
 * Author:  EduPay Core Engineering Team
 *
 * Description:
 *   Centralised coordinator implementation for the Saga Pattern demonstration
 *   mode.  Handles orchestration, rollback, persistence, and audit/event
 *   publishing for distributed, multi-service financial workflows such as
 *   tuition payments, stipend disbursements, and scholarship settlements.
 *
 *   The coordinator is purposely framework-agnostic so instructors can
 *   substitute transport layers (gRPC, AMQP, REST), persistence mechanisms
 *   (PostgreSQL, Redis, flat files), or monitoring suites without touching
 *   business logic.
 *
 *   Compile with:
 *     cc -std=c11 -Wall -Wextra -pedantic -pthread -o saga_coordinator \
 *        saga_coordinator.c
 */

#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "uuid/uuid.h"   /* libuuid: sudo apt-get install uuid-dev */

/*--------------------------------------------------------------------------*/
/* Constants & Macros                                                       */
/*--------------------------------------------------------------------------*/
#define SAGA_MAX_STEPS          16      /* educational demo limit            */
#define SAGA_ID_STRLEN          37      /* 36 bytes + NULL                   */
#define SAGA_EVENT_BUS_PATH     "/var/run/edupay/eventbus.sock"
#define SAGA_PERSISTENCE_DIR    "/var/lib/edupay/saga"

#define UNUSED(x)               ((void)(x))

/*--------------------------------------------------------------------------*/
/* Typedefs                                                                 */
/*--------------------------------------------------------------------------*/

typedef enum {
    SAGA_STATE_NOT_STARTED   = 0,
    SAGA_STATE_IN_PROGRESS   = 1,
    SAGA_STATE_COMPLETED     = 2,
    SAGA_STATE_COMPENSATING  = 3,
    SAGA_STATE_ABORTED       = 4
} saga_state_t;

/* Return codes for actions/compensations */
typedef enum {
    SAGA_STEP_SUCCESS        =  0,
    SAGA_STEP_RETRYABLE_ERR  = -1,
    SAGA_STEP_FATAL_ERR      = -2
} saga_step_rc_t;

/* Function pointer signatures for step actions & compensations */
typedef int (*saga_action_fn)(void *step_ctx);
typedef int (*saga_comp_fn)(void *step_ctx);

/* Saga step definition */
typedef struct {
    char            name[64];
    saga_action_fn  action;
    saga_comp_fn    compensate;
    int             timeout_ms;         /* zero -> no timeout */
} saga_step_t;

/* Saga instance */
typedef struct {
    char            id[SAGA_ID_STRLEN];
    saga_state_t    state;
    saga_step_t     steps[SAGA_MAX_STEPS];
    size_t          step_count;

    /* runtime fields */
    size_t          current_step;
    time_t          started_at;
    pthread_mutex_t lock;
} saga_t;

/*--------------------------------------------------------------------------*/
/* Forward declarations                                                     */
/*--------------------------------------------------------------------------*/
static int saga_persist_state(const saga_t *sg);
static int saga_publish_event(const saga_t *sg, const char *event_name,
                              const char *detail);
static void saga_log(const saga_t *sg, const char *level,
                     const char *fmt, ...);

static int saga_execute_step(saga_t *sg, size_t idx, void *ctx);
static int saga_compensate(saga_t *sg, size_t failed_idx, void *ctx);

/*--------------------------------------------------------------------------*/
/* Public API                                                               */
/*--------------------------------------------------------------------------*/

/*
 * saga_create()
 *   Allocates and initialises a saga instance.
 */
saga_t *saga_create(const saga_step_t *steps,
                    size_t             step_count)
{
    if (!steps || step_count == 0 || step_count > SAGA_MAX_STEPS) {
        fprintf(stderr, "saga_create: invalid step array\n");
        return NULL;
    }

    saga_t *sg = calloc(1, sizeof(*sg));
    if (!sg) {
        perror("calloc");
        return NULL;
    }

    uuid_t uuid;
    uuid_generate(uuid);
    uuid_unparse_lower(uuid, sg->id);

    sg->state         = SAGA_STATE_NOT_STARTED;
    sg->step_count    = step_count;
    memcpy(sg->steps, steps, sizeof(saga_step_t) * step_count);
    sg->current_step  = 0;
    sg->started_at    = 0;
    pthread_mutex_init(&sg->lock, NULL);

    if (saga_persist_state(sg) != 0) {
        /* non-fatal during creation; caller may persist later */
        saga_log(sg, "WARN", "Unable to persist saga during creation");
    }
    return sg;
}

/*
 * saga_destroy()
 *   Frees a saga instance.  Must not be invoked while another thread is
 *   executing the saga.
 */
void saga_destroy(saga_t *sg)
{
    if (!sg) return;
    pthread_mutex_destroy(&sg->lock);
    free(sg);
}

/*
 * saga_execute()
 *   Executes all steps for a saga in order.  On failure, compensations are
 *   performed in reverse order (up to the failed step).
 *
 *   ctx may be any user-defined pointer passed to all actions/compensations.
 *
 *   Returns 0 on success, non-zero on failure.
 */
int saga_execute(saga_t *sg, void *ctx)
{
    if (!sg) return EINVAL;

    pthread_mutex_lock(&sg->lock);
    if (sg->state != SAGA_STATE_NOT_STARTED) {
        pthread_mutex_unlock(&sg->lock);
        return EALREADY;
    }
    sg->state      = SAGA_STATE_IN_PROGRESS;
    sg->started_at = time(NULL);
    pthread_mutex_unlock(&sg->lock);

    saga_publish_event(sg, "SAGA_STARTED", NULL);

    for (size_t i = 0; i < sg->step_count; ++i) {
        int rc = saga_execute_step(sg, i, ctx);
        if (rc == SAGA_STEP_SUCCESS) {
            continue;
        }

        /* Something went wrong, start compensation */
        (void)saga_publish_event(sg, "SAGA_STEP_FAILED", sg->steps[i].name);

        pthread_mutex_lock(&sg->lock);
        sg->state = SAGA_STATE_COMPENSATING;
        pthread_mutex_unlock(&sg->lock);

        if (saga_compensate(sg, i, ctx) != 0) {
            /* Could not fully compensate; escalate to ops */
            saga_publish_event(sg, "SAGA_COMPENSATION_INCOMPLETE",
                               sg->steps[i].name);
        }

        pthread_mutex_lock(&sg->lock);
        sg->state = SAGA_STATE_ABORTED;
        pthread_mutex_unlock(&sg->lock);

        saga_persist_state(sg);
        saga_publish_event(sg, "SAGA_ABORTED", sg->steps[i].name);
        return rc;
    }

    pthread_mutex_lock(&sg->lock);
    sg->state = SAGA_STATE_COMPLETED;
    pthread_mutex_unlock(&sg->lock);

    saga_persist_state(sg);
    saga_publish_event(sg, "SAGA_COMPLETED", NULL);
    return 0;
}

/*--------------------------------------------------------------------------*/
/* Implementation Internals                                                 */
/*--------------------------------------------------------------------------*/

static int saga_execute_step(saga_t *sg, size_t idx, void *ctx)
{
    saga_step_t *step = &sg->steps[idx];
    sg->current_step  = idx;

    saga_log(sg, "INFO", "Executing step #%zu (%s)", idx, step->name);
    saga_publish_event(sg, "SAGA_STEP_STARTED", step->name);

    /* Simple timeout handling using alarm + sleep granularity.
     * Production systems would leverage epoll/ev timers or async futures.
     */
    if (step->timeout_ms > 0) {
        struct timespec ts = {
            .tv_sec  = step->timeout_ms / 1000,
            .tv_nsec = (step->timeout_ms % 1000) * 1000000L
        };
        nanosleep(&ts, NULL); /* Simulated work; replace with real action */
    }

    int rc = step->action(ctx);

    saga_publish_event(sg, "SAGA_STEP_FINISHED", step->name);
    saga_persist_state(sg);

    if (rc != SAGA_STEP_SUCCESS) {
        saga_log(sg, "ERROR", "Step %s failed with rc=%d", step->name, rc);
    }
    return rc;
}

static int saga_compensate(saga_t *sg, size_t failed_idx, void *ctx)
{
    /* Traverse backwards up to failed index */
    for (ssize_t i = (ssize_t)failed_idx; i >= 0; --i) {
        saga_step_t *step = &sg->steps[i];
        saga_log(sg, "INFO", "Compensating step #%zd (%s)", i, step->name);

        if (!step->compensate) {
            saga_log(sg, "WARN", "No compensation defined for step %s",
                     step->name);
            continue;
        }

        int rc = step->compensate(ctx);
        saga_publish_event(sg, "SAGA_STEP_COMPENSATED", step->name);
        if (rc != 0) {
            saga_log(sg, "ERROR", "Compensation for %s failed rc=%d",
                     step->name, rc);
            return rc;
        }
    }
    return 0;
}

/*--------------------------------------------------------------------------*/
/* Persistence & Event Bus Stubs                                            */
/*--------------------------------------------------------------------------*/

/*
 * saga_persist_state()
 *   Very simple persistence: write JSON-like state to a file named
 *   <SAGA_PERSISTENCE_DIR>/<saga_id>.log
 *
 *   Production systems would use a proper event store or relational DB.
 */
static int saga_persist_state(const saga_t *sg)
{
    char path[256];
    snprintf(path, sizeof(path), "%s/%s.log", SAGA_PERSISTENCE_DIR, sg->id);

    FILE *fp = fopen(path, "a");
    if (!fp) {
        perror("fopen");
        return errno;
    }

    time_t now = time(NULL);
    fprintf(fp,
            "{ \"ts\":%ld, \"state\":%d, \"current_step\":%zu }\n",
            now, sg->state, sg->current_step);
    fclose(fp);
    return 0;
}

/*
 * saga_publish_event()
 *   Stubbed event bus publisher.  Writes to stdout and optionally to a UNIX
 *   domain socket path defined by SAGA_EVENT_BUS_PATH.
 */
static int saga_publish_event(const saga_t *sg, const char *event_name,
                              const char *detail)
{
    time_t now = time(NULL);
    saga_log(sg, "EVENT", "%s (%s)", event_name,
             detail ? detail : "n/a");

    /* TODO: Implement real event bus IPC here */
    UNUSED(now);
    UNUSED(SAGA_EVENT_BUS_PATH);
    UNUSED(event_name);
    UNUSED(detail);
    return 0;
}

/*--------------------------------------------------------------------------*/
/* Logging                                                                  */
/*--------------------------------------------------------------------------*/
#include <stdarg.h>

static void saga_log(const saga_t *sg, const char *level,
                     const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);

    fprintf(stderr, "[%s] SAGA(%s) ", level, sg ? sg->id : "n/a");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");

    va_end(ap);
}

/*--------------------------------------------------------------------------*/
/* Demo Harness (Only compiled when building standalone)                    */
/*--------------------------------------------------------------------------*/
#ifdef SAGA_COORDINATOR_DEMO

/* Example action/compensation functions */
static int debit_student_account(void *ctx)
{
    UNUSED(ctx);
    /* Simulate success */
    return SAGA_STEP_SUCCESS;
}
static int credit_bursar_account(void *ctx)
{
    UNUSED(ctx);
    /* Simulate retryable failure */
    return SAGA_STEP_RETRYABLE_ERR;
}
static int revert_debit_student_account(void *ctx)
{
    UNUSED(ctx);
    /* Always succeed */
    return 0;
}

int main(void)
{
    saga_step_t steps[] = {
        {
            .name        = "Debit Student",
            .action      = debit_student_account,
            .compensate  = revert_debit_student_account,
            .timeout_ms  = 200
        },
        {
            .name        = "Credit Bursar",
            .action      = credit_bursar_account,
            .compensate  = NULL,
            .timeout_ms  = 200
        }
    };

    saga_t *sg = saga_create(steps, sizeof(steps)/sizeof(steps[0]));
    if (!sg) return EXIT_FAILURE;

    int rc = saga_execute(sg, NULL);
    saga_destroy(sg);
    return (rc == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
}

#endif /* SAGA_COORDINATOR_DEMO */
