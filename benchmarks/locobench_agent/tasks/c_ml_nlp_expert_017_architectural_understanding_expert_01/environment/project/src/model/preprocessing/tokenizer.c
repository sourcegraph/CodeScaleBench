/**
 * LexiLearn Orchestrator – Tokenizer
 *
 * File path: lexilearn_orchestrator/src/model/preprocessing/tokenizer.c
 *
 * Description:
 *   Production-ready, highly configurable tokenizer used by the Model layer
 *   during NLP data-preprocessing.  The implementation focuses on robustness,
 *   extensibility, and performance while keeping external dependencies light.
 *
 *   Features
 *     • UTF-8 aware, whitespace/punctuation based tokenisation
 *     • Optional lower-casing
 *     • Configurable punctuation stripping & number preservation
 *     • Pluggable stop-word filtering backed by a fast hash-set (uthash)
 *     • Clear memory-management semantics – all heap allocations owned
 *       either by the tokenizer instance or the caller.
 *     • Thorough error handling with meaningful return codes
 *
 * Copyright:
 *   © 2024 LexiLearn. All rights reserved.
 *
 * License:
 *   Proprietary – for academic/educational use at licensed institutions only.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <ctype.h>
#include <stdint.h>
#include <errno.h>

#include "tokenizer.h"      /* Public API                                       */
#include "uthash.h"         /* Single-file hash-table – https://troydhanson.github.io/uthash/ */

/* -------------------------------------------------------------------------- */
/* Internal macros & helpers                                                  */
/* -------------------------------------------------------------------------- */

#define TK_SUCCESS              (0)
#define TK_ERR_OOM              (-1)
#define TK_ERR_IO               (-2)
#define TK_ERR_INVALID_UTF8     (-3)

/* Simple logger – can later be wired to the project-wide logging facility */
#ifndef TK_LOG
#   define TK_LOG(fmt, ...)  fprintf(stderr, "[TOKENIZER] " fmt "\n", ##__VA_ARGS__)
#endif

#define CHECK_ALLOCATION(ptr)                           \
    do {                                                \
        if ((ptr) == NULL) {                            \
            TK_LOG("Out-of-memory at %s:%d",            \
                   __FILE__, __LINE__);                 \
            return TK_ERR_OOM;                          \
        }                                               \
    } while (0)

/* -------------------------------------------------------------------------- */
/* UTF-8 decoding utilities                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Decode a single UTF-8 codepoint.
 *
 * @param s          Pointer to the first byte of a UTF-8 sequence.
 * @param cp_out     Output pointer for the decoded Unicode codepoint.
 * @return           Number of bytes consumed (>0) or -1 on malformed input.
 */
static int
utf8_decode(const char *s, uint32_t *cp_out)
{
    const unsigned char *u = (const unsigned char *)s;

    if (u[0] < 0x80) {              /* ASCII fast path */
        *cp_out = u[0];
        return 1;
    }
    if ((u[0] & 0xe0) == 0xc0) {    /* Two byte seq */
        if ((u[1] & 0xc0) != 0x80)
            return -1;
        *cp_out = ((u[0] & 0x1f) << 6) | (u[1] & 0x3f);
        return 2;
    }
    if ((u[0] & 0xf0) == 0xe0) {    /* Three byte seq */
        if ((u[1] & 0xc0) != 0x80 || (u[2] & 0xc0) != 0x80)
            return -1;
        *cp_out = ((u[0] & 0x0f) << 12) |
                  ((u[1] & 0x3f) << 6) |
                  (u[2] & 0x3f);
        return 3;
    }
    if ((u[0] & 0xf8) == 0xf0) {    /* Four byte seq */
        if ((u[1] & 0xc0) != 0x80 || (u[2] & 0xc0) != 0x80 ||
            (u[3] & 0xc0) != 0x80)
            return -1;
        *cp_out = ((u[0] & 0x07) << 18) |
                  ((u[1] & 0x3f) << 12) |
                  ((u[2] & 0x3f) << 6) |
                  (u[3] & 0x3f);
        return 4;
    }
    return -1;                      /* Invalid leading byte */
}

/* -------------------------------------------------------------------------- */
/* Character classification helpers                                           */
/* -------------------------------------------------------------------------- */

/* We only treat ASCII punctuation specially; other codepoints are handled
 * with a simple heuristic (non-alnum => punctuation) to avoid heavy deps.   */
