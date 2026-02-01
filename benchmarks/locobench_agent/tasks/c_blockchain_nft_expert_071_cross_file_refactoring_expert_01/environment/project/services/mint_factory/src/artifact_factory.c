/**
 * HoloCanvas – Mint-Factory Microservice
 * -------------------------------------
 * artifact_factory.c
 *
 * Production-quality implementation of the Artifact Factory subsystem.  This unit
 * is responsible for validating incoming recipe fragments, composing them into a
 * canonical “creative recipe” JSON document, generating a deterministic SHA-256
 * identifier, persisting the artifact to LedgerCore, and emitting the appropriate
 * event onto the service event mesh.
 *
 * Author: HoloCanvas Core Team
 * License: Apache-2.0
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <string.h>
#include <time.h>
#include <pthread.h>
#include <errno.h>

#include <openssl/sha.h>
#include <cjson/cJSON.h>

/*--- External service stubs (implemented elsewhere in the project) ----------*/
#include "ledger_client.h"      /* LedgerCore L2 roll-up client                */
#include "event_bus.h"          /* Kafka / gRPC event mesh abstraction         */
#include "artifact_factory.h"   /* Public interface for this compilation unit  */
#include "hc_logging.h"         /* Centralised logging facade                  */

/*---------------------------------------------------------------------------*/
/* Internal constants                                                        */
/*---------------------------------------------------------------------------*/

#define ARTIFACT_ID_HEX_SIZE (SHA256_DIGEST_LENGTH * 2 + 1)
#define MAX_CREATOR_ADDR     96   /* Enough for bech32 or hex-encoded address */

/*---------------------------------------------------------------------------*/
/* Local data types                                                          */
/*---------------------------------------------------------------------------*/

/* Life-cycle states—the canonical definition sits in shared headers */
typedef enum
{
    ART_STATE_DRAFT = 0,
    ART_STATE_CURATED,
    ART_STATE_AUCTION,
    ART_STATE_FRACTIONALIZED,
    ART_STATE_STAKED
} artifact_state_e;

/* A single creative recipe fragment set */
typedef struct
{
    char *shader;    /* GLSL / WGSL fragment */
    char *audio;     /* PureData │ Faust │ WebAudio Graph JSON */
    char *metadata;  /* RFC 8259-compliant JSON */
} artifact_fragments_t;

/* Fully-fledged artifact object */
typedef struct
{
    char                id[ARTIFACT_ID_HEX_SIZE];
    artifact_fragments_t recipe;
    char                creator[MAX_CREATOR_ADDR];
    artifact_state_e    state;
    time_t              created_at;
} artifact_t;

/* Factory-wide runtime state */
typedef struct
{
    pthread_mutex_t lock;
    bool            initialised;
    /* ... future cache handles, metrics, etc. */
} factory_ctx_t;

/*---------------------------------------------------------------------------*/
/* Static (translation-unit local) members                                   */
/*---------------------------------------------------------------------------*/

static factory_ctx_t g_ctx = {
    .lock        = PTHREAD_MUTEX_INITIALIZER,
    .initialised = false
};

/*---------------------------------------------------------------------------*/
/* Forward declarations                                                      */
/*---------------------------------------------------------------------------*/

static bool validate_fragments(const artifact_fragments_t *fr);
static cJSON *compose_recipe_json(const artifact_fragments_t *fr);
static void   sha256_hex(const char *input, size_t len, char out_hex[ARTIFACT_ID_HEX_SIZE]);
static bool   persist_to_ledger(const char *artifact_id, const char *recipe_json);
static void   emit_event_artifact_minted(const artifact_t *artifact);

/*---------------------------------------------------------------------------*/
/* Public API implementation                                                 */
/*---------------------------------------------------------------------------*/

/**
 * Initialise the Artifact Factory.  Must be called exactly once during
 * service bootstrap.  Thread safe.
 */
af_status_e af_init(void)
{
    int rc;

    pthread_mutex_lock(&g_ctx.lock);

    if (g_ctx.initialised)
    {
        pthread_mutex_unlock(&g_ctx.lock);
        return AF_STATUS_OK; /* Idempotent */
    }

    /* Initialise external subsystems */
    if ((rc = ledger_client_init()) != 0)
    {
        HC_LOG_ERROR("artifact_factory: ledger_client_init() failed: %d", rc);
        pthread_mutex_unlock(&g_ctx.lock);
        return AF_STATUS_ERR_DEPENDENCY;
    }

    if ((rc = event_bus_init()) != 0)
    {
        HC_LOG_ERROR("artifact_factory: event_bus_init() failed: %d", rc);
        pthread_mutex_unlock(&g_ctx.lock);
        return AF_STATUS_ERR_DEPENDENCY;
    }

    g_ctx.initialised = true;
    pthread_mutex_unlock(&g_ctx.lock);

    HC_LOG_INFO("artifact_factory: initialised successfully");
    return AF_STATUS_OK;
}

