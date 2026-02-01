/*
 * SynestheticCanvas - Texture Service (texture-service)
 *
 * File:    src/main.c
 * Author:  SynestheticCanvas Core Team
 * License: MIT
 *
 * Description:
 *   Stand-alone micro-service responsible for on-demand texture synthesis.
 *   Exposes a small HTTP/REST surface (with GraphQL overlay handled by the
 *   upstream gateway) enabling clients to request procedurally generated
 *   textures in real time.  
 *
 *   1. Config is read from JSON (environment override: SC_TEXTURE_CONFIG).
 *   2. Robust structured logging (levels, timestamps, source).
 *   3. Graceful shutdown (SIGINT / SIGTERM).
 *   4. Built on libmicrohttpd for tiny HTTP footprint.
 *   5. Implements a simple value-noise generator for demonstration purposes.
 *
 *   Endpoints:
 *     GET /healthz              → {"status":"ok"}
 *     GET /v1/noise?width=..&height=..&scale=..  
 *                                → binary PGM payload (Content-Type: image/x-pgm)
 *
 * Build flags (example):
 *   cc -Wall -Wextra -O2 -DMHD_STATIC -lm -lcjson -lmicrohttpd \
 *      -o texture-service src/main.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <signal.h>
#include <time.h>
#include <errno.h>
#include <math.h>

#include <microhttpd.h>   /* libmicrohttpd */
#include <cjson/cJSON.h>  /* cJSON */

#define DEFAULT_PORT                8080
#define DEFAULT_MAX_TEXTURE_SIZE    4096   /* pixels in either dimension */
#define DEFAULT_SCALE               8.0f
#define MAX_LOG_LINE                1024
#define CONFIG_ENV_VAR              "SC_TEXTURE_CONFIG"

/* ---------- Logging ------------------------------------------------------ */

typedef enum {
    LOG_DEBUG = 0,
    LOG_INFO,
    LOG_WARN,
    LOG_ERROR,
    LOG_FATAL
} LogLevel;

static const char *LOG_LEVEL_NAMES[] = {
    "DEBUG", "INFO", "WARN", "ERROR", "FATAL"
};

static LogLevel g_log_level = LOG_INFO;

/* Variadic logger */
static void log_msg(LogLevel level, const char *fmt, ...)
{
    if (level < g_log_level)
        return;

    char tsbuf[32];
    time_t  now  = time(NULL);
    struct tm tm = *localtime(&now);
    strftime(tsbuf, sizeof(tsbuf), "%Y-%m-%d %H:%M:%S", &tm);

    fprintf(level >= LOG_ERROR ? stderr : stdout,
            "%s [%s] ", tsbuf, LOG_LEVEL_NAMES[level]);

    va_list ap;
    va_start(ap, fmt);
    vfprintf(level >= LOG_ERROR ? stderr : stdout, fmt, ap);
    va_end(ap);
    fputc('\n', level >= LOG_ERROR ? stderr : stdout);

    if (level == LOG_FATAL)
        exit(EXIT_FAILURE);
}

/* ---------- Configuration ------------------------------------------------ */

typedef struct {
    unsigned short port;
    unsigned       max_texture_size; /* maximum width/height */
    LogLevel       log_level;
} ServiceConfig;

/* Forward-decl for default config generator */
static void config_set_defaults(ServiceConfig *cfg);

/* Reads configuration from a JSON file. Unknown keys are ignored. */
static int config_from_file(const char *path, ServiceConfig *cfg)
{
    FILE *fp = fopen(path, "r");
    if (!fp)
        return -1;

    fseek(fp, 0, SEEK_END);
    long len = ftell(fp);
    rewind(fp);

    char *text = malloc(len + 1);
    if (!text) { fclose(fp); return -1; }
    fread(text, 1, len, fp);
    text[len] = '\0';
    fclose(fp);

    cJSON *json = cJSON_Parse(text);
    free(text);

    if (!json) {
        log_msg(LOG_ERROR, "Config parse error at pos %zu", cJSON_GetErrorPtr() - text);
        return -1;
    }

    cJSON *val;
    if ((val = cJSON_GetObjectItem(json, "port")) && cJSON_IsNumber(val))
        cfg->port = (unsigned short)val->valueint;

    if ((val = cJSON_GetObjectItem(json, "max_texture_size")) && cJSON_IsNumber(val))
        cfg->max_texture_size = (unsigned)val->valueint;

    if ((val = cJSON_GetObjectItem(json, "log_level")) && cJSON_IsString(val)) {
        const char *lvl = cJSON_GetStringValue(val);
        for (size_t i = 0; i < sizeof(LOG_LEVEL_NAMES)/sizeof(LOG_LEVEL_NAMES[0]); ++i) {
            if (strcasecmp(lvl, LOG_LEVEL_NAMES[i]) == 0) {
                cfg->log_level = (LogLevel)i;
                break;
            }
        }
    }

    cJSON_Delete(json);
    return 0;
}

