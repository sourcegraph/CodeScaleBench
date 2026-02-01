/*
 * LexiLearn MVC Orchestrator — Observer API
 *
 * File:    observer.h
 * Author:  LexiLearn Engineering Team
 * License: MIT
 *
 * Description
 * -----------
 * This header defines a lightweight, embeddable Observer/Observable framework
 * for the Controller layer.  Components that produce model-monitoring events
 * (e.g., drift detectors, training pipelines) expose an `observable_t`
 * instance, while downstream components (dashboards, alert dispatchers,
 * auto-retraining schedulers) register `observer_t` callbacks.
 *
 * The implementation is 100 % header-only: define
 *
 *      #define LEXILEARN_OBSERVER_IMPLEMENTATION
 *
 * in exactly one translation unit before including this file to pull in the
 * static-inline implementation.  All other translation units should include
 * this header *without* that macro.
 */

#ifndef LEXILEARN_CONTROLLER_MONITORING_OBSERVER_H
#define LEXILEARN_CONTROLLER_MONITORING_OBSERVER_H

/* ────────────────────────────────────────────────────────────────────────── */
/* Standard Library Dependencies                                            */
/* ────────────────────────────────────────────────────────────────────────── */
#include <stddef.h>     /* size_t  */
#include <stdint.h>     /* uint64_t */
#include <stdbool.h>    /* bool     */
#include <time.h>       /* timespec */

/* ────────────────────────────────────────────────────────────────────────── */
/* Public Constants                                                         */
/* ────────────────────────────────────────────────────────────────────────── */

/* Maximum number of observers that can subscribe to a single observable */
#ifndef OBSERVER_MAX_SUBSCRIBERS
#   define OBSERVER_MAX_SUBSCRIBERS 32
#endif

/* Maximum length (bytes) of model or component names */
#ifndef OBSERVER_MAX_NAME_LEN
#   define OBSERVER_MAX_NAME_LEN    64
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Event Types                                                              */
/* ────────────────────────────────────────────────────────────────────────── */
typedef enum {
    EVENT_NONE = 0,

    /* Drift / Monitoring */
    EVENT_MODEL_DRIFT,
    EVENT_DATA_DRIFT,

    /* Training Lifecycle */
    EVENT_TRAINING_START,
    EVENT_TRAINING_END,

    /* Hyper-parameter Tuning */
    EVENT_HPARAM_TUNING_START,
    EVENT_HPARAM_TUNING_END,

    /* Model Registry / Versioning */
    EVENT_MODEL_VERSION_CREATED,

    /* Health Monitoring */
    EVENT_HEARTBEAT,

    /* Generic Error */
    EVENT_ERROR
} observer_event_type_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Event Payload                                                            */
/* ────────────────────────────────────────────────────────────────────────── */
typedef struct {
    observer_event_type_t type;           /* Event discriminator           */
    uint64_t              id;             /* Monotonically increasing UID  */
    struct timespec       timestamp;      /*CLOCK_REALTIME when generated  */
    char                  model_name[OBSERVER_MAX_NAME_LEN]; /* affected model */
    double                metric_value;   /* e.g., drift score, loss value */
    const char           *payload;        /* Optional JSON/YAML blob       */
} observer_event_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Observer Definition                                                      */
/* ────────────────────────────────────────────────────────────────────────── */
struct observer;   /* Forward declaration */

typedef void (*observer_callback_t)(const observer_event_t *event,
                                    void                  *user_data);

typedef struct observer {
    char                name[OBSERVER_MAX_NAME_LEN]; /* Human-readable label */
    observer_callback_t on_event;                    /* Notification hook    */
    void               *user_data;                   /* Opaque context       */
} observer_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Observable Definition                                                    */
/* ────────────────────────────────────────────────────────────────────────── */
typedef struct {
    observer_t *subscribers[OBSERVER_MAX_SUBSCRIBERS];
    size_t      count;       /* Active subscriber count */
} observable_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* C-Linkage for C++ Consumers                                              */
/* ────────────────────────────────────────────────────────────────────────── */
#ifdef __cplusplus
extern "C" {
#endif

/* Initialize an observable in zero-initialized memory */
void observable_init(observable_t *observable);

/* Register an observer.  Returns 0 on success, <0 on error.                *
 *  - -1: invalid args; -2: capacity reached                                */
int  observable_subscribe(observable_t *observable,
                          observer_t   *subscriber);

/* Unregister an observer.  Returns 0 on success, <0 on error.              *
 *  - -1: invalid args; -2: subscriber not found                            */
int  observable_unsubscribe(observable_t *observable,
                            observer_t   *subscriber);

/* Dispatch an event to all registered observers. */
void observable_notify(const observable_t   *observable,
                       const observer_event_t *event);

/* Helper to create a fully-populated event struct                           *
 *  (uses CLOCK_REALTIME and a simple UID generator).                        */
observer_event_t observer_event_create(observer_event_type_t type,
                                       const char           *model_name,
                                       double                metric_value,
                                       const char           *payload);

/* Utility for logging/debugging.  Returns static string representation. */
const char *observer_event_type_str(observer_event_type_t type);

#ifdef __cplusplus
} /* extern "C" */
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Header-Only Implementation (optional)                                    */
/* ────────────────────────────────────────────────────────────────────────── */
#ifdef LEXILEARN_OBSERVER_IMPLEMENTATION