/**
 * Tear down the Artifact Factory.
 */
void af_shutdown(void)
{
    pthread_mutex_lock(&g_ctx.lock);

    if (!g_ctx.initialised)
    {
        pthread_mutex_unlock(&g_ctx.lock);
        return;
    }

    ledger_client_shutdown();
    event_bus_shutdown();

    g_ctx.initialised = false;
    pthread_mutex_unlock(&g_ctx.lock);
    HC_LOG_INFO("artifact_factory: shutdown complete");
}

/**
 * Mint a new generative artifact.  Ownership of dynamically allocated
 * strings inside `fragments` is transferred to the factory on success.
 *
 * Parameters:
 *  - fragments     : Pointer to caller-allocated fragment bundle
 *  - creator_addr  : Null-terminated creator wallet address
 *  - out_artifact_id (optional): Buffer receiving generated ID (hex-string)
 *
 * Returns:
 *  AF_STATUS_OK on success, otherwise error code.
 */
af_status_e af_mint(const artifact_fragments_t *fragments,
                    const char                 *creator_addr,
                    char                       *out_artifact_id /* Nullable */)
{
    if (!g_ctx.initialised)
    {
        HC_LOG_ERROR("artifact_factory: must call af_init() first");
        return AF_STATUS_ERR_NOT_INIT;
    }

    if (!fragments || !creator_addr)
    {
        HC_LOG_ERROR("artifact_factory: invalid argument (null ptr)");
        return AF_STATUS_ERR_INVALID_ARG;
    }

    if (!validate_fragments(fragments))
    {
        HC_LOG_WARN("artifact_factory: fragment validation failed");
        return AF_STATUS_ERR_VALIDATION;
    }

    /* Compose canonical JSON recipe */
    cJSON *recipe_json = compose_recipe_json(fragments);
    if (!recipe_json)
    {
        HC_LOG_ERROR("artifact_factory: failed to compose JSON recipe");
        return AF_STATUS_ERR_INTERNAL;
    }

    char *recipe_str = cJSON_PrintUnformatted(recipe_json);
    cJSON_Delete(recipe_json);
    if (!recipe_str)
    {
        HC_LOG_ERROR("artifact_factory: cJSON_PrintUnformatted() failed");
        return AF_STATUS_ERR_OOM;
    }

    /* Derive deterministic ID */
    char artifact_id[ARTIFACT_ID_HEX_SIZE];
    sha256_hex(recipe_str, strlen(recipe_str), artifact_id);

    /* Persist recipe to LedgerCore */
    if (!persist_to_ledger(artifact_id, recipe_str))
    {
        HC_LOG_ERROR("artifact_factory: failed to persist artifact to ledger");
        free(recipe_str);
        return AF_STATUS_ERR_DEPENDENCY;
    }

    /* Construct runtime artifact object (stack-allocated) for event emission */
    artifact_t artifact = {
        .state      = ART_STATE_DRAFT,
        .created_at = time(NULL)
    };
    strncpy(artifact.id, artifact_id, sizeof(artifact.id));
    strncpy(artifact.creator, creator_addr, sizeof(artifact.creator) - 1);
    artifact.recipe.shader   = fragments->shader   ? strdup(fragments->shader)   : NULL;
    artifact.recipe.audio    = fragments->audio    ? strdup(fragments->audio)    : NULL;
    artifact.recipe.metadata = fragments->metadata ? strdup(fragments->metadata) : NULL;

    /* Emit event into mesh */
    emit_event_artifact_minted(&artifact);

    /* Populate output */
    if (out_artifact_id)
        strcpy(out_artifact_id, artifact_id);

    /* Clean up */
    free(artifact.recipe.shader);
    free(artifact.recipe.audio);
    free(artifact.recipe.metadata);
    free(recipe_str);

    HC_LOG_INFO("artifact_factory: successfully minted artifact %s", artifact_id);
    return AF_STATUS_OK;
}

