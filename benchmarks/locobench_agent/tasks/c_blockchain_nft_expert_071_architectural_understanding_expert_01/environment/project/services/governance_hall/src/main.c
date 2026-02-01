/*
 * HoloCanvas Governance Hall – Main Service Entrypoint
 *
 * Project      : HoloCanvas – A Micro-Gallery Blockchain for Generative Artifacts
 * Service      : governance_hall
 * File         : src/main.c
 * Description  :
 *      Governance-Hall is the DAO brain of HoloCanvas.  It ingests on-chain &
 *      off-chain governance events (Kafka), keeps an in-memory registry of
 *      proposals, tallies votes, drives state transitions in accordance with
 *      the platform’s finite-state machine, and emits deterministic events back
 *      onto the mesh for downstream services (LedgerCore, Mint-Factory, etc.).
 *
 *      This file hosts:
 *          • Process lifecycle & CLI parsing
 *          • Signal-safe, graceful shutdown
 *          • Event-consumer worker thread (Kafka stub)
 *          • Proposal FSM & in-memory store (uthash)
 *          • Minimalistic logging framework
 *
 * Build flags  :
 *      cc -Wall -Wextra -pedantic -pthread -std=c11 -o governance_hall \
 *          src/main.c -lrdkafka          # real Kafka
 *         (or remove -lrdkafka if you only want to unit-test the core FSM)
 */

#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>       /* clock_gettime */
#include <pthread.h>
#include <unistd.h>

#include "uthash.h"     /* https://troydhanson.github.io/uthash/ */

#ifdef WITH_KAFKA
#   include <rdkafka.h>
#endif

/* -------------------------------------------------------------------------- */
/*                               Build-time Info                              */
/* -------------------------------------------------------------------------- */
#define GOV_HALL_VERSION "1.2.0"
#define BUILD_TIMESTAMP  __DATE__ " " __TIME__

/* -------------------------------------------------------------------------- */
/*                                 Logging                                    */
/* -------------------------------------------------------------------------- */
typedef enum {
    LOG_DEBUG,
    LOG_INFO,
    LOG_WARN,
    LOG_ERROR,
    LOG_FATAL
} log_level_t;

/* The log level can be overridden via the GOV_HALL_LOG_LEVEL env variable */
static log_level_t g_log_level = LOG_INFO;

static const char *log_level_str(log_level_t lvl)
{
    switch (lvl) {
    case LOG_DEBUG: return "DEBUG";
    case LOG_INFO:  return "INFO ";
    case LOG_WARN:  return "WARN ";
    case LOG_ERROR: return "ERROR";
    case LOG_FATAL: return "FATAL";
    default:        return "?????";
    }
}

static void log_internal(log_level_t lvl,
                         const char *file,
                         int line,
                         const char *fmt, ...)
{
    if (lvl < g_log_level) {
        return;
    }

    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);

    struct tm tm;
    localtime_r(&ts.tv_sec, &tm);

    char ts_buf[64];
    strftime(ts_buf, sizeof ts_buf, "%Y-%m-%d %H:%M:%S", &tm);

    fprintf((lvl >= LOG_ERROR) ? stderr : stdout,
            "%s.%03ld [%s] %s:%d: ",
            ts_buf, ts.tv_nsec / 1000000,
            log_level_str(lvl),
            file, line);

    va_list ap;
    va_start(ap, fmt);
    vfprintf((lvl >= LOG_ERROR) ? stderr : stdout, fmt, ap);
    va_end(ap);

    fputc('\n', (lvl >= LOG_ERROR) ? stderr : stdout);

    if (lvl == LOG_FATAL) {
        abort();
    }
}

#define LOGD(...) log_internal(LOG_DEBUG, __FILE__, __LINE__, __VA_ARGS__)
#define LOGI(...) log_internal(LOG_INFO,  __FILE__, __LINE__, __VA_ARGS__)
#define LOGW(...) log_internal(LOG_WARN,  __FILE__, __LINE__, __VA_ARGS__)
#define LOGE(...) log_internal(LOG_ERROR, __FILE__, __LINE__, __VA_ARGS__)
#define LOGF(...) log_internal(LOG_FATAL, __FILE__, __LINE__, __VA_ARGS__)

