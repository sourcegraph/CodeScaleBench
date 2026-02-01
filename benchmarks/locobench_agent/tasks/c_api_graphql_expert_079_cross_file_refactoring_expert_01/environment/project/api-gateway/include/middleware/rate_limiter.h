#ifndef SYNESTHETIC_CANVAS_RATE_LIMITER_H
#define SYNESTHETIC_CANVAS_RATE_LIMITER_H
/*
 *  SynestheticCanvas – API Gateway Middleware
 *  ==========================================
 *  Token-bucket rate-limiter (thread-safe, header-only)
 *
 *  This module implements a production-grade, per-consumer token-bucket rate
 *  limiter intended for use inside the SynestheticCanvas API-Gateway.  The
 *  gateway calls `sc_rate_limiter_allow()` as early as possible in the request
 *  path to decide whether a request should be processed or rejected with
 *  HTTP/GraphQL error `429 Too Many Requests`.
 *
 *  Design goals
 *  ------------
 *  •   No external dependencies beyond the C/POSIX runtime.
 *  •   Header-only (define SC_RATE_LIMITER_IMPLEMENTATION in exactly ONE
 *      translation unit to emit the implementation).
 *  •   O(1) insert/lookup by consumer key (open-addressing hash table).
 *  •   Safe for concurrent use from multiple threads (single global mutex).
 *  •   Introspection helpers for monitoring/exporter subsystems.
 *
 *  Usage
 *  -----
 *      #define SC_RATE_LIMITER_IMPLEMENTATION
 *      #include "middleware/rate_limiter.h"
 *
 *      // …
 *      sc_rate_limiter_t *rl = NULL;
 *      sc_rate_limiter_create(&rl, 120, 60);   // 120 tokens, refill 60/s
 *
 *      if (sc_rate_limiter_allow(rl, client_id)) {
 *          // handle request
 *      } else {
 *          // respond 429
 *      }
 *
 *  License
 *  -------
 *  MIT — See end of file.
 */

#include <stdint.h>
#include <stdbool.h>
#include <time.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Forward-declared opaque structure. */
typedef struct sc_rate_limiter sc_rate_limiter_t;

/*
 *  sc_rate_limiter_create
 *  ----------------------
 *  Create a new rate-limiter instance.
 *
 *  Parameters
 *      out_rl          Pointer to the location where the newly created handle
 *                      will be stored.
 *      capacity        Maximum number of tokens the bucket can hold.
 *      refill_rate     How many tokens are added per second.
 *
 *  Returns
 *      0  on success,
 *     -1  on error (errno will be set).
 */
int sc_rate_limiter_create(sc_rate_limiter_t **out_rl,
                           uint32_t             capacity,
                           uint32_t             refill_rate);

/*
 *  sc_rate_limiter_destroy
 *  -----------------------
 *  Release all resources held by a rate-limiter instance.
 */
void sc_rate_limiter_destroy(sc_rate_limiter_t *rl);

/*
 *  sc_rate_limiter_allow
 *  ---------------------
 *  Attempt to consume one token for the given client key.
 *
 *  Parameters
 *      rl              Rate-limiter instance.
 *      client_key      Zero-terminated identifier for the consumer
 *                      (e.g. API key, user ID, IP address).
 *
 *  Returns
 *      true  if a token was successfully consumed (request may proceed),
 *      false if the bucket is empty (request must be rejected).
 */
bool sc_rate_limiter_allow(sc_rate_limiter_t *rl,
                           const char        *client_key);

/*
 *  sc_rate_limiter_set_limit
 *  -------------------------
 *  Override limits for a specific consumer.  If the consumer already exists,
 *  its bucket will be resized; otherwise a new bucket is created.
 *
 *  Passing NULL for `client_key` changes the default configuration that will
 *  be applied to future unknown consumers.
 *
 *  Returns 0 on success, -1 on error (errno is set).
 */
int sc_rate_limiter_set_limit(sc_rate_limiter_t *rl,
                              const char        *client_key,
                              uint32_t           capacity,
                              uint32_t           refill_rate);

/*
 *  sc_rate_limiter_stats
 *  ---------------------
 *  Runtime metrics for monitoring/exporting.
 */
typedef struct
{
    uint32_t capacity;     /* Configured bucket size.           */
    uint32_t tokens;       /* Currently available tokens.       */
    uint32_t refill_rate;  /* Tokens per second.                */
} sc_rate_limiter_stats_t;

/*
 *  sc_rate_limiter_get_stats
 *  -------------------------
 *  Fetch statistics for a specific consumer bucket.  If the consumer does not
 *  exist, ENOENT is returned.
 *
 *  Returns 0 on success, -1 on error (errno is set).
 */
