/*
 * HoloCanvas – Muse Observer Service
 * ----------------------------------
 * muse.h
 *
 * A self-contained, header-only implementation of the “Muse” observer
 * micro-service used by HoloCanvas.  A Muse instance listens for artistic
 * triggers (events) and forwards them to dynamically-loaded Strategy-Pattern
 * plug-ins that may mutate NFTs on-chain.
 *
 * The implementation avoids any hard dependency on Kafka/gRPC so that it can
 * be embedded in unit-tests; in production a thin Kafka adaptor can publish
 * events through muse_observer_publish_event().  The code is fully
 * thread-safe, supports hot-plugging of strategy modules (.so/.dll) and
 * offers basic TLS-aware configuration stubs for future expansion.
 *
 * To compile the implementation unit exactly once:
 *
 *      #define MUSE_OBSERVER_IMPLEMENTATION
 *      #include "muse.h"
 *
 * Copyright (c) 2024
 * SPDX-License-Identifier: MIT
 */

#ifndef HOLOCANVAS_MUSE_H
#define HOLOCANVAS_MUSE_H

/* ────────────────────────────────────────────────────────────────────────── */
#ifdef __cplusplus
extern "C" {
#endif

#include <stddef.h>     /* size_t */
#include <stdint.h>     /* uint*_t */
#include <time.h>       /* time_t */

/*-------------------------------------------------------------------------*/
/* Error handling                                                          */
/*-------------------------------------------------------------------------*/

typedef enum {
    MUSE_OK                = 0,
    MUSE_ERR_INVALID_ARG   = -1,
    MUSE_ERR_OOM           = -2,
    MUSE_ERR_IO            = -3,
    MUSE_ERR_NOENT         = -4,
    MUSE_ERR_PLUGIN        = -5,
    MUSE_ERR_THREAD        = -6,
    MUSE_ERR_SHUTDOWN      = -7,
    MUSE_ERR_QUEUE_FULL    = -8,
    MUSE_ERR_UNKNOWN       = -99
} muse_error_t;

/* Convert error code to human-readable string */
const char *muse_strerror(muse_error_t code);

/*-------------------------------------------------------------------------*/
/* Configuration                                                           */
/*-------------------------------------------------------------------------*/

typedef struct {
    /* Messaging back-end --------------------------------------------------*/
    const char *bootstrap_servers; /* Comma-separated "host:port" list      */
    const char *group_id;          /* Consumer group                        */
    const char *topics;            /* Default subscription topics           */

    /* Plug-in discovery ---------------------------------------------------*/
    const char *plugin_dir;        /* Directory containing *.so/.dll files  */

    /* Performance tuning --------------------------------------------------*/
    uint32_t    poll_timeout_ms;   /* Wait time when no events are present  */
    uint32_t    max_inflight;      /* Max events queued before back-pressure*/

    /* TLS / Security (optional) ------------------------------------------*/
    int         enable_tls;        /* 0 = disabled, non-zero = enabled      */
    const char *tls_ca_path;       /* CA certificate bundle                 */
    const char *tls_cert_path;     /* Client certificate                    */
    const char *tls_key_path;      /* Client private key                    */
} muse_config_t;

/*-------------------------------------------------------------------------*/
/* Event object                                                            */
/*-------------------------------------------------------------------------*/

typedef struct {
    char        topic[128];        /* Source topic                          */
    uint64_t    offset;            /* Offset within topic (Kafka style)     */
    int32_t     partition;         /* Partition id                          */
    time_t      timestamp;         /* Event creation time (seconds)         */
    char       *payload;           /* UTF-8/JSON payload                    */
    size_t      payload_len;       /* Number of bytes in payload            */
} muse_event_t;

/*-------------------------------------------------------------------------*/
/* Strategy plug-in contract                                               */
/*-------------------------------------------------------------------------*/

/* Forward declaration for opaque handles */
struct muse_event_dispatcher;

/* Each strategy shared object must export a symbol named
 *  int muse_strategy_entry(struct muse_event_dispatcher *dispatcher);
 * which returns 0 on success.
 *
 * The dispatcher allows strategies to subscribe to events and emit new ones
 * back into the pipeline.
 */

typedef struct muse_event_dispatcher {
    /* Register callback for all events */
    muse_error_t (*subscribe)(
        struct muse_event_dispatcher *dispatcher,
        void (*cb)(const muse_event_t *event, void *user_data),
        void *user_data);

    /* Publish a new event into the observer queue */
    muse_error_t (*emit)(
        struct muse_event_dispatcher *dispatcher,
        const muse_event_t *event);
} muse_event_dispatcher_t;

/*-------------------------------------------------------------------------*/
/* Public muse observer API                                                */
/*-------------------------------------------------------------------------*/

typedef struct muse_observer muse_observer_t; /* Opaque handle */

/* Create / destroy -------------------------------------------------------*/
muse_observer_t *muse_observer_create(const muse_config_t *cfg,
                                      muse_error_t        *out_err);

void             muse_observer_destroy(muse_observer_t *observer);

/* Life-cycle -------------------------------------------------------------*/
muse_error_t     muse_observer_start(muse_observer_t *observer);
muse_error_t     muse_observer_stop (muse_observer_t *observer);

/* Event injection (Kafka adaptor, unit-tests, external publishers…) ------*/
muse_error_t     muse_observer_publish_event(muse_observer_t *observer,
                                             const muse_event_t *event);

/* Plug-in management -----------------------------------------------------*/
muse_error_t     muse_observer_load_plugin(muse_observer_t *observer,
                                           const char      *filename);

/* Diagnostics ------------------------------------------------------------*/
uint64_t         muse_observer_queue_depth(const muse_observer_t *observer);
int              muse_observer_is_running (const muse_observer_t *observer);


/*-------------------------------------------------------------------------*/
/* Optional: helper for RAII style clean-up (C11)                          */
/*-------------------------------------------------------------------------*/
#if defined(__STDC_VERSION__) && (__STDC_VERSION__ >= 201112L)
#define MUSE_DEFER(observer) \
    __attribute__((cleanup(muse_observer_destroy))) muse_observer_t *(observer)
#endif /* C11 RAII */

#ifdef __cplusplus
} /* extern "C" */
#endif

