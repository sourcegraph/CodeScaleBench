/*
 * =============================================================================
 *  File:    ll_vector.c
 *  Project: LexiLearn MVC Orchestrator (ml_nlp)
 *
 *  A generic, thread–optional, resizable vector implementation that serves as a
 *  foundational data-structure across the LexiLearn code-base.  The vector is
 *  capable of storing arbitrary POD or non-POD types through opaque byte
 *  storage.  An optional per-element destructor allows safe use with heap
 *  allocated objects.  Compile with `-DLL_VECTOR_THREADSAFE` to enable
 *  fine-grained, reader/writer locking.
 *
 *  Copyright © 2023-2024 The LexiLearn Authors
 *  SPDX-License-Identifier: MIT
 * =============================================================================
 */

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common/data_structures/ll_vector.h"  /* Public API declaration */

/* ------------------------------------------------------------------------- */
/*                           Internal helper macros                          */
/* ------------------------------------------------------------------------- */
#define  LL_VECTOR_MIN_CAPACITY   (8U)

#ifdef LL_VECTOR_THREADSAFE
    #define _LL_RDLOCK(vec)   (pthread_rwlock_rdlock(&(vec)->lock))
    #define _LL_WRLOCK(vec)   (pthread_rwlock_wrlock(&(vec)->lock))
    #define _LL_UNLOCK(vec)   (pthread_rwlock_unlock(&(vec)->lock))
#else
    #define _LL_RDLOCK(vec)   ((void)0)
    #define _LL_WRLOCK(vec)   ((void)0)
    #define _LL_UNLOCK(vec)   ((void)0)
#endif /* LL_VECTOR_THREADSAFE */

#ifndef NDEBUG
    #define _LL_ASSERT(cond, msg)                                   \
        do {                                                        \
            if (!(cond)) {                                          \
                fprintf(stderr, "[ll_vector] Assertion failed: %s " \
                        "at %s:%d\n", (msg), __FILE__, __LINE__);    \
                abort();                                            \
            }                                                       \
        } while (0)
#else
    #define _LL_ASSERT(cond, msg) ((void)0)
#endif /* NDEBUG */

/* ------------------------------------------------------------------------- */
/*                           Static helper functions                         */
/* ------------------------------------------------------------------------- */

/* Forward declaration */
static ll_vector_status_t _ll_vector_reserve_unlocked(ll_vector_t *vec,
                                                      size_t       min_capacity);

/*
 * Safely calculate the next capacity when growing.
 * Uses the expansion policy `cap' → `cap * 1.5 + 8`.
 */
static size_t
_next_capacity(size_t current, size_t required)
{
    size_t new_cap = current;

    while (new_cap < required) {
        new_cap = (new_cap < LL_VECTOR_MIN_CAPACITY)
                    ? LL_VECTOR_MIN_CAPACITY
                    : (new_cap + (new_cap >> 1U));  /* 1.5x growth */
    }
    return new_cap;
}

/* ------------------------------------------------------------------------- */
/*                          Lifecycle / initialisation                       */
/* ------------------------------------------------------------------------- */

ll_vector_status_t
ll_vector_init(ll_vector_t        *vec,
               size_t              element_size,
               size_t              initial_capacity,
               ll_element_dtor_fn  destructor)
{
    if (!vec || element_size == 0U) { return LL_VECTOR_ERR_INVALID_ARG; }

    vec->element_size = element_size;
    vec->size         = 0U;
    vec->capacity     = (initial_capacity == 0U)
                        ? LL_VECTOR_MIN_CAPACITY
                        : initial_capacity;
    vec->destructor   = destructor;

#ifdef LL_VECTOR_THREADSAFE
    if (pthread_rwlock_init(&vec->lock, NULL) != 0) {
        return LL_VECTOR_ERR_SYNC;
    }
#endif

    vec->data = calloc(vec->capacity, element_size);
    if (!vec->data) {
#ifdef LL_VECTOR_THREADSAFE
        pthread_rwlock_destroy(&vec->lock);
#endif
        return LL_VECTOR_ERR_ALLOCATION;
    }
    return LL_VECTOR_OK;
}

ll_vector_t *
ll_vector_new(size_t element_size,
              size_t initial_capacity,
              ll_element_dtor_fn destructor)
{
    ll_vector_t *vec = malloc(sizeof *vec);
    if (!vec) { return NULL; }

    if (ll_vector_init(vec, element_size,
                       initial_capacity, destructor) != LL_VECTOR_OK) {
        free(vec);
        return NULL;
    }
    return vec;
}