static inline bool
is_unicode_whitespace(uint32_t cp)
{
    /* ASCII whitespace */
    if (cp == ' '  || cp == '\n' || cp == '\t' || cp == '\r' || cp == '\f' ||
        cp == '\v')
        return true;

    /* Unicode category Zs – a minimal, non-exhaustive subset */
    return (cp == 0x00A0 /* NBSP */ || cp == 0x1680 || cp == 0x2000 ||
            cp == 0x2001 || cp == 0x2002 || cp == 0x2003 || cp == 0x2004 ||
            cp == 0x2005 || cp == 0x2006 || cp == 0x2007 || cp == 0x2008 ||
            cp == 0x2009 || cp == 0x200A || cp == 0x202F || cp == 0x205F ||
            cp == 0x3000);
}

static inline bool
is_unicode_punctuation(uint32_t cp)
{
    /* Basic ASCII punctuation */
    if (cp < 128 && ispunct((int)cp))
        return true;

    /* Common Unicode punctuation, highly abbreviated list */
    return (cp >= 0x2010 && cp <= 0x2027)   /* dashes, quotes, bullets, … */
         || (cp >= 0x3001 && cp <= 0x303F); /* CJK punctuation            */
}

/* -------------------------------------------------------------------------- */
/* Stop-word hash-set                                                         */
/* -------------------------------------------------------------------------- */

typedef struct stopword_entry_s
{
    char            *word;   /* lower-case UTF-8 token                        */
    UT_hash_handle   hh;
} stopword_entry_t;

static int
stopword_add(stopword_entry_t **table, const char *word)
{
    stopword_entry_t *e = NULL;
    HASH_FIND_STR(*table, word, e);
    if (e) return TK_SUCCESS;   /* already present */

    e = (stopword_entry_t *)calloc(1, sizeof(*e));
    CHECK_ALLOCATION(e);

    e->word = strdup(word);
    CHECK_ALLOCATION(e->word);

    HASH_ADD_KEYPTR(hh, *table, e->word, strlen(e->word), e);
    return TK_SUCCESS;
}

static bool
stopword_contains(stopword_entry_t *table, const char *word)
{
    stopword_entry_t *e = NULL;
    HASH_FIND_STR(table, word, e);
    return (e != NULL);
}

static void
stopword_free_all(stopword_entry_t **table)
{
    stopword_entry_t *cur, *tmp;
    HASH_ITER(hh, *table, cur, tmp) {
        HASH_DEL(*table, cur);
        free(cur->word);
        free(cur);
    }
}

/* -------------------------------------------------------------------------- */
/* Tokenizer object                                                           */
/* -------------------------------------------------------------------------- */

struct tokenizer_s
{
    tokenizer_config_t  cfg;
    stopword_entry_t   *stopwords;
};

/* -------------------------------------------------------------------------- */
/* Stop-word loading                                                          */
/* -------------------------------------------------------------------------- */

static int
load_stopwords_from_file(tokenizer_t *tk, const char *path)
{
    FILE *fp = fopen(path, "r");
    if (!fp) {
        TK_LOG("Failed to open stop-word file '%s': %s", path, strerror(errno));
        return TK_ERR_IO;
    }

    char *line   = NULL;
    size_t len   = 0;
    ssize_t read = 0;
    int rc       = TK_SUCCESS;

    while ((read = getline(&line, &len, fp)) != -1) {
        /* Strip newline & surrounding whitespace */
        while (read > 0 && (line[read-1] == '\n' || line[read-1] == '\r' ||
                            line[read-1] == ' '  || line[read-1] == '\t'))
            line[--read] = '\0';
        if (read == 0) continue;

        /* Force lower-case for look-ups */
        for (ssize_t i = 0; i < read; ++i)
            line[i] = (char)tolower((unsigned char)line[i]);

        rc = stopword_add(&tk->stopwords, line);
        if (rc != TK_SUCCESS)
            break;
    }

    if (line) free(line);
    fclose(fp);
    return rc;
}

/* -------------------------------------------------------------------------- */
/* Public API Implementation                                                  */
/* -------------------------------------------------------------------------- */

