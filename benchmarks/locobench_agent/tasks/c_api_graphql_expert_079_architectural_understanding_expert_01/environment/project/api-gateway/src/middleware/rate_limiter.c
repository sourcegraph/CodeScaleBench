/*
 * SynestheticCanvas API Gateway
 * File: middleware/rate_limiter.c
 *
 * Description:
 *   Thread-safe, token-bucket rate-limiter middleware.  A single instance
 *   protects the gateway from abusive callers while remaining lightweight
 *   enough for millisecond-level latency budgets.  Each client (typically an
 *   auth-subject or IP address) receives an independent bucket that refills
 *   at a configurable rate.  Buckets are garbage-collected when inactive.
 *
 *   Dependencies:
 *     - POSIX Threads
 *     - uthash (header-only hash-table <https://troydhanson.github.io/uthash/>)
 *
 * Copyright (c) 2024
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <time.h>
#include <errno.h>
#include <pthread.h>
#include <inttypes.h>

#include "uthash.h"               /* Header-only hash map */
#include "rate_limiter.h"         /* Public interface */
#include "gateway_logger.h"       /* Centralised logging macros */
#include "gateway_metrics.h"      /* Metrics sink (counters, gauges, histograms) */

/* --------------------------------------------------------------------------
 * Internal helpers
 * --------------------------------------------------------------------------*/

#define NS_PER_SEC 1000000000LL
#define SEC_TO_NS(x) ((long long)(x) * NS_PER_SEC)

static inline int64_t
timespec_to_ns(const struct timespec *ts)
{
    return (int64_t)ts->tv_sec * NS_PER_SEC + ts->tv_nsec;
}

static inline void
ns_to_timespec(int64_t ns, struct timespec *ts)
{
    ts->tv_sec  = (time_t)(ns / NS_PER_SEC);
    ts->tv_nsec = (long)(ns % NS_PER_SEC);
}

static inline int64_t
clock_now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return timespec_to_ns(&ts);
}

/* --------------------------------------------------------------------------
 * Token bucket representation
 * --------------------------------------------------------------------------*/

typedef struct rl_bucket_s
{
    char            key[64];      /* client-identifier */
    double          tokens;       /* current token count */
    double          capacity;     /* max tokens */
    double          refill_rate;  /* tokens per second */
    int64_t         last_ns;      /* last refill timestamp (ns) */
    uint32_t        generation;   /* incremented on refresh (for GC) */
    UT_hash_handle  hh;           /* uthash handler */
} rl_bucket_t;

/* --------------------------------------------------------------------------
 * Rate-limiter state
 * --------------------------------------------------------------------------*/

struct rate_limiter_s
{
    pthread_mutex_t lock;
    rl_bucket_t    *buckets;
    size_t          max_clients;
    double          capacity;
    double          refill_rate;
    uint32_t        generation;      /* global GC counter */
    uint32_t        gc_threshold;    /* generations before eviction */
};

/* --------------------------------------------------------------------------
 * Bucket manipulation
 * --------------------------------------------------------------------------*/

/* Bring bucket up-to-date with elapsed time */
static void
rl_refill_bucket(rl_bucket_t *bucket, int64_t now_ns)
{
    if (now_ns <= bucket->last_ns)
        return;

    const double elapsed = (double)(now_ns - bucket->last_ns) / (double)NS_PER_SEC;
    const double new_tokens = bucket->tokens + elapsed * bucket->refill_rate;
    bucket->tokens  = new_tokens > bucket->capacity ? bucket->capacity : new_tokens;
    bucket->last_ns = now_ns;
}

/* --------------------------------------------------------------------------
 * Public interface implementation
 * --------------------------------------------------------------------------*/

rate_limiter_t *
rate_limiter_create(size_t    max_clients,
                    double    capacity,
                    double    refill_rate,
                    uint32_t  gc_threshold)
{
    if (capacity <= 0.0 || refill_rate <= 0.0) {
        GW_LOG_ERROR("Invalid rate-limiter parameters (capacity=%f, refill=%f)",
                     capacity, refill_rate);
        errno = EINVAL;
        return NULL;
    }

    rate_limiter_t *rl = calloc(1, sizeof(*rl));
    if (!rl) {
        GW_LOG_SYSERROR("calloc");
        return NULL;
    }

    rl->max_clients   = max_clients;
    rl->capacity      = capacity;
    rl->refill_rate   = refill_rate;
    rl->gc_threshold  = gc_threshold ? gc_threshold : 5; /* default */
    rl->generation    = 0;

    if (pthread_mutex_init(&rl->lock, NULL) != 0) {
        GW_LOG_SYSERROR("pthread_mutex_init");
        free(rl);
        return NULL;
    }

    GW_LOG_INFO("Rate-limiter created (max_clients=%zu, cap=%.2f, refill=%.2f/s)",
                max_clients, capacity, refill_rate);
    return rl;
}

