/*
 * sc_ipc.h
 * ----------------------------------------------------------------------------
 * SynestheticCanvas Inter-Process Communication (IPC) library – Public API
 *
 * The IPC layer allows individual SynestheticCanvas micro-services to exchange
 * strongly-typed messages with predictable latency guarantees.  The transport
 * is based on UNIX domain sockets with configurable timeouts, automatic
 * envelope framing, and correlation identifiers for request/response
 * matching.  The ABI is stable and versioned; breaking changes will bump
 * SC_IPC_VERSION_MAJOR.
 *
 * Copyright (c) 2024
 *   SynestheticCanvas Contributors <oss@synestheticcanvas.io>
 *   Licensed under the MIT License – see LICENSE file for details.
 * ----------------------------------------------------------------------------
 */

#ifndef SC_IPC_H
#define SC_IPC_H

/* ------------------------------------------------------------------------- */
/*  Standard & system includes                                               */
/* ------------------------------------------------------------------------- */
#include <errno.h>
#include <inttypes.h>
#include <stddef.h>
#include <stdbool.h>
#include <time.h>

#if defined(_WIN32) || defined(_WIN64)
/*  Windows is currently not supported; compilation will fail clearly.       */
#   error "sc_ipc currently supports POSIX / UNIX-like systems only."
#else
#   include <sys/socket.h>
#   include <sys/types.h>
#   include <sys/un.h>
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------------- */
/*  Versioning                                                               */
/* ------------------------------------------------------------------------- */
#define SC_IPC_VERSION_MAJOR  1
#define SC_IPC_VERSION_MINOR  0
#define SC_IPC_VERSION_PATCH  0

#define SC_IPC_VERSION_STR    "1.0.0"

/* ------------------------------------------------------------------------- */
/*  Compile-time configuration                                               */
/* ------------------------------------------------------------------------- */
/* Maximum UNIX-domain socket path length (108 on Linux).                    */
#ifndef SC_IPC_MAX_ENDPOINT
#define SC_IPC_MAX_ENDPOINT   107U
#endif

/* Largest allowed user payload in a single message.                         */
#ifndef SC_IPC_MAX_PAYLOAD
#define SC_IPC_MAX_PAYLOAD    (64 * 1024u)    /* 64 KiB */
#endif

/* Magic constant used to quickly validate message integrity.                */
#define SC_IPC_MSG_MAGIC      0xC0FEBABEUL

/* ------------------------------------------------------------------------- */
/*  Error codes                                                              */
/* ------------------------------------------------------------------------- */
typedef enum sc_ipc_err
{
    SC_IPC_SUCCESS        =  0,
    SC_IPC_EINVAL         = -1,   /* Invalid argument                              */
    SC_IPC_ETIMEDOUT      = -2,   /* Operation timed out                           */
    SC_IPC_ECONN          = -3,   /* Connection failure                            */
    SC_IPC_EIO            = -4,   /* I/O error – see errno for details             */
    SC_IPC_EPROTO         = -5,   /* Protocol violation / corrupt frame            */
    SC_IPC_ECLOSED        = -6,   /* Peer closed connection                        */
    SC_IPC_EBUFFER        = -7,   /* Provided buffer too small                     */
    SC_IPC_ENOMEM         = -8,   /* Memory allocation failed                      */
    SC_IPC_ESTATE         = -9,   /* Invalid library state (internal bug)          */
} sc_ipc_err_t;

/* Returns a static, human-readable string for an sc_ipc_err_t value.        */
const char *sc_ipc_strerr(sc_ipc_err_t err);

/* ------------------------------------------------------------------------- */
/*  Message envelope                                                         */
/* ------------------------------------------------------------------------- */
typedef enum sc_ipc_msg_type
{
    SC_IPC_MSG_REQUEST    = 1,
    SC_IPC_MSG_RESPONSE   = 2,
    SC_IPC_MSG_EVENT      = 3,
    SC_IPC_MSG_HEARTBEAT  = 4
} sc_ipc_msg_type_t;

