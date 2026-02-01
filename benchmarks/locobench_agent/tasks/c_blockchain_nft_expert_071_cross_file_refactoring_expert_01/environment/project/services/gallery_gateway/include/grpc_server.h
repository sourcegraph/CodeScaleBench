/**
 * HoloCanvas – Gallery Gateway
 * File: services/gallery_gateway/include/grpc_server.h
 *
 * A thin yet production–grade wrapper around the official gRPC-C server API
 * that adds:
 *   – Thread-safe reference counting
 *   – Graceful start/stop life-cycle with state tracking
 *   – TLS credential loading from PEM files
 *   – Completion-queue polling in a dedicated thread
 *
 * In keeping with HoloCanvas’ micro-service ethos, the wrapper is purposely
 * minimal and does not expose application level service definitions.  Those
 * are expected to be registered by the caller once the server object has been
 * created (see hc_grpc_server_get_raw()).
 *
 * Build notes:
 *   – Requires gRPC C core library (>= 1.45)
 *   – Compile this translation unit once by defining:
 *         #define HOLOCANVAS_GRPC_SERVER_IMPLEMENTATION
 *     in exactly one source file before including this header.
 */

#ifndef HOLOCANVAS_GALLERY_GATEWAY_GRPC_SERVER_H
#define HOLOCANVAS_GALLERY_GATEWAY_GRPC_SERVER_H

/* ---- Public includes ---------------------------------------------------- */

#include <grpc/grpc.h>
#include <grpc/grpc_security.h>

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------------- */
/*                              Error Handling                               */
/* ------------------------------------------------------------------------- */

typedef enum hc_grpc_status_e {
    HC_GRPC_OK                 =  0,
    HC_GRPC_ERR_INVALID_ARGS   = -1,
    HC_GRPC_ERR_ALLOC          = -2,
    HC_GRPC_ERR_IO             = -3,
    HC_GRPC_ERR_STATE          = -4,
    HC_GRPC_ERR_GRPC_INTERNAL  = -5
} hc_grpc_status_t;

/* ------------------------------------------------------------------------- */
/*                              Server Object                                */
/* ------------------------------------------------------------------------- */

typedef struct hc_grpc_server_s hc_grpc_server_t;

/**
 * Create an un-started gRPC server instance.
 *
 * Arguments:
 *   bind_address             – E.g. "0.0.0.0:8443"
 *   server_key_pem_path      – PEM file containing the server’s private key
 *   server_cert_pem_path     – PEM file containing the server’s certificate
 *   root_cert_pem_path       – (Optional) CA root certificate for mTLS client
 *                              auth.  Pass NULL to disable client auth.
 *   max_concurrent_streams   – gRPC HTTP/2 setting, 0 for library default
 *   out_server               – Returns a retained pointer on success
 *
 * Returns:
 *   HC_GRPC_OK on success, otherwise an error code.  *out_server is set to
 *   NULL on failure.
 *
 * Note:
 *   The server starts with ref-count 1.  Call hc_grpc_server_unref() when
 *   the reference is no longer needed.
 */
hc_grpc_status_t
hc_grpc_server_create(const char     *bind_address,
                      const char     *server_key_pem_path,
                      const char     *server_cert_pem_path,
                      const char     *root_cert_pem_path,
                      uint16_t        max_concurrent_streams,
                      hc_grpc_server_t **out_server);

/**
 * Increment the server’s reference count.
 */
void hc_grpc_server_ref(hc_grpc_server_t *srv);

/**
 * Decrement the reference count.  When it drops to zero the server will be
 * disposed and all resources freed (gracefully if it was running).
 */
void hc_grpc_server_unref(hc_grpc_server_t *srv);

/**
 * Start the server and its completion-queue poller thread.
 */
hc_grpc_status_t hc_grpc_server_start(hc_grpc_server_t *srv);

/**
 * Asynchronously request server shutdown and wait up to grace_period_ms before
 * force-closing outstanding calls.
 */
void hc_grpc_server_shutdown(hc_grpc_server_t *srv, uint32_t grace_period_ms);

/**
 * Raw access to the underlying grpc_server*.  Useful for registering services.
 * DO NOT call grpc_server_start/stop directly on the returned pointer.
 */
grpc_server *hc_grpc_server_get_raw(hc_grpc_server_t *srv);

/**
 * Convenience helper to get the server’s bound address string.
 * Returned memory is owned by the server and valid until unref().
 */
const char *hc_grpc_server_get_bind_address(hc_grpc_server_t *srv);

/* ------------------------------------------------------------------------- */

#ifdef __cplusplus
} /* extern "C" */
#endif

/* ------------------------------------------------------------------------- */
/*                    Optional Header-Only Implementation                    */
/* ------------------------------------------------------------------------- */

#ifdef HOLOCANVAS_GRPC_SERVER_IMPLEMENTATION

/* ---- Private includes --------------------------------------------------- */

#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

/* ---- Constants ---------------------------------------------------------- */

#define HC__MAX_PEM_FILE_SZ (64 * 1024) /* 64 KiB should cover most PEMs */

