/*
 * File: ll_config_parser.c
 * Project: LexiLearn MVC Orchestrator (ml_nlp)
 * Description:
 *   Robust parser for LexiLearn configuration files.  The parser supports
 *   INI-style syntax with sections, key-value pairs, environment-variable
 *   substitution, and runtime validation utilities.
 *
 *   Example configuration (lexilearn.conf):
 *
 *     [logging]
 *     level           = INFO
 *     file            = /var/log/lexilearn/orchestrator.log
 *
 *     [ml_pipeline]
 *     default_strategy = transformer
 *     hyper_tuner      = optuna
 *     retrain_cron     = 0 3 * * 1
 *
 *     [model_registry]
 *     uri  = http://registry.internal:5000
 *     auth = ${REGISTRY_TOKEN}
 *
 *   If a value contains ${VAR_NAME} it is expanded from the process
 *   environment.  Missing variables raise an error unless
 *   LL_CFG_ENV_MISSING_AS_EMPTY is passed to the loader.
 *
 * Author: LexiLearn Engineering
 * License: Apache-2.0
 */

#define _POSIX_C_SOURCE 200809L /* for getline */
#include <ctype.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/*-----------------------------------------------------------------------------
 * Public API
 *---------------------------------------------------------------------------*/
#include "ll_config_parser.h" /* The public header for this module */

/*-----------------------------------------------------------------------------
 * Internal Data Structures
 *---------------------------------------------------------------------------*/
typedef struct ll_cfg_kv {
    char               *key;
    char               *value;
    struct ll_cfg_kv   *next;
} ll_cfg_kv_t;

typedef struct ll_cfg_section {
    char                     *name;
    ll_cfg_kv_t              *kv_head;
    struct ll_cfg_section    *next;
} ll_cfg_section_t;

struct ll_cfg_ctx {
    ll_cfg_section_t *sec_head;
};

/*-----------------------------------------------------------------------------
 * Helpers – memory utilities
 *---------------------------------------------------------------------------*/
static void *xcalloc(size_t n, size_t s)
{
    void *p = calloc(n, s);
    if (!p) {
        fprintf(stderr, "lexilearn: out of memory\n");
        abort();
    }
    return p;
}

static char *xstrdup(const char *s)
{
    char *dup = strdup(s);
    if (!dup) {
        fprintf(stderr, "lexilearn: out of memory\n");
        abort();
    }
    return dup;
}

/*-----------------------------------------------------------------------------
 * Helpers – string handling
 *---------------------------------------------------------------------------*/
static char *lstrip(char *s)
{
    while (*s && isspace((unsigned char)*s)) ++s;
    return s;
}

static void rstrip(char *s)
{
    size_t len = strlen(s);
    while (len && isspace((unsigned char)s[len - 1]))
        s[--len] = '\0';
}

static bool is_comment_or_blank(const char *s)
{
    const char *p = lstrip((char *)s);
    return *p == '\0' || *p == '#' || *p == ';';
}

/*-----------------------------------------------------------------------------
 * Internal lookup helpers
 *---------------------------------------------------------------------------*/
static ll_cfg_section_t *find_section(const ll_cfg_ctx_t *ctx,
                                      const char         *name)
{
    for (ll_cfg_section_t *sec = ctx->sec_head; sec; sec = sec->next) {
        if (strcmp(sec->name, name) == 0)
            return sec;
    }
    return NULL;
}

static ll_cfg_kv_t *find_kv(const ll_cfg_section_t *sec, const char *key)
{
    for (ll_cfg_kv_t *kv = sec ? sec->kv_head : NULL; kv; kv = kv->next) {
        if (strcmp(kv->key, key) == 0)
            return kv;
    }
    return NULL;
}

/*-----------------------------------------------------------------------------
 * Environment variable expansion
 *---------------------------------------------------------------------------*/
