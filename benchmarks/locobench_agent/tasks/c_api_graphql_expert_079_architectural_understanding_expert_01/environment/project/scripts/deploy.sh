```c
/**
 * SynestheticCanvas API Suite – Deployment Orchestrator
 *
 * File:    scripts/deploy.c            (compiled and invoked by deploy.sh)
 * Purpose: Declarative, version-aware deployment tool written in C.
 *           • Reads a tiny YAML/INI-like manifest that lists individual
 *             microservices (aka “brush strokes”) with Docker metadata.
 *           • Builds, tags, pushes, and (optionally) rolls out containers
 *             in the correct order, injecting version labels and
 *             Git commit hashes for traceability.
 *           • Emits structured JSON logs that can be picked up by the
 *             platform’s centralized ELK/Grafana pipeline.
 *
 * Compile: cc -std=c18 -O2 -Wall -Wextra -pedantic -o deploy scripts/deploy.c
 *
 * Example manifest (deploy.yaml):
 *   ---
 *   workspace: synestheticcanvas
 *   registry:  ghcr.io
 *   namespace: digital-arts
 *
 *   services:
 *     - name: palette-mgr
 *       path: ../palette_service
 *       tag:  v2.1.0
 *       port: 7001
 *     - name: texture-synth
 *       path: ../texture_service
 *       tag:  v1.3.7
 *       port: 7002
 *
 * Usage:
 *   ./deploy --file deploy.yaml --rollout
 *
 * Notes:
 *   This utility purposefully avoids heavy YAML dependencies to keep the
 *   deployment image lightweight.  A thin, hand-rolled parser that recognises
 *   only the required subset of YAML is employed instead.
 */

#define _POSIX_C_SOURCE 200809L   /* getline, strdup */
#include <errno.h>
#include <json-c/json.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* --------------------------------------------------------------------------
 * Global compile-time tunables
 * -------------------------------------------------------------------------- */
#define MAX_SERVICES        64
#define MAX_STR             256
#define LOG_PATH_DEFAULT    "deploy.log"
#define TIMEBUF_LEN         32

/* --------------------------------------------------------------------------
 * Data structures
 * -------------------------------------------------------------------------- */
typedef struct {
    char     name[MAX_STR];
    char     path[MAX_STR];
    char     tag[MAX_STR];
    int      port;
} service_t;

typedef struct {
    char     workspace[MAX_STR];
    char     registry[MAX_STR];
    char     namespace[MAX_STR];
    service_t services[MAX_SERVICES];
    size_t   service_count;
} config_t;

/* --------------------------------------------------------------------------
 * Logging helpers – JSON formatted for machine parsing
 * -------------------------------------------------------------------------- */
static FILE *log_file = NULL;

static void log_open(const char *file_path)
{
    log_file = fopen(file_path, "a");
    if (!log_file) {
        fprintf(stderr, "fatal: could not open log file (%s): %s\n",
                file_path, strerror(errno));
        exit(EXIT_FAILURE);
    }
}

__attribute__((format(printf, 2, 3)))
static void log_json(const char *level, const char *fmt, ...)
{
    time_t  now = time(NULL);
    char    tbuf[TIMEBUF_LEN] = {0};
    strftime(tbuf, sizeof tbuf, "%FT%TZ", gmtime(&now));

    json_object *root = json_object_new_object();
    json_object_object_add(root, "time",  json_object_new_string(tbuf));
    json_object_object_add(root, "level", json_object_new_string(level));

    char msgbuf[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msgbuf, sizeof msgbuf, fmt, ap);
    va_end(ap);

    json_object_object_add(root, "msg", json_object_new_string(msgbuf));

    const char *json_str = json_object_to_json_string(root);
    fprintf(log_file ? log_file : stderr, "%s\n", json_str);
    fflush(log_file ? log_file : stderr);
    json_object_put(root);
}

#define LOG_INFO(...)  log_json("info",  __VA_ARGS__)
#define LOG_WARN(...)  log_json("warn",  __VA_ARGS__)
#define LOG_ERR(...)   log_json("error", __VA_ARGS__)

/* --------------------------------------------------------------------------
 * Utility helpers
 * -------------------------------------------------------------------------- */
static char *trim(char *s)
{
    while (*s == ' ' || *s == '\t') ++s;
    char *end = s + strlen(s);
    while (end > s && (end[-1] == '\n' || end[-1] == '\r' ||
                       end[-1] == ' '  || end[-1] == '\t'))
        --end;
    *end = '\0';
    return s;
}

static bool starts_with(const char *s, const char *prefix)
{
    return strncmp(s, prefix, strlen(prefix)) == 0;
}

/* --------------------------------------------------------------------------
 * Process exec wrapper
 * -------------------------------------------------------------------------- */
static int run_command(const char *cmd, bool dry_run)
{
    LOG_INFO("%s command: %s", dry_run ? "dry-run" : "executing", cmd);

    if (dry_run)
        return 0;

    int status = system(cmd);
    if (status == -1) {
        LOG_ERR("system() failed (%s)", strerror(errno));
        return -1;
    }
    if (WIFEXITED(status) && WEXITSTATUS(status) == 0)
        return 0;

    LOG_ERR("command failed with status %d", status);
    return -1;
}

/* --------------------------------------------------------------------------
 * Minimal YAML-ish parser (very limited, expects deterministic format)
 * -------------------------------------------------------------------------- */
static void parse_config_line(config_t *cfg, const char *key, const char *val,
                              service_t *current, bool *in_services)
{
    if (starts_with(key, "workspace")) {
        strncpy(cfg->workspace, val, MAX_STR - 1);
    } else if (starts_with(key, "registry")) {
        strncpy(cfg->registry, val, MAX_STR - 1);
    } else if (starts_with(key, "namespace")) {
        strncpy(cfg->namespace, val, MAX_STR - 1);
    } else if (starts_with(key, "- name")) {
        *in_services = true;
        if (cfg->service_count >= MAX_SERVICES) {
            LOG_ERR("too many services in manifest (max %d)", MAX_SERVICES);
            exit(EXIT_FAILURE);
        }
        current = &cfg->services[cfg->service_count++];
        strncpy(current->name, val, MAX_STR - 1);
    } else if (*in_services && current) {
        if (starts_with(key, "path"))
            strncpy(current->path, val, MAX_STR - 1);
        else if (starts_with(key, "tag"))
            strncpy(current->tag, val, MAX_STR - 1);
        else if (starts_with(key, "port"))
            current->port = atoi(val);
    }
}

static void read_config(const char *file_path, config_t *cfg)
{
    memset(cfg, 0, sizeof *cfg);
    FILE *fp = fopen(file_path, "r");
    if (!fp) {
        LOG_ERR("cannot open manifest '%s': %s", file_path, strerror(errno));
        exit(EXIT_FAILURE);
    }

    char *line = NULL;
    size_t len = 0;
    ssize_t nread;
    bool in_services = false;
    service_t *current = NULL;

    while ((nread = getline(&line, &len, fp)) != -1) {
        char *str = trim(line);
        if (str[0] == '#' || str[0] == '\0') continue;

        /* rudimentary split on ':' or ' ' */
        char *sep = strchr(str, ':');
        if (!sep) sep = strchr(str, ' ');
        if (!sep) continue;

        *sep = '\0';
        char *val = trim(sep + 1);

        parse_config_line(cfg, trim(str), trim(val), current, &in_services);

        /* update current pointer after a new service is recognised */
        if (in_services && cfg->service_count > 0)
            current = &cfg->services[cfg->service_count - 1];
    }

    free(line);
    fclose(fp);

    if (cfg->service_count == 0) {
        LOG_WARN("no services found in manifest – nothing to do");
    }
}

/* --------------------------------------------------------------------------
 * Deployment steps
 * -------------------------------------------------------------------------- */
static void build_and_push(const config_t *cfg,
                           const service_t *svc,
                           const char *git_sha,
                           bool dry_run)
{
    char image_full[MAX_STR * 2];
    snprintf(image_full, sizeof image_full, "%s/%s/%s:%s-%s",
             cfg->registry,
             cfg->namespace,
             svc->name,
             svc->tag,
             git_sha);

    char cmd[1024];

    /* Build */
    snprintf(cmd, sizeof cmd,
             "docker build -t %s %s",
             image_full, svc->path);
    if (run_command(cmd, dry_run) != 0) {
        LOG_ERR("build failed for %s", svc->name);
        exit(EXIT_FAILURE);
    }

    /* Push */
    snprintf(cmd, sizeof cmd,
             "docker push %s", image_full);
    if (run_command(cmd, dry_run) != 0) {
        LOG_ERR("push failed for %s", svc->name);
        exit(EXIT_FAILURE);
    }

    LOG_INFO("successfully built & pushed %s", image_full);
}

static void rollout(const config_t *cfg,
                    const service_t *svc,
                    const char *git_sha,
                    bool dry_run)
{
    char image_full[MAX_STR * 2];
    snprintf(image_full, sizeof image_full, "%s/%s/%s:%s-%s",
             cfg->registry, cfg->namespace, svc->name, svc->tag, git_sha);

    char cmd[1024];
    snprintf(cmd, sizeof cmd,
             "kubectl set image deployment/%s %s=%s --record",
             svc->name, svc->name, image_full);

    if (run_command(cmd, dry_run) != 0) {
        LOG_ERR("rollout failed for %s", svc->name);
        exit(EXIT_FAILURE);
    }

    LOG_INFO("rollout triggered for %s", svc->name);
}

/* --------------------------------------------------------------------------
 * Entry point
 * -------------------------------------------------------------------------- */
static void usage(const char *prog)
{
    fprintf(stderr,
        "Usage: %s --file <manifest> [--dry-run] [--rollout] "
        "[--log <file>]\n", prog);
}

int main(int argc, char *argv[])
{
    const char *manifest = NULL;
    bool dry_run  = false;
    bool do_roll  = false;
    const char *logpath = LOG_PATH_DEFAULT;

    /* --- Cli parsing ----------------------------------------------------- */
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--file") && i + 1 < argc)
            manifest = argv[++i];
        else if (!strcmp(argv[i], "--dry-run"))
            dry_run = true;
        else if (!strcmp(argv[i], "--rollout"))
            do_roll = true;
        else if (!strcmp(argv[i], "--log") && i + 1 < argc)
            logpath = argv[++i];
        else {
            usage(argv[0]);
            return EXIT_FAILURE;
        }
    }

    if (!manifest) {
        usage(argv[0]);
        return EXIT_FAILURE;
    }

    log_open(logpath);
    LOG_INFO("starting deployment (dry-run=%s, rollout=%s)",
             dry_run ? "true" : "false",
             do_roll ? "true" : "false");

    /* --- Git describe ---------------------------------------------------- */
    char git_buf[64] = "unknown";
    FILE *gp = popen("git rev-parse --short HEAD 2>/dev/null", "r");
    if (gp) {
        if (fgets(git_buf, sizeof git_buf, gp)) {
            git_buf[strcspn(git_buf, "\n")] = '\0';
        }
        pclose(gp);
    }

    /* --- Parse manifest -------------------------------------------------- */
    config_t cfg;
    read_config(manifest, &cfg);

    /* --- Iterate services ------------------------------------------------ */
    for (size_t i = 0; i < cfg.service_count; ++i) {
        service_t *svc = &cfg.services[i];

        LOG_INFO("processing service %zu/%zu – %s",
                 i + 1, cfg.service_count, svc->name);

        build_and_push(&cfg, svc, git_buf, dry_run);

        if (do_roll)
            rollout(&cfg, svc, git_buf, dry_run);
    }

    LOG_INFO("deployment finished successfully");
    fclose(log_file);
    return EXIT_SUCCESS;
}
```