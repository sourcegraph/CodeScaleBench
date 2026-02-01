/*
 * sc_config.c
 * SynestheticCanvas Common Library - Configuration Management
 *
 * This module is responsible for loading, merging, reloading and supplying
 * runtime configuration values required by all other components of the
 * SynestheticCanvas constellation.  It supports three layers of
 * configuration (lowest to highest priority):
 *
 *   1. Static defaults compiled into the binary      (compile-time)
 *   2. Key/Value config file on disk (INI-like)      (runtime, optional)
 *   3. Individual environment variables              (runtime, optional)
 *
 * If built with SC_CONFIG_ENABLE_INOTIFY (Linux only), the module will keep
 * monitoring the configuration file and hot-reload values after receiving
 * inotify events, subsequently broadcasting SC_CONFIG_RELOAD events to
 * interested subscribers via the logging subsystem.
 *
 * Author  : SynestheticCanvas Core Team
 * License : MIT
 */

#include "sc_config.h"
#include "sc_logger.h"

#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef SC_CONFIG_ENABLE_INOTIFY
#include <sys/inotify.h>
#include <unistd.h>
#endif

/* -------------------------------------------------------------------------
 * Internal helpers / declarations
 * ------------------------------------------------------------------------- */

#define SC_CONFIG_FILE_MAX_LINE 4096
#define SC_CONFIG_INOTIFY_BUF   4096

typedef struct sc_kv_pair {
    char key[SC_CONFIG_KEY_MAX];
    char value[SC_CONFIG_VALUE_MAX];
} sc_kv_pair_t;

static void     sc_trim(char *s);
static int      sc_parse_kv_line(const char *line, sc_kv_pair_t *out);
static int      sc_read_file_kv(const char *path,
                                sc_config_t *cfg,
                                sc_err_t *err);
static void     sc_config_apply_pair(sc_config_t *cfg,
                                     const sc_kv_pair_t *pair);
static void     sc_config_apply_env(sc_config_t *cfg);
static int      sc_parse_size(const char *s, size_t *out);
static _Bool    sc_path_readable(const char *path);

#ifdef SC_CONFIG_ENABLE_INOTIFY
static void    *sc_watchdog_thread(void *arg);
#endif

/* -------------------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------------------- */

void sc_config_init_defaults(sc_config_t *cfg)
{
    if (!cfg) return;

    /* Zero entire struct so that strings are NULL */
    memset(cfg, 0, sizeof(*cfg));

    /* Static defaults */
    cfg->service_name              = strdup("synesthetic_canvas");
    cfg->service_version           = strdup("0.1.0-dev");
    cfg->log_level                 = strdup("info");
    cfg->graphql_schema_path       = strdup("./schemas/graphql/root.graphql");
    cfg->validator_schema_path     = strdup("./schemas/validators/request.json");
    cfg->rest_endpoint_prefix      = strdup("/api/v1");
    cfg->pagination_default_limit  = 25;
    cfg->pagination_max_limit      = 250;
    cfg->enable_metrics            = 1;
    cfg->enable_request_validation = 1;
}

sc_err_t sc_config_load(const sc_config_opts_t *opts,
                        sc_config_t *out_cfg)
{
    sc_err_t err = {0};

    if (!out_cfg) {
        err.code = SC_ERR_INVALID_ARG;
        snprintf(err.msg, sizeof(err.msg), "out_cfg cannot be NULL");
        return err;
    }

    /* 1. Defaults */
    sc_config_init_defaults(out_cfg);

    /* 2. Config file (optional) */
    if (opts && opts->config_path[0] != '\0') {
        if (!sc_path_readable(opts->config_path)) {
            err.code = SC_ERR_FILE_IO;
            snprintf(err.msg, sizeof(err.msg),
                     "Config file '%s' is not readable: %s",
                     opts->config_path, strerror(errno));
            goto fail;
        }

        if (!sc_read_file_kv(opts->config_path, out_cfg, &err)) {
            goto fail;
        }
    }

    /* 3. Environment overrides */
    sc_config_apply_env(out_cfg);

#ifdef SC_CONFIG_ENABLE_INOTIFY
    /* 4. Start watchdog thread if requested */
    if (opts && opts->watch_config && opts->config_path[0] != '\0') {
        pthread_t tid;
        char *path_dup = strdup(opts->config_path);
        if (!path_dup) {
            err.code = SC_ERR_OOM;
            snprintf(err.msg, sizeof(err.msg),
                     "Failed to duplicate config path");
            goto fail;
        }
        if (pthread_create(&tid, NULL, sc_watchdog_thread, path_dup) != 0) {
            free(path_dup);
            err.code = SC_ERR_THREAD;
            snprintf(err.msg, sizeof(err.msg),
                     "Failed to spawn config watchdog thread");
            goto fail;
        }
        pthread_detach(tid);
    }
#endif

    return err;

fail:
    sc_config_destroy(out_cfg);
    return err;
}

void sc_config_destroy(sc_config_t *cfg)
{
    if (!cfg) return;

    free(cfg->service_name);
    free(cfg->service_version);
    free(cfg->log_level);
    free(cfg->graphql_schema_path);
    free(cfg->validator_schema_path);
    free(cfg->rest_endpoint_prefix);

    memset(cfg, 0, sizeof(*cfg));
}

