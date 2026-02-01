/*
 * evolution_strategist.c
 *
 * HoloCanvas – Muse Observer Service
 * ----------------------------------
 * Strategy loader / executor for automatically evolving
 * NFT artifacts in response to artistic triggers.
 *
 * The Evolution Strategist implements a dynamic plug-in layer (Strategy Pattern).
 * Individual evolution strategies are compiled as shared libraries (*.so)
 * that expose a small, versioned C interface (see below).  At runtime, the
 * muse_observer dynamically loads, caches, and dispatches to these strategies
 * based on events coming in from the event-mesh (Kafka/gRPC/etc.).
 *
 *  Strategy plug-in interface (ABI v1):
 *      int  strategy_get_api_version(void);                // must return 1
 *      const char *strategy_get_name(void);                // human-readable
 *      int  strategy_on_event(const char *artifact_id,     // JSON->JSON
 *                             const char *trigger_payload,
 *                             char      **out_tx_payload); // malloc'd
 *      void strategy_free_payload(char *payload);          // free helper
 *
 *  Return codes: 0 on success, >0 custom success, <0 error.
 *
 *  Copyright (c) 2024 HoloCanvas.
 *  Released under the MIT License.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <stdbool.h>
#include <string.h>
#include <limits.h>
#include <errno.h>
#include <dlfcn.h>
#include <pthread.h>
#include <syslog.h>
#include <unistd.h>

#include "evolution_strategist.h"

/* --------------------------------------------------------------------------
 *  Build-time constants
 * -------------------------------------------------------------------------- */
#define HC_STRATEGIST_ABI_VERSION 1
#define HC_MAX_STRATEGY_NAME      64
#define HC_DEFAULT_PLUGIN_DIR     "/usr/local/lib/hc_strategies"
#define HC_ENV_PLUGIN_DIR         "HC_STRATEGY_PLUGIN_DIR"

/* --------------------------------------------------------------------------
 *  Logging helpers
 * -------------------------------------------------------------------------- */
#define LOG_TAG "evolution_strategist"

static inline void
log_open_if_needed(void)
{
    static bool opened = false;
    if (!opened) {
        openlog(LOG_TAG, LOG_PID | LOG_NDELAY, LOG_USER);
        opened = true;
    }
}

static void
log_fmt(int level, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    log_open_if_needed();
    vsyslog(level, fmt, ap);
    va_end(ap);
}

#define LOG_E(...) log_fmt(LOG_ERR, __VA_ARGS__)
#define LOG_W(...) log_fmt(LOG_WARNING, __VA_ARGS__)
#define LOG_I(...) log_fmt(LOG_INFO, __VA_ARGS__)
#define LOG_D(...) log_fmt(LOG_DEBUG, __VA_ARGS__)

/* --------------------------------------------------------------------------
 *  Strategy structure
 * -------------------------------------------------------------------------- */
typedef int  (*strategy_get_api_version_fn)(void);
typedef const char *(*strategy_get_name_fn)(void);
typedef int  (*strategy_on_event_fn)(const char *, const char *, char **);
typedef void (*strategy_free_payload_fn)(char *);

typedef struct EvoStrategist {
    char                         name[HC_MAX_STRATEGY_NAME];
    void                        *dl_handle;
    strategy_on_event_fn         on_event;
    strategy_free_payload_fn     free_payload;
} EvoStrategist;

/* --------------------------------------------------------------------------
 *  Cache of loaded strategies – simple singly-linked list guarded by RW-lock.
 * -------------------------------------------------------------------------- */
typedef struct StrategyNode {
    EvoStrategist       strat;
    struct StrategyNode *next;
} StrategyNode;

static StrategyNode        *g_strategy_cache = NULL;
static pthread_rwlock_t     g_cache_lock     = PTHREAD_RWLOCK_INITIALIZER;

/* --------------------------------------------------------------------------
 *  Utility helpers
 * -------------------------------------------------------------------------- */
static char *
safe_strdup(const char *s)
{
    if (!s) return NULL;
    size_t len = strlen(s) + 1;
    char *dup = malloc(len);
    if (!dup) {
        LOG_E("Out of memory duplicating string");
        return NULL;
    }
    memcpy(dup, s, len);
    return dup;
}

/* Build the absolute path to a plug-in given its name */
static bool
build_plugin_path(const char *strategy_name, char *out_path, size_t len)
{
    const char *dir = getenv(HC_ENV_PLUGIN_DIR);
    if (!dir || !*dir)
        dir = HC_DEFAULT_PLUGIN_DIR;

    int ret = snprintf(out_path, len, "%s/lib%s.so", dir, strategy_name);
    if (ret < 0 || (size_t)ret >= len) {
        LOG_E("Plugin path buffer too small for strategy `%s`", strategy_name);
        return false;
    }
    return true;
}

/* --------------------------------------------------------------------------
 *  Plug-in loader
 * -------------------------------------------------------------------------- */