/* -------------------------------------------------------------------------- */
/*                         Governance Proposal State                          */
/* -------------------------------------------------------------------------- */

typedef enum {
    PROPOSAL_DRAFT = 0,
    PROPOSAL_VOTING,
    PROPOSAL_ACCEPTED,
    PROPOSAL_REJECTED,
    PROPOSAL_EXECUTED
} proposal_state_t;

typedef struct governance_proposal {
    char id[64];                /* unique sha-256/uuid string */
    proposal_state_t state;
    uint64_t yes_votes;
    uint64_t no_votes;
    time_t created_at;
    time_t voting_deadline;     /* epoch seconds */
    UT_hash_handle hh;          /* makes this struct hashable */
} governance_proposal_t;

/* In-memory key-value store of proposals */
static governance_proposal_t *g_proposals = NULL;
/* Protects g_proposals against concurrent reads/writes */
static pthread_rwlock_t g_prop_lock = PTHREAD_RWLOCK_INITIALIZER;

/* Lookup or create a proposal record */
static governance_proposal_t *
proposal_get_or_create(const char *id)
{
    governance_proposal_t *p = NULL;
    pthread_rwlock_rdlock(&g_prop_lock);
    HASH_FIND_STR(g_proposals, id, p);
    pthread_rwlock_unlock(&g_prop_lock);

    if (p) {
        return p;
    }

    /* Not found – upgrade to write lock and allocate */
    pthread_rwlock_wrlock(&g_prop_lock);
    HASH_FIND_STR(g_proposals, id, p);
    if (!p) {
        p = calloc(1, sizeof *p);
        if (!p) {
            pthread_rwlock_unlock(&g_prop_lock);
            LOGE("Memory allocation failed for proposal '%s'", id);
            return NULL;
        }
        strncpy(p->id, id, sizeof p->id - 1);
        p->created_at = time(NULL);
        p->state      = PROPOSAL_DRAFT;
        HASH_ADD_STR(g_proposals, id, p);
        LOGI("Created new proposal %s", id);
    }
    pthread_rwlock_unlock(&g_prop_lock);
    return p;
}

/* Apply proposal finite-state transitions */
static void proposal_try_finalize(governance_proposal_t *p)
{
    if (p->state != PROPOSAL_VOTING) {
        return;
    }

    time_t now = time(NULL);
    if (now < p->voting_deadline) {
        return;
    }

    /* Time is up – tally */
    p->state = (p->yes_votes > p->no_votes)
                 ? PROPOSAL_ACCEPTED
                 : PROPOSAL_REJECTED;

    LOGI("Proposal %s finalized as %s (yes=%" PRIu64 ", no=%" PRIu64 ")",
         p->id,
         (p->state == PROPOSAL_ACCEPTED) ? "ACCEPTED" : "REJECTED",
         p->yes_votes, p->no_votes);
}

/* -------------------------------------------------------------------------- */
/*                       Mock Event Deserialization Layer                     */
/* -------------------------------------------------------------------------- */

/*
 * In production we ingest binary protobuf payloads from Kafka.  For purposes of
 * this sample we accept a line-oriented JSON subset coming from stdin, Kafka,
 * or a test file.  Each line is one event:
 *
 *  { "type":"PROPOSAL_CREATE", "id":"abc", "voting_deadline":1660000000 }
 *  { "type":"VOTE_CAST", "id":"abc", "vote":"yes" }
 *
 * This rudimentary parser keeps the demo self-contained without pulling in a
 * heavyweight JSON stack.  It is NOT robust and must be replaced for prod.
 */

typedef enum {
    EVT_NONE = 0,
    EVT_PROPOSAL_CREATE,
    EVT_VOTE_CAST,
    EVT_FINALIZE_REQ
} event_type_t;

typedef struct {
    event_type_t type;
    char id[64];
    uint64_t voting_deadline;   /* for CREATE */
    bool vote_yes;              /* for VOTE */
} event_t;

static void trim(char *s)
{
    char *p = s;
    size_t len = strlen(s);
    while (len && (s[len - 1] == '\n' || s[len - 1] == '\r' || s[len - 1] == ' '))
        s[--len] = '\0';
    while (*p == ' ' || *p == '\t')
        ++p;
    if (p != s)
        memmove(s, p, strlen(p) + 1);
}

