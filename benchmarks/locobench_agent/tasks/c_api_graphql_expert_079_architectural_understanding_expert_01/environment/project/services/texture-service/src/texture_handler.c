/**
 * SynestheticCanvas Texture Service
 * ---------------------------------
 * texture_handler.c
 *
 * Production-grade implementation of the TextureHandler API.  The handler
 * validates incoming texture requests, coordinates with the repository layer,
 * updates runtime metrics, and emits structured logs.  All public functions
 * are thread-safe and resilient to partial failures.
 *
 * NOTE: This compilation unit purposefully hides private implementation
 * details from the header, keeping the public surface minimal and stable.
 *
 * Dependencies (resolved through include-paths / pkg-config):
 *   - jansson          (JSON parsing / serialization)
 *   - pthread          (POSIX threading primitives)
 *   - uuid             (libuuid for unique IDs)
 *
 * Author: SynestheticCanvas Core Team
 * License: MIT
 */

#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <uuid/uuid.h>

#include <jansson.h>

#include "logger.h"              /* Project-local, syslog-backed logging wrapper */
#include "metrics.h"             /* Histogram / Counter helpers */
#include "texture_handler.h"     /* Corresponding public header */
#include "texture_repository.h"  /* Repository Pattern abstraction */
#include "validation.h"          /* Utility validators for inbound DTOs */

/* ────────────────────────────────────────────────────────────────────────── */
/* Internal Constants                                                       */
/* ────────────────────────────────────────────────────────────────────────── */

#define TEXTURE_ID_STRLEN 37           /* 36 bytes UUID + NUL */
#define MAX_TEXTURE_NAME_LEN 128
#define MAX_COLOR_PROFILE_LEN 32
#define JSON_SERIALIZATION_FLAGS (JSON_COMPACT | JSON_SORT_KEYS)

/* ────────────────────────────────────────────────────────────────────────── */
/* Private Helper Structs / Types                                           */
/* ────────────────────────────────────────────────────────────────────────── */

/* Guard state for thread-safe handler */
typedef struct
{
    TextureRepository *repo;       /* Injected storage adapter (non-null) */
    MetricsCollector  *metrics;    /* Global metrics sink (may be null)   */
    pthread_rwlock_t   lock;       /* Protects repository multi-step ops  */
    bool               ready;      /* Handler has been initialized        */
} TextureHandlerState;

/* Encoded error detail used for internal propagation */
typedef struct
{
    TextureErrorCode code;
    char             msg[256];
} TextureErrorDetail;

/* ────────────────────────────────────────────────────────────────────────── */
/* Local Forward Declarations                                               */
/* ────────────────────────────────────────────────────────────────────────── */

static void        _set_error(TextureError *out, TextureErrorCode code, const char *fmt, ...)
    __attribute__((format(printf, 3, 4)));
static bool        _validate_texture_input(const TextureInput *in, TextureError *err);
static char       *_generate_uuid(void);
static json_t     *_texture_to_json(const Texture *tx, TextureError *err);

/* ────────────────────────────────────────────────────────────────────────── */
/* Public API Implementation                                                */
/* ────────────────────────────────────────────────────────────────────────── */

TextureHandler *texture_handler_new(TextureRepository *repo, MetricsCollector *metrics, TextureError *err)
{
    if (repo == NULL)
    {
        _set_error(err, TX_ERR_INVALID_ARGUMENT, "TextureRepository instance cannot be NULL");
        return NULL;
    }

    TextureHandlerState *state = calloc(1, sizeof(TextureHandlerState));
    if (!state)
    {
        _set_error(err, TX_ERR_OOM, "Failed to allocate handler state: %s", strerror(errno));
        return NULL;
    }

    state->repo    = repo;
    state->metrics = metrics;
    state->ready   = false;

    if (pthread_rwlock_init(&state->lock, NULL) != 0)
    {
        _set_error(err, TX_ERR_INTERNAL, "Failed to initialize rwlock: %s", strerror(errno));
        free(state);
        return NULL;
    }

    state->ready = true;
    log_info("[texture-handler] Initialized successfully");

    return (TextureHandler *)state;
}

void texture_handler_dispose(TextureHandler *handler)
{
    if (!handler)
        return;

    TextureHandlerState *state = (TextureHandlerState *)handler;
    pthread_rwlock_destroy(&state->lock);
    /* Repository and metrics lifetime are managed by the caller */
    free(state);
}

