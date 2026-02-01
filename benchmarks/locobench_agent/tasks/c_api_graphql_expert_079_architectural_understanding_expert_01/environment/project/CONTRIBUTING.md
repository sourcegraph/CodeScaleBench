```c
/* ========================================================================
 * SynestheticCanvas – Contribution Registry
 * ------------------------------------------------------------------------
 * File:        CONTRIBUTING.md               (yes, really — see note below)
 * Language:    C11
 *
 * NOTE:  In the SynestheticCanvas build-system, every public repository
 *        requires a “CONTRIBUTING.md”.  For the API Suite we interpret
 *        “contributing” literally and embed the contribution-registry
 *        implementation here.  The CI pipeline renames the file to
 *        contribution_registry.c during compilation, but keeping the
 *        Markdown extension satisfies GitHub’s UI requirements while
 *        ensuring the code is part of the mandatory documentation set.
 *
 * PURPOSE
 * -------
 * 1.  Provide a thread-safe registry that micro-services use to announce
 *     new creative capabilities (GraphQL schemas, REST routes, etc.).
 * 2.  Offer a minimal, zero-dependency C API so services written in
 *     different languages can still link through a C FFI boundary.
 * 3.  Act as a single source of truth for health checks, versioning, and
 *     schema discovery inside the API gateway.
 *
 * BUILD
 * -----
 *   $ cc -std=c11 -pthread -o contribution_registry CONTRIBUTING.md
 *   # Optional self-test:
 *   $ ./contribution_registry --self-test
 *
 * ===================================================================== */

#define _POSIX_C_SOURCE 200809L   /* For clock_gettime, strdup, etc. */

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* --------------------------------------------------------------------- *
 * Logging facility
 * --------------------------------------------------------------------- */

static bool            g_log_debug_enabled = false;
static pthread_mutex_t g_log_lock          = PTHREAD_MUTEX_INITIALIZER;

#define SC_LOG_LEVEL_INFO  "INFO"
#define SC_LOG_LEVEL_WARN  "WARN"
#define SC_LOG_LEVEL_ERR   "ERROR"
#define SC_LOG_LEVEL_DBG   "DEBUG"

static void
sc_log_internal(const char *lvl,
                const char *func,
                uint32_t    line,
                const char *fmt,
                ...)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);

    char time_buf[32];
    strftime(time_buf,
             sizeof time_buf,
             "%Y-%m-%dT%H:%M:%S",
             localtime(&ts.tv_sec));

    pthread_mutex_lock(&g_log_lock);

    fprintf(stderr,
            "[%s.%03ld] %-5s (%s:%u): ",
            time_buf,
            ts.tv_nsec / 1000000L,
            lvl,
            func,
            line);

    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);

    fputc('\n', stderr);
    fflush(stderr);

    pthread_mutex_unlock(&g_log_lock);
}

#define SC_LOG_INFO(fmt, ...)                                                \
    sc_log_internal(SC_LOG_LEVEL_INFO, __func__, __LINE__, fmt, ##__VA_ARGS__)
#define SC_LOG_WARN(fmt, ...)                                                \
    sc_log_internal(SC_LOG_LEVEL_WARN, __func__, __LINE__, fmt, ##__VA_ARGS__)
#define SC_LOG_ERR(fmt, ...)                                                 \
    sc_log_internal(SC_LOG_LEVEL_ERR, __func__, __LINE__, fmt, ##__VA_ARGS__)
#define SC_LOG_DBG(fmt, ...)                                                 \
    do {                                                                     \
        if (g_log_debug_enabled)                                             \
            sc_log_internal(SC_LOG_LEVEL_DBG,                                \
                            __func__,                                        \
                            __LINE__,                                        \
                            fmt,                                             \
                            ##__VA_ARGS__);                                  \
    } while (0)

/* --------------------------------------------------------------------- *
 * Contribution data-model
 * --------------------------------------------------------------------- */

#define SC_MAX_ID_LEN            64
#define SC_MAX_NAME_LEN         128
#define SC_MAX_SEMVER_LEN        16
#define SC_MAX_PATH_LEN         256
#define SC_MAX_ENDPOINT_LEN     256

typedef struct
{
    char id[SC_MAX_ID_LEN];
    char friendly_name[SC_MAX_NAME_LEN];
    char semantic_version[SC_MAX_SEMVER_LEN];
    char schema_path[SC_MAX_PATH_LEN];
    char health_endpoint[SC_MAX_ENDPOINT_LEN];
} sc_contribution_t;

/* Linked-list node */
typedef struct sc_node
{
    sc_contribution_t      item;
    struct sc_node        *next;
} sc_node_t;

/* --------------------------------------------------------------------- *
 * Registry implementation (singleton)
 * --------------------------------------------------------------------- */

typedef struct
{
    sc_node_t       *head;
    size_t           count;
    pthread_mutex_t  mtx;
    bool             initialized;
} sc_registry_t;

static sc_registry_t g_registry = {
    .head        = NULL,
    .count       = 0,
    .mtx         = PTHREAD_MUTEX_INITIALIZER,
    .initialized = false,
};

/* Utility helpers ----------------------------------------------------- */

static bool
sc_str_empty(const char *s)
{
    return !s || *s == '\0';
}

static bool
sc_semver_valid(const char *s)
{
    /* Very loose semver check:  MAJOR.MINOR.PATCH, all numeric */
    if (sc_str_empty(s))
        return false;

    unsigned major, minor, patch;
    if (sscanf(s, "%u.%u.%u", &major, &minor, &patch) != 3)
        return false;
    return true;
}

static bool
sc_id_exists_unlocked(const char *id)
{
    for (sc_node_t *cur = g_registry.head; cur; cur = cur->next)
        if (strncmp(cur->item.id, id, sizeof cur->item.id) == 0)
            return true;
    return false;
}

/* Public API ---------------------------------------------------------- */

int
sc_registry_init(void)
{
    if (g_registry.initialized)
        return 0;

    const char *dbg = getenv("SC_DEBUG");
    g_log_debug_enabled = dbg && (strcmp(dbg, "1") == 0);

    pthread_mutex_lock(&g_registry.mtx);
    g_registry.head        = NULL;
    g_registry.count       = 0;
    g_registry.initialized = true;
    pthread_mutex_unlock(&g_registry.mtx);

    SC_LOG_INFO("Contribution registry initialized");
    return 0;
}

void
sc_registry_shutdown(void)
{
    pthread_mutex_lock(&g_registry.mtx);

    sc_node_t *cur = g_registry.head;
    while (cur)
    {
        sc_node_t *next = cur->next;
        free(cur);
        cur = next;
    }

    g_registry.head        = NULL;
    g_registry.count       = 0;
    g_registry.initialized = false;

    pthread_mutex_unlock(&g_registry.mtx);
    SC_LOG_INFO("Contribution registry shutdown");
}

int
sc_registry_add(const sc_contribution_t *in)
{
    if (!g_registry.initialized)
    {
        SC_LOG_ERR("Registry not initialized");
        return -ENODEV;
    }

    if (!in)
        return -EINVAL;

    if (sc_str_empty(in->id) || sc_str_empty(in->friendly_name) ||
        sc_str_empty(in->schema_path) || sc_str_empty(in->health_endpoint) ||
        !sc_semver_valid(in->semantic_version))
    {
        SC_LOG_WARN("Invalid contribution payload");
        return -EINVAL;
    }

    pthread_mutex_lock(&g_registry.mtx);

    if (sc_id_exists_unlocked(in->id))
    {
        pthread_mutex_unlock(&g_registry.mtx);
        SC_LOG_WARN("Contribution '%s' already exists", in->id);
        return -EEXIST;
    }

    sc_node_t *node = calloc(1, sizeof *node);
    if (!node)
    {
        pthread_mutex_unlock(&g_registry.mtx);
        return -ENOMEM;
    }
    node->item = *in;
    node->next = g_registry.head;
    g_registry.head = node;
    g_registry.count++;

    pthread_mutex_unlock(&g_registry.mtx);
    SC_LOG_INFO("Registered contribution '%s' (%s)",
                in->id,
                in->semantic_version);
    return 0;
}

int
sc_registry_remove(const char *id)
{
    if (!g_registry.initialized)
        return -ENODEV;
    if (sc_str_empty(id))
        return -EINVAL;

    pthread_mutex_lock(&g_registry.mtx);

    sc_node_t **pp = &g_registry.head;
    while (*pp)
    {
        if (strncmp((*pp)->item.id, id, sizeof(*pp)->item.id) == 0)
        {
            sc_node_t *victim = *pp;
            *pp              = victim->next;
            free(victim);
            g_registry.count--;
            pthread_mutex_unlock(&g_registry.mtx);
            SC_LOG_INFO("Removed contribution '%s'", id);
            return 0;
        }
        pp = &(*pp)->next;
    }

    pthread_mutex_unlock(&g_registry.mtx);
    return -ENOENT;
}

ssize_t
sc_registry_count(void)
{
    if (!g_registry.initialized)
        return -ENODEV;
    pthread_mutex_lock(&g_registry.mtx);
    size_t c = g_registry.count;
    pthread_mutex_unlock(&g_registry.mtx);
    return (ssize_t)c;
}

int
sc_registry_get(const char *id, sc_contribution_t *out)
{
    if (!g_registry.initialized)
        return -ENODEV;
    if (sc_str_empty(id) || !out)
        return -EINVAL;

    pthread_mutex_lock(&g_registry.mtx);
    for (sc_node_t *cur = g_registry.head; cur; cur = cur->next)
    {
        if (strncmp(cur->item.id, id, sizeof cur->item.id) == 0)
        {
            *out = cur->item;
            pthread_mutex_unlock(&g_registry.mtx);
            return 0;
        }
    }
    pthread_mutex_unlock(&g_registry.mtx);
    return -ENOENT;
}

typedef bool (*sc_registry_iter_cb)(const sc_contribution_t *, void *);

/*
 * Iterate over the registry.  The callback receives a snapshot of each
 * contribution (thread-safe).  If the callback returns false, iteration
 * terminates early.
 */
int
sc_registry_foreach(sc_registry_iter_cb cb, void *user_data)
{
    if (!g_registry.initialized || !cb)
        return -EINVAL;

    pthread_mutex_lock(&g_registry.mtx);

    for (sc_node_t *cur = g_registry.head; cur; cur = cur->next)
    {
        sc_contribution_t item = cur->item; /* local snapshot */
        pthread_mutex_unlock(&g_registry.mtx);

        bool keep_going = cb(&item, user_data);

        pthread_mutex_lock(&g_registry.mtx);
        if (!keep_going)
            break;
    }

    pthread_mutex_unlock(&g_registry.mtx);
    return 0;
}

/* --------------------------------------------------------------------- *
 * Self-test (can be disabled by undef-ing)
 * --------------------------------------------------------------------- */
#ifdef SC_CONTRIB_REGISTRY_TEST
static bool
dump_cb(const sc_contribution_t *c, void *unused)
{
    (void)unused;
    printf(" - %s (%s) [%s]\n",
           c->id,
           c->friendly_name,
           c->semantic_version);
    return true;
}

static void
run_self_test(void)
{
    sc_registry_init();

    sc_contribution_t foo = {
        .id               = "palette-service",
        .friendly_name    = "Dynamic Palette Manager",
        .semantic_version = "1.2.0",
        .schema_path      = "/opt/schemas/palette.graphql",
        .health_endpoint  = "http://palette:8080/healthz",
    };

    sc_contribution_t bar = {
        .id               = "texture-synth",
        .friendly_name    = "GPU Texture Synthesizer",
        .semantic_version = "0.9.3",
        .schema_path      = "/opt/schemas/texture.graphql",
        .health_endpoint  = "http://texture:8080/healthz",
    };

    sc_registry_add(&foo);
    sc_registry_add(&bar);
    sc_registry_add(&foo); /* duplicate */

    printf("Registry contains %zd entries\n", sc_registry_count());

    sc_registry_foreach(dump_cb, NULL);

    sc_registry_remove("palette-service");
    sc_registry_remove("does-not-exist");

    printf("After removal: %zd entries\n", sc_registry_count());
    sc_registry_foreach(dump_cb, NULL);

    sc_registry_shutdown();
}
#endif /* SC_CONTRIB_REGISTRY_TEST */

/* --------------------------------------------------------------------- *
 * Main shim (only for manual execution, not required in shared library)
 * --------------------------------------------------------------------- */
#ifndef SC_AS_LIBRARY
int
main(int argc, char **argv)
{
    bool self_test = argc > 1 && strcmp(argv[1], "--self-test") == 0;
#ifdef SC_CONTRIB_REGISTRY_TEST
    if (self_test)
    {
        run_self_test();
        return EXIT_SUCCESS;
    }
#else
    (void)self_test;
#endif
    fprintf(stderr,
            "SynestheticCanvas Contribution Registry\n"
            "  (compiled with %s)\n"
            "\n"
            "Usage:\n"
            "  %s --self-test      Run built-in test harness\n",
            __VERSION__,
            argv[0]);
    return EXIT_FAILURE;
}
#endif /* SC_AS_LIBRARY */
```