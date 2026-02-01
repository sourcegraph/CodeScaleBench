/*  ===========================================================================
 *  File:    ll_logger.h
 *  Project: LexiLearn MVC Orchestrator (ml_nlp)
 *  License: MIT
 *
 *  Description:
 *      Thread-safe, highly configurable logging facility used throughout the
 *      LexiLearn code-base.  Features compile-time and run-time log-level
 *      control, automatic log-rotation, pluggable callbacks (e.g. stream logs
 *      to a Model-Registry collector), and minimal dependencies.  Everything is
 *      self-contained inside this header to ease integration with shared
 *      libraries and unit-test binaries.
 *
 *  Usage:
 *      #define LL_LOGGER_IMPLEMENTATION      // exactly once in a .c/.cpp file
 *      #include "common/ll_logger.h"
 *
 *      int main(void)
 *      {
 *          ll_logger_init("orchestrator.log", LL_LOG_INFO,
 *                         /* also log to console * / true,
 *                         /* rotate at 10 MB       * / 10 * 1024 * 1024);
 *
 *          LL_INFO("Pipeline orchestrator started (pid=%d)", getpid());
 *          ...
 *          ll_logger_shutdown();
 *      }
 *  ===========================================================================
 */
#ifndef LL_LOGGER_H_
#define LL_LOGGER_H_

/* ---------------------------------------------------------------------------
 *  Public configuration switches
 * ---------------------------------------------------------------------------*/
#ifndef LL_LOG_DISABLE            /* compile-time kill-switch              */
    #define LL_LOG_ENABLE 1
#else
    #define LL_LOG_ENABLE 0
#endif

#ifndef LL_LOG_MAX_MESSAGE_LEN
    #define LL_LOG_MAX_MESSAGE_LEN  4096      /* bytes incl. final '\0'      */
#endif

/* ---------------------------------------------------------------------------
 *  Includes
 * ---------------------------------------------------------------------------*/
#include <stdio.h>
#include <stdarg.h>
#include <stdbool.h>
#include <time.h>
#include <stdint.h>
#include <string.h>

#if LL_LOG_ENABLE
    #include <pthread.h>
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* ---------------------------------------------------------------------------
 *  Log level enumeration
 * ---------------------------------------------------------------------------*/
typedef enum
{
    LL_LOG_TRACE = 0,
    LL_LOG_DEBUG,
    LL_LOG_INFO,
    LL_LOG_WARN,
    LL_LOG_ERROR,
    LL_LOG_FATAL,
    LL_LOG_OFF            /* sentinel – nothing gets logged              */
} LLLogLevel;

/* ---------------------------------------------------------------------------
 *  Callback prototype for custom log sinks
 * ---------------------------------------------------------------------------*/
typedef void (*ll_log_callback_t)(LLLogLevel level,
                                  const struct tm *ts_utc,
                                  const char       *msg,
                                  void             *user_data);

/* ---------------------------------------------------------------------------
 *  Public API
 * ---------------------------------------------------------------------------*/

/*  Initialize logging system
 *      log_path        – path to log-file (may be NULL => file logging off)
 *      level           – minimum level to log
 *      log_to_console  – if true, send output to stderr as well
 *      max_file_size   – rotate file after this many bytes (0 => none)
 *
 *  Return: 0 on success, non-zero errno code on error.
 */
int  ll_logger_init(const char     *log_path,
                    LLLogLevel      level,
                    bool            log_to_console,
                    uint64_t        max_file_size);

/*  Modify log level at run-time */
void ll_logger_set_level(LLLogLevel level);

/*  Register additional callback sink.
 *  Pass NULL to remove existing sink.
 */
void ll_logger_register_callback(ll_log_callback_t cb, void *user_data);

/*  Graceful shutdown: flush and close log file, destroy mutex.           */
void ll_logger_shutdown(void);

/* ---------------------------------------------------------------------------
 *  Logging macros – client code uses these
 * ---------------------------------------------------------------------------*/