void
ll_vector_cleanup(ll_vector_t *vec)
{
    if (!vec) { return; }

    _LL_WRLOCK(vec);

    if (vec->destructor) {
        for (size_t i = 0U; i < vec->size; ++i) {
            void *elem_ptr = vec->data + (i * vec->element_size);
            vec->destructor(elem_ptr);
        }
    }
    free(vec->data);
    vec->data       = NULL;
    vec->size       = 0U;
    vec->capacity   = 0U;

    _LL_UNLOCK(vec);

#ifdef LL_VECTOR_THREADSAFE
    pthread_rwlock_destroy(&vec->lock);
#endif
}

void
ll_vector_free(ll_vector_t *vec)
{
    if (!vec) { return; }
    ll_vector_cleanup(vec);
    free(vec);
}

/* ------------------------------------------------------------------------- */
/*                             Element operations                            */
/* ------------------------------------------------------------------------- */

ll_vector_status_t
ll_vector_push_back(ll_vector_t *vec, const void *element)
{
    if (!vec || !element) { return LL_VECTOR_ERR_INVALID_ARG; }

    _LL_WRLOCK(vec);

    if (vec->size == vec->capacity) {
        const ll_vector_status_t st = _ll_vector_reserve_unlocked(
                                            vec,
                                            _next_capacity(vec->capacity,
                                                           vec->size + 1U));
        if (st != LL_VECTOR_OK) {
            _LL_UNLOCK(vec);
            return st;
        }
    }

    void *dest = vec->data + (vec->size * vec->element_size);
    memcpy(dest, element, vec->element_size);
    ++vec->size;

    _LL_UNLOCK(vec);
    return LL_VECTOR_OK;
}

ll_vector_status_t
ll_vector_pop_back(ll_vector_t *vec, void *out_element)
{
    if (!vec) { return LL_VECTOR_ERR_INVALID_ARG; }

    _LL_WRLOCK(vec);

    if (vec->size == 0U) {
        _LL_UNLOCK(vec);
        return LL_VECTOR_ERR_OUT_OF_BOUNDS;
    }

    --vec->size;
    void *src = vec->data + (vec->size * vec->element_size);

    if (out_element) {
        memcpy(out_element, src, vec->element_size);
    }

    if (vec->destructor) {
        vec->destructor(src);
    }

    _LL_UNLOCK(vec);
    return LL_VECTOR_OK;
}

void *
ll_vector_get(const ll_vector_t *vec, size_t index)
{
    if (!vec) { return NULL; }

    _LL_RDLOCK((ll_vector_t *)vec);

    if (index >= vec->size) {
        _LL_UNLOCK((ll_vector_t *)vec);
        return NULL;
    }

    void *elem_ptr = vec->data + (index * vec->element_size);

    _LL_UNLOCK((ll_vector_t *)vec);
    return elem_ptr;
}

ll_vector_status_t
ll_vector_set(ll_vector_t *vec, size_t index, const void *element)
{
    if (!vec || !element) { return LL_VECTOR_ERR_INVALID_ARG; }

    _LL_WRLOCK(vec);

    if (index >= vec->size) {
        _LL_UNLOCK(vec);
        return LL_VECTOR_ERR_OUT_OF_BOUNDS;
    }

    void *dest = vec->data + (index * vec->element_size);

    if (vec->destructor) {
        vec->destructor(dest);
    }

    memcpy(dest, element, vec->element_size);

    _LL_UNLOCK(vec);
    return LL_VECTOR_OK;
}

/*
 * Remove an element at 'index'.  If preserve_order is false the element is
 * swapped with the last, resulting in O(1) removal.
 */
ll_vector_status_t
ll_vector_remove_at(ll_vector_t *vec,
                    size_t       index,
                    void        *out_element,
                    bool         preserve_order)
{
    if (!vec) { return LL_VECTOR_ERR_INVALID_ARG; }

    _LL_WRLOCK(vec);

    if (index >= vec->size) {
        _LL_UNLOCK(vec);
        return LL_VECTOR_ERR_OUT_OF_BOUNDS;
    }

    void *target = vec->data + (index * vec->element_size);

    if (out_element) {
        memcpy(out_element, target, vec->element_size);
    }

    if (vec->destructor) {
        vec->destructor(target);
    }

    --vec->size;
    if (index != vec->size) {
        void *src = vec->data + (vec->size * vec->element_size);

        if (preserve_order) {
            memmove(target, (uint8_t *)target + vec->element_size,
                    (vec->size - index) * vec->element_size);
        } else {
            memcpy(target, src, vec->element_size);
        }
    }

    _LL_UNLOCK(vec);
    return LL_VECTOR_OK;
}