/* ---- Internal helpers --------------------------------------------------- */

static bool
hc__read_file_as_string(const char *path, char **out_buf, size_t *out_len)
{
    FILE *fp = fopen(path, "rb");
    if (!fp) {
        return false;
    }

    if (fseek(fp, 0, SEEK_END) != 0) {
        fclose(fp);
        return false;
    }
    long fsz = ftell(fp);
    if (fsz < 0 || (size_t)fsz > HC__MAX_PEM_FILE_SZ) {
        fclose(fp);
        return false;
    }
    rewind(fp);

    char *buf = (char *)malloc((size_t)fsz + 1);
    if (!buf) {
        fclose(fp);
        return false;
    }

    if (fread(buf, 1, (size_t)fsz, fp) != (size_t)fsz) {
        free(buf);
        fclose(fp);
        return false;
    }
    buf[fsz] = '\0';

    fclose(fp);
    *out_buf = buf;
    if (out_len) *out_len = (size_t)fsz;
    return true;
}

/* ---- Type definitions --------------------------------------------------- */

typedef enum {
    HC_SRV_STATE_INIT = 0,
    HC_SRV_STATE_STARTED,
    HC_SRV_STATE_STOPPING,
    HC_SRV_STATE_STOPPED
} hc_srv_state_t;

struct hc_grpc_server_s {
    grpc_server               *grpc_srv;
    grpc_completion_queue     *cq;
    pthread_t                  cq_thread;

    atomic_int                 ref_cnt;
    atomic_int                 state;          /* hc_srv_state_t */

    char                      *bind_addr;      /* strdup() of supplied string */
};

/* ---- Global gRPC runtime init / shutdown -------------------------------- */

static void hc__grpc_global_init(void)
{
    static pthread_once_t once = PTHREAD_ONCE_INIT;
    pthread_once(&once, grpc_init);
}

static void hc__grpc_global_shutdown(void)
{
    /* grpc_shutdown() must be balanced with grpc_init() calls.
     * We simply call it once at process exit.
     */
    grpc_shutdown();
}

static void __attribute__((constructor)) hc__on_process_start(void)
{
    hc__grpc_global_init();
}

static void __attribute__((destructor)) hc__on_process_end(void)
{
    hc__grpc_global_shutdown();
}

/* ---- Completion queue polling thread ------------------------------------ */

static void *hc__cq_poller(void *arg)
{
    hc_grpc_server_t *srv = (hc_grpc_server_t *)arg;
    const gpr_timespec timeout = gpr_time_from_millis(200, GPR_TIMESPAN);

    while (atomic_load_explicit(&srv->state, memory_order_acquire) ==
               HC_SRV_STATE_STARTED) {

        grpc_event ev = grpc_completion_queue_next(srv->cq, timeout, NULL);

        switch (ev.type) {
            case GRPC_QUEUE_SHUTDOWN:
                return NULL;

            case GRPC_OP_COMPLETE:
                /* We use the CQ solely for shutdown handling; service methods
                 * use their own CQs.  Therefore we just free the tag if any.
                 */
                if (ev.tag) free(ev.tag);
                break;

            case GRPC_QUEUE_TIMEOUT:
                /* Idle – loop again */
                break;
        }
    }

    return NULL;
}

/* ---- Public API implementation ----------------------------------------- */