/* Extremely naive key search */
static const char *json_get_value(const char *json, const char *key, char *buf, size_t buf_sz)
{
    char pattern[64];
    snprintf(pattern, sizeof pattern, "\"%s\":\"", key);
    const char *p = strstr(json, pattern);
    if (!p) return NULL;
    p += strlen(pattern);
    const char *q = strchr(p, '"');
    if (!q) return NULL;
    size_t len = (size_t)(q - p);
    if (len >= buf_sz) len = buf_sz - 1;
    memcpy(buf, p, len);
    buf[len] = '\0';
    return buf;
}

static bool json_get_uint64(const char *json, const char *key, uint64_t *out)
{
    char pattern[64];
    snprintf(pattern, sizeof pattern, "\"%s\":", key);
    const char *p = strstr(json, pattern);
    if (!p) return false;
    p += strlen(pattern);
    *out = strtoull(p, NULL, 10);
    return true;
}

static event_type_t parse_event_type(const char *json)
{
    char type[32];
    if (!json_get_value(json, "type", type, sizeof type))
        return EVT_NONE;

    if (strcmp(type, "PROPOSAL_CREATE") == 0) return EVT_PROPOSAL_CREATE;
    if (strcmp(type, "VOTE_CAST")       == 0) return EVT_VOTE_CAST;
    if (strcmp(type, "FINALIZE_REQ")    == 0) return EVT_FINALIZE_REQ;
    return EVT_NONE;
}

static bool parse_event(const char *line, event_t *out_evt)
{
    memset(out_evt, 0, sizeof *out_evt);
    out_evt->type = parse_event_type(line);
    if (out_evt->type == EVT_NONE) {
        return false;
    }

    char id[64];
    if (!json_get_value(line, "id", id, sizeof id))
        return false;
    strncpy(out_evt->id, id, sizeof out_evt->id - 1);

    switch (out_evt->type) {
    case EVT_PROPOSAL_CREATE:
        if (!json_get_uint64(line, "voting_deadline", &out_evt->voting_deadline))
            return false;
        break;
    case EVT_VOTE_CAST: {
        char vote[8];
        if (!json_get_value(line, "vote", vote, sizeof vote))
            return false;
        out_evt->vote_yes = (strcmp(vote, "yes") == 0);
        break;
    }
    default: break;
    }
    return true;
}

/* -------------------------------------------------------------------------- */
/*                             Event Processing                               */
/* -------------------------------------------------------------------------- */

static void handle_event(const event_t *ev)
{
    governance_proposal_t *p = NULL;

    switch (ev->type) {
    case EVT_PROPOSAL_CREATE:
        p = proposal_get_or_create(ev->id);
        if (!p) break;

        p->state           = PROPOSAL_VOTING;
        p->voting_deadline = (time_t)ev->voting_deadline;
        LOGI("Proposal %s entered VOTING state (deadline=%lu)",
             p->id, (unsigned long)p->voting_deadline);
        break;

    case EVT_VOTE_CAST:
        p = proposal_get_or_create(ev->id);
        if (!p) break;

        if (p->state != PROPOSAL_VOTING) {
            LOGW("Vote ignored for non-voting proposal %s", p->id);
            break;
        }

        if (ev->vote_yes)
            p->yes_votes++;
        else
            p->no_votes++;

        LOGD("Vote registered on %s → yes=%" PRIu64 ", no=%" PRIu64,
             p->id, p->yes_votes, p->no_votes);
        break;

    case EVT_FINALIZE_REQ:
        pthread_rwlock_rdlock(&g_prop_lock);
        HASH_FIND_STR(g_proposals, ev->id, p);
        pthread_rwlock_unlock(&g_prop_lock);

        if (!p) {
            LOGW("Finalize requested for unknown proposal %s", ev->id);
            break;
        }
        proposal_try_finalize(p);
        break;

    default:
        LOGW("Unhandled event type %d", ev->type);
        break;
    }
}

/* -------------------------------------------------------------------------- */
/*                            Event Consumer Loop                             */
/* -------------------------------------------------------------------------- */

static atomic_bool g_running = ATOMIC_VAR_INIT(true);

static void sig_handler(int sig)
{
    (void)sig;
    atomic_store(&g_running, false);
}

