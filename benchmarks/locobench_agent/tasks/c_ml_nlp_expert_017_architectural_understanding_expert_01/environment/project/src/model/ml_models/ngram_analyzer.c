/*
 *  LexiLearn MVC Orchestrator – N-Gram Analyzer
 *  -------------------------------------------------
 *  File:        lexilearn_orchestrator/src/model/ml_models/ngram_analyzer.c
 *  Description: Classical n-gram language-model implementation that
 *               conforms to LexiLearn’s Strategy interface so that it can be
 *               swapped in and out at runtime with transformer or hybrid
 *               approaches.  The analyzer supports:
 *                 • Add-k (Laplace) smoothing
 *                 • Model serialization / deserialization for Model Registry
 *                 • Thread-safe training via coarse-grained locking
 *                 • Basic perplexity scoring for drift monitoring
 *
 *  Author:      LexiLearn Core Team
 *  License:     MIT
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <pthread.h>
#include <errno.h>

#include "uthash.h"                /* Third-party single-header hash map       */
#include "logger.h"                /* Project-wide structured logging utility  */
#include "feature_store.h"         /* Shared feature store abstraction         */
#include "model_registry.h"        /* Online model registry / versioning       */
#include "ngram_analyzer.h"        /* Public header for this implementation    */

/*----------------------------------------------------------
 *  Error-handling helpers
 *----------------------------------------------------------*/
#define NG_OK         (0)
#define NG_ERR        (-1)

/* Macro that logs and bails on memory allocation failure. */
#define NG_CHECK_ALLOC(ptr)                                                \
    do {                                                                   \
        if ((ptr) == NULL) {                                               \
            log_error("[NGramAnalyzer] Out of memory at %s:%d",            \
                      __FILE__, __LINE__);                                 \
            return NG_ERR;                                                 \
        }                                                                  \
    } while (0)

/*----------------------------------------------------------
 *  Internal data structures
 *----------------------------------------------------------*/

/* Hash-table entry for n-gram counts. */
typedef struct {
    char            *ngram;   /* key */
    uint64_t         count;
    UT_hash_handle   hh;      /* makes this structure hashable */
} ngram_entry_t;

/* Primary model object (opaque pointer exposed in header). */
struct _NGramAnalyzer {
    int               n;                 /* n-gram size               */
    double            k;                 /* Laplace smoothing factor  */
    ngram_entry_t    *ngrams;            /* n-gram frequency table    */
    ngram_entry_t    *contexts;          /* (n-1)-gram frequency      */
    ngram_entry_t    *vocabulary;        /* Unique token set          */
    pthread_rwlock_t  rwlock;            /* For multi-thread safety   */
    char              version_tag[32];   /* e.g., "v1.0.3-beta"       */
};

/*----------------------------------------------------------
 *  Utility functions
 *----------------------------------------------------------*/

/* Simple whitespace tokenizer; returns #tokens. */
static size_t tokenize(const char  *text,
                       char      ***out_tokens)
{
    if (!text) return 0;

    /* First pass: count tokens */
    size_t count = 0;
    const char *p = text;
    while (*p) {
        while (*p && (*p == ' ' || *p == '\t' || *p == '\n'))
            ++p;
        if (*p) {
            ++count;
            while (*p && (*p != ' ' && *p != '\t' && *p != '\n'))
                ++p;
        }
    }

    /* Allocate array */
    char **tokens = calloc(count, sizeof(char *));
    if (!tokens) return 0;

    /* Second pass: copy tokens */
    size_t idx = 0;
    p = text;
    while (*p) {
        while (*p && (*p == ' ' || *p == '\t' || *p == '\n'))
            ++p;
        if (*p) {
            const char *start = p;
            while (*p && (*p != ' ' && *p != '\t' && *p != '\n'))
                ++p;
            size_t len = p - start;
            tokens[idx] = calloc(len + 1, sizeof(char));
            if (!tokens[idx]) {
                /* clean up */
                for (size_t i = 0; i < idx; ++i) free(tokens[i]);
                free(tokens);
                return 0;
            }
            strncpy(tokens[idx], start, len);
            tokens[idx][len] = '\0';
            ++idx;
        }
    }

    *out_tokens = tokens;
    return count;
}

/* Free token array returned by tokenize(). */
static void free_tokens(char **tokens, size_t n_tokens)
{
    if (!tokens) return;
    for (size_t i = 0; i < n_tokens; ++i) free(tokens[i]);
    free(tokens);
}

