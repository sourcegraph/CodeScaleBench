```c
/**
 * HoloCanvas – Governance Hall
 * File: services/governance_hall/src/event_handler.c
 *
 * Event-Driven governance layer that listens to Kafka for on-chain DAO
 * instructions (proposals, votes, parameter changes, etc.), performs
 * cryptographic validation, and dispatches the event to strategy plug-ins
 * or internal state-machines.
 *
 * Build:
 *   gcc -std=c11 -Wall -Wextra -pthread \
 *       -lrdkafka -lssl -lcrypto -ljansson -ldl \
 *       -o governance_event_handler event_handler.c
 *
 * Runtime env vars:
 *   GOV_KAFKA_BROKERS   – comma-separated list of brokers
 *   GOV_KAFKA_GROUP_ID  – consumer group id
 *   GOV_KAFKA_TOPICS    – comma-separated list of topics to subscribe
 *   GOV_PUBKEY_FILE     – path to PEM file containing governance public key
 *
 * NOTE:
 *   All cryptographic checks are performed with OpenSSL (EVP interface).
 *   Events are JSON encoded with a common schema:
 *     {
 *       "type"      : "VOTE_CAST",
 *       "payload"   : { ... arbitrary ... },
 *       "sig"       : "<base64-signature>",
 *       "timestamp" : 1684852584
 *     }
 *
 *   Only the canonicalized JSON of `type` + `payload` + `timestamp`
 *   is signed/verified.
 */

#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <inttypes.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <jansson.h>
#include <librdkafka/rdkafka.h>
#include <openssl/bio.h>
#include <openssl/evp.h>
#include <openssl/pem.h>

#include <dlfcn.h>

/* ------------------------------------------------------------------------- *
 * Types                                                                     *
 * ------------------------------------------------------------------------- */

typedef int (*event_callback_fn)(const char *event_type,
                                 const json_t *payload,
                                 void *user_data);

typedef struct callback_entry_s {
    char               *event_type;   /* ownership transferred */
    event_callback_fn   cb;
    void               *user_data;
    struct callback_entry_s *next;
} callback_entry_t;

typedef struct plugin_handle_s {
    void            *dl_handle;
    callback_entry_t *callbacks;
    struct plugin_handle_s *next;
} plugin_handle_t;

typedef struct {
    rd_kafka_t                    *rk;
    rd_kafka_conf_t               *rk_conf;
    rd_kafka_topic_partition_list_t *sub_topics;
    pthread_t                      consumer_thread;
    atomic_bool                    running;
    pthread_mutex_t                cb_lock;
    callback_entry_t              *callbacks;      /* head of linked list */
    plugin_handle_t               *plugins;        /* loaded .so’s        */
    EVP_PKEY                      *governance_pub; /* public key for signature verification */
} event_handler_t;


/* ------------------------------------------------------------------------- *
 * Forward Declarations                                                      *
 * ------------------------------------------------------------------------- */
static void  *consumer_loop(void *arg);
static bool   verify_event_signature(const json_t *root, EVP_PKEY *pubkey);
static int    dispatch_event(event_handler_t *handler,
                             const char *type,
                             const json_t *payload);
static void   free_callback_list(callback_entry_t *head);
static void   free_plugin_list(plugin_handle_t *head);
static void   drain_queue(rd_kafka_t *rk);


/* ------------------------------------------------------------------------- *
 * Utility — LOG                                                             *
 * ------------------------------------------------------------------------- */

#define LOG_PREFIX "[Governance-Hall/EventHandler] "
#define LOG_ERROR(fmt, ...)  fprintf(stderr, LOG_PREFIX "ERROR: " fmt "\n", ##__VA_ARGS__)
#define LOG_WARN(fmt, ...)   fprintf(stderr, LOG_PREFIX "WARN:  " fmt "\n", ##__VA_ARGS__)
#define LOG_INFO(fmt, ...)   fprintf(stdout, LOG_PREFIX "INFO:  " fmt "\n", ##__VA_ARGS__)
#define LOG_DEBUG(fmt, ...)  fprintf(stdout, LOG_PREFIX "DEBUG: " fmt "\n", ##__VA_ARGS__)

/* ------------------------------------------------------------------------- *
 * Event Handler API                                                         *
 * ------------------------------------------------------------------------- */

/* Global singleton (for signal handling) */
static event_handler_t g_handler;

/**
 * Load an OpenSSL EVP_PKEY (PEM) public key from file.
 */
static EVP_PKEY *load_public_key(const char *filepath)
{
    FILE *fp = fopen(filepath, "r");
    if (!fp) {
        LOG_ERROR("Unable to open public key file %s: %s",
                  filepath, strerror(errno));
        return NULL;
    }
    EVP_PKEY *key = PEM_read_PUBKEY(fp, NULL, NULL, NULL);
    fclose(fp);

    if (!key)
        LOG_ERROR("PEM_read_PUBKEY failed.");

    return key;
}

/**
 * Register callback for given event_type.
 */
int event_handler_register(const char      *event_type,
                           event_callback_fn cb,
                           void             *user_data)
{
    if (!event_type || !cb) return -EINVAL;

    callback_entry_t *entry = malloc(sizeof *entry);
    if (!entry) return -ENOMEM;

    entry->event_type = strdup(event_type);
    entry->cb         = cb;
    entry->user_data  = user_data;
    entry->next       = NULL;

    pthread_mutex_lock(&g_handler.cb_lock);

    /* Prepend */
    entry->next       = g_handler.callbacks;
    g_handler.callbacks = entry;

    pthread_mutex_unlock(&g_handler.cb_lock);

    LOG_INFO("Registered callback for event type '%s'", event_type);
    return 0;
}

/**
 * Dynamically load a governance plug-in (.so). The plug-in’s init
 * function must look like:
 *     int plugin_init(event_handler_register_fn reg);
 */
typedef int (*plugin_init_fn)(int (*reg)(const char *,
                                         event_callback_fn,
                                         void *));

static int load_plugin(const char *path)
{
    void *handle = dlopen(path, RTLD_NOW);
    if (!handle) {
        LOG_ERROR("dlopen(%s) failed: %s", path, dlerror());
        return -EINVAL;
    }

    plugin_init_fn init = (plugin_init_fn)dlsym(handle, "plugin_init");
    if (!init) {
        LOG_ERROR("Symbol 'plugin_init' missing in %s: %s", path, dlerror());
        dlclose(handle);
        return -EINVAL;
    }

    int rc = init(event_handler_register);
    if (rc != 0) {
        LOG_ERROR("plugin_init failed for %s (rc=%d)", path, rc);
        dlclose(handle);
        return rc;
    }

    plugin_handle_t *ph = calloc(1, sizeof *ph);
    ph->dl_handle = handle;
    ph->next      = NULL;

    ph->next           = g_handler.plugins;
    g_handler.plugins  = ph;

    LOG_INFO("Plug-in %s loaded.", path);
    return 0;
}

/**
 * Initialize Kafka and spawn consumer thread.
 */
int event_handler_start(const char *brokers,
                        const char *group_id,
                        const char *topics_csv,
                        const char *pubkey_path,
                        const char *plugins_csv)
{
    memset(&g_handler, 0, sizeof g_handler);
    pthread_mutex_init(&g_handler.cb_lock, NULL);

    /* ------------------------------------------------------------------ *
     * Load governance public key                                         *
     * ------------------------------------------------------------------ */
    g_handler.governance_pub = load_public_key(pubkey_path);
    if (!g_handler.governance_pub)
        return -EIO;

    /* ------------------------------------------------------------------ *
     * Kafka Conf                                                         *
     * ------------------------------------------------------------------ */
    char errstr[512];
    g_handler.rk_conf = rd_kafka_conf_new();

    if (rd_kafka_conf_set(g_handler.rk_conf, "bootstrap.servers",
                          brokers, errstr, sizeof errstr) != RD_KAFKA_CONF_OK) {
        LOG_ERROR("rd_kafka_conf_set: %s", errstr);
        return -EINVAL;
    }

    if (rd_kafka_conf_set(g_handler.rk_conf, "group.id",
                          group_id, errstr, sizeof errstr) != RD_KAFKA_CONF_OK) {
        LOG_ERROR("rd_kafka_conf_set: %s", errstr);
        return -EINVAL;
    }

    /* Enable auto-commit */
    rd_kafka_conf_set(g_handler.rk_conf, "enable.auto.commit", "true", NULL, 0);

    /* ------------------------------------------------------------------ *
     * Create consumer instance                                           *
     * ------------------------------------------------------------------ */
    g_handler.rk = rd_kafka_new(RD_KAFKA_CONSUMER,
                                g_handler.rk_conf,
                                errstr, sizeof errstr);
    if (!g_handler.rk) {
        LOG_ERROR("Failed to create Kafka consumer: %s", errstr);
        return -EINVAL;
    }

    rd_kafka_poll_set_consumer(g_handler.rk);

    /* ------------------------------------------------------------------ *
     * Topics                                                             *
     * ------------------------------------------------------------------ */
    g_handler.sub_topics = rd_kafka_topic_partition_list_new(8);
    char *topics_dup = strdup(topics_csv);
    char *saveptr = NULL;
    for (char *tok = strtok_r(topics_dup, ",", &saveptr);
         tok != NULL;
         tok = strtok_r(NULL, ",", &saveptr)) {
        rd_kafka_topic_partition_list_add(g_handler.sub_topics, tok, RD_KAFKA_PARTITION_UA);
    }
    free(topics_dup);

    if (rd_kafka_subscribe(g_handler.rk, g_handler.sub_topics)) {
        LOG_ERROR("Failed to subscribe to topics");
        return -EINVAL;
    }

    /* ------------------------------------------------------------------ *
     * Load plug-ins                                                      *
     * ------------------------------------------------------------------ */
    if (plugins_csv && *plugins_csv) {
        char *dup = strdup(plugins_csv);
        char *sp  = NULL;
        for (char *tok = strtok_r(dup, ",", &sp);
             tok != NULL;
             tok = strtok_r(NULL, ",", &sp)) {
            load_plugin(tok);
        }
        free(dup);
    }

    /* ------------------------------------------------------------------ *
     * Spawn consumer thread                                              *
     * ------------------------------------------------------------------ */
    g_handler.running = true;
    if (pthread_create(&g_handler.consumer_thread, NULL,
                       consumer_loop, &g_handler) != 0) {
        LOG_ERROR("Failed to spawn consumer thread");
        return -errno;
    }

    LOG_INFO("Governance event handler started.");
    return 0;
}

/**
 * Stop consumer thread and clean up.
 */
void event_handler_stop(void)
{
    if (!g_handler.running) return;

    g_handler.running = false;
    pthread_join(g_handler.consumer_thread, NULL);

    drain_queue(g_handler.rk);
    rd_kafka_consumer_close(g_handler.rk);
    rd_kafka_destroy(g_handler.rk);

    free_callback_list(g_handler.callbacks);
    free_plugin_list(g_handler.plugins);
    rd_kafka_topic_partition_list_destroy(g_handler.sub_topics);

    if (g_handler.governance_pub)
        EVP_PKEY_free(g_handler.governance_pub);

    pthread_mutex_destroy(&g_handler.cb_lock);

    LOG_INFO("Governance event handler stopped.");
}

/* ------------------------------------------------------------------------- *
 * Consumer thread                                                           *
 * ------------------------------------------------------------------------- */

static void *consumer_loop(void *arg)
{
    event_handler_t *handler = arg;
    const int timeout_ms = 500;

    while (handler->running) {
        rd_kafka_message_t *rkmsg = rd_kafka_consumer_poll(handler->rk,
                                                           timeout_ms);
        if (!rkmsg) continue;

        if (rkmsg->err) {
            if (rkmsg->err == RD_KAFKA_RESP_ERR__PARTITION_EOF) {
                rd_kafka_message_destroy(rkmsg);
                continue;
            }
            LOG_WARN("Kafka error: %s", rd_kafka_message_errstr(rkmsg));
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        /* Parse message as JSON */
        json_error_t jerr;
        json_t *root = json_loadb((const char *)rkmsg->payload,
                                  rkmsg->len, 0, &jerr);
        if (!root) {
            LOG_WARN("JSON parse error at line %d: %s", jerr.line, jerr.text);
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        /* Validate schema */
        json_t *type_js = json_object_get(root, "type");
        json_t *payload = json_object_get(root, "payload");
        json_t *sig     = json_object_get(root, "sig");
        json_t *ts      = json_object_get(root, "timestamp");

        if (!json_is_string(type_js) || !json_is_object(payload) ||
            !json_is_string(sig)     || !json_is_integer(ts)) {
            LOG_WARN("Invalid event schema, dropping.");
            json_decref(root);
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        /* Cryptographic validation */
        if (!verify_event_signature(root, handler->governance_pub)) {
            LOG_WARN("Signature verification failed, dropping event.");
            json_decref(root);
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        /* Dispatch */
        const char *type_str = json_string_value(type_js);
        dispatch_event(handler, type_str, payload);

        json_decref(root);
        rd_kafka_message_destroy(rkmsg);
    }

    return NULL;
}

/* ------------------------------------------------------------------------- *
 * Dispatch                                                                  *
 * ------------------------------------------------------------------------- */

static int dispatch_event(event_handler_t *handler,
                          const char *type,
                          const json_t *payload)
{
    int rc_tot = 0;
    pthread_mutex_lock(&handler->cb_lock);

    for (callback_entry_t *it = handler->callbacks; it; it = it->next) {
        if (strcmp(it->event_type, type) == 0) {
            int rc = it->cb(type, payload, it->user_data);
            if (rc != 0) {
                LOG_WARN("Callback for '%s' returned %d", type, rc);
            }
            rc_tot |= rc;
        }
    }

    pthread_mutex_unlock(&handler->cb_lock);

    if (rc_tot == 0)
        LOG_DEBUG("Event '%s' processed successfully.", type);
    else
        LOG_WARN("Event '%s' processed with rc=%d.", type, rc_tot);

    return rc_tot;
}

/* ------------------------------------------------------------------------- *
 * Signature Verification                                                    *
 * ------------------------------------------------------------------------- */

/* Canonicalize event by serializing `type`+`payload`+`timestamp` */
static char *canonicalize_event(const json_t *root, size_t *out_len)
{
    json_t *type     = json_object_get(root, "type");
    json_t *payload  = json_object_get(root, "payload");
    json_t *ts       = json_object_get(root, "timestamp");

    /* Build new object in predictable order */
    json_t *canon = json_pack("{s:o,s:o,s:o}",
                              "type", type,
                              "payload", payload,
                              "timestamp", ts);

    char *dump = json_dumps(canon, JSON_COMPACT|JSON_SORT_KEYS);
    *out_len = strlen(dump);
    json_decref(canon);
    return dump;
}

static bool verify_event_signature(const json_t *root, EVP_PKEY *pubkey)
{
    json_t *sig_js = json_object_get(root, "sig");
    if (!json_is_string(sig_js)) return false;

    const char *sig_b64 = json_string_value(sig_js);
    size_t sig_len = 0;

    /* Base64 decode */
    BIO *b64 = BIO_new(BIO_f_base64());
    BIO_set_flags(b64, BIO_FLAGS_BASE64_NO_NL);
    BIO *mem = BIO_new_mem_buf(sig_b64, -1);
    BIO_push(b64, mem);

    uint8_t sig_buf[512]; /* Should accommodate 4096-bit RSA */
    sig_len = BIO_read(b64, sig_buf, sizeof sig_buf);
    BIO_free_all(b64);

    if (sig_len <= 0) {
        LOG_WARN("Signature base64 decode failed");
        return false;
    }

    size_t msg_len = 0;
    char *msg = canonicalize_event(root, &msg_len);

    bool ok = false;
    EVP_MD_CTX *mdctx = EVP_MD_CTX_new();
    if (EVP_DigestVerifyInit(mdctx, NULL, EVP_sha256(), NULL, pubkey) == 1 &&
        EVP_DigestVerifyUpdate(mdctx, msg, msg_len) == 1 &&
        EVP_DigestVerifyFinal(mdctx, sig_buf, sig_len) == 1) {
        ok = true;
    }

    if (!ok) {
        LOG_WARN("EVP_DigestVerify failed: %s",
                 ERR_error_string(ERR_get_error(), NULL));
    }

    free(msg);
    EVP_MD_CTX_free(mdctx);
    return ok;
}

/* ------------------------------------------------------------------------- *
 * Helpers                                                                   *
 * ------------------------------------------------------------------------- */

static void free_callback_list(callback_entry_t *head)
{
    while (head) {
        callback_entry_t *next = head->next;
        free(head->event_type);
        free(head);
        head = next;
    }
}

static void free_plugin_list(plugin_handle_t *head)
{
    while (head) {
        plugin_handle_t *next = head->next;
        if (head->dl_handle)
            dlclose(head->dl_handle);
        free(head);
        head = next;
    }
}

static void drain_queue(rd_kafka_t *rk)
{
    LOG_INFO("Draining Kafka producer queue...");
    rd_kafka_flush(rk, 5000); /* wait up to 5 s */
}

/* ------------------------------------------------------------------------- *
 * Signal Handling                                                           *
 * ------------------------------------------------------------------------- */

static void sig_handler(int sig)
{
    (void)sig;
    LOG_INFO("Caught termination signal, shutting down...");
    event_handler_stop();
    exit(EXIT_SUCCESS);
}

static void install_signal_handlers(void)
{
    struct sigaction sa = {
        .sa_handler = sig_handler,
        .sa_flags   = 0
    };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
}

/* ------------------------------------------------------------------------- *
 * Main test harness (can be removed in production)                          *
 * ------------------------------------------------------------------------- */

#ifdef EVENT_HANDLER_STANDALONE
/* A minimal callback implementation */
static int on_vote_cast(const char *event_type,
                        const json_t *payload,
                        void *user_data)
{
    (void)user_data;
    char *dump = json_dumps(payload, JSON_INDENT(2));
    LOG_INFO("Received %s event:\n%s", event_type, dump);
    free(dump);
    return 0;
}

int main(void)
{
    const char *brokers = getenv("GOV_KAFKA_BROKERS") ?: "localhost:9092";
    const char *group   = getenv("GOV_KAFKA_GROUP_ID") ?: "gov-hall-local";
    const char *topics  = getenv("GOV_KAFKA_TOPICS") ?: "governance-events";
    const char *pubkey  = getenv("GOV_PUBKEY_FILE") ?: "./governance.pub.pem";

    install_signal_handlers();
    OpenSSL_add_all_algorithms();

    if (event_handler_register("VOTE_CAST", on_vote_cast, NULL) != 0) {
        LOG_ERROR("Failed to register default callback.");
        return EXIT_FAILURE;
    }

    if (event_handler_start(brokers, group, topics, pubkey, NULL) != 0) {
        LOG_ERROR("event_handler_start failed.");
        return EXIT_FAILURE;
    }

    /* Keep main thread alive */
    while (1) pause();

    /* never reached */
    return EXIT_SUCCESS;
}
#endif
```