/*
 * EduPay Ledger Academy – Projections Service
 *
 * File:    src/projections_service/main.c
 * Author:  EduPay Engineering Team
 *
 * Synopsis:
 *   A lightweight CQRS read-model updater that consumes immutable
 *   domain events from a newline-delimited JSON stream and projects
 *   them into an optimized SQLite read database.  Although production
 *   deployments feed events over Kafka, this reference implementation
 *   keeps I/O simple so that students can experiment on a single laptop
 *   without brokers or containers.
 *
 * Build:
 *      cc -std=c11 -Wall -Wextra -O2 -pthread main.c -lsqlite3 -o projections_service
 *
 * Example Usage:
 *      ./projections_service                                 \
 *          --events ./tmp/events.ndjson                       \
 *          --db     ./tmp/edu_pay_read.db
 *
 * Event Format (newline-delimited JSON):
 *      {"type":"payment_created","currency":"USD","amount":100.00}
 *      {"type":"payment_refunded","currency":"USD","amount":25.00}
 *
 * Resulting projection table (payments_summary):
 *      currency | total_amount
 *      ---------|-------------
 *      USD      | 75.00
 *
 * Design Notes:
 *   • Clean shutdown on SIGINT/SIGTERM via atomic flag.
 *   • Robust error handling and resource cleanup.
 *   • Modularised for unit testing (e.g., inject f* streams, db handles).
 *   • Single-threaded for clarity; swap to worker pool if event volume grows.
 */

#define _POSIX_C_SOURCE 200809L   /* getline, sigaction */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sqlite3.h>
#include <getopt.h>
#include <signal.h>
#include <errno.h>
#include <time.h>
#include <stdatomic.h>

/* ------------------------------------------------------------------------- */
/* Constants & Macros                                                        */
/* ------------------------------------------------------------------------- */

#define APP_NAME            "EduPay Projections Service"
#define APP_VERSION         "1.0.0"
#define LOG_TIME_BUFF       64
#define MAX_LINE_LENGTH     4096    /* reasonable bound for NDJSON line */

/* ------------------------------------------------------------------------- */
/* Global State                                                              */
/* ------------------------------------------------------------------------- */

static atomic_bool g_shutdown_requested = ATOMIC_VAR_INIT(false);

/* ------------------------------------------------------------------------- */
/* Utility – Simple Timestamped Logger                                       */
/* ------------------------------------------------------------------------- */

static void log_msg(const char *level, const char *fmt, ...)
{
    char timebuf[LOG_TIME_BUFF];
    time_t now = time(NULL);
    struct tm tm_now;
    localtime_r(&now, &tm_now);
    strftime(timebuf, sizeof timebuf, "%Y-%m-%d %H:%M:%S", &tm_now);

    fprintf(stderr, "[%s] [%s] ", timebuf, level);

    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);

    fputc('\n', stderr);
}

#define LOG_INFO(...)  log_msg("INFO",  __VA_ARGS__)
#define LOG_WARN(...)  log_msg("WARN",  __VA_ARGS__)
#define LOG_ERR(...)   log_msg("ERROR", __VA_ARGS__)

/* ------------------------------------------------------------------------- */
/* Signal Handling                                                           */
/* ------------------------------------------------------------------------- */

static void handle_signal(int signo)
{
    (void)signo;
    atomic_store(&g_shutdown_requested, true);
}

/* ------------------------------------------------------------------------- */
/* Domain Model                                                              */
/* ------------------------------------------------------------------------- */

typedef enum {
    EVT_PAYMENT_CREATED,
    EVT_PAYMENT_REFUNDED,
    EVT_UNSUPPORTED
} event_type_t;

typedef struct {
    event_type_t type;
    char currency[4];  /* ISO-4217 code, null-terminated */
    double amount;
} event_t;

/* ------------------------------------------------------------------------- */
/* SQLite Helpers                                                            */
/* ------------------------------------------------------------------------- */