static int expand_env_token(const char *token,
                            char      **out,
                            uint32_t    flags,
                            char       **errmsg)
{
    const char *env_val = getenv(token);
    if (!env_val) {
        if (flags & LL_CFG_ENV_MISSING_AS_EMPTY) {
            *out = xstrdup("");
            return 0;
        }
        if (errmsg) {
            size_t n = snprintf(NULL, 0,
                                "undefined environment variable '%s'", token);
            *errmsg  = xcalloc(n + 1, 1);
            snprintf(*errmsg, n + 1, "undefined environment variable '%s'",
                     token);
        }
        return -1;
    }
    *out = xstrdup(env_val);
    return 0;
}

/*
 * Expand ${VARNAME} or $VARNAME occurrences.  Returns dynamically allocated
 * string that must be free(3)’d by caller.
 */
static int perform_env_substitution(const char *src,
                                    uint32_t    flags,
                                    char      **out_str,
                                    char      **errmsg)
{
    const char  *p = src;
    size_t       capacity = strlen(src) + 1;
    size_t       len = 0;
    char        *buf = xcalloc(capacity, 1);

    while (*p) {
        if (*p == '$') {
            const char *beg = NULL, *end = NULL;
            if (*(p + 1) == '{') {
                beg = p + 2;
                end = strchr(beg, '}');
                if (!end) {
                    if (errmsg)
                        *errmsg = xstrdup("unterminated ${VAR} token");
                    free(buf);
                    return -1;
                }
            } else {
                beg = p + 1;
                end = beg;
                while (*end && (isalnum((unsigned char)*end) || *end == '_'))
                    ++end;
                if (beg == end) { /* '$' not followed by variable name */
                    buf[len++] = *p++;
                    continue;
                }
            }
            size_t var_len = (size_t)(end - beg);
            char  *varname = xcalloc(var_len + 1, 1);
            memcpy(varname, beg, var_len);
            char *env_val = NULL;
            if (expand_env_token(varname, &env_val, flags, errmsg) != 0) {
                free(varname);
                free(buf);
                return -1;
            }
            size_t env_len = strlen(env_val);
            /* grow buffer if necessary */
            if (len + env_len + 1 > capacity) {
                capacity = (capacity + env_len) * 2;
                buf      = realloc(buf, capacity);
                if (!buf) {
                    fprintf(stderr, "lexilearn: out of memory\n");
                    abort();
                }
            }
            memcpy(buf + len, env_val, env_len);
            len += env_len;
            free(env_val);
            free(varname);
            p = (*end == '}') ? end + 1 : end; /* skip '}' if present */
        } else {
            buf[len++] = *p++;
        }
    }
    buf[len] = '\0';
    *out_str = buf;
    return 0;
}

/*-----------------------------------------------------------------------------
 * Parsing implementation
 *---------------------------------------------------------------------------*/
