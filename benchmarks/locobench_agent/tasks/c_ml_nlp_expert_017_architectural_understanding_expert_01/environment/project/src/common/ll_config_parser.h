/*
 * ============================================================================
 *  LexiLearn Orchestrator – Common Utilities
 *  File: ll_config_parser.h
 *
 *  Description:
 *      Header-only, production-quality configuration parser used throughout the
 *      LexiLearn MVC Orchestrator.  The parser understands an INI-like syntax
 *      with sections, dot-notation keys, single-line comments, and environment
 *      variable expansion (${VAR}).  It provides a thin, zero-dependency API
 *      for loading, querying, modifying, and hot-reloading configuration files.
 *
 *      The file follows the “single-header” pattern.  To compile the
 *      implementation, define LL_CONFIG_PARSER_IMPLEMENTATION in exactly ONE
 *      translation unit before including this header:
 *
 *          #define LL_CONFIG_PARSER_IMPLEMENTATION
 *          #include "ll_config_parser.h"
 *
 *      All other translation units should include the header without defining
 *      the macro.
 *
 *  Author:  LexiLearn Core Team
 *  License: MIT
 * ============================================================================
 */

#ifndef LL_CONFIG_PARSER_H
#define LL_CONFIG_PARSER_H

/* --------------------------------------------------------------------------
 *  Standard headers
 * -------------------------------------------------------------------------- */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>

