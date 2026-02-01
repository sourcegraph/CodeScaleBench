/*
 * ll_logger.c
 *
 * Centralized, thread-safe logging facility for the LexiLearn MVC Orchestrator.
 *
 * Production-quality features:
 *  - Multiple log levels
 *  - Log file rotation based on configurable size
 *  - Optional colorized stderr output for interactive debugging
 *  - Environment-variable overrides for runtime configurability
 *  - Mutex-guarded critical sections for thread safety
 *  - Minimal external dependencies (POSIX only)
 *
 * Author: LexiLearn Core Engineering Team
 * SPDX-License-Identifier: MIT
 */

#define _POSIX_C_SOURCE 200809L   /* For getline, clock_gettime, strftime */
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include "ll_logger.h"           /* Public interface / macros */


/* ---------- Internal constants ---------- */

#define LL_DEFAULT_MAX_SIZE_MB   10          /* Rotate when log file > 10 MB */
#define LL_MAX_TIMESTAMP_LEN     64
#define LL_MAX_TRUNCATED_MSG     4096

/* ANSI colors (foreground) */
#define ANSI_RESET   "\033[0m"
#define ANSI_GREY    "\033[90m"
#define ANSI_RED     "\033[91m"
#define ANSI_GREEN   "\033[92m"
#define ANSI_YELLOW  "\033[93m"
#define ANSI_BLUE    "\033[94m"
#define ANSI_MAGENTA "\033[95m"
#define ANSI_CYAN    "\033[96m"


/* ---------- Internal data structures ---------- */

typedef struct {
    char             module_name[64];         /* Short identifier for log source */
    char             log_path[PATH_MAX];      /* Absolute path to current log file */
    FILE            *fp;                      /* Active log stream */
    LL_LOG_LEVEL     level;                   /* Minimum severity to record */
    size_t           max_bytes;               /* Rotation threshold */
    bool             also_stderr;             /* Mirror messages to stderr? */
    bool             use_color;               /* Colorize stderr output? */
    pthread_mutex_t  mutex;                   /* Guard all state */
    bool             initialized;             /* Defensive flag */
} ll_logger_t;


/* ---------- Singleton instance ---------- */

static ll_logger_t g_logger = {
    .fp          = NULL,
    .level       = LL_LOG_INFO,
    .max_bytes   = LL_DEFAULT_MAX_SIZE_MB * 1024 * 1024,
    .also_stderr = true,
    .use_color   = true,
    .mutex       = PTHREAD_MUTEX_INITIALIZER,
    .initialized = false
};


/* ---------- Forward declarations ---------- */

static const char *level_to_string(LL_LOG_LEVEL level);
static const char *level_to_color(LL_LOG_LEVEL level);
static int          ensure_open_locked(void);
static int          maybe_rotate_locked(void);
static void         write_locked(LL_LOG_LEVEL level,
                                 const char *timestamp,
                                 const char *msg);


/* ---------- Helper functions ---------- */

/*
 * build_timestamp
 *   Produce RFC-3339-ish timestamp "YYYY-MM-DDTHH:MM:SS.mmmZ".
 *   Buffer must be at least LL_MAX_TIMESTAMP_LEN.
 */
static void build_timestamp(char *buf, size_t len)
{
    struct timespec ts;
    struct tm       tm_info;

    clock_gettime(CLOCK_REALTIME, &ts);
    gmtime_r(&ts.tv_sec, &tm_info);

    int written = strftime(buf, len, "%Y-%m-%dT%H:%M:%S", &tm_info);
    snprintf(buf + written, len - (size_t)written, ".%03ldZ", ts.tv_nsec / 1000000L);
}


static const char *level_to_string(LL_LOG_LEVEL level)
{
    switch (level) {
        case LL_LOG_TRACE: return "TRACE";
        case LL_LOG_DEBUG: return "DEBUG";
        case LL_LOG_INFO:  return "INFO ";
        case LL_LOG_WARN:  return "WARN ";
        case LL_LOG_ERROR: return "ERROR";
        case LL_LOG_FATAL: return "FATAL";
        default:           return "UKN  ";
    }
}


