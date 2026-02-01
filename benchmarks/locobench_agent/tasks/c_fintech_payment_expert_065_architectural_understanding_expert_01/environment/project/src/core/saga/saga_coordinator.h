/**
 * @file saga_coordinator.h
 *
 * @brief Core abstraction for orchestrating distributed transactions
 *        via the Saga Pattern inside EduPay Ledger Academy.
 *
 *  The coordinator lives in the domain layer (Enterprise-Business Rules)
 *  and therefore must not import any framework-specific headers.
 *  It exposes a small surface-area in C so that professors can swap
 *  infrastructure (Kafka, NATS, gRPC, REST, SQL, NoSQL, etc.) without
 *  recompiling core business rules.
 *
 *  Thread-safety:
 *      All public functions are re-entrant but *not* thread-safe.
 *      Callers that share a coordinator instance *must* provide their own
 *      synchronization (e.g., inject a mutex from the application layer).
 *
 *  Memory-management:
 *      Memory is allocated only inside saga_coordinator_create().
 *      The caller is responsible for releasing resources via
 *      saga_coordinator_destroy().
 *
 *  License:
 *      MIT – Copyright © 2024 EduPay Ledger Academy
 */

#ifndef EDU_PAY_LEDGER_ACADEMY_CORE_SAGA_COORDINATOR_H
#define EDU_PAY_LEDGER_ACADEMY_CORE_SAGA_COORDINATOR_H

/*------------------------------ System Headers -----------------------------*/
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/*------------------------------ Public Macros ------------------------------*/
#define SAGA_MAX_STEPS        32     /* Upper bound to keep stack usage low */
#define SAGA_MAX_ERROR_TEXT  128     /* Human-readable reason buffer size   */

/*------------------------------- Enumerations ------------------------------*/
/**
 * @enum saga_step_state_t
 * Represents runtime state of an individual step during a Saga execution.
 */
typedef enum
{
    SAGA_STEP_PENDING = 0,     /* Step has not been executed yet              */
    SAGA_STEP_COMPLETED,       /* Step executed successfully                  */
    SAGA_STEP_FAILED,          /* Step executed and returned error            */
    SAGA_STEP_COMPENSATED,     /* Compensation executed after a failure       */
    SAGA_STEP_COMPENSATION_FAILED /* Compensation itself failed              */
} saga_step_state_t;

/**
 * @enum saga_execution_state_t
 * High-level status of the overall Saga.
 */
typedef enum
{
    SAGA_STATE_IDLE = 0,
    SAGA_STATE_RUNNING,
    SAGA_STATE_ROLLING_BACK,
    SAGA_STATE_COMPLETED,
    SAGA_STATE_ABORTED
} saga_execution_state_t;

/*------------------------------ Forward Decls ------------------------------*/
struct saga_coordinator_t;

/**
 * Callback invoked by a Saga step to perform its forward (happy-path) logic.
 *
 * @param step_ctx  User-supplied context pointer bound to the step.
 * @param reason    Output buffer for an error description if the step fails.
 * @param reason_len Length of the provided buffer.
 *
 * @return true  if the step succeeded and the Saga may continue.
 *         false if an error occurred; compensation will be triggered.
 */
typedef bool (*saga_forward_cb_t)(void *step_ctx,
                                  char *reason,
                                  size_t reason_len);

/**
 * Callback invoked during rollback when a previous forward step failed.
 *
 * @param step_ctx  Same context pointer passed to the forward call.
 * @param reason    Output buffer for an error description if compensation
 *                  fails. When compensation fails, the Saga transitions to
 *                  SAGA_STATE_ABORTED and no further steps are attempted.
 * @param reason_len Length of the provided buffer.
 *
 * @return true  if compensation succeeded.
 *         false if compensation itself failed – requires manual intervention.
 */
typedef bool (*saga_compensate_cb_t)(void *step_ctx,
                                     char *reason,
                                     size_t reason_len);

/*------------------------------ Data Structures ----------------------------*/
/**
 * @struct saga_step_t
 * Encapsulates a single unit of work and its compensating action.
 */
typedef struct
{
    const char          *name;           /* Human-readable step identifier   */
    saga_forward_cb_t    do_txn;         /* Forward transaction logic        */
    saga_compensate_cb_t undo_txn;       /* Compensation logic               */
    void                *ctx;            /* User-defined context per step    */
    saga_step_state_t    state;          /* Runtime state                    */
    char                 error[SAGA_MAX_ERROR_TEXT]; /* Error buffer         */
} saga_step_t;

/**
 * @struct saga_coordinator_t
 * Public handle used by application services to compose a Saga.
 */
typedef struct saga_coordinator_t
{
    saga_step_t            steps[SAGA_MAX_STEPS];
    uint8_t                step_count;
    uint8_t                current;      /* Index of currently executing step */
    saga_execution_state_t state;
} saga_coordinator_t;

/*--------------------------- Public API Functions --------------------------*/

/**
 * Create a fresh Saga coordinator.
 *
 * @param[out] out_handle Pointer to hold the newly-allocated coordinator.
 *
 * @return true on success; false if memory allocation fails.
 */
bool saga_coordinator_create(saga_coordinator_t **out_handle);

/**
 * Append a step to the Saga.
 *
 * @param saga     Saga instance obtained from saga_coordinator_create().
 * @param name     Null-terminated string used for logging/observability.
 * @param forward  Forward (commit) callback.
 * @param compensate Compensation (rollback) callback.
 * @param ctx      User context pointer passed untouched to both callbacks.
 *
 * @return true if the step was registered; false if capacity reached.
 */
bool saga_coordinator_add_step(saga_coordinator_t *saga,
                               const char        *name,
                               saga_forward_cb_t  forward,
                               saga_compensate_cb_t compensate,
                               void              *ctx);

/**
 * Execute the Saga end-to-end.
 *
 * The function iterates over all steps:
 *   1. Invokes each forward callback sequentially.
 *   2. On first failure, switches to rollback mode and calls compensation
 *      callbacks in reverse order for *completed* steps.
 *
 * @param saga  Saga handle.
 *
 * @return SAGA_STATE_COMPLETED on success,
 *         SAGA_STATE_ABORTED   if any compensation fails,
 *         SAGA_STATE_ROLLING_BACK if rollback succeeded but original
 *                                 forward path had a failure.
 */
saga_execution_state_t saga_coordinator_execute(saga_coordinator_t *saga);

/**
 * Acquire details about the failure that caused a rollback or abort.
 *
 * @param saga  Saga handle.
 *
 * @return Pointer to a constant string describing the last error,
 *         or NULL if no error was recorded.
 *
 * @note The pointer becomes invalid after saga_coordinator_destroy().
 */
const char * saga_coordinator_last_error(const saga_coordinator_t *saga);

/**
 * Release all resources held by the coordinator.
 *
 * @param saga  Pointer returned by saga_coordinator_create().
 */
void saga_coordinator_destroy(saga_coordinator_t *saga);

/*----------------------- Inline Convenience Functions ----------------------*/
static inline bool saga_is_success(const saga_execution_state_t st)
{
    return st == SAGA_STATE_COMPLETED;
}

static inline bool saga_is_failed(const saga_execution_state_t st)
{
    return (st == SAGA_STATE_ROLLING_BACK) || (st == SAGA_STATE_ABORTED);
}

#endif /* EDU_PAY_LEDGER_ACADEMY_CORE_SAGA_COORDINATOR_H */