/**
 * Create a new texture based on the DTO provided by higher layers. This
 * function validates all fields, generates an ID, persists the record, and
 * returns a deep-copied Texture object that the caller must free.
 */
Texture *texture_handler_create(TextureHandler *handler,
                                const TextureInput *input,
                                TextureError *err)
{
    TextureHandlerState *state = (TextureHandlerState *)handler;
    if (!state || !state->ready)
    {
        _set_error(err, TX_ERR_NOT_INITIALIZED, "TextureHandler is not initialized");
        return NULL;
    }

    /* Validate input first */
    if (!_validate_texture_input(input, err))
        return NULL;

    /* Build Texture domain object */
    Texture tx      = {0};
    tx.id           = _generate_uuid();
    tx.name         = strndup(input->name, MAX_TEXTURE_NAME_LEN);
    tx.color_profile= strndup(input->color_profile, MAX_COLOR_PROFILE_LEN);
    tx.width        = input->width;
    tx.height       = input->height;
    tx.created_at   = (uint64_t)time(NULL);

    if (!tx.id || !tx.name || !tx.color_profile)
    {
        _set_error(err, TX_ERR_OOM, "Failed to allocate texture attributes");
        goto cleanup_fail;
    }

    /* Serialize metadata payload */
    tx.metadata = _texture_to_json(&tx, err);
    if (!tx.metadata)
        goto cleanup_fail;

    /* Acquire write-lock for repository update */
    if (pthread_rwlock_wrlock(&state->lock) != 0)
    {
        _set_error(err, TX_ERR_INTERNAL, "Failed to acquire write lock");
        goto cleanup_fail;
    }

    bool persist_ok = repository_save_texture(state->repo, &tx, err);
    pthread_rwlock_unlock(&state->lock);

    if (!persist_ok)
        goto cleanup_fail;

    /* Metrics */
    if (state->metrics)
        metrics_counter_inc(state->metrics, "texture_created_total", 1);

    /* Deep copy result for caller (repository may own original memory) */
    Texture *result = texture_clone(&tx, err);
    texture_free(&tx); /* Free local copy */

    log_info("[texture-handler] Created texture '%s' (%ux%u)", result->id, result->width, result->height);
    return result;

cleanup_fail:
    texture_free(&tx);
    return NULL;
}

/**
 * Retrieve a single texture by its UUID. Caller is responsible for freeing
 * the returned object via texture_free().
 */
Texture *texture_handler_get(TextureHandler *handler, const char *texture_id, TextureError *err)
{
    TextureHandlerState *state = (TextureHandlerState *)handler;
    if (!state || !state->ready)
    {
        _set_error(err, TX_ERR_NOT_INITIALIZED, "TextureHandler is not initialized");
        return NULL;
    }

    if (!validation_is_uuid(texture_id))
    {
        _set_error(err, TX_ERR_INVALID_ARGUMENT, "Invalid UUID provided: '%s'", texture_id);
        return NULL;
    }

    if (pthread_rwlock_rdlock(&state->lock) != 0)
    {
        _set_error(err, TX_ERR_INTERNAL, "Failed to acquire read lock");
        return NULL;
    }

    Texture *tx = repository_get_texture(state->repo, texture_id, err);
    pthread_rwlock_unlock(&state->lock);

    if (!tx)
        return NULL; /* Error already populated */

    if (state->metrics)
        metrics_counter_inc(state->metrics, "texture_fetched_total", 1);

    return tx; /* Ownership transferred to caller */
}

/**
 * Paginated list of textures.  Returns the number of items copied into
 * out_list, or SIZE_MAX on error.
 *
 * The out_list vector is allocated by the caller; this function fills it up to
 * page_req->page_size. Each populated entry must be released with
 * texture_free() by the caller.
 */
