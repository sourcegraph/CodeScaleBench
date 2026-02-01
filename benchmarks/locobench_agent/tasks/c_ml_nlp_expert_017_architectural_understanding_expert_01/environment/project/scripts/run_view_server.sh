```c
/*
 *  LexiLearn MVC Orchestrator
 *  --------------------------
 *  File:  scripts/run_view_server.c   (compiled from run_view_server.sh wrapper)
 *
 *  Description:
 *      Lightweight, dependency–free HTTP server responsible for
 *      delivering real-time visualization dashboards for the
 *      LexiLearn View layer.  Designed for containerized / on-prem
 *      deployments where introducing scripting runtimes or external
 *      web servers is undesirable.
 *
 *      Features
 *      --------
 *      • Health-check endpoint      : GET /healthz
 *      • Prometheus-style metrics   : GET /metrics
 *      • Static dashboard delivery  : GET /
 *      • Graceful shutdown via SIGINT/SIGTERM
 *      • Configurable log-level & port
 *
 *  Build:
 *      gcc -O2 -Wall -Wextra -pedantic -pthread \
 *          -o run_view_server scripts/run_view_server.c
 *
 *  Usage:
 *      ./run_view_server            # defaults to 0.0.0.0:8080
 *      ./run_view_server -p 9090 -l debug
 *
 *  NOTE:
 *      For production use behind TLS, terminate HTTPS upstream
 *      (e.g., via nginx/Envoy) or compile with mbedTLS/OpenSSL.
 */

#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <netdb.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/poll.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

/* ------------------------------------------------------------------------- */
/*                               Configuration                               */
/* ------------------------------------------------------------------------- */

#define DEFAULT_PORT        8080
#define BACKLOG_SIZE        128
#define MAX_REQUEST_SIZE    8192
#define READ_TIMEOUT_SEC    5

typedef enum {
    LOG_DEBUG = 0,
    LOG_INFO,
    LOG_WARN,
    LOG_ERROR
} log_level_t;

typedef struct {
    char         bind_addr[64];
    uint16_t     port;
    log_level_t  log_level;
} server_config_t;

/* ------------------------------------------------------------------------- */
/*                               Global State                                */
/* ------------------------------------------------------------------------- */

static server_config_t g_cfg = {
    .bind_addr = "0.0.0.0",
    .port      = DEFAULT_PORT,
    .log_level = LOG_INFO
};

static volatile sig_atomic_t g_shutdown_requested = 0;

/* ------------------------------------------------------------------------- */
/*                               Logging util                                */
/* ------------------------------------------------------------------------- */

static const char *level_to_string(log_level_t lvl)
{
    switch (lvl) {
        case LOG_DEBUG: return "DEBUG";
        case LOG_INFO:  return "INFO ";
        case LOG_WARN:  return "WARN ";
        case LOG_ERROR: return "ERROR";
        default:        return "UNKWN";
    }
}

static void log_message(log_level_t lvl, const char *fmt, ...)
{
    if (lvl < g_cfg.log_level)
        return;

    struct timeval tv;
    gettimeofday(&tv, NULL);
    struct tm tm_info;
    localtime_r(&tv.tv_sec, &tm_info);

    char time_buf[64];
    strftime(time_buf, sizeof time_buf, "%Y-%m-%d %H:%M:%S", &tm_info);

    fprintf((lvl >= LOG_WARN) ? stderr : stdout,
            "[%s.%03ld] %-5s : ",
            time_buf, tv.tv_usec / 1000, level_to_string(lvl));

    va_list ap;
    va_start(ap, fmt);
    vfprintf((lvl >= LOG_WARN) ? stderr : stdout, fmt, ap);
    va_end(ap);
    fputc('\n', (lvl >= LOG_WARN) ? stderr : stdout);
    fflush((lvl >= LOG_WARN) ? stderr : stdout);
}

/* ------------------------------------------------------------------------- */
/*                         Utility / Helper Functions                        */
/* ------------------------------------------------------------------------- */

static int set_nonblocking(int fd)
{
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0)
        return -1;
    return fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

static ssize_t full_write(int fd, const void *buf, size_t count)
{
    size_t total = 0;
    const uint8_t *ptr = buf;
    while (total < count) {
        ssize_t n = write(fd, ptr + total, count - total);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        total += n;
    }
    return (ssize_t)total;
}

/* ------------------------------------------------------------------------- */
/*                              HTTP Responses                               */
/* ------------------------------------------------------------------------- */

static const char RESPONSE_404[] =
    "HTTP/1.1 404 Not Found\r\n"
    "Content-Length: 13\r\n"
    "Content-Type: text/plain\r\n"
    "Connection: close\r\n"
    "\r\n"
    "404 Not Found";

static const char RESPONSE_405[] =
    "HTTP/1.1 405 Method Not Allowed\r\n"
    "Content-Length: 18\r\n"
    "Content-Type: text/plain\r\n"
    "Allow: GET\r\n"
    "Connection: close\r\n"
    "\r\n"
    "405 Not Allowed";

static const char RESPONSE_500[] =
    "HTTP/1.1 500 Internal Server Error\r\n"
    "Content-Length: 25\r\n"
    "Content-Type: text/plain\r\n"
    "Connection: close\r\n"
    "\r\n"
    "500 Internal Server Error";

static const char DASHBOARD_HTML[] =
    "<!DOCTYPE html>\n"
    "<html lang=\"en\">\n"
    "  <head>\n"
    "    <meta charset=\"utf-8\">\n"
    "    <title>LexiLearn Dashboard</title>\n"
    "    <style>\n"
    "      body { font-family: sans-serif; margin: 40px; }\n"
    "      h1  { color: #2c3e50; }\n"
    "    </style>\n"
    "  </head>\n"
    "  <body>\n"
    "    <h1>LexiLearn View Server is Running</h1>\n"
    "    <p>Replace this stub with full React/Angular build artifacts.</p>\n"
    "  </body>\n"
    "</html>\n";

/* Generate runtime metrics in a minimal Prometheus-compatible format */
static void build_metrics(char *dst, size_t dst_sz)
{
    /* Example metrics; replace with real runtime counters */
    snprintf(dst, dst_sz,
             "# HELP view_active_connections Current active TCP connections.\n"
             "# TYPE view_active_connections gauge\n"
             "view_active_connections 1\n"
             "# HELP view_uptime_seconds Server uptime in seconds.\n"
             "# TYPE view_uptime_seconds counter\n"
             "view_uptime_seconds %ld\n",
             time(NULL));
}

/* ------------------------------------------------------------------------- */
/*                             Client Handling                               */
/* ------------------------------------------------------------------------- */

typedef struct {
    int fd;
    struct sockaddr_storage addr;
    socklen_t addr_len;
} client_ctx_t;

static void *client_thread(void *arg)
{
    client_ctx_t *ctx = arg;
    int fd = ctx->fd;
    free(ctx);

    char req_buf[MAX_REQUEST_SIZE + 1] = {0};
    size_t received = 0;
    bool header_done = false;
    time_t start = time(NULL);

    /* Read loop with simple timeout */
    while (!header_done && (time(NULL) - start) < READ_TIMEOUT_SEC) {
        ssize_t n = recv(fd, req_buf + received,
                         MAX_REQUEST_SIZE - received, 0);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                /* wait a bit */
                struct timespec ts = {0, 100000000}; /* 100 ms */
                nanosleep(&ts, NULL);
                continue;
            }
            log_message(LOG_WARN, "recv() error: %s", strerror(errno));
            goto cleanup;
        } else if (n == 0) {
            /* client closed */
            goto cleanup;
        }
        received += (size_t)n;
        req_buf[received] = '\0';
        if (strstr(req_buf, "\r\n\r\n") != NULL)
            header_done = true;
        if (received >= MAX_REQUEST_SIZE) {
            log_message(LOG_WARN, "Request exceeded buffer limit");
            goto cleanup;
        }
    }

    if (!header_done) {
        log_message(LOG_WARN, "Header read timeout");
        goto cleanup;
    }

    /* Parse basic request line */
    char method[8], path[1024];
    if (sscanf(req_buf, "%7s %1023s", method, path) != 2) {
        full_write(fd, RESPONSE_400, strlen(RESPONSE_500));
        goto cleanup;
    }

    log_message(LOG_DEBUG, "Request: %s %s", method, path);

    if (strcmp(method, "GET") != 0) {
        full_write(fd, RESPONSE_405, sizeof(RESPONSE_405) - 1);
        goto cleanup;
    }

    if (strcmp(path, "/") == 0 || strcmp(path, "/index.html") == 0) {
        char header[256];
        int hdr_len = snprintf(header, sizeof header,
                               "HTTP/1.1 200 OK\r\n"
                               "Content-Type: text/html; charset=utf-8\r\n"
                               "Content-Length: %zu\r\n"
                               "Connection: close\r\n"
                               "\r\n",
                               strlen(DASHBOARD_HTML));

        full_write(fd, header, (size_t)hdr_len);
        full_write(fd, DASHBOARD_HTML, sizeof(DASHBOARD_HTML) - 1);

    } else if (strcmp(path, "/healthz") == 0) {
        const char body[] = "ok";
        char header[256];
        int hdr_len = snprintf(header, sizeof header,
                               "HTTP/1.1 200 OK\r\n"
                               "Content-Type: text/plain\r\n"
                               "Content-Length: %zu\r\n"
                               "Connection: close\r\n"
                               "\r\n",
                               sizeof(body) - 1);
        full_write(fd, header, (size_t)hdr_len);
        full_write(fd, body, sizeof(body) - 1);

    } else if (strcmp(path, "/metrics") == 0) {
        char metrics[1024];
        build_metrics(metrics, sizeof metrics);

        char header[256];
        int hdr_len = snprintf(header, sizeof header,
                               "HTTP/1.1 200 OK\r\n"
                               "Content-Type: text/plain; version=0.0.4\r\n"
                               "Content-Length: %zu\r\n"
                               "Connection: close\r\n"
                               "\r\n",
                               strlen(metrics));
        full_write(fd, header, (size_t)hdr_len);
        full_write(fd, metrics, strlen(metrics));

    } else {
        full_write(fd, RESPONSE_404, sizeof(RESPONSE_404) - 1);
    }

cleanup:
    shutdown(fd, SHUT_RDWR);
    close(fd);
    return NULL;
}

/* ------------------------------------------------------------------------- */
/*                           Signal Handling                                 */
/* ------------------------------------------------------------------------- */

static void handle_signal(int sig)
{
    (void)sig;
    g_shutdown_requested = 1;
}

/* ------------------------------------------------------------------------- */
/*                               Server Main                                 */
/* ------------------------------------------------------------------------- */

static int create_and_bind_socket(const char *addr_str, uint16_t port)
{
    char port_str[16];
    snprintf(port_str, sizeof port_str, "%u", port);

    struct addrinfo hints, *res, *rp;
    memset(&hints, 0, sizeof hints);
    hints.ai_family   = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags    = AI_PASSIVE | AI_NUMERICSERV;

    int rc = getaddrinfo(addr_str, port_str, &hints, &res);
    if (rc != 0) {
        log_message(LOG_ERROR, "getaddrinfo: %s", gai_strerror(rc));
        return -1;
    }

    int listen_fd = -1;

    for (rp = res; rp != NULL; rp = rp->ai_next) {
        listen_fd = socket(rp->ai_family, rp->ai_socktype, rp->ai_protocol);
        if (listen_fd == -1)
            continue;

        int opt = 1;
        setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof opt);

        if (bind(listen_fd, rp->ai_addr, rp->ai_addrlen) == 0)
            break; /* success */

        close(listen_fd);
        listen_fd = -1;
    }

    freeaddrinfo(res);

    if (listen_fd == -1) {
        log_message(LOG_ERROR, "Could not bind to %s:%d", addr_str, port);
        return -1;
    }

    if (listen(listen_fd, BACKLOG_SIZE) < 0) {
        log_message(LOG_ERROR, "listen(): %s", strerror(errno));
        close(listen_fd);
        return -1;
    }

    if (set_nonblocking(listen_fd) < 0) {
        log_message(LOG_WARN, "Failed to set non-blocking mode");
    }

    return listen_fd;
}

/* ------------------------------------------------------------------------- */
/*                              CLI Parsing                                  */
/* ------------------------------------------------------------------------- */

static void usage(const char *prog)
{
    printf("Usage: %s [options]\n"
           "Options:\n"
           "  -p, --port <num>        TCP port to bind (default: %d)\n"
           "  -b, --bind <addr>       Bind address (default: 0.0.0.0)\n"
           "  -l, --log-level <lvl>   debug|info|warn|error (default: info)\n"
           "  -h, --help              Show this help message\n",
           prog, DEFAULT_PORT);
}

static log_level_t parse_log_level(const char *str)
{
    if (strcasecmp(str, "debug") == 0) return LOG_DEBUG;
    if (strcasecmp(str, "info")  == 0) return LOG_INFO;
    if (strcasecmp(str, "warn")  == 0) return LOG_WARN;
    if (strcasecmp(str, "error") == 0) return LOG_ERROR;
    return LOG_INFO;
}

static void parse_args(int argc, char **argv)
{
    static struct option long_opts[] = {
        { "port",      required_argument, NULL, 'p' },
        { "bind",      required_argument, NULL, 'b' },
        { "log-level", required_argument, NULL, 'l' },
        { "help",      no_argument,       NULL, 'h' },
        { NULL,        0,                 NULL,  0  }
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "p:b:l:h", long_opts, NULL)) != -1) {
        switch (opt) {
            case 'p':
                g_cfg.port = (uint16_t)atoi(optarg);
                break;
            case 'b':
                strncpy(g_cfg.bind_addr, optarg, sizeof g_cfg.bind_addr - 1);
                g_cfg.bind_addr[sizeof g_cfg.bind_addr - 1] = '\0';
                break;
            case 'l':
                g_cfg.log_level = parse_log_level(optarg);
                break;
            case 'h':
            default:
                usage(argv[0]);
                exit(EXIT_SUCCESS);
        }
    }
}

/* ------------------------------------------------------------------------- */
/*                                   Main                                    */
/* ------------------------------------------------------------------------- */

int main(int argc, char **argv)
{
    parse_args(argc, argv);

    /* Install signal handlers */
    struct sigaction sa = { .sa_handler = handle_signal };
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    int listen_fd = create_and_bind_socket(g_cfg.bind_addr, g_cfg.port);
    if (listen_fd < 0)
        exit(EXIT_FAILURE);

    log_message(LOG_INFO, "LexiLearn View Server listening on %s:%u",
                g_cfg.bind_addr, g_cfg.port);

    struct pollfd pfd = { .fd = listen_fd, .events = POLLIN };

    while (!g_shutdown_requested) {
        int poll_rc = poll(&pfd, 1, 500); /* 0.5 second timeout */
        if (poll_rc < 0) {
            if (errno == EINTR)
                continue;
            log_message(LOG_ERROR, "poll(): %s", strerror(errno));
            break;
        }
        if (poll_rc == 0)
            continue; /* timeout */

        if (pfd.revents & POLLIN) {
            client_ctx_t *ctx = calloc(1, sizeof *ctx);
            if (!ctx) {
                log_message(LOG_ERROR, "calloc failed");
                continue;
            }

            ctx->addr_len = sizeof ctx->addr;
            ctx->fd = accept(listen_fd,
                             (struct sockaddr *)&ctx->addr,
                             &ctx->addr_len);

            if (ctx->fd < 0) {
                log_message(LOG_WARN, "accept(): %s", strerror(errno));
                free(ctx);
                continue;
            }

            pthread_t tid;
            pthread_attr_t attr;
            pthread_attr_init(&attr);
            pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
            if (pthread_create(&tid, &attr, client_thread, ctx) != 0) {
                log_message(LOG_WARN, "pthread_create failed");
                close(ctx->fd);
                free(ctx);
            }
            pthread_attr_destroy(&attr);
        }
    }

    log_message(LOG_INFO, "Shutdown requested, closing listener");
    close(listen_fd);
    return EXIT_SUCCESS;
}
```