static void config_set_defaults(ServiceConfig *cfg)
{
    cfg->port             = DEFAULT_PORT;
    cfg->max_texture_size = DEFAULT_MAX_TEXTURE_SIZE;
    cfg->log_level        = LOG_INFO;
}

/* ---------- Value-Noise Generator --------------------------------------- */

/* Simple hash-based 2D value noise (deterministic) */
static inline float hash2i(int x, int y)
{
    /* Jenkins hash variant */
    unsigned int h = (unsigned int)(x * 374761393u + y * 668265263u); /* large primes */
    h = (h ^ (h >> 13u)) * 1274126177u;
    return (float)(h & 0xFFFF) / 65535.0f;
}

static inline float lerp(float a, float b, float t) { return a + t*(b-a); }

/* Bilinear interpolation of hashed corner values */
static float value_noise(float x, float y)
{
    int xi = (int)floorf(x);
    int yi = (int)floorf(y);

    float xf = x - xi;
    float yf = y - yi;

    float v00 = hash2i(xi,     yi);
    float v10 = hash2i(xi + 1, yi);
    float v01 = hash2i(xi,     yi + 1);
    float v11 = hash2i(xi + 1, yi + 1);

    float i1 = lerp(v00, v10, xf);
    float i2 = lerp(v01, v11, xf);

    return lerp(i1, i2, yf);
}

/* Fractal Brownian Motion wrapper for richer texture */
static float fbm(float x, float y, int octaves, float lacunarity, float gain)
{
    float total = 0.0f;
    float amp   = 1.0f;
    for (int i = 0; i < octaves; ++i) {
        total += value_noise(x, y) * amp;
        x      *= lacunarity;
        y      *= lacunarity;
        amp    *= gain;
    }
    return total;
}

/* Generates a binary PGM buffer (always 8-bit grayscale). */
static int generate_texture_pgm(unsigned width,
                                unsigned height,
                                float     scale,
                                unsigned char **out_buf,
                                size_t    *out_size)
{
    if (!out_buf || !out_size)
        return -1;

    const size_t header_len = 32;
    const size_t img_len    = width * height;
    size_t total_len        = header_len + img_len;

    unsigned char *buf = malloc(total_len);
    if (!buf)
        return -1;

    int header_written = snprintf((char*)buf, header_len, "P5\n%u %u\n255\n", width, height);
    if (header_written < 0 || (size_t)header_written >= header_len) {
        free(buf);
        return -1;
    }

    unsigned char *pixels = buf + header_written;
    float inv_scale       = 1.0f / (scale <= 0.0f ? DEFAULT_SCALE : scale);

    for (unsigned y = 0; y < height; ++y) {
        for (unsigned x = 0; x < width; ++x) {
            float nx = x * inv_scale;
            float ny = y * inv_scale;
            float v  = fbm(nx, ny, 5, 2.0f, 0.5f); /* 5 octave FBM */
            /* Normalize */
            v = fminf(fmaxf(v, 0.0f), 1.0f);
            pixels[y*width + x] = (unsigned char)(v * 255.0f);
        }
    }

    *out_buf  = buf;
    *out_size = header_written + img_len;
    return 0;
}

/* ---------- HTTP Request Handling --------------------------------------- */

typedef struct {
    struct MHD_Daemon *daemon;
    ServiceConfig      cfg;
} ServiceCtx;

static enum MHD_Result
send_response(struct MHD_Connection *conn,
              const char           *mime,
              const unsigned char  *data,
              size_t                size,
              unsigned int          status)
{
    struct MHD_Response *resp = MHD_create_response_from_buffer(size,
                                            (void*)data,
                                            MHD_RESPMEM_MUST_COPY);
    if (!resp)
        return MHD_NO;

    MHD_add_response_header(resp, "Content-Type", mime);
    enum MHD_Result ret = MHD_queue_response(conn, status, resp);
    MHD_destroy_response(resp);
    return ret;
}

/* Helpers to parse int params safely */
static int query_param_int(struct MHD_Connection *conn,
                           const char *key,
                           int def,
                           int *out_val)
{
    const char *str = MHD_lookup_connection_value(conn, MHD_GET_ARGUMENT_KIND, key);
    if (!str) {
        *out_val = def;
        return 0;
    }

    char *endptr = NULL;
    long val = strtol(str, &endptr, 10);
    if (endptr == str || val < 0 || val > INT_MAX)
        return -1;

    *out_val = (int)val;
    return 0;
}

