/**
 * SynestheticCanvas - Palette Service
 * File: palette_service.c
 *
 * This source file implements the Palette Service: a small, embeddable,
 * thread-safe micro-component that handles CRUD operations for color palettes.
 *
 * Responsibilities
 *  – Validation of palette payloads (name, hex codes, etc.).
 *  – In-memory repository via uthash (can be swapped for real DB via adapters).
 *  – Basic monitoring counters (op counts, error counts, latency buckets*).
 *  – Simple pagination for list queries.
 *  – RFC-4122 UUID generation for primary keys.
 *  – Syslog-style logging with compile-time log-level control.
 *
 * NOTE: All public functions are prefixed with palette_service_*
 *
 * ---------------------------------------------------------------------------
 * Build:
 *   cc -std=c11 -DUSE_SYSLOG -lpthread -luuid -o palette_service palette_service.c
 * ---------------------------------------------------------------------------
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stdarg.h>
#include <pthread.h>
#include <uuid/uuid.h>
#include <time.h>
#include <sys/time.h>

#include "uthash.h" /* https://troydhanson.github.io/uthash/ */

/* ────────────────────────────────────────────────────────────────────────────
 * Compile-time configuration
 * ────────────────────────────────────────────────────────────────────────── */
#ifndef PALETTE_SERVICE_MAX_COLORS
#define PALETTE_SERVICE_MAX_COLORS 32
#endif

#ifndef PALETTE_SERVICE_PAGE_SIZE
#define PALETTE_SERVICE_PAGE_SIZE 50
#endif

/* Log levels */
#define LOG_TRACE  0
#define LOG_DEBUG  1
#define LOG_INFO   2
#define LOG_WARN   3
#define LOG_ERROR  4
#define LOG_FATAL  5

#ifndef PALETTE_LOG_LEVEL
#define PALETTE_LOG_LEVEL LOG_INFO
#endif

/* ────────────────────────────────────────────────────────────────────────────
 * Logging helpers
 * ────────────────────────────────────────────────────────────────────────── */
static const char *LOG_LEVEL_NAMES[] = {
    "TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"
};

static void log_internal(int level, const char *fmt, ...)
{
#if PALETTE_LOG_LEVEL <= LOG_FATAL
    if (level < PALETTE_LOG_LEVEL) return;

    va_list args;
    va_start(args, fmt);

#ifdef USE_SYSLOG
    /* Map to syslog priorities if desired; omitted for brevity */
    vfprintf(stderr, fmt, args);
    fprintf(stderr, "\n");
#else
    struct timeval tv;
    gettimeofday(&tv, NULL);
    struct tm tm;
    localtime_r(&tv.tv_sec, &tm);

    char ts[64];
    strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%S", &tm);

    fprintf(stderr, "%s.%03ld [%s] ", ts, tv.tv_usec / 1000, LOG_LEVEL_NAMES[level]);
    vfprintf(stderr, fmt, args);
    fprintf(stderr, "\n");
#endif

    va_end(args);
#endif
}

#define LOGT(fmt, ...) log_internal(LOG_TRACE, fmt, ##__VA_ARGS__)
#define LOGD(fmt, ...) log_internal(LOG_DEBUG, fmt, ##__VA_ARGS__)
#define LOGI(fmt, ...) log_internal(LOG_INFO,  fmt, ##__VA_ARGS__)
#define LOGW(fmt, ...) log_internal(LOG_WARN,  fmt, ##__VA_ARGS__)
#define LOGE(fmt, ...) log_internal(LOG_ERROR, fmt, ##__VA_ARGS__)
#define LOGF(fmt, ...) log_internal(LOG_FATAL, fmt, ##__VA_ARGS__)

/* ────────────────────────────────────────────────────────────────────────────
 * Data types
 * ────────────────────────────────────────────────────────────────────────── */

typedef struct
{
    char  name[32]; /* e.g., "accent" */
    char  hex[8];   /* "#RRGGBB" or "#RGB" – validated */
} palette_color_t;

typedef struct
{
    char  id[37];               /* RFC 4122 UUID string */
    char  name[64];             /* Public-facing name   */
    unsigned int version;       /* Incremented on update */
    size_t color_count;
    palette_color_t colors[PALETTE_SERVICE_MAX_COLORS];

    UT_hash_handle hh;          /* uthash handle (key=id) */
} palette_record_t;

/* Pagination request and response */
typedef struct
{
    size_t page_size;       /* defaults to PALETTE_SERVICE_PAGE_SIZE */
    size_t page_number;     /* 0-based page index                    */
} palette_page_request_t;

