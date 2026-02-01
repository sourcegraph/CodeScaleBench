```c
/**
 * synesthetic-canvas :: libs/sc_ipc/src/sc_ipc.c
 *
 * Inter-process communication helper for SynestheticCanvas micro-services.
 * The implementation is based on UNIX domain sockets (AF_UNIX) with a
 * length-prefixed (uint32 big-endian) message framing protocol.
 *
 * Copyright (c) 2024
 * SPDX-License-Identifier: MIT
 */

#define _GNU_SOURCE /* accept4, SOCK_NONBLOCK, SOCK_CLOEXEC */

#include "sc_ipc.h"

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <syslog.h>
#include <time.h>
#include <unistd.h>

/* -------------------------------------------------------------------------
 * Internal helpers
 * -------------------------------------------------------------------------*/

/* Simple macro-based logger. Redirects to syslog and stderr (debug builds). */
#ifndef SC_IPC_LOG_TAG
#define SC_IPC_LOG_TAG "sc_ipc"
#endif

#define SC_LOG(level, fmt, ...)                                                       \
    do {                                                                              \
        syslog(level, "[" SC_IPC_LOG_TAG "] " fmt, ##__VA_ARGS__);                    \
        /* In debug/CI builds we additionally emit to stderr for convenience.   */    \
        /* NDEBUG disables the extra logging in production to save cycles.      */    \
        /* (The syslog call above remains.)                                     */    \
        #ifndef NDEBUG                                                                  \
        fprintf(stderr, "[" SC_IPC_LOG_TAG "] " fmt "\n", ##__VA_ARGS__);             \
        #endif                                                                         \
    } while (0)

static inline int
set_fd_flags(int fd, int set, int unset)
{
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags == -1)
        return -1;
    flags |= set;
    flags &= ~unset;
    return fcntl(fd, F_SETFL, flags);
}

static int
set_nonblocking_cloexec(int fd)
{
    if (set_fd_flags(fd, O_NONBLOCK, 0) == -1)
        return -1;

    /* Ensure FD_CLOEXEC to avoid leaking sockets into execve. */
    int flags = fcntl(fd, F_GETFD, 0);
    if (flags == -1)
        return -1;
    return fcntl(fd, F_SETFD, flags | FD_CLOEXEC);
}

/* Write exactly len bytes or fail with ‑1. Returns 0 on success. */
static int
write_full(int fd, const uint8_t *buf, size_t len)
{
    while (len > 0) {
        ssize_t n = write(fd, buf, len);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                /* Busy-wait could be replaced with poll/epoll for high-load
                 * services. Since message payloads are typically small
                 * (<64 KiB), we keep the logic simple here. */
                continue;
            }
            return -1;
        }
        buf += n;
        len -= (size_t)n;
    }
    return 0;
}

/* Read exactly len bytes, honoring deadline. Returns 0, ‑1 on error, ‑2 on
 * timeout. */
static int
read_full_deadline(int fd, uint8_t *buf, size_t len, int deadline_ms)
{
    struct pollfd pfd = { .fd = fd, .events = POLLIN };

    while (len > 0) {
        int rc = poll(&pfd, 1, deadline_ms);
        if (rc == 0)
            return -2; /* timeout                               */
        if (rc < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        ssize_t n = read(fd, buf, len);
        if (n == 0)
            return -1; /* orderly shutdown (unexpected here)    */
        if (n < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        buf += n;
        len -= (size_t)n;
    }
    return 0;
}

/* -------------------------------------------------------------------------
 * Public API
 * -------------------------------------------------------------------------*/

struct sc_ipc_endpoint {
    int   fd;
    bool  is_server;  /* server listening socket or connected peer         */
    char  path[SC_IPC_MAX_PATH + 1];
};

/* Helper used by both server and client to allocate endpoint structs */
static sc_ipc_endpoint_t *
endpoint_new(int fd, bool is_server, const char *path)
{
    sc_ipc_endpoint_t *ep = calloc(1, sizeof(*ep));
    if (!ep)
        return NULL;

    ep->fd         = fd;
    ep->is_server  = is_server;

    if (path)
        strncpy(ep->path, path, SC_IPC_MAX_PATH);

    return ep;
}

sc_ipc_endpoint_t *
sc_ipc_server_create(const char *socket_path, int backlog)
{
    if (!socket_path) {
        errno = EINVAL;
        return NULL;
    }
    size_t path_len = strlen(socket_path);
    if (path_len == 0 || path_len >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        errno = ENAMETOOLONG;
        return NULL;
    }

    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd == -1) {
        SC_LOG(LOG_ERR, "socket(): %m");
        return NULL;
    }

    /* Remove leftover socket path from previously crashed instance. */
    unlink(socket_path);

    struct sockaddr_un addr = { .sun_family = AF_UNIX };
    strncpy(addr.sun_path, socket_path, sizeof(addr.sun_path) - 1);

    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) == -1) {
        SC_LOG(LOG_ERR, "bind(%s): %m", socket_path);
        close(fd);
        return NULL;
    }

    /* Restrict permissions to caller's UID/GID (umask honored). */
    if (chmod(socket_path, 0660) == -1) {
        SC_LOG(LOG_WARNING, "chmod(%s): %m", socket_path);
        /* Not fatal; continue. */
    }

    if (listen(fd, backlog) == -1) {
        SC_LOG(LOG_ERR, "listen(): %m");
        close(fd);
        unlink(socket_path);
        return NULL;
    }

    sc_ipc_endpoint_t *ep = endpoint_new(fd, true, socket_path);
    if (!ep) {
        close(fd);
        unlink(socket_path);
    }
    SC_LOG(LOG_INFO, "IPC server listening on %s", socket_path);
    return ep;
}

int
sc_ipc_accept(const sc_ipc_endpoint_t *server,
              sc_ipc_endpoint_t      **client_out,
              int                      timeout_ms)
{
    if (!server || !server->is_server || !client_out) {
        errno = EINVAL;
        return -1;
    }

    struct pollfd pfd = { .fd = server->fd, .events = POLLIN };
    int rc            = poll(&pfd, 1, timeout_ms);
    if (rc == 0)
        return -2; /* timeout */
    if (rc < 0) {
        if (errno == EINTR)
            return -2; /* treat as timeout for simplicity */
        return -1;
    }

    int cfd = accept4(server->fd, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
    if (cfd == -1)
        return -1;

    *client_out = endpoint_new(cfd, false, NULL);
    if (!*client_out) {
        close(cfd);
        return -1;
    }
    return 0;
}

sc_ipc_endpoint_t *
sc_ipc_client_connect(const char *socket_path, int timeout_ms)
{
    if (!socket_path) {
        errno = EINVAL;
        return NULL;
    }
    size_t path_len = strlen(socket_path);
    if (path_len == 0 || path_len >= sizeof(((struct sockaddr_un *)0)->sun_path)) {
        errno = ENAMETOOLONG;
        return NULL;
    }

    int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd == -1) {
        SC_LOG(LOG_ERR, "socket(): %m");
        return NULL;
    }

    struct sockaddr_un addr = { .sun_family = AF_UNIX };
    strncpy(addr.sun_path, socket_path, sizeof(addr.sun_path) - 1);

    int rc = connect(fd, (struct sockaddr *)&addr, sizeof(addr));
    if (rc == -1 && errno != EINPROGRESS) {
        SC_LOG(LOG_ERR, "connect(%s): %m", socket_path);
        close(fd);
        return NULL;
    }

    if (rc == -1) {
        /* Wait for connect completion */
        struct pollfd pfd = { .fd = fd, .events = POLLOUT };
        rc                = poll(&pfd, 1, timeout_ms);
        if (rc == 0) {
            errno = ETIMEDOUT;
            close(fd);
            return NULL;
        }
        if (rc < 0) {
            close(fd);
            return NULL;
        }
        /* Check connection result */
        int err;
        socklen_t len = sizeof(err);
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &len) == -1 || err) {
            if (!err)
                err = errno;
            errno = err;
            close(fd);
            return NULL;
        }
    }

    sc_ipc_endpoint_t *ep = endpoint_new(fd, false, socket_path);
    if (!ep) {
        close(fd);
        return NULL;
    }
    return ep;
}

ssize_t
sc_ipc_send(const sc_ipc_endpoint_t *endpoint, const void *buf, size_t len,
            int flags /* future use */)
{
    (void)flags;

    if (!endpoint || !buf || len > SC_IPC_MAX_PAYLOAD) {
        errno = EINVAL;
        return -1;
    }

    uint8_t header[4];
    uint32_t be_len = htonl((uint32_t)len);
    memcpy(header, &be_len, sizeof(be_len));

    struct iovec iov[2] = {
        { .iov_base = header, .iov_len = sizeof(header) },
        { .iov_base = (void *)buf, .iov_len = len },
    };

    /* Use writev for fewer syscalls */
    ssize_t sent = writev(endpoint->fd, iov, 2);
    if (sent == -1 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
        /* Fallback to blocking loop */
        if (write_full(endpoint->fd, header, sizeof(header)) == -1)
            return -1;
        if (write_full(endpoint->fd, buf, len) == -1)
            return -1;
        sent = sizeof(header) + (ssize_t)len;
    } else if (sent != (ssize_t)sizeof(header) + (ssize_t)len) {
        /* Partial write not expected when socket is blocking; treat as error. */
        errno = EIO;
        return -1;
    }

    return sent;
}

ssize_t
sc_ipc_recv(const sc_ipc_endpoint_t *endpoint, void **buf_out, int timeout_ms)
{
    if (!endpoint || !buf_out) {
        errno = EINVAL;
        return -1;
    }

    uint32_t be_len;
    int rc = read_full_deadline(endpoint->fd, (uint8_t *)&be_len,
                                sizeof(be_len), timeout_ms);
    if (rc == -2) { /* timeout */
        return 0;
    }
    if (rc == -1) {
        return -1;
    }

    uint32_t len = ntohl(be_len);
    if (len == 0 || len > SC_IPC_MAX_PAYLOAD) {
        errno = EMSGSIZE;
        return -1;
    }

    uint8_t *payload = malloc(len + 1);
    if (!payload) {
        return -1;
    }

    rc = read_full_deadline(endpoint->fd, payload, len, timeout_ms);
    if (rc == -2) {
        free(payload);
        return 0; /* timeout waiting for rest */
    }
    if (rc == -1) {
        free(payload);
        return -1;
    }

    payload[len] = '\0'; /* NUL-terminate for quick string use (optional) */
    *buf_out     = payload;
    return (ssize_t)len;
}

void
sc_ipc_endpoint_destroy(sc_ipc_endpoint_t *endpoint)
{
    if (!endpoint)
        return;

    if (endpoint->fd != -1)
        close(endpoint->fd);

    /* Remove socket file only for server listening endpoints. */
    if (endpoint->is_server && *endpoint->path)
        unlink(endpoint->path);

    free(endpoint);
}

/* Convenience wrapper to send a NUL-terminated string. Returns bytes sent. */
ssize_t
sc_ipc_send_str(const sc_ipc_endpoint_t *endpoint, const char *str)
{
    if (!str)
        return -1;
    return sc_ipc_send(endpoint, str, strlen(str), 0);
}

/* Graceful shutdown helper: shuts down write side then waits for peer EOF. */
int
sc_ipc_shutdown(sc_ipc_endpoint_t *endpoint, int deadline_ms)
{
    if (!endpoint)
        return -1;

    shutdown(endpoint->fd, SHUT_WR);

    struct pollfd pfd = { .fd = endpoint->fd, .events = POLLIN };
    int rc            = poll(&pfd, 1, deadline_ms);
    if (rc <= 0)
        return rc; /* 0 = timeout, -1 = error */

    /* Drain any remaining input (could also just close). */
    char tmp[256];
    while (read(endpoint->fd, tmp, sizeof(tmp)) > 0)
        ;
    return 0;
}

/* -------------------------------------------------------------------------
 * Version info (returned via sc_ipc_version_string()) so that dynamically
 * loaded plugins can verify ABI compatibility at runtime.
 * -------------------------------------------------------------------------*/
#define SC_IPC_VERSION_STR "1.0.0"

const char *
sc_ipc_version_string(void)
{
    return SC_IPC_VERSION_STR;
}
```