#include <string.h>  /* memset, strncpy */
#include <stdio.h>   /* snprintf        */

/* Initialize observable -------------------------------------------------- */
static inline void observable_init(observable_t *observable)
{
    if (!observable) return;
    observable->count = 0;
    memset(observable->subscribers, 0, sizeof(observable->subscribers));
}

/* Subscribe -------------------------------------------------------------- */
static inline int observable_subscribe(observable_t *observable,
                                       observer_t   *subscriber)
{
    if (!observable || !subscriber || !subscriber->on_event)
        return -1; /* invalid args */

    /* Prevent duplicate registration */
    for (size_t i = 0; i < observable->count; ++i)
        if (observable->subscribers[i] == subscriber)
            return 0; /* already subscribed */

    if (observable->count >= OBSERVER_MAX_SUBSCRIBERS)
        return -2; /* capacity exceeded */

    observable->subscribers[observable->count++] = subscriber;
    return 0;
}

/* Unsubscribe ------------------------------------------------------------ */
static inline int observable_unsubscribe(observable_t *observable,
                                         observer_t   *subscriber)
{
    if (!observable || !subscriber)
        return -1; /* invalid args */

    for (size_t i = 0; i < observable->count; ++i)
        if (observable->subscribers[i] == subscriber) {
            /* Compact the array in O(1) */
            observable->subscribers[i] = 
                observable->subscribers[observable->count - 1];
            observable->subscribers[observable->count - 1] = NULL;
            observable->count--;
            return 0;
        }

    return -2; /* not found */
}

/* Notify ----------------------------------------------------------------- */
static inline void observable_notify(const observable_t    *observable,
                                     const observer_event_t *event)
{
    if (!observable || !event) return;

    for (size_t i = 0; i < observable->count; ++i) {
        observer_t *sub = observable->subscribers[i];
        if (sub && sub->on_event)
            sub->on_event(event, sub->user_data);
    }
}

/* Event Factory ---------------------------------------------------------- */
static inline observer_event_t observer_event_create(observer_event_type_t type,
                                                     const char           *model_name,
                                                     double                metric_value,
                                                     const char           *payload)
{
    observer_event_t ev;

    ev.type   = type;
    ev.id     = ((uint64_t)time(NULL) << 32) ^ (uint64_t)(uintptr_t)&ev;
    clock_gettime(CLOCK_REALTIME, &ev.timestamp);

    if (model_name) {
        strncpy(ev.model_name, model_name, OBSERVER_MAX_NAME_LEN - 1);
        ev.model_name[OBSERVER_MAX_NAME_LEN - 1] = '\0';
    } else {
        ev.model_name[0] = '\0';
    }

    ev.metric_value = metric_value;
    ev.payload      = payload;
    return ev;
}

/* Stringify Event Type --------------------------------------------------- */
static inline const char *observer_event_type_str(observer_event_type_t type)
{
    switch (type) {
        case EVENT_NONE:                  return "NONE";
        case EVENT_MODEL_DRIFT:           return "MODEL_DRIFT";
        case EVENT_DATA_DRIFT:            return "DATA_DRIFT";
        case EVENT_TRAINING_START:        return "TRAINING_START";
        case EVENT_TRAINING_END:          return "TRAINING_END";
        case EVENT_HPARAM_TUNING_START:   return "HPARAM_TUNING_START";
        case EVENT_HPARAM_TUNING_END:     return "HPARAM_TUNING_END";
        case EVENT_MODEL_VERSION_CREATED: return "MODEL_VERSION_CREATED";
        case EVENT_HEARTBEAT:             return "HEARTBEAT";
        case EVENT_ERROR:                 return "ERROR";
        default:                          return "UNKNOWN";
    }
}

#endif /* LEXILEARN_OBSERVER_IMPLEMENTATION */
#endif /* LEXILEARN_CONTROLLER_MONITORING_OBSERVER_H */