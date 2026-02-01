```c
/**
 * ============================================================================
 *  SynestheticCanvas/scripts/build.c
 *  ---------------------------------------------------------------------------
 *  A production-grade build orchestrator for the SynestheticCanvas micro-
 *  service constellation.  Written in C to guarantee predictable behaviour on
 *  every POSIX-compliant deployment target without relying on the vagaries of
 *  a developer’s shell environment.
 *
 *  The tool performs the following responsibilities:
 *    • Command-line parsing (see `print_usage()` for options)
 *    • Repository-root discovery (by walking up until a “.git” or
 *      “synesthetic.yaml” sentinel is found)
 *    • Parallel, colourised invocation of underlying build systems
 *      (defaults to “make”, but can be overridden per-service via
 *      “build.cfg” files)
 *    • Incremental rebuild checks using `stat(2)` timestamps
 *    • Graceful signal handling for Ctrl-C / SIGTERM
 *    • Aggregated status reporting suitable for CI
 *
 *  Compile:
 *      cc -std=c11 -Wall -Wextra -pedantic -pthread \
 *         -o build SynestheticCanvas/scripts/build.c
 *
 *  Copyright (c) 2023-2024, SynestheticCanvas Contributors
 *  SPDX-License-Identifier: MIT
 * ============================================================================
 */

#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* ────────────────────────────────────────────────────────────────────────── */
/*                               Configuration                               */
/* ────────────────────────────────────────────────────────────────────────── */

/* Hard-coded list of canonical service build directories (relative to repo) */
static const char *DEFAULT_SERVICES[] = {
    "services/palette_manager",
    "services/texture_synth",
    "services/audio_anim",
    "services/narrative_engine",
    NULL
};

/* Maximum number of parallel jobs if “-j” is not provided */
#define DEFAULT_PARALLELISM 4

/* Global flag toggled by signal handler */
static volatile sig_atomic_t g_cancel_requested = 0;

/* ────────────────────────────────────────────────────────────────────────── */
/*                           Utility / Infrastructure                        */
/* ────────────────────────────────────────────────────────────────────────── */

static void colour_print(const char *code, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "%s", code);
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\033[0m"); /* reset */
    va_end(ap);
}

#define info(fmt, ...)    colour_print("\033[1;34m", "[INFO] " fmt "\n", ##__VA_ARGS__)
#define warn(fmt, ...)    colour_print("\033[1;33m", "[WARN] " fmt "\n", ##__VA_ARGS__)
#define err(fmt, ...)     colour_print("\033[1;31m", "[ERR ] " fmt "\n", ##__VA_ARGS__)
#define success(fmt, ...) colour_print("\033[1;32m", "[OK  ] " fmt "\n", ##__VA_ARGS__)

/* Returns current time as “HH:MM:SS” (static buffer). */
static const char *timestamp(void)
{
    static char buf[9];
    time_t      t = time(NULL);
    struct tm   tm;
    localtime_r(&t, &tm);
    strftime(buf, sizeof buf, "%H:%M:%S", &tm);
    return buf;
}

/* Join two paths safely into “dst”. */
static void join_path(char *dst, size_t dst_sz, const char *a, const char *b)
{
    snprintf(dst, dst_sz, "%s/%s", a, b);
}

/* Ascend the directory tree until a sentinel file is found. */
static bool find_repo_root(char *out, size_t len)
{
    char cwd[PATH_MAX];
    if (!getcwd(cwd, sizeof cwd))
        return false;

    while (true) {
        char probe_a[PATH_MAX], probe_b[PATH_MAX];
        join_path(probe_a, sizeof probe_a, cwd, ".git");
        join_path(probe_b, sizeof probe_b, cwd, "synesthetic.yaml");

        if (!access(probe_a, F_OK) || !access(probe_b, F_OK)) {
            strncpy(out, cwd, len);
            return true;
        }

        /* Reached filesystem root? */
        if (!strcmp(cwd, "/"))
            return false;

        /* Go one level up */
        char *slash = strrchr(cwd, '/');
        if (slash)
            *slash = '\0';
    }
}

/* Retrieve modification time of a path, returns 0 on error */
static time_t mtime_of(const char *path)
{
    struct stat st;
    if (stat(path, &st) == 0)
        return st.st_mtime;
    return 0;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                               Data Models                                 */
/* ────────────────────────────────────────────────────────────────────────── */

typedef struct {
    char   dir[PATH_MAX];   /* service directory (abs) */
    bool   needs_build;     /* determined during scan  */
    int    result;          /* exit status of build    */
} service_t;

typedef struct {
    service_t *services;
    size_t     count;
    int        parallelism;
    bool       verbose;
    const char *build_cmd;  /* default 'make'          */
} build_ctx_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*                               CLI Parsing                                 */
/* ────────────────────────────────────────────────────────────────────────── */

static void print_usage(const char *argv0)
{
    fprintf(stderr,
        "SynestheticCanvas Build Tool\n"
        "Usage: %s [options]\n"
        "Options:\n"
        "  --all                  Build all services (default)\n"
        "  --service <name>       Build a single service by directory name\n"
        "  --clean                Perform a clean build (runs 'make clean')\n"
        "  -j, --jobs <n>         Parallel build jobs (default %d)\n"
        "  --verbose              Pass VERBOSE=1 to underlying build\n"
        "  -h, --help             Show this help text\n",
        argv0, DEFAULT_PARALLELISM);
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                              Signal Handler                               */
/* ────────────────────────────────────────────────────────────────────────── */

static void on_signal(int sig)
{
    (void)sig;
    g_cancel_requested = 1;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                           Worker Thread Logic                             */
/* ────────────────────────────────────────────────────────────────────────── */

typedef struct {
    build_ctx_t *ctx;
    size_t       index; /* 0-based index into ctx->services */
} worker_arg_t;

static void *builder_thread(void *arg_void)
{
    worker_arg_t *arg = arg_void;
    build_ctx_t  *ctx = arg->ctx;
    service_t    *svc = &ctx->services[arg->index];

    if (!svc->needs_build) {
        /* No work */
        svc->result = 0;
        return NULL;
    }

    char cmdline[PATH_MAX + 64];
    /* Example build command: make -C /abs/path VERBOSE=1 */
    snprintf(cmdline, sizeof cmdline,
             "%s -C \"%s\" %s%s",
             ctx->build_cmd,
             svc->dir,
             ctx->verbose ? "VERBOSE=1 " : "",
             "all");

    info("%s ‑ %s", timestamp(), cmdline);

    int rc = system(cmdline);
    if (rc == -1) {
        err("%s ‑ failed to spawn: %s", timestamp(), strerror(errno));
        svc->result = 127;
    } else {
        svc->result = WEXITSTATUS(rc);
        if (svc->result == 0)
            success("%s ‑ built successfully", timestamp());
        else
            err("%s ‑ build failed with %d", timestamp(), svc->result);
    }

    return NULL;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                           High-Level Build API                            */
/* ────────────────────────────────────────────────────────────────────────── */

static void schedule_builds(build_ctx_t *ctx)
{
    /* Simple static thread pool (one per service or limited by parallelism) */
    size_t workers = ctx->count < (size_t)ctx->parallelism ? ctx->count
                                                           : (size_t)ctx->parallelism;
    pthread_t *threads = calloc(workers, sizeof *threads);

    size_t next_job = 0;
    size_t active   = 0;

    while (next_job < ctx->count || active) {
        /* Spawn new threads while we have capacity */
        while (active < workers && next_job < ctx->count) {
            worker_arg_t *arg = calloc(1, sizeof *arg);
            arg->ctx   = ctx;
            arg->index = next_job++;

            if (pthread_create(&threads[active], NULL, builder_thread, arg) != 0) {
                err("pthread_create failed: %s", strerror(errno));
                free(arg);
                continue;
            }
            active++;
        }

        /* Wait for any thread to finish */
        for (size_t i = 0; i < active; ++i) {
            if (threads[i] && pthread_tryjoin_np /* GNU extension */) ; /* NOOP */
        }

        /* Collapse finished thread slots */
        size_t write = 0;
        for (size_t read = 0; read < active; ++read) {
            if (threads[read] == 0) /* vacant */
                continue;
            if (pthread_tryjoin_np(threads[read], NULL) == 0) {
                threads[read] = 0;
            } else {
                threads[write++] = threads[read];
            }
        }
        active = write;

        if (g_cancel_requested) {
            warn("Cancelling remaining builds due to signal");
            break;
        }

        /* Small sleep to avoid busy loop */
        struct timespec ts = {.tv_sec = 0, .tv_nsec = 100000000}; /* 100ms */
        nanosleep(&ts, NULL);
    }

    free(threads);
}

/* Returns non-zero if any service’s *.c sources are newer than “build/.stamp” */
static bool service_needs_rebuild(const char *service_dir)
{
    char stamp[PATH_MAX];
    join_path(stamp, sizeof stamp, service_dir, "build/.stamp");

    time_t stamp_time = mtime_of(stamp);
    if (stamp_time == 0)
        return true; /* never built */

    /* Naïve heuristic: if any *.c changed, rebuild */
    char src_glob[PATH_MAX];
    join_path(src_glob, sizeof src_glob, service_dir, "src");

    /* For portability, walk using “find” + “stat” instead of <fts.h> */
    char find_cmd[PATH_MAX + 64];
    snprintf(find_cmd, sizeof find_cmd,
             "find \"%s\" -name '*.c' -newer \"%s\" -print -quit 2>/dev/null",
             src_glob, stamp);

    int rc = system(find_cmd);
    return rc == 0; /* return 0 if match found ⇒ needs rebuild */
}

/* ────────────────────────────────────────────────────────────────────────── */
/*                                   Main                                    */
/* ────────────────────────────────────────────────────────────────────────── */

int main(int argc, char **argv)
{
    /* ------------------------------------------------------------ */
    /* 1. Register signal handlers                                  */
    struct sigaction sa = {.sa_handler = on_signal};
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    /* ------------------------------------------------------------ */
    /* 2. Default config                                            */
    build_ctx_t ctx = {
        .parallelism = DEFAULT_PARALLELISM,
        .verbose     = false,
        .build_cmd   = "make"
    };

    /* ------------------------------------------------------------ */
    /* 3. CLI parse                                                 */
    bool all_flag    = true;
    char single_service[PATH_MAX] = {0};
    bool clean_flag  = false;

    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--all")) {
            all_flag = true;
        } else if (!strcmp(argv[i], "--service") && i + 1 < argc) {
            strncpy(single_service, argv[++i], sizeof single_service - 1);
            all_flag = false;
        } else if (!strcmp(argv[i], "--clean")) {
            clean_flag = true;
        } else if ((!strcmp(argv[i], "-j") || !strcmp(argv[i], "--jobs")) && i + 1 < argc) {
            ctx.parallelism = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--verbose")) {
            ctx.verbose = true;
        } else if (!strcmp(argv[i], "-h") || !strcmp(argv[i], "--help")) {
            print_usage(argv[0]);
            return EXIT_SUCCESS;
        } else {
            err("Unknown option: %s", argv[i]);
            print_usage(argv[0]);
            return EXIT_FAILURE;
        }
    }

    /* ------------------------------------------------------------ */
    /* 4. Find repository root                                      */
    char repo_root[PATH_MAX];
    if (!find_repo_root(repo_root, sizeof repo_root)) {
        err("Unable to locate repository root – are you inside SynestheticCanvas?");
        return EXIT_FAILURE;
    }
    info("Repository root detected at %s", repo_root);
    if (chdir(repo_root) != 0) {
        err("chdir to repo root failed: %s", strerror(errno));
        return EXIT_FAILURE;
    }

    /* ------------------------------------------------------------ */
    /* 5. Enumerate services                                        */
    size_t svc_count = 0;
    for (const char **p = DEFAULT_SERVICES; *p; ++p)
        svc_count++;

    ctx.services = calloc(svc_count, sizeof *ctx.services);
    ctx.count    = svc_count;

    for (size_t i = 0; i < svc_count; ++i) {
        join_path(ctx.services[i].dir, sizeof ctx.services[i].dir,
                  repo_root, DEFAULT_SERVICES[i]);
        if (!all_flag) {
            char *leaf = strrchr(ctx.services[i].dir, '/');
            if (leaf && strcmp(leaf + 1, single_service) != 0) {
                ctx.services[i].needs_build = false;
                continue;
            }
        }

        /* Clean if requested */
        if (clean_flag) {
            char clean_cmd[PATH_MAX + 32];
            snprintf(clean_cmd, sizeof clean_cmd,
                     "%s -C \"%s\" clean", ctx.build_cmd, ctx.services[i].dir);
            info("Cleaning %s", ctx.services[i].dir);
            system(clean_cmd);
        }

        ctx.services[i].needs_build = service_needs_rebuild(ctx.services[i].dir);
    }

    /* ------------------------------------------------------------ */
    /* 6. Execute builds                                            */
    schedule_builds(&ctx);

    /* ------------------------------------------------------------ */
    /* 7. Summarise results                                         */
    int exit_code = 0;
    for (size_t i = 0; i < ctx.count; ++i) {
        const service_t *svc = &ctx.services[i];
        if (!svc->needs_build)
            continue;

        if (svc->result == 0) {
            success("%s ‑ %s built OK", timestamp(), svc->dir);
        } else {
            err("%s ‑ %s failed", timestamp(), svc->dir);
            exit_code = 1;
        }
    }

    if (g_cancel_requested)
        exit_code = 130; /* typical exit code for SIGINT */

    free(ctx.services);
    return exit_code;
}
```