/* Concatenate n tokens into a single key string. */
static char *join_tokens(char **tokens, size_t start, size_t n)
{
    size_t len = 0;
    for (size_t i = 0; i < n; ++i)
        len += strlen(tokens[start+i]) + 1; /* +1 for space/terminator */

    char *key = calloc(len, sizeof(char));
    if (!key) return NULL;

    key[0] = '\0';
    for (size_t i = 0; i < n; ++i) {
        strcat(key, tokens[start+i]);
        if (i < n - 1)
            strcat(key, " ");
    }
    return key;
}

/* Increment count in hash table. */
static int incr_count(ngram_entry_t **table, const char *key)
{
    ngram_entry_t *entry = NULL;
    HASH_FIND_STR(*table, key, entry);
    if (!entry) {
        entry = malloc(sizeof(ngram_entry_t));
        NG_CHECK_ALLOC(entry);
        entry->ngram = strdup(key);
        NG_CHECK_ALLOC(entry->ngram);
        entry->count = 1;
        HASH_ADD_KEYPTR(hh, *table, entry->ngram, strlen(entry->ngram), entry);
    } else {
        entry->count += 1;
    }
    return NG_OK;
}

/* Fetch count (returns 0 if not present). */
static uint64_t get_count(ngram_entry_t *table, const char *key)
{
    ngram_entry_t *entry = NULL;
    HASH_FIND_STR(table, key, entry);
    return entry ? entry->count : 0;
}

/* Total size of hash table. */
static uint64_t table_size(ngram_entry_t *table)
{
    return (uint64_t)HASH_COUNT(table);
}

/*----------------------------------------------------------
 *  Public API implementation
 *----------------------------------------------------------*/

NGramAnalyzer *ngram_analyzer_create(int n, double k, const char *version_tag)
{
    if (n < 1 || k < 0.0) {
        log_error("[NGramAnalyzer] Invalid parameters: n=%d k=%f", n, k);
        return NULL;
    }

    NGramAnalyzer *model = calloc(1, sizeof(NGramAnalyzer));
    if (!model) return NULL;

    model->n = n;
    model->k = k;

    if (version_tag)
        strncpy(model->version_tag, version_tag, sizeof(model->version_tag)-1);
    else
        strcpy(model->version_tag, "unversioned");

    pthread_rwlock_init(&model->rwlock, NULL);
    return model;
}

int ngram_analyzer_fit(NGramAnalyzer      *model,
                       const char *const  *corpus,
                       size_t              corpus_sz)
{
    if (!model || !corpus) return NG_ERR;

    /* Exclusive lock during training. */
    pthread_rwlock_wrlock(&model->rwlock);

    for (size_t doc_idx = 0; doc_idx < corpus_sz; ++doc_idx) {

        char **tokens = NULL;
        size_t  t_sz  = tokenize(corpus[doc_idx], &tokens);
        if (t_sz == 0 || !tokens)
            continue; /* empty doc */

        /* Build vocabulary set */
        for (size_t i = 0; i < t_sz; ++i)
            incr_count(&model->vocabulary, tokens[i]);

        /* Increment n-gram and context counts */
        for (size_t i = 0; i + model->n <= t_sz; ++i) {

            char *ngram = join_tokens(tokens, i, model->n);
            char *ctx   = (model->n == 1) ? NULL :
                          join_tokens(tokens, i, model->n - 1);

            if (!ngram || (model->n > 1 && !ctx)) {
                free(ngram);
                free(ctx);
                free_tokens(tokens, t_sz);
                pthread_rwlock_unlock(&model->rwlock);
                return NG_ERR;
            }

            incr_count(&model->ngrams, ngram);
            if (ctx)
                incr_count(&model->contexts, ctx);

            free(ngram);
            free(ctx);
        }
        free_tokens(tokens, t_sz);
    }

    pthread_rwlock_unlock(&model->rwlock);
    log_info("[NGramAnalyzer] Training complete: %zu documents, "
             "%" PRIu64 " unique %d-grams.",
             corpus_sz, table_size(model->ngrams), model->n);
    return NG_OK;
}