#ifdef __cplusplus
extern "C" {
#endif

/* --------------------------------------------------------------------------
 *  Public API
 * -------------------------------------------------------------------------- */

/* Forward declaration ------------------------------------------------------ */
typedef struct ll_cfg           ll_cfg_t;

/**
 * ll_cfg_load
 * --------------------------------------------------------------------------
 * Parse a configuration file and create a new configuration handle.
 *
 * @param  path        Path to the configuration file.
 * @param  err_out     Optional; if non-NULL, receives a malloc()’d
 *                     human-readable error message.  The caller must free().
 *
 * @return Pointer to configuration handle on success, NULL on failure.
 */
ll_cfg_t *ll_cfg_load(const char *path, char **err_out);

/**
 * ll_cfg_reload
 * --------------------------------------------------------------------------
 * Re-parse the configuration file if it has been modified on disk since the
 * last load/reload call.  In production, this can be scheduled by a watchdog
 * thread to enable hot-reload of orchestrator settings without downtime.
 *
 * @param  cfg         Configuration handle returned by ll_cfg_load().
 * @param  err_out     Optional; receives malloc()’d error string on failure.
 *
 * @return  1 if file was reloaded, 0 if no changes detected, ‑1 on error.
 */
int ll_cfg_reload(ll_cfg_t *cfg, char **err_out);

/**
 * Getter helpers
 * --------------------------------------------------------------------------
 * Fetch typed values from the configuration.  If the key is missing or the
 * value cannot be coerced to the requested type, the specified default is
 * returned instead.
 */
const char *ll_cfg_get_str   (const ll_cfg_t *cfg, const char *key,
                              const char *default_val);
int         ll_cfg_get_int   (const ll_cfg_t *cfg, const char *key,
                              int default_val);
double      ll_cfg_get_double(const ll_cfg_t *cfg, const char *key,
                              double default_val);
bool        ll_cfg_get_bool  (const ll_cfg_t *cfg, const char *key,
                              bool default_val);

/**
 * ll_cfg_set
 * --------------------------------------------------------------------------
 * Set or update a key in memory (does NOT write to disk).  The key will be
 * automatically duplicated; the caller retains ownership of the arguments.
 *
 * @return 0 on success, ‑1 on allocation failure.
 */
int  ll_cfg_set(ll_cfg_t *cfg, const char *key, const char *value);

/**
 * ll_cfg_save
 * --------------------------------------------------------------------------
 * Persist the in-memory configuration onto disk, atomically replacing the
 * original file (safe write-rename sequence).
 *
 * @return 0 on success, ‑1 on error.
 */
int  ll_cfg_save(const ll_cfg_t *cfg, char **err_out);

/**
 * ll_cfg_free
 * --------------------------------------------------------------------------
 * Release all resources associated with the configuration handle.
 */
void ll_cfg_free(ll_cfg_t *cfg);

/* --------------------------------------------------------------------------
 *  Optional helpers (inline)
 * -------------------------------------------------------------------------- */
static inline long ll_cfg_get_long(const ll_cfg_t *cfg,
                                   const char      *key,
                                   long             default_val)
{
    return (long)ll_cfg_get_int(cfg, key, (int)default_val);
}

/* --------------------------------------------------------------------------
 *  Implementation (define LL_CONFIG_PARSER_IMPLEMENTATION in ONE .c/.cpp file)
 * -------------------------------------------------------------------------- */
#ifdef LL_CONFIG_PARSER_IMPLEMENTATION
/* --- Private structures --------------------------------------------------- */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#if defined(_WIN32)
    #include <io.h>
    #include <sys/stat.h>
    #define stat _stat
#else
    #include <sys/stat.h>
#endif

/* Linked-list entry for key/value pair */
typedef struct ll_cfg_entry
{
    char                    *key;
    char                    *value;
    struct ll_cfg_entry     *next;
} ll_cfg_entry_t;

struct ll_cfg
{
    char            *path;          /* Path to backing file (dup-ed)          */
    time_t           mtime;         /* Last modification time observed        */
    ll_cfg_entry_t  *entries;       /* Linked list of key/value pairs         */
};

/* --------------------------------------------------------------------------
 *  Utility helpers (static)
 * -------------------------------------------------------------------------- */

/* trim – remove leading/trailing whitespace (in-place) --------------------- */
static char *trim(char *s)
{
    char *end;
    while (*s && isspace((unsigned char)*s)) ++s;
    if (!*s) return s;

    end = s + strlen(s) - 1;
    while (end > s && isspace((unsigned char)*end)) --end;
    *(end + 1) = '\0';
    return s;
}

/* env_expand – expand ${VAR} patterns inside value strings ----------------- */
static char *env_expand(const char *src)
{
    const char *p = src;
    size_t out_cap = strlen(src) + 1;
    char *out = (char *)malloc(out_cap);
    if (!out) return NULL;

    size_t idx = 0;
    while (*p)
    {
        if (p[0] == '$' && p[1] == '{')
        {
            const char *closing = strchr(p + 2, '}');
            if (closing)
            {
                char var[128] = {0};
                size_t len = (size_t)(closing - (p + 2));
                if (len >= sizeof(var)) len = sizeof(var) - 1;
                memcpy(var, p + 2, len);
                var[len] = '\0';

                const char *env = getenv(var);
                if (env)
                {
                    size_t env_len = strlen(env);
                    if (idx + env_len + 1 > out_cap)
                    {
                        out_cap = (idx + env_len + 1) * 2;
                        char *tmp = (char *)realloc(out, out_cap);
                        if (!tmp)
                        {
                            free(out);
                            return NULL;
                        }
                        out = tmp;
                    }
                    memcpy(out + idx, env, env_len);
                    idx += env_len;
                }
                p = closing + 1;
                continue;
            }
        }
        if (idx + 2 > out_cap)
        {
            out_cap *= 2;
            char *tmp = (char *)realloc(out, out_cap);
            if (!tmp)
            {
                free(out);
                return NULL;
            }
            out = tmp;
        }
        out[idx++] = *p++;
    }
    out[idx] = '\0';
    return out;
}

/* entry_find – returns pointer to entry or NULL ---------------------------- */
static ll_cfg_entry_t *entry_find(ll_cfg_entry_t *head, const char *key)
{
    for (; head; head = head->next)
        if (strcmp(head->key, key) == 0)
            return head;
    return NULL;
}

/* entry_add – creates and prepends a new entry ----------------------------- */
static ll_cfg_entry_t *entry_add(ll_cfg_entry_t **head,
                                 const char       *key,
                                 const char       *value)
{
    ll_cfg_entry_t *e = (ll_cfg_entry_t *)calloc(1, sizeof(*e));
    if (!e) return NULL;

    e->key   = strdup(key);
    e->value = strdup(value);
    if (!e->key || !e->value)
    {
        free(e->key); free(e->value); free(e);
        return NULL;
    }
    e->next  = *head;
    *head    = e;
    return e;
}

/* entries_free – free linked list ----------------------------------------- */
static void entries_free(ll_cfg_entry_t *head)
{
    while (head)
    {
        ll_cfg_entry_t *next = head->next;
        free(head->key);
        free(head->value);
        free(head);
        head = next;
    }
}

/* file_mtime – return modification time ----------------------------------- */
static int file_mtime(const char *path, time_t *out)
{
    struct stat st;
    if (stat(path, &st) != 0) return -1;
    *out = st.st_mtime;
    return 0;
}

/* parse_file – core parsing routine --------------------------------------- */
static int parse_file(ll_cfg_t *cfg, FILE *fp, char **err_out)
{
    char line[4096];
    char section[256] = {0};

    while (fgets(line, sizeof(line), fp))
    {
        char *cursor = trim(line);

        /* Skip blanks/comments */
        if (*cursor == '\0' || *cursor == '#' || *cursor == ';')
            continue;

        /* Section header */
        if (*cursor == '[')
        {
            char *end = strchr(cursor, ']');
            if (!end)
            {
                if (err_out) *err_out = strdup("Unterminated section header");
                return -1;
            }
            size_t len = (size_t)(end - (cursor + 1));
            if (len >= sizeof(section))
            {
                if (err_out) *err_out = strdup("Section name too long");
                return -1;
            }
            memcpy(section, cursor + 1, len);
            section[len] = '\0';
            continue;
        }

        /* Key = value */
        char *eq = strchr(cursor, '=');
        if (!eq)
        {
            if (err_out) *err_out = strdup("Expected '=' delimiter");
            return -1;
        }
        *eq = '\0';
        char *k = trim(cursor);
        char *v = trim(eq + 1);

        /* Remove optional surrounding quotes */
        if ((*v == '"' && v[strlen(v) - 1] == '"') ||
            (*v == '\'' && v[strlen(v) - 1] == '\''))
        {
            v[strlen(v) - 1] = '\0';
            ++v;
        }

        /* Build full key: section.key */
        char full_key[512];
        if (*section)
            snprintf(full_key, sizeof(full_key), "%s.%s", section, k);
        else
            snprintf(full_key, sizeof(full_key), "%s", k);

        /* Expand environment variables */
        char *expanded = env_expand(v);
        if (!expanded)
        {
            if (err_out) *err_out = strdup("Out of memory during env expand");
            return -1;
        }

        /* Insert/update */
        ll_cfg_entry_t *e = entry_find(cfg->entries, full_key);
        if (e)
        {
            free(e->value);
            e->value = expanded;
        }
        else
        {
            if (!entry_add(&cfg->entries, full_key, expanded))
            {
                if (err_out) *err_out = strdup("Out of memory inserting key");
                free(expanded);
                return -1;
            }
            /* value duplicated by entry_add, free the one from env_expand */
            free(expanded);
        }
    }
    return 0;
}

/* --------------------------------------------------------------------------
 *  API implementation
 * -------------------------------------------------------------------------- */

ll_cfg_t *ll_cfg_load(const char *path, char **err_out)
{
    if (err_out) *err_out = NULL;

    FILE *fp = fopen(path, "r");
    if (!fp)
    {
        if (err_out) asprintf(err_out, "Could not open '%s'", path);
        return NULL;
    }

    ll_cfg_t *cfg = (ll_cfg_t *)calloc(1, sizeof(*cfg));
    if (!cfg)
    {
        fclose(fp);
        if (err_out) *err_out = strdup("Out of memory allocating cfg");
        return NULL;
    }
    cfg->path = strdup(path);

    if (!cfg->path || parse_file(cfg, fp, err_out) != 0)
    {
        fclose(fp);
        ll_cfg_free(cfg);
        return NULL;
    }
    fclose(fp);

    if (file_mtime(path, &cfg->mtime) != 0)
    {
        if (err_out) *err_out = strdup("stat() failed");
        ll_cfg_free(cfg);
        return NULL;
    }
    return cfg;
}

int ll_cfg_reload(ll_cfg_t *cfg, char **err_out)
{
    if (!cfg || !cfg->path)
    {
        if (err_out) *err_out = strdup("cfg == NULL");
        return -1;
    }

    time_t current_mtime;
    if (file_mtime(cfg->path, &current_mtime) != 0)
    {
        if (err_out) asprintf(err_out, "stat('%s') failed", cfg->path);
        return -1;
    }

    if (current_mtime <= cfg->mtime)
        return 0; /* No change */

    FILE *fp = fopen(cfg->path, "r");
    if (!fp)
    {
        if (err_out) asprintf(err_out, "Could not open '%s' for reload",
                              cfg->path);
        return -1;
    }

    /* Build a temp config to avoid corrupting the current one on failure */
    ll_cfg_t tmp = {0};
    if (parse_file(&tmp, fp, err_out) != 0)
    {
        fclose(fp);
        entries_free(tmp.entries);
        return -1;
    }
    fclose(fp);

    /* Replace old entries */
    entries_free(cfg->entries);
    cfg->entries = tmp.entries;
    cfg->mtime   = current_mtime;
    return 1; /* Reloaded */
}

/* Internal retrieval helper (const) --------------------------------------- */
static const char *get_raw_value(const ll_cfg_t *cfg, const char *key)
{
    if (!cfg) return NULL;
    ll_cfg_entry_t *e = entry_find(cfg->entries, key);
    return e ? e->value : NULL;
}

const char *ll_cfg_get_str(const ll_cfg_t *cfg,
                           const char      *key,
                           const char      *default_val)
{
    const char *v = get_raw_value(cfg, key);
    return v ? v : default_val;
}

int ll_cfg_get_int(const ll_cfg_t *cfg, const char *key, int default_val)
{
    const char *v = get_raw_value(cfg, key);
    if (!v) return default_val;
    char *end;
    long l = strtol(v, &end, 0);
    if (*end != '\0') return default_val;
    return (int)l;
}

double ll_cfg_get_double(const ll_cfg_t *cfg,
                         const char      *key,
                         double           default_val)
{
    const char *v = get_raw_value(cfg, key);
    if (!v) return default_val;
    char *end;
    double d = strtod(v, &end);
    if (*end != '\0') return default_val;
    return d;
}

bool ll_cfg_get_bool(const ll_cfg_t *cfg, const char *key, bool default_val)
{
    const char *v = get_raw_value(cfg, key);
    if (!v) return default_val;

    if (!strcasecmp(v, "true")  || !strcasecmp(v, "yes") ||
        !strcasecmp(v, "on")    || !strcmp(v, "1"))
        return true;
    if (!strcasecmp(v, "false") || !strcasecmp(v, "no") ||
        !strcasecmp(v, "off")   || !strcmp(v, "0"))
        return false;
    return default_val;
}

int ll_cfg_set(ll_cfg_t *cfg, const char *key, const char *value)
{
    if (!cfg || !key || !value) return -1;
    ll_cfg_entry_t *e = entry_find(cfg->entries, key);
    if (e)
    {
        char *dup = strdup(value);
        if (!dup) return -1;
        free(e->value);
        e->value = dup;
        return 0;
    }
    return entry_add(&cfg->entries, key, value) ? 0 : -1;
}

int ll_cfg_save(const ll_cfg_t *cfg, char **err_out)
{
    if (err_out) *err_out = NULL;
    if (!cfg || !cfg->path)
    {
        if (err_out) *err_out = strdup("cfg == NULL");
        return -1;
    }

    /* Write to temporary file */
    char tmp_path[1024];
    snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", cfg->path);
    FILE *fp = fopen(tmp_path, "w");
    if (!fp)
    {
        if (err_out) asprintf(err_out, "Could not open '%s' for writing",
                              tmp_path);
        return -1;
    }

    /* Serialize entries in insertion order (reverse initial because we used
     * head-insert).  Collect them into array first for deterministic order. */
    size_t count = 0;
    for (ll_cfg_entry_t *e = cfg->entries; e; e = e->next) ++count;
    ll_cfg_entry_t **arr = (ll_cfg_entry_t **)malloc(count * sizeof(*arr));
    if (!arr)
    {
        fclose(fp);
        unlink(tmp_path);
        if (err_out) *err_out = strdup("Out of memory");
        return -1;
    }
    size_t i = count;
    for (ll_cfg_entry_t *e = cfg->entries; e; e = e->next)
        arr[--i] = e; /* reverse */

    /* Write simple key=value lines (section grouping skipped for brevity) */
    for (i = 0; i < count; ++i)
        fprintf(fp, "%s=%s\n", arr[i]->key, arr[i]->value);

    free(arr);

    if (fflush(fp) != 0 || fsync(fileno(fp)) != 0)
    {
        if (err_out) *err_out = strdup("fsync failed");
        fclose(fp);
        unlink(tmp_path);
        return -1;
    }
    fclose(fp);

    /* Atomic replace */
    if (rename(tmp_path, cfg->path) != 0)
    {
        if (err_out) asprintf(err_out, "rename('%s','%s') failed",
                              tmp_path, cfg->path);
        unlink(tmp_path);
        return -1;
    }
    return 0;
}

void ll_cfg_free(ll_cfg_t *cfg)
{
    if (!cfg) return;
    free(cfg->path);
    entries_free(cfg->entries);
    free(cfg);
}

#endif /* LL_CONFIG_PARSER_IMPLEMENTATION */

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* LL_CONFIG_PARSER_H */
