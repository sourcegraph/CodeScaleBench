/*
 * recipe_composer.c
 *
 * HoloCanvas – Mint-Factory Microservice
 * --------------------------------------
 * Creates an immutable “creative recipe” for a to-be-minted artifact by
 * composing user-submitted fragments (GLSL shader code, audio buffers,
 * arbitrary metadata) into a canonical JSON document. The finalized recipe
 * is hashed (SHA-256) and persisted to durable storage (e.g. roll-up chain,
 * IPFS, Cold-DB) while an event is emitted to the mesh for downstream
 * consumers (LedgerCore, Gallery-Gateway, etc.).
 *
 * This module focuses on the composition, hashing, validation, persistence
 * (filesystem-backed for now), and event-publication stubs.
 *
 * Dependencies:
 *   – OpenSSL libcrypto (SHA-256)
 *   – cJSON             (JSON construction)
 *   – librdkafka        (Kafka producer)       [compile-time option]
 *
 * Compile example:
 *   gcc -Wall -Wextra -O2 \
 *       -DUSE_KAFKA \
 *       recipe_composer.c -lcjson -lcrypto -lpthread -lrdkafka -o recipe_composer
 *
 * Author:  HoloCanvas Core Team
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdarg.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include <pthread.h>
#include <sys/stat.h>

#include <openssl/sha.h>
#include <cjson/cJSON.h>

#ifdef USE_KAFKA
#include <rdkafka.h>
#endif

/* ---------- Constants & Macros ------------------------------------------ */

#define RC_OK                   (0)
#define RC_ERR_GENERIC          (-1)
#define RC_ERR_OOM              (-2)
#define RC_ERR_INVALID_ARG      (-3)
#define RC_ERR_IO               (-4)
#define RC_ERR_JSON             (-5)
#define RC_ERR_STATE            (-6)

#define UNUSED(x)               (void)(x)

#define SHA256_HEX_LENGTH       (SHA256_DIGEST_LENGTH * 2)

/* ---------- Typedefs ---------------------------------------------------- */

typedef enum {
    FRAG_SHADER,
    FRAG_AUDIO,
    FRAG_METADATA,
    FRAG_UNKNOWN
} fragment_type_e;

typedef struct {
    fragment_type_e   type;
    char             *id;        /* user-supplied fragment ID */
    char             *content;   /* raw content */
    size_t            content_sz;
} recipe_fragment_t;

typedef struct {
    char               *artifact_id;
    char               *author_wallet;
    recipe_fragment_t **fragments;
    size_t              frag_count;
    size_t              frag_capacity;
    pthread_mutex_t     lock;
    bool                finalized;
    char                sha256_hex[SHA256_HEX_LENGTH + 1]; /* null-terminated */
} recipe_composer_t;

/* ---------- Forward Declarations --------------------------------------- */

static int  rc_log_err(int rc, const char *fmt, ...);
static void rc_free_fragment(recipe_fragment_t *frag);
static int  rc_expand_frag_array(recipe_composer_t *rc);

/* ---------- Public API -------------------------------------------------- */

/*
 * rc_create()
 * Initializes a new recipe composer context.
 */
recipe_composer_t *
rc_create(const char *artifact_id, const char *author_wallet)
{
    if (!artifact_id || !author_wallet) {
        rc_log_err(RC_ERR_INVALID_ARG, "artifact_id and author_wallet required");
        return NULL;
    }

    recipe_composer_t *rc = calloc(1, sizeof(*rc));
    if (!rc) {
        rc_log_err(RC_ERR_OOM, "calloc failed");
        return NULL;
    }

    rc->artifact_id   = strdup(artifact_id);
    rc->author_wallet = strdup(author_wallet);
    rc->frag_capacity = 8; /* start with modest capacity */
    rc->fragments     = calloc(rc->frag_capacity, sizeof(recipe_fragment_t *));
    if (!rc->artifact_id || !rc->author_wallet || !rc->fragments) {
        rc_log_err(RC_ERR_OOM, "calloc/strdup failed");
        free(rc->artifact_id);
        free(rc->author_wallet);
        free(rc->fragments);
        free(rc);
        return NULL;
    }

    pthread_mutex_init(&rc->lock, NULL);
    return rc;
}