tokenizer_t *
tokenizer_create(const tokenizer_config_t *config)
{
    tokenizer_t *tk = (tokenizer_t *)calloc(1, sizeof(*tk));
    if (!tk) {
        TK_LOG("Out-of-memory creating tokenizer");
        return NULL;
    }
    /* Copy user-supplied config; ensure sane defaults for optional fields */
    tk->cfg = *config;
    if (!tk->cfg.language)
        tk->cfg.language = "en";

    /* Load stop-words (optional) */
    if (tk->cfg.stopword_path) {
        if (load_stopwords_from_file(tk, tk->cfg.stopword_path) != TK_SUCCESS) {
            tokenizer_destroy(tk);
            return NULL;
        }
    }

    return tk;
}

void
tokenizer_destroy(tokenizer_t *tk)
{
    if (!tk) return;
    stopword_free_all(&tk->stopwords);
    free(tk);
}

/**
 * Tokenise input UTF-8 text.
 *
 * Memory semantics: The caller owns the returned `tokens` array as well as each
 * individual string.  Use tokenizer_free_tokens() to release resources.
 *
 * @param tk          Tokenizer instance
 * @param text        Null-terminated UTF-8 input string
 * @param out_tokens  (out) Pointer to dynamically allocated token array
 * @param out_count   (out) Number of returned tokens
 * @return            TK_SUCCESS on success or error code (<0)
 */
int
tokenizer_tokenize(tokenizer_t   *tk,
                   const char    *text,
                   char        ***out_tokens,
                   size_t        *out_count)
{
    if (!tk || !text || !out_tokens || !out_count)
        return TK_ERR_IO;

    size_t capacity = 32;
    size_t count    = 0;
    char **tokens   = (char **)malloc(capacity * sizeof(char *));
    CHECK_ALLOCATION(tokens);

    const char *p = text;
    char        buf[256];   /* Temporary in-place buffer for small tokens */
    size_t      buf_len = 0;

    while (*p) {
        uint32_t cp;
        int bytes = utf8_decode(p, &cp);
        if (bytes < 0) {
            TK_LOG("Invalid UTF-8 sequence detected");
            tokenizer_free_tokens(tokens, count);
            return TK_ERR_INVALID_UTF8;
        }

        bool is_ws  = is_unicode_whitespace(cp);
        bool is_pun = is_unicode_punctuation(cp);

        /* Determine if the codepoint should delimit a token */
        if (is_ws || (is_pun && tk->cfg.remove_punctuation)) {
            /* Finalise current token, if any */
            if (buf_len > 0) {
                buf[buf_len] = '\0';

                /* Lowercase if configured (ASCII only) */
                if (tk->cfg.lowercase) {
                    for (size_t i = 0; i < buf_len; ++i)
                        buf[i] = (char)tolower((unsigned char)buf[i]);
                }

                /* Stop-word filtering */
                if (!stopword_contains(tk->stopwords, buf)) {
                    if (count == capacity) {
                        capacity *= 2;
                        char **tmp = (char **)realloc(tokens,
                                                      capacity * sizeof(char *));
                        CHECK_ALLOCATION(tmp);
                        tokens = tmp;
                    }
                    tokens[count++] = strdup(buf);
                    CHECK_ALLOCATION(tokens[count-1]);
                }
                buf_len = 0;
            }
            p += bytes;
            continue;   /* Skip delimiter */
        }

        /* If numbers should be removed, treat as delimiter */
        if (!tk->cfg.preserve_numbers && isdigit((int)cp)) {
            if (buf_len > 0) {
                buf[buf_len] = '\0';

                if (tk->cfg.lowercase) {
                    for (size_t i = 0; i < buf_len; ++i)
                        buf[i] = (char)tolower((unsigned char)buf[i]);
                }

                if (!stopword_contains(tk->stopwords, buf)) {
                    if (count == capacity) {
                        capacity *= 2;
                        char **tmp = (char **)realloc(tokens,
                                                      capacity * sizeof(char *));
                        CHECK_ALLOCATION(tmp);
                        tokens = tmp;
                    }
                    tokens[count++] = strdup(buf);
                    CHECK_ALLOCATION(tokens[count-1]);
                }
                buf_len = 0;
            }
            p += bytes;
            continue;
        }

        /* Append bytes to buffer */
        if (buf_len + bytes >= sizeof(buf)-1) {
            /* Token too long for stack buffer – fall back to heap */
            char *heap_buf = (char *)malloc(buf_len + bytes + 1);
            CHECK_ALLOCATION(heap_buf);
            memcpy(heap_buf, buf, buf_len);
            memcpy(heap_buf + buf_len, p, bytes);
            heap_buf[buf_len + bytes] = '\0';

            /* Consume any remaining chars until delimiter */
            p += bytes;
            while (*p) {
                uint32_t cp2; int b2 = utf8_decode(p, &cp2);
                if (b2 < 0) {
                    free(heap_buf);
                    tokenizer_free_tokens(tokens, count);
                    TK_LOG("Invalid UTF-8 sequence in oversized token");
                    return TK_ERR_INVALID_UTF8;
                }
                if (is_unicode_whitespace(cp2) ||
                    (is_unicode_punctuation(cp2) && tk->cfg.remove_punctuation) ||
                    (!tk->cfg.preserve_numbers && isdigit((int)cp2)))
                    break;

                heap_buf = (char *)realloc(heap_buf, strlen(heap_buf) + b2 + 1);
                CHECK_ALLOCATION(heap_buf);
                strncat(heap_buf, p, b2);
                p += b2;
            }

            /* Apply lowercase (ASCII only) */
            if (tk->cfg.lowercase) {
                for (char *c = heap_buf; *c; ++c)
                    *c = (char)tolower((unsigned char)*c);
            }

            if (!stopword_contains(tk->stopwords, heap_buf)) {
                if (count == capacity) {
                    capacity *= 2;
                    char **tmp = (char **)realloc(tokens,
                                                  capacity * sizeof(char *));
                    CHECK_ALLOCATION(tmp);
                    tokens = tmp;
                }
                tokens[count++] = heap_buf;
            } else {
                free(heap_buf);
            }
            buf_len = 0;
            continue;
        }

        /* Normal path: append bytes to buffer */
        memcpy(&buf[buf_len], p, bytes);
        buf_len += bytes;
        p       += bytes;
    }

    /* Final token at EOF */
    if (buf_len > 0) {
        buf[buf_len] = '\0';
        if (tk->cfg.lowercase) {
            for (size_t i = 0; i < buf_len; ++i)
                buf[i] = (char)tolower((unsigned char)buf[i]);
        }
        if (!stopword_contains(tk->stopwords, buf)) {
            if (count == capacity) {
                capacity += 1;
                char **tmp = (char **)realloc(tokens,
                                              capacity * sizeof(char *));
                CHECK_ALLOCATION(tmp);
                tokens = tmp;
            }
            tokens[count++] = strdup(buf);
            CHECK_ALLOCATION(tokens[count-1]);
        }
    }

    *out_tokens = tokens;
    *out_count  = count;
    return TK_SUCCESS;
}