static const char *level_to_color(LL_LOG_LEVEL level)
{
    switch (level) {
        case LL_LOG_TRACE: return ANSI_GREY;
        case LL_LOG_DEBUG: return ANSI_CYAN;
        case LL_LOG_INFO:  return ANSI_GREEN;
        case LL_LOG_WARN:  return ANSI_YELLOW;
        case LL_LOG_ERROR: return ANSI_RED;
        case LL_LOG_FATAL: return ANSI_MAGENTA;
        default:           return ANSI_RESET;
    }
}


/*
 * expand_env_or_default
 *   Return env var value if defined and non-empty, otherwise default_value.
 */
static const char *expand_env_or_default(const char *env_var, const char *default_value)
{
    const char *val = getenv(env_var);
    return (val && *val) ? val : default_value;
}


/*
 * parse_level
 *   Convert string (e.g., "debug") to LL_LOG_LEVEL, default if unrecognized.
 */
static LL_LOG_LEVEL parse_level(const char *str, LL_LOG_LEVEL default_level)
{
    if (!str) return default_level;

    if (strcasecmp(str, "trace") == 0) return LL_LOG_TRACE;
    if (strcasecmp(str, "debug") == 0) return LL_LOG_DEBUG;
    if (strcasecmp(str, "info")  == 0) return LL_LOG_INFO;
    if (strcasecmp(str, "warn")  == 0 ||
        strcasecmp(str, "warning") == 0) return LL_LOG_WARN;
    if (strcasecmp(str, "error") == 0) return LL_LOG_ERROR;
    if (strcasecmp(str, "fatal") == 0) return LL_LOG_FATAL;

    return default_level;
}


/*
 * ensure_open_locked
 *   Open log file if not already. Must be called with mutex held.
 *   Returns 0 on success, ‑1 on failure (stderr fallback still allowed).
 */
static int ensure_open_locked(void)
{
    if (g_logger.fp) return 0;

    /* Create directory tree if necessary */
    char dir[PATH_MAX];
    strncpy(dir, g_logger.log_path, sizeof dir);
    char *slash = strrchr(dir, '/');
    if (slash) {
        *slash = '\0';
        if (mkdir(dir, 0755) == -1 && errno != EEXIST) {
            fprintf(stderr, "ll_logger: mkdir('%s') failed: %s\n",
                    dir, strerror(errno));
            return -1;
        }
    }

    g_logger.fp = fopen(g_logger.log_path, "a");
    if (!g_logger.fp) {
        fprintf(stderr, "ll_logger: fopen('%s') failed: %s\n",
                g_logger.log_path, strerror(errno));
        return -1;
    }

    setvbuf(g_logger.fp, NULL, _IOLBF, 0); /* line-buffered */
    return 0;
}


/*
 * maybe_rotate_locked
 *   Rotate if file exceeds max_bytes. Caller must hold mutex and
 *   ensure g_logger.fp is open.
 */
static int maybe_rotate_locked(void)
{
    if (!g_logger.fp) return -1;

    long pos = ftell(g_logger.fp);
    if (pos < 0) return -1;

    if ((size_t)pos < g_logger.max_bytes) return 0;

    /* Close current file */
    fclose(g_logger.fp);
    g_logger.fp = NULL;

    /* Build rotated filename "name.log.YYYYMMDDHHMMSS" */
    char rotated_path[PATH_MAX];
    char timestamp[LL_MAX_TIMESTAMP_LEN];
    build_timestamp(timestamp, sizeof timestamp);
    /* Remove non-filename chars */
    for (char *p = timestamp; *p; ++p)
        if (*p == ':' || *p == 'T' || *p == 'Z' || *p == '-') *p = '_';

    snprintf(rotated_path, sizeof rotated_path, "%s.%s", g_logger.log_path, timestamp);

    if (rename(g_logger.log_path, rotated_path) == -1) {
        fprintf(stderr, "ll_logger: rotate rename failed: %s\n", strerror(errno));
        /* Attempt to continue with new file */
    }

    return ensure_open_locked();
}


/*
 * write_locked
 *   Core logging routine. Assumes message has no trailing newline.
 */
