```c
/*
 * SynestheticCanvas – Texture Service
 * -----------------------------------
 * This micro-service is responsible for dynamic texture synthesis, on-disk
 * persistence and low-latency retrieval.  A minimal REST façade is exposed
 * through libmicrohttpd so that the API-gateway can proxy requests.  The
 * code purposefully keeps networking, repository-pattern and generation
 * logic in the same translation unit for simplicity, but real deployments
 * would split these concerns into dedicated modules / libraries.
 *
 * Build (example):
 *   cc -std=c11 -Wall -Wextra -O2 texture_service.c -o texture_service \
 *      -lmicrohttpd -lpthread -luuid -lm
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <inttypes.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include <pthread.h>
#include <uuid/uuid.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <math.h>

#include <microhttpd.h>     /* libmicrohttpd – lightweight HTTP server */

#define ARRAY_LEN(arr) (sizeof(arr) / sizeof((arr)[0]))
#define SERVICE_PORT (getenv("TEXTURE_SERVICE_PORT") ? atoi(getenv("TEXTURE_SERVICE_PORT")) : 8081)
#define STORAGE_DIR "./textures"
#define MAX_CACHE_ITEMS 100
#define MAX_TEXTURE_SIDE 4096   /* guardrail */
#define DEFAULT_NOISE_FREQ 0.05f
#define HTTP_BUFFER_SZ 8192

/* ------------------------------------------------------------------------
 * Logging helpers
 * ----------------------------------------------------------------------*/
#define LOG_TS()                               \
    do {                                       \
        time_t _now = time(NULL);              \
        struct tm _tm;                         \
        localtime_r(&_now, &_tm);              \
        char _buf[32];                         \
        strftime(_buf, sizeof _buf, "%F %T", &_tm); \
        fprintf(stderr, "[%s] ", _buf);        \
    } while (0)

#define LOG_INFO(fmt, ...) \
    do { LOG_TS(); fprintf(stderr, "INFO: " fmt "\n", ##__VA_ARGS__); } while (0)

#define LOG_ERROR(fmt, ...) \
    do { LOG_TS(); fprintf(stderr, "ERROR: " fmt " (errno=%d: %s)\n", \
             ##__VA_ARGS__, errno, strerror(errno)); } while (0)

/* ------------------------------------------------------------------------
 * Domain – Texture metadata & binary representation
 * ----------------------------------------------------------------------*/
typedef struct texture_meta {
    char      id[37];   /* UUID string, NUL-terminated */
    uint32_t  width;
    uint32_t  height;
    char      file_path[PATH_MAX];
    time_t    created_at;  /* epoch */
} texture_meta_t;

/* Simple in-memory LRU cache entry */
typedef struct cache_entry {
    texture_meta_t meta;
    struct cache_entry *prev, *next;
    uint8_t *pixels;          /* raw RGBA, width * height * 4 */
    size_t   size;            /* bytes */
} cache_entry_t;

/* ------------------------------------------------------------------------
 * Repository (thread-safe)
 * ----------------------------------------------------------------------*/
typedef struct texture_repository {
    pthread_mutex_t lock;
} texture_repository_t;

static texture_repository_t g_repo = {
    .lock = PTHREAD_MUTEX_INITIALIZER
};

/* Ensure storage directory exists */
static void
repo_init(void)
{
    struct stat st;
    if (stat(STORAGE_DIR, &st) != 0) {
        if (mkdir(STORAGE_DIR, 0755) != 0) {
            LOG_ERROR("mkdir('%s') failed", STORAGE_DIR);
            exit(EXIT_FAILURE);
        }
    }
}

/* Persist raw RGBA pixels to disk as a simple binary dump (.raw) */
static bool
repo_save_raw(const texture_meta_t *meta, const uint8_t *pixels)
{
    FILE *fp = fopen(meta->file_path, "wb");
    if (!fp) {
        LOG_ERROR("fopen");
        return false;
    }
    size_t expected = (size_t)meta->width * meta->height * 4;
    if (fwrite(pixels, 1, expected, fp) != expected) {
        LOG_ERROR("fwrite");
        fclose(fp);
        return false;
    }
    fclose(fp);
    return true;
}

/* Stream file to HTTP client (using libmicrohttpd's callback mechanism) */
struct file_stream_ctx {
    FILE *fp;
    char  buf[HTTP_BUFFER_SZ];
};

static ssize_t
stream_file_cb(void *cls, uint64_t pos, char *buf, size_t max)
{
    struct file_stream_ctx *ctx = cls;
    (void)pos; /* Not using pos because we read sequentially */

    if (feof(ctx->fp))
        return MHD_CONTENT_READER_END_OF_STREAM;

    size_t n = fread(buf, 1, max < sizeof(ctx->buf) ? max : sizeof(ctx->buf), ctx->fp);
    if (n == 0)
        return MHD_CONTENT_READER_END_OF_STREAM;

    return (ssize_t)n;
}

/* ------------------------------------------------------------------------
 * Texture synthesis (simple value noise as demonstration)
 * ----------------------------------------------------------------------*/
static inline float
rand_unit(void)
{
    return (float)rand() / (float)RAND_MAX;
}

/* Basic gradient noise (returns value in [0;1]) */
static void
generate_noise_texture(uint32_t width, uint32_t height,
                       float frequency, uint8_t *out_pixels)
{
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            float nx = x * frequency;
            float ny = y * frequency;
            /* pseudo-random value per pixel */
            float v = fabsf(sinf(nx * 12.9898f + ny * 78.233f) * 43758.5453f);
            v = v - floorf(v); /* fract */

            uint8_t c = (uint8_t)(v * 255.0f);
            size_t idx = ((size_t)y * width + x) * 4;
            out_pixels[idx + 0] = c;  /* R */
            out_pixels[idx + 1] = c;  /* G */
            out_pixels[idx + 2] = c;  /* B */
            out_pixels[idx + 3] = 255;/* A opaque */
        }
    }
}

/* ------------------------------------------------------------------------
 * LRU Cache
 * ----------------------------------------------------------------------*/
typedef struct texture_cache {
    pthread_mutex_t lock;
    cache_entry_t  *head; /* MRU */
    cache_entry_t  *tail; /* LRU */
    size_t          items;
    size_t          bytes;
} texture_cache_t;

static texture_cache_t g_cache = {
    .lock  = PTHREAD_MUTEX_INITIALIZER,
    .head  = NULL,
    .tail  = NULL,
    .items = 0,
    .bytes = 0
};

static void
cache_move_to_front(cache_entry_t *entry)
{
    if (g_cache.head == entry)
        return;

    /* detach */
    if (entry->prev)
        entry->prev->next = entry->next;
    if (entry->next)
        entry->next->prev = entry->prev;
    if (g_cache.tail == entry)
        g_cache.tail = entry->prev;

    /* insert at front */
    entry->prev = NULL;
    entry->next = g_cache.head;
    if (g_cache.head)
        g_cache.head->prev = entry;
    g_cache.head = entry;
    if (!g_cache.tail)
        g_cache.tail = entry;
}

static cache_entry_t *
cache_find(const char *id)
{
    cache_entry_t *it = g_cache.head;
    while (it) {
        if (strcmp(it->meta.id, id) == 0)
            return it;
        it = it->next;
    }
    return NULL;
}

static void
cache_evict_if_needed(void)
{
    while (g_cache.items > MAX_CACHE_ITEMS) {
        cache_entry_t *victim = g_cache.tail;
        if (!victim)
            return;
        /* detach */
        if (victim->prev)
            victim->prev->next = NULL;
        g_cache.tail = victim->prev;
        if (g_cache.head == victim)
            g_cache.head = NULL;

        g_cache.items--;
        g_cache.bytes -= victim->size;
        LOG_INFO("Evicted texture %s from cache (now %" PRIu64 " KiB)",
                 victim->meta.id, (uint64_t)(g_cache.bytes / 1024));

        free(victim->pixels);
        free(victim);
    }
}

static void
cache_insert(cache_entry_t *entry)
{
    entry->prev = NULL;
    entry->next = g_cache.head;
    if (g_cache.head)
        g_cache.head->prev = entry;
    g_cache.head = entry;
    if (!g_cache.tail)
        g_cache.tail = entry;

    g_cache.items++;
    g_cache.bytes += entry->size;
    cache_evict_if_needed();
}

/* ------------------------------------------------------------------------
 * REST Controller helpers
 * ----------------------------------------------------------------------*/
typedef struct rest_ctx {
    struct MHD_Connection *conn;
    const char            *url;
    const char            *method;
} rest_ctx_t;

static int
resp_json(struct MHD_Connection *conn, unsigned status,
          const char *json_str)
{
    struct MHD_Response *resp = MHD_create_response_from_buffer(
        strlen(json_str), (void *)json_str, MHD_RESPMEM_MUST_COPY);
    if (!resp)
        return MHD_NO;

    MHD_add_response_header(resp, "Content-Type", "application/json");
    int ret = MHD_queue_response(conn, status, resp);
    MHD_destroy_response(resp);
    return ret;
}

static int
resp_plain(struct MHD_Connection *conn, unsigned status,
           const char *text)
{
    struct MHD_Response *resp = MHD_create_response_from_buffer(
        strlen(text), (void *)text, MHD_RESPMEM_MUST_COPY);
    if (!resp)
        return MHD_NO;

    MHD_add_response_header(resp, "Content-Type", "text/plain");
    int ret = MHD_queue_response(conn, status, resp);
    MHD_destroy_response(resp);
    return ret;
}

/* ------------------------------------------------------------------------
 * Endpoint: POST /textures
 * Body (form-encoded):
 *   width=<int>&height=<int>&freq=<float>
 * Returns JSON: { "id": "...", "width": n, "height": n }
 * ----------------------------------------------------------------------*/
static int
handle_post_textures(rest_ctx_t *ctx)
{
    uint32_t width  = 0, height = 0;
    float freq = DEFAULT_NOISE_FREQ;

    const char *width_str  = MHD_lookup_connection_value(ctx->conn, MHD_POST_FIELD_KIND, "width");
    const char *height_str = MHD_lookup_connection_value(ctx->conn, MHD_POST_FIELD_KIND, "height");
    const char *freq_str   = MHD_lookup_connection_value(ctx->conn, MHD_POST_FIELD_KIND, "freq");

    if (width_str)  width  = (uint32_t)strtoul(width_str, NULL, 10);
    if (height_str) height = (uint32_t)strtoul(height_str, NULL, 10);
    if (freq_str)   freq   = strtof(freq_str, NULL);

    if (width == 0 || height == 0 || width > MAX_TEXTURE_SIDE || height > MAX_TEXTURE_SIDE) {
        return resp_plain(ctx->conn, MHD_HTTP_BAD_REQUEST, "Invalid dimensions");
    }

    size_t bytes = (size_t)width * height * 4;
    uint8_t *pixels = malloc(bytes);
    if (!pixels)
        return resp_plain(ctx->conn, MHD_HTTP_INTERNAL_SERVER_ERROR, "OOM");

    generate_noise_texture(width, height, freq, pixels);

    texture_meta_t meta = {0};
    uuid_t uu;
    uuid_generate(uu);
    uuid_unparse_lower(uu, meta.id);
    meta.width  = width;
    meta.height = height;
    meta.created_at = time(NULL);
    snprintf(meta.file_path, sizeof meta.file_path,
             STORAGE_DIR "/%s.raw", meta.id);

    pthread_mutex_lock(&g_repo.lock);
    bool ok = repo_save_raw(&meta, pixels);
    pthread_mutex_unlock(&g_repo.lock);
    if (!ok) {
        free(pixels);
        return resp_plain(ctx->conn, MHD_HTTP_INTERNAL_SERVER_ERROR, "Save failed");
    }

    /* Add to cache */
    pthread_mutex_lock(&g_cache.lock);
    cache_entry_t *item = malloc(sizeof *item);
    if (!item) {
        pthread_mutex_unlock(&g_cache.lock);
        free(pixels);
        return resp_plain(ctx->conn, MHD_HTTP_INTERNAL_SERVER_ERROR, "OOM");
    }
    item->meta  = meta;
    item->pixels = pixels;
    item->size   = bytes;
    cache_insert(item);
    pthread_mutex_unlock(&g_cache.lock);

    char json[256];
    snprintf(json, sizeof json,
             "{\"id\":\"%s\",\"width\":%u,\"height\":%u}",
             meta.id, meta.width, meta.height);
    LOG_INFO("Generated texture %s (%ux%u)", meta.id, width, height);

    return resp_json(ctx->conn, MHD_HTTP_CREATED, json);
}

/* ------------------------------------------------------------------------
 * Endpoint: GET /textures/<uuid>/metadata
 * ----------------------------------------------------------------------*/
static int
handle_get_texture_metadata(rest_ctx_t *ctx, const char *uuid_str)
{
    pthread_mutex_lock(&g_cache.lock);
    cache_entry_t *hit = cache_find(uuid_str);
    if (hit)
        cache_move_to_front(hit);
    pthread_mutex_unlock(&g_cache.lock);

    texture_meta_t meta;
    bool found = false;

    if (hit) {
        meta   = hit->meta;
        found = true;
    } else {
        /* Fall back to disk */
        char file_path[PATH_MAX];
        snprintf(file_path, sizeof file_path, STORAGE_DIR "/%s.raw", uuid_str);
        struct stat st;
        if (stat(file_path, &st) == 0) {
            /* Dimensions are not stored on disk header. In real code you would 
             * store metadata in DB; we'll derive from file size here. */
            size_t bytes = (size_t)st.st_size;
            uint32_t side = (uint32_t)sqrt((double)(bytes / 4));
            if (side * side * 4 == bytes) {
                strncpy(meta.id, uuid_str, sizeof meta.id);
                meta.width  = side;
                meta.height = side;
                strncpy(meta.file_path, file_path, sizeof meta.file_path);
                meta.created_at = st.st_mtime;
                found = true;
            }
        }
    }

    if (!found)
        return resp_plain(ctx->conn, MHD_HTTP_NOT_FOUND, "Not found");

    char created[32];
    struct tm tm;
    gmtime_r(&meta.created_at, &tm);
    strftime(created, sizeof created, "%FT%TZ", &tm);

    char json[256];
    snprintf(json, sizeof json,
             "{\"id\":\"%s\",\"width\":%u,\"height\":%u,\"created\":\"%s\"}",
             meta.id, meta.width, meta.height, created);

    return resp_json(ctx->conn, MHD_HTTP_OK, json);
}

/* ------------------------------------------------------------------------
 * Endpoint: GET /textures/<uuid>/raw
 * Streams the binary .raw pixel dump
 * ----------------------------------------------------------------------*/
static int
handle_get_texture_raw(rest_ctx_t *ctx, const char *uuid_str)
{
    /* Check cache first */
    pthread_mutex_lock(&g_cache.lock);
    cache_entry_t *hit = cache_find(uuid_str);
    if (hit) {
        cache_move_to_front(hit);
        size_t size = hit->size;
        uint8_t *copy = malloc(size);
        if (!copy) {
            pthread_mutex_unlock(&g_cache.lock);
            return resp_plain(ctx->conn, MHD_HTTP_INTERNAL_SERVER_ERROR, "OOM");
        }
        memcpy(copy, hit->pixels, size);
        pthread_mutex_unlock(&g_cache.lock);

        struct MHD_Response *resp = MHD_create_response_from_buffer(
            size, copy, MHD_RESPMEM_MUST_FREE);
        if (!resp) {
            free(copy);
            return MHD_NO;
        }
        MHD_add_response_header(resp, "Content-Type", "application/octet-stream");
        int ret = MHD_queue_response(ctx->conn, MHD_HTTP_OK, resp);
        MHD_destroy_response(resp);
        return ret;
    }
    pthread_mutex_unlock(&g_cache.lock);

    /* Stream from disk instead */
    char file_path[PATH_MAX];
    snprintf(file_path, sizeof file_path, STORAGE_DIR "/%s.raw", uuid_str);
    FILE *fp = fopen(file_path, "rb");
    if (!fp)
        return resp_plain(ctx->conn, MHD_HTTP_NOT_FOUND, "Not found");

    struct stat st;
    if (stat(file_path, &st) != 0) {
        fclose(fp);
        return resp_plain(ctx->conn, MHD_HTTP_INTERNAL_SERVER_ERROR, "stat failed");
    }

    struct file_stream_ctx *fsctx = malloc(sizeof *fsctx);
    if (!fsctx) {
        fclose(fp);
        return resp_plain(ctx->conn, MHD_HTTP_INTERNAL_SERVER_ERROR, "OOM");
    }
    fsctx->fp = fp;

    struct MHD_Response *resp = MHD_create_response_from_callback(
        (uint64_t)st.st_size, HTTP_BUFFER_SZ,
        stream_file_cb, fsctx,
        (MHD_ContentReaderFreeCallback)fclose);
    if (!resp) {
        fclose(fp);
        free(fsctx);
        return MHD_NO;
    }
    MHD_add_response_header(resp, "Content-Type", "application/octet-stream");
    int ret = MHD_queue_response(ctx->conn, MHD_HTTP_OK, resp);
    MHD_destroy_response(resp);
    return ret;
}

/* ------------------------------------------------------------------------
 * Dispatcher
 * ----------------------------------------------------------------------*/
static int
dispatch(void *cls,
         struct MHD_Connection *conn,
         const char *url,
         const char *method,
         const char *version,
         const char *upload_data,
         size_t      *upload_data_size,
         void       **con_cls)
{
    (void)cls; (void)version; (void)upload_data; (void)upload_data_size;

    rest_ctx_t ctx = {.conn = conn, .url = url, .method = method};

    /* Routing */
    if (strcmp(method, MHD_HTTP_METHOD_POST) == 0 &&
        strcmp(url, "/textures") == 0) {
        return handle_post_textures(&ctx);
    }

    if (strncmp(url, "/textures/", 10) == 0) {
        const char *uuid_part = url + 10;
        const char *slash = strchr(uuid_part, '/');
        if (!slash)
            return resp_plain(conn, MHD_HTTP_NOT_FOUND, "Bad URL");

        char uuid[37] = {0};
        size_t len = slash - uuid_part;
        if (len >= sizeof uuid)
            return resp_plain(conn, MHD_HTTP_BAD_REQUEST, "UUID toolong");
        memcpy(uuid, uuid_part, len);

        if (strcmp(slash, "/metadata") == 0 &&
            strcmp(method, MHD_HTTP_METHOD_GET) == 0) {
            return handle_get_texture_metadata(&ctx, uuid);
        }
        if (strcmp(slash, "/raw") == 0 &&
            strcmp(method, MHD_HTTP_METHOD_GET) == 0) {
            return handle_get_texture_raw(&ctx, uuid);
        }
    }

    return resp_plain(conn, MHD_HTTP_NOT_FOUND, "Not found");
}

/* ------------------------------------------------------------------------
 * Service bootstrap
 * ----------------------------------------------------------------------*/
int
main(void)
{
    LOG_INFO("Texture Service starting on port %d", SERVICE_PORT);
    repo_init();

    struct MHD_Daemon *daemon = MHD_start_daemon(
        MHD_USE_SELECT_INTERNALLY, SERVICE_PORT, NULL, NULL,
        &dispatch, NULL, MHD_OPTION_END);
    if (!daemon) {
        LOG_ERROR("Failed to start HTTP daemon");
        return EXIT_FAILURE;
    }

    LOG_INFO("Texture Service ready");
    (void)getchar(); /* Run until stdin closes, simple way to stop */
    LOG_INFO("Shutting down");

    MHD_stop_daemon(daemon);

    /* Cleanup cache */
    pthread_mutex_lock(&g_cache.lock);
    cache_entry_t *it = g_cache.head;
    while (it) {
        cache_entry_t *next = it->next;
        free(it->pixels);
        free(it);
        it = next;
    }
    pthread_mutex_unlock(&g_cache.lock);

    return EXIT_SUCCESS;
}
```