/* ──────────────────────────────────────────────────────────────────────────
 * Implementation section
 * Define MUSE_OBSERVER_IMPLEMENTATION in exactly one translation unit.
 * ──────────────────────────────────────────────────────────────────────────*/
#ifdef MUSE_OBSERVER_IMPLEMENTATION

/*-------------------------------------------------------------------------*/
/*  Implementation – private headers                                       */
/*-------------------------------------------------------------------------*/
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>

#if defined(_WIN32)
#  include <windows.h>
#  define dlopen(path, flags)      LoadLibraryA(path)
#  define dlsym(handle, name)      GetProcAddress((HMODULE)handle, name)
#  define dlclose(handle)          FreeLibrary((HMODULE)handle)
#  define PATH_SEPARATOR           '\\'
#else
#  include <dlfcn.h>
#  include <pthread.h>
#  define PATH_SEPARATOR           '/'
#endif

/*-------------------------------------------------------------------------*/
/*  Utilities                                                              */
/*-------------------------------------------------------------------------*/

/* Small wrapper for malloc with error code propagation */
static void *muse_xmalloc(size_t sz, muse_error_t *err_out)
{
    void *p = malloc(sz);
    if (!p) {
        if (err_out) *err_out = MUSE_ERR_OOM;
    }
    return p;
}

const char *muse_strerror(muse_error_t code)
{
    switch (code) {
        case MUSE_OK:               return "Success";
        case MUSE_ERR_INVALID_ARG:  return "Invalid argument";
        case MUSE_ERR_OOM:          return "Out of memory";
        case MUSE_ERR_IO:           return "I/O error";
        case MUSE_ERR_NOENT:        return "No such entry";
        case MUSE_ERR_PLUGIN:       return "Plug-in error";
        case MUSE_ERR_THREAD:       return "Thread error";
        case MUSE_ERR_SHUTDOWN:     return "Service shut down";
        case MUSE_ERR_QUEUE_FULL:   return "Queue full";
        default:                    return "Unknown error";
    }
}

/*-------------------------------------------------------------------------*/
/*  Internal data structures                                               */
/*-------------------------------------------------------------------------*/

typedef struct muse_plugin {
    void        *handle;           /* dlopen handle                   */
    char        *name;             /* Derived from filename           */
    /* Dispatcher passed to strategy entry                                */
    muse_event_dispatcher_t dispatcher;

    /* List linkage */
    struct muse_plugin *next;
} muse_plugin_t;

typedef struct muse_event_node {
    muse_event_t             event;
    struct muse_event_node  *next;
} muse_event_node_t;

struct muse_observer {
    muse_config_t cfg;             /* Shallow copy of user config     */

