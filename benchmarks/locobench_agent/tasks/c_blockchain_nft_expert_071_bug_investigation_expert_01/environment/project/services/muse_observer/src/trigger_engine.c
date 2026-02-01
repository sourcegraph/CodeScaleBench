```c
/**
 * HoloCanvas – Muse Observer
 * File: trigger_engine.c
 *
 * Description
 * -----------
 * A generic trigger-evaluation engine responsible for listening to the
 * event-bus (Kafka/gRPC) and invoking user-supplied Strategy plug-ins once a
 * configured artistic condition has been met (e.g., “≥ 500 likes” or
 * “temperature < 0 °C”).  The implementation is transport-agnostic; the
 * concrete event source is injected at runtime via a callback interface so
 * that unit tests can easily stub or mock it.
 *
 * Concurrency
 * -----------
 * The engine maintains a dedicated worker thread that continuously pulls
 * events from the bus.  A RW-lock guards the mutable trigger registry so
 * that readers (evaluation) and writers (register/unregister) do not race.
 *
 * Error handling & logging
 * ------------------------
 * All user-facing API calls return a detailed status code (trigger_status_t)
 * that can be converted into a human-readable message with
 * trigger_status_str().  Compact, production-grade logging macros are used
 * instead of printf(3) directly, and can later be wired to syslog or
 * CloudWatch.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#include <time.h>
#include <unistd.h>

/* -------------------------------------------------------------------------- */
/*                              Compile-time opts                             */
/* -------------------------------------------------------------------------- */

#ifndef TE_MAX_TRIGGERS
#   define TE_MAX_TRIGGERS   128u        /* Hard upper-bound for simplicity   */
#endif

#ifndef TE_EVENT_TOPIC_MAX
#   define TE_EVENT_TOPIC_MAX  64u
#endif

#ifndef TE_EVENT_PAYLOAD_MAX
#   define TE_EVENT_PAYLOAD_MAX 256u
#endif

/* -------------------------------------------------------------------------- */
/*                                   Logging                                  */
/* -------------------------------------------------------------------------- */

#define LOG_TAG "muse_trigger_engine"

#define LOG_ERR(fmt, ...)   fprintf(stderr, "[%s][ERR] " fmt "\n", LOG_TAG, ##__VA_ARGS__)
#define LOG_WARN(fmt, ...)  fprintf(stderr, "[%s][WRN] " fmt "\n", LOG_TAG, ##__VA_ARGS__)
#define LOG_INFO(fmt, ...)  fprintf(stdout, "[%s][INF] " fmt "\n", LOG_TAG, ##__VA_ARGS__)
#define LOG_DBG(fmt, ...)   fprintf(stdout, "[%s][DBG] " fmt "\n", LOG_TAG, ##__VA_ARGS__)

/* -------------------------------------------------------------------------- */
/*                              Status / Error codes                          */
/* -------------------------------------------------------------------------- */

typedef enum {
    TE_STATUS_OK = 0,
    TE_STATUS_EINVAL,
    TE_STATUS_ENOMEM,
    TE_STATUS_EFULL,
    TE_STATUS_ENOTFOUND,
    TE_STATUS_EBUSY,
    TE_STATUS_EINTERNAL,
} trigger_status_t;

static const char *trigger_status_str(trigger_status_t st)
{
    switch (st) {
        case TE_STATUS_OK:        return "OK";
        case TE_STATUS_EINVAL:    return "Invalid argument";
        case TE_STATUS_ENOMEM:    return "Out of memory";
        case TE_STATUS_EFULL:     return "Registry full";
        case TE_STATUS_ENOTFOUND: return "Trigger not found";
        case TE_STATUS_EBUSY:     return "Engine busy";
        case TE_STATUS_EINTERNAL: return "Internal error";
        default:                  return "Unknown";
    }
}

/* -------------------------------------------------------------------------- */
/*                          Event Source Abstraction                          */
/* -------------------------------------------------------------------------- */

typedef bool (*event_fetch_fn)(
        void          *ctx,
        char          *topic,      size_t topic_cap,
        char          *payload,    size_t payload_cap,
        uint64_t      *timestamp_ns);

/*
 * The concrete implementation of `event_fetch_fn` must:
 *   • Block until a new event is available, or return false on fatal error.
 *   • Populate 'topic' and 'payload' strings and null-terminate them.
 *   • Fill 'timestamp_ns' (Unix epoch, nanoseconds).
 *   • Observe the supplied '..._cap' buffer size limits.
 */

/* -------------------------------------------------------------------------- */
/*                                Trigger Model                               */
/* -------------------------------------------------------------------------- */

/* User-supplied callback signature */
typedef void (*trigger_cb_t)(
        const char *topic,
        const char *payload,
        uint64_t    timestamp_ns,
        void       *user_data);

typedef struct {
    char         id[64];                      /* Unique trigger identifier   */
    char         topic[TE_EVENT_TOPIC_MAX];   /* Event topic this trigger listens to  */
    uint32_t     threshold;                   /* Simple integer threshold    */
    atomic_uint  counter;                     /* How many times topic seen   */
    trigger_cb_t callback;                    /* Strategy function to invoke */
    void        *user_data;                   /* Opaque pointer passed back  */
} muse_trigger_t;

/* -------------------------------------------------------------------------- */
/*                          Engine private – internals                        */
/* -------------------------------------------------------------------------- */

typedef struct {
    muse_trigger_t triggers[TE_MAX_TRIGGERS];
    atomic_uint     used;                 /* Number of active triggers            */
    pthread_rwlock_t rwlock;              /* Guards `triggers` array              */

    /* Worker thread management */
    pthread_t       worker_th;
    atomic_bool     worker_run;

    /* Injected event source */
    event_fetch_fn  fetch_fn;
    void           *fetch_ctx;
} trigger_engine_t;

/* -------------------------------------------------------------------------- */
/*                           Forward declarations                             */
/* -------------------------------------------------------------------------- */

static void* worker_thread_main(void *arg);

/* -------------------------------------------------------------------------- */
/*                              Public API                                    */
/* -------------------------------------------------------------------------- */

/**
 * Initialize a trigger engine instance.
 */
trigger_status_t trigger_engine_init(trigger_engine_t *eng,
                                     event_fetch_fn     fetch_fn,
                                     void              *fetch_ctx)
{
    if (!eng || !fetch_fn) {
        return TE_STATUS_EINVAL;
    }

    memset(eng, 0, sizeof(*eng));
    eng->fetch_fn  = fetch_fn;
    eng->fetch_ctx = fetch_ctx;

    if (pthread_rwlock_init(&eng->rwlock, NULL) != 0) {
        LOG_ERR("Failed to init RW-lock: %s", strerror(errno));
        return TE_STATUS_EINTERNAL;
    }

    /* Launch worker thread */
    eng->worker_run = true;
    if (pthread_create(&eng->worker_th, NULL, worker_thread_main, eng) != 0) {
        LOG_ERR("Failed to spawn worker thread: %s", strerror(errno));
        pthread_rwlock_destroy(&eng->rwlock);
        return TE_STATUS_EINTERNAL;
    }

    LOG_INFO("Trigger engine initialized");
    return TE_STATUS_OK;
}

/**
 * Gracefully shut down the trigger engine.
 */
trigger_status_t trigger_engine_shutdown(trigger_engine_t *eng)
{
    if (!eng) return TE_STATUS_EINVAL;

    /* Signal worker to exit */
    eng->worker_run = false;
    pthread_join(eng->worker_th, NULL);

    pthread_rwlock_destroy(&eng->rwlock);

    LOG_INFO("Trigger engine shut down");
    return TE_STATUS_OK;
}

/**
 * Register a new trigger. Returns TE_STATUS_EFULL if registry is saturated or
 * TE_STATUS_EINVAL if duplicate ID found.
 */
trigger_status_t trigger_engine_register(trigger_engine_t *eng,
                                         const char       *id,
                                         const char       *topic,
                                         uint32_t          threshold,
                                         trigger_cb_t      cb,
                                         void             *user_data)
{
    if (!eng || !id || !topic || !cb || threshold == 0) {
        return TE_STATUS_EINVAL;
    }

    if (strlen(id) >= sizeof(((muse_trigger_t*)0)->id) ||
        strlen(topic) >= sizeof(((muse_trigger_t*)0)->topic)) {
        return TE_STATUS_EINVAL;
    }

    trigger_status_t rc = TE_STATUS_OK;

    pthread_rwlock_wrlock(&eng->rwlock);

    /* Prevent duplicate IDs */
    for (unsigned i = 0; i < eng->used; ++i) {
        if (strcmp(eng->triggers[i].id, id) == 0) {
            rc = TE_STATUS_EINVAL;
            goto exit;
        }
    }

    if (eng->used >= TE_MAX_TRIGGERS) {
        rc = TE_STATUS_EFULL;
        goto exit;
    }

    muse_trigger_t *slot = &eng->triggers[eng->used++];
    memset(slot, 0, sizeof(*slot));
    strcpy(slot->id, id);
    strcpy(slot->topic, topic);
    slot->threshold = threshold;
    atomic_store(&slot->counter, 0);
    slot->callback  = cb;
    slot->user_data = user_data;

    LOG_INFO("Registered trigger '%s' (topic='%s', threshold=%u)", id, topic, threshold);

exit:
    pthread_rwlock_unlock(&eng->rwlock);
    return rc;
}

/**
 * Unregister an existing trigger.
 */
trigger_status_t trigger_engine_unregister(trigger_engine_t *eng,
                                           const char       *id)
{
    if (!eng || !id) return TE_STATUS_EINVAL;

    trigger_status_t rc = TE_STATUS_ENOTFOUND;

    pthread_rwlock_wrlock(&eng->rwlock);

    for (unsigned i = 0; i < eng->used; ++i) {
        if (strcmp(eng->triggers[i].id, id) == 0) {
            /* Swap-and-pop */
            eng->triggers[i] = eng->triggers[eng->used - 1];
            memset(&eng->triggers[eng->used - 1], 0, sizeof(muse_trigger_t));
            eng->used--;
            LOG_INFO("Unregistered trigger '%s'", id);
            rc = TE_STATUS_OK;
            break;
        }
    }

    pthread_rwlock_unlock(&eng->rwlock);
    return rc;
}

/* -------------------------------------------------------------------------- */
/*                       Worker thread – event processing                     */
/* -------------------------------------------------------------------------- */

static void* worker_thread_main(void *arg)
{
    trigger_engine_t *eng = (trigger_engine_t*)arg;
    char topic[TE_EVENT_TOPIC_MAX];
    char payload[TE_EVENT_PAYLOAD_MAX];
    uint64_t ts_ns = 0;

    pthread_setname_np(pthread_self(), "muse_trig_eng");

    while (atomic_load(&eng->worker_run)) {
        bool ok = eng->fetch_fn(eng->fetch_ctx,
                                topic, sizeof(topic),
                                payload, sizeof(payload),
                                &ts_ns);
        if (!ok) { /* fatal bus error – sleep to avoid busy loop */
            LOG_ERR("Event bus returned fatal error; backing off 1s");
            sleep(1);
            continue;
        }

        pthread_rwlock_rdlock(&eng->rwlock);

        for (unsigned i = 0; i < eng->used; ++i) {
            muse_trigger_t *tr = &eng->triggers[i];

            if (strcmp(tr->topic, topic) != 0)
                continue;

            unsigned prev = atomic_fetch_add(&tr->counter, 1u) + 1u;
            LOG_DBG("Trigger '%s' counter=%u/%u (topic=%s)",
                    tr->id, prev, tr->threshold, topic);

            if (prev >= tr->threshold) {
                /* Reset counter BEFORE invoking callback to avoid reentrancy races. */
                atomic_store(&tr->counter, 0u);

                /* Unlock while doing user callback – allow registry ops inside callback */
                pthread_rwlock_unlock(&eng->rwlock);
                LOG_INFO("Trigger '%s' fired; invoking strategy", tr->id);
                tr->callback(topic, payload, ts_ns, tr->user_data);
                pthread_rwlock_rdlock(&eng->rwlock); /* Reacquire for next iteration */
            }
        }

        pthread_rwlock_unlock(&eng->rwlock);
    }

    LOG_INFO("Worker thread exiting");
    return NULL;
}

/* -------------------------------------------------------------------------- */
/*                       ------------  Test stub -------------                */
/*  The following section is only compiled when this file is built as a       */
/*  standalone object (e.g., `cc trigger_engine.c -DTE_TEST_MAIN ...`) for    */
/*  manual smoke testing.  In production, the engine is linked into the       */
/*  Muse Observer microservice and the real event bus adapter is provided.    */
/* -------------------------------------------------------------------------- */
#ifdef TE_TEST_MAIN

#include <signal.h>

/* Simple in-memory ring of demo events */
typedef struct {
    const char *topic;
    const char *payload;
    uint32_t    repeat;
} demo_evt_t;

static const demo_evt_t DEMO_EVENTS[] = {
    { "likes",  "{\"count\":1}",  5 },
    { "bids",   "{\"eth\":0.2}",  3 },
    { "likes",  "{\"count\":1}",  5 },
    { "bids",   "{\"eth\":0.1}", 10 },
};

typedef struct {
    size_t  idx;
    size_t  sub;
} demo_bus_ctx_t;

static bool demo_fetch(void *ctx,
                       char *topic,    size_t topic_cap,
                       char *payload,  size_t payload_cap,
                       uint64_t *ts_ns)
{
    demo_bus_ctx_t *bus = (demo_bus_ctx_t*)ctx;
    if (bus->idx >= sizeof(DEMO_EVENTS)/sizeof(DEMO_EVENTS[0]))
        bus->idx = 0;

    const demo_evt_t *ev = &DEMO_EVENTS[bus->idx];

    strncpy(topic, ev->topic, topic_cap - 1);
    strncpy(payload, ev->payload, payload_cap - 1);
    *ts_ns = (uint64_t)time(NULL) * 1000000000ull;

    if (++bus->sub >= ev->repeat) {
        bus->idx++;
        bus->sub = 0;
    }

    /* simulate 100 ms bus latency */
    usleep(100000);
    return true;
}

static void on_like_threshold(const char *topic,
                              const char *payload,
                              uint64_t    ts_ns,
                              void       *user_data)
{
    (void)user_data;
    time_t t = (time_t)(ts_ns / 1000000000ull);
    LOG_INFO("Strategy fired! topic=%s payload=%s ts=%s",
             topic, payload, ctime(&t));
}

static volatile sig_atomic_t g_stop = 0;
static void on_sigint(int s) { (void)s; g_stop = 1; }

int main(void)
{
    signal(SIGINT, on_sigint);

    trigger_engine_t eng;
    demo_bus_ctx_t   bus_ctx = {0};

    if (trigger_engine_init(&eng, demo_fetch, &bus_ctx) != TE_STATUS_OK) {
        return EXIT_FAILURE;
    }

    trigger_engine_register(&eng, "like_threshold",
                            "likes", 10,
                            on_like_threshold, NULL);

    while (!g_stop) {
        sleep(1);
    }

    trigger_engine_shutdown(&eng);
    return EXIT_SUCCESS;
}
#endif  /* TE_TEST_MAIN */
```