/* Calculate log-probability of sentence; returns perplexity if perplexity=1 */
double ngram_analyzer_score(NGramAnalyzer *model,
                            const char    *text,
                            int            return_perplexity)
{
    if (!model || !text) return 0.0;

    pthread_rwlock_rdlock(&model->rwlock);

    char **tokens = NULL;
    size_t t_sz   = tokenize(text, &tokens);
    if (t_sz == 0 || !tokens) {
        pthread_rwlock_unlock(&model->rwlock);
        return 0.0;
    }

    const double V = (double)table_size(model->vocabulary);
    double log_prob = 0.0;
    size_t gram_cnt = 0;

    for (size_t i = 0; i + model->n <= t_sz; ++i) {

        char *ngram = join_tokens(tokens, i, model->n);
        char *ctx   = (model->n == 1) ? NULL :
                      join_tokens(tokens, i, model->n - 1);

        uint64_t num   = get_count(model->ngrams, ngram);
        uint64_t denom = (model->n == 1) ? 0 : get_count(model->contexts, ctx);

        /* Add-k Laplace smoothing */
        double prob = (num + model->k) /
                      ( (model->n == 1 ?
                         (double)table_size(model->vocabulary) :
                         denom + model->k * V) );

        log_prob += log(prob);
        ++gram_cnt;

        free(ngram);
        free(ctx);
    }

    free_tokens(tokens, t_sz);
    pthread_rwlock_unlock(&model->rwlock);

    if (gram_cnt == 0) return 0.0;

    if (return_perplexity)
        return exp( -log_prob / gram_cnt );
    else
        return log_prob;
}

int ngram_analyzer_save(const NGramAnalyzer *model, const char *filepath)
{
    if (!model || !filepath) return NG_ERR;

    pthread_rwlock_rdlock((pthread_rwlock_t *)&model->rwlock);

    FILE *fp = fopen(filepath, "wb");
    if (!fp) {
        log_error("[NGramAnalyzer] Unable to write %s: %s",
                  filepath, strerror(errno));
        pthread_rwlock_unlock((pthread_rwlock_t *)&model->rwlock);
        return NG_ERR;
    }

    /* Header: n, k, version tag length + string */
    fwrite(&model->n, sizeof(int), 1, fp);
    fwrite(&model->k, sizeof(double), 1, fp);

    uint32_t tag_len = (uint32_t)strlen(model->version_tag);
    fwrite(&tag_len, sizeof(uint32_t), 1, fp);
    fwrite(model->version_tag, sizeof(char), tag_len, fp);

    /* Dump table sizes */
    uint64_t ngram_sz   = table_size(model->ngrams);
    uint64_t ctx_sz     = table_size(model->contexts);
    uint64_t vocab_sz   = table_size(model->vocabulary);

    fwrite(&ngram_sz, sizeof(uint64_t), 1, fp);
    fwrite(&ctx_sz,   sizeof(uint64_t), 1, fp);
    fwrite(&vocab_sz, sizeof(uint64_t), 1, fp);

    /* Serialize n-gram counts */
    for (ngram_entry_t *e = model->ngrams; e; e = e->hh.next) {
        uint32_t keylen = (uint32_t)strlen(e->ngram);
        fwrite(&keylen, sizeof(uint32_t), 1, fp);
        fwrite(e->ngram, sizeof(char), keylen, fp);
        fwrite(&e->count, sizeof(uint64_t), 1, fp);
    }

    /* Context counts */
    for (ngram_entry_t *e = model->contexts; e; e = e->hh.next) {
        uint32_t keylen = (uint32_t)strlen(e->ngram);
        fwrite(&keylen, sizeof(uint32_t), 1, fp);
        fwrite(e->ngram, sizeof(char), keylen, fp);
        fwrite(&e->count, sizeof(uint64_t), 1, fp);
    }

    /* Vocabulary */
    for (ngram_entry_t *e = model->vocabulary; e; e = e->hh.next) {
        uint32_t keylen = (uint32_t)strlen(e->ngram);
        fwrite(&keylen, sizeof(uint32_t), 1, fp);
        fwrite(e->ngram, sizeof(char), keylen, fp);
        fwrite(&e->count, sizeof(uint64_t), 1, fp);
    }

    fclose(fp);
    pthread_rwlock_unlock((pthread_rwlock_t *)&model->rwlock);

    log_info("[NGramAnalyzer] Model persisted to %s (%" PRIu64 " n-grams).",
             filepath, (uint64_t)ngram_sz);
    return NG_OK;
}