/* -------------------------------------------------------------------------
 * Internal – Config file parsing
 * ------------------------------------------------------------------------- */

/* Trim leading and trailing whitespace in-place */
static void sc_trim(char *s)
{
    if (!s) return;

    char *end, *start = s;

    /* Left trim */
    while (*start && (*start == ' ' || *start == '\t' ||
                      *start == '\r' || *start == '\n'))
        ++start;

    /* Right trim */
    end = start + strlen(start);
    while (end > start &&
           (end[-1] == ' ' || end[-1] == '\t' ||
            end[-1] == '\r' || end[-1] == '\n'))
        --end;

    size_t len = (size_t)(end - start);
    if (start != s)
        memmove(s, start, len);

    s[len] = '\0';
}

/* Parse "key=value" lines, ignoring comments & blank lines */
static int sc_parse_kv_line(const char *line, sc_kv_pair_t *out)
{
    if (!line || !out) return 0;

    /* Skip comments */
    if (*line == '#' || *line == ';')
        return 0;

    const char *eq = strchr(line, '=');
    if (!eq) return 0;

    size_t key_len = (size_t)(eq - line);
    size_t val_len = strlen(eq + 1);

    if (key_len == 0 || val_len == 0) return 0;
    if (key_len >= sizeof(out->key) || val_len >= sizeof(out->value))
        return 0;

    strncpy(out->key, line, key_len);
    out->key[key_len] = '\0';
    strncpy(out->value, eq + 1, val_len);
    out->value[val_len] = '\0';

    sc_trim(out->key);
    sc_trim(out->value);

    return 1;
}

static int sc_read_file_kv(const char *path,
                           sc_config_t *cfg,
                           sc_err_t *err)
{
    FILE *fp = fopen(path, "r");
    if (!fp) {
        if (err) {
            err->code = SC_ERR_FILE_IO;
            snprintf(err->msg, sizeof(err->msg),
                     "Failed to open config file '%s': %s",
                     path, strerror(errno));
        }
        return 0;
    }

    char line[SC_CONFIG_FILE_MAX_LINE];
    sc_kv_pair_t pair;

    size_t lineno = 0;

    while (fgets(line, sizeof(line), fp)) {
        ++lineno;

        if (!sc_parse_kv_line(line, &pair))
            continue; /* Skip blank/comment/invalid */

        sc_config_apply_pair(cfg, &pair);
    }

    fclose(fp);
    return 1;
}

/* -------------------------------------------------------------------------
 * Internal – Key -> Config field binding
 * ------------------------------------------------------------------------- */

static void sc_config_apply_pair(sc_config_t *cfg,
                                 const sc_kv_pair_t *pair)
{
#define MATCH(k) (strcasecmp((k), pair->key) == 0)

    if (MATCH("service.name")) {
        free(cfg->service_name);
        cfg->service_name = strdup(pair->value);
    } else if (MATCH("service.version")) {
        free(cfg->service_version);
        cfg->service_version = strdup(pair->value);
    } else if (MATCH("log.level")) {
        free(cfg->log_level);
        cfg->log_level = strdup(pair->value);
    } else if (MATCH("graphql.schema_path")) {
        free(cfg->graphql_schema_path);
        cfg->graphql_schema_path = strdup(pair->value);
    } else if (MATCH("validator.schema_path")) {
        free(cfg->validator_schema_path);
        cfg->validator_schema_path = strdup(pair->value);
    } else if (MATCH("rest.endpoint_prefix")) {
        free(cfg->rest_endpoint_prefix);
        cfg->rest_endpoint_prefix = strdup(pair->value);
    } else if (MATCH("pagination.default_limit")) {
        size_t val;
        if (sc_parse_size(pair->value, &val))
            cfg->pagination_default_limit = val;
    } else if (MATCH("pagination.max_limit")) {
        size_t val;
        if (sc_parse_size(pair->value, &val))
            cfg->pagination_max_limit = val;
    } else if (MATCH("metrics.enable")) {
        cfg->enable_metrics = (strcasecmp(pair->value, "true") == 0 ||
                               strcmp(pair->value, "1") == 0);
    } else if (MATCH("request_validation.enable")) {
        cfg->enable_request_validation = (strcasecmp(pair->value, "true") == 0 ||
                                          strcmp(pair->value, "1") == 0);
    }
#undef MATCH
}

