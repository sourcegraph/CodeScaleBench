/*
 *  feeds.h
 *  HoloCanvas :: Oracle-Bridge Service
 *
 *  SPDX-License-Identifier: Apache-2.0
 *
 *  Description:
 *      Public API for the Oracle-Bridge “Feeds” subsystem.  A feed is a
 *      time-series data stream (e.g. ETH/USD price, weather sensor, DAO vote
 *      tally) that can be consumed by other HoloCanvas micro-services or
 *      on-chain smart-contracts.  This header exposes:
 *
 *          • Lifecycle management: init/shutdown
 *          • Registration / deregistration of feeds
 *          • Publishing updates
 *          • In-process subscription callbacks
 *          • Synchronous read of the latest value
 *          • Pluggable allocators + error codes
 *
 *      The implementation lives in:
 *          services/oracle_bridge/src/feeds.c
 */

#ifndef HOLOCANVAS_ORACLE_BRIDGE_FEEDS_H
#define HOLOCANVAS_ORACLE_BRIDGE_FEEDS_H

/*–––––––––––––––––––––––––––––––––––––––  Dependencies  –––––––––––––––––––––––––––––––––––––––*/
#include <stddef.h>     /* size_t                         */
#include <stdint.h>     /* uint*_t                       */
#include <time.h>       /* time_t                        */

