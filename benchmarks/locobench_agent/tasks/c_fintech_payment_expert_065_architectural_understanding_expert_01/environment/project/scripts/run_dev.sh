```c
/*─────────────────────────────────────────────────────────────────────────────
 * File:    EduPayLedgerAcademy/scripts/run_dev.sh      (yes, it’s really C 😉)
 * Project: EduPay Ledger Academy – Fin-Tech Payment Platform for Higher-Ed
 *
 * Purpose:
 *   Developer command-line utility that bootstraps a local development
 *   environment.  Although stored in the scripts/ folder with a .sh suffix
 *   (to match legacy build pipelines), this is a full-blown C binary. It
 *   orchestrates micro-services, exports .env variables, tails logs, and
 *   performs health checks for classroom demonstrations of Clean Architecture
 *   payment rails.
 *
 * Build:
 *   $ cc -Wall -Wextra -pedantic -std=c17 -o run_dev scripts/run_dev.sh
 *
 * Usage:
 *   ./run_dev --start [--services admissions,bursar]
 *   ./run_dev --stop  [--services admissions]
 *   ./run_dev --status
 *   ./run_dev --logs  --service bursar
 *
 * Dependencies:
 *   POSIX.1-2008. Tested on Linux and macOS.  Requires Docker if services are
 *   containerised.  No third-party libraries needed.
 *
 * Author:
 *   EduPay Ledger Academy – © 2024.  MIT License.
 *────────────────────────────────────────────────────────────────────────────*/

#define _POSIX_C_SOURCE 200809L   /* getline, kill(2), sigaction…            */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/*─────────────────────────────── Constants ────────────────────────────────*/

#define MAX_SERVICES        16
#define MAX_NAME_LEN        64
#define RUNTIME_DIR         ".edupay_dev"
#define PID_DIR             ".edupay_dev/pids"
#define LOG_DIR             ".edupay_dev/logs"
#define ENV_FILE_NAME       ".env.dev"
#define LOG_BUF_SZ          4096

static const char *DEFAULT_SERVICES[] = {
    "gateway", "admissions", "bursar", "financial_aid",
    "continuing_education", NULL
};

typedef enum {
    CMD_NONE,
    CMD_START,
    CMD_STOP,
    CMD_STATUS,
    CMD_LOGS
} command_t;

/*─────────────────────────────── Structures ───────────────────────────────*/

typedef struct {
    char  name[MAX_NAME_LEN];
    pid_t pid;
} service_t;

/*────────────────────────── Utility Prototypes ────────────────────────────*/
static void die(const char *fmt, ...)     __attribute__((format(printf, 1, 2)));
static void log_info(const char *fmt, ...)__attribute__((format(printf, 1, 2)));
static void ensure_dirs(void);
static char *runtime_path(const char *dir, const char *name, char *buf,
                          size_t len);
static bool file_exists(const char *path);
static pid_t read_pid(const char *service);
static void  write_pid(const char *service, pid_t pid);
static void  remove_pidfile(const char *service);
static int   load_env(const char *path);
static int   parse_services(const char *csv, service_t list[], size_t *count);
static int   default_services(service_t list[], size_t *count);

/*──────────────────────── Service Management ──────────────────────────────*/
static int start_services(service_t list[], size_t count);
static int stop_services(service_t list[], size_t count);
static int status_services(service_t list[], size_t count);
static int tail_logs(const char *service);

/*──────────────────────────────── Helpers ─────────────────────────────────*/

static void die(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "\033[31m[ERROR]\033[0m ");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
    exit(EXIT_FAILURE);
}

static void log_info(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fprintf(stdout, "\033[32m[INFO]\033[0m ");
    vfprintf(stdout, fmt, ap);
    fprintf(stdout, "\n");
    va_end(ap);
}

static void ensure_dirs(void)
{
    const char *home = getenv("HOME");
    if (!home) die("Could not locate HOME directory");

    char path[PATH_MAX];

    /* ~/.edupay_dev             */
    runtime_path(NULL, NULL, path, sizeof(path));
    mkdir(path, 0700);

    /* ~/.edupay_dev/pids        */
    runtime_path("pids", NULL, path, sizeof(path));
    mkdir(path, 0700);

    /* ~/.edupay_dev/logs        */
    runtime_path("logs", NULL, path, sizeof(path));
    mkdir(path, 0700);
}

static char *runtime_path(const char *dir, const char *name,
                          char *buf, size_t len)
{
    const char *home = getenv("HOME");
    if (!home) die("HOME env not set");

    if (dir && name)
        snprintf(buf, len, "%s/%s/%s/%s", home, RUNTIME_DIR, dir, name);
    else if (dir)
        snprintf(buf, len, "%s/%s/%s", home, RUNTIME_DIR, dir);
    else if (name)
        snprintf(buf, len, "%s/%s/%s", home, RUNTIME_DIR, name);
    else
        snprintf(buf, len, "%s/%s", home, RUNTIME_DIR);

    return buf;
}

static bool file_exists(const char *path)
{
    struct stat st;
    return stat(path, &st) == 0;
}

/*────────────────────────── PID-file helpers ──────────────────────────────*/

static pid_t read_pid(const char *service)
{
    char path[PATH_MAX];
    runtime_path("pids", service, path, sizeof(path));

    FILE *fp = fopen(path, "r");
    if (!fp) return -1;

    long pid = -1;
    if (fscanf(fp, "%ld", &pid) != 1) pid = -1;
    fclose(fp);
    return (pid_t)pid;
}

static void write_pid(const char *service, pid_t pid)
{
    char path[PATH_MAX];
    runtime_path("pids", service, path, sizeof(path));

    FILE *fp = fopen(path, "w");
    if (!fp) die("Unable to write pidfile %s: %s", path, strerror(errno));

    fprintf(fp, "%d\n", pid);
    fclose(fp);
}

static void remove_pidfile(const char *service)
{
    char path[PATH_MAX];
    runtime_path("pids", service, path, sizeof(path));
    unlink(path);
}

/*──────────────────────────── Env Loader ─────────────────────────────────*/

static int load_env(const char *path)
{
    FILE *fp = fopen(path, "r");
    if (!fp) {
        log_info("No %s found, skipping env import", path);
        return -1;
    }

    char *line = NULL;
    size_t n = 0;
    while (getline(&line, &n, fp) != -1) {
        if (line[0] == '#' || line[0] == '\n')
            continue;

        char *eq = strchr(line, '=');
        if (!eq) continue;

        *eq = '\0';
        char *key = line;
        char *val = eq + 1;

        /* Trim newline */
        char *nl = strchr(val, '\n');
        if (nl) *nl = '\0';

        setenv(key, val, 1);
    }

    free(line);
    fclose(fp);
    return 0;
}

/*────────────────── Service list parsing helpers ─────────────────────────*/

static int parse_services(const char *csv, service_t list[], size_t *count)
{
    char *temp = strdup(csv);
    if (!temp) return -1;

    size_t idx = 0;
    for (char *tok = strtok(temp, ","); tok && idx < MAX_SERVICES;
         tok = strtok(NULL, ",")) {

        strncpy(list[idx].name, tok, MAX_NAME_LEN - 1);
        list[idx].name[MAX_NAME_LEN - 1] = '\0';
        list[idx].pid = read_pid(list[idx].name);
        idx++;
    }
    *count = idx;
    free(temp);
    return 0;
}

static int default_services(service_t list[], size_t *count)
{
    size_t idx = 0;
    for (const char **p = DEFAULT_SERVICES; *p && idx < MAX_SERVICES; ++p) {
        strncpy(list[idx].name, *p, MAX_NAME_LEN - 1);
        list[idx].pid = read_pid(list[idx].name);
        idx++;
    }
    *count = idx;
    return 0;
}

/*──────────────────────────── Spawning Logic ─────────────────────────────*/

static pid_t spawn_service(const char *service, int stdout_fd)
{
    /* For demonstration, we just invoke "docker compose up <service>".
     * Real-world deployments could exec the compiled microservice binary.
     */
    pid_t pid = fork();
    if (pid < 0) return -1;

    if (pid == 0) {
        /* Child process */

        /* Redirect stdout/stderr to logfile */
        if (stdout_fd >= 0) {
            dup2(stdout_fd, STDOUT_FILENO);
            dup2(stdout_fd, STDERR_FILENO);
        }

        /* Restore default signals */
        signal(SIGINT,  SIG_DFL);
        signal(SIGTERM, SIG_DFL);

        execlp("docker", "docker", "compose", "up", "--detach", service, NULL);
        /* If exec fails: */
        perror("exec docker compose");
        _exit(EXIT_FAILURE);
    }

    return pid;
}

static int start_services(service_t list[], size_t count)
{
    for (size_t i = 0; i < count; ++i) {
        if (list[i].pid > 0 && kill(list[i].pid, 0) == 0) {
            log_info("%s already running (pid %d)", list[i].name, list[i].pid);
            continue;
        }

        /* Prepare logfile */
        char logfile[PATH_MAX];
        runtime_path("logs", list[i].name, logfile, sizeof(logfile));
        int fd = open(logfile, O_CREAT | O_WRONLY | O_APPEND, 0644);
        if (fd < 0)
            die("Cannot open log %s: %s", logfile, strerror(errno));

        pid_t pid = spawn_service(list[i].name, fd);
        if (pid < 0) die("Failed to spawn %s", list[i].name);

        write_pid(list[i].name, pid);
        log_info("Started %s (pid %d)", list[i].name, pid);
        close(fd);
    }
    return 0;
}

static int stop_services(service_t list[], size_t count)
{
    int rc = 0;
    for (size_t i = 0; i < count; ++i) {
        pid_t pid = list[i].pid;
        if (pid <= 0 || kill(pid, 0) != 0) {
            log_info("%s not running", list[i].name);
            continue;
        }

        log_info("Stopping %s (pid %d)", list[i].name, pid);
        if (kill(pid, SIGTERM) != 0) {
            die("Failed to SIGTERM %s: %s", list[i].name, strerror(errno));
        }

        /* Wait up to 10 seconds */
        time_t start = time(NULL);
        while (kill(pid, 0) == 0 && time(NULL) - start < 10) {
            usleep(200000); /* 200ms */
        }

        if (kill(pid, 0) == 0) {
            log_info("%s didn't exit, sending SIGKILL", list[i].name);
            kill(pid, SIGKILL);
        }

        remove_pidfile(list[i].name);
    }
    return rc;
}

static int status_services(service_t list[], size_t count)
{
    for (size_t i = 0; i < count; ++i) {
        pid_t pid = list[i].pid;
        if (pid > 0 && kill(pid, 0) == 0) {
            printf("\033[32m%-22s RUNNING\033[0m (pid %d)\n",
                   list[i].name, pid);
        } else {
            printf("\033[31m%-22s STOPPED\033[0m\n", list[i].name);
        }
    }
    return 0;
}

/*───────────────────────────── Log Tailing ───────────────────────────────*/

static int tail_logs(const char *service)
{
    char logfile[PATH_MAX];
    runtime_path("logs", service, logfile, sizeof(logfile));

    int fd = open(logfile, O_RDONLY);
    if (fd < 0) die("Cannot open %s: %s", logfile, strerror(errno));

    /* Seek to end */
    lseek(fd, 0, SEEK_END);

    char buf[LOG_BUF_SZ];
    while (1) {
        ssize_t n = read(fd, buf, sizeof(buf));
        if (n > 0) {
            fwrite(buf, 1, (size_t)n, stdout);
            fflush(stdout);
        } else {
            /* No data; avoid busy loop */
            usleep(200000);
        }
    }
    return 0;
}

/*───────────────────────────── Main routine ──────────────────────────────*/

static void print_usage(const char *prog)
{
    printf("Usage: %s [command] [options]\n", prog);
    printf("Commands:\n"
           "  --start               Start services\n"
           "  --stop                Stop services\n"
           "  --status              Show running status\n"
           "  --logs  --service S   Tail logs of service S\n"
           "\nOptions:\n"
           "  --services LIST       Comma-separated list of services\n"
           "  -h, --help            Show this help\n");
}

int main(int argc, char *argv[])
{
    command_t cmd = CMD_NONE;
    const char *services_csv = NULL;
    const char *log_service   = NULL;

    /* Very light getopt_long replacement to keep dependencies low */
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--start") == 0)       cmd = CMD_START;
        else if (strcmp(argv[i], "--stop") == 0)   cmd = CMD_STOP;
        else if (strcmp(argv[i], "--status") == 0) cmd = CMD_STATUS;
        else if (strcmp(argv[i], "--logs") == 0)   cmd = CMD_LOGS;
        else if (strcmp(argv[i], "--services") == 0 && i + 1 < argc)
            services_csv = argv[++i];
        else if (strcmp(argv[i], "--service") == 0 && i + 1 < argc)
            log_service = argv[++i];
        else if (strcmp(argv[i], "-h") == 0 ||
                 strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            return EXIT_SUCCESS;
        } else {
            die("Unknown argument: %s", argv[i]);
        }
    }

    if (cmd == CMD_NONE) {
        print_usage(argv[0]);
        return EXIT_FAILURE;
    }

    ensure_dirs();

    /* Load .env file if present */
    char envpath[PATH_MAX];
    runtime_path(ENV_FILE_NAME, NULL, envpath, sizeof(envpath));
    load_env(envpath);

    service_t services[MAX_SERVICES];
    size_t svc_count = 0;

    if (cmd != CMD_LOGS) {
        if (services_csv)
            parse_services(services_csv, services, &svc_count);
        else
            default_services(services, &svc_count);
    }

    switch (cmd) {
    case CMD_START:
        return start_services(services, svc_count);
    case CMD_STOP:
        return stop_services(services, svc_count);
    case CMD_STATUS:
        return status_services(services, svc_count);
    case CMD_LOGS:
        if (!log_service) die("--service is required with --logs");
        return tail_logs(log_service);
    default:
        die("Unsupported command");
    }
}

/*──────────────────────────── End of file ───────────────────────────────*/
```