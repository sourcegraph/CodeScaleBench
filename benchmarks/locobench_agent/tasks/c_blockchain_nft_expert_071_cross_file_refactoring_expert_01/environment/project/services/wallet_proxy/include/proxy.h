```c
/*
 *  HoloCanvas Wallet-Proxy
 *  File: proxy.h
 *
 *  Description:
 *      Public API for the Wallet-Proxy micro-service.  The Wallet-Proxy
 *      implements a Proxy-Pattern façade that abstracts over multiple
 *      blockchain back-ends (L1, rollup, test-nets, hardware wallets,
 *      etc.).  All wallet operations (signing, broadcasting, querying,
 *      event streaming) are exposed through a common, pluggable v-table
 *      interface so that new chain adapters can be added at run-time
 *      without impacting the rest of the platform.
 *
 *  NOTE:
 *      This header is intentionally C-only (no C++ STL) to keep the core
 *      of HoloCanvas fully portable and embeddable in constrained or
 *      kernel-space environments.
 */

#ifndef HOLOCANVAS_WALLET_PROXY_H
#define HOLOCANVAS_WALLET_PROXY_H

/*─────────────────────────────
 *  System & Standard Headers
 *─────────────────────────────*/
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*─────────────────────────────
 *  Versioning & Visibility
 *─────────────────────────────*/
#define HC_WLT_PROXY_VERSION_MAJOR   1
#define HC_WLT_PROXY_VERSION_MINOR   0
#define HC_WLT_PROXY_VERSION_PATCH   2

#if defined(_WIN32) && defined(HC_WLT_PROXY_DLL)
/* Building / using as DLL on Windows. */
#  ifdef HC_WLT_PROXY_EXPORTS
#    define HC_WLT_API  __declspec(dllexport)
#  else
#    define HC_WLT_API  __declspec(dllimport)
#  endif
#else
#  define HC_WLT_API  __attribute__((visibility("default")))
#endif

/*─────────────────────────────
 *  Forward Declarations
 *─────────────────────────────*/
struct hc_wallet_proxy;
struct hc_wallet_provider;

/*─────────────────────────────
 *  Fundamental Types
 *─────────────────────────────*/

/* Fixed-size byte array used for addresses, hashes, signatures, etc. */
typedef struct hc_bytes
{
    uint8_t  *data;       /* Pointer to raw data (NOT ownership).     */
    size_t    len;        /* Number of bytes pointed to by `data`.    */
} hc_bytes_t;

/* Opaque handle of a transaction previously submitted. */
typedef struct hc_tx_handle
{
    uint64_t id;          /* Unique identifier within this proxy.     */
} hc_tx_handle_t;

/* Opaque handle to identify a subscribed event stream. */
typedef struct hc_evt_handle
{
    uint64_t id;          /* Unique identifier within this proxy.     */
} hc_evt_handle_t;

/* Standard error domain for the wallet proxy. */
typedef enum hc_wlt_err
{
    HC_WLT_OK                 =  0,
    HC_WLT_ERR_UNKNOWN        = -1,
    HC_WLT_ERR_INVALID_ARG    = -2,
    HC_WLT_ERR_NO_MEMORY      = -3,
    HC_WLT_ERR_NOT_SUPPORTED  = -4,
    HC_WLT_ERR_IO             = -5,
    HC_WLT_ERR_TIMEOUT        = -6,
    HC_WLT_ERR_DISCONNECTED   = -7,
    HC_WLT_ERR_AUTH           = -8,
    HC_WLT_ERR_BUSY           = -9
} hc_wlt_err_t;

/* Callback for async transaction broadcast completion. */
typedef void (*hc_tx_cb)(
        const hc_tx_handle_t *tx,
        bool                  success,
        const char           *err_msg,
        void                 *user_data);

/* Callback for chain events (log, receipt, state change, etc.). */
typedef void (*hc_evt_cb)(
        const hc_bytes_t     *encoded_evt,
        void                 *user_data);

/*─────────────────────────────
 *  Wallet Provider V-Table
 *─────────────────────────────*/

/*
 *  Each provider implements a concrete wallet back-end (e.g., Ethereum,
 *  Stark-based rollup, hardware Ledger, offline signer, etc.).
 *
 *  All functions MUST be thread-safe; the proxy is shared across the
 *  microservice’s worker pool.  Providers may maintain internal locks
 *  or use lock-free techniques.
 */
typedef struct hc_wallet_provider_vtable
{
    /*
     * Initialise provider resources (network sockets, key-stores …).
     * Returns HC_WLT_OK on success.
     */
    hc_wlt_err_t (*init)(struct hc_wallet_provider *prov,
                         const char                *config_uri);

    /* Gracefully tear down resources.  Called exactly once. */
    void (*shutdown)(struct hc_wallet_provider *prov);

    /* Network connectivity helpers. */
    hc_wlt_err_t (*connect)(struct hc_wallet_provider *prov);
    void         (*disconnect)(struct hc_wallet_provider *prov);

    /* Basic read-only wallet queries. */
    hc_wlt_err_t (*get_address)(struct hc_wallet_provider *prov,
                                hc_bytes_t                *out_addr);

    hc_wlt_err_t (*get_balance)(struct hc_wallet_provider *prov,
                                const hc_bytes_t          *asset_id,
                                uint64_t                  *out_balance);

    hc_wlt_err_t (*get_nonce)(struct hc_wallet_provider *prov,
                              uint64_t                  *out_nonce);

    /* Transaction workflow. */
    hc_wlt_err_t (*sign_tx)(struct hc_wallet_provider *prov,
                            const hc_bytes_t          *tx_blob,
                            hc_bytes_t                *out_signed_tx);

    hc_wlt_err_t (*broadcast_tx_async)(struct hc_wallet_provider *prov,
                                       const hc_bytes_t          *signed_tx,
                                       hc_tx_cb                   cb,
                                       void                      *user_data,
                                       hc_tx_handle_t            *out_handle);

    /* Event subscription. */
    hc_wlt_err_t (*subscribe_events)(struct hc_wallet_provider *prov,
                                     const char               *filter_expr,
                                     hc_evt_cb                 cb,
                                     void                     *user_data,
                                     hc_evt_handle_t          *out_handle);

    hc_wlt_err_t (*unsubscribe)(struct hc_wallet_provider *prov,
                                const hc_evt_handle_t     *handle);

} hc_wallet_provider_vtable_t;

/* Provider base type.  Concrete impls embed this as first member. */
typedef struct hc_wallet_provider
{
    const char                     *name;   /* e.g. "eth-infura", "ledger" */
    const hc_wallet_provider_vtable *vt;    /* Function table.             */
    void                            *state; /* Implementation-specific.    */
} hc_wallet_provider_t;

/*─────────────────────────────
 *  Wallet-Proxy Public Object
 *─────────────────────────────*/

/*
 *  The proxy is reference-counted so that multiple subsystems (REST
 *  façade, WebSocket push, Kafka listeners) can share a single wallet
 *  instance without complex ownership rules.
 */
typedef struct hc_wallet_proxy
{
    hc_wallet_provider_t *provider;     /* Selected back-end.            */
    volatile uint32_t     refcnt;       /* Atomic (see .c for impl).     */
} hc_wallet_proxy_t;

/*─────────────────────────────
 *  Public API
 *─────────────────────────────*/

/* Create a proxy from a provider (Takes a ref on `provider`). */
HC_WLT_API hc_wallet_proxy_t *
hc_wallet_proxy_create(hc_wallet_provider_t *provider);

/* Increment reference count (returns the same pointer for chaining). */
HC_WLT_API hc_wallet_proxy_t *
hc_wallet_proxy_retain(hc_wallet_proxy_t *proxy);

/* Decrement refcount and destroy on zero. */
HC_WLT_API void
hc_wallet_proxy_release(hc_wallet_proxy_t *proxy);

/* Inline convenience wrappers that delegate to provider v-table. */

static inline hc_wlt_err_t
hc_wallet_proxy_connect(hc_wallet_proxy_t *proxy)
{
    if (!proxy || !proxy->provider || !proxy->provider->vt) {
        return HC_WLT_ERR_INVALID_ARG;
    }
    return proxy->provider->vt->connect(proxy->provider);
}

static inline void
hc_wallet_proxy_disconnect(hc_wallet_proxy_t *proxy)
{
    if (proxy && proxy->provider && proxy->provider->vt &&
        proxy->provider->vt->disconnect) {
        proxy->provider->vt->disconnect(proxy->provider);
    }
}

static inline hc_wlt_err_t
hc_wallet_proxy_get_address(hc_wallet_proxy_t *proxy, hc_bytes_t *addr)
{
    if (!proxy || !addr) return HC_WLT_ERR_INVALID_ARG;
    return proxy->provider->vt->get_address(proxy->provider, addr);
}

static inline hc_wlt_err_t
hc_wallet_proxy_get_balance(hc_wallet_proxy_t *proxy,
                            const hc_bytes_t  *asset_id,
                            uint64_t          *balance)
{
    if (!proxy) return HC_WLT_ERR_INVALID_ARG;
    return proxy->provider->vt->get_balance(proxy->provider, asset_id, balance);
}

static inline hc_wlt_err_t
hc_wallet_proxy_sign_tx(hc_wallet_proxy_t *proxy,
                        const hc_bytes_t  *tx_blob,
                        hc_bytes_t        *signed_tx)
{
    if (!proxy || !tx_blob || !signed_tx) return HC_WLT_ERR_INVALID_ARG;
    return proxy->provider->vt->sign_tx(proxy->provider, tx_blob, signed_tx);
}

static inline hc_wlt_err_t
hc_wallet_proxy_broadcast_async(hc_wallet_proxy_t *proxy,
                                const hc_bytes_t  *signed_tx,
                                hc_tx_cb           cb,
                                void              *user_data,
                                hc_tx_handle_t    *handle)
{
    if (!proxy) return HC_WLT_ERR_INVALID_ARG;
    return proxy->provider->vt->broadcast_tx_async(proxy->provider,
                                                   signed_tx,
                                                   cb,
                                                   user_data,
                                                   handle);
}

static inline hc_wlt_err_t
hc_wallet_proxy_subscribe(hc_wallet_proxy_t *proxy,
                          const char        *filter,
                          hc_evt_cb          cb,
                          void              *user_data,
                          hc_evt_handle_t   *handle)
{
    if (!proxy) return HC_WLT_ERR_INVALID_ARG;
    return proxy->provider->vt->subscribe_events(proxy->provider,
                                                 filter,
                                                 cb,
                                                 user_data,
                                                 handle);
}

static inline hc_wlt_err_t
hc_wallet_proxy_unsubscribe(hc_wallet_proxy_t     *proxy,
                            const hc_evt_handle_t *handle)
{
    if (!proxy) return HC_WLT_ERR_INVALID_ARG;
    return proxy->provider->vt->unsubscribe(proxy->provider, handle);
}

/*─────────────────────────────
 *  Convenience Helpers
 *─────────────────────────────*/

/*
 *  hc_wallet_proxy_load_provider()
 *      Dynamically load a provider implementation shared object / DLL
 *      at run-time.  `so_path` can be absolute, relative, or a module
 *      name resolved by the platform’s search strategy.
 *
 *      The symbol `hc_wallet_provider_factory` must be exported by the
 *      shared library and must have the signature:
 *
 *          hc_wallet_provider_t *factory(const char *config_uri);
 *
 *      Ownership of the returned provider is transferred to the caller
 *      who must eventually call `hc_wallet_provider_destroy()`.
 *
 *  TODO: Implement cross-platform dlopen()/LoadLibrary() in proxy.c
 */
HC_WLT_API hc_wallet_provider_t *
hc_wallet_proxy_load_provider(const char *so_path,
                              const char *config_uri,
                              hc_wlt_err_t *out_err);

/* Destroy provider (even if not proxied). */
HC_WLT_API void
hc_wallet_provider_destroy(hc_wallet_provider_t *prov);

/*─────────────────────────────
 *  Utility / Debug Helpers
 *─────────────────────────────*/

/* Printable string for a hc_wlt_err_t. */
HC_WLT_API const char *
hc_wallet_err_str(hc_wlt_err_t err);

/* Convert byte array to hex string.  Caller frees result. */
HC_WLT_API char *
hc_wallet_bytes_to_hex(const hc_bytes_t *bytes);

/*─────────────────────────────
 *  C++ Compatibility Footer
 *─────────────────────────────*/
#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* HOLOCANVAS_WALLET_PROXY_H */
```