/*---------------------------------------------------------------------------*/
/* Internal helpers                                                          */
/*---------------------------------------------------------------------------*/

/**
 * Basic heuristic validation of recipe fragments.
 * In production this would call out to a sandboxed compiler / linter.
 */
static bool validate_fragments(const artifact_fragments_t *fr)
{
    if (!fr->shader || !fr->metadata)
        return false; /* Mandatory fields */

    /* Size checks (prevent DoS memory bombs) */
    size_t shader_len   = strlen(fr->shader);
    size_t audio_len    = fr->audio ? strlen(fr->audio) : 0;
    size_t metadata_len = strlen(fr->metadata);

    if (shader_len   > 64 * 1024   /* 64 kB */
        || audio_len > 128 * 1024  /* 128 kB */
        || metadata_len > 16 * 1024) /* 16 kB */
    {
        return false;
    }

    /* Metadata must be valid JSON */
    cJSON *meta = cJSON_Parse(fr->metadata);
    if (!meta)
        return false;
    cJSON_Delete(meta);

    /* TODO: syntax check shader & audio; omitted here for brevity */

    return true;
}

/**
 * Compose the canonical recipe JSON object from individual fragments.
 * Caller must free returned cJSON with cJSON_Delete().
 */
static cJSON *compose_recipe_json(const artifact_fragments_t *fr)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;

    cJSON_AddItemToObject(root, "shader_fragment",
                          fr->shader ? cJSON_CreateString(fr->shader) : cJSON_CreateNull());
    cJSON_AddItemToObject(root, "audio_fragment",
                          fr->audio ? cJSON_CreateString(fr->audio) : cJSON_CreateNull());

    /* Metadata fragment is already JSON—parse and embed to maintain types */
    cJSON *meta = cJSON_Parse(fr->metadata);
    if (meta)
    {
        cJSON_AddItemToObject(root, "metadata_fragment", meta);
    }
    else
    {
        /* Fallback as raw string to avoid data loss */
        cJSON_AddItemToObject(root, "metadata_fragment",
                              cJSON_CreateString(fr->metadata ? fr->metadata : ""));
    }

    return root;
}

/**
 * Compute SHA-256 digest and return as lowercase hex string.
 */
static void sha256_hex(const char *input, size_t len, char out_hex[ARTIFACT_ID_HEX_SIZE])
{
    unsigned char hash[SHA256_DIGEST_LENGTH];
    SHA256((const unsigned char *)input, len, hash);

    for (int i = 0; i < SHA256_DIGEST_LENGTH; ++i)
        sprintf(out_hex + (i * 2), "%02x", hash[i]);

    out_hex[ARTIFACT_ID_HEX_SIZE - 1] = '\0';
}

/**
 * Persist artifact recipe into LedgerCore.  Wraps ledger_client API.
 */
static bool persist_to_ledger(const char *artifact_id, const char *recipe_json)
{
    ledger_record_t record = {
        .key        = (char *)artifact_id,
        .value      = (char *)recipe_json,
        .topic      = LEDGER_TOPIC_ARTIFACTS
    };
    int rc = ledger_client_put(&record);
    return (rc == 0);
}

/**
 * Emit an “ArtifactMinted” domain event to the mesh.
 */
static void emit_event_artifact_minted(const artifact_t *artifact)
{
    cJSON *evt = cJSON_CreateObject();
    if (!evt) return;

    cJSON_AddStringToObject(evt, "event_type", "ArtifactMinted");
    cJSON_AddStringToObject(evt, "artifact_id", artifact->id);
    cJSON_AddStringToObject(evt, "creator", artifact->creator);
    cJSON_AddNumberToObject(evt, "timestamp", (double)artifact->created_at);

    char *payload = cJSON_PrintUnformatted(evt);
    if (!payload)
    {
        cJSON_Delete(evt);
        return;
    }

    event_msg_t msg = {
        .topic   = "artifact.events",
        .payload = payload,
        .length  = strlen(payload)
    };

    if (event_bus_publish(&msg) != 0)
        HC_LOG_WARN("artifact_factory: failed to publish ArtifactMinted event");

    free(payload);
    cJSON_Delete(evt);
}

/*---------------------------------------------------------------------------*/
/* Logging helpers (variadic wrappers)                                       */
/*---------------------------------------------------------------------------*/
/* The hc_logging.h facade provides macros.  No implementation required here. */

/*---------------------------------------------------------------------------*/
/* End of file                                                               */
/*---------------------------------------------------------------------------*/