static rl_bucket_t *
rl_get_or_create_bucket(rate_limiter_t *rl,
                        const char     *key,
                        int64_t         now_ns)
{
    rl_bucket_t *bucket = NULL;
    HASH_FIND_STR(rl->buckets, key, bucket);
    if (bucket)
        return bucket;

    /* Enforce client limit */
    if (rl->max_clients && HASH_COUNT(rl->buckets) >= rl->max_clients) {
        /* Simple heuristic: refuse new bucket to protect memory */
        GW_METRIC_COUNTER_INC("rl.reject.too_many_clients", 1);
        return NULL;
    }

    bucket = calloc(1, sizeof(*bucket));
    if (!bucket) {
        GW_LOG_SYSERROR("calloc");
        return NULL;
    }

    strncpy(bucket->key, key, sizeof(bucket->key) - 1);
    bucket->capacity    = rl->capacity;
    bucket->refill_rate = rl->refill_rate;
    bucket->tokens      = rl->capacity;          /* start full */
    bucket->last_ns     = now_ns;
    bucket->generation  = rl->generation;

    HASH_ADD_STR(rl->buckets, key, bucket);
    return bucket;
}

bool
rate_limiter_allow(rate_limiter_t *rl,
                   const char     *client_key,
                   double          cost)
{
    if (!rl || !client_key || cost <= 0)
        return false;

    const int64_t now_ns = clock_now_ns();
    bool allow = false;

    pthread_mutex_lock(&rl->lock);

    rl_bucket_t *bucket = rl_get_or_create_bucket(rl, client_key, now_ns);
    if (!bucket) {
        pthread_mutex_unlock(&rl->lock);
        return false;
    }

    rl_refill_bucket(bucket, now_ns);

    if (bucket->tokens >= cost) {
        bucket->tokens -= cost;
        allow = true;
        GW_METRIC_COUNTER_INC("rl.request.allowed", 1);
    } else {
        GW_METRIC_COUNTER_INC("rl.request.denied", 1);
    }

    pthread_mutex_unlock(&rl->lock);
    return allow;
}

void
rate_limiter_tick(rate_limiter_t *rl)
{
    /* Periodic maintenance called by gateway (e.g., every 30s) */
    if (!rl)
        return;

    const int64_t now_ns = clock_now_ns();

    pthread_mutex_lock(&rl->lock);
    rl->generation++;

    rl_bucket_t *bucket, *tmp;
    HASH_ITER(hh, rl->buckets, bucket, tmp) {

        rl_refill_bucket(bucket, now_ns);

        /* Evict inactive buckets */
        if (rl->generation - bucket->generation >= rl->gc_threshold &&
            bucket->tokens >= bucket->capacity)
        {
            HASH_DEL(rl->buckets, bucket);
            free(bucket);
            GW_METRIC_COUNTER_INC("rl.bucket.evicted", 1);
        }
    }
    pthread_mutex_unlock(&rl->lock);
}

void
rate_limiter_destroy(rate_limiter_t *rl)
{
    if (!rl)
        return;

    pthread_mutex_lock(&rl->lock);
    rl_bucket_t *bucket, *tmp;
    HASH_ITER(hh, rl->buckets, bucket, tmp) {
        HASH_DEL(rl->buckets, bucket);
        free(bucket);
    }
    pthread_mutex_unlock(&rl->lock);

    pthread_mutex_destroy(&rl->lock);
    free(rl);
}

/* --------------------------------------------------------------------------
 * Gateway middleware adapter
 * --------------------------------------------------------------------------*/

/*
 * The following function bridges the standalone limiter with the gateway’s
 * request pipeline.  It must be registered during gateway startup:
 *
 *     gateway_register_middleware(rate_limiter_middleware, rl);
 */
gateway_result_t
rate_limiter_middleware(gw_request_t   *req,
                        gw_response_t  *res,
                        void           *user_data)
{
    rate_limiter_t *rl = (rate_limiter_t *)user_data;
    const char *client = gw_request_client_id(req); /* usually IP or auth id */

    if (!rate_limiter_allow(rl, client, 1.0)) {
        gw_response_set_status(res, 429);          /* Too Many Requests */
        gw_response_set_header(res, "Retry-After", "1"); /* advisory */
        gw_response_set_body(res, "rate limit exceeded", 19);
        return GW_RES_COMPLETE;                    /* stop pipeline here */
    }

    return GW_RES_NEXT;                            /* continue processing */
}