static int db_init(sqlite3 *db)
{
    const char *ddl =
        "CREATE TABLE IF NOT EXISTS payments_summary ("
        "  currency     CHAR(3) PRIMARY KEY,"
        "  total_amount REAL NOT NULL"
        ");";
    char *errmsg = NULL;
    int rc = sqlite3_exec(db, ddl, NULL, NULL, &errmsg);
    if (rc != SQLITE_OK) {
        LOG_ERR("SQLite DDL error: %s", errmsg);
        sqlite3_free(errmsg);
    }
    return rc;
}

static int db_apply_event(sqlite3 *db, const event_t *ev)
{
    static const char *upsert_sql =
        "INSERT INTO payments_summary(currency,total_amount) VALUES(?,?) "
        "ON CONFLICT(currency) DO UPDATE SET total_amount = excluded.total_amount "
        "+ (SELECT total_amount FROM payments_summary WHERE currency = excluded.currency);";

    static const char *refund_sql =
        "UPDATE payments_summary SET total_amount = total_amount - ? WHERE currency = ?;";

    sqlite3_stmt *stmt = NULL;
    int rc;

    switch (ev->type) {
        case EVT_PAYMENT_CREATED:
            rc = sqlite3_prepare_v2(db, upsert_sql, -1, &stmt, NULL);
            if (rc != SQLITE_OK) break;
            sqlite3_bind_text (stmt, 1, ev->currency, -1, SQLITE_STATIC);
            sqlite3_bind_double(stmt, 2, ev->amount);
            break;

        case EVT_PAYMENT_REFUNDED:
            rc = sqlite3_prepare_v2(db, refund_sql, -1, &stmt, NULL);
            if (rc != SQLITE_OK) break;
            sqlite3_bind_double(stmt, 1, ev->amount);
            sqlite3_bind_text  (stmt, 2, ev->currency, -1, SQLITE_STATIC);
            break;

        default:
            return SQLITE_OK; /* unsupported events are ignored */
    }

    if (rc != SQLITE_OK) {
        LOG_ERR("SQLite prepare error: %s", sqlite3_errmsg(db));
        return rc;
    }

    rc = sqlite3_step(stmt);
    if (rc != SQLITE_DONE) {
        LOG_ERR("SQLite step error: %s", sqlite3_errmsg(db));
    } else {
        LOG_INFO("Applied %s event: %.2f %s",
                 ev->type == EVT_PAYMENT_CREATED ? "CREATE" : "REFUND",
                 ev->amount, ev->currency);
        rc = SQLITE_OK;
    }
    sqlite3_finalize(stmt);
    return rc;
}

/* ------------------------------------------------------------------------- */
/* Event Parsing (very small JSON subset)                                    */
/* ------------------------------------------------------------------------- */

static event_type_t parse_event_type(const char *type_str)
{
    if (strcmp(type_str, "payment_created") == 0)
        return EVT_PAYMENT_CREATED;
    if (strcmp(type_str, "payment_refunded") == 0)
        return EVT_PAYMENT_REFUNDED;
    return EVT_UNSUPPORTED;
}

/*
 * Extremely lightweight JSON parser – assumes well-formed, flat objects
 * with no escaped quotes.  Suitable only for demo purposes.
 */
static int parse_event(const char *json, event_t *out_ev)
{
    char type[32] = {0};
    char currency[4] = {0};
    double amount = 0.0;

    /* Example input: {"type":"payment_created","currency":"USD","amount":100.0} */
    int matched = sscanf(json,
                         " { \"type\" : \"%31[^\"]\" , \"currency\" : \"%3[^\"]\" , \"amount\" : %lf } ",
                         type, currency, &amount);

    if (matched != 3) {
        /* Try again without spaces for flexibility */
        matched = sscanf(json,
                         "{\"type\":\"%31[^\"]\",\"currency\":\"%3[^\"]\",\"amount\":%lf}",
                         type, currency, &amount);
    }

    if (matched != 3) {
        LOG_WARN("Failed to parse JSON line: %s", json);
        return -1;
    }

    out_ev->type = parse_event_type(type);
    strncpy(out_ev->currency, currency, sizeof out_ev->currency);
    out_ev->amount = amount;

    return 0;
}