/*
 * rc_destroy()
 * Frees all resources associated with the composer.
 */
void
rc_destroy(recipe_composer_t *rc)
{
    if (!rc) return;

    for (size_t i = 0; i < rc->frag_count; ++i)
        rc_free_fragment(rc->fragments[i]);

    free(rc->fragments);
    free(rc->artifact_id);
    free(rc->author_wallet);
    pthread_mutex_destroy(&rc->lock);
    free(rc);
}

/*
 * rc_add_fragment()
 * Adds a fragment to the recipe. Ownership of `content` is transferred to the
 * composer on success (caller must malloc it).
 */
int
rc_add_fragment(recipe_composer_t *rc,
                fragment_type_e type,
                const char     *fragment_id,
                char           *content,
                size_t          content_sz)
{
    if (!rc || !fragment_id || !content || content_sz == 0)
        return rc_log_err(RC_ERR_INVALID_ARG,
                          "add_fragment() invalid arguments");

    pthread_mutex_lock(&rc->lock);

    if (rc->finalized) {
        pthread_mutex_unlock(&rc->lock);
        return rc_log_err(RC_ERR_STATE,
                          "cannot add fragment: recipe already finalized");
    }

    /* Capacity expansion if needed */
    if (rc->frag_count >= rc->frag_capacity &&
        rc_expand_frag_array(rc) != RC_OK) {
        pthread_mutex_unlock(&rc->lock);
        return rc_log_err(RC_ERR_OOM, "expanding fragment array failed");
    }

    recipe_fragment_t *frag = calloc(1, sizeof(*frag));
    if (!frag) {
        pthread_mutex_unlock(&rc->lock);
        return rc_log_err(RC_ERR_OOM, "calloc failed");
    }
    frag->type       = type;
    frag->id         = strdup(fragment_id);
    frag->content    = content;       /* take ownership */
    frag->content_sz = content_sz;

    if (!frag->id) {
        rc_free_fragment(frag);
        pthread_mutex_unlock(&rc->lock);
        return rc_log_err(RC_ERR_OOM, "strdup failed");
    }

    rc->fragments[rc->frag_count++] = frag;
    pthread_mutex_unlock(&rc->lock);
    return RC_OK;
}

/*
 * rc_finalize()
 * Assembles JSON, computes SHA-256, persists to disk, and emits Kafka event.
 */
