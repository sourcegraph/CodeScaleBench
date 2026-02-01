```c
/**
 * ============================================================================
 *  EduPay Ledger Academy – Core Domain (Saga Pattern Definitions)
 *  File: saga_definition.h
 *
 *  Description:
 *    Public, framework-agnostic definitions for the Saga Pattern used within
 *    EduPay Ledger Academy.  These interfaces live in the core domain layer so
 *    that professors can swap out messaging middleware (e.g., NATS, Kafka,
 *    AMQP) or persistence engines (e.g., PostgreSQL, DynamoDB) without touching
 *    business rules.
 *
 *  The definitions below purposely avoid leaking infrastructure concerns
 *  (threads, sockets, ORMs, etc.).  They only describe *what* a saga is and
 *  *how* steps are composed.  Concrete executors, adapters, and integration
 *  tests are implemented in the application / infrastructure layers.
 *
 *  Author: EduPay Ledger Academy Core Team
 *  SPDX-License-Identifier: MIT
 * ============================================================================
 */

#ifndef EDUPAY_LEDGER_ACADEMY_CORE_SAGA_DEFINITION_H
#define EDUPAY_LEDGER_ACADEMY_CORE_SAGA_DEFINITION_H

/* ──────────────────────────────────────────────────────────────
 *  Standard Library
 * ──────────────────────────────────────────────────────────── */
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* ──────────────────────────────────────────────────────────────
 *  Versioning
 * ──────────────────────────────────────────────────────────── */
#define SAGA_DEFINITION_VERSION_MAJOR 1
#define SAGA_DEFINITION_VERSION_MINOR 0
#define SAGA_DEFINITION_VERSION_PATCH 0

/* ──────────────────────────────────────────────────────────────
 *  Constants & Configuration
 * ──────────────────────────────────────────────────────────── */

/* Upper bound prevents memory corruption in student exercises.   */
#ifndef SAGA_MAX_STEPS
#define SAGA_MAX_STEPS 16U
#endif /* SAGA_MAX_STEPS */

/* Status/Return codes for saga operations.                      */
typedef enum
{
    SAGA_OK = 0,
    SAGA_ERR_INVALID_ARG      = -1,
    SAGA_ERR_TOO_MANY_STEPS   = -2,
    SAGA_ERR_ALREADY_STARTED  = -3,
    SAGA_ERR_STEP_FAILED      = -4,
    SAGA_ERR_COMPENSATION     = -5,
    SAGA_ERR_NOT_STARTED      = -6
} saga_rc_t;

/* ──────────────────────────────────────────────────────────────
 *  Forward Declarations
 * ──────────────────────────────────────────────────────────── */
struct saga_step;
struct saga_definition;

/* ──────────────────────────────────────────────────────────────
 *  Function Pointer Types
 * ──────────────────────────────────────────────────────────── */
/**
 * Each saga step is implemented as a pair of callback functions that operate
 * on an opaque, caller-supplied context.  Business rules live inside these
 * callbacks, whereas the saga engine merely orchestrates them.
 *
 * Return:  SAGA_OK (0)     – success
 *          < 0             – error code, triggers compensation
 */
typedef saga_rc_t (*saga_step_action_fn)(void *opaque_ctx);

/* ──────────────────────────────────────────────────────────────
 *  Enumerations
 * ──────────────────────────────────────────────────────────── */
typedef enum
{
    SAGA_STEP_PENDING = 0,
    SAGA_STEP_COMPLETED,
    SAGA_STEP_FAILED,
    SAGA_STEP_COMPENSATED
} saga_step_state_t;

typedef enum
{
    SAGA_PENDING = 0,
    SAGA_IN_PROGRESS,
    SAGA_COMPLETED,
    SAGA_ROLLING_BACK,
    SAGA_COMPENSATED,
    SAGA_ABORTED
} saga_state_t;

/* ──────────────────────────────────────────────────────────────
 *  Data Structures
 * ──────────────────────────────────────────────────────────── */

/**
 * saga_step:
 *    Declarative description of a single unit of work within a saga.
 *
 * Members:
 *    id                 – unique identifier within the saga (array index).
 *    name               – human-readable identifier (for audit logs).
 *    forward_action     – executes the primary business logic.
 *    compensation_action– reverses forward_action if failure occurs.
 *    state              – runtime state tracked by saga executor.
 */
typedef struct saga_step
{
    uint8_t               id;
    const char           *name;
    saga_step_action_fn   forward_action;
    saga_step_action_fn   compensation_action;
    saga_step_state_t     state;
} saga_step_t;

/**
 * saga_definition:
 *    Immutable blueprint for constructing a saga at runtime.  A concrete
 *    executor copies this definition into a mutable saga_instance that tracks
 *    states, timing, and metrics.
 *
 * Members:
 *    saga_name          – business-level identifier (e.g., "TuitionPayment").
 *    version            – semantic versioning so code & DB migrations align.
 *    steps              – fixed-size array of steps.
 *    step_count         – number of valid steps stored in ::steps.
 *
 *    NOTE:  The struct is intentionally POD-style so that it can be serialized
 *           into JSON/YAML/TOML for interactive labs or persisted in the
 *           Audit Trail event stream without custom marshallers.
 */
typedef struct saga_definition
{
    const char    *saga_name;
    struct
    {
        uint16_t major;
        uint16_t minor;
        uint16_t patch;
    } version;
    saga_step_t   steps[SAGA_MAX_STEPS];
    uint8_t       step_count;
} saga_definition_t;

/* ──────────────────────────────────────────────────────────────
 *  API – Compile-Time Construction Helpers
 * ──────────────────────────────────────────────────────────── */

/**
 * SAGA_DEF_INIT:
 *    Macro to create an empty saga_definition_t literal at compile time.
 */
#define SAGA_DEF_INIT(NAME)                      \
    {                                            \
        .saga_name  = NAME,                      \
        .version    = {                          \
            .major = SAGA_DEFINITION_VERSION_MAJOR, \
            .minor = SAGA_DEFINITION_VERSION_MINOR, \
            .patch = SAGA_DEFINITION_VERSION_PATCH  \
        },                                       \
        .steps      = {0},                       \
        .step_count = 0                          \
    }

/**
 * saga_def_add_step:
 *    Adds a step to a saga_definition.  Safe for compile-time or run-time use.
 *
 * Parameters:
 *    def                 – pointer to saga_definition_t.
 *    step_name           – constant string, must outlive saga_definition_t.
 *    forward_fn          – required forward action.
 *    compensation_fn     – optional compensation (can be NULL).
 *
 * Returns:
 *    SAGA_OK on success, otherwise negative error code.
 */
static inline saga_rc_t
saga_def_add_step(saga_definition_t     *def,
                  const char            *step_name,
                  saga_step_action_fn    forward_fn,
                  saga_step_action_fn    compensation_fn)
{
    if (def == NULL || step_name == NULL || forward_fn == NULL)
        return SAGA_ERR_INVALID_ARG;

    if (def->step_count >= SAGA_MAX_STEPS)
        return SAGA_ERR_TOO_MANY_STEPS;

    uint8_t idx = def->step_count;

    def->steps[idx].id                  = idx;
    def->steps[idx].name                = step_name;
    def->steps[idx].forward_action      = forward_fn;
    def->steps[idx].compensation_action = compensation_fn;
    def->steps[idx].state               = SAGA_STEP_PENDING;

    def->step_count++;
    return SAGA_OK;
}

/* ──────────────────────────────────────────────────────────────
 *  API – Introspection Utilities
 * ──────────────────────────────────────────────────────────── */

/**
 * saga_def_get_step:
 *    Retrieves a mutable pointer to a step by ID.
 */
static inline saga_step_t *
saga_def_get_step(saga_definition_t *def, uint8_t id)
{
    if (def == NULL || id >= def->step_count)
        return NULL;
    return &def->steps[id];
}

/**
 * saga_def_find_step_by_name:
 *    Linear search is adequate because compile-time bound is small
 *    (≤ SAGA_MAX_STEPS).  Students can refactor to hashmap for bonus credit.
 */
static inline saga_step_t *
saga_def_find_step_by_name(saga_definition_t *def, const char *name)
{
    if (def == NULL || name == NULL)
        return NULL;

    for (uint8_t i = 0; i < def->step_count; i++)
    {
        if (def->steps[i].name && (strcmp(def->steps[i].name, name) == 0))
            return &def->steps[i];
    }
    return NULL;
}

/* ──────────────────────────────────────────────────────────────
 *  API – Validation
 * ──────────────────────────────────────────────────────────── */

/**
 * saga_def_validate:
 *    Performs a lightweight, synchronous verification that the saga
 *    definition is internally consistent before handing it off to an
 *    asynchronous executor.
 *
 * Returns:
 *    SAGA_OK              – definition passes sanity checks
 *    SAGA_ERR_INVALID_ARG – null pointer or missing callbacks
 */
static inline saga_rc_t
saga_def_validate(const saga_definition_t *def)
{
    if (def == NULL || def->step_count == 0)
        return SAGA_ERR_INVALID_ARG;

    for (uint8_t i = 0; i < def->step_count; i++)
    {
        const saga_step_t *s = &def->steps[i];
        if (s->forward_action == NULL)
            return SAGA_ERR_INVALID_ARG;
        /* Compensation function may be NULL (irreversible step). */
    }
    return SAGA_OK;
}

/* ──────────────────────────────────────────────────────────────
 *  Experimental Feature Flags
 * ──────────────────────────────────────────────────────────── */
#ifdef EDUPAY_SAGA_ENABLE_TRACE_IDS
#include <uuid/uuid.h>

/**
 * saga_trace_id_t:
 *    128-bit identifier used for distributed tracing in labs that integrate
 *    OpenTelemetry.  Defined under a feature flag so core business rules
 *    remain dependency-free unless professors opt-in.
 */
typedef struct
{
    uint8_t bytes[16];
} saga_trace_id_t;
#endif /* EDUPAY_SAGA_ENABLE_TRACE_IDS */

#endif /* EDUPAY_LEDGER_ACADEMY_CORE_SAGA_DEFINITION_H */
```