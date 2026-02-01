```c
/**
 * SynestheticCanvas – Common Library
 * ----------------------------------
 * File:    libs/sc_common/src/sc_logging.c
 * Author:  SynestheticCanvas Core Team
 *
 * A small but production-ready logging facility shared by every micro-service
 * in the SynestheticCanvas constellation.  Features:
 *
 *   • ISO-8601 timestamps with micro-second precision
 *   • Thread-safe
 *   • Log levels (TRACE → FATAL)
 *   • Optional ANSI colour output when writing to a TTY
 *   • Log-file rotation (size-based) with sane defaults
 *   • Environment-variable overrides for run-time flexibility
 *
 * This module is deliberately dependency-free (POSIX + pthread) to minimise
 * the surface area of the “common” library.  It can be dropped into any
 * existing code-base that needs structured logging without modification.
 */

#include "sc_logging.h"      /* public header for this implementation      */

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

/* -------------------------------------------------------------------------
 * Constants
 * ------------------------------------------------------------------------- */
#define SC_LOG_DEFAULT_LEVEL     SC_LOG_INFO
#define SC_LOG_DEFAULT_MAX_BYTES (10ULL * 1024ULL * 1024ULL)   /* 10 MiB   */
#define SC_LOG_MAX_SUBSYSTEM_LEN 64U
#define SC_LOG_TIME_BUF_LEN      64U
#define SC_LOG_MSG_BUF_LEN       4096U
#define SC_LOG_PATH_LEN          4096U

/* -------------------------------------------------------------------------
 * ANSI colour helpers
 * ------------------------------------------------------------------------- */
static const char *_colour_reset   = "\033[0m";
static const char *_colour_level[] = {
        [SC_LOG_TRACE] = "\033[37m", /* Bright Black / Gray   */
        [SC_LOG_DEBUG] = "\033[36m", /* Cyan                  */
        [SC_LOG_INFO]  = "\033[32m", /* Green                 */
        [SC_LOG_WARN]  = "\033[33m", /* Yellow                */
        [SC_LOG_ERROR] = "\033[31m", /* Red                   */
        [SC_LOG_FATAL] = "\033[35m", /* Magenta               */
};

/* Matching string representations */
static const char *_level_str[] = {
        [SC_LOG_TRACE] = "TRACE",
        [SC_LOG_DEBUG] = "DEBUG",
        [SC_LOG_INFO]  = "INFO ",
        [SC_LOG_WARN]  = "WARN ",
        [SC_LOG_ERROR] = "ERROR",
        [SC_LOG_FATAL] = "FATAL",
};

/* -------------------------------------------------------------------------
 * Internal state
 * ------------------------------------------------------------------------- */
typedef struct {
        FILE          *sink;                               /* current output                */
        char           active_path[SC_LOG_PATH_LEN];       /* canonical log file path       */
        char           subsystem[SC_LOG_MAX_SUBSYSTEM_LEN];
        sc_log_level_t level;                              /* threshold                     */
        uint64_t       max_bytes;                          /* rotate when > max_bytes       */
        bool           use_colour;                         /* colourise terminal output?    */
        bool           initialised;                        /* has sc_log_init() been called */
        pthread_mutex_t lock;                              /* protects writes & rotation    */
} sc_log_state_t;

/* Private singleton */
static sc_log_state_t g_log = {
        .sink         = NULL,
        .active_path  = {0},
        .subsystem    = {0},
        .level        = SC_LOG_DEFAULT_LEVEL,
        .max_bytes    = SC_LOG_DEFAULT_MAX_BYTES,
        .use_colour   = true,
        .initialised  = false,
        .lock         = PTHREAD_MUTEX_INITIALIZER,
};

/* -------------------------------------------------------------------------
 * Internal helpers
 * ------------------------------------------------------------------------- */

/* Fetch monotonic file size; returns 0 on error */
static uint64_t
_get_file_size(const char *path)
{
        struct stat st;
        if (!path || stat(path, &st) != 0) {
                return 0;
        }
        return (uint64_t)st.st_size;
}

/* Rotate the active log file: called under lock */
static void
_rotate_if_needed_locked(void)
{
        if (!g_log.sink || !*g_log.active_path || g_log.max_bytes == 0) {
                return; /* Nothing to do. */
        }

        const uint64_t sz = _get_file_size(g_log.active_path);

        if (sz < g_log.max_bytes) {
                return; /* Still under the limit. */
        }

        /* Close existing sink before renaming. */
        fflush(g_log.sink);
        fclose(g_log.sink);
        g_log.sink = NULL;

        /* Build rotated path "foo.log.YYYYMMDD-HHMMSS" */
        char rotated_path[SC_LOG_PATH_LEN] = {0};
        struct timeval tv;
        gettimeofday(&tv, NULL);

        struct tm tm_now;
        localtime_r(&tv.tv_sec, &tm_now);

        snprintf(rotated_path,
                 sizeof(rotated_path),
                 "%s.%04d%02d%02d-%02d%02d%02d",
                 g_log.active_path,
                 tm_now.tm_year + 1900,
                 tm_now.tm_mon + 1,
                 tm_now.tm_mday,
                 tm_now.tm_hour,
                 tm_now.tm_min,
                 tm_now.tm_sec);

        /* Best-effort rename; ignore errno on failure */
        rename(g_log.active_path, rotated_path);

        /* Re-open sink */
        g_log.sink = fopen(g_log.active_path, "a");
        if (!g_log.sink) { /* Fallback to stderr */
                g_log.sink = stderr;
        }
}

/* Format current UTC timestamp ISO-8601 with microsecond precision */
static void
_format_timestamp(char *buf, size_t len)
{
        struct timeval tv;
        gettimeofday(&tv, NULL);

        struct tm tm_now;
        gmtime_r(&tv.tv_sec, &tm_now);

        /* YYYY-MM-DDThh:mm:ss.mmmuuuZ */
        strftime(buf, len, "%Y-%m-%dT%H:%M:%S", &tm_now);
        size_t base_len = strlen(buf);
        snprintf(buf + base_len,
                 len - base_len,
                 ".%06ldZ",
                 tv.tv_usec);
}

/* -------------------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------------------- */
void
sc_log_init(const char *subsystem, const char *file_path)
{
        if (g_log.initialised) {
                return; /* Already initialised */
        }

        /* Set subsystem (truncated safely) */
        if (subsystem) {
                snprintf(g_log.subsystem,
                         sizeof(g_log.subsystem),
                         "%s",
                         subsystem);
        } else {
                strcpy(g_log.subsystem, "core");
        }

        /* Honour environment variable overrides */
        const char *lvl_env = getenv("SC_LOG_LEVEL");
        if (lvl_env) {
                for (int lvl = SC_LOG_TRACE; lvl <= SC_LOG_FATAL; ++lvl) {
                        if (strcasecmp(lvl_env, _level_str[lvl]) == 0) {
                                g_log.level = (sc_log_level_t)lvl;
                                break;
                        }
                }
        }

        const char *size_env = getenv("SC_LOG_MAX_SIZE");
        if (size_env) {
                /* Parse as MiB for convenience */
                long sz_mib = strtol(size_env, NULL, 10);
                if (sz_mib > 0) {
                        g_log.max_bytes = (uint64_t)sz_mib * 1024ULL * 1024ULL;
                }
        }

        /* Determine sink */
        if (file_path && *file_path) {
                snprintf(g_log.active_path,
                         sizeof(g_log.active_path),
                         "%s",
                         file_path);

                g_log.sink = fopen(g_log.active_path, "a");
                if (!g_log.sink) {
                        fprintf(stderr,
                                "sc_logging: cannot open '%s' (%s) – "
                                "falling back to stderr\n",
                                g_log.active_path,
                                strerror(errno));
                        g_log.sink = stderr;
                }
        } else {
                /* Default to stderr */
                g_log.sink = stderr;
        }

        /* Colour only if writing to TTY & not explicitly disabled */
        const char *no_colour_env = getenv("SC_LOG_NO_COLOUR");
        g_log.use_colour = (isatty(fileno(g_log.sink)) && !no_colour_env);

        /* Register atexit cleanup */
        atexit(sc_log_shutdown);

        g_log.initialised = true;
}

void
sc_log_set_level(sc_log_level_t level)
{
        g_log.level = level;
}

sc_log_level_t
sc_log_get_level(void)
{
        return g_log.level;
}

void
sc_log_shutdown(void)
{
        if (!g_log.initialised) {
                return;
        }

        pthread_mutex_lock(&g_log.lock);
        if (g_log.sink && g_log.sink != stderr && g_log.sink != stdout) {
                fflush(g_log.sink);
                fclose(g_log.sink);
        }
        g_log.sink        = NULL;
        g_log.initialised = false;
        pthread_mutex_unlock(&g_log.lock);
}

/* Core writer – varargs version used by public macro facade */
void
sc_log_write(sc_log_level_t level,
             const char    *file,
             int            line,
             const char    *fmt,
             ...)
{
        if (level < g_log.level) {
                return; /* filtered */
        }

        if (!g_log.initialised) {
                /* Lazy init to stderr when not initialised explicitly */
                sc_log_init("core", NULL);
        }

        char ts[SC_LOG_TIME_BUF_LEN];
        _format_timestamp(ts, sizeof(ts));

        char payload[SC_LOG_MSG_BUF_LEN];
        va_list ap;
        va_start(ap, fmt);
        vsnprintf(payload, sizeof(payload), fmt, ap);
        va_end(ap);

        pthread_mutex_lock(&g_log.lock);

        _rotate_if_needed_locked();

        /* Build final log line */
        if (g_log.use_colour) {
                fprintf(g_log.sink,
                        "%s%s %-5s [%s] %s:%d | %s%s\n",
                        _colour_level[level],
                        ts,
                        _level_str[level],
                        g_log.subsystem,
                        file,
                        line,
                        payload,
                        _colour_reset);
        } else {
                fprintf(g_log.sink,
                        "%s %-5s [%s] %s:%d | %s\n",
                        ts,
                        _level_str[level],
                        g_log.subsystem,
                        file,
                        line,
                        payload);
        }

        fflush(g_log.sink);

        pthread_mutex_unlock(&g_log.lock);

        /* Elevate fatal errors to process termination */
        if (level == SC_LOG_FATAL) {
                abort();
        }
}

/* -------------------------------------------------------------------------
 * End of file
 * ------------------------------------------------------------------------- */
```