NGramAnalyzer *ngram_analyzer_load(const char *filepath)
{
    if (!filepath) return NULL;

    FILE *fp = fopen(filepath, "rb");
    if (!fp) {
        log_error("[NGramAnalyzer] Unable to read %s: %s",
                  filepath, strerror(errno));
        return NULL;
    }

    int n; double k;
    fread(&n, sizeof(int), 1, fp);
    fread(&k, sizeof(double), 1, fp);

    uint32_t tag_len;
    fread(&tag_len, sizeof(uint32_t), 1, fp);

    char tag[33] = {0};
    fread(tag, sizeof(char), tag_len, fp);
    tag[tag_len] = '\0';

    NGramAnalyzer *model = ngram_analyzer_create(n, k, tag);
    if (!model) { fclose(fp); return NULL; }

    uint64_t ngram_sz, ctx_sz, vocab_sz;
    fread(&ngram_sz, sizeof(uint64_t), 1, fp);
    fread(&ctx_sz,   sizeof(uint64_t), 1, fp);
    fread(&vocab_sz, sizeof(uint64_t), 1, fp);

    char *keybuf = NULL;
    uint32_t keylen;
    uint64_t count;

    /* Load n-grams */
    for (uint64_t i = 0; i < ngram_sz; ++i) {
        fread(&keylen, sizeof(uint32_t), 1, fp);
        keybuf = calloc(keylen + 1, sizeof(char));
        fread(keybuf, sizeof(char), keylen, fp);
        keybuf[keylen] = '\0';
        fread(&count, sizeof(uint64_t), 1, fp);

        ngram_entry_t *entry = malloc(sizeof(ngram_entry_t));
        entry->ngram = keybuf;
        entry->count = count;
        HASH_ADD_KEYPTR(hh, model->ngrams, entry->ngram,
                        strlen(entry->ngram), entry);
    }

    /* Contexts */
    for (uint64_t i = 0; i < ctx_sz; ++i) {
        fread(&keylen, sizeof(uint32_t), 1, fp);
        keybuf = calloc(keylen + 1, sizeof(char));
        fread(keybuf, sizeof(char), keylen, fp);
        keybuf[keylen] = '\0';
        fread(&count, sizeof(uint64_t), 1, fp);

        ngram_entry_t *entry = malloc(sizeof(ngram_entry_t));
        entry->ngram = keybuf;
        entry->count = count;
        HASH_ADD_KEYPTR(hh, model->contexts, entry->ngram,
                        strlen(entry->ngram), entry);
    }

    /* Vocabulary */
    for (uint64_t i = 0; i < vocab_sz; ++i) {
        fread(&keylen, sizeof(uint32_t), 1, fp);
        keybuf = calloc(keylen + 1, sizeof(char));
        fread(keybuf, sizeof(char), keylen, fp);
        keybuf[keylen] = '\0';
        fread(&count, sizeof(uint64_t), 1, fp);

        ngram_entry_t *entry = malloc(sizeof(ngram_entry_t));
        entry->ngram = keybuf;
        entry->count = count;
        HASH_ADD_KEYPTR(hh, model->vocabulary, entry->ngram,
                        strlen(entry->ngram), entry);
    }

    fclose(fp);
    log_info("[NGramAnalyzer] Model loaded from %s (n=%d, k=%.3f).",
             filepath, n, k);
    return model;
}

void ngram_analyzer_destroy(NGramAnalyzer *model)
{
    if (!model) return;

    pthread_rwlock_wrlock(&model->rwlock);

    ngram_entry_t *cur, *tmp;
    HASH_ITER(hh, model->ngrams, cur, tmp) {
        HASH_DEL(model->ngrams, cur);
        free(cur->ngram);
        free(cur);
    }
    HASH_ITER(hh, model->contexts, cur, tmp) {
        HASH_DEL(model->contexts, cur);
        free(cur->ngram);
        free(cur);
    }
    HASH_ITER(hh, model->vocabulary, cur, tmp) {
        HASH_DEL(model->vocabulary, cur);
        free(cur->ngram);
        free(cur);
    }
    pthread_rwlock_unlock(&model->rwlock);
    pthread_rwlock_destroy(&model->rwlock);
    free(model);
}

/*----------------------------------------------------------
 *  Strategy Pattern registration helper
 *----------------------------------------------------------*/

static int register_with_registry(void)
{
    ModelDescriptor desc = {
        .name            = "ClassicNGramAnalyzer",
        .version         = "1.0.0",
        .create_fn       = (void *(*)(void))ngram_analyzer_create,
        .fit_fn          = (int (*)(void *, const char *const *, size_t))
                           ngram_analyzer_fit,
        .score_fn        = (double (*)(void *, const char *, int))
                           ngram_analyzer_score,
        .save_fn         = (int (*)(const void *, const char *))
                           ngram_analyzer_save,
        .load_fn         = (void *(*)(const char *))
                           ngram_analyzer_load,
        .destroy_fn      = (void (*)(void *))ngram_analyzer_destroy
    };
    return model_registry_register(&desc);
}

/* Run once when shared object is loaded. */
__attribute__((constructor))
static void on_load(void)
{
    if (register_with_registry() == NG_OK) {
        log_info("[NGramAnalyzer] Registered with model registry.");
    } else {
        log_error("[NGramAnalyzer] Failed to register with model registry.");
    }
}