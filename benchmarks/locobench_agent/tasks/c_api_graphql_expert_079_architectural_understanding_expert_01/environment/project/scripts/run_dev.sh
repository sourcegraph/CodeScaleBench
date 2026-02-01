```c
/*
 * SynestheticCanvas – Development Runner
 * --------------------------------------
 * File:    scripts/run_dev.sh   (yes, it’s actually C – compile & execute)
 * Target:  Launches all local micro-services that compose a full
 *          SynestheticCanvas stack in *development* mode.
 *
 * To build:
 *      cc -std=c11 -Wall -Wextra -pedantic -O2 \
 *         -o run_dev ./scripts/run_dev.sh
 *
 * To run:
 *      ./run_dev                 # uses built-in defaults
 *      ./run_dev -c config.json  # load services/env from JSON file
 *
 * A valid JSON config example:
 * {
 *   "env": {
 *     "SC_LOG_LEVEL":"debug",
 *     "SC_ENV":"development"
 *   },
 *   "services":[
 *     {
 *       "name":"palette",
 *       "exec":"../palette/bin/palette_service",
 *       "args":["--port=7001"]
 *     },
 *     {
 *       "name":"texture",
 *       "exec":"../texture/bin/texture_service",
 *       "args":["--port=7002", "--enable-preview"]
 *     }
 *   ]
 * }
 *
 * Notes:
 *   • No third-party dependencies – shipping with embedded JSMN parser (MIT).
 *   • Designed for POSIX platforms (Linux, macOS).
 */

#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <signal.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/*───────────────────────────────────────────────────────────────────────────*/
/* Logging utilities                                                        */
/*───────────────────────────────────────────────────────────────────────────*/
enum log_level { LOG_INFO, LOG_WARN, LOG_ERROR, LOG_DEBUG };

static enum log_level CURRENT_LEVEL = LOG_INFO;

static const char *level_tag(enum log_level lvl) {
    switch (lvl) {
    case LOG_INFO:  return "INFO ";
    case LOG_WARN:  return "WARN ";
    case LOG_ERROR: return "ERROR";
    case LOG_DEBUG: return "DEBUG";
    default:        return "?????";
    }
}

static void log_set_level_from_env(void) {
    const char *env = getenv("SC_LOG_LEVEL");
    if (!env) return;
    if (strcasecmp(env, "debug") == 0) CURRENT_LEVEL = LOG_DEBUG;
    else if (strcasecmp(env, "warn") == 0) CURRENT_LEVEL = LOG_WARN;
    else if (strcasecmp(env, "error") == 0) CURRENT_LEVEL = LOG_ERROR;
    else CURRENT_LEVEL = LOG_INFO;
}

#define COLOR_RESET   "\x1b[0m"
#define COLOR_INFO    "\x1b[36m"
#define COLOR_WARN    "\x1b[33m"
#define COLOR_ERROR   "\x1b[31m"
#define COLOR_DEBUG   "\x1b[35m"

static void log_msg(enum log_level lvl, const char *fmt, ...) {
    if (lvl > CURRENT_LEVEL) return;

    const char *color =
        (lvl == LOG_INFO)  ? COLOR_INFO  :
        (lvl == LOG_WARN)  ? COLOR_WARN  :
        (lvl == LOG_ERROR) ? COLOR_ERROR : COLOR_DEBUG;

    time_t t = time(NULL);
    struct tm tm;
    localtime_r(&t, &tm);
    char ts[32];
    strftime(ts, sizeof ts, "%H:%M:%S", &tm);

    fprintf(stderr, "%s[%s] %-5s | ", color, ts, level_tag(lvl));
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fprintf(stderr, "%s\n", COLOR_RESET);
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Embedded JSMN – minimalistic JSON parser (MIT)                           */
/*───────────────────────────────────────────────────────────────────────────*/
#ifndef JSMN_HEADER
#define JSMN_HEADER
typedef enum { JSMN_UNDEFINED = 0, JSMN_OBJECT = 1, JSMN_ARRAY  = 2,
               JSMN_STRING   = 3, JSMN_PRIMITIVE = 4 } jsmntype_t;

typedef enum { JSMN_ERROR_NOMEM = -1, JSMN_ERROR_INVAL = -2,
               JSMN_ERROR_PART = -3, JSMN_SUCCESS = 0 } jsmnerr_t;

typedef struct {
    jsmntype_t type;
    int        start;
    int        end;
    int        size;
#ifdef JSMN_PARENT_LINKS
    int parent;
#endif
} jsmntok_t;

typedef struct {
    unsigned int pos;     /* offset in the JSON string */
    unsigned int toknext; /* next token to allocate */
    int          toksuper; /* superior token node, e.g parent object or array */
} jsmn_parser;

void jsmn_init(jsmn_parser *parser);
int  jsmn_parse(jsmn_parser *parser, const char *js, const size_t len,
                jsmntok_t *tokens, const unsigned int num_tokens);
#endif /* JSMN_HEADER */

/* == JSMN implementation == */
#ifdef JSMN_IMPLEMENTATION
#undef JSMN_IMPLEMENTATION
static int jsmn_parse_primitive(jsmn_parser *parser, const char *js,
                                const size_t len, jsmntok_t *tokens,
                                const unsigned int num_tokens);
static int jsmn_parse_string(jsmn_parser *parser, const char *js,
                             const size_t len, jsmntok_t *tokens,
                             const unsigned int num_tokens);

void jsmn_init(jsmn_parser *parser) {
    parser->pos = 0;
    parser->toknext = 0;
    parser->toksuper = -1;
}

static jsmntok_t *jsmn_alloc_token(jsmn_parser *parser,
                                   jsmntok_t *tokens, const unsigned int num_tokens) {
    if (parser->toknext >= num_tokens) return NULL;
    jsmntok_t *tok = &tokens[parser->toknext++];
    tok->start = tok->end = -1;
    tok->size = 0;
#ifdef JSMN_PARENT_LINKS
    tok->parent = -1;
#endif
    return tok;
}

static void jsmn_fill_token(jsmntok_t *token, const jsmntype_t type,
                            const int start, const int end) {
    token->type = type;
    token->start = start;
    token->end   = end;
    token->size  = 0;
}

static int jsmn_parse_primitive(jsmn_parser *parser, const char *js,
                                const size_t len, jsmntok_t *tokens,
                                const unsigned int num_tokens) {
    int start = parser->pos;
    for (; parser->pos < len; parser->pos++) {
        switch (js[parser->pos]) {
        case '\t': case '\r': case '\n': case ' ': case ',': case ']': case '}':
            goto found;
        default:
            /* to quiet -Wswitch */
            break;
        }
    }
found:
    if (tokens == NULL) { parser->pos--; return 0; }
    jsmntok_t *tok = jsmn_alloc_token(parser, tokens, num_tokens);
    if (!tok) return JSMN_ERROR_NOMEM;
    jsmn_fill_token(tok, JSMN_PRIMITIVE, start, parser->pos);
    parser->pos--; return 0;
}

static int jsmn_parse_string(jsmn_parser *parser, const char *js,
                             const size_t len, jsmntok_t *tokens,
                             const unsigned int num_tokens) {
    int start = ++parser->pos;
    for (; parser->pos < len; parser->pos++) {
        char c = js[parser->pos];
        if (c == '\"') goto found;
        if (c == '\\') parser->pos++; /* skip escaped char */
    }
    return JSMN_ERROR_PART;
found:
    if (tokens == NULL) { return 0; }
    jsmntok_t *tok = jsmn_alloc_token(parser, tokens, num_tokens);
    if (!tok) return JSMN_ERROR_NOMEM;
    jsmn_fill_token(tok, JSMN_STRING, start, parser->pos);
    return 0;
}

int jsmn_parse(jsmn_parser *parser, const char *js, const size_t len,
               jsmntok_t *tokens, const unsigned int num_tokens) {
    int r;
    int i;
    jsmntok_t *token;
    for (; parser->pos < len; parser->pos++) {
        char c = js[parser->pos];
        switch (c) {
        case '{': case '[':
            token = jsmn_alloc_token(parser, tokens, num_tokens);
            if (!token) return JSMN_ERROR_NOMEM;
            token->type = (c == '{' ? JSMN_OBJECT : JSMN_ARRAY);
            token->start = parser->pos;
            token->parent = parser->toksuper;
            parser->toksuper = parser->toknext - 1;
            break;
        case '}': case ']':
            for (i = parser->toknext - 1; i >= 0; i--) {
                token = &tokens[i];
                if (token->start != -1 && token->end == -1) {
                    if (token->type != (c == '}' ? JSMN_OBJECT : JSMN_ARRAY))
                        return JSMN_ERROR_INVAL;
                    token->end = parser->pos + 1;
                    parser->toksuper = token->parent;
                    break;
                }
            }
            if (i == -1) return JSMN_ERROR_INVAL;
            break;
        case '\"':
            r = jsmn_parse_string(parser, js, len, tokens, num_tokens);
            if (r < 0) return r;
            if (parser->toksuper != -1) tokens[parser->toksuper].size++;
            break;
        case '\t': case '\r': case '\n': case ' ': case ':': case ',':
            break;
        default:
            r = jsmn_parse_primitive(parser, js, len, tokens, num_tokens);
            if (r < 0) return r;
            if (parser->toksuper != -1) tokens[parser->toksuper].size++;
            break;
        }
    }
    for (i = parser->toknext - 1; i >= 0; i--) {
        if (tokens[i].start != -1 && tokens[i].end == -1) return JSMN_ERROR_PART;
    }
    return JSMN_SUCCESS;
}
#endif /* JSMN_IMPLEMENTATION */

/* We need the implementation in this TU */
#define JSMN_IMPLEMENTATION
#include __FILE__
/*───────────────────────────────────────────────────────────────────────────*/
/* Data structures                                                          */
/*───────────────────────────────────────────────────────────────────────────*/
#define MAX_ARGS         16
#define MAX_SERVICE_NAME 32
#define MAX_SERVICES     32
#define MAX_ENV_VARS     32
#define MAX_JSON_TOKENS  256

typedef struct {
    char  name[MAX_SERVICE_NAME];
    char  exec_path[PATH_MAX];
    char *argv[MAX_ARGS + 2]; /* +2 for exec[0] and NULL terminator */
    pid_t pid;
} service_t;

typedef struct {
    char key[64];
    char val[256];
} env_var_t;

typedef struct {
    service_t services[MAX_SERVICES];
    size_t    service_count;
    env_var_t env[MAX_ENV_VARS];
    size_t    env_count;
} config_t;

static config_t CONFIG = {0};

static void config_add_default_services(void) {
    struct {
        const char *name;
        const char *exec_path;
        const char *args;
    } defaults[] = {
        {"palette",   "../palette/bin/palette_service",   "--port=7001"},
        {"texture",   "../texture/bin/texture_service",   "--port=7002"},
        {"audio",     "../audio/bin/audio_service",       "--port=7003"},
        {"narrative", "../narrative/bin/narrative_service","--port=7004"}
    };
    for (size_t i = 0; i < sizeof defaults / sizeof defaults[0]; ++i) {
        service_t *svc = &CONFIG.services[CONFIG.service_count++];
        snprintf(svc->name, sizeof svc->name, "%s", defaults[i].name);
        snprintf(svc->exec_path, sizeof svc->exec_path, "%s", defaults[i].exec_path);
        svc->argv[0] = svc->exec_path;
        svc->argv[1] = (char *)defaults[i].args;
        svc->argv[2] = NULL;
        svc->pid = 0;
    }
    /* default environment */
    putenv("SC_ENV=development");
    putenv("SC_LOG_LEVEL=info");
}

static bool json_token_eq(const char *json, jsmntok_t *tok, const char *s) {
    return (int)strlen(s) == (tok->end - tok->start) &&
           strncmp(json + tok->start, s, tok->end - tok->start) == 0;
}

static char *json_token_strdup(const char *json, jsmntok_t *tok) {
    size_t len = tok->end - tok->start;
    char *s = malloc(len + 1);
    if (!s) return NULL;
    memcpy(s, json + tok->start, len);
    s[len] = '\0';
    return s;
}

/* Parse JSON config into CONFIG struct */
static int config_load_from_json(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        log_msg(LOG_ERROR, "Unable to open config file '%s': %s", path, strerror(errno));
        return -1;
    }
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *json = malloc(len + 1);
    if (!json) { fclose(f); return -1; }
    fread(json, 1, len, f);
    json[len] = '\0';
    fclose(f);

    jsmn_parser parser;
    jsmntok_t tokens[MAX_JSON_TOKENS];
    jsmn_init(&parser);
    int r = jsmn_parse(&parser, json, len, tokens, MAX_JSON_TOKENS);
    if (r < 0) {
        log_msg(LOG_ERROR, "Invalid JSON in config: error %d", r);
        free(json);
        return -1;
    }

    int i = 1; /* skip root */
    for (; i < r; ++i) {
        if (json_token_eq(json, &tokens[i], "env")) {
            int env_obj = ++i;
            if (tokens[env_obj].type != JSMN_OBJECT) { --i; continue; }
            int env_end = env_obj + tokens[env_obj].size * 2;
            for (int j = env_obj + 1; j <= env_end; j += 2) {
                char *k = json_token_strdup(json, &tokens[j]);
                char *v = json_token_strdup(json, &tokens[j + 1]);
                if (CONFIG.env_count < MAX_ENV_VARS) {
                    snprintf(CONFIG.env[CONFIG.env_count].key, sizeof CONFIG.env[CONFIG.env_count].key, "%s", k);
                    snprintf(CONFIG.env[CONFIG.env_count].val, sizeof CONFIG.env[CONFIG.env_count].val, "%s", v);
                    CONFIG.env_count++;
                    setenv(k, v, 1);
                }
                free(k); free(v);
            }
            i = env_end;
        } else if (json_token_eq(json, &tokens[i], "services")) {
            int arr = ++i;
            if (tokens[arr].type != JSMN_ARRAY) { --i; continue; }
            int idx = 0;
            for (int j = arr + 1; idx < tokens[arr].size; ++idx) {
                jsmntok_t *svc_tok = &tokens[j];
                if (svc_tok->type != JSMN_OBJECT) break;
                service_t *svc = &CONFIG.services[CONFIG.service_count++];
                int kv_pairs = svc_tok->size;
                ++j; /* move to first key */
                for (int k = 0; k < kv_pairs; ++k) {
                    jsmntok_t *key_tok = &tokens[j++];
                    jsmntok_t *val_tok = &tokens[j++];
                    if (json_token_eq(json, key_tok, "name")) {
                        snprintf(svc->name, sizeof svc->name, "%.*s",
                                 val_tok->end - val_tok->start, json + val_tok->start);
                    } else if (json_token_eq(json, key_tok, "exec")) {
                        snprintf(svc->exec_path, sizeof svc->exec_path, "%.*s",
                                 val_tok->end - val_tok->start, json + val_tok->start);
                    } else if (json_token_eq(json, key_tok, "args")) {
                        if (val_tok->type != JSMN_ARRAY) continue;
                        int arg_count = val_tok->size;
                        svc->argv[0] = svc->exec_path;
                        int base = j;
                        for (int a = 0; a < arg_count && a < MAX_ARGS; ++a) {
                            jsmntok_t *arg_tok = &tokens[base + a];
                            svc->argv[a + 1] = json_token_strdup(json, arg_tok);
                        }
                        svc->argv[arg_count + 1] = NULL;
                        j += arg_count;
                    }
                }
                if (svc->argv[0] == NULL) {
                    svc->argv[0] = svc->exec_path;
                    svc->argv[1] = NULL;
                }
            }
        }
    }
    free(json);
    return 0;
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Process management                                                       */
/*───────────────────────────────────────────────────────────────────────────*/
static volatile sig_atomic_t SHUTDOWN = 0;

static void sig_handler(int sig) {
    (void)sig;
    SHUTDOWN = 1;
}

static int spawn_service(service_t *svc) {
    pid_t pid = fork();
    if (pid < 0) {
        log_msg(LOG_ERROR, "Failed to fork for service %s: %s", svc->name, strerror(errno));
        return -1;
    } else if (pid == 0) {
        /* child */
        execvp(svc->exec_path, svc->argv);
        fprintf(stderr, "Exec failed for %s: %s\n", svc->exec_path, strerror(errno));
        _exit(EXIT_FAILURE);
    } else {
        svc->pid = pid;
        log_msg(LOG_INFO, "Started %-10s [pid=%d]", svc->name, pid);
    }
    return 0;
}

static void kill_service(service_t *svc) {
    if (svc->pid <= 0) return;
    if (kill(svc->pid, SIGTERM) == 0) {
        log_msg(LOG_INFO, "Signaled %-10s [pid=%d] for termination", svc->name, svc->pid);
    }
}

static void reap_services(void) {
    int status;
    pid_t pid;
    while ((pid = waitpid(-1, &status, WNOHANG)) > 0) {
        for (size_t i = 0; i < CONFIG.service_count; ++i) {
            if (CONFIG.services[i].pid == pid) {
                log_msg(LOG_WARN, "Service %-10s [pid=%d] exited (status=%d)",
                        CONFIG.services[i].name, pid, status);
                CONFIG.services[i].pid = 0;
            }
        }
    }
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Entry                                                                     */
/*───────────────────────────────────────────────────────────────────────────*/
static void usage(const char *prog) {
    printf("Usage: %s [-c config.json]\n", prog);
}

int main(int argc, char **argv) {
    const char *cfg_path = NULL;
    int opt;
    while ((opt = getopt(argc, argv, "c:h")) != -1) {
        switch (opt) {
        case 'c': cfg_path = optarg; break;
        case 'h': default: usage(argv[0]); return EXIT_SUCCESS;
        }
    }

    /* default */
    config_add_default_services();

    if (cfg_path) {
        /* override / extend defaults with external config */
        if (config_load_from_json(cfg_path) < 0) {
            log_msg(LOG_ERROR, "Loading of config '%s' failed – aborting.", cfg_path);
            return EXIT_FAILURE;
        }
    }

    log_set_level_from_env();
    log_msg(LOG_INFO, "Launching SynestheticCanvas Development stack…");

    struct sigaction sa = {.sa_handler = sig_handler};
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGCHLD, &sa, NULL);

    /* Start services */
    for (size_t i = 0; i < CONFIG.service_count; ++i) {
        spawn_service(&CONFIG.services[i]);
    }

    /* Main loop */
    while (!SHUTDOWN) {
        pause(); /* interrupted by signals */
        reap_services();
    }

    log_msg(LOG_INFO, "Shutting down %zu services…", CONFIG.service_count);
    for (size_t i = 0; i < CONFIG.service_count; ++i) {
        kill_service(&CONFIG.services[i]);
    }

    /* Final reap */
    for (;;) {
        pid_t pid = wait(NULL);
        if (pid == -1) {
            if (errno == ECHILD) break;
        }
    }

    /* Free dynamically allocated argv strings */
    for (size_t i = 0; i < CONFIG.service_count; ++i) {
        for (int a = 1; CONFIG.services[i].argv[a]; ++a) {
            /* Don't free exec_path pointer */
            if (CONFIG.services[i].argv[a] != CONFIG.services[i].exec_path)
                free(CONFIG.services[i].argv[a]);
        }
    }

    log_msg(LOG_INFO, "Goodbye!");
    return EXIT_SUCCESS;
}
```