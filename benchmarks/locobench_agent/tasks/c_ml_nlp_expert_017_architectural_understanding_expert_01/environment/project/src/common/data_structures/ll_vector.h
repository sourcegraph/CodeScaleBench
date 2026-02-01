#ifndef LL_VECTOR_H
#define LL_VECTOR_H
/*
 *  LexiLearn Orchestrator — Common Data Structures
 *  ------------------------------------------------
 *  File:    ll_vector.h
 *  Author:  LexiLearn Core Team
 *  License: MIT
 *
 *  A small, production-ready, dynamically resizable vector that stores
 *  void* elements.  Designed for general-purpose use throughout the
 *  LexiLearn MVC Orchestrator code-base (data pipelines, model registry,
 *  experiment tracking, etc.).
 *
 *  Features
 *  --------
 *  • Generic interface (void* elements)
 *  • Custom element destructor callback
 *  • Amortised O(1) push_back / pop_back
 *  • Optional error-code out-param for branch-free fast paths
 *  • Safe “clear”, “shrink_to_fit”, and iterator macro
 *
 *  NOTE: All heavy-weight routines are implemented in ll_vector.c.
 */
#ifdef __cplusplus
extern "C" {
#endif

#include <stddef.h>   /* size_t   */
#include <stdint.h>   /* uint32_t */
#include <stdbool.h>  /* bool     */

/* -------------------------------------------------------------------------- */
/*                               Configuration                                */
/* -------------------------------------------------------------------------- */
#define LL_VECTOR_DEFAULT_CAPACITY 8U   /* Must be > 0                       */
#define LL_VECTOR_GROWTH_FACTOR    2U   /* Capacity *= 2 when full           */

/* -------------------------------------------------------------------------- */
/*                               Error Handling                               */
/* -------------------------------------------------------------------------- */
typedef enum ll_vector_status_e
{
    LL_VECTOR_STATUS_OK = 0,
    LL_VECTOR_STATUS_OOM,               /* Out-of-memory                     */
    LL_VECTOR_STATUS_INDEX_OOB,         /* Index out-of-bounds               */
    LL_VECTOR_STATUS_INVALID_ARGUMENT   /* NULL ptr or otherwise invalid     */
} ll_vector_status_t;

/* -------------------------------------------------------------------------- */
/*                         Forward Declarations                               */
/* -------------------------------------------------------------------------- */
typedef void (*ll_vector_elem_destructor_cb)(void *elem);

/*
 *  Publicly visible structure; fields are *read-only* for callers.
 *  Mutating them directly breaks invariants—use API functions instead.
 */
typedef struct ll_vector_t
{
    size_t  size;            /* Logical number of elements                */
    size_t  capacity;        /* Allocated slots in data[]                 */
    void  **data;            /* Heap-allocated C-array of void*           */
    ll_vector_elem_destructor_cb destructor_cb;   /* Optional element dtor */
} ll_vector_t;

/* -------------------------------------------------------------------------- */
/*                              API Functions                                 */
/* -------------------------------------------------------------------------- */

/*
 *  ll_vector_create
 *  ----------------
 *  Returns a freshly allocated vector or NULL on allocation failure.
 *  Pass `initial_capacity == 0` to use LL_VECTOR_DEFAULT_CAPACITY.
 */
ll_vector_t *
ll_vector_create(size_t                     initial_capacity,
                 ll_vector_elem_destructor_cb destructor_cb);

/*
 *  ll_vector_destroy
 *  -----------------
 *  Calls registered destructor on each element (if provided),
 *  frees underlying storage, then frees the vector itself.
 */
void
ll_vector_destroy(ll_vector_t *vec);

/*
 *  ll_vector_clear
 *  ---------------
 *  Clears the vector in-place but preserves capacity and buffer.
 *  Each element is destroyed via the registered callback.
 */
ll_vector_status_t
ll_vector_clear(ll_vector_t *vec);

/*
 *  ll_vector_push_back
 *  -------------------
 *  Appends `elem` to the end of the vector, resizing if necessary.
 */
ll_vector_status_t
ll_vector_push_back(ll_vector_t *vec, void *elem);

/*
 *  ll_vector_pop_back
 *  ------------------
 *  Removes and returns the last element or NULL if empty.
 *  If `out_status` is NOT NULL it will be filled accordingly.
 */
void *
ll_vector_pop_back(ll_vector_t *vec, ll_vector_status_t *out_status);

/*
 *  ll_vector_get / ll_vector_set
 *  -----------------------------
 *  Random-access getter / setter.
 *  On error (index out-of-bounds) getter returns NULL and status is set.
 */
void *
ll_vector_get(const ll_vector_t *vec, size_t idx, ll_vector_status_t *out_status);

ll_vector_status_t
ll_vector_set(ll_vector_t *vec, size_t idx, void *elem);

/*
 *  ll_vector_resize
 *  ----------------
 *  Changes logical size.  If growing, new slots are NULL-initialised.
 */
ll_vector_status_t
ll_vector_resize(ll_vector_t *vec, size_t new_size);

/*
 *  ll_vector_reserve / ll_vector_shrink_to_fit
 *  ------------------------------------------
 */
ll_vector_status_t
ll_vector_reserve(ll_vector_t *vec, size_t new_capacity);

ll_vector_status_t
ll_vector_shrink_to_fit(ll_vector_t *vec);

/* -------------------------------------------------------------------------- */
/*                       Lightweight Inline Helpers                           */
/* -------------------------------------------------------------------------- */
static inline size_t
ll_vector_size(const ll_vector_t *vec)
{
    return vec ? vec->size : 0U;
}

static inline size_t
ll_vector_capacity(const ll_vector_t *vec)
{
    return vec ? vec->capacity : 0U;
}

/*
 *  LL_VECTOR_FOREACH
 *  -----------------
 *  Example:
 *      LL_VECTOR_FOREACH(char*, word, my_vec) {
 *          printf("%s\n", word);
 *      }
 *
 *  Warning: Iteration is *not* safe against concurrent modifications.
 */
#define LL_VECTOR_FOREACH(elem_type, it_var, vec_ptr)                         \
    for (size_t _ll_i = 0;                                                    \
         (vec_ptr) != NULL && _ll_i < (vec_ptr)->size                         \
         && (((it_var) = (elem_type)(vec_ptr)->data[_ll_i]), true);           \
         ++_ll_i)

/* -------------------------------------------------------------------------- */

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* LL_VECTOR_H */