static void write_locked(LL_LOG_LEVEL level,
                         const char *timestamp,
                         const char *msg)
{
    if (!g_logger.initialized)
        return;

    /* Lazily open file and rotate if needed */
    if (ensure_open_locked() == 0)
        maybe_rotate_locked();

    /* Compose log line */
    if (g_logger.fp) {
        fprintf(g_logger.fp, "%s  %s  %-5s  %s\n",
                timestamp,
                g_logger.module_name,
                level_to_string(level),
                msg);
    }

    if (g_logger.also_stderr) {
        if (g_logger.use_color)
            fprintf(stderr, "%s%s  %s  %-5s  %s%s\n",
                    level_to_color(level),
                    timestamp,
                    g_logger.module_name,
                    level_to_string(level),
                    msg,
                    ANSI_RESET);
        else
            fprintf(stderr, "%s  %s  %-5s  %s\n",
                    timestamp,
                    g_logger.module_name,
                    level_to_string(level),
                    msg);
    }

    if (level == LL_LOG_FATAL) {
        fflush(stderr);
        if (g_logger.fp)
            fflush(g_logger.fp);
    }
}


/* ---------- Public API implementation ---------- */

int ll_logger_init(const char *module_name, const char *log_dir)
{
    if (!module_name || !*module_name) {
        fprintf(stderr, "ll_logger: module_name required\n");
        return -1;
    }

    pthread_mutex_lock(&g_logger.mutex);

    if (g_logger.initialized) {
        pthread_mutex_unlock(&g_logger.mutex);
        return 0; /* Already initialized */
    }

    /* Copy module name (truncated) */
    snprintf(g_logger.module_name, sizeof g_logger.module_name, "%s", module_name);

    /* Resolve log directory */
    const char *dir_env = expand_env_or_default("LL_LOG_DIR",
                                                log_dir ? log_dir : "./logs");
    size_t dir_len = strlen(dir_env);
    if (dir_len + 1 + strlen(module_name) + 4 >= sizeof g_logger.log_path) {
        fprintf(stderr, "ll_logger: log path too long\n");
        pthread_mutex_unlock(&g_logger.mutex);
        return -1;
    }

    snprintf(g_logger.log_path, sizeof g_logger.log_path,
             "%s/%s.log", dir_env, module_name);

    /* Level from env or default */
    const char *lvl_env = getenv("LL_LOG_LEVEL");
    g_logger.level = parse_level(lvl_env, g_logger.level);

    /* Max size env override */
    const char *size_env = getenv("LL_LOG_MAX_MB");
    if (size_env && *size_env) {
        char *end = NULL;
        long mb = strtol(size_env, &end, 10);
        if (end && *end == '\0' && mb > 0)
            g_logger.max_bytes = (size_t)mb * 1024 * 1024;
    }

    /* Disable color if non-TTY or env override */
    if (!isatty(STDERR_FILENO) ||
        getenv("LL_LOG_NO_COLOR"))
        g_logger.use_color = false;

    /* Redirection control */
    if (getenv("LL_LOG_FILE_ONLY"))
        g_logger.also_stderr = false;

    /* Open first log file */
    ensure_open_locked();

    g_logger.initialized = true;

    pthread_mutex_unlock(&g_logger.mutex);
    return 0;
}


void ll_logger_set_level(LL_LOG_LEVEL level)
{
    pthread_mutex_lock(&g_logger.mutex);
    g_logger.level = level;
    pthread_mutex_unlock(&g_logger.mutex);
}


void ll_logger_log(LL_LOG_LEVEL level, const char *fmt, ...)
{
    if (level < g_logger.level)
        return;

    char timestamp[LL_MAX_TIMESTAMP_LEN];
    build_timestamp(timestamp, sizeof timestamp);

    char msg[LL_MAX_TRUNCATED_MSG];

    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msg, sizeof msg, fmt, ap);
    va_end(ap);

    pthread_mutex_lock(&g_logger.mutex);
    write_locked(level, timestamp, msg);
    pthread_mutex_unlock(&g_logger.mutex);

    /* Fatal => exit */
    if (level == LL_LOG_FATAL) {
        ll_logger_close();
        abort(); /* Generate core for post-mortem */
    }
}


void ll_logger_flush(void)
{
    pthread_mutex_lock(&g_logger.mutex);
    if (g_logger.fp)
        fflush(g_logger.fp);
    pthread_mutex_unlock(&g_logger.mutex);
}


void ll_logger_close(void)
{
    pthread_mutex_lock(&g_logger.mutex);
    if (g_logger.fp) {
        fclose(g_logger.fp);
        g_logger.fp = NULL;
    }
    g_logger.initialized = false;
    pthread_mutex_unlock(&g_logger.mutex);
}


/* ---------- End of file ---------- */