static int parse_line(ll_cfg_ctx_t *ctx,
                      const char   *line,
                      uint32_t      flags,
                      char        **errmsg)
{
    static ll_cfg_section_t *current_section = NULL;

    /* section header */
    if (*line == '[') {
        const char *end = strchr(line, ']');
        if (!end) {
            if (errmsg) *errmsg = xstrdup("unterminated section header");
            return -1;
        }
        size_t      name_len = (size_t)(end - line - 1);
        char       *sec_name = xcalloc(name_len + 1, 1);
        memcpy(sec_name, line + 1, name_len);

        /* check duplicate sections */
        ll_cfg_section_t *existing = find_section(ctx, sec_name);
        if (existing) {
            current_section = existing;
            free(sec_name);
            return 0;
        }

        ll_cfg_section_t *sec = xcalloc(1, sizeof(*sec));
        sec->name             = sec_name;
        /* insert at head */
        sec->next        = ctx->sec_head;
        ctx->sec_head    = sec;
        current_section  = sec;
        return 0;
    }

    /* key=value lines */
    const char *equal = strchr(line, '=');
    if (!equal) {
        if (errmsg) {
            size_t n = snprintf(NULL, 0, "invalid line: '%s'", line);
            *errmsg  = xcalloc(n + 1, 1);
            snprintf(*errmsg, n + 1, "invalid line: '%s'", line);
        }
        return -1;
    }
    size_t key_len = (size_t)(equal - line);
    char  *key     = xcalloc(key_len + 1, 1);
    memcpy(key, line, key_len);
    rstrip(key);
    char *key_trim = lstrip(key);

    char *value_raw = xstrdup(equal + 1);
    char *value_trim = lstrip(value_raw);
    rstrip(value_trim);

    char *expanded = NULL;
    if (perform_env_substitution(value_trim, flags, &expanded, errmsg) != 0) {
        free(key);
        free(value_raw);
        return -1;
    }

    if (!current_section) {
        /* keys outside any section go to an implicit empty-name section */
        current_section = find_section(ctx, "");
        if (!current_section) {
            current_section        = xcalloc(1, sizeof(*current_section));
            current_section->name  = xstrdup("");
            current_section->next  = ctx->sec_head;
            ctx->sec_head          = current_section;
        }
    }

    ll_cfg_kv_t *kv   = find_kv(current_section, key_trim);
    if (kv) {
        /* override existing key */
        free(kv->value);
        kv->value = expanded;
    } else {
        kv          = xcalloc(1, sizeof(*kv));
        kv->key     = xstrdup(key_trim);
        kv->value   = expanded;
        kv->next    = current_section->kv_head;
        current_section->kv_head = kv;
    }

    free(key);
    free(value_raw);
    return 0;
}

static int parse_file_stream(ll_cfg_ctx_t *ctx,
                             FILE         *fp,
                             uint32_t      flags,
                             char        **errmsg)
{
    char  *line   = NULL;
    size_t n      = 0;
    ssize_t r     = 0;
    size_t lineno = 0;
    while ((r = getline(&line, &n, fp)) != -1) {
        ++lineno;
        /* remove trailing newline */
        if (r && (line[r - 1] == '\n' || line[r - 1] == '\r'))
            line[r - 1] = '\0';
        char *trimmed = lstrip(line);
        rstrip(trimmed);
        if (is_comment_or_blank(trimmed))
            continue;
        if (parse_line(ctx, trimmed, flags, errmsg) != 0) {
            if (errmsg && *errmsg) {
                size_t m = snprintf(NULL, 0,
                                    "line %zu: %s", lineno, *errmsg);
                char *aug = xcalloc(m + 1, 1);
                snprintf(aug, m + 1, "line %zu: %s", lineno, *errmsg);
                free(*errmsg);
                *errmsg = aug;
            }
            free(line);
            return -1;
        }
    }
    free(line);
    return 0;
}

/*-----------------------------------------------------------------------------
 * Public API implementations
 *---------------------------------------------------------------------------*/
ll_cfg_ctx_t *ll_cfg_ctx_new(void)
{
    return xcalloc(1, sizeof(ll_cfg_ctx_t));
}

void ll_cfg_ctx_free(ll_cfg_ctx_t *ctx)
{
    if (!ctx) return;

    ll_cfg_section_t *sec = ctx->sec_head;
    while (sec) {
        ll_cfg_kv_t *kv = sec->kv_head;
        while (kv) {
            ll_cfg_kv_t *next_kv = kv->next;
            free(kv->key);
            free(kv->value);
            free(kv);
            kv = next_kv;
        }
        ll_cfg_section_t *next_sec = sec->next;
        free(sec->name);
        free(sec);
        sec = next_sec;
    }
    free(ctx);
}

int ll_cfg_load_from_file(ll_cfg_ctx_t *ctx,
                          const char   *file_path,
                          uint32_t      flags,
                          char        **errmsg)
{
    if (!ctx || !file_path) {
        if (errmsg)
            *errmsg = xstrdup("invalid arguments to ll_cfg_load_from_file");
        return -1;
    }

    FILE *fp = fopen(file_path, "r");
    if (!fp) {
        if (errmsg) {
            size_t n = snprintf(NULL, 0,
                                "failed to open config '%s': %s",
                                file_path, strerror(errno));
            *errmsg  = xcalloc(n + 1, 1);
            snprintf(*errmsg, n + 1,
                     "failed to open config '%s': %s",
                     file_path, strerror(errno));
        }
        return -1;
    }

    int rc = parse_file_stream(ctx, fp, flags, errmsg);
    fclose(fp);
    return rc;
}