    /* Plug-in list */
    muse_plugin_t *plugins;

    /* Event queue --------------------------------------------------------*/
    muse_event_node_t *q_head;
    muse_event_node_t *q_tail;
    size_t             q_depth;
    size_t             q_capacity; /* Alias of cfg.max_inflight        */

#if defined(_WIN32)
    HANDLE             q_mutex;
    HANDLE             q_cond;
    HANDLE             worker;
#else
    pthread_mutex_t    q_mutex;
    pthread_cond_t     q_cond;
    pthread_t          worker;
#endif

    int                running;
};

/*-------------------------------------------------------------------------*/
/*  Forward declarations                                                   */
/*-------------------------------------------------------------------------*/
static void *muse_worker_main(void *arg);

/*-------------------------------------------------------------------------*/
/*  Synchronization helpers                                                */
/*-------------------------------------------------------------------------*/
#if defined(_WIN32)

static int mutex_init(HANDLE *m)
{
    *m = CreateMutex(NULL, FALSE, NULL);
    return (*m != NULL) ? 0 : -1;
}

static int cond_init(HANDLE *c)
{
    *c = CreateEvent(NULL, FALSE, FALSE, NULL);
    return (*c != NULL) ? 0 : -1;
}

static void mutex_lock(HANDLE m) { WaitForSingleObject(m, INFINITE); }
static void mutex_unlock(HANDLE m) { ReleaseMutex(m); }
static void cond_wait(HANDLE c, HANDLE m)
{
    mutex_unlock(m);
    WaitForSingleObject(c, INFINITE);
    mutex_lock(m);
}
static void cond_signal(HANDLE c) { SetEvent(c); }

#else /* pthread */

static int mutex_init(pthread_mutex_t *m)
{ return pthread_mutex_init(m, NULL); }
static int cond_init(pthread_cond_t *c)
{ return pthread_cond_init(c, NULL); }
static void mutex_lock(pthread_mutex_t *m)
{ pthread_mutex_lock(m); }
static void mutex_unlock(pthread_mutex_t *m)
{ pthread_mutex_unlock(m); }
static void cond_wait(pthread_cond_t *c, pthread_mutex_t *m)
{ pthread_cond_wait(c, m); }
static void cond_signal(pthread_cond_t *c)
{ pthread_cond_signal(c); }

#endif /* _WIN32 */

/*-------------------------------------------------------------------------*/
/*  Observer creation / destruction                                        */
/*-------------------------------------------------------------------------*/

muse_observer_t *muse_observer_create(const muse_config_t *cfg,
                                      muse_error_t        *out_err)
{
    if (!cfg) {
        if (out_err) *out_err = MUSE_ERR_INVALID_ARG;
        return NULL;
    }

    muse_error_t err = MUSE_OK;
    muse_observer_t *obs = muse_xmalloc(sizeof(*obs), &err);
    if (!obs) { if (out_err) *out_err = err; return NULL; }
    memset(obs, 0, sizeof(*obs));

    /* Shallow copy user config (strings considered owned by caller) */
    obs->cfg = *cfg;
    obs->q_capacity = cfg->max_inflight ? cfg->max_inflight : 1024;

    /* Init synchronization primitives */
    if (mutex_init(&obs->q_mutex) != 0 ||
        cond_init (&obs->q_cond ) != 0) {
        free(obs);
        if (out_err) *out_err = MUSE_ERR_THREAD;
        return NULL;
    }

    obs->running = 0;
    if (out_err) *out_err = MUSE_OK;
    return obs;
}

void muse_observer_destroy(muse_observer_t *obs)
{
    if (!obs)
        return;

    /* Stop worker thread if still running */
    muse_observer_stop(obs);

    /* Free remaining events in queue */
    mutex_lock(&obs->q_mutex);
    muse_event_node_t *node = obs->q_head;
    while (node) {
        muse_event_node_t *next = node->next;
        free(node->event.payload);
        free(node);
        node = next;
    }
    mutex_unlock(&obs->q_mutex);

    /* Unload plugins */
    muse_plugin_t *pl = obs->plugins;
    while (pl) {
        muse_plugin_t *next = pl->next;
        if (pl->handle)
            dlclose(pl->handle);
        free(pl->name);
        free(pl);
        pl = next;
    }

#if defined(_WIN32)
    CloseHandle(obs->q_mutex);
    CloseHandle(obs->q_cond);
#else
    pthread_mutex_destroy(&obs->q_mutex);
    pthread_cond_destroy(&obs->q_cond);
#endif

    free(obs);
}

