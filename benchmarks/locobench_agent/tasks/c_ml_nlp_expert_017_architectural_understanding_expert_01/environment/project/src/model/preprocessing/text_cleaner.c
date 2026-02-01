/*
 *  LexiLearn Orchestrator
 *  Source  : lexilearn_orchestrator/src/model/preprocessing/text_cleaner.c
 *  Project : ml_nlp (Model Layer)
 *
 *  Description:
 *      Implementation of a production-grade, configurable text-cleaning component
 *      used across the Model layer’s NLP pipelines.  The TextCleaner performs
 *      lower-casing, punctuation stripping, stop-word removal, whitespace
 *      normalization, and rudimentary Unicode down-casting (ASCII-only fallback).
 *
 *      Design goals:
 *          • Fast in-memory stop-word look-ups (binary-search on sorted array)
 *          • Thread-safety (stateless API, no global mutability after init)
 *          • Robust error handling + propagating diagnostics
 *          • Zero external runtime dependencies—only the C standard library
 *
 *  Author  : LexiLearn Core NLP Team
 *  License : Proprietary – All Rights Reserved
 */

#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ──────────────────────────────────────────────────────────────────────────── */
/*                                    API                                      */

#include "text_cleaner.h" /* Public header—exposes TextCleaner API            */

/* ──────────────────────────────────────────────────────────────────────────── */
/*                              Logging utilities                              */

#ifndef TC_LOG_TAG
#    define TC_LOG_TAG "TextCleaner"
#endif