int sc_rate_limiter_get_stats(sc_rate_limiter_t       *rl,
                              const char              *client_key,
                              sc_rate_limiter_stats_t *out_stats);

#ifdef __cplusplus
}   /* extern "C" */
#endif


/* ========================================================================== */
/* ==  Implementation section – include once in exactly ONE compilation unit */
#ifdef SC_RATE_LIMITER_IMPLEMENTATION
/* ========================================================================== */

#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L   /* clock_gettime, strdup, … */
#endif

#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>

/* -------------------------------------------------------------------------- */
/*  Internal helpers                                                          */
/* -------------------------------------------------------------------------- */

static inline uint64_t _sc_timespec_to_ns(const struct timespec *ts)
{
    return (uint64_t)ts->tv_sec * 1000000000ull + (uint64_t)ts->tv_nsec;
}

static inline void _sc_timespec_now(struct timespec *ts)
{
    clock_gettime(CLOCK_MONOTONIC, ts);
}

static inline uint32_t _sc_min_u32(uint32_t a, uint32_t b)
{
    return a < b ? a : b;
}

/* -------------------------------------------------------------------------- */
/*  Very small open-addressing hash table for strings ➜ bucket.               */
/*  Because we want a single-header solution, we embed this purpose-built     */
/*  associative array (FNV-1a hash + linear probing).  Keys are immutable     */
/*  after insertion, which simplifies deletion (tombstones are never reused   */
/*  because consumer buckets rarely disappear during the lifetime of the      */
/*  process).                                                                 */
/* -------------------------------------------------------------------------- */

#define _SC_HASH_INITIAL_CAPACITY  1024u
#define _SC_HASH_LOAD_FACTOR_NUM   7u
#define _SC_HASH_LOAD_FACTOR_DEN   10u    /* 0.7 */

/* Forward declare per-consumer bucket struct (defined later). */
typedef struct _sc_consumer_bucket _sc_consumer_bucket_t;

typedef struct
{
    char                *key;       /* NULL if slot is empty                     */
    _sc_consumer_bucket_t *value;   /* Pointer into the allocator arena         */
} _sc_hash_slot_t;

typedef struct
{
    _sc_hash_slot_t *slots;
    uint32_t         capacity;
    uint32_t         count;
} _sc_hash_t;

/* 32-bit FNV-1a */
static inline uint32_t _sc_fnv1a(const char *s)
{
    uint32_t h = 2166136261u;
    while (*s) {
        h ^= (uint8_t)*s++;
        h *= 16777619u;
    }
    return h;
}

static int _sc_hash_init(_sc_hash_t *ht)
{
    ht->capacity = _SC_HASH_INITIAL_CAPACITY;
    ht->count    = 0;
    ht->slots    = calloc(ht->capacity, sizeof(*ht->slots));
    if (!ht->slots) return -1;
    return 0;
}

static void _sc_hash_destroy(_sc_hash_t *ht)
{
    for (uint32_t i = 0; i < ht->capacity; ++i) {
        free(ht->slots[i].key);
        /* buckets are freed en-masse later */
    }
    free(ht->slots);
    ht->slots = NULL;
    ht->capacity = ht->count = 0;
}

static int _sc_hash_resize(_sc_hash_t *ht, uint32_t new_cap)
{
    _sc_hash_slot_t *old_slots = ht->slots;
    uint32_t         old_cap   = ht->capacity;

    ht->slots = calloc(new_cap, sizeof(*ht->slots));
    if (!ht->slots) {
        ht->slots = old_slots; /* keep original */
        return -1;
    }
    ht->capacity = new_cap;
    ht->count    = 0;

    for (uint32_t i = 0; i < old_cap; ++i) {
        if (!old_slots[i].key) continue;
        /* re-insert */
        uint32_t idx = _sc_fnv1a(old_slots[i].key) % ht->capacity;
        while (ht->slots[idx].key) idx = (idx + 1) % ht->capacity;
        ht->slots[idx] = old_slots[i];
        ++ht->count;
    }
    free(old_slots);
    return 0;
}

static _sc_consumer_bucket_t *_sc_hash_get(_sc_hash_t *ht, const char *key)
{
    if (!ht->slots) return NULL;
    uint32_t idx = _sc_fnv1a(key) % ht->capacity;
    for (;;) {
        if (!ht->slots[idx].key) return NULL;                 /* not found */
        if (strcmp(ht->slots[idx].key, key) == 0) return ht->slots[idx].value;
        idx = (idx + 1) % ht->capacity;
    }
}

