/*
 * SPDX-License-Identifier: MIT
 *
 * SynestheticCanvas – Audio Service
 * ---------------------------------
 * Model: audio_stream
 *
 * This unit provides the concrete implementation of the audio_stream
 * domain object used by the Audio-Service.  An audio_stream represents
 * an audio data source that may be pulled from disk, a remote URI, or a
 * live capture device.  The object supports:
 *
 *   • Reference-counted lifetime management
 *   • Thread-safe metadata updates
 *   • JSON serialisation for GraphQL/REST payloads
 *
 * The implementation purposely avoids any heavy DSP concerns; that
 * responsibility is delegated to the streaming-engine component.
 */

#include "audio_stream.h"

#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "log.h"       /* Project-local logging wrapper                */
#include "mem_sanit.h" /* Sanitised allocation helpers (wraps malloc) */
#include "cjson.h"     /* https://github.com/DaveGamble/cJSON          */

/* ---------------------------------------------------------------------------
 * Internal helpers
 * ---------------------------------------------------------------------------*/

/* Safely duplicate a C-string; returns NULL on OOM. */
static char *duplicate_str(const char *src)
{
    if (!src) {
        return NULL;
    }

    const size_t len = strlen(src) + 1;
    char *dup = sc_alloc(len);
    if (!dup) {
        return NULL;
    }
    memcpy(dup, src, len);
    return dup;
}

/* ---------------------------------------------------------------------------
 * Public interface
 * ---------------------------------------------------------------------------*/

audio_stream_t *audio_stream_create(const char *stream_id,
                                    const char *source_uri,
                                    uint32_t sample_rate,
                                    uint8_t channels,
                                    bool is_live)
{
    if (!stream_id || !source_uri || !channels || !sample_rate) {
        sc_log_error("audio_stream_create: Invalid argument(s).");
        errno = EINVAL;
        return NULL;
    }

    audio_stream_t *stream = sc_calloc(1, sizeof(*stream));
    if (!stream) {
        sc_log_error("audio_stream_create: Allocation failure.");
        return NULL;
    }

    stream->stream_id  = duplicate_str(stream_id);
    stream->source_uri = duplicate_str(source_uri);

    if (!stream->stream_id || !stream->source_uri) {
        sc_log_error("audio_stream_create: Allocation failure.");
        audio_stream_destroy(stream); /* cleans partial allocs */
        return NULL;
    }

    stream->sample_rate       = sample_rate;
    stream->channels          = channels;
    stream->is_live           = is_live;
    stream->created_at        = time(NULL);
    stream->last_activity_at  = stream->created_at;
    atomic_init(&stream->ref_count, 1);

    if (pthread_mutex_init(&stream->mutex, NULL) != 0) {
        sc_log_perror("audio_stream_create: mutex init failed");
        audio_stream_destroy(stream);
        return NULL;
    }

    sc_log_debug("audio_stream [%s] created (rate=%u, ch=%u, live=%d)",
                 stream->stream_id, stream->sample_rate, stream->channels,
                 stream->is_live);

    return stream;
}

void audio_stream_retain(audio_stream_t *stream)
{
    if (!stream) {
        return;
    }
    (void)atomic_fetch_add_explicit(&stream->ref_count, 1, memory_order_relaxed);
}

void audio_stream_release(audio_stream_t *stream)
{
    if (!stream) {
        return;
    }

    if (atomic_fetch_sub_explicit(&stream->ref_count, 1, memory_order_acq_rel) ==
        1) {
        /* Last reference dropped */
        audio_stream_destroy(stream);
    }
}

bool audio_stream_update(audio_stream_t *stream,
                         uint32_t sample_rate,
                         uint8_t channels,
                         bool is_live)
{
    if (!stream || !sample_rate || !channels) {
        errno = EINVAL;
        return false;
    }

    if (pthread_mutex_lock(&stream->mutex) != 0) {
        sc_log_perror("audio_stream_update: mutex lock failed");
        return false;
    }

    stream->sample_rate      = sample_rate;
    stream->channels         = channels;
    stream->is_live          = is_live;
    stream->last_activity_at = time(NULL);

    pthread_mutex_unlock(&stream->mutex);

    sc_log_debug("audio_stream [%s] metadata updated (rate=%u, ch=%u, live=%d)",
                 stream->stream_id, stream->sample_rate, stream->channels,
                 stream->is_live);
    return true;
}