/* ------------------------------------------------------------------------- */
/* CLI & Config                                                              */
/* ------------------------------------------------------------------------- */

typedef struct {
    const char *events_path;
    const char *db_path;
} config_t;

static void print_usage(const char *prog)
{
    fprintf(stderr,
        "%s v%s\n"
        "Usage: %s --events <file> --db <sqlite_db>\n\n"
        "Options:\n"
        "  -e, --events   File containing NDJSON event stream    (required)\n"
        "  -d, --db       SQLite database path for projections   (required)\n"
        "  -h, --help     Show this help\n",
        APP_NAME, APP_VERSION, prog);
}

static int parse_cli_args(int argc, char *argv[], config_t *cfg)
{
    static struct option long_opts[] = {
        {"events", required_argument, NULL, 'e'},
        {"db",     required_argument, NULL, 'd'},
        {"help",   no_argument,       NULL, 'h'},
        {0, 0, 0, 0}
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "e:d:h", long_opts, NULL)) != -1) {
        switch (opt) {
            case 'e':
                cfg->events_path = optarg;
                break;
            case 'd':
                cfg->db_path = optarg;
                break;
            case 'h':
            default:
                return -1;
        }
    }

    if (!cfg->events_path || !cfg->db_path) {
        return -1;
    }
    return 0;
}

/* ------------------------------------------------------------------------- */
/* Main Loop                                                                 */
/* ------------------------------------------------------------------------- */

static int run_projection(const config_t *cfg)
{
    /* Open SQLite DB */
    sqlite3 *db = NULL;
    int rc = sqlite3_open(cfg->db_path, &db);
    if (rc != SQLITE_OK) {
        LOG_ERR("Unable to open SQLite DB '%s': %s",
                cfg->db_path, sqlite3_errmsg(db));
        sqlite3_close(db);
        return EXIT_FAILURE;
    }

    if (db_init(db) != SQLITE_OK) {
        sqlite3_close(db);
        return EXIT_FAILURE;
    }

    /* Open event stream */
    FILE *fp = fopen(cfg->events_path, "r");
    if (!fp) {
        LOG_ERR("Unable to open events file '%s': %s",
                cfg->events_path, strerror(errno));
        sqlite3_close(db);
        return EXIT_FAILURE;
    }

    LOG_INFO("Started projections service.  Ctrl+C to stop.");

    char *line = NULL;
    size_t len = 0;
    ssize_t nread;

    while (!atomic_load(&g_shutdown_requested) &&
           (nread = getline(&line, &len, fp)) != -1) {

        if (nread > MAX_LINE_LENGTH) {
            LOG_WARN("Input line too long (%zu bytes), skipping.", nread);
            continue;
        }

        /* Trim newline */
        if (nread > 0 && line[nread-1] == '\n')
            line[nread - 1] = '\0';

        event_t ev;
        if (parse_event(line, &ev) == 0 && ev.type != EVT_UNSUPPORTED) {
            if (db_apply_event(db, &ev) != SQLITE_OK) {
                LOG_ERR("Fatal DB error, aborting.");
                break;
            }
        } else {
            LOG_WARN("Ignoring unsupported/unparseable event.");
        }
    }

    free(line);
    fclose(fp);
    sqlite3_close(db);

    LOG_INFO("Projection service stopped.");
    return EXIT_SUCCESS;
}

/* ------------------------------------------------------------------------- */
/* Entry Point                                                               */
/* ------------------------------------------------------------------------- */

int main(int argc, char *argv[])
{
    config_t cfg = {0};

    if (parse_cli_args(argc, argv, &cfg) != 0) {
        print_usage(argv[0]);
        return EXIT_FAILURE;
    }

    /* Setup signal handlers for graceful shutdown */
    struct sigaction sa = {.sa_handler = handle_signal};
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    return run_projection(&cfg);
}