static int handle_healthz(struct MHD_Connection *conn)
{
    const char *ok = "{\"status\":\"ok\"}";
    return send_response(conn, "application/json", (const unsigned char*)ok,
                         strlen(ok), MHD_HTTP_OK);
}

static int handle_noise(ServiceCtx          *svc,
                        struct MHD_Connection *conn)
{
    int width, height;
    if (query_param_int(conn, "width", 256, &width)   ||
        query_param_int(conn, "height", 256, &height))
    {
        const char *err = "{\"error\":\"invalid width/height\"}";
        return send_response(conn, "application/json",
                             (const unsigned char*)err,
                             strlen(err),
                             MHD_HTTP_BAD_REQUEST);
    }

    if (width  <= 0 || width  > (int)svc->cfg.max_texture_size ||
        height <= 0 || height > (int)svc->cfg.max_texture_size)
    {
        const char *err = "{\"error\":\"dimensions out of range\"}";
        return send_response(conn, "application/json",
                             (const unsigned char*)err,
                             strlen(err),
                             MHD_HTTP_BAD_REQUEST);
    }

    float scale = DEFAULT_SCALE;
    const char *scale_str = MHD_lookup_connection_value(conn,
                                MHD_GET_ARGUMENT_KIND, "scale");
    if (scale_str)
        scale = strtof(scale_str, NULL);

    unsigned char *buf  = NULL;
    size_t         size = 0;
    if (generate_texture_pgm((unsigned)width,
                             (unsigned)height,
                             scale,
                             &buf,
                             &size) != 0)
    {
        const char *err = "{\"error\":\"generation failed\"}";
        return send_response(conn, "application/json",
                             (const unsigned char*)err,
                             strlen(err),
                             MHD_HTTP_INTERNAL_SERVER_ERROR);
    }

    enum MHD_Result res = send_response(conn, "image/x-pgm", buf, size,
                                        MHD_HTTP_OK);
    free(buf);
    return res;
}

/* libmicrohttpd callback */
static enum MHD_Result
request_router(void                *cls,
               struct MHD_Connection *connection,
               const char           *url,
               const char           *method,
               const char           *version,
               const char           *upload_data,
               size_t               *upload_data_size,
               void                **con_cls)
{
    (void)cls; (void)version; (void)upload_data; (void)upload_data_size; (void)con_cls;

    if (strcmp(method, "GET") != 0)
        return MHD_NO;

    ServiceCtx *svc = (ServiceCtx*)cls;

    if (strcmp(url, "/healthz") == 0) {
        return handle_healthz(connection);
    }
    else if (strcmp(url, "/v1/noise") == 0) {
        return handle_noise(svc, connection);
    }
    else {
        const char *err = "{\"error\":\"not found\"}";
        return send_response(connection, "application/json",
                             (const unsigned char*)err,
                             strlen(err),
                             MHD_HTTP_NOT_FOUND);
    }
}

/* ---------- Graceful Shutdown ------------------------------------------- */

static volatile sig_atomic_t g_shutdown = 0;

static void on_signal(int sig)
{
    (void)sig;
    g_shutdown = 1;
}

/* ---------- Main -------------------------------------------------------- */

int main(void)
{
    ServiceCtx svc;
    config_set_defaults(&svc.cfg);

    /* --- Load configuration file if provided -------------------------- */
    const char *cfg_path = getenv(CONFIG_ENV_VAR);
    if (cfg_path && *cfg_path) {
        if (config_from_file(cfg_path, &svc.cfg) != 0) {
            log_msg(LOG_WARN, "Falling back to default config (%s)", strerror(errno));
        }
    }
    g_log_level = svc.cfg.log_level;

    log_msg(LOG_INFO, "Texture-Service starting on port %u", svc.cfg.port);

    /* --- Setup signal handlers ---------------------------------------- */
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_signal;
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    /* --- Start HTTP daemon -------------------------------------------- */
    svc.daemon = MHD_start_daemon(MHD_USE_AUTO | MHD_USE_INTERNAL_POLLING_THREAD,
                                  svc.cfg.port,
                                  NULL, NULL,
                                  request_router, &svc,
                                  MHD_OPTION_CONNECTION_TIMEOUT, (unsigned int)10,
                                  MHD_OPTION_END);
    if (!svc.daemon) {
        log_msg(LOG_FATAL, "Failed to start HTTP daemon");
    }

    log_msg(LOG_INFO, "Texture-Service ready (max_texture_size=%u)",
            svc.cfg.max_texture_size);

    /* --- Wait until a termination signal is received ------------------ */
    while (!g_shutdown)
        sleep(1);

    log_msg(LOG_INFO, "Shutting down...");
    MHD_stop_daemon(svc.daemon);

    log_msg(LOG_INFO, "Shutdown complete");
    return EXIT_SUCCESS;
}