static void *event_consumer_thread(void *arg)
{
    (void)arg;
    LOGI("Event consumer started");

#ifdef WITH_KAFKA
    /* Kafka setup (omitted for brevity) */
#endif

    char *line = NULL;
    size_t n   = 0;

    while (atomic_load(&g_running)) {
        ssize_t rd = getline(&line, &n, stdin);
        if (rd == -1) {
            if (feof(stdin)) {
                LOGI("EOF reached on stdin – terminating");
                break;
            } else if (errno == EINTR) {
                continue;
            } else {
                LOGE("getline failed: %s", strerror(errno));
                break;
            }
        }
        trim(line);
        if (*line == '\0') continue;

        event_t evt;
        if (!parse_event(line, &evt)) {
            LOGW("Unable to parse event: %s", line);
            continue;
        }
        handle_event(&evt);
    }

    free(line);
    LOGI("Event consumer stopped");
    return NULL;
}

/* -------------------------------------------------------------------------- */
/*                             CLI & Bootstrapping                            */
/* -------------------------------------------------------------------------- */

static void load_env_config(void)
{
    const char *lvl = getenv("GOV_HALL_LOG_LEVEL");
    if (lvl) {
        if (strcmp(lvl, "DEBUG") == 0) g_log_level = LOG_DEBUG;
        else if (strcmp(lvl, "INFO") == 0) g_log_level = LOG_INFO;
        else if (strcmp(lvl, "WARN") == 0) g_log_level = LOG_WARN;
        else if (strcmp(lvl, "ERROR") == 0) g_log_level = LOG_ERROR;
        else if (strcmp(lvl, "FATAL") == 0) g_log_level = LOG_FATAL;
    }
}

static void usage(const char *exe)
{
    printf(
        "HoloCanvas Governance Hall %s (built %s)\n\n"
        "Usage: %s [options]\n"
        "Options:\n"
        "  -h, --help            Show this help\n"
        "\n"
        "Environment variables:\n"
        "  GOV_HALL_LOG_LEVEL    DEBUG|INFO|WARN|ERROR|FATAL (default INFO)\n",
        GOV_HALL_VERSION, BUILD_TIMESTAMP, exe);
}

int main(int argc, char **argv)
{
    /* --------------------------- CLI: parse flags ------------------------- */
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "-h") || !strcmp(argv[i], "--help")) {
            usage(argv[0]);
            return EXIT_SUCCESS;
        } else {
            fprintf(stderr, "Unknown option: %s\n", argv[i]);
            usage(argv[0]);
            return EXIT_FAILURE;
        }
    }

    /* -------------------------- Config & logging -------------------------- */
    load_env_config();
    LOGI("Starting Governance Hall v%s (%s)", GOV_HALL_VERSION, BUILD_TIMESTAMP);

    /* -------------------------- Signal handling --------------------------- */
    struct sigaction sa = { .sa_handler = sig_handler };
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    /* -------------------------- Start consumer --------------------------- */
    pthread_t consumer_tid;
    if (pthread_create(&consumer_tid, NULL, event_consumer_thread, NULL) != 0) {
        LOGF("Failed to spawn consumer thread: %s", strerror(errno));
    }

    /* -------------------------- Main thread loop ------------------------- */
    while (atomic_load(&g_running)) {
        /* Periodically walk proposals to auto-finalize */
        pthread_rwlock_rdlock(&g_prop_lock);
        governance_proposal_t *p, *tmp;
        HASH_ITER(hh, g_proposals, p, tmp) {
            proposal_try_finalize(p);
        }
        pthread_rwlock_unlock(&g_prop_lock);

        /* Sleep for 1 second */
        struct timespec ts = { .tv_sec = 1, .tv_nsec = 0 };
        nanosleep(&ts, NULL);
    }

    /* ---------------------------- Shutdown ------------------------------- */
    LOGI("Shutting down…");
    pthread_join(consumer_tid, NULL);

    /* Clean up hash table */
    pthread_rwlock_wrlock(&g_prop_lock);
    governance_proposal_t *curr, *tmp2;
    HASH_ITER(hh, g_proposals, curr, tmp2) {
        HASH_DEL(g_proposals, curr);
        free(curr);
    }
    pthread_rwlock_unlock(&g_prop_lock);

    LOGI("Goodbye");
    return EXIT_SUCCESS;
}