size_t texture_handler_list(TextureHandler           *handler,
                            const PaginationRequest  *page_req,
                            Texture                 **out_list,
                            TextureError             *err)
{
    memset(out_list, 0, sizeof(Texture *) * page_req->page_size);

    TextureHandlerState *state = (TextureHandlerState *)handler;
    if (!state || !state->ready)
    {
        _set_error(err, TX_ERR_NOT_INITIALIZED, "TextureHandler is not initialized");
        return SIZE_MAX;
    }

    if (!page_req || !validation_is_pagination_request_valid(page_req))
    {
        _set_error(err, TX_ERR_INVALID_ARGUMENT, "Invalid pagination request");
        return SIZE_MAX;
    }

    if (pthread_rwlock_rdlock(&state->lock) != 0)
    {
        _set_error(err, TX_ERR_INTERNAL, "Failed to acquire read lock");
        return SIZE_MAX;
    }

    size_t fetched = repository_list_textures(state->repo, page_req, out_list, err);
    pthread_rwlock_unlock(&state->lock);

    if (fetched == SIZE_MAX)
        return SIZE_MAX;

    if (state->metrics)
        metrics_histogram_observe(state->metrics, "textures_per_page", fetched);

    log_debug("[texture-handler] Listed %zu textures (page %u)", fetched, page_req->page_index);
    return fetched;
}

/**
 * Deletes a texture by ID.  Returns true on success, false otherwise.
 */
bool texture_handler_delete(TextureHandler *handler, const char *texture_id, TextureError *err)
{
    TextureHandlerState *state = (TextureHandlerState *)handler;
    if (!state || !state->ready)
    {
        _set_error(err, TX_ERR_NOT_INITIALIZED, "TextureHandler is not initialized");
        return false;
    }

    if (!validation_is_uuid(texture_id))
    {
        _set_error(err, TX_ERR_INVALID_ARGUMENT, "Invalid UUID '%s'", texture_id);
        return false;
    }

    if (pthread_rwlock_wrlock(&state->lock) != 0)
    {
        _set_error(err, TX_ERR_INTERNAL, "Failed to acquire write lock");
        return false;
    }

    bool ok = repository_delete_texture(state->repo, texture_id, err);
    pthread_rwlock_unlock(&state->lock);

    if (ok && state->metrics)
        metrics_counter_inc(state->metrics, "texture_deleted_total", 1);

    log_info("[texture-handler] Deleted texture '%s' (%s)", texture_id, ok ? "ok" : "not-found");
    return ok;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Private Helpers                                                          */
/* ────────────────────────────────────────────────────────────────────────── */

static void _set_error(TextureError *out, TextureErrorCode code, const char *fmt, ...)
{
    if (!out)
        return;

    va_list ap;
    va_start(ap, fmt);
    vsnprintf(out->message, sizeof(out->message), fmt, ap);
    va_end(ap);

    out->code = code;
}

static bool _validate_texture_input(const TextureInput *in, TextureError *err)
{
    if (!in)
    {
        _set_error(err, TX_ERR_INVALID_ARGUMENT, "TextureInput cannot be NULL");
        return false;
    }

    if (!validation_is_valid_name(in->name, MAX_TEXTURE_NAME_LEN))
    {
        _set_error(err, TX_ERR_VALIDATION, "Invalid texture name");
        return false;
    }

    if (!validation_is_color_profile(in->color_profile))
    {
        _set_error(err, TX_ERR_VALIDATION, "Unsupported color profile '%s'", in->color_profile);
        return false;
    }

    if (in->width == 0 || in->height == 0 || in->width > 16384 || in->height > 16384)
    {
        _set_error(err, TX_ERR_VALIDATION, "Texture dimensions out of bounds (1..16384)");
        return false;
    }

    return true;
}

static char *_generate_uuid(void)
{
    uuid_t bin;
    uuid_generate_random(bin);

    char *str = malloc(TEXTURE_ID_STRLEN);
    if (!str)
        return NULL;

    uuid_unparse_lower(bin, str);
    return str;
}

static json_t *_texture_to_json(const Texture *tx, TextureError *err)
{
    json_t *obj = json_object();
    if (!obj)
    {
        _set_error(err, TX_ERR_OOM, "Failed to allocate JSON object");
        return NULL;
    }

    if (json_object_set_new(obj, "id",            json_string(tx->id))           < 0 ||
        json_object_set_new(obj, "name",          json_string(tx->name))         < 0 ||
        json_object_set_new(obj, "color_profile", json_string(tx->color_profile))< 0 ||
        json_object_set_new(obj, "width",         json_integer(tx->width))       < 0 ||
        json_object_set_new(obj, "height",        json_integer(tx->height))      < 0 ||
        json_object_set_new(obj, "created_at",    json_integer(tx->created_at))  < 0)
    {
        json_decref(obj);
        _set_error(err, TX_ERR_INTERNAL, "Failed to build texture JSON payload");
        return NULL;
    }

    return obj;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* End of file                                                               */
/* ────────────────────────────────────────────────────────────────────────── */