#ifdef __cplusplus
extern "C" {
#endif

/*–––––––––––––––––––––––––––––––––––––  Compile-time Config  –––––––––––––––––––––––––––––––––––*/
#define OC_FEED_MAX_NAME_LEN        64U
#define OC_FEED_MAX_DESC_LEN        256U
#define OC_FEED_MAX_SYMBOL_LEN      16U

/*–––––––––––––––––––––––––––––––––––––––  Error Codes  ––––––––––––––––––––––––––––––––––––––––*/
typedef enum oc_feed_err_e
{
    OC_FEED_OK            =  0,   /* Success                                            */
    OC_FEED_EINIT         = -1,   /* Subsystem not initialised                          */
    OC_FEED_EINVAL        = -2,   /* Invalid argument                                   */
    OC_FEED_ENOMEM        = -3,   /* Allocation failure                                 */
    OC_FEED_ENOENT        = -4,   /* Feed not found                                     */
    OC_FEED_EEXISTS       = -5,   /* Feed already registered                            */
    OC_FEED_EBUSY         = -6,   /* Feed currently locked                              */
    OC_FEED_EOVERFLOW     = -7,   /* Buffer too small / index overflow                  */
    OC_FEED_ETIMEOUT      = -8,   /* Operation timed out                                */
    OC_FEED_EUNKNOWN      = -9    /* Unknown / internal error                           */
} oc_feed_err_t;

/*––––––––––––––––––––––––––––––––––––––––  Typedefs  ––––––––––––––––––––––––––––––––––––––––––*/
typedef uint64_t oc_feed_id_t;

/* Feed content encoding */
typedef enum oc_feed_format_e
{
    OC_FEED_FMT_UNSPEC   = 0,
    OC_FEED_FMT_FLOAT64  = 1,   /* double (IEEE-754) */
    OC_FEED_FMT_UINT64   = 2,   /* unsigned 64-bit   */
    OC_FEED_FMT_CBOR     = 3,   /* RFC 8949          */
    OC_FEED_FMT_JSON     = 4,   /* UTF-8 JSON text   */
    OC_FEED_FMT_BLOB     = 5    /* arbitrary bytes   */
} oc_feed_format_t;

/* Feed category — may guide routing & ACLs */
typedef enum oc_feed_kind_e
{
    OC_FEED_KIND_PRICE     = 1,   /* Fiat/crypto price oracle                      */
    OC_FEED_KIND_SENSOR    = 2,   /* IoT / real-world sensor data                  */
    OC_FEED_KIND_GOVERN    = 3,   /* Governance / DAO votes                        */
    OC_FEED_KIND_CUSTOM    = 255  /* Application-defined                           */
} oc_feed_kind_t;

/* Feed Quality-of-Service options */
typedef struct oc_feed_qos_s
{
    uint32_t heartbeat_sec;   /* Expected update interval (0 = not specified)   */
    uint32_t grace_sec;       /* Allowed delay before marking stale             */
    double   min_confidence;  /* Minimum acceptable confidence (NaN = ignore)   */
} oc_feed_qos_t;

/* Feed metadata (immutable after registration) */
typedef struct oc_feed_meta_s
{
    oc_feed_id_t     id;                                  /* Unique identifier (caller provided or 0 to auto-generate) */
    oc_feed_kind_t   kind;                                /* Category of feed                                          */
    oc_feed_format_t format;                              /* Encoding of value payload                                */
    char             name[OC_FEED_MAX_NAME_LEN];          /* Human-readable name                                       */
    char             description[OC_FEED_MAX_DESC_LEN];   /* Longer description                                        */
    char             symbol[OC_FEED_MAX_SYMBOL_LEN];      /* Ticker-like short code (e.g. “ETHUSD”)                    */
    uint8_t          decimals;                            /* Display precision (if numeric)                           */
    oc_feed_qos_t    qos;                                 /* QoS constraints                                           */
    void            *user_data;                           /* Application context pointer                               */
} oc_feed_meta_t;

/* Live feed value */
typedef struct oc_feed_update_s
{
    oc_feed_id_t  id;          /* Feed identifier                                    */
    uint64_t      sequence;    /* Monotonically increasing sequence number           */
    time_t        timestamp;   /* UNIX epoch                                         */
    double        confidence;  /* 0-1 range or NaN if not applicable                 */
    const void   *data;        /* Pointer to payload                                 */
    size_t        data_len;    /* Length of payload in bytes                         */
} oc_feed_update_t;

/* Subscription callback */
typedef void (*oc_feed_sub_cb)(const oc_feed_update_t *update, void *ctx);

/* Custom allocator hooks (optional) */
typedef void *(*oc_feed_malloc_fn)(size_t);
typedef void (*oc_feed_free_fn)(void *);

/*––––––––––––––––––––––––––––––––––  Public API — Lifecycle  –––––––––––––––––––––––––––––––––––*/

/*
 *  oc_feed_init
 *  ------------
 *  Initialise the feeds subsystem.  Must be called once during service start-up.
 *
 *  @return OC_FEED_OK on success.
 */
oc_feed_err_t oc_feed_init(void);

/*
 *  oc_feed_shutdown
 *  ----------------
 *  Gracefully shut down the subsystem, flushing pending updates and freeing
 *  allocated resources.  All subscriptions are cancelled.
 */
oc_feed_err_t oc_feed_shutdown(void);

/*
 *  oc_feed_set_allocator
 *  ---------------------
 *  Install custom malloc/free functions.  Must be called BEFORE oc_feed_init().
 */
void oc_feed_set_allocator(oc_feed_malloc_fn malloc_fn,
                           oc_feed_free_fn   free_fn);

/*––––––––––––––––––––––––––––––––  Public API — Registration  ––––––––––––––––––––––––––––––––––*/

/*
 *  oc_feed_register
 *  ----------------
 *  Register a new feed.  If meta->id == 0, a 64-bit non-zero identifier is
 *  auto-generated and written back to meta->id.
 */
oc_feed_err_t oc_feed_register(oc_feed_meta_t *meta /* IN/OUT */);

/*
 *  oc_feed_unregister
 *  ------------------
 *  Remove a previously registered feed.  Fails if there are active subscribers.
 */
oc_feed_err_t oc_feed_unregister(oc_feed_id_t id);

/*–––––––––––––––––––––––––––––––  Public API — Publishing  ––––––––––––––––––––––––––––––––––––*/

/*
 *  oc_feed_update_push
 *  -------------------
 *  Publish a new value for the given feed.  Ownership of 'data' remains with the
 *  caller; the buffers are copied internally if needed.
 */
oc_feed_err_t oc_feed_update_push(const oc_feed_update_t *update);

/*–––––––––––––––––––––––––––––––  Public API — Consumption  –––––––––––––––––––––––––––––––––––*/

/*
 *  oc_feed_subscribe
 *  -----------------
 *  Register an in-process callback for feed updates.
 *
 *  @param replay_last   If non-zero, immediately invoke the callback with the
 *                       most recent value (if any).
 */
oc_feed_err_t oc_feed_subscribe(oc_feed_id_t    id,
                                oc_feed_sub_cb  cb,
                                void           *ctx,
                                int             replay_last);

/*
 *  oc_feed_unsubscribe
 *  -------------------
 *  Detach a previously registered callback.
 */
oc_feed_err_t oc_feed_unsubscribe(oc_feed_id_t   id,
                                  oc_feed_sub_cb cb,
                                  void          *ctx);

/*
 *  oc_feed_get_latest
 *  ------------------
 *  Blocking read of the latest value.  Caller provides storage for the
 *  oc_feed_update_t header; the payload data is copied into *data_buf.
 *
 *  @param data_buf      Destination buffer, can be NULL to query required size.
 *  @param io_len        IN:  capacity of data_buf
 *                       OUT: actual length written (or required size if buffer
 *                            was NULL/too small)
 */
oc_feed_err_t oc_feed_get_latest(oc_feed_id_t       id,
                                 oc_feed_update_t  *update_hdr /* OUT */,
                                 void              *data_buf   /* OUT */,
                                 size_t            *io_len     /* IN/OUT */);

/*––––––––––––––––––––––––––––––  Utility — ID Generation  ––––––––––––––––––––––––––––––––––––*/

/*
 *  oc_feed_generate_id
 *  -------------------
 *  Deterministically derive a 64-bit feed identifier from a “namespace/name”
 *  string pair using FNV-1a 64-bit hashing.  This helper is header-only for
 *  convenience.
 */
static inline oc_feed_id_t
oc_feed_generate_id(const char *ns,
                    const char *name)
{
    /* 64-bit FNV-1a parameters */
    const uint64_t FNV_OFFSET_BASIS = 0xcbf29ce484222325ULL;
    const uint64_t FNV_PRIME        = 0x100000001b3ULL;

    if (!ns || !name) { return 0ULL; }

    uint64_t hash = FNV_OFFSET_BASIS;
    const unsigned char *p;

    for (p = (const unsigned char *)ns; *p; ++p) {
        hash ^= *p;
        hash *= FNV_PRIME;
    }
    hash ^= (unsigned char)'/';
    hash *= FNV_PRIME;
    for (p = (const unsigned char *)name; *p; ++p) {
        hash ^= *p;
        hash *= FNV_PRIME;
    }
    /* Zero reserved as “invalid / auto-generate”, so nudge if needed */
    return (hash == 0ULL) ? 0x1ULL : hash;
}

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* HOLOCANVAS_ORACLE_BRIDGE_FEEDS_H */