const char *ll_cfg_get(ll_cfg_ctx_t *ctx,
                       const char   *section,
                       const char   *key,
                       const char   *def_val)
{
    if (!ctx || !section || !key) return def_val;

    ll_cfg_section_t *sec = find_section(ctx, section);
    if (!sec) return def_val;

    ll_cfg_kv_t *kv = find_kv(sec, key);
    return kv ? kv->value : def_val;
}

bool ll_cfg_get_bool(ll_cfg_ctx_t *ctx,
                     const char   *section,
                     const char   *key,
                     bool          def_val)
{
    const char *v = ll_cfg_get(ctx, section, key, NULL);
    if (!v) return def_val;

    if (strcasecmp(v, "true") == 0 ||
        strcasecmp(v, "yes") == 0 ||
        strcmp(v, "1") == 0)
        return true;
    if (strcasecmp(v, "false") == 0 ||
        strcasecmp(v, "no") == 0 ||
        strcmp(v, "0") == 0)
        return false;

    return def_val;
}

long ll_cfg_get_long(ll_cfg_ctx_t *ctx,
                     const char   *section,
                     const char   *key,
                     long          def_val)
{
    const char *v = ll_cfg_get(ctx, section, key, NULL);
    if (!v) return def_val;

    char *endptr = NULL;
    errno = 0;
    long val = strtol(v, &endptr, 10);
    if (errno || *endptr != '\0')  /* not a valid long */
        return def_val;
    return val;
}

double ll_cfg_get_double(ll_cfg_ctx_t *ctx,
                         const char   *section,
                         const char   *key,
                         double        def_val)
{
    const char *v = ll_cfg_get(ctx, section, key, NULL);
    if (!v) return def_val;

    char *endptr = NULL;
    errno = 0;
    double d = strtod(v, &endptr);
    if (errno || *endptr != '\0')
        return def_val;
    return d;
}

/*-----------------------------------------------------------------------------
 * Convenience function – load from standard locations
 *---------------------------------------------------------------------------*/
static const char *default_search_paths[] = {
    "./lexilearn.conf",
    "/etc/lexilearn/lexilearn.conf",
    NULL
};

int ll_cfg_auto_load(ll_cfg_ctx_t *ctx,
                     uint32_t      flags,
                     char        **errmsg)
{
    const char *env_path = getenv("LEXILEARN_CFG");
    if (env_path) {
        if (ll_cfg_load_from_file(ctx, env_path, flags, errmsg) == 0)
            return 0;

        /* if env path fails, report immediately */
        return -1;
    }

    for (const char **p = default_search_paths; *p; ++p) {
        if (ll_cfg_load_from_file(ctx, *p, flags, NULL) == 0)
            return 0;
    }

    if (errmsg)
        *errmsg = xstrdup("unable to locate configuration file");
    return -1;
}

/*-----------------------------------------------------------------------------
 * Debug helpers
 *---------------------------------------------------------------------------*/
#ifdef LL_CFG_ENABLE_DUMP
void ll_cfg_dump(const ll_cfg_ctx_t *ctx, FILE *out)
{
    if (!ctx) return;
    for (ll_cfg_section_t *sec = ctx->sec_head; sec; sec = sec->next) {
        fprintf(out, "[%s]\n", sec->name);
        for (ll_cfg_kv_t *kv = sec->kv_head; kv; kv = kv->next) {
            fprintf(out, "%s=%s\n", kv->key, kv->value);
        }
        fprintf(out, "\n");
    }
}
#endif /* LL_CFG_ENABLE_DUMP */