int
rc_finalize(recipe_composer_t *rc,
            const char *storage_path,   /* directory for recipe JSON */
            const char *kafka_topic)    /* optional, NULL to skip */
{
    if (!rc || !storage_path)
        return rc_log_err(RC_ERR_INVALID_ARG, "finalize() invalid arguments");

    pthread_mutex_lock(&rc->lock);
    if (rc->finalized) {
        pthread_mutex_unlock(&rc->lock);
        return rc_log_err(RC_ERR_STATE, "recipe already finalized");
    }

    /* -------------------- Build JSON -------------------- */
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        pthread_mutex_unlock(&rc->lock);
        return rc_log_err(RC_ERR_JSON, "failed to create JSON root");
    }

    cJSON_AddStringToObject(root, "artifact_id", rc->artifact_id);
    cJSON_AddStringToObject(root, "author_wallet", rc->author_wallet);

    char iso8601[32] = {0};
    time_t now = time(NULL);
    strftime(iso8601, sizeof iso8601, "%Y-%m-%dT%H:%M:%SZ", gmtime(&now));
    cJSON_AddStringToObject(root, "timestamp", iso8601);

    cJSON *frag_arr = cJSON_AddArrayToObject(root, "fragments");
    if (!frag_arr) {
        cJSON_Delete(root);
        pthread_mutex_unlock(&rc->lock);
        return rc_log_err(RC_ERR_JSON, "failed to create JSON array");
    }

    for (size_t i = 0; i < rc->frag_count; ++i) {
        recipe_fragment_t *f = rc->fragments[i];
        cJSON *entry = cJSON_CreateObject();
        cJSON_AddStringToObject(entry, "id", f->id);

        switch (f->type) {
            case FRAG_SHADER:   cJSON_AddStringToObject(entry, "type", "shader");   break;
            case FRAG_AUDIO:    cJSON_AddStringToObject(entry, "type", "audio");    break;
            case FRAG_METADATA: cJSON_AddStringToObject(entry, "type", "metadata"); break;
            default:            cJSON_AddStringToObject(entry, "type", "unknown");  break;
        }
        /* Content is stored as base64 to keep JSON/text-safe */
        char *b64 = NULL;
        size_t b64_len = 0;
        {
            /* --- simplistic Base64 encoding using OpenSSL BIO --- */
            BIO *bio, *b64f;
            BUF_MEM *buffer_ptr = NULL;

            b64f = BIO_new(BIO_f_base64());
            bio  = BIO_new(BIO_s_mem());
            b64f = BIO_push(b64f, bio);

            BIO_set_flags(b64f, BIO_FLAGS_BASE64_NO_NL);
            BIO_write(b64f, f->content, (int)f->content_sz);
            BIO_flush(b64f);
            BIO_get_mem_ptr(b64f, &buffer_ptr);

            b64 = malloc(buffer_ptr->length + 1);
            if (b64) {
                memcpy(b64, buffer_ptr->data, buffer_ptr->length);
                b64[buffer_ptr->length] = 0;
                b64_len = buffer_ptr->length;
            }
            BIO_free_all(b64f);
        }

        if (!b64) {
            cJSON_Delete(root);
            pthread_mutex_unlock(&rc->lock);
            return rc_log_err(RC_ERR_OOM, "base64 encoding failed");
        }

        cJSON_AddStringToObject(entry, "content_b64", b64);
        free(b64);
        cJSON_AddItemToArray(frag_arr, entry);
    }

    char *json_text = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!json_text) {
        pthread_mutex_unlock(&rc->lock);
        return rc_log_err(RC_ERR_JSON, "cJSON_Print failed");
    }

    /* -------------------- Compute SHA-256 -------------------- */
    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256((unsigned char *)json_text, strlen(json_text), digest);

    for (int i = 0; i < SHA256_DIGEST_LENGTH; ++i)
        sprintf(rc->sha256_hex + (i * 2), "%02x", digest[i]);

    /* -------------------- Persist to storage -------------------- */
    if (mkdir(storage_path, 0755) != 0 && errno != EEXIST) {
        free(json_text);
        pthread_mutex_unlock(&rc->lock);
        return rc_log_err(RC_ERR_IO, "mkdir '%s' failed: %s",
                          storage_path, strerror(errno));
    }

    char file_path[1024];
    snprintf(file_path, sizeof file_path, "%s/%s.json", storage_path,
             rc->sha256_hex);

    FILE *fp = fopen(file_path, "w");
    if (!fp) {
        free(json_text);
        pthread_mutex_unlock(&rc->lock);
        return rc_log_err(RC_ERR_IO, "fopen '%s' failed: %s",
                          file_path, strerror(errno));
    }

    if (fwrite(json_text, 1, strlen(json_text), fp)
        != strlen(json_text)) {
        fclose(fp);
        unlink(file_path);
        free(json_text);
        pthread_mutex_unlock(&rc->lock);
        return rc_log_err(RC_ERR_IO, "fwrite failed");
    }
    fclose(fp);

    /* -------------------- Emit event -------------------- */