static void sc_config_apply_env(sc_config_t *cfg)
{
    const char *val;

#define ENV_OVERRIDE(env_name, action)                 \
    do {                                               \
        val = getenv(env_name);                        \
        if (val && val[0] != '\0') {                   \
            action;                                    \
        }                                              \
    } while (0)

    ENV_OVERRIDE("SC_SERVICE_NAME", {
        free(cfg->service_name);
        cfg->service_name = strdup(val);
    });

    ENV_OVERRIDE("SC_SERVICE_VERSION", {
        free(cfg->service_version);
        cfg->service_version = strdup(val);
    });

    ENV_OVERRIDE("SC_LOG_LEVEL", {
        free(cfg->log_level);
        cfg->log_level = strdup(val);
    });

    ENV_OVERRIDE("SC_GQL_SCHEMA_PATH", {
        free(cfg->graphql_schema_path);
        cfg->graphql_schema_path = strdup(val);
    });

    ENV_OVERRIDE("SC_VALIDATOR_SCHEMA_PATH", {
        free(cfg->validator_schema_path);
        cfg->validator_schema_path = strdup(val);
    });

    ENV_OVERRIDE("SC_REST_PREFIX", {
        free(cfg->rest_endpoint_prefix);
        cfg->rest_endpoint_prefix = strdup(val);
    });

    ENV_OVERRIDE("SC_PAGINATION_DEFAULT_LIMIT", {
        size_t parsed;
        if (sc_parse_size(val, &parsed))
            cfg->pagination_default_limit = parsed;
    });

    ENV_OVERRIDE("SC_PAGINATION_MAX_LIMIT", {
        size_t parsed;
        if (sc_parse_size(val, &parsed))
            cfg->pagination_max_limit = parsed;
    });

    ENV_OVERRIDE("SC_ENABLE_METRICS", {
        cfg->enable_metrics = (strcasecmp(val, "true") == 0 ||
                               strcmp(val, "1") == 0);
    });

    ENV_OVERRIDE("SC_ENABLE_VALIDATION", {
        cfg->enable_request_validation = (strcasecmp(val, "true") == 0 ||
                                          strcmp(val, "1") == 0);
    });

#undef ENV_OVERRIDE
}

/* -------------------------------------------------------------------------
 * Internal – Helpers
 * ------------------------------------------------------------------------- */

static int sc_parse_size(const char *s, size_t *out)
{
    if (!s || !out) return 0;

    char *end = NULL;
    errno = 0;
    unsigned long long val = strtoull(s, &end, 10);
    if (errno != 0 || end == s || *end != '\0')
        return 0;
    *out = (size_t)val;
    return 1;
}

static _Bool sc_path_readable(const char *path)
{
    struct stat st;
    return (stat(path, &st) == 0) && S_ISREG(st.st_mode);
}

/* -------------------------------------------------------------------------
 * Optional – Live reload via inotify (Linux)
 * ------------------------------------------------------------------------- */

#ifdef SC_CONFIG_ENABLE_INOTIFY
typedef struct {
    int         fd;
    int         wd;
    char        path[PATH_MAX];
} sc_watch_ctx_t;

static void *sc_watchdog_thread(void *arg)
{
    char *path = (char *)arg;

    sc_watch_ctx_t ctx;
    ctx.fd = inotify_init1(IN_CLOEXEC);
    if (ctx.fd < 0) {
        SC_LOG_ERROR("config", "inotify_init failed: %s", strerror(errno));
        free(path);
        return NULL;
    }

    strncpy(ctx.path, path, sizeof(ctx.path)-1);
    ctx.path[sizeof(ctx.path)-1] = '\0';

    ctx.wd = inotify_add_watch(ctx.fd, ctx.path,
                               IN_MODIFY | IN_CLOSE_WRITE | IN_MOVED_TO);
    if (ctx.wd < 0) {
        SC_LOG_ERROR("config", "inotify_add_watch failed for %s: %s",
                     ctx.path, strerror(errno));
        close(ctx.fd);
        free(path);
        return NULL;
    }

    SC_LOG_INFO("config", "Started watching %s for changes", ctx.path);

    char buf[SC_CONFIG_INOTIFY_BUF] __attribute__((aligned(__alignof__(struct inotify_event))));

    for (;;) {
        ssize_t len = read(ctx.fd, buf, sizeof(buf));
        if (len <= 0) {
            if (errno == EINTR)
                continue;
            SC_LOG_ERROR("config", "inotify read error: %s", strerror(errno));
            break;
        }

        const struct inotify_event *ev;
        for (char *ptr = buf; ptr < buf + len;
             ptr += sizeof(struct inotify_event) + ev->len) {
            ev = (const struct inotify_event *)ptr;
            if (ev->mask & (IN_MODIFY | IN_CLOSE_WRITE | IN_MOVED_TO)) {
                SC_LOG_INFO("config", "Config file changed, triggering reload");
                sc_config_t new_cfg;
                sc_config_opts_t opts = {
                    .config_path = {0},
                    .watch_config = 0
                };
                strncpy(opts.config_path, ctx.path, sizeof(opts.config_path)-1);
                sc_err_t e = sc_config_load(&opts, &new_cfg);
                if (e.code == SC_OK) {
                    sc_config_set_global(&new_cfg); /* Provided by sc_config.h */
                    SC_LOG_INFO("config", "Configuration hot-reloaded");
                } else {
                    SC_LOG_ERROR("config",
                                 "Failed to reload configuration: (%d) %s",
                                 e.code, e.msg);
                }
            }
        }
    }

    inotify_rm_watch(ctx.fd, ctx.wd);
    close(ctx.fd);
    free(path);
    return NULL;
}
#endif /* SC_CONFIG_ENABLE_INOTIFY */
