/**
 * @file logger.c
 * @author
 * @brief Thread-safe, multi-destination logger used throughout the
 *        EduPay Ledger Academy shared-kernel.  The implementation is
 *        dependency-free (aside from the C standard library + pthreads) so that
 *        professors can replace the transport layer (e.g., ship to syslog,
 *        Fluent Bit, or an observability side-car) without touching the rest of
 *        the domain.
 *
 *        Features
 *        ---------
 *        • Console + file logging with colourised ANSI output.
 *        • Log-level filtering (TRACE → FATAL).
 *        • File rotation based on maximum on-disk size.
 *        • Re-entrant, thread-safe design using an internal mutex.
 *        • Minimal heap allocations to remain friendly in embedded
 *          demonstrations.
 *
 *        Compile-time Flags
 *        ------------------
 *        LOG_DISABLE_COLOUR   – Disable ANSI colour even when `colourize`
 *                               runtime option is true.
 *        EDU_ENV_PRODUCTION   – Strips TRACE/DEBUG at compile-time.
 *
 *        Public API is declared in `logger.h`.
 */

#include "logger.h"           /* Public interface                                        */
#include <errno.h>            /* errno                                                   */
#include <pthread.h>          /* pthread_mutex_*                                         */
#include <stdarg.h>           /* va_list, va_start, va_end                               */
#include <stdbool.h>          /* bool                                                    */
#include <stdint.h>           /* uint64_t                                                */
#include <stdio.h>            /* FILE, fprintf, fopen, fflush                            */
#include <stdlib.h>           /* getenv, malloc (only for rotation tmp path)             */
#include <string.h>           /* strlen, strcpy, strncpy                                 */
#include <sys/stat.h>         /* stat                                                    */
#include <time.h>             /* localtime_r, strftime                                   */
#include <unistd.h>           /* access, rename                                          */

/* -------------------------------------------------------------------------- */
/* Local constants                                                            */
/* -------------------------------------------------------------------------- */

#define LOGGER_DATE_STAMP_LEN      32U
#define LOGGER_MAX_LINE_LEN        2048U
#define LOGGER_ROTATE_SUFFIX_LEN   32U
#define LOGGER_ROTATE_CHECK_EVERY  256U   /* Check file size every N writes   */

#ifndef LOGGER_DEFAULT_MAX_FILE_SIZE
#   define LOGGER_DEFAULT_MAX_FILE_SIZE (10ULL * 1024ULL * 1024ULL) /* 10 MiB */
#endif

/* -------------------------------------------------------------------------- */
/* Helper macros                                                              */
/* -------------------------------------------------------------------------- */

#define UNUSED(x)    (void)(x)

/* Colour escape codes */
#ifndef LOG_DISABLE_COLOUR
#   define COLOUR_RED      "\x1b[31m"
#   define COLOUR_GREEN    "\x1b[32m"
#   define COLOUR_YELLOW   "\x1b[33m"
#   define COLOUR_BLUE     "\x1b[34m"
#   define COLOUR_MAGENTA  "\x1b[35m"
#   define COLOUR_CYAN     "\x1b[36m"
#   define COLOUR_RESET    "\x1b[0m"
#else
#   define COLOUR_RED      ""
#   define COLOUR_GREEN    ""
#   define COLOUR_YELLOW   ""
#   define COLOUR_BLUE     ""
#   define COLOUR_MAGENTA  ""
#   define COLOUR_CYAN     ""
#   define COLOUR_RESET    ""
#endif

/* -------------------------------------------------------------------------- */
/* Internal state                                                             */
/* -------------------------------------------------------------------------- */

/* Maps log_level -> string/colour pair */
typedef struct {
    const char *name;
    const char *colour;
} level_meta_t;

static const level_meta_t k_level_meta[LOG_LEVEL_COUNT] = {
    [LOG_TRACE] = {"TRACE", COLOUR_CYAN},
    [LOG_DEBUG] = {"DEBUG", COLOUR_BLUE},
    [LOG_INFO]  = {"INFO ", COLOUR_GREEN},
    [LOG_WARN]  = {"WARN ", COLOUR_YELLOW},
    [LOG_ERROR] = {"ERROR", COLOUR_RED},
    [LOG_FATAL] = {"FATAL", COLOUR_MAGENTA},
};