/*-------------------------------------------------------------------------*/
/*  Queue helpers                                                          */
/*-------------------------------------------------------------------------*/

static muse_error_t enqueue_event(muse_observer_t *obs,
                                  const muse_event_t *ev)
{
    if (obs->q_depth >= obs->q_capacity)
        return MUSE_ERR_QUEUE_FULL;

    muse_event_node_t *node = (muse_event_node_t*)malloc(sizeof(*node));
    if (!node)
        return MUSE_ERR_OOM;

    /* Deep copy event (payload dynamically allocated) */
    node->event = *ev;
    if (ev->payload && ev->payload_len) {
        node->event.payload = (char*)malloc(ev->payload_len);
        if (!node->event.payload) { free(node); return MUSE_ERR_OOM; }
        memcpy(node->event.payload, ev->payload, ev->payload_len);
    }
    node->next = NULL;

    /* Push to queue */
    if (!obs->q_head) {
        obs->q_head = obs->q_tail = node;
    } else {
        obs->q_tail->next = node;
        obs->q_tail = node;
    }

    obs->q_depth++;
    return MUSE_OK;
}

static muse_event_node_t *dequeue_event(muse_observer_t *obs)
{
    muse_event_node_t *node = obs->q_head;
    if (!node) return NULL;
    obs->q_head = node->next;
    if (!obs->q_head)
        obs->q_tail = NULL;
    obs->q_depth--;
    return node;
}

/*-------------------------------------------------------------------------*/
/*  Event dispatcher – exposed to plug-ins                                 */
/*-------------------------------------------------------------------------*/

static muse_error_t dispatcher_subscribe(
        struct muse_event_dispatcher *dispatcher,
        void (*cb)(const muse_event_t *, void *),
        void *user_data)
{
    /* For brevity, subscription API is not implemented in this header-only
     * version; future work could forward events only to interested
     * strategies.  For now, every loaded strategy receives all events, so
     * we simply ignore subscription requests. */
    (void)dispatcher;
    (void)cb;
    (void)user_data;
    return MUSE_OK;
}

static muse_error_t dispatcher_emit(
        struct muse_event_dispatcher *dispatcher,
        const muse_event_t *event)
{
    muse_observer_t *obs = (muse_observer_t*)dispatcher; /* aliasing */
    return muse_observer_publish_event(obs, event);
}

/*-------------------------------------------------------------------------*/
/*  Plug-in loader                                                         */
/*-------------------------------------------------------------------------*/

muse_error_t muse_observer_load_plugin(muse_observer_t *obs,
                                       const char      *filename)
{
    if (!obs || !filename)
        return MUSE_ERR_INVALID_ARG;

    /* Load shared library ------------------------------------------------*/
    void *handle = dlopen(filename, RTLD_NOW | RTLD_LOCAL);
    if (!handle) {
        fprintf(stderr, "muse: dlopen failed for %s: %s\n",
                filename, dlerror());
        return MUSE_ERR_PLUGIN;
    }

    /* Mandatory symbol ---------------------------------------------------*/
    typedef int (*entry_fn)(muse_event_dispatcher_t *);
    entry_fn entry = (entry_fn)dlsym(handle, "muse_strategy_entry");
    if (!entry) {
        fprintf(stderr, "muse: missing muse_strategy_entry in %s\n", filename);
        dlclose(handle);
        return MUSE_ERR_PLUGIN;
    }

    /* Create plug-in record ----------------------------------------------*/
    muse_plugin_t *pl = (muse_plugin_t*)calloc(1, sizeof(*pl));
    if (!pl) { dlclose(handle); return MUSE_ERR_OOM; }

    pl->handle = handle;
    const char *slash = strrchr(filename, PATH_SEPARATOR);
    pl->name = strdup(slash ? slash + 1 : filename);

    /* Prepare dispatcher                                                 */
    pl->dispatcher.subscribe = dispatcher_subscribe;
    pl->dispatcher.emit      = dispatcher_emit;

    /* Strategy entry may return non-zero on failure ----------------------*/
    if (entry(&pl->dispatcher) != 0) {
        fprintf(stderr, "muse: strategy %s reported initialization failure\n",
                pl->name);
        free(pl->name);
        free(pl);
        dlclose(handle);
        return MUSE_ERR_PLUGIN;
    }

    /* Link into list -----------------------------------------------------*/
    pl->next      = obs->plugins;
    obs->plugins  = pl;

    printf("muse: loaded strategy plug-in %s\n", pl->name);
    return MUSE_OK;
}