typedef struct
{
    palette_record_t **items; /* dynamic array of ptrs to palette_record_t */
    size_t item_count;
    size_t total_items;
    size_t page_number;
    size_t total_pages;
} palette_page_t;

/* Monitoring counters (extremely coarse) */
typedef struct
{
    unsigned long create_ok;
    unsigned long create_err;
    unsigned long read_ok;
    unsigned long read_err;
    unsigned long update_ok;
    unsigned long update_err;
    unsigned long delete_ok;
    unsigned long delete_err;
    unsigned long list_ok;
    unsigned long list_err;
} palette_metrics_t;

/* ────────────────────────────────────────────────────────────────────────────
 * Module state
 * ────────────────────────────────────────────────────────────────────────── */
static struct
{
    palette_record_t *records;      /* uthash head */
    pthread_rwlock_t  lock;
    bool              initialized;
    palette_metrics_t metrics;
} g_ctx = {0};

/* ────────────────────────────────────────────────────────────────────────────
 * Forward declarations
 * ────────────────────────────────────────────────────────────────────────── */
static bool validate_hex(const char *hex);
static bool validate_palette(const palette_record_t *p, char *err, size_t err_len);
static void free_page(palette_page_t *page);

/* ────────────────────────────────────────────────────────────────────────────
 * Public API
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * palette_service_init
 * Initializes internal structures; should be called once on startup.
 */
bool palette_service_init(void)
{
    if (g_ctx.initialized) {
        LOGW("Palette Service already initialized");
        return true;
    }

    if (pthread_rwlock_init(&g_ctx.lock, NULL) != 0) {
        LOGE("Failed to create rwlock");
        return false;
    }

    g_ctx.records     = NULL;
    g_ctx.initialized = true;
    memset(&g_ctx.metrics, 0, sizeof(g_ctx.metrics));

    LOGI("Palette Service initialized");
    return true;
}

/**
 * palette_service_shutdown
 * Frees all allocated resources. Must be idempotent.
 */
void palette_service_shutdown(void)
{
    if (!g_ctx.initialized) return;

    pthread_rwlock_wrlock(&g_ctx.lock);
    palette_record_t *cur, *tmp;
    HASH_ITER(hh, g_ctx.records, cur, tmp)
    {
        HASH_DEL(g_ctx.records, cur);
        free(cur);
    }
    pthread_rwlock_unlock(&g_ctx.lock);

    pthread_rwlock_destroy(&g_ctx.lock);
    g_ctx.initialized = false;

    LOGI("Palette Service shut down");
}

/**
 * palette_service_create_palette
 * Allocates and stores a new palette. Returns copy of stored record on success.
 */
bool palette_service_create_palette(const char *name,
                                    const palette_color_t *colors,
                                    size_t color_count,
                                    palette_record_t *out_record)
{
    if (!g_ctx.initialized) { LOGE("Service not initialized"); return false; }
    if (!name || !colors || color_count == 0 || color_count > PALETTE_SERVICE_MAX_COLORS) {
        g_ctx.metrics.create_err++;
        LOGW("Create request failed validation: invalid arguments");
        return false;
    }

    palette_record_t *rec = calloc(1, sizeof(*rec));
    if (!rec) {
        g_ctx.metrics.create_err++;
        LOGE("Memory allocation failed");
        return false;
    }

    uuid_t uuid;
    uuid_generate(uuid);
    uuid_unparse_lower(uuid, rec->id);

    strncpy(rec->name, name, sizeof(rec->name) - 1);
    rec->color_count = color_count;
    rec->version     = 1;

    for (size_t i = 0; i < color_count; ++i)
        memcpy(&rec->colors[i], &colors[i], sizeof(palette_color_t));

    char err[256];
    if (!validate_palette(rec, err, sizeof(err))) {
        g_ctx.metrics.create_err++;
        free(rec);
        LOGW("Palette validation failed: %s", err);
        return false;
    }

    /* Store */
    pthread_rwlock_wrlock(&g_ctx.lock);
    HASH_ADD_STR(g_ctx.records, id, rec);
    pthread_rwlock_unlock(&g_ctx.lock);

    if (out_record) memcpy(out_record, rec, sizeof(*out_record));

    g_ctx.metrics.create_ok++;
    LOGI("Created palette id=%s (%zu colors)", rec->id, rec->color_count);
    return true;
}