static int _sc_hash_put(_sc_hash_t *ht,
                        const char *key,
                        _sc_consumer_bucket_t *value)
{
    if ((uint64_t)(ht->count + 1) * _SC_HASH_LOAD_FACTOR_DEN >
        (uint64_t)ht->capacity * _SC_HASH_LOAD_FACTOR_NUM) {
        /* grow table */
        if (_sc_hash_resize(ht, ht->capacity * 2) != 0) return -1;
    }

    uint32_t idx = _sc_fnv1a(key) % ht->capacity;
    while (ht->slots[idx].key) {
        if (strcmp(ht->slots[idx].key, key) == 0) break;  /* update existing */
        idx = (idx + 1) % ht->capacity;
    }

    if (!ht->slots[idx].key) {            /* fresh entry */
        ht->slots[idx].key   = strdup(key);
        if (!ht->slots[idx].key) return -1;
        ht->slots[idx].value = value;
        ++ht->count;
    } else {
        ht->slots[idx].value = value;     /* overwrite */
    }
    return 0;
}

/* -------------------------------------------------------------------------- */
/*  Token-bucket structures                                                   */
/* -------------------------------------------------------------------------- */

typedef struct
{
    uint32_t        capacity;
    volatile uint32_t tokens;
    uint32_t        refill_rate;     /* tokens/sec */
    struct timespec last_refill;     /* MONOTONIC clock */
} _sc_bucket_state_t;

struct _sc_consumer_bucket
{
    _sc_bucket_state_t state;
    struct _sc_consumer_bucket *next_in_arena; /* for mass-free */
};

struct sc_rate_limiter
{
    pthread_mutex_t lock;
    uint32_t        default_capacity;
    uint32_t        default_refill_rate;

    _sc_hash_t      table;           /* consumer_key -> bucket */
    _sc_consumer_bucket_t *arena;    /* singly-linked list for freeing */
};

/* -------------------------------------------------------------------------- */
/*  Allocation helpers                                                        */
/* -------------------------------------------------------------------------- */

static _sc_consumer_bucket_t *
_sc_consumer_bucket_create(uint32_t capacity,
                           uint32_t refill_rate)
{
    _sc_consumer_bucket_t *cb = calloc(1, sizeof(*cb));
    if (!cb) return NULL;

    cb->state.capacity     = capacity;
    cb->state.tokens       = capacity;
    cb->state.refill_rate  = refill_rate;
    _sc_timespec_now(&cb->state.last_refill);
    cb->next_in_arena = NULL;
    return cb;
}

static void _sc_consumer_bucket_destroy_arena(_sc_consumer_bucket_t *arena)
{
    _sc_consumer_bucket_t *cur = arena;
    while (cur) {
        _sc_consumer_bucket_t *next = cur->next_in_arena;
        free(cur);
        cur = next;
    }
}

/* -------------------------------------------------------------------------- */
/*  Core algorithms                                                           */
/* -------------------------------------------------------------------------- */

/* Refill tokens based on elapsed time. */
static void _sc_bucket_refill(_sc_bucket_state_t *bs)
{
    struct timespec now;
    _sc_timespec_now(&now);

    uint64_t elapsed_ns  = _sc_timespec_to_ns(&now) -
                           _sc_timespec_to_ns(&bs->last_refill);
    if (elapsed_ns == 0) return;

    /* integer arithmetic: add full tokens only */
    uint64_t tokens_to_add = (elapsed_ns * bs->refill_rate) / 1000000000ull;
    if (tokens_to_add == 0) return;

    uint32_t new_tokens = _sc_min_u32(bs->capacity,
                                      bs->tokens + (uint32_t)tokens_to_add);
    bs->tokens       = new_tokens;
    bs->last_refill  = now;
}

static _sc_consumer_bucket_t *
_sc_rate_limiter_get_or_create_bucket(sc_rate_limiter_t *rl,
                                      const char        *client_key)
{
    _sc_consumer_bucket_t *bucket = _sc_hash_get(&rl->table, client_key);
    if (bucket) return bucket;

    /* not present → allocate */
    bucket = _sc_consumer_bucket_create(rl->default_capacity,
                                        rl->default_refill_rate);
    if (!bucket) return NULL;

    /* chain to arena for batch destruction */
    bucket->next_in_arena = rl->arena;
    rl->arena             = bucket;

    if (_sc_hash_put(&rl->table, client_key, bucket) != 0) {
        /* out of memory; roll back */
        rl->arena = bucket->next_in_arena;
        free(bucket);
        return NULL;
    }
    return bucket;
}

/* -------------------------------------------------------------------------- */
/*  Public API                                                                */
/* -------------------------------------------------------------------------- */

