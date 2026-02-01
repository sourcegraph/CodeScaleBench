```c
/**
 * ll_hashmap.h
 *
 * A generic, production-quality, open-addressing hash-map with optional
 * thread-safety for the LexiLearn MVC Orchestrator.
 *
 * This header is self-contained: declare LL_HASHMAP_IMPLEMENTATION in **one**
 * compilation unit before including this file to emit the implementation.
 *
 *      #define LL_HASHMAP_IMPLEMENTATION
 *      #include "ll_hashmap.h"
 *
 * Keys and values are stored as void*.  Users are responsible for managing
 * memory of their data.  A default FNV-1a hash routine for zero-terminated
 * strings is provided.  Custom hash / equality functions are supported.
 *
 * Thread-safety: define LL_HASHMAP_THREAD_SAFE to enable a pthread
 * read-write lock guarding all public operations.
 *
 * License: MIT
 */

#ifndef LL_HASHMAP_H
#define LL_HASHMAP_H

/* ------------------------------------------------------------------------- */
/* Dependencies                                                              */
/* ------------------------------------------------------------------------- */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#if defined(LL_HASHMAP_THREAD_SAFE)
#   include <pthread.h>
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------------- */
/* Status codes                                                              */
/* ------------------------------------------------------------------------- */
typedef enum {
    LL_HASHMAP_OK               =  0,
    LL_HASHMAP_ERR_NOMEM        = -1,
    LL_HASHMAP_ERR_KEY_NOT_FOUND= -2,
    LL_HASHMAP_ERR_INVALID      = -3
} ll_hashmap_status_t;

/* ------------------------------------------------------------------------- */
/* Function pointer types                                                    */
/* ------------------------------------------------------------------------- */
typedef size_t (*ll_hash_fn)(const void *key);
typedef int    (*ll_key_eq_fn)(const void *a, const void *b);

/* ------------------------------------------------------------------------- */
/* Public structures                                                         */
/* ------------------------------------------------------------------------- */
typedef struct ll_hash_entry {
    void    *key;
    void    *value;
    uint8_t  state; /* 0 = empty, 1 = occupied, 2 = tombstone */
} ll_hash_entry_t;

typedef struct ll_hashmap {
    ll_hash_entry_t *entries;
    size_t           capacity;          /* total slots               */
    size_t           size;              /* active key/value pairs     */
    float            max_load_factor;   /* triggers resize            */
    ll_hash_fn       hash;
    ll_key_eq_fn     key_eq;

#if defined(LL_HASHMAP_THREAD_SAFE)
    pthread_rwlock_t lock;
#endif
} ll_hashmap_t;

/* Iterator --------------------------------------------------------------- */
typedef struct ll_hashmap_iter {
    ll_hashmap_t *map;
    size_t        index;
} ll_hashmap_iter_t;

/* ------------------------------------------------------------------------- */
/* Public API                                                                */
/* ------------------------------------------------------------------------- */

/* Default hash / equality for NUL-terminated strings --------------------- */
size_t ll_hashmap_hash_cstr(const void *key);
int    ll_hashmap_eq_cstr  (const void *a, const void *b);

/* Core lifecycle --------------------------------------------------------- */
ll_hashmap_status_t ll_hashmap_init(
        ll_hashmap_t   *map,
        size_t          initial_capacity,     /* 0 ⇒ implementation default */
        ll_hash_fn      hash_fn,              /* NULL ⇒ default string hash */
        ll_key_eq_fn    eq_fn);               /* NULL ⇒ default string eq   */

void ll_hashmap_destroy(
        ll_hashmap_t *map,
        void (*free_key)(void *),             /* optional                   */
        void (*free_val)(void *));

/* CRUD --------------------------------------------------------------------*/
ll_hashmap_status_t ll_hashmap_set(
        ll_hashmap_t *map,
        void *key,
        void *value);

void *ll_hashmap_get(
        ll_hashmap_t *map,
        const void   *key);

ll_hashmap_status_t ll_hashmap_remove(
        ll_hashmap_t  *map,
        const void    *key,
        void (**key_out)(void *),      /* can be NULL */
        void (**val_out)(void *));     /* can be NULL */

size_t ll_hashmap_size(const ll_hashmap_t *map);

/* Iteration ---------------------------------------------------------------*/
void ll_hashmap_iter_init(ll_hashmap_t *map, ll_hashmap_iter_t *iter);

bool ll_hashmap_iter_next(
        ll_hashmap_iter_t *iter,
        void             **key_out,
        void             **val_out);

#ifdef __cplusplus
} /* extern "C" */
#endif

/* ------------------------------------------------------------------------- */
/* Implementation (define LL_HASHMAP_IMPLEMENTATION once)                   */
/* ------------------------------------------------------------------------- */
#ifdef LL_HASHMAP_IMPLEMENTATION
/* ------------------------------------------------------------------------- */
/* Private helpers                                                           */
/* ------------------------------------------------------------------------- */
#include <stdlib.h>
#include <string.h>

/* Minimum capacity must be a power of two for fast modulo using mask */
#define LL_HASHMAP_MIN_CAPACITY 16U
#define LL_HASHMAP_DEFAULT_LOAD 0.75f

/* Entry states */
#define LL_ENTRY_EMPTY      0u
#define LL_ENTRY_OCCUPIED   1u
#define LL_ENTRY_TOMBSTONE  2u

/* Forward declarations */
static ll_hashmap_status_t ll__hashmap_rehash(ll_hashmap_t *map, size_t new_cap);
static size_t              ll__next_pow2(size_t v);

/* --------------------- Default FNV-1a 64-bit string hash ----------------- */
size_t ll_hashmap_hash_cstr(const void *key)
{
    const char *str = (const char *)key;
    const uint64_t fnv_offset = 14695981039346656037ULL;
    const uint64_t fnv_prime  = 1099511628211ULL;

    uint64_t hash = fnv_offset;
    for (; *str; ++str)
    {
        hash ^= (uint64_t)(unsigned char)(*str);
        hash *= fnv_prime;
    }
    return (size_t)hash;
}

int ll_hashmap_eq_cstr(const void *a, const void *b)
{
    return strcmp((const char *)a, (const char *)b) == 0;
}

/* --------------------- Public API --------------------------------------- */
ll_hashmap_status_t ll_hashmap_init(
        ll_hashmap_t *map,
        size_t        initial_capacity,
        ll_hash_fn    hash_fn,
        ll_key_eq_fn  eq_fn)
{
    if (!map) return LL_HASHMAP_ERR_INVALID;

    if (initial_capacity < LL_HASHMAP_MIN_CAPACITY)
        initial_capacity = LL_HASHMAP_MIN_CAPACITY;
    else
        initial_capacity = ll__next_pow2(initial_capacity);

    map->entries = (ll_hash_entry_t *)calloc(initial_capacity,
                                             sizeof(ll_hash_entry_t));
    if (!map->entries) return LL_HASHMAP_ERR_NOMEM;

    map->capacity         = initial_capacity;
    map->size             = 0;
    map->max_load_factor  = LL_HASHMAP_DEFAULT_LOAD;
    map->hash             = hash_fn ? hash_fn : ll_hashmap_hash_cstr;
    map->key_eq           = eq_fn   ? eq_fn   : ll_hashmap_eq_cstr;

#if defined(LL_HASHMAP_THREAD_SAFE)
    if (pthread_rwlock_init(&map->lock, NULL) != 0) {
        free(map->entries);
        return LL_HASHMAP_ERR_INVALID;
    }
#endif
    return LL_HASHMAP_OK;
}

void ll_hashmap_destroy(
        ll_hashmap_t *map,
        void (*free_key)(void *),
        void (*free_val)(void *))
{
    if (!map || !map->entries) return;

#if defined(LL_HASHMAP_THREAD_SAFE)
    pthread_rwlock_wrlock(&map->lock);
#endif

    if (free_key || free_val)
    {
        for (size_t i = 0; i < map->capacity; ++i)
        {
            ll_hash_entry_t *e = &map->entries[i];
            if (e->state == LL_ENTRY_OCCUPIED)
            {
                if (free_key) free_key(e->key);
                if (free_val) free_val(e->value);
            }
        }
    }

    free(map->entries);
    map->entries = NULL;
    map->capacity = map->size = 0;

#if defined(LL_HASHMAP_THREAD_SAFE)
    pthread_rwlock_unlock(&map->lock);
    pthread_rwlock_destroy(&map->lock);
#endif
}

static inline bool ll__need_rehash(const ll_hashmap_t *map)
{
    return (float)(map->size + 1) / (float)map->capacity > map->max_load_factor;
}

ll_hashmap_status_t ll_hashmap_set(
        ll_hashmap_t *map,
        void *key,
        void *value)
{
    if (!map || !key) return LL_HASHMAP_ERR_INVALID;

#if defined(LL_HASHMAP_THREAD_SAFE)
    pthread_rwlock_wrlock(&map->lock);
#endif

    /* Resize if load factor exceeded */
    if (ll__need_rehash(map))
    {
        ll_hashmap_status_t st = ll__hashmap_rehash(map, map->capacity * 2);
        if (st != LL_HASHMAP_OK) {
#if defined(LL_HASHMAP_THREAD_SAFE)
            pthread_rwlock_unlock(&map->lock);
#endif
            return st;
        }
    }

    size_t mask = map->capacity - 1;
    size_t idx  = map->hash(key) & mask;
    size_t first_tombstone = SIZE_MAX;

    for (;;)
    {
        ll_hash_entry_t *e = &map->entries[idx];

        if (e->state == LL_ENTRY_EMPTY)
        {
            /* Use previous tombstone if found */
            size_t target = (first_tombstone != SIZE_MAX) ? first_tombstone : idx;
            e = &map->entries[target];
            e->key   = key;
            e->value = value;
            e->state = LL_ENTRY_OCCUPIED;
            map->size++;
#if defined(LL_HASHMAP_THREAD_SAFE)
            pthread_rwlock_unlock(&map->lock);
#endif
            return LL_HASHMAP_OK;
        }
        else if (e->state == LL_ENTRY_TOMBSTONE)
        {
            if (first_tombstone == SIZE_MAX)
                first_tombstone = idx;
        }
        else if (map->key_eq(e->key, key))
        {
            /* Update existing value */
            e->value = value;
#if defined(LL_HASHMAP_THREAD_SAFE)
            pthread_rwlock_unlock(&map->lock);
#endif
            return LL_HASHMAP_OK;
        }

        idx = (idx + 1) & mask;
    }
}

void *ll_hashmap_get(
        ll_hashmap_t *map,
        const void   *key)
{
    if (!map || !key) return NULL;

#if defined(LL_HASHMAP_THREAD_SAFE)
    pthread_rwlock_rdlock(&map->lock);
#endif

    size_t mask = map->capacity - 1;
    size_t idx  = map->hash(key) & mask;

    for (;;)
    {
        ll_hash_entry_t *e = &map->entries[idx];
        if (e->state == LL_ENTRY_EMPTY) break;
        if (e->state == LL_ENTRY_OCCUPIED && map->key_eq(e->key, key))
        {
#if defined(LL_HASHMAP_THREAD_SAFE)
            pthread_rwlock_unlock(&map->lock);
#endif
            return e->value;
        }
        idx = (idx + 1) & mask;
    }

#if defined(LL_HASHMAP_THREAD_SAFE)
    pthread_rwlock_unlock(&map->lock);
#endif
    return NULL;
}

ll_hashmap_status_t ll_hashmap_remove(
        ll_hashmap_t  *map,
        const void    *key,
        void (**key_out)(void *),
        void (**val_out)(void *))
{
    if (!map || !key) return LL_HASHMAP_ERR_INVALID;

#if defined(LL_HASHMAP_THREAD_SAFE)
    pthread_rwlock_wrlock(&map->lock);
#endif

    size_t mask = map->capacity - 1;
    size_t idx  = map->hash(key) & mask;

    for (;;)
    {
        ll_hash_entry_t *e = &map->entries[idx];
        if (e->state == LL_ENTRY_EMPTY) break;

        if (e->state == LL_ENTRY_OCCUPIED && map->key_eq(e->key, key))
        {
            if (key_out) *key_out = (void (*)(void *))e->key;
            if (val_out) *val_out = (void (*)(void *))e->value;
            e->state = LL_ENTRY_TOMBSTONE;
            e->key   = NULL;
            e->value = NULL;
            map->size--;

#if defined(LL_HASHMAP_THREAD_SAFE)
            pthread_rwlock_unlock(&map->lock);
#endif
            return LL_HASHMAP_OK;
        }
        idx = (idx + 1) & mask;
    }

#if defined(LL_HASHMAP_THREAD_SAFE)
    pthread_rwlock_unlock(&map->lock);
#endif
    return LL_HASHMAP_ERR_KEY_NOT_FOUND;
}

size_t ll_hashmap_size(const ll_hashmap_t *map)
{
    if (!map) return 0;
    return map->size;
}

/* -------------------- Iteration ----------------------------------------- */
void ll_hashmap_iter_init(ll_hashmap_t *map, ll_hashmap_iter_t *iter)
{
    iter->map   = map;
    iter->index = 0;
}

bool ll_hashmap_iter_next(
        ll_hashmap_iter_t *iter,
        void             **key_out,
        void             **val_out)
{
    ll_hashmap_t *map = iter->map;
    while (iter->index < map->capacity)
    {
        ll_hash_entry_t *e = &map->entries[iter->index++];
        if (e->state == LL_ENTRY_OCCUPIED)
        {
            if (key_out) *key_out = e->key;
            if (val_out) *val_out = e->value;
            return true;
        }
    }
    return false;
}

/* -------------------- Private helpers ----------------------------------- */
static ll_hashmap_status_t ll__hashmap_rehash(ll_hashmap_t *map, size_t new_cap)
{
    new_cap = ll__next_pow2(new_cap);
    if (new_cap < LL_HASHMAP_MIN_CAPACITY)
        new_cap = LL_HASHMAP_MIN_CAPACITY;

    ll_hash_entry_t *new_entries = (ll_hash_entry_t *)calloc(new_cap,
                                                             sizeof(ll_hash_entry_t));
    if (!new_entries) return LL_HASHMAP_ERR_NOMEM;

    size_t old_cap = map->capacity;
    ll_hash_entry_t *old_entries = map->entries;

    map->entries  = new_entries;
    map->capacity = new_cap;
    map->size     = 0;

    size_t mask = new_cap - 1;

    for (size_t i = 0; i < old_cap; ++i)
    {
        ll_hash_entry_t *e = &old_entries[i];
        if (e->state != LL_ENTRY_OCCUPIED) continue;

        size_t idx = map->hash(e->key) & mask;
        while (new_entries[idx].state == LL_ENTRY_OCCUPIED)
            idx = (idx + 1) & mask;

        new_entries[idx].key   = e->key;
        new_entries[idx].value = e->value;
        new_entries[idx].state = LL_ENTRY_OCCUPIED;
        map->size++;
    }

    free(old_entries);
    return LL_HASHMAP_OK;
}

static size_t ll__next_pow2(size_t v)
{
    if (v == 0) return 1;
    v--;
    v |= v >> 1;
    v |= v >> 2;
    v |= v >> 4;
    v |= v >> 8;
    v |= v >> 16;
#if SIZE_MAX > UINT32_MAX
    v |= v >> 32;
#endif
    return ++v;
}

#endif /* LL_HASHMAP_IMPLEMENTATION */
#endif /* LL_HASHMAP_H */
```