#if LL_LOG_ENABLE
    #define LL_LOG_INTERNAL(lvl, fmt, ...)                                         \
        ll_logger_write((lvl), __FILE__, __LINE__, __func__, (fmt), ##__VA_ARGS__)

    #define LL_TRACE(fmt, ...)  LL_LOG_INTERNAL(LL_LOG_TRACE, (fmt), ##__VA_ARGS__)
    #define LL_DEBUG(fmt, ...)  LL_LOG_INTERNAL(LL_LOG_DEBUG, (fmt), ##__VA_ARGS__)
    #define LL_INFO(fmt,  ...)  LL_LOG_INTERNAL(LL_LOG_INFO,  (fmt), ##__VA_ARGS__)
    #define LL_WARN(fmt,  ...)  LL_LOG_INTERNAL(LL_LOG_WARN,  (fmt), ##__VA_ARGS__)
    #define LL_ERROR(fmt, ...)  LL_LOG_INTERNAL(LL_LOG_ERROR, (fmt), ##__VA_ARGS__)
    #define LL_FATAL(fmt, ...)  LL_LOG_INTERNAL(LL_LOG_FATAL, (fmt), ##__VA_ARGS__)
#else
    /*  Compile-out logging completely */
    #define LL_TRACE(fmt, ...)
    #define LL_DEBUG(fmt, ...)
    #define LL_INFO(fmt,  ...)
    #define LL_WARN(fmt,  ...)
    #define LL_ERROR(fmt, ...)
    #define LL_FATAL(fmt, ...)
#endif /* LL_LOG_ENABLE */

/* ---------------------------------------------------------------------------
 *  Internal interface – DO NOT USE DIRECTLY
 * ---------------------------------------------------------------------------*/
#if LL_LOG_ENABLE
void ll_logger_write(LLLogLevel level,
                     const char *file,
                     int         line,
                     const char *func,
                     const char *fmt, ...) __attribute__((format(printf,5,6)));
#endif

/* ---------------------------------------------------------------------------
 *  Implementation (define LL_LOGGER_IMPLEMENTATION *once*)
 * ---------------------------------------------------------------------------*/
#ifdef LL_LOGGER_IMPLEMENTATION
    #include <sys/stat.h>
    #include <errno.h>
    #include <inttypes.h>
    #include <stdlib.h>

    typedef struct
    {
        FILE            *fp;
        char             path[4096];
        uint64_t         max_size;
        LLLogLevel       level;
        bool             log_to_stderr;
        ll_log_callback_t cb;
        void            *cb_user;
        pthread_mutex_t  lock;
    } ll_logger_t;

    static ll_logger_t g_ll_logger = {
        .fp             = NULL,
        .path           = {0},
        .max_size       = 0,
        .level          = LL_LOG_INFO,
        .log_to_stderr  = true,
        .cb             = NULL,
        .cb_user        = NULL,
        .lock           = PTHREAD_MUTEX_INITIALIZER
    };

    /* -------------------------------------------------------
     *  Helpers
     * -------------------------------------------------------*/
    static const char *s_lvl_str(LLLogLevel lvl)
    {
        static const char *LUT[] = {
            "TRACE", "DEBUG", "INFO ", "WARN ", "ERROR", "FATAL", "OFF"
        };
        return LUT[(int)lvl];
    }

    static int s_rotate_if_needed(ll_logger_t *lg)
    {
        if (!lg->fp || lg->max_size == 0) return 0;

        long pos = ftell(lg->fp);
        if (pos < 0) return errno;

        uint64_t size = (uint64_t)pos;
        if (size < lg->max_size) return 0;          /* no rotation */

        /* Close current file */
        fclose(lg->fp);
        lg->fp = NULL;

        /* Generate rotated name with timestamp */
        time_t t = time(NULL);
        struct tm tm_utc;
        gmtime_r(&t, &tm_utc);

        char rotated[4096 + 64];
        snprintf(rotated, sizeof rotated,
                 "%s.%04d%02d%02dT%02d%02d%02d",
                 lg->path,
                 tm_utc.tm_year + 1900, tm_utc.tm_mon + 1, tm_utc.tm_mday,
                 tm_utc.tm_hour, tm_utc.tm_min, tm_utc.tm_sec);

        /* Rename */
        if (rename(lg->path, rotated) != 0)
        {
            /* best effort – continue */
        }

        /* Re-open */
        lg->fp = fopen(lg->path, "a");
        if (!lg->fp) return errno;

        return 0;
    }

    static void s_format_timestamp(struct tm *out_tm, char *buf, size_t len)
    {
        time_t now = time(NULL);
        gmtime_r(&now, out_tm);
        /* ISO-8601 UTC */
        strftime(buf, len, "%Y-%m-%dT%H:%M:%S", out_tm);
    }

    /* -------------------------------------------------------
     *  Public API implementation
     * -------------------------------------------------------*/
    int ll_logger_init(const char     *log_path,
                       LLLogLevel      level,
                       bool            log_to_console,
                       uint64_t        max_file_size)
    {
        pthread_mutex_lock(&g_ll_logger.lock);

        g_ll_logger.level         = level;
        g_ll_logger.log_to_stderr = log_to_console;
        g_ll_logger.max_size      = max_file_size;

        if (log_path)
        {
            strncpy(g_ll_logger.path, log_path, sizeof(g_ll_logger.path)-1);
            g_ll_logger.fp = fopen(log_path, "a");
            if (!g_ll_logger.fp)
            {
                int err = errno;
                pthread_mutex_unlock(&g_ll_logger.lock);
                return err;
            }
            setvbuf(g_ll_logger.fp, NULL, _IOLBF, 0);    /* line buffered */
        }

        pthread_mutex_unlock(&g_ll_logger.lock);
        return 0;
    }

    void ll_logger_set_level(LLLogLevel level)
    {
        pthread_mutex_lock(&g_ll_logger.lock);
        g_ll_logger.level = level;
        pthread_mutex_unlock(&g_ll_logger.lock);
    }

    void ll_logger_register_callback(ll_log_callback_t cb, void *user_data)
    {
        pthread_mutex_lock(&g_ll_logger.lock);
        g_ll_logger.cb       = cb;
        g_ll_logger.cb_user  = user_data;
        pthread_mutex_unlock(&g_ll_logger.lock);
    }

    void ll_logger_shutdown(void)
    {
        pthread_mutex_lock(&g_ll_logger.lock);
        if (g_ll_logger.fp)
        {
            fflush(g_ll_logger.fp);
            fclose(g_ll_logger.fp);
            g_ll_logger.fp = NULL;
        }
        pthread_mutex_unlock(&g_ll_logger.lock);

        /* Destroy mutex in case of valgrind complaints */
        pthread_mutex_destroy(&g_ll_logger.lock);
    }

    /* -------------------------------------------------------
     *  Core writer
     * -------------------------------------------------------*/
    void ll_logger_write(LLLogLevel level,
                         const char *file,
                         int         line,
                         const char *func,
                         const char *fmt, ...)
    {
        if (level < g_ll_logger.level || level >= LL_LOG_OFF)
            return;

        char message[LL_LOG_MAX_MESSAGE_LEN];
        va_list ap;
        va_start(ap, fmt);
        vsnprintf(message, sizeof message, fmt, ap);
        va_end(ap);

        /* Build final log line */
        char timestamp[32];
        struct tm ts_utc;
        s_format_timestamp(&ts_utc, timestamp, sizeof timestamp);

        pthread_mutex_lock(&g_ll_logger.lock);

        /* Rotate file if necessary */
        s_rotate_if_needed(&g_ll_logger);

        /* Compose header */
        char header[512];
        snprintf(header, sizeof header,
                 "[%s] %-5s %s:%d (%s): ",
                 timestamp, s_lvl_str(level),
                 file, line, func);

        /* Write to FILE* */
        if (g_ll_logger.fp)
        {
            fputs(header, g_ll_logger.fp);
            fputs(message, g_ll_logger.fp);
            fputc('\n', g_ll_logger.fp);
            fflush(g_ll_logger.fp);
        }

        /* Write to stderr */
        if (g_ll_logger.log_to_stderr)
        {
            fputs(header, stderr);
            fputs(message, stderr);
            fputc('\n', stderr);
            fflush(stderr);
        }

        /* Forward to callback */
        if (g_ll_logger.cb)
            g_ll_logger.cb(level, &ts_utc, message, g_ll_logger.cb_user);

        pthread_mutex_unlock(&g_ll_logger.lock);
    }

#endif /* LL_LOGGER_IMPLEMENTATION */

/* ---------------------------------------------------------------------------
 *  End of header
 * ---------------------------------------------------------------------------*/
#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LL_LOGGER_H_ */