/**
 * palette_service_get_palette_by_id
 * Retrieves a palette by its UUID. Returns false if not found.
 */
bool palette_service_get_palette_by_id(const char *id, palette_record_t *out_record)
{
    if (!g_ctx.initialized) { LOGE("Service not initialized"); return false; }
    if (!id || !out_record) { g_ctx.metrics.read_err++; return false; }

    pthread_rwlock_rdlock(&g_ctx.lock);
    palette_record_t *rec = NULL;
    HASH_FIND_STR(g_ctx.records, id, rec);
    pthread_rwlock_unlock(&g_ctx.lock);

    if (!rec) {
        g_ctx.metrics.read_err++;
        LOGD("Palette id=%s not found", id);
        return false;
    }

    memcpy(out_record, rec, sizeof(*out_record));
    g_ctx.metrics.read_ok++;
    return true;
}

/**
 * palette_service_list_palettes
 * Returns a paginated list of palettes. Caller must free page->items.
 */
bool palette_service_list_palettes(palette_page_request_t req, palette_page_t *out_page)
{
    if (!g_ctx.initialized) { LOGE("Service not initialized"); return false; }
    if (!out_page) { g_ctx.metrics.list_err++; return false; }

    if (req.page_size == 0 || req.page_size > PALETTE_SERVICE_PAGE_SIZE)
        req.page_size = PALETTE_SERVICE_PAGE_SIZE;

    /* Step 1: snapshot count */
    pthread_rwlock_rdlock(&g_ctx.lock);
    size_t total_items = HASH_COUNT(g_ctx.records);
    pthread_rwlock_unlock(&g_ctx.lock);

    size_t total_pages = (total_items + req.page_size - 1) / req.page_size;
    if (req.page_number >= total_pages && total_pages > 0)
        req.page_number = total_pages - 1;

    /* Step 2: allocate array */
    palette_record_t **arr = calloc(req.page_size, sizeof(palette_record_t *));
    if (!arr) {
        g_ctx.metrics.list_err++;
        LOGE("Memory allocation failed (list)");
        return false;
    }

    /* Step 3: iterate */
    pthread_rwlock_rdlock(&g_ctx.lock);
    palette_record_t *rec, *tmp;
    size_t idx = 0, skipped = 0, start = req.page_number * req.page_size;

    HASH_ITER(hh, g_ctx.records, rec, tmp)
    {
        if (skipped < start) { skipped++; continue; }
        if (idx >= req.page_size) break;
        arr[idx++] = rec;
    }
    pthread_rwlock_unlock(&g_ctx.lock);

    /* Build page */
    out_page->items       = arr;
    out_page->item_count  = idx;
    out_page->total_items = total_items;
    out_page->page_number = req.page_number;
    out_page->total_pages = total_pages;

    g_ctx.metrics.list_ok++;
    return true;
}

/**
 * palette_service_update_palette
 * Replaces palette data atomically; increments version.
 */
bool palette_service_update_palette(const char *id,
                                    const char *name,
                                    const palette_color_t *colors,
                                    size_t color_count,
                                    palette_record_t *out_record)
{
    if (!g_ctx.initialized) { LOGE("Service not initialized"); return false; }
    if (!id || !name || !colors || color_count == 0 ||
        color_count > PALETTE_SERVICE_MAX_COLORS) {
        g_ctx.metrics.update_err++;
        return false;
    }

    pthread_rwlock_wrlock(&g_ctx.lock);
    palette_record_t *rec = NULL;
    HASH_FIND_STR(g_ctx.records, id, rec);
    if (!rec) {
        pthread_rwlock_unlock(&g_ctx.lock);
        g_ctx.metrics.update_err++;
        LOGD("Palette id=%s not found for update", id);
        return false;
    }

    strncpy(rec->name, name, sizeof(rec->name) - 1);
    rec->color_count = color_count;
    rec->version++;

    for (size_t i = 0; i < color_count; ++i)
        memcpy(&rec->colors[i], &colors[i], sizeof(palette_color_t));

    char err[256];
    if (!validate_palette(rec, err, sizeof(err))) {
        pthread_rwlock_unlock(&g_ctx.lock);
        g_ctx.metrics.update_err++;
        LOGW("Palette update validation failed: %s", err);
        return false;
    }

    pthread_rwlock_unlock(&g_ctx.lock);

    if (out_record) memcpy(out_record, rec, sizeof(*out_record));

    g_ctx.metrics.update_ok++;
    LOGI("Updated palette id=%s version=%u", rec->id, rec->version);
    return true;
}