static bool
load_strategy(EvoStrategist *out, const char *strategy_name)
{
    char so_path[PATH_MAX];
    if (!build_plugin_path(strategy_name, so_path, sizeof(so_path)))
        return false;

    void *handle = dlopen(so_path, RTLD_LAZY | RTLD_LOCAL);
    if (!handle) {
        LOG_E("dlopen failed for %s: %s", so_path, dlerror());
        return false;
    }

    /* Reset dlerror */
    (void)dlerror();
    strategy_get_api_version_fn api_ver_fn =
        (strategy_get_api_version_fn)dlsym(handle, "strategy_get_api_version");
    const char *sym_err = dlerror();
    if (sym_err) {
        LOG_E("Missing symbol strategy_get_api_version in %s: %s", so_path, sym_err);
        dlclose(handle);
        return false;
    }

    int api_version = api_ver_fn();
    if (api_version != HC_STRATEGIST_ABI_VERSION) {
        LOG_E("Unsupported ABI v%d in %s (expected v%d)",
              api_version, so_path, HC_STRATEGIST_ABI_VERSION);
        dlclose(handle);
        return false;
    }

    strategy_get_name_fn        name_fn   = dlsym(handle, "strategy_get_name");
    strategy_on_event_fn        event_fn  = dlsym(handle, "strategy_on_event");
    strategy_free_payload_fn    free_fn   = dlsym(handle, "strategy_free_payload");
    if (!name_fn || !event_fn || !free_fn) {
        LOG_E("Mandatory symbol missing in %s", so_path);
        dlclose(handle);
        return false;
    }

    const char *plugin_name = name_fn();
    if (!plugin_name || !*plugin_name) {
        LOG_E("Plug-in %s returned invalid name", so_path);
        dlclose(handle);
        return false;
    }

    strncpy(out->name, plugin_name, sizeof(out->name) - 1);
    out->name[sizeof(out->name) - 1] = '\0';
    out->dl_handle   = handle;
    out->on_event    = event_fn;
    out->free_payload= free_fn;

    LOG_I("Loaded strategy '%s' from %s", out->name, so_path);
    return true;
}

/* --------------------------------------------------------------------------
 *  Strategy cache helpers
 * -------------------------------------------------------------------------- */
static EvoStrategist *
cache_lookup_locked(const char *name, StrategyNode **owner_out)
{
    StrategyNode *curr = g_strategy_cache;
    while (curr) {
        if (strcmp(curr->strat.name, name) == 0) {
            if (owner_out) *owner_out = curr;
            return &curr->strat;
        }
        curr = curr->next;
    }
    return NULL;
}

static EvoStrategist *
get_or_load_strategy(const char *strategy_name)
{
    EvoStrategist *strat = NULL;

    /* First attempt read-lock lookup */
    pthread_rwlock_rdlock(&g_cache_lock);
    strat = cache_lookup_locked(strategy_name, NULL);
    pthread_rwlock_unlock(&g_cache_lock);

    if (strat)
        return strat;

    /* Not found – upgrade to write lock and attempt to load */
    pthread_rwlock_wrlock(&g_cache_lock);
    /* Double-check after acquiring write lock (other thread may have loaded) */
    StrategyNode *owner = NULL;
    strat = cache_lookup_locked(strategy_name, &owner);
    if (strat) {
        pthread_rwlock_unlock(&g_cache_lock);
        return strat;
    }

    /* Allocate node */
    owner = calloc(1, sizeof(*owner));
    if (!owner) {
        LOG_E("Out of memory adding strategy node");
        pthread_rwlock_unlock(&g_cache_lock);
        return NULL;
    }

    if (!load_strategy(&owner->strat, strategy_name)) {
        free(owner);
        pthread_rwlock_unlock(&g_cache_lock);
        return NULL;
    }

    /* Insert at list head */
    owner->next      = g_strategy_cache;
    g_strategy_cache = owner;
    strat            = &owner->strat;

    pthread_rwlock_unlock(&g_cache_lock);
    return strat;
}

/* --------------------------------------------------------------------------
 *  Public API
 * -------------------------------------------------------------------------- */
int
evolution_strategist_apply(const char *strategy_name,
                           const char *artifact_id,
                           const char *trigger_payload,
                           char       **out_tx_payload)
{
    if (!strategy_name || !artifact_id || !trigger_payload || !out_tx_payload) {
        LOG_E("Invalid arguments to evolution_strategist_apply");
        return -EINVAL;
    }

    *out_tx_payload = NULL;
    EvoStrategist *strat = get_or_load_strategy(strategy_name);
    if (!strat) {
        LOG_E("Failed to obtain strategy '%s'", strategy_name);
        return -ENOENT;
    }

    int rc = strat->on_event(artifact_id, trigger_payload, out_tx_payload);
    if (rc < 0) {
        LOG_W("Strategy '%s' returned error %d on artifact '%s'",
              strategy_name, rc, artifact_id);
    } else {
        LOG_D("Strategy '%s' executed on artifact '%s' (rc=%d)",
              strategy_name, artifact_id, rc);
    }
    return rc;
}

void
evolution_strategist_free_payload(const char *strategy_name, char *payload)
{
    if (!payload)
        return;

    EvoStrategist *strat = NULL;
    if (strategy_name)
        strat = get_or_load_strategy(strategy_name); /* ensures cache */
    if (strat && strat->free_payload) {
        strat->free_payload(payload);
    } else {
        /* Fallback: default free if strategy unavailable */
        free(payload);
    }
}

/* --------------------------------------------------------------------------
 *  Cleanup at process exit
 * -------------------------------------------------------------------------- */
static void
unload_all_strategies(void)
{
    pthread_rwlock_wrlock(&g_cache_lock);
    StrategyNode *curr = g_strategy_cache;
    while (curr) {
        if (curr->strat.dl_handle) {
            LOG_I("Unloading strategy '%s'", curr->strat.name);
            dlclose(curr->strat.dl_handle);
        }
        StrategyNode *next = curr->next;
        free(curr);
        curr = next;
    }
    g_strategy_cache = NULL;
    pthread_rwlock_unlock(&g_cache_lock);
    pthread_rwlock_destroy(&g_cache_lock);
    closelog();
}

__attribute__((constructor))
static void
evolution_strategist_init(void)
{
    /* Register cleanup */
    atexit(unload_all_strategies);
}

/* --------------------------------------------------------------------------
 *  END
 * -------------------------------------------------------------------------- */