/* Global config (single-instance by design) */
typedef struct {
    FILE          *fp;                       /* File stream or NULL           */
    char           path[PATH_MAX];           /* Path for rotation             */
    bool           console_enabled;          /* Also emit to stdout/stderr    */
    bool           colourize;                /* Colourise console output      */
    log_level_t    level;                    /* Current threshold             */
    uint64_t       max_file_size_bytes;      /* Rotation threshold            */
    uint64_t       write_count;              /* Writes since last stat()      */
    pthread_mutex_t mutex;                   /* Serialises emitters           */
    bool           is_init;                  /* Initialised flag              */
} logger_t;

static logger_t g_logger = {
    .fp                   = NULL,
    .console_enabled      = true,
    .colourize            = true,
    .level                = LOG_INFO,
    .max_file_size_bytes  = LOGGER_DEFAULT_MAX_FILE_SIZE,
    .write_count          = 0ULL,
    .mutex                = PTHREAD_MUTEX_INITIALIZER,
    .is_init              = false
};

/* -------------------------------------------------------------------------- */
/* Forward decl                                                               */
/* -------------------------------------------------------------------------- */
static void logger_rotate_if_needed(void);
static int  logger_open_file(const char *path);

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

int
logger_init(const logger_options_t *opts)
{
    if (opts == NULL) {
        return -EINVAL;
    }

    pthread_mutex_lock(&g_logger.mutex);

    if (g_logger.is_init) {
        pthread_mutex_unlock(&g_logger.mutex);
        return 0; /* already initialised */
    }

    g_logger.console_enabled     = opts->console;
    g_logger.colourize           = opts->colour;
    g_logger.level               = opts->level;
    g_logger.max_file_size_bytes = (opts->max_file_sz > 0)
                                     ? opts->max_file_sz
                                     : LOGGER_DEFAULT_MAX_FILE_SIZE;

    if (opts->file_path && *opts->file_path) {
        if (logger_open_file(opts->file_path) != 0) {
            pthread_mutex_unlock(&g_logger.mutex);
            return -errno;
        }
        (void)strncpy(g_logger.path, opts->file_path, sizeof(g_logger.path) - 1U);
        g_logger.path[sizeof(g_logger.path) - 1U] = '\0';
    }

    g_logger.is_init = true;
    pthread_mutex_unlock(&g_logger.mutex);
    return 0;
}

void
logger_set_level(log_level_t level)
{
    pthread_mutex_lock(&g_logger.mutex);
    g_logger.level = level;
    pthread_mutex_unlock(&g_logger.mutex);
}

void
logger_flush(void)
{
    pthread_mutex_lock(&g_logger.mutex);
    if (g_logger.fp != NULL) {
        fflush(g_logger.fp);
    }
    fflush(stdout);
    fflush(stderr);
    pthread_mutex_unlock(&g_logger.mutex);
}

void
logger_shutdown(void)
{
    pthread_mutex_lock(&g_logger.mutex);
    if (g_logger.fp) {
        fflush(g_logger.fp);
        fclose(g_logger.fp);
        g_logger.fp = NULL;
    }
    g_logger.is_init = false;
    pthread_mutex_unlock(&g_logger.mutex);
}