int sc_rate_limiter_create(sc_rate_limiter_t **out_rl,
                           uint32_t            capacity,
                           uint32_t            refill_rate)
{
    if (!out_rl || capacity == 0 || refill_rate == 0) {
        errno = EINVAL;
        return -1;
    }

    sc_rate_limiter_t *rl = calloc(1, sizeof(*rl));
    if (!rl) return -1;

    if (pthread_mutex_init(&rl->lock, NULL) != 0) {
        free(rl);
        return -1;
    }

    rl->default_capacity     = capacity;
    rl->default_refill_rate  = refill_rate;

    if (_sc_hash_init(&rl->table) != 0) {
        pthread_mutex_destroy(&rl->lock);
        free(rl);
        return -1;
    }

    rl->arena = NULL;
    *out_rl   = rl;
    return 0;
}

void sc_rate_limiter_destroy(sc_rate_limiter_t *rl)
{
    if (!rl) return;
    _sc_hash_destroy(&rl->table);
    _sc_consumer_bucket_destroy_arena(rl->arena);
    pthread_mutex_destroy(&rl->lock);
    free(rl);
}

bool sc_rate_limiter_allow(sc_rate_limiter_t *rl,
                           const char        *client_key)
{
    if (!rl || !client_key) return false;

    bool allowed = false;

    if (pthread_mutex_lock(&rl->lock) != 0) return false;

    _sc_consumer_bucket_t *bucket = _sc_rate_limiter_get_or_create_bucket(rl,
                                                                          client_key);
    if (!bucket) {
        /* allocation failed -> deny to be safe */
        pthread_mutex_unlock(&rl->lock);
        return false;
    }

    _sc_bucket_refill(&bucket->state);

    if (bucket->state.tokens > 0) {
        --bucket->state.tokens;
        allowed = true;
    }

    pthread_mutex_unlock(&rl->lock);
    return allowed;
}

int sc_rate_limiter_set_limit(sc_rate_limiter_t *rl,
                              const char        *client_key,
                              uint32_t           capacity,
                              uint32_t           refill_rate)
{
    if (!rl || capacity == 0 || refill_rate == 0) {
        errno = EINVAL;
        return -1;
    }

    if (pthread_mutex_lock(&rl->lock) != 0) return -1;

    if (!client_key) {
        rl->default_capacity    = capacity;
        rl->default_refill_rate = refill_rate;
        pthread_mutex_unlock(&rl->lock);
        return 0;
    }

    _sc_consumer_bucket_t *bucket = _sc_rate_limiter_get_or_create_bucket(rl,
                                                                          client_key);
    if (!bucket) {
        pthread_mutex_unlock(&rl->lock);
        return -1;
    }

    bucket->state.capacity     = capacity;
    bucket->state.refill_rate  = refill_rate;
    bucket->state.tokens       = _sc_min_u32(bucket->state.tokens, capacity);
    _sc_timespec_now(&bucket->state.last_refill);

    pthread_mutex_unlock(&rl->lock);
    return 0;
}

int sc_rate_limiter_get_stats(sc_rate_limiter_t       *rl,
                              const char              *client_key,
                              sc_rate_limiter_stats_t *out_stats)
{
    if (!rl || !client_key || !out_stats) {
        errno = EINVAL;
        return -1;
    }

    if (pthread_mutex_lock(&rl->lock) != 0) return -1;

    _sc_consumer_bucket_t *bucket = _sc_hash_get(&rl->table, client_key);
    if (!bucket) {
        pthread_mutex_unlock(&rl->lock);
        errno = ENOENT;
        return -1;
    }

    _sc_bucket_refill(&bucket->state);

    out_stats->capacity    = bucket->state.capacity;
    out_stats->tokens      = bucket->state.tokens;
    out_stats->refill_rate = bucket->state.refill_rate;

    pthread_mutex_unlock(&rl->lock);
    return 0;
}

/* -------------------------------------------------------------------------- */
/*  End of implementation section                                             */
/* -------------------------------------------------------------------------- */
#endif  /* SC_RATE_LIMITER_IMPLEMENTATION */


/* ========================================================================== */
/*  MIT License                                                               */
/*                                                                            */
/*  Copyright (c) 2024 SynestheticCanvas Contributors                          */
/*                                                                            */
/*  Permission is hereby granted, free of charge, to any person obtaining a   */
/*  copy of this software and associated documentation files (the "Software"),*/
/*  to deal in the Software without restriction, including without limitation */
/*  the rights to use, copy, modify, merge, publish, distribute, sublicense,  */
/*  and/or sell copies of the Software, and to permit persons to whom the     */
/*  Software is furnished to do so, subject to the following conditions:      */
/*                                                                            */
/*  The above copyright notice and this permission notice shall be included   */
/*  in all copies or substantial portions of the Software.                    */
/*                                                                            */
/*  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS   */
/*  OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF                */
/*  MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN */
/*  NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,  */
/*  DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR     */
/*  OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE */
/*  USE OR OTHER DEALINGS IN THE SOFTWARE.                                    */
/* ========================================================================== */
#endif /* SYNESTHETIC_CANVAS_RATE_LIMITER_H */