void audio_stream_touch(audio_stream_t *stream)
{
    if (!stream) {
        return;
    }

    if (pthread_mutex_lock(&stream->mutex) == 0) {
        stream->last_activity_at = time(NULL);
        pthread_mutex_unlock(&stream->mutex);
    }
}

const char *audio_stream_get_id(const audio_stream_t *stream)
{
    return stream ? stream->stream_id : NULL;
}

uint64_t audio_stream_age_ms(const audio_stream_t *stream)
{
    if (!stream) {
        return 0;
    }

    if (pthread_mutex_lock((pthread_mutex_t *)&stream->mutex) != 0) {
        return 0; /* best-effort */
    }

    time_t now  = time(NULL);
    time_t last = stream->last_activity_at;

    pthread_mutex_unlock((pthread_mutex_t *)&stream->mutex);

    if (now < last) {
        return 0;
    }
    return (uint64_t)(now - last) * 1000;
}

char *audio_stream_to_json(const audio_stream_t *stream)
{
    if (!stream) {
        errno = EINVAL;
        return NULL;
    }

    char *json_out = NULL;

    if (pthread_mutex_lock((pthread_mutex_t *)&stream->mutex) != 0) {
        return NULL;
    }

    cJSON *root = cJSON_CreateObject();
    if (!root) {
        goto cleanup_unlock;
    }

    cJSON_AddStringToObject(root, "id", stream->stream_id);
    cJSON_AddStringToObject(root, "sourceUri", stream->source_uri);
    cJSON_AddNumberToObject(root, "sampleRate", stream->sample_rate);
    cJSON_AddNumberToObject(root, "channels", stream->channels);
    cJSON_AddBoolToObject(root, "live", stream->is_live);
    cJSON_AddNumberToObject(root, "createdAt", (double)stream->created_at);
    cJSON_AddNumberToObject(root, "lastActivityAt",
                            (double)stream->last_activity_at);

    json_out = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

cleanup_unlock:
    pthread_mutex_unlock((pthread_mutex_t *)&stream->mutex);
    return json_out; /* Caller must free() */
}

/* ---------------------------------------------------------------------------
 * Destructor
 * ---------------------------------------------------------------------------*/

void audio_stream_destroy(audio_stream_t *stream)
{
    if (!stream) {
        return;
    }

    sc_log_debug("audio_stream [%s] destroyed", stream->stream_id);

    /* Free dynamic members */
    sc_free(stream->stream_id);
    sc_free(stream->source_uri);

    (void)pthread_mutex_destroy(&stream->mutex);
    sc_free(stream);
}

/* ---------------------------------------------------------------------------
 * Diagnostic dump (human readable)
 * ---------------------------------------------------------------------------*/

void audio_stream_dump(const audio_stream_t *stream, FILE *out)
{
    if (!stream) {
        return;
    }
    if (!out) {
        out = stderr;
    }

    if (pthread_mutex_lock((pthread_mutex_t *)&stream->mutex) != 0) {
        return;
    }

    fprintf(out,
            "audio_stream@%p {\n"
            "  id               : %s\n"
            "  source_uri       : %s\n"
            "  sample_rate      : %u\n"
            "  channels         : %u\n"
            "  is_live          : %s\n"
            "  created_at       : %ld\n"
            "  last_activity_at : %ld\n"
            "  ref_count        : %u\n"
            "}\n",
            (void *)stream,
            stream->stream_id,
            stream->source_uri,
            stream->sample_rate,
            stream->channels,
            stream->is_live ? "true" : "false",
            stream->created_at,
            stream->last_activity_at,
            atomic_load(&stream->ref_count));

    pthread_mutex_unlock((pthread_mutex_t *)&stream->mutex);
}