void
logger_log_internal(log_level_t level,
                    const char *src_file,
                    const char *func,
                    int         line,
                    const char *fmt, ...)
{
#if defined(EDU_ENV_PRODUCTION)
    /* Optimise away TRACE/DEBUG in production */
    if (level <= LOG_DEBUG) {
        return;
    }
#endif

    if (level < g_logger.level) {
        return;
    }

    char timestamp[LOGGER_DATE_STAMP_LEN];
    time_t now = time(NULL);
    struct tm tm_info;
    localtime_r(&now, &tm_info);
    strftime(timestamp, sizeof timestamp, "%Y-%m-%d %H:%M:%S", &tm_info);

    char message[LOGGER_MAX_LINE_LEN];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(message, sizeof message, fmt, ap);
    va_end(ap);

    pthread_mutex_lock(&g_logger.mutex);

    /* ------------------------------------------------------------------ */
    /* File sink                                                          */
    /* ------------------------------------------------------------------ */
    if (g_logger.fp != NULL) {
        fprintf(g_logger.fp, "%s | %-5s | %s:%d %s() | %s\n",
                timestamp,
                k_level_meta[level].name,
                src_file, line, func,
                message);

        /* Rotate periodically to amortise cost of stat() */
        if (++g_logger.write_count % LOGGER_ROTATE_CHECK_EVERY == 0U) {
            logger_rotate_if_needed();
        }
    }

    /* ------------------------------------------------------------------ */
    /* Console sink                                                       */
    /* ------------------------------------------------------------------ */
    if (g_logger.console_enabled) {
        FILE *out = (level >= LOG_ERROR) ? stderr : stdout;

        if (g_logger.colourize) {
            fprintf(out, "%s%s%s | %s | %s\n",
                    k_level_meta[level].colour, k_level_meta[level].name,
                    COLOUR_RESET, timestamp, message);
        } else {
            fprintf(out, "%-5s | %s | %s\n",
                    k_level_meta[level].name, timestamp, message);
        }
    }

    pthread_mutex_unlock(&g_logger.mutex);
}

/* -------------------------------------------------------------------------- */
/* Internal helpers                                                           */
/* -------------------------------------------------------------------------- */

/**
 * @brief Open log file in append mode creating any intermediate directories
 *        if necessary.
 */
static int
logger_open_file(const char *path)
{
    /* Create missing directories (best effort)                            */
    char tmp[PATH_MAX];
    (void)strncpy(tmp, path, sizeof(tmp) - 1U);
    tmp[sizeof(tmp) - 1U] = '\0';

    for (char *p = tmp + 1; *p; ++p) {
        if (*p == '/') {
            *p = '\0';
            if (access(tmp, F_OK) != 0 && mkdir(tmp, 0775) != 0 && errno != EEXIST) {
                return -errno;
            }
            *p = '/';
        }
    }

    FILE *fp = fopen(path, "a");
    if (!fp) {
        return -errno;
    }

    /* line buffering for better perf w/o losing data on crash             */
    setvbuf(fp, NULL, _IOLBF, 1024);
    g_logger.fp = fp;
    return 0;
}

/**
 * @brief Rotate the active log file when its size exceeds threshold.
 *
 *        Old file renamed to <name>.<timestamp>.log
 */
static void
logger_rotate_if_needed(void)
{
    if (g_logger.fp == NULL) {
        return;
    }

    /* Get current size                                                    */
    struct stat st;
    if (stat(g_logger.path, &st) != 0) {
        return;
    }

    if ((uint64_t)st.st_size < g_logger.max_file_size_bytes) {
        return; /* not yet time */
    }

    /* Close current file                                                  */
    fflush(g_logger.fp);
    fclose(g_logger.fp);
    g_logger.fp = NULL;

    /* Build rotated filename                                              */
    char rotated[PATH_MAX + LOGGER_ROTATE_SUFFIX_LEN];
    time_t now = time(NULL);
    struct tm tm_info;
    localtime_r(&now, &tm_info);

    char ts_suffix[LOGGER_ROTATE_SUFFIX_LEN];
    strftime(ts_suffix, sizeof ts_suffix, "%Y%m%d-%H%M%S", &tm_info);

    snprintf(rotated, sizeof rotated, "%s.%s.log", g_logger.path, ts_suffix);

    /* Rename -> rotate                                                    */
    if (rename(g_logger.path, rotated) != 0) {
        /* If rename fails, attempt to continue logging anyway             */
    }

    /* Reopen fresh file                                                   */
    (void)logger_open_file(g_logger.path);
}

/* -------------------------------------------------------------------------- */
/* End of file                                                                */
/* -------------------------------------------------------------------------- */