/*
 * The envelope precedes every payload.  All integer fields are encoded in the
 * native endianness of the host (the IPC is local-host only).  The envelope is
 * always transmitted in a single write(2)/send(2) call to guarantee atomicity
 * on UNIX domain sockets for payloads < PIPE_BUF – see POSIX.1-2001.
 */
#pragma pack(push, 1)
typedef struct sc_ipc_msg_hdr
{
    uint32_t         magic;          /* == SC_IPC_MSG_MAGIC                       */
    uint16_t         version;        /* Envelope format version (currently 1)     */
    uint16_t         type;           /* sc_ipc_msg_type_t                         */
    uint32_t         length;         /* Length of following payload in bytes      */
    uint64_t         correlation_id; /* Client-supplied token for matchmaking      */
    uint64_t         timestamp_ns;   /* CLOCK_REALTIME timestamp, nanoseconds     */
} sc_ipc_msg_hdr_t;
#pragma pack(pop)

/* ------------------------------------------------------------------------- */
/*  IPC handle (opaque to callers)                                           */
/* ------------------------------------------------------------------------- */
typedef struct sc_ipc_channel
{
    int              fd;                       /* Socket descriptor            */
    bool             is_server;                /* Server or client side?       */
    char             endpoint[SC_IPC_MAX_ENDPOINT + 1];
} sc_ipc_channel_t;

/* ------------------------------------------------------------------------- */
/*  Initialization / teardown                                                */
/* ------------------------------------------------------------------------- */
/*
 * Initialize a listening server socket at `endpoint` (UNIX-domain path).
 * Returns SC_IPC_SUCCESS on success, otherwise a negative error code.
 */
int sc_ipc_server_init(sc_ipc_channel_t      *srv,
                       const char            *endpoint,
                       size_t                 backlog);

/*
 * Initialize a client socket and connect to the specified `endpoint`.
 * `timeout_ms` ∈ [0, UINT32_MAX]  (0 → block indefinitely).
 */
int sc_ipc_client_init(sc_ipc_channel_t      *cli,
                       const char            *endpoint,
                       uint32_t               timeout_ms);

/*
 * Accept an incoming client connection on `srv` into `out_cli`.
 * On success returns SC_IPC_SUCCESS and `out_cli` is initialized.
 */
int sc_ipc_accept(const sc_ipc_channel_t     *srv,
                  sc_ipc_channel_t           *out_cli,
                  uint32_t                    timeout_ms);

/* Close socket and wipe internal state (safe to call on uninitialized obj). */
void sc_ipc_close(sc_ipc_channel_t *chan);

/* ------------------------------------------------------------------------- */
/*  Message I/O                                                              */
/* ------------------------------------------------------------------------- */
/*
 * Send a payload with envelope fields filled automatically.  The function
 * blocks up to `timeout_ms`;  0 → blocking, UINT32_MAX → poll once + return.
 */
int sc_ipc_send_msg(sc_ipc_channel_t        *chan,
                    sc_ipc_msg_type_t         type,
                    const void              *payload,
                    size_t                    payload_len,
                    uint64_t                  correlation_id,
                    uint32_t                  timeout_ms);

/*
 * Receive a message into `buf` (size `buf_size`) and write header to `hdr`.
 * On success returns the number of payload bytes copied into `buf`.  The
 * caller may pass NULL for `buf` to peek at the header without reading the
 * payload (useful for length negotiation).
 */
int sc_ipc_recv_msg(sc_ipc_channel_t        *chan,
                    sc_ipc_msg_hdr_t        *hdr,
                    void                    *buf,
                    size_t                   buf_size,
                    uint32_t                 timeout_ms);

/* ------------------------------------------------------------------------- */
/*  Utility helpers                                                          */
/* ------------------------------------------------------------------------- */
/* Generates a random, non-zero correlation identifier. */
uint64_t sc_ipc_gen_correlation_id(void);

/* Blocking helper: drain socket until all outstanding data has been read.   */
int sc_ipc_drain(sc_ipc_channel_t *chan);

/* ------------------------------------------------------------------------- */
/*  Inline helpers                                                           */
/* ------------------------------------------------------------------------- */
static inline bool sc_ipc_is_ok(int rv)
{
    return rv >= 0;
}

/* ------------------------------------------------------------------------- */
#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* SC_IPC_H */
