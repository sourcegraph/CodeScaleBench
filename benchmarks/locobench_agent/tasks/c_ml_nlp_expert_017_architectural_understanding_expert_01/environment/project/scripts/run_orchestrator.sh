```c
/*------------------------------------------------------------------------------
 * File:    lexilearn_orchestrator/scripts/run_orchestrator.sh
 * Project: LexiLearn MVC Orchestrator (ml_nlp)
 *
 * NOTE:  Despite the “.sh” extension mandated by legacy build tooling,
 *        this is a fully-featured, production-quality C program that serves as
 *        the main command-line entry-point for the LexiLearn Orchestrator.
 *
 * Compile: cc -O2 -Wall -Wextra -pedantic -std=c11 -lyaml -lpthread \
 *          -o run_orchestrator run_orchestrator.sh
 *----------------------------------------------------------------------------*/

#define  _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <signal.h>
#include <spawn.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <yaml.h>

/*----------------------------------------------------------------------------*/
/*                                Definitions                                 */
/*----------------------------------------------------------------------------*/

#define LEO_VERSION          "2.4.1"
#define DEFAULT_CFG_PATH     "/etc/lexilearn/lexilearn.yaml"
#define MAX_CMD_ARGS         16
#define TS_BUF_SZ            64
#define LOG_BUF_SZ           1024

typedef enum {
    TASK_NONE = 0,
    TASK_INGEST,
    TASK_TRAIN,
    TASK_EVAL,
    TASK_MONITOR,
    TASK_RETRAIN
} task_t;

typedef enum {
    LVL_DEBUG,
    LVL_INFO,
    LVL_WARN,
    LVL_ERROR
} log_level_t;

static const char *lvl_to_str[] = { "DEBUG", "INFO", "WARN", "ERROR" };

typedef struct {
    char cfg_path[PATH_MAX];
    char feature_store[PATH_MAX];
    char registry_uri[PATH_MAX];
    char python_bin[PATH_MAX];
    int  log_verbosity;      /* 0:ERROR … 3:DEBUG */
    int  retrain_threshold;  /* drift %      */
    int  max_parallel_jobs;
} orchestrator_cfg_t;

/*----------------------------------------------------------------------------*/
/*                            Forward Declarations                             */
/*----------------------------------------------------------------------------*/

static void        print_usage(FILE *out);
static void        log_msg(log_level_t lvl, const char *fmt, ...) __attribute__((format(printf,2,3)));
static void        die(const char *fmt, ...) __attribute__((noreturn,format(printf,1,2)));
static void        install_sig_handlers(void);
static void        sig_handler(int signo);
static void        load_config(const char *path, orchestrator_cfg_t *cfg);
static void        spawn_task(task_t task, const orchestrator_cfg_t *cfg);
static const char *task_to_str(task_t t);
static task_t      parse_task(const char *optarg);

/*----------------------------------------------------------------------------*/
/*                              Global State                                  */
/*----------------------------------------------------------------------------*/

static volatile sig_atomic_t g_shutdown = 0;

/*----------------------------------------------------------------------------*/
/*                                  Utils                                     */
/*----------------------------------------------------------------------------*/

static void get_ts(char *buf, size_t sz)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    struct tm tm;
    localtime_r(&ts.tv_sec, &tm);
    strftime(buf, sz, "%Y-%m-%d %H:%M:%S", &tm);
}

static void log_msg(log_level_t lvl, const char *fmt, ...)
{
    static int cur_verbosity = LVL_INFO;

    if (lvl < cur_verbosity) return;

    char ts[TS_BUF_SZ];
    get_ts(ts, sizeof ts);

    char msg[LOG_BUF_SZ];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msg, sizeof msg, fmt, ap);
    va_end(ap);

    FILE *stream = (lvl >= LVL_WARN) ? stderr : stdout;
    fprintf(stream, "[%s] %-5s %s\n", ts, lvl_to_str[lvl], msg);
}

static void die(const char *fmt, ...)
{
    char buf[LOG_BUF_SZ];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);

    log_msg(LVL_ERROR, "%s", buf);
    exit(EXIT_FAILURE);
}

/*----------------------------------------------------------------------------*/
/*                               Signal Handling                              */
/*----------------------------------------------------------------------------*/

static void sig_handler(int signo)
{
    if (signo == SIGINT || signo == SIGTERM) {
        g_shutdown = 1;
    }
}

static void install_sig_handlers(void)
{
    struct sigaction sa = { .sa_handler = sig_handler };
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    if (sigaction(SIGINT,  &sa, NULL) == -1 ||
        sigaction(SIGTERM, &sa, NULL) == -1) {
        die("sigaction failed: %s", strerror(errno));
    }
}

/*----------------------------------------------------------------------------*/
/*                                  Config                                    */
/*----------------------------------------------------------------------------*/

static void cfg_set_defaults(orchestrator_cfg_t *cfg)
{
    memset(cfg, 0, sizeof *cfg);
    strncpy(cfg->cfg_path, DEFAULT_CFG_PATH, sizeof cfg->cfg_path);
    strncpy(cfg->feature_store, "/var/lib/lexilearn/features", sizeof cfg->feature_store);
    strncpy(cfg->registry_uri, "http://localhost:5000", sizeof cfg->registry_uri);
    strncpy(cfg->python_bin, "/usr/bin/python3", sizeof cfg->python_bin);
    cfg->log_verbosity     = LVL_INFO;
    cfg->retrain_threshold = 7;  /* default 7% drift */
    cfg->max_parallel_jobs = 2;
}

static void load_config(const char *path, orchestrator_cfg_t *cfg)
{
    cfg_set_defaults(cfg);

    FILE *fh = fopen(path, "r");
    if (!fh) {
        log_msg(LVL_WARN, "Could not open config (%s): %s – using defaults", path, strerror(errno));
        return;
    }

    yaml_parser_t parser;
    yaml_event_t  event;
    if (!yaml_parser_initialize(&parser))
        die("Failed to initialize YAML parser");

    yaml_parser_set_input_file(&parser, fh);

    char key[128] = {0};
    bool in_key   = true;

    while (1) {
        if (!yaml_parser_parse(&parser, &event))
            die("YAML parse error: %s", parser.problem);

        switch (event.type) {
        case YAML_SCALAR_EVENT:
            if (in_key) {
                strncpy(key, (char *)event.data.scalar.value, sizeof key - 1);
                in_key = false;
            } else {
                const char *val = (char *)event.data.scalar.value;

                if (strcmp(key, "feature_store") == 0)
                    strncpy(cfg->feature_store, val, sizeof cfg->feature_store);
                else if (strcmp(key, "registry_uri") == 0)
                    strncpy(cfg->registry_uri, val, sizeof cfg->registry_uri);
                else if (strcmp(key, "python_bin") == 0)
                    strncpy(cfg->python_bin, val, sizeof cfg->python_bin);
                else if (strcmp(key, "log_verbosity") == 0)
                    cfg->log_verbosity = atoi(val);
                else if (strcmp(key, "retrain_threshold") == 0)
                    cfg->retrain_threshold = atoi(val);
                else if (strcmp(key, "max_parallel_jobs") == 0)
                    cfg->max_parallel_jobs = atoi(val);

                in_key = true;
            }
            break;
        case YAML_STREAM_END_EVENT:
            yaml_event_delete(&event);
            goto done;
        default:
            break;
        }

        yaml_event_delete(&event);
    }

done:
    yaml_parser_delete(&parser);
    fclose(fh);
}

/*----------------------------------------------------------------------------*/
/*                               Task Helpers                                 */
/*----------------------------------------------------------------------------*/

static const char *task_to_str(task_t t)
{
    switch (t) {
    case TASK_INGEST:  return "ingest";
    case TASK_TRAIN:   return "train";
    case TASK_EVAL:    return "evaluate";
    case TASK_MONITOR: return "monitor";
    case TASK_RETRAIN: return "retrain";
    default:           return "unknown";
    }
}

static task_t parse_task(const char *s)
{
    if (strcmp(s, "ingest") == 0)   return TASK_INGEST;
    if (strcmp(s, "train") == 0)    return TASK_TRAIN;
    if (strcmp(s, "evaluate") == 0) return TASK_EVAL;
    if (strcmp(s, "monitor") == 0)  return TASK_MONITOR;
    if (strcmp(s, "retrain") == 0)  return TASK_RETRAIN;
    return TASK_NONE;
}

static void spawn_task(task_t task, const orchestrator_cfg_t *cfg)
{
    const char *subcmd    = task_to_str(task);
    char script_path[PATH_MAX];

    snprintf(script_path, sizeof script_path, "/usr/local/lib/lexilearn/%s.py", subcmd);

    char *argv[MAX_CMD_ARGS] = {
        (char *)cfg->python_bin,
        script_path,
        "--feature-store", (char *)cfg->feature_store,
        "--registry-uri",  (char *)cfg->registry_uri,
        NULL
    };

    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);

    /* Redirect child stdout/stderr to dedicated logs */
    char log_file[PATH_MAX];
    snprintf(log_file, sizeof log_file, "/var/log/lexilearn/%s.log", subcmd);
    int fd = open(log_file, O_CREAT | O_WRONLY | O_APPEND, 0644);
    if (fd != -1) {
        posix_spawn_file_actions_adddup2(&actions, fd, STDOUT_FILENO);
        posix_spawn_file_actions_adddup2(&actions, fd, STDERR_FILENO);
        posix_spawn_file_actions_addclose(&actions, fd);
    }

    pid_t pid;
    int   rc = posix_spawnp(&pid, cfg->python_bin, &actions, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&actions);

    if (rc != 0) {
        log_msg(LVL_ERROR, "Failed to spawn %s (%s): %s", subcmd, script_path, strerror(rc));
        return;
    }

    log_msg(LVL_INFO, "Started %s (PID=%d)", subcmd, pid);

    /* Wait synchronously; could be made asynchronous for parallel exec */
    int status;
    if (waitpid(pid, &status, 0) == -1)
        log_msg(LVL_ERROR, "waitpid failed for %s: %s", subcmd, strerror(errno));
    else if (WIFEXITED(status) && WEXITSTATUS(status) != 0)
        log_msg(LVL_WARN, "%s exited with status %d", subcmd, WEXITSTATUS(status));
    else if (WIFSIGNALED(status))
        log_msg(LVL_WARN, "%s killed by signal %d", subcmd, WTERMSIG(status));
    else
        log_msg(LVL_INFO, "%s finished successfully", subcmd);
}

/*----------------------------------------------------------------------------*/
/*                                 CLI                                        */
/*----------------------------------------------------------------------------*/

static void print_version(void)
{
    printf("LexiLearn Orchestrator %s\n", LEO_VERSION);
}

static void print_usage(FILE *out)
{
    fprintf(out,
        "Usage: run_orchestrator [OPTIONS] TASK\n"
        "TASKS:\n"
        "  ingest      Ingest data from LMS APIs\n"
        "  train       Train model with latest data\n"
        "  evaluate    Evaluate model & generate metrics\n"
        "  monitor     Run model-drift monitoring job\n"
        "  retrain     Trigger automated retraining cycle\n\n"
        "OPTIONS:\n"
        "  -c, --config PATH     Override default config path (%s)\n"
        "  -v, --verbose LEVEL   Log verbosity 0-3 (ERROR-DEBUG)\n"
        "  -h, --help            Display this help and exit\n"
        "  -V, --version         Print version and exit\n",
        DEFAULT_CFG_PATH);
}

/*----------------------------------------------------------------------------*/
/*                                   main                                     */
/*----------------------------------------------------------------------------*/

int main(int argc, char *argv[])
{
    orchestrator_cfg_t cfg;
    char cfg_path[PATH_MAX] = DEFAULT_CFG_PATH;

    static struct option long_opts[] = {
        { "config",  required_argument, 0, 'c' },
        { "verbose", required_argument, 0, 'v' },
        { "help",    no_argument,       0, 'h' },
        { "version", no_argument,       0, 'V' },
        { 0, 0, 0, 0 }
    };

    int opt, idx;
    while ((opt = getopt_long(argc, argv, "c:v:hV", long_opts, &idx)) != -1) {
        switch (opt) {
        case 'c':
            strncpy(cfg_path, optarg, sizeof cfg_path);
            break;
        case 'v':
            cfg.log_verbosity = atoi(optarg);
            break;
        case 'h':
            print_usage(stdout);
            return EXIT_SUCCESS;
        case 'V':
            print_version();
            return EXIT_SUCCESS;
        default:
            print_usage(stderr);
            return EXIT_FAILURE;
        }
    }

    /* Remaining arg must be task */
    if (optind >= argc) {
        print_usage(stderr);
        return EXIT_FAILURE;
    }

    task_t task = parse_task(argv[optind]);
    if (task == TASK_NONE) {
        fprintf(stderr, "Unknown task: %s\n", argv[optind]);
        print_usage(stderr);
        return EXIT_FAILURE;
    }

    /* Setup */
    load_config(cfg_path, &cfg);
    install_sig_handlers();

    log_msg(LVL_INFO, "LexiLearn Orchestrator started (task=%s)", task_to_str(task));
    spawn_task(task, &cfg);

    /* Graceful shutdown handling */
    if (g_shutdown)
        log_msg(LVL_INFO, "Received termination signal, shutting down…");

    log_msg(LVL_INFO, "Done.");
    return EXIT_SUCCESS;
}
```