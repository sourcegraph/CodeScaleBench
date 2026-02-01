```c
/**
 * EduPay Ledger Academy – Bursar Service
 * --------------------------------------
 * File:    src/services/bursar_service/main.c
 * Author:  EduPay Engineering Team
 *
 * Description:
 *  Entry-point for the Bursar micro-service.  The service listens for
 *  “TuitionDue”, “PaymentPosted”, “ScholarshipApplied”, and control events
 *  published on the internal message bus.  Clean-Architecture guidelines are
 *  followed – all external dependencies are inverted behind thin adapters so
 *  that instructors can swap them during coursework.
 *
 *  For the purpose of the courseware this file contains self-contained,
 *  production-quality code that compiles and runs without any external
 *  libraries, while still modelling realistic service behaviour.  In the
 *  real system most of these concerns (logging, configuration, broker,
 *  metrics) live in their own translation units.
 *
 * Build:
 *     $ cc -std=c11 -Wall -Wextra -pedantic -pthread \
 *          -o bursar_service src/services/bursar_service/main.c
 *
 * Run:
 *     $ ./bursar_service  # reads newline-delimited events from STDIN
 *
 *     Example:
 *        echo "TUITION_DUE student_id=42 amount=12500 currency=USD" | ./bursar_service
 */

#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* -------------------------------------------------------------------------- */
/*                               Version / Flags                              */
/* -------------------------------------------------------------------------- */

#define SERVICE_NAME        "bursar_service"
#define SERVICE_VERSION     "0.9.3"
#define DEFAULT_BROKER_URI  "stdio://localhost"
#define CFG_ENV_PREFIX      "EDUPAY_"
#define MAX_EVENT_LINE      1024
#define MAX_PAYLOAD         768
#define MAX_TYPE_LEN        64

/* Enable Saga failure simulation with export EDUPAY_SAGA_MODE=1 */
static bool g_saga_mode = false;

/* -------------------------------------------------------------------------- */
/*                                    ANSI                                    */
/* -------------------------------------------------------------------------- */

#define CLR_RESET   "\033[0m"
#define CLR_RED     "\033[31m"
#define CLR_GREEN   "\033[32m"
#define CLR_YELLOW  "\033[33m"
#define CLR_CYAN    "\033[36m"

/* -------------------------------------------------------------------------- */
/*                                   Logging                                  */
/* -------------------------------------------------------------------------- */

typedef enum {
    LOG_DEBUG = 0,
    LOG_INFO,
    LOG_WARN,
    LOG_ERROR,
} LogLevel;

static const char *level_to_str(LogLevel lvl)
{
    switch (lvl) {
        case LOG_DEBUG: return "DEBUG";
        case LOG_INFO:  return "INFO";
        case LOG_WARN:  return "WARN";
        case LOG_ERROR: return "ERROR";
        default:        return "UNKNOWN";
    }
}

static LogLevel g_log_level = LOG_INFO;
static FILE    *g_log_sink  = NULL;

static void log_init(LogLevel lvl, FILE *sink)
{
    g_log_level = lvl;
    g_log_sink  = sink ? sink : stderr;
}

static void log_write(LogLevel lvl, const char *fmt, ...)
{
    if (lvl < g_log_level) return;

    /* Timestamp in UTC ISO-8601 */
    time_t     now = time(NULL);
    struct tm  tm_utc;
    char       ts[32];
    gmtime_r(&now, &tm_utc);
    strftime(ts, sizeof ts, "%Y-%m-%dT%H:%M:%SZ", &tm_utc);

    /* Color by severity */
    const char *color = "";
    const char *reset = "";
    switch (lvl) {
        case LOG_ERROR: color = CLR_RED;    reset = CLR_RESET; break;
        case LOG_WARN:  color = CLR_YELLOW; reset = CLR_RESET; break;
        case LOG_INFO:  color = CLR_GREEN;  reset = CLR_RESET; break;
        case LOG_DEBUG: color = CLR_CYAN;   reset = CLR_RESET; break;
        default: break;
    }

    fprintf(g_log_sink, "%s [%s%s%s] %s: ", ts, color, level_to_str(lvl),
            reset, SERVICE_NAME);

    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_log_sink, fmt, ap);
    va_end(ap);
    fprintf(g_log_sink, "\n");
    fflush(g_log_sink);
}

/* -------------------------------------------------------------------------- */
/*                                 Configuration                              */
/* -------------------------------------------------------------------------- */

typedef struct {
    char     broker_uri[256];
    char     service_id[64];
    int      max_retry;
    LogLevel log_level;
} BursarConfig;

static void cfg_set_defaults(BursarConfig *cfg)
{
    snprintf(cfg->broker_uri, sizeof cfg->broker_uri, "%s", DEFAULT_BROKER_URI);
    snprintf(cfg->service_id, sizeof cfg->service_id,  "%s-%s", SERVICE_NAME,
             SERVICE_VERSION);
    cfg->max_retry  = 3;
    cfg->log_level  = LOG_INFO;
}

/* Simple environment-based configuration loader */
static void cfg_load_from_env(BursarConfig *cfg)
{
    const char *uri  = getenv(CFG_ENV_PREFIX "BROKER_URI");
    const char *lvl  = getenv(CFG_ENV_PREFIX "LOG_LEVEL");
    const char *retry = getenv(CFG_ENV_PREFIX "MAX_RETRY");

    if (uri && *uri)
        snprintf(cfg->broker_uri, sizeof cfg->broker_uri, "%s", uri);

    if (retry && *retry)
        cfg->max_retry = (int)strtol(retry, NULL, 10);

    if (lvl && *lvl) {
        if (strcasecmp(lvl, "DEBUG") == 0) cfg->log_level = LOG_DEBUG;
        else if (strcasecmp(lvl, "INFO") == 0) cfg->log_level = LOG_INFO;
        else if (strcasecmp(lvl, "WARN") == 0) cfg->log_level = LOG_WARN;
        else if (strcasecmp(lvl, "ERROR") == 0) cfg->log_level = LOG_ERROR;
    }
}

/* -------------------------------------------------------------------------- */
/*                                 Broker Stub                                */
/* -------------------------------------------------------------------------- */

/**
 * For pedagogical purposes the broker is modelled as STDIN/STDOUT.
 * Instructors may swap in a real AMQP or Kafka implementation without
 * touching business rules – only this adapter is replaced.
 */

typedef struct {
    char type[MAX_TYPE_LEN];
    char payload[MAX_PAYLOAD];
} Message;

static bool broker_receive(Message *out_msg)
{
    char line[MAX_EVENT_LINE];

    if (!fgets(line, sizeof line, stdin))
        return false; /* EOF */

    size_t len = strlen(line);
    if (len == 0) return false;
    if (line[len - 1] == '\n') line[len - 1] = '\0';

    /* Tokenize: first token is event type */
    char *saveptr;
    char *tok = strtok_r(line, " ", &saveptr);
    if (!tok) return false;

    snprintf(out_msg->type, sizeof out_msg->type, "%s", tok);

    char *rest = strtok_r(NULL, "", &saveptr); /* get remainder */
    snprintf(out_msg->payload, sizeof out_msg->payload, "%s",
             rest ? rest : "");

    return true;
}

static void broker_publish(const Message *msg)
{
    /* Production code would publish to the real bus.
       Here we log and write to stdout to keep demo self-contained. */

    log_write(LOG_DEBUG, "Publishing %s | %s", msg->type, msg->payload);

    fprintf(stdout, "%s %s\n", msg->type, msg->payload);
    fflush(stdout);
}

/* -------------------------------------------------------------------------- */
/*                                   Metrics                                  */
/* -------------------------------------------------------------------------- */

typedef struct {
    uint64_t events_processed;
    uint64_t failures;
    time_t   start_ts;
} Metrics;

static Metrics g_metrics = { 0 };

static void metrics_init(void)
{
    g_metrics.events_processed = 0;
    g_metrics.failures         = 0;
    g_metrics.start_ts         = time(NULL);
}

static void metrics_report(void)
{
    double uptime = difftime(time(NULL), g_metrics.start_ts);

    log_write(LOG_INFO,
              "Service stopped.  Processed %" PRIu64 " events, %" PRIu64
              " failures over %.1f seconds.",
              g_metrics.events_processed, g_metrics.failures, uptime);
}

/* -------------------------------------------------------------------------- */
/*                                 Domain Logic                               */
/* -------------------------------------------------------------------------- */

/* Simplified accounting book */
typedef struct {
    char   student_id[32];
    double balance;
    char   currency[8];
} LedgerEntry;

#define MAX_LEDGER 256
static LedgerEntry g_ledger[MAX_LEDGER];
static size_t      g_ledger_count = 0;

static LedgerEntry *ledger_find_or_create(const char *student_id,
                                          const char *currency)
{
    for (size_t i = 0; i < g_ledger_count; ++i)
        if (strcmp(g_ledger[i].student_id, student_id) == 0)
            return &g_ledger[i];

    if (g_ledger_count >= MAX_LEDGER) return NULL;

    LedgerEntry *e = &g_ledger[g_ledger_count++];
    snprintf(e->student_id, sizeof e->student_id, "%s", student_id);
    snprintf(e->currency, sizeof e->currency, "%s", currency);
    e->balance = 0.0;
    return e;
}

static bool parse_keyval(char *src, const char *key, char *dst,
                         size_t dst_sz)
{
    size_t key_len = strlen(key);
    char  *p = strstr(src, key);
    if (!p) return false;
    p += key_len; /* skip key */
    if (*p != '=') return false;
    ++p;
    char *end = strchr(p, ' ');
    size_t len = end ? (size_t)(end - p) : strlen(p);
    if (len >= dst_sz) len = dst_sz - 1;
    strncpy(dst, p, len);
    dst[len] = '\0';
    return true;
}

/* Tuition Due event handler */
static bool handle_tuition_due(const char *payload)
{
    char student_id[32] = {0};
    char amount_str[32] = {0};
    char currency[8]    = {0};

    if (!parse_keyval((char *)payload, "student_id", student_id,
                      sizeof student_id) ||
        !parse_keyval((char *)payload, "amount", amount_str,
                      sizeof amount_str) ||
        !parse_keyval((char *)payload, "currency", currency,
                      sizeof currency))
    {
        log_write(LOG_ERROR, "Malformed TUITION_DUE payload: %s", payload);
        return false;
    }

    double amount = atof(amount_str);
    LedgerEntry *entry = ledger_find_or_create(student_id, currency);
    if (!entry) {
        log_write(LOG_ERROR, "Ledger full, cannot add student %s", student_id);
        return false;
    }

    entry->balance += amount;
    log_write(LOG_INFO,
              "Recorded tuition due for student %s: +%.2f %s "
              "(new balance %.2f)",
              student_id, amount, currency, entry->balance);

    /* Emit accounting event */
    Message m = { "LEDGER_UPDATED", "" };
    snprintf(m.payload, sizeof m.payload,
             "student_id=%s balance=%.2f currency=%s",
             student_id, entry->balance, currency);

    broker_publish(&m);
    return true;
}

/* Payment Posted event handler */
static bool handle_payment_posted(const char *payload)
{
    char student_id[32] = {0};
    char amount_str[32] = {0};
    char currency[8]    = {0};

    if (!parse_keyval((char *)payload, "student_id", student_id,
                      sizeof student_id) ||
        !parse_keyval((char *)payload, "amount", amount_str,
                      sizeof amount_str) ||
        !parse_keyval((char *)payload, "currency", currency,
                      sizeof currency))
    {
        log_write(LOG_ERROR, "Malformed PAYMENT_POSTED payload: %s", payload);
        return false;
    }

    double amount = atof(amount_str);
    LedgerEntry *entry = ledger_find_or_create(student_id, currency);
    if (!entry) {
        log_write(LOG_ERROR, "Ledger full, cannot add student %s", student_id);
        return false;
    }

    entry->balance -= amount;
    log_write(LOG_INFO,
              "Payment posted for student %s: -%.2f %s "
              "(new balance %.2f)",
              student_id, amount, currency, entry->balance);

    Message m = { "LEDGER_UPDATED", "" };
    snprintf(m.payload, sizeof m.payload,
             "student_id=%s balance=%.2f currency=%s",
             student_id, entry->balance, currency);
    broker_publish(&m);
    return true;
}

/* Saga demonstration – artificially fail every Nth event */
static bool saga_maybe_fail(void)
{
    static int counter = 0;
    const  int fail_after = 5;

    if (!g_saga_mode)
        return false;

    if (++counter >= fail_after) {
        counter = 0;
        log_write(LOG_WARN,
                  "Saga mode: simulated outage after %d events.  "
                  "Throwing SIGTERM to trigger rollback.",
                  fail_after);
        raise(SIGTERM);
        return true;
    }
    return false;
}

/* Primary dispatcher */
static bool process_message(const Message *msg)
{
    ++g_metrics.events_processed;

    if (strcmp(msg->type, "TUITION_DUE") == 0)
        return handle_tuition_due(msg->payload);

    else if (strcmp(msg->type, "PAYMENT_POSTED") == 0)
        return handle_payment_posted(msg->payload);

    else if (strcmp(msg->type, "SHUTDOWN") == 0) {
        log_write(LOG_INFO, "Shutdown event received.");
        return false;
    }

    else {
        log_write(LOG_WARN, "Unhandled event type: %s", msg->type);
        return true; /* keep running */
    }
}

/* -------------------------------------------------------------------------- */
/*                               Graceful Shutdown                            */
/* -------------------------------------------------------------------------- */

static atomic_bool g_should_stop = ATOMIC_VAR_INIT(false);

static void on_signal(int sig)
{
    (void)sig;
    atomic_store_explicit(&g_should_stop, true, memory_order_relaxed);
}

/* -------------------------------------------------------------------------- */
/*                                    Main                                    */
/* -------------------------------------------------------------------------- */

int main(int argc, char **argv)
{
    (void)argc; (void)argv;

    /* Config ---------------------------------------------------------------- */
    BursarConfig cfg;
    cfg_set_defaults(&cfg);
    cfg_load_from_env(&cfg);

    /* Logging ---------------------------------------------------------------- */
    log_init(cfg.log_level, stderr);
    log_write(LOG_INFO, "%s v%s booting…", SERVICE_NAME, SERVICE_VERSION);

    /* Saga mode -------------------------------------------------------------- */
    g_saga_mode = (getenv(CFG_ENV_PREFIX "SAGA_MODE") != NULL);

    /* Metrics ---------------------------------------------------------------- */
    metrics_init();

    /* Signal handling -------------------------------------------------------- */
    struct sigaction sa = {0};
    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    /* Event loop ------------------------------------------------------------- */
    Message msg;
    while (!atomic_load_explicit(&g_should_stop, memory_order_relaxed)) {

        /* Non-blocking check if data ready on stdin */
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(STDIN_FILENO, &rfds);
        struct timeval tv = { .tv_sec = 0, .tv_usec = 250000 }; /* 250ms */
        int ret = select(STDIN_FILENO + 1, &rfds, NULL, NULL, &tv);
        if (ret == -1) {
            if (errno == EINTR) continue;
            log_write(LOG_ERROR, "select() failed: %s", strerror(errno));
            break;
        }

        if (ret == 0) continue; /* timeout – heartbeat */

        if (!broker_receive(&msg)) {
            /* EOF reached – treat as graceful shutdown */
            log_write(LOG_INFO, "Input stream closed.  Exiting.");
            break;
        }

        if (!process_message(&msg))
            atomic_store_explicit(&g_should_stop, true, memory_order_relaxed);

        /* Simulate failure when saga mode enabled */
        if (saga_maybe_fail())
            break;
    }

    metrics_report();
    return 0;
}
```