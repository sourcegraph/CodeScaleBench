#ifndef HOLOCANVAS_WALLET_PROXY_ADAPTERS_H
#define HOLOCANVAS_WALLET_PROXY_ADAPTERS_H
/*
 * HoloCanvas – Wallet-Proxy
 * adapters.h
 *
 * A generic, pluggable interface used by the Wallet-Proxy micro-service to
 * communicate with heterogeneous chain wallets (hardware devices, mobile apps,
 * browser extensions, daemon processes, etc.).  Adapters implement this
 * interface and are registered at run-time—either through static linking or by
 * loading shared-object plug-ins—so that higher-level business logic can remain
 * completely chain- and wallet-agnostic.
 *
 * This header is intentionally self-contained and provides both the public API
 * and a small reference implementation for the adapter registry.  It may be
 * compiled in multiple translation units without ODR issues by defining
 * HOLOCANVAS_WALLET_PROXY_ADAPTERS_IMPL in exactly one of them.
 *
 * Thread-safety: The registry is protected by a pthread mutex and may be
 * concurrently accessed from multiple threads.
 */

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <pthread.h>

#ifdef __cplusplus
extern "C" {
#endif

/* --------------------------------------------------------------------------
 * Capability bit-flags describing the features supported by an adapter
 * -------------------------------------------------------------------------- */
enum hc_wallet_capability {
    HC_WALLET_CAP_SIGN_TX      = 0x01, /* can sign arbitrary transactions            */
    HC_WALLET_CAP_SUBMIT_TX    = 0x02, /* can broadcast signed transactions           */
    HC_WALLET_CAP_QUERY_BAL    = 0x04, /* can query on-chain balance                  */
    HC_WALLET_CAP_EVENTS       = 0x08, /* can stream account-level events / logs      */
    HC_WALLET_CAP_OFFLINE      = 0x10, /* works offline (e.g., hardware wallet)       */
    HC_WALLET_CAP_MULTI_SIG    = 0x20  /* supports multi-sig workflows                */
};

/* --------------------------------------------------------------------------
 * Error codes returned by adapters
 * -------------------------------------------------------------------------- */
typedef enum hc_wallet_err {
    HC_WALLET_OK           = 0,
    HC_WALLET_EINVALID     = -1,
    HC_WALLET_ENOTSUP      = -2,
    HC_WALLET_EIO          = -3,
    HC_WALLET_EBUSY        = -4,
    HC_WALLET_ESTATE       = -5,
    HC_WALLET_ECRYPTO      = -6,
    HC_WALLET_EUNKNOWN     = -255
} hc_wallet_err_t;

/* --------------------------------------------------------------------------
 * Chain identifiers (extendable)
 * -------------------------------------------------------------------------- */
typedef enum hc_chain {
    HC_CHAIN_ETHEREUM = 1,
    HC_CHAIN_POLYGON  = 137,
    HC_CHAIN_SOLANA   = 501,
    HC_CHAIN_UNKNOWN  = 0xFFFF
} hc_chain_t;

/* --------------------------------------------------------------------------
 * Forward declaration of adapter context handle
 * -------------------------------------------------------------------------- */
typedef struct hc_wallet_ctx_s hc_wallet_ctx_t;

/* --------------------------------------------------------------------------
 * Virtual function table for wallet operations
 * -------------------------------------------------------------------------- */
typedef struct hc_wallet_adapter_vtbl {
    /* Allocate adapter-specific context; return HC_WALLET_OK on success        */
    hc_wallet_err_t (*init)       (hc_wallet_ctx_t **out_ctx,
                                   const char       *config_json);

    /* Release context                                                          */
    hc_wallet_err_t (*deinit)     (hc_wallet_ctx_t  *ctx);

    /* Return the public address for this wallet (hex/base58, NUL-terminated)   */
    hc_wallet_err_t (*get_address)(hc_wallet_ctx_t  *ctx,
                                   char             *out_addr,
                                   size_t            out_size);

    /* Query native token balance (wei/lamports/etc.)                           */
    hc_wallet_err_t (*get_balance)(hc_wallet_ctx_t  *ctx,
                                   uint64_t         *out_balance);

    /* Sign an unsigned, RLP/BCS/raw transaction                                */
    hc_wallet_err_t (*sign_tx)    (hc_wallet_ctx_t  *ctx,
                                   const uint8_t    *tx_raw,
                                   size_t            tx_len,
                                   uint8_t          *out_sig,
                                   size_t           *inout_sig_len);

    /* Broadcast a signed transaction                                           */
    hc_wallet_err_t (*submit_tx)  (hc_wallet_ctx_t  *ctx,
                                   const uint8_t    *signed_tx,
                                   size_t            tx_len,
                                   char             *out_tx_hash,
                                   size_t            hash_len);

    /* Blocking event stream; invokes user callback per event                   */
    hc_wallet_err_t (*poll_events)(hc_wallet_ctx_t  *ctx,
                                   void (*cb)(const char *event_json,
                                              void       *user_data),
                                   void *user_data,
                                   uint32_t          timeout_ms);

    /* Optional: human-readable error for the last adapter failure              */
    const char     *(*last_error) (hc_wallet_ctx_t  *ctx);
} hc_wallet_adapter_vtbl_t;

/* --------------------------------------------------------------------------
 * Public descriptor exposed by each adapter
 * -------------------------------------------------------------------------- */
typedef struct hc_wallet_adapter {
    const char                   *name;         /* unique, lower-snake-case id  */
    hc_chain_t                    chain;        /* primary chain supported      */
    uint32_t                      capabilities; /* bitmask from hc_wallet_cap…  */
    hc_wallet_adapter_vtbl_t      vtbl;         /* function table               */
} hc_wallet_adapter_t;

/* ==========================================================================
 * Adapter Registry – API
 * ========================================================================== */

/*
 * Register an adapter with the global registry.  Ownership of the descriptor
 * remains with the caller (typically a static const struct).  Safe to call
 * multiple times for the same pointer; duplicates are ignored.
 */
hc_wallet_err_t
hc_wallet_registry_register(const hc_wallet_adapter_t *adapter);

/* Remove previously registered adapter */
hc_wallet_err_t
hc_wallet_registry_unregister(const hc_wallet_adapter_t *adapter);

/* Find adapter by name (case-sensitive) */
const hc_wallet_adapter_t *
hc_wallet_registry_find(const char *name);

/* Iterate over all adapters; iteration is performed under a read lock. */
void
hc_wallet_registry_foreach(void (*cb)(const hc_wallet_adapter_t *adapter,
                                      void                     *user_data),
                           void *user_data);

/*
 * Convenience macro to statically export an adapter from a translation unit.
 * Example:
 *
 *    static const hc_wallet_adapter_t my_adapter = { … };
 *    HC_WALLET_ADAPTER_EXPORT(my_adapter);
 */
#define HC_WALLET_ADAPTER_EXPORT(_adapter_symbol)                    \
    static void __attribute__((constructor))                         \
    _hc_wallet_adapter_ctor_##_adapter_symbol(void)                  \
    {                                                                \
        hc_wallet_registry_register(&_adapter_symbol);               \
    }                                                                \
    static void __attribute__((destructor))                          \
    _hc_wallet_adapter_dtor_##_adapter_symbol(void)                  \
    {                                                                \
        hc_wallet_registry_unregister(&_adapter_symbol);             \
    }

/* ==========================================================================
 * Reference implementation – compiled if HOLOCANVAS_WALLET_PROXY_ADAPTERS_IMPL
 * ========================================================================== */
#ifdef HOLOCANVAS_WALLET_PROXY_ADAPTERS_IMPL

#include <stdlib.h>
#include <string.h>
#include <errno.h>

/* Internal linked-list node */
typedef struct hc_adapter_node {
    const hc_wallet_adapter_t *adapter;
    struct hc_adapter_node    *next;
} hc_adapter_node_t;

/* Head of the list and its mutex */
static hc_adapter_node_t  *g_adapters      = NULL;
static pthread_rwlock_t    g_registry_lock = PTHREAD_RWLOCK_INITIALIZER;

static bool
hc_adapter_already_registered(const hc_wallet_adapter_t *adapter)
{
    for (hc_adapter_node_t *n = g_adapters; n; n = n->next)
        if (n->adapter == adapter)
            return true;
    return false;
}

hc_wallet_err_t
hc_wallet_registry_register(const hc_wallet_adapter_t *adapter)
{
    if (!adapter || !adapter->name)
        return HC_WALLET_EINVALID;

    if (pthread_rwlock_wrlock(&g_registry_lock) != 0)
        return HC_WALLET_EBUSY;

    if (hc_adapter_already_registered(adapter)) {
        pthread_rwlock_unlock(&g_registry_lock);
        return HC_WALLET_OK; /* idempotent */
    }

    hc_adapter_node_t *node = (hc_adapter_node_t *)calloc(1, sizeof(*node));
    if (!node) {
        pthread_rwlock_unlock(&g_registry_lock);
        return HC_WALLET_EIO;
    }
    node->adapter = adapter;
    node->next    = g_adapters;
    g_adapters    = node;

    pthread_rwlock_unlock(&g_registry_lock);
    return HC_WALLET_OK;
}

hc_wallet_err_t
hc_wallet_registry_unregister(const hc_wallet_adapter_t *adapter)
{
    if (!adapter)
        return HC_WALLET_EINVALID;

    if (pthread_rwlock_wrlock(&g_registry_lock) != 0)
        return HC_WALLET_EBUSY;

    hc_adapter_node_t **pp = &g_adapters;
    while (*pp) {
        if ((*pp)->adapter == adapter) {
            hc_adapter_node_t *victim = *pp;
            *pp = victim->next;
            free(victim);
            pthread_rwlock_unlock(&g_registry_lock);
            return HC_WALLET_OK;
        }
        pp = &(*pp)->next;
    }

    pthread_rwlock_unlock(&g_registry_lock);
    return HC_WALLET_EINVALID; /* not found */
}

const hc_wallet_adapter_t *
hc_wallet_registry_find(const char *name)
{
    if (!name)
        return NULL;

    if (pthread_rwlock_rdlock(&g_registry_lock) != 0)
        return NULL;

    for (hc_adapter_node_t *n = g_adapters; n; n = n->next) {
        if (strcmp(n->adapter->name, name) == 0) {
            const hc_wallet_adapter_t *result = n->adapter;
            pthread_rwlock_unlock(&g_registry_lock);
            return result;
        }
    }
    pthread_rwlock_unlock(&g_registry_lock);
    return NULL;
}

void
hc_wallet_registry_foreach(void (*cb)(const hc_wallet_adapter_t *, void *),
                           void *user_data)
{
    if (!cb)
        return;

    if (pthread_rwlock_rdlock(&g_registry_lock) != 0)
        return;

    for (hc_adapter_node_t *n = g_adapters; n; n = n->next)
        cb(n->adapter, user_data);

    pthread_rwlock_unlock(&g_registry_lock);
}

#endif /* HOLOCANVAS_WALLET_PROXY_ADAPTERS_IMPL */

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* HOLOCANVAS_WALLET_PROXY_ADAPTERS_H */