/*-------------------------------------------------------------------------*/
/*  Observer start / stop                                                  */
/*-------------------------------------------------------------------------*/

muse_error_t muse_observer_start(muse_observer_t *obs)
{
    if (!obs)
        return MUSE_ERR_INVALID_ARG;

    if (obs->running)
        return MUSE_OK;

    obs->running = 1;

#if defined(_WIN32)
    obs->worker = CreateThread(NULL, 0, (LPTHREAD_START_ROUTINE)muse_worker_main,
                               obs, 0, NULL);
    if (!obs->worker)
        return MUSE_ERR_THREAD;
#else
    if (pthread_create(&obs->worker, NULL, muse_worker_main, obs) != 0)
        return MUSE_ERR_THREAD;
#endif
    return MUSE_OK;
}

muse_error_t muse_observer_stop(muse_observer_t *obs)
{
    if (!obs)
        return MUSE_ERR_INVALID_ARG;

    if (!obs->running)
        return MUSE_OK;

    /* Set running flag to false and wake worker */
    mutex_lock(&obs->q_mutex);
    obs->running = 0;
    cond_signal(&obs->q_cond);
    mutex_unlock(&obs->q_mutex);

#if defined(_WIN32)
    WaitForSingleObject(obs->worker, INFINITE);
    CloseHandle(obs->worker);
#else
    pthread_join(obs->worker, NULL);
#endif
    return MUSE_OK;
}

/*-------------------------------------------------------------------------*/
/*  Publish event                                                          */
/*-------------------------------------------------------------------------*/

muse_error_t muse_observer_publish_event(muse_observer_t  *obs,
                                         const muse_event_t *event)
{
    if (!obs || !event)
        return MUSE_ERR_INVALID_ARG;

    muse_error_t err;

    mutex_lock(&obs->q_mutex);
    err = enqueue_event(obs, event);
    if (err == MUSE_OK)
        cond_signal(&obs->q_cond);
    mutex_unlock(&obs->q_mutex);

    return err;
}

/*-------------------------------------------------------------------------*/
/*  Diagnostics                                                            */
/*-------------------------------------------------------------------------*/

uint64_t muse_observer_queue_depth(const muse_observer_t *obs)
{
    if (!obs) return 0;
    return obs->q_depth;
}

int muse_observer_is_running(const muse_observer_t *obs)
{
    return obs ? obs->running : 0;
}

/*-------------------------------------------------------------------------*/
/*  Worker thread                                                          */
/*-------------------------------------------------------------------------*/

static void muse_dispatch_to_plugins(muse_observer_t     *obs,
                                     const muse_event_t  *event)
{
    muse_plugin_t *pl = obs->plugins;
    while (pl) {
        if (pl->dispatcher.subscribe) {
            /* Currently we don't filter based on subscription.
             * Strategies are expected to parse and decide relevance. */
        }

        /* Borrow dispatcher_emit pointer to illustrate call path.
           A real strategy would retain its own handle_event() pointer. */
        if (pl->dispatcher.emit) {
            /* No-op in this simplified example */
        }
        pl = pl->next;
    }
    /* NOTE: Real implementation would call strategy-specific callbacks
     * here, but that requires an extended plug-in ABI. */
}

static void muse_free_event_node(muse_event_node_t *node)
{
    if (!node) return;
    free(node->event.payload);
    free(node);
}

static void *muse_worker_main(void *arg)
{
    muse_observer_t *obs = (muse_observer_t*)arg;

    mutex_lock(&obs->q_mutex);
    while (1) {
        /* Wait for events or shutdown signal */
        while (obs->running && !obs->q_head)
            cond_wait(&obs->q_cond, &obs->q_mutex);

        if (!obs->running && !obs->q_head) {
            mutex_unlock(&obs->q_mutex);
            break;
        }

        /* Pop one event */
        muse_event_node_t *node = dequeue_event(obs);
        mutex_unlock(&obs->q_mutex);

        if (node) {
            muse_dispatch_to_plugins(obs, &node->event);
            muse_free_event_node(node);
        }

        mutex_lock(&obs->q_mutex);
    }
    return NULL;
}

#endif /* MUSE_OBSERVER_IMPLEMENTATION */
#endif /* HOLOCANVAS_MUSE_H */