#ifdef USE_KAFKA
    if (kafka_topic) {
        char errstr[512];
        rd_kafka_conf_t *conf = rd_kafka_conf_new();
        rd_kafka_conf_set(conf, "bootstrap.servers", "localhost:9092",
                          errstr, sizeof errstr);

        rd_kafka_t *rk = rd_kafka_new(RD_KAFKA_PRODUCER, conf,
                                      errstr, sizeof errstr);
        if (!rk) {
            rc_log_err(RC_ERR_GENERIC, "rd_kafka_new failed: %s", errstr);
        } else {
            rd_kafka_resp_err_t rerr;
            rerr = rd_kafka_producev(
                rk,
                RD_KAFKA_V_TOPIC(kafka_topic),
                RD_KAFKA_V_VALUE(rc->sha256_hex, SHA256_HEX_LENGTH),
                RD_KAFKA_V_END);
            if (rerr)
                rc_log_err(RC_ERR_GENERIC, "kafka produce failed: %s",
                           rd_kafka_err2str(rerr));

            rd_kafka_flush(rk, 3000);
            rd_kafka_destroy(rk);
        }
    }
#else
    UNUSED(kafka_topic);
#endif

    /* mark finalized */
    rc->finalized = true;
    free(json_text);
    pthread_mutex_unlock(&rc->lock);
    return RC_OK;
}

/*
 * rc_get_sha256()
 * Returns the hex-encoded SHA-256 hash after finalize().
 */
const char *
rc_get_sha256(recipe_composer_t *rc)
{
    if (!rc || !rc->finalized) return NULL;
    return rc->sha256_hex;
}

/* ---------- Internal Helpers ------------------------------------------- */

static int
rc_log_err(int rc, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "[recipe_composer] ERROR: ");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
    return rc;
}

static void
rc_free_fragment(recipe_fragment_t *frag)
{
    if (!frag) return;
    free(frag->id);
    free(frag->content);
    free(frag);
}

static int
rc_expand_frag_array(recipe_composer_t *rc)
{
    size_t new_cap = rc->frag_capacity * 2;
    recipe_fragment_t **tmp =
        realloc(rc->fragments, new_cap * sizeof(recipe_fragment_t *));
    if (!tmp) return RC_ERR_OOM;
    rc->fragments = tmp;
    rc->frag_capacity = new_cap;
    return RC_OK;
}

/* ---------- Test Harness (optional) ------------------------------------ */
#ifdef RC_UNIT_TEST

static char *slurp_file(const char *path, size_t *out_sz);

int main(void)
{
    recipe_composer_t *rc = rc_create("artifact_123", "0xDEADBEEF");
    if (!rc) return EXIT_FAILURE;

    /* add dummy shader fragment */
    size_t sz = 0;
    char *shader = slurp_file("demo_shader.vert", &sz);
    if (!shader) return EXIT_FAILURE;
    rc_add_fragment(rc, FRAG_SHADER, "shader.vert", shader, sz);

    /* dummy audio buffer */
    char *audio = strdup("dummy_ogg_bytes");
    rc_add_fragment(rc, FRAG_AUDIO, "soundtrack.ogg",
                    audio, strlen(audio));

    /* finalize */
    if (rc_finalize(rc, "./recipes", "mint_recipes") != RC_OK) {
        rc_destroy(rc);
        return EXIT_FAILURE;
    }

    printf("Recipe SHA-256: %s\n", rc_get_sha256(rc));
    rc_destroy(rc);
    return EXIT_SUCCESS;
}

static char *
slurp_file(const char *path, size_t *out_sz)
{
    FILE *fp = fopen(path, "rb");
    if (!fp) {
        perror(path);
        return NULL;
    }
    fseek(fp, 0, SEEK_END);
    long len = ftell(fp);
    rewind(fp);

    char *buf = malloc(len);
    if (!buf) { fclose(fp); return NULL; }

    if (fread(buf, 1, len, fp) != (size_t)len) {
        perror("fread");
        free(buf);
        fclose(fp);
        return NULL;
    }
    fclose(fp);
    *out_sz = len;
    return buf;
}

#endif /* RC_UNIT_TEST */