/**
 * palette_service_delete_palette
 * Removes palette from storage.
 */
bool palette_service_delete_palette(const char *id)
{
    if (!g_ctx.initialized) { LOGE("Service not initialized"); return false; }
    if (!id) { g_ctx.metrics.delete_err++; return false; }

    pthread_rwlock_wrlock(&g_ctx.lock);
    palette_record_t *rec = NULL;
    HASH_FIND_STR(g_ctx.records, id, rec);
    if (rec) {
        HASH_DEL(g_ctx.records, rec);
        free(rec);
        pthread_rwlock_unlock(&g_ctx.lock);

        g_ctx.metrics.delete_ok++;
        LOGI("Deleted palette id=%s", id);
        return true;
    }
    pthread_rwlock_unlock(&g_ctx.lock);

    g_ctx.metrics.delete_err++;
    LOGD("Palette id=%s not found for deletion", id);
    return false;
}

/**
 * palette_service_dump_metrics
 * Caller provides preallocated struct. Thread-safe read.
 */
void palette_service_dump_metrics(palette_metrics_t *out_metrics)
{
    if (!out_metrics) return;
    pthread_rwlock_rdlock(&g_ctx.lock);
    memcpy(out_metrics, &g_ctx.metrics, sizeof(*out_metrics));
    pthread_rwlock_unlock(&g_ctx.lock);
}

/* ────────────────────────────────────────────────────────────────────────────
 * Validation helpers (static)
 * ────────────────────────────────────────────────────────────────────────── */

static bool validate_hex(const char *hex)
{
    if (!hex) return false;
    size_t len = strlen(hex);
    if (!(len == 4 || len == 7)) return false;  /* "#RGB" or "#RRGGBB" */

    if (hex[0] != '#') return false;

    for (size_t i = 1; i < len; ++i) {
        char c = hex[i];
        if (!((c >= '0' && c <= '9') ||
              (c >= 'A' && c <= 'F') ||
              (c >= 'a' && c <= 'f')))
            return false;
    }
    return true;
}

static bool validate_palette(const palette_record_t *p, char *err, size_t err_len)
{
    if (!p) { snprintf(err, err_len, "palette pointer null"); return false; }
    if (strlen(p->name) == 0) {
        snprintf(err, err_len, "empty name");
        return false;
    }
    if (p->color_count == 0 || p->color_count > PALETTE_SERVICE_MAX_COLORS) {
        snprintf(err, err_len, "invalid color count");
        return false;
    }
    for (size_t i = 0; i < p->color_count; ++i) {
        const palette_color_t *c = &p->colors[i];
        if (strlen(c->name) == 0) {
            snprintf(err, err_len, "color %zu has empty name", i);
            return false;
        }
        if (!validate_hex(c->hex)) {
            snprintf(err, err_len, "color %zu has invalid hex '%s'", i, c->hex);
            return false;
        }
    }
    return true;
}

/* ────────────────────────────────────────────────────────────────────────────
 * Utility
 * ────────────────────────────────────────────────────────────────────────── */

static void free_page(palette_page_t *page)
{
    if (!page) return;
    free(page->items);
    memset(page, 0, sizeof(*page));
}

/* --------------------------------------------------------------------------
 * Example usage (unit test stub) – compile with -DPALETTE_SERVICE_TEST
 * ----------------------------------------------------------------------- */
#ifdef PALETTE_SERVICE_TEST
int main(void)
{
    if (!palette_service_init()) return EXIT_FAILURE;

    palette_color_t colors[] = {
        {"background", "#112233"},
        {"accent",     "#FFAA00"},
        {"highlight",  "#00FF00"}
    };

    palette_record_t created;
    if (!palette_service_create_palette("Sunset", colors, 3, &created)) {
        LOGE("Create failed");
        return EXIT_FAILURE;
    }

    palette_record_t fetched;
    if (palette_service_get_palette_by_id(created.id, &fetched))
        LOGI("Fetched palette name=%s color_count=%zu", fetched.name, fetched.color_count);

    palette_page_request_t req = { .page_size = 10, .page_number = 0 };
    palette_page_t page;
    if (palette_service_list_palettes(req, &page)) {
        LOGI("Listing palettes: page %zu/%zu, items=%zu",
             page.page_number + 1, page.total_pages, page.item_count);
        free_page(&page);
    }

    palette_service_shutdown();
    return EXIT_SUCCESS;
}
#endif /* PALETTE_SERVICE_TEST */
