```c
/*
 *  LexiLearn MVC Orchestrator
 *  --------------------------------------
 *  File:    ll_hashmap.c
 *  Author:  LexiLearn Platform Team
 *
 *  Description:
 *      General-purpose, pointer-based hashmap with support for arbitrary
 *      (binary-safe) keys.  Employs separate chaining with dynamic resizing.
 *      This implementation is intentionally self-contained so that it can be
 *      reused in low-level components (e.g., feature-store cache, experiment
 *      metadata registry) without pulling in heavy external deps.
 *
 *  Public interface is declared in:  ll_hashmap.h
 *
 *  Thread-safety:
 *      ‑ All functions operate on user-supplied ll_hashmap* instances and are
 *        NOT internally synchronized.  External synchronization is required
 *        when sharing a hashmap across threads (e.g., via pthread mutexes or
 *        rw-locks).
 *
 *  Complexity:
 *      Average-case O(1) put/get/remove; worst-case O(n) when many collisions
 *      occur.  Resizing is O(n).
 *
 *  Copyright (c) 2024  LexiLearn Systems
 *  SPDX-License-Identifier: MIT
 */

#include "ll_hashmap.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* -------------------------------------------------------------------------- */
/*  Internal helpers                                                          */
/* -------------------------------------------------------------------------- */

#ifndef LLHM_DEFAULT_INITIAL_CAP
#define LLHM_DEFAULT_INITIAL_CAP  64U
#endif

#ifndef LLHM_DEFAULT_LOAD_FACTOR
#define LLHM_DEFAULT_LOAD_FACTOR  0.80f
#endif

/* Forward declaration */
typedef struct _llhm_entry _llhm_entry;

/* Linked-list node stored in each bucket */
struct _llhm_entry
{
    void        *key;
    size_t       key_len;
    uint64_t     hash;     /* Cached hash for quick comparison               */
    void        *value;
    _llhm_entry *next;
};

struct ll_hashmap
{
    _llhm_entry **buckets;
    size_t        nbuckets;
    size_t        size;        /* Number of key/value pairs                   */
    float         max_load;    /* Resize threshold (size/nbuckets)           */
};

/* -------------------------------------------------------------------------- */
/*  Hash function (FNV-1a 64-bit)                                             */
/* -------------------------------------------------------------------------- */
static uint64_t _fnv1a_hash(const void *data, size_t len)
{
    static const uint64_t FNV_PRIME  = 0x100000001b3ULL;
    static const uint64_t FNV_OFFSET = 0xcbf29ce484222325ULL;

    const uint8_t *ptr  = (const uint8_t *)data;
    uint64_t       hash = FNV_OFFSET;

    for (size_t i = 0; i < len; ++i)
    {
        hash ^= (uint64_t)ptr[i];
        hash *= FNV_PRIME;
    }
    return hash;
}

/* -------------------------------------------------------------------------- */
/*  Bucket index helper                                                       */
/* -------------------------------------------------------------------------- */
#define _bucket_index(h, nb) ((size_t)((h) & ((nb) - 1)))

/* -------------------------------------------------------------------------- */
/*  Entry allocation                                                          */
/* -------------------------------------------------------------------------- */
static _llhm_entry *_entry_create(const void *key,
                                  size_t       key_len,
                                  uint64_t     hash,
                                  void        *value)
{
    _llhm_entry *entry = (_llhm_entry *)calloc(1, sizeof(_llhm_entry));
    if (!entry)
        return NULL;

    entry->key = malloc(key_len);
    if (!entry->key)
    {
        free(entry);
        return NULL;
    }

    memcpy(entry->key, key, key_len);
    entry->key_len = key_len;
    entry->hash    = hash;
    entry->value   = value;
    entry->next    = NULL;
    return entry;
}

/* -------------------------------------------------------------------------- */
/*  Destroy a single bucket chain                                             */
/* -------------------------------------------------------------------------- */
static void _entry_chain_destroy(_llhm_entry *head,
                                 llhm_free_fn free_key,
                                 llhm_free_fn free_val)
{
    _llhm_entry *cur = head;
    while (cur)
    {
        _llhm_entry *next = cur->next;

        if (free_key)
            free_key(cur->key);
        else
            free(cur->key);

        if (free_val)
            free_val(cur->value);

        free(cur);
        cur = next;
    }
}

/* -------------------------------------------------------------------------- */
/*  Resize                                                                   */
/* -------------------------------------------------------------------------- */
static int _resize(ll_hashmap *map, size_t new_cap)
{
    /* new_cap must be power of two for fast modulo op via bit-and */
    if (new_cap < 8 || (new_cap & (new_cap - 1)) != 0)
        return EINVAL;

    _llhm_entry **new_buckets =
        (_llhm_entry **)calloc(new_cap, sizeof(_llhm_entry *));
    if (!new_buckets)
        return ENOMEM;

    /* Rehash all existing entries */
    for (size_t i = 0; i < map->nbuckets; ++i)
    {
        _llhm_entry *entry = map->buckets[i];
        while (entry)
        {
            _llhm_entry *next = entry->next;

            size_t new_idx       = _bucket_index(entry->hash, new_cap);
            entry->next          = new_buckets[new_idx];
            new_buckets[new_idx] = entry;

            entry = next;
        }
    }

    free(map->buckets);
    map->buckets   = new_buckets;
    map->nbuckets  = new_cap;
    return 0;
}

/* -------------------------------------------------------------------------- */
/*  Public API                                                                */
/* -------------------------------------------------------------------------- */

ll_hashmap *ll_hashmap_create(size_t initial_capacity, float load_factor)
{
    if (initial_capacity == 0)
        initial_capacity = LLHM_DEFAULT_INITIAL_CAP;

    /* Ensure capacity is power of two for modulus trick */
    size_t cap_pow2 = 1;
    while (cap_pow2 < initial_capacity)
        cap_pow2 <<= 1;

    if (load_factor <= 0.0f || load_factor >= 1.0f)
        load_factor = LLHM_DEFAULT_LOAD_FACTOR;

    ll_hashmap *map = (ll_hashmap *)calloc(1, sizeof(ll_hashmap));
    if (!map)
        return NULL;

    map->buckets = (_llhm_entry **)calloc(cap_pow2, sizeof(_llhm_entry *));
    if (!map->buckets)
    {
        free(map);
        return NULL;
    }

    map->nbuckets = cap_pow2;
    map->size     = 0;
    map->max_load = load_factor;

    return map;
}

void ll_hashmap_destroy(ll_hashmap *map,
                        llhm_free_fn free_key,
                        llhm_free_fn free_val)
{
    if (!map)
        return;

    for (size_t i = 0; i < map->nbuckets; ++i)
        _entry_chain_destroy(map->buckets[i], free_key, free_val);

    free(map->buckets);
    free(map);
}

size_t ll_hashmap_size(const ll_hashmap *map)
{
    return map ? map->size : 0;
}

/* -------------------------------------------------------------------------- */
/*  PUT                                                                       */
/* -------------------------------------------------------------------------- */
int ll_hashmap_put(ll_hashmap *map,
                   const void *key,
                   size_t      key_len,
                   void       *value,
                   void      **old_value)
{
    if (!map || !key || key_len == 0)
        return EINVAL;

    uint64_t hash = _fnv1a_hash(key, key_len);
    size_t   idx  = _bucket_index(hash, map->nbuckets);

    _llhm_entry *cur = map->buckets[idx];
    for (; cur; cur = cur->next)
    {
        if (cur->hash == hash && cur->key_len == key_len &&
            memcmp(cur->key, key, key_len) == 0)
        {
            /* Key already exists -> replace value */
            if (old_value)
                *old_value = cur->value;

            cur->value = value;
            return 0;
        }
    }

    /* New key -> create entry */
    _llhm_entry *entry = _entry_create(key, key_len, hash, value);
    if (!entry)
        return ENOMEM;

    entry->next        = map->buckets[idx];
    map->buckets[idx]  = entry;
    map->size++;

    /* Resize if necessary */
    if ((float)map->size / (float)map->nbuckets > map->max_load)
    {
        int rc = _resize(map, map->nbuckets << 1);
        if (rc != 0)
            return rc;
    }

    if (old_value)
        *old_value = NULL;
    return 0;
}

/* -------------------------------------------------------------------------- */
/*  GET                                                                       */
/* -------------------------------------------------------------------------- */
int ll_hashmap_get(const ll_hashmap *map,
                   const void       *key,
                   size_t            key_len,
                   void            **out_value)
{
    if (!map || !key || key_len == 0)
        return EINVAL;

    uint64_t hash = _fnv1a_hash(key, key_len);
    size_t   idx  = _bucket_index(hash, map->nbuckets);

    _llhm_entry *cur = map->buckets[idx];
    for (; cur; cur = cur->next)
    {
        if (cur->hash == hash && cur->key_len == key_len &&
            memcmp(cur->key, key, key_len) == 0)
        {
            if (out_value)
                *out_value = cur->value;
            return 0; /* Found */
        }
    }
    return ENOENT;
}

/* -------------------------------------------------------------------------- */
/*  REMOVE                                                                    */
/* -------------------------------------------------------------------------- */
int ll_hashmap_remove(ll_hashmap *map,
                      const void *key,
                      size_t      key_len,
                      llhm_free_fn free_key,
                      void      **removed_value)
{
    if (!map || !key || key_len == 0)
        return EINVAL;

    uint64_t hash = _fnv1a_hash(key, key_len);
    size_t   idx  = _bucket_index(hash, map->nbuckets);

    _llhm_entry *prev = NULL;
    _llhm_entry *cur  = map->buckets[idx];

    for (; cur; prev = cur, cur = cur->next)
    {
        if (cur->hash == hash && cur->key_len == key_len &&
            memcmp(cur->key, key, key_len) == 0)
        {
            /* Found */
            if (prev)
                prev->next = cur->next;
            else
                map->buckets[idx] = cur->next;

            if (removed_value)
                *removed_value = cur->value;
            else if (free_key)
                free_key(cur->value);

            if (free_key)
                free_key(cur->key);
            else
                free(cur->key);

            free(cur);
            map->size--;
            return 0;
        }
    }
    return ENOENT;
}

/* -------------------------------------------------------------------------- */
/*  Iterator                                                                  */
/* -------------------------------------------------------------------------- */
struct llhm_iterator
{
    const ll_hashmap *_map;
    size_t            _bucket_idx;
    _llhm_entry      *_cur;
};

llhm_iterator *ll_hashmap_iterator_create(const ll_hashmap *map)
{
    if (!map)
        return NULL;

    llhm_iterator *it = (llhm_iterator *)calloc(1, sizeof(llhm_iterator));
    if (!it)
        return NULL;

    it->_map        = map;
    it->_bucket_idx = 0;
    it->_cur        = NULL;

    return it;
}

void ll_hashmap_iterator_destroy(llhm_iterator *it)
{
    free(it);
}

bool ll_hashmap_iter_next(llhm_iterator *it, const void **out_key,
                          size_t *out_key_len, void **out_val)
{
    if (!it || !it->_map)
        return false;

    /* Move to next entry if present */
    if (it->_cur)
        it->_cur = it->_cur->next;

    /* If current chain exhausted, move to next bucket */
    while (!it->_cur && it->_bucket_idx < it->_map->nbuckets)
    {
        it->_cur = it->_map->buckets[it->_bucket_idx++];
    }

    if (!it->_cur)
        return false;

    if (out_key)
        *out_key = it->_cur->key;
    if (out_key_len)
        *out_key_len = it->_cur->key_len;
    if (out_val)
        *out_val = it->_cur->value;

    return true;
}
```