#define TC_LOG_ERR(fmt, ...) \
    fprintf(stderr, "[ERROR] [%s] " fmt "\n", TC_LOG_TAG, ##__VA_ARGS__)
#define TC_LOG_WARN(fmt, ...) \
    fprintf(stderr, "[WARN ] [%s] " fmt "\n", TC_LOG_TAG, ##__VA_ARGS__)
#define TC_LOG_INFO(fmt, ...) \
    fprintf(stdout, "[INFO ] [%s] " fmt "\n", TC_LOG_TAG, ##__VA_ARGS__)

/* ──────────────────────────────────────────────────────────────────────────── */
/*                          Internal helper definitions                        */

#define TC_INITIAL_STOPWORD_CAP 128 /* initial alloc when reading file */

/* Simple macro for freeing and nulling a pointer */
#define TC_SAFE_FREE(p) \
    do {                \
        free(p);        \
        (p) = NULL;     \
    } while (0)

/* Comparator for qsort/bsearch on char* arrays */
static int cmp_cstr(const void *a, const void *b)
{
    const char *sa = *(const char *const *)a;
    const char *sb = *(const char *const *)b;
    return strcmp(sa, sb);
}

/* Trim leading/trailing whitespace in place. Returns new length. */
static size_t str_trim_inplace(char *s)
{
    if (!s)
        return 0;

    char *end = s + strlen(s) - 1;
    char *start = s;

    while (start <= end && isspace((unsigned char)*start))
        ++start;
    while (end >= start && isspace((unsigned char)*end))
        --end;

    size_t len = (size_t)(end >= start ? (end - start + 1) : 0);
    if (start != s && len)
        memmove(s, start, len);
    s[len] = '\0';
    return len;
}

/* Lower-case a string in place (ASCII only). */
static void str_to_lower_inplace(char *s)
{
    for (; s && *s; ++s) {
        *s = (char)tolower((unsigned char)*s);
    }
}

/* Append char to dynamic buffer with realloc growth policy. */
static bool buf_append_char(char **buf, size_t *cap, size_t *len, char c)
{
    if (*len + 1 >= *cap) {
        size_t new_cap = (*cap == 0) ? 64 : (*cap * 2);
        char *tmp = realloc(*buf, new_cap);
        if (!tmp) {
            TC_LOG_ERR("Memory allocation failed while expanding buffer");
            return false;
        }
        *buf  = tmp;
        *cap  = new_cap;
    }
    (*buf)[(*len)++] = c;
    (*buf)[*len]     = '\0';
    return true;
}

/* ──────────────────────────────────────────────────────────────────────────── */
/*                              Stop-word loading                              */

static bool load_stopwords(TextCleaner *tc, const char *filepath)
{
    FILE *fp = fopen(filepath, "r");
    if (!fp) {
        TC_LOG_ERR("Unable to open stop-word file '%s' (%s)", filepath,
                   strerror(errno));
        return false;
    }

    size_t cap   = TC_INITIAL_STOPWORD_CAP;
    size_t count = 0;
    char **tbl   = malloc(sizeof(char *) * cap);
    if (!tbl) {
        fclose(fp);
        TC_LOG_ERR("Out of memory while allocating stop-word table");
        return false;
    }

    char *line   = NULL;
    size_t n     = 0;
    ssize_t read = 0;

    /* POSIX getline loop */
    while ((read = getline(&line, &n, fp)) != -1) {
        if (read <= 1) /* empty line or newline only */
            continue;

        str_trim_inplace(line);
        str_to_lower_inplace(line);

        if (*line == '\0')
            continue;

        /* Duplicate string for storage */
        char *entry = strdup(line);
        if (!entry) {
            TC_LOG_ERR("Memory allocation failed while copying stop-word");
            fclose(fp);
            free(line);
            for (size_t i = 0; i < count; ++i)
                free(tbl[i]);
            free(tbl);
            return false;
        }

        /* Expand array if needed */
        if (count >= cap) {
            size_t new_cap = cap * 2;
            char **tmp     = realloc(tbl, new_cap * sizeof(char *));
            if (!tmp) {
                TC_LOG_ERR("Out of memory while growing stop-word array");
                fclose(fp);
                free(line);
                for (size_t i = 0; i < count; ++i)
                    free(tbl[i]);
                free(tbl);
                return false;
            }
            tbl = tmp;
            cap = new_cap;
        }
        tbl[count++] = entry;
    }

    free(line);
    fclose(fp);

    /* Sort for binary search */
    qsort(tbl, count, sizeof(char *), cmp_cstr);

    tc->stopwords       = tbl;
    tc->stopword_count  = count;
    TC_LOG_INFO("Loaded %" PRIu64 " stop-words from '%s'", (uint64_t)count,
                filepath);
    return true;
}

/* Binary search wrapper: returns true if word is a stop-word. */
static bool is_stopword(const TextCleaner *tc, const char *word)
{
    if (!tc || !word || !*word)
        return false;
    return bsearch(&word, tc->stopwords, tc->stopword_count, sizeof(char *),
                   cmp_cstr) != NULL;
}

/* ──────────────────────────────────────────────────────────────────────────── */
/*                               Public API impl                               */

TextCleaner *tc_create(const char *stopword_file, TcError *err_out)
{
    if (err_out)
        *err_out = TC_OK;

    TextCleaner *tc = calloc(1, sizeof(TextCleaner));
    if (!tc) {
        if (err_out)
            *err_out = TC_ERR_OOM;
        TC_LOG_ERR("Failed to allocate TextCleaner");
        return NULL;
    }

    if (stopword_file && *stopword_file) {
        if (!load_stopwords(tc, stopword_file)) {
            if (err_out)
                *err_out = TC_ERR_IO;
            tc_destroy(tc);
            return NULL;
        }
    }

    return tc;
}

void tc_destroy(TextCleaner *tc)
{
    if (!tc)
        return;

    for (size_t i = 0; i < tc->stopword_count; ++i)
        free(tc->stopwords[i]);
    free(tc->stopwords);
    free(tc);
}

/* Main cleaning routine */
char *tc_clean_text(const TextCleaner *tc, const char *input, TcError *err_out)
{
    if (err_out)
        *err_out = TC_OK;

    if (!input) {
        if (err_out)
            *err_out = TC_ERR_INVALID_ARG;
        return NULL;
    }

    size_t buf_cap  = 0;
    size_t buf_len  = 0;
    char  *out_buf  = NULL;
    bool   last_was_space = true; /* leading spaces suppressed */

    const char *cursor = input;
    char        token[256] = {0};
    size_t      tok_len    = 0;

    /* Tokenize – simple FSM */
    while (true) {
        int c = (unsigned char)*cursor;
        bool flush_token = false;

        if (c == '\0') {
            flush_token = (tok_len > 0);
        } else if (isspace(c) || ispunct(c)) {
            flush_token = (tok_len > 0);
        } else {
            if (tok_len + 1 < sizeof(token)) {
                token[tok_len++] = (char)tolower(c);
                token[tok_len]   = '\0';
            } else {
                /* Token overflow – unlikely for natural language; skip char */
                TC_LOG_WARN("Token length exceeded limit (truncating)");
            }
        }

        if (flush_token) {
            bool is_stop = is_stopword(tc, token);
            if (!is_stop) {
                /* Add space if not first word */
                if (!last_was_space) {
                    if (!buf_append_char(&out_buf, &buf_cap, &buf_len, ' ')) {
                        if (err_out)
                            *err_out = TC_ERR_OOM;
                        TC_SAFE_FREE(out_buf);
                        return NULL;
                    }
                }
                /* Add token */
                for (size_t i = 0; i < tok_len; ++i) {
                    if (!buf_append_char(&out_buf, &buf_cap, &buf_len,
                                         token[i])) {
                        if (err_out)
                            *err_out = TC_ERR_OOM;
                        TC_SAFE_FREE(out_buf);
                        return NULL;
                    }
                }
                last_was_space = false;
            }
            tok_len         = 0;
            token[0]        = '\0';
        }

        if (c == '\0')
            break;

        if (isspace(c) || ispunct(c))
            last_was_space = true;

        ++cursor;
    }

    /* Ensure non-NULL return */
    if (!out_buf) {
        out_buf = strdup("");
        if (!out_buf && err_out)
            *err_out = TC_ERR_OOM;
    }
    return out_buf;
}

/* Convenience one-shot helper (for quick scripts/tests). */
char *tc_clean_text_one_shot(const char *stopword_file, const char *input,
                             TcError *err_out)
{
    TextCleaner *tc = tc_create(stopword_file, err_out);
    if (!tc)
        return NULL;

    char *out = tc_clean_text(tc, input, err_out);
    tc_destroy(tc);
    return out;
}

/* ──────────────────────────────────────────────────────────────────────────── */
/*                                   EOF                                       */
/* ──────────────────────────────────────────────────────────────────────────── */