void
tokenizer_free_tokens(char **tokens, size_t count)
{
    if (!tokens) return;
    for (size_t i = 0; i < count; ++i)
        free(tokens[i]);
    free(tokens);
}

/* -------------------------------------------------------------------------- */
/* Debug/CLI harness (optional, compiled out in release builds)               */
/* -------------------------------------------------------------------------- */

#ifdef TOKENIZER_STANDALONE

static void
print_tokens(char **tokens, size_t count)
{
    printf("Tokens (%zu):\n", count);
    for (size_t i = 0; i < count; ++i)
        printf("  [%zu] \"%s\"\n", i, tokens[i]);
}

int main(int argc, char *argv[])
{
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <text> [stopwords.txt]\n", argv[0]);
        return EXIT_FAILURE;
    }

    tokenizer_config_t cfg = {
        .lowercase          = true,
        .remove_punctuation = true,
        .preserve_numbers   = false,
        .language           = "en",
        .stopword_path      = (argc >= 3 ? argv[2] : NULL)
    };

    tokenizer_t *tk = tokenizer_create(&cfg);
    if (!tk) return EXIT_FAILURE;

    char **tokens  = NULL;
    size_t count   = 0;
    int rc         = tokenizer_tokenize(tk, argv[1], &tokens, &count);

    if (rc == TK_SUCCESS) {
        print_tokens(tokens, count);
        tokenizer_free_tokens(tokens, count);
    } else {
        TK_LOG("Tokenization failed with code %d", rc);
    }

    tokenizer_destroy(tk);
    return rc == TK_SUCCESS ? EXIT_SUCCESS : EXIT_FAILURE;
}

#endif /* TOKENIZER_STANDALONE */

/* -------------------------------------------------------------------------- */
/* End of File                                                                */
/* -------------------------------------------------------------------------- */