hc_grpc_status_t
hc_grpc_server_create(const char     *bind_address,
                      const char     *server_key_pem_path,
                      const char     *server_cert_pem_path,
                      const char     *root_cert_pem_path,
                      uint16_t        max_concurrent_streams,
                      hc_grpc_server_t **out_server)
{
    if (!bind_address || !server_key_pem_path || !server_cert_pem_path ||
        !out_server)
    {
        return HC_GRPC_ERR_INVALID_ARGS;
    }

    *out_server = NULL;
    hc_grpc_server_t *srv = calloc(1, sizeof(*srv));
    if (!srv) {
        return HC_GRPC_ERR_ALLOC;
    }

    srv->bind_addr = strdup(bind_address);
    if (!srv->bind_addr) {
        free(srv);
        return HC_GRPC_ERR_ALLOC;
    }

    /* -------- TLS credentials -------- */

    char *key_pem  = NULL, *cert_pem = NULL, *root_pem = NULL;
    if (!hc__read_file_as_string(server_key_pem_path, &key_pem, NULL) ||
        !hc__read_file_as_string(server_cert_pem_path, &cert_pem, NULL))
    {
        goto io_error;
    }

    grpc_ssl_pem_key_cert_pair pem_pair = {
        .private_key = key_pem,
        .cert_chain  = cert_pem
    };

    grpc_server_credentials *creds = NULL;

    if (root_cert_pem_path) {
        if (!hc__read_file_as_string(root_cert_pem_path, &root_pem, NULL)) {
            goto io_error;
        }

        creds = grpc_ssl_server_credentials_create(
                     root_pem,
                     &pem_pair, 1,
                     /* force_client_auth= */ true, /* reserved */ NULL);
    } else {
        creds = grpc_ssl_server_credentials_create(
                     NULL, &pem_pair, 1,
                     /* force_client_auth= */ false, /* reserved */ NULL);
    }

    if (!creds) {
        goto grpc_internal_error;
    }

    /* -------- Server + Completion queue -------- */

    srv->cq = grpc_completion_queue_create_for_next(NULL);
    if (!srv->cq) {
        goto grpc_internal_error;
    }

    grpc_channel_args args;
    grpc_arg arg_array[1];

    arg_array[0].type = GRPC_ARG_INTEGER;
    arg_array[0].key  = (char *)GRPC_ARG_MAX_CONCURRENT_STREAMS;
    arg_array[0].value.integer = max_concurrent_streams ? max_concurrent_streams : 0;

    args.num_args = 1;
    args.args     = arg_array;

    srv->grpc_srv = grpc_server_create(&args, NULL);
    if (!srv->grpc_srv) {
        goto grpc_internal_error;
    }

    grpc_server_register_completion_queue(srv->grpc_srv, srv->cq, NULL);

    if (grpc_server_add_secure_http2_port(srv->grpc_srv,
                                          srv->bind_addr, creds) == 0)
    {
        goto grpc_internal_error;
    }

    grpc_server_credentials_release(creds);
    creds = NULL;

    atomic_init(&srv->ref_cnt, 1);
    atomic_init(&srv->state, HC_SRV_STATE_INIT);

    *out_server = srv;
    free(key_pem);
    free(cert_pem);
    free(root_pem);
    return HC_GRPC_OK;

/* ---- Error paths ------------------------------------------------------- */
grpc_internal_error:
    if (creds) grpc_server_credentials_release(creds);
io_error:
    free(key_pem); free(cert_pem); free(root_pem);
    if (srv->grpc_srv) grpc_server_destroy(srv->grpc_srv);
    if (srv->cq) grpc_completion_queue_destroy(srv->cq);
    free(srv->bind_addr);
    free(srv);
    return HC_GRPC_ERR_GRPC_INTERNAL;
}

void hc_grpc_server_ref(hc_grpc_server_t *srv)
{
    if (srv) atomic_fetch_add_explicit(&srv->ref_cnt, 1, memory_order_acq_rel);
}

void hc_grpc_server_unref(hc_grpc_server_t *srv)
{
    if (!srv) return;
    if (atomic_fetch_sub_explicit(&srv->ref_cnt, 1, memory_order_acq_rel) == 1) {
        /* Last reference – destroy */
        hc_grpc_server_shutdown(srv, 500 /*ms*/); /* Ensure stopped */

        if (srv->grpc_srv) grpc_server_destroy(srv->grpc_srv);
        if (srv->cq) grpc_completion_queue_destroy(srv->cq);
        free(srv->bind_addr);
        free(srv);
    }
}

hc_grpc_status_t hc_grpc_server_start(hc_grpc_server_t *srv)
{
    if (!srv) return HC_GRPC_ERR_INVALID_ARGS;

    int expected = HC_SRV_STATE_INIT;
    if (!atomic_compare_exchange_strong(&srv->state, &expected,
                                        HC_SRV_STATE_STARTED))
    {
        /* Already started or stopping */
        return HC_GRPC_ERR_STATE;
    }

    grpc_server_start(srv->grpc_srv);

    if (pthread_create(&srv->cq_thread, NULL, &hc__cq_poller, srv) != 0) {
        atomic_store(&srv->state, HC_SRV_STATE_STOPPED);
        return HC_GRPC_ERR_GRPC_INTERNAL;
    }

    return HC_GRPC_OK;
}

void hc_grpc_server_shutdown(hc_grpc_server_t *srv, uint32_t grace_period_ms)
{
    if (!srv) return;

    int expected = HC_SRV_STATE_STARTED;
    if (!atomic_compare_exchange_strong(&srv->state, &expected,
                                        HC_SRV_STATE_STOPPING))
    {
        return; /* Not running */
    }

    gpr_timespec deadline =
        gpr_time_add(gpr_now(GPR_CLOCK_REALTIME),
                     gpr_time_from_millis(grace_period_ms, GPR_TIMESPAN));

    grpc_server_shutdown_and_notify(srv->grpc_srv, srv->cq, NULL);
    grpc_completion_queue_shutdown(srv->cq);

    pthread_join(srv->cq_thread, NULL);

    grpc_server_destroy(srv->grpc_srv);
    srv->grpc_srv = NULL;

    atomic_store(&srv->state, HC_SRV_STATE_STOPPED);
}

grpc_server *hc_grpc_server_get_raw(hc_grpc_server_t *srv)
{
    return srv ? srv->grpc_srv : NULL;
}

const char *hc_grpc_server_get_bind_address(hc_grpc_server_t *srv)
{
    return srv ? srv->bind_addr : NULL;
}

#endif /* HOLOCANVAS_GRPC_SERVER_IMPLEMENTATION */
#endif /* HOLOCANVAS_GALLERY_GATEWAY_GRPC_SERVER_H */