/* ------------------------------------------------------------------------- */
/*                           Capacity management                             */
/* ------------------------------------------------------------------------- */

static ll_vector_status_t
_ll_vector_reserve_unlocked(ll_vector_t *vec, size_t min_capacity)
{
    if (min_capacity <= vec->capacity) { return LL_VECTOR_OK; }

    uint8_t *new_buf = realloc(vec->data, min_capacity * vec->element_size);
    if (!new_buf) {
        return LL_VECTOR_ERR_ALLOCATION;
    }
    /* Zero initialise the new memory for safety & deterministic tests */
    if (min_capacity > vec->capacity) {
        size_t newly_allocated_bytes = (min_capacity - vec->capacity)
                                        * vec->element_size;
        memset(new_buf + (vec->capacity * vec->element_size),
               0,
               newly_allocated_bytes);
    }

    vec->data     = new_buf;
    vec->capacity = min_capacity;
    return LL_VECTOR_OK;
}

ll_vector_status_t
ll_vector_reserve(ll_vector_t *vec, size_t new_capacity)
{
    if (!vec) { return LL_VECTOR_ERR_INVALID_ARG; }

    _LL_WRLOCK(vec);
    ll_vector_status_t st = _ll_vector_reserve_unlocked(vec, new_capacity);
    _LL_UNLOCK(vec);
    return st;
}

ll_vector_status_t
ll_vector_shrink_to_fit(ll_vector_t *vec)
{
    if (!vec) { return LL_VECTOR_ERR_INVALID_ARG; }

    _LL_WRLOCK(vec);

    if (vec->size == vec->capacity) {
        _LL_UNLOCK(vec);
        return LL_VECTOR_OK; /* Nothing to do. */
    }

    uint8_t *new_buf = realloc(vec->data,
                               (vec->size ? vec->size : 1U) * vec->element_size);
    if (!new_buf) {
        _LL_UNLOCK(vec);
        return LL_VECTOR_ERR_ALLOCATION;
    }

    vec->data     = new_buf;
    vec->capacity = (vec->size ? vec->size : 1U);

    _LL_UNLOCK(vec);
    return LL_VECTOR_OK;
}

/* ------------------------------------------------------------------------- */
/*                               Query helpers                               */
/* ------------------------------------------------------------------------- */

size_t
ll_vector_size(const ll_vector_t *vec)
{
    if (!vec) { return 0U; }
    _LL_RDLOCK((ll_vector_t *)vec);
    size_t s = vec->size;
    _LL_UNLOCK((ll_vector_t *)vec);
    return s;
}

size_t
ll_vector_capacity(const ll_vector_t *vec)
{
    if (!vec) { return 0U; }
    _LL_RDLOCK((ll_vector_t *)vec);
    size_t c = vec->capacity;
    _LL_UNLOCK((ll_vector_t *)vec);
    return c;
}

bool
ll_vector_is_empty(const ll_vector_t *vec)
{
    return ll_vector_size(vec) == 0U;
}

/* ------------------------------------------------------------------------- */
/*                           Utility / debugging                             */
/* ------------------------------------------------------------------------- */

#ifndef NDEBUG
void
ll_vector_debug_dump(const ll_vector_t *vec,
                     ll_element_debug_fn debug_fn,
                     FILE               *out_stream)
{
    if (!vec || !debug_fn) { return; }

    FILE *out = out_stream ? out_stream : stderr;

    _LL_RDLOCK((ll_vector_t *)vec);

    fprintf(out, "ll_vector@%p { size=%zu, capacity=%zu, elem_size=%zu }\n",
            (void *)vec, vec->size, vec->capacity, vec->element_size);

    for (size_t i = 0U; i < vec->size; ++i) {
        void *elem = vec->data + (i * vec->element_size);
        fprintf(out, "  [%zu] ", i);
        debug_fn(elem, out);
        fputc('\n', out);
    }

    _LL_UNLOCK((ll_vector_t *)vec);
}
#endif /* NDEBUG */

/* =============================================================================
 *                                    EOF
 * ============================================================================= */
