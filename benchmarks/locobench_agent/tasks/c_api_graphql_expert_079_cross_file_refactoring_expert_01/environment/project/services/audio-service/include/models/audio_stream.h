```c
/**
 * SynestheticCanvas – Audio-service
 * File: include/models/audio_stream.h
 *
 * Copyright (c) 2023-2024
 * SPDX-License-Identifier: MIT
 *
 * Description:
 *     Thread-safe in-memory ring-buffer abstraction for real-time PCM
 *     audio transport between processing stages inside the audio-service
 *     micro-component.
 *
 *     The implementation purposefully lives in a header file so that the
 *     compiler can inline hot paths (read/write) when optimisation flags
 *     are enabled.  A separate translation unit can be provided if the
 *     build system needs a strictly opaque type.
 *
 * Usage:
 *     #define SC_AUDIO_STREAM_IMPLEMENTATION
 *     #include "models/audio_stream.h"
 *
 *     (placing the define in exactly one .c file that needs the function
 *     bodies, while other includes only see the declarations.)
 */

#pragma once

/*=====================================================================*/
/*  Standard Library Dependencies                                      */
/*=====================================================================*/
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <time.h>

#if __STDC_VERSION__ >= 201112L
#    include <stdatomic.h>
#else
#    error "C11 (or newer) compiler required for stdatomic support."
#endif

#include <errno.h>     /* For standard error codes */
#include <string.h>    /* memcpy */
#include <pthread.h>   /* Fallback lock for non-lock-free atomics */


/*=====================================================================*/
/*  Versioning                                                         */
/*=====================================================================*/
#define SC_AUDIO_STREAM_VERSION_MAJOR  1
#define SC_AUDIO_STREAM_VERSION_MINOR  0
#define SC_AUDIO_STREAM_VERSION_PATCH  0

/*=====================================================================*/
/*  Helper Macros                                                      */
/*=====================================================================*/
#ifndef SC_UNUSED
#    define SC_UNUSED(x) ((void)(x))
#endif

#define SC_ALIGN_TO_16(x)  (((x) + 15u) & ~15u)

/*=====================================================================*/
/*  Audio Format Definition                                            */
/*=====================================================================*/

/**
 * sc_audio_format_t – Inter-service canonical PCM sample layout
 *
 * Note: An enum is used instead of a bit-mask to keep the public
 *       contract small.  If an exotic format is needed in the future,
 *       add a new value and ensure audio-gateway resampling code is
 *       updated accordingly.
 */
typedef enum
{
    SC_AUDIO_FORMAT_S16LE = 0,  /* 16-bit signed little-endian */
    SC_AUDIO_FORMAT_S32LE,      /* 32-bit signed little-endian */
    SC_AUDIO_FORMAT_FLOAT32,    /* 32-bit IEEE-754 */
    SC_AUDIO_FORMAT_FLOAT64,    /* 64-bit IEEE-754 */
    SC_AUDIO_FORMAT__COUNT
} sc_audio_format_t;

/* Query helper */
static inline uint8_t sc_audio_format_bytes(sc_audio_format_t fmt)
{
    switch (fmt) {
    case SC_AUDIO_FORMAT_S16LE:  return 2u;
    case SC_AUDIO_FORMAT_S32LE:  return 4u;
    case SC_AUDIO_FORMAT_FLOAT32:return 4u;
    case SC_AUDIO_FORMAT_FLOAT64:return 8u;
    default:                     return 0u;
    }
}

/*=====================================================================*/
/*  Timestamp                                                          */
/*=====================================================================*/

/**
 * sc_audio_timestamp_t – Logical frame counter + wall-clock snapshot.
 *
 * The wall-clock timestamp is taken from CLOCK_MONOTONIC_RAW so that
 * audio latency computations remain unaffected by NTP and leap-second
 * corrections.
 */
typedef struct
{
    uint64_t        frames;      /* Stream position in frames          */
    struct timespec mono_raw;    /* CLOCK_MONOTONIC_RAW snapshot       */
} sc_audio_timestamp_t;

/*=====================================================================*/
/*  Error Codes                                                        */
/*=====================================================================*/
typedef enum
{
    SC_AUDIO_OK          = 0,
    SC_AUDIO_EINVAL      = EINVAL,
    SC_AUDIO_ENOMEM      = ENOMEM,
    SC_AUDIO_ECLOSED     = 0x1001, /* Stream not active/closed          */
    SC_AUDIO_EOVERFLOW   = 0x1002, /* Reader missed data (overrun)      */
    SC_AUDIO_EUNDERFLOW  = 0x1003  /* Not enough data available         */
} sc_audio_err_t;

/*=====================================================================*/
/*  Public Opaque Type                                                 */
/*=====================================================================*/
typedef struct sc_audio_stream sc_audio_stream_t;

/*=====================================================================*/
/*  API – Lifecycle                                                    */
/*=====================================================================*/

/**
 * sc_audio_stream_create –
 *     Allocate and initialise a ring-buffer with the requested
 *     parameters. Capacity is expressed in number of *frames* (not
 *     bytes). A frame corresponds to (channels × sample_size) bytes.
 *
 * Params:
 *     sample_rate_hz – sampling frequency (e.g., 48000)
 *     channels       – number of interleaved channels
 *     fmt            – sample representation
 *     capacity_frames– ring-buffer size
 *     out_stream     – address of pointer to be filled with instance
 *
 * Return:
 *     SC_AUDIO_OK on success, or an error code on failure.
 */
sc_audio_err_t
sc_audio_stream_create(uint32_t              sample_rate_hz,
                       uint8_t               channels,
                       sc_audio_format_t     fmt,
                       size_t                capacity_frames,
                       sc_audio_stream_t  ** out_stream);

/**
 * sc_audio_stream_destroy – Free all memory; safe to call on NULL.
 */
void
sc_audio_stream_destroy(sc_audio_stream_t *stream);

/*=====================================================================*/
/*  API – State Management                                             */
/*=====================================================================*/

/**
 * sc_audio_stream_activate –
 *     Atomically marks the stream “active”.  While inactive, reads and
 *     writes will return SC_AUDIO_ECLOSED.
 */
void
sc_audio_stream_activate(sc_audio_stream_t *stream);

/**
 * sc_audio_stream_deactivate –
 *     Immediately stop all I/O. Pending blocking calls (if any) should
 *     be unblocked by the owner before destroying the object.
 */
void
sc_audio_stream_deactivate(sc_audio_stream_t *stream);

/**
 * sc_audio_stream_is_active – Query active flag (lock-free).
 */
static inline bool
sc_audio_stream_is_active(const sc_audio_stream_t *stream);

/*=====================================================================*/
/*  API – I/O                                                          */
/*=====================================================================*/

/**
 * sc_audio_stream_write –
 *     Write |frames| frames to the ring-buffer. The function returns
 *     the number of frames actually written, which may be smaller than
 *     requested when the buffer runs full (non-blocking behaviour).
 *
 *     The function is safe for concurrent producer/consumer use.
 *
 *     Upon overflow, SC_AUDIO_EOVERFLOW will be stored in |err| if
 *     provided.
 *
 * Params:
 *     stream – ring-buffer handle
 *     data   – pointer to PCM frames
 *     frames – amount of frames to write
 *     err    – optional error placeholder
 *
 * Return:
 *     size_t amount of frames written
 */
size_t
sc_audio_stream_write(sc_audio_stream_t *stream,
                      const void *data,
                      size_t frames,
                      sc_audio_err_t *err);

/**
 * sc_audio_stream_read –
 *     Attempt to read up to |max_frames| into |out|. Returns the number
 *     of frames consumed, or zero when no data is available.
 *
 *     On underflow, SC_AUDIO_EUNDERFLOW will be stored in |err|.
 */
size_t
sc_audio_stream_read(sc_audio_stream_t *stream,
                     void *out,
                     size_t max_frames,
                     sc_audio_err_t *err);

/*=====================================================================*/
/*  Implementation Section (optional)                                  */
/*=====================================================================*/
#ifdef SC_AUDIO_STREAM_IMPLEMENTATION
#include <stdlib.h>

/*---------------------------------------------------------*/
/*  Private definitions                                    */
/*---------------------------------------------------------*/
struct sc_audio_stream
{
    /* Immutable after _create() */
    uint32_t           sample_rate;
    uint8_t            channels;
    sc_audio_format_t  fmt;
    size_t             frame_size;         /* bytes per frame */
    size_t             capacity_frames;    /* ring size (frames) */
    uint8_t          * buffer;             /* malloc'd, size = cap*frame_size */

    /* Ring-buffer indices (monotonically increasing counters) */
    _Atomic uint64_t   write_idx;          /* number of frames written */
    _Atomic uint64_t   read_idx;           /* number of frames read    */

    /* Stream state */
    _Atomic bool       active;

    /* Native mutex as fallback guard for non-lock-free atomics on exotic
     * platforms. The fast-path never locks on mainstream architectures.
     */
    pthread_mutex_t    fallback_lock;
};

/* Utility: allocate aligned buffer (16-byte to assist SIMD paths) */
static uint8_t *
sc_malloc_aligned(size_t bytes)
{
#if defined(_POSIX_C_SOURCE) && _POSIX_C_SOURCE >= 200112L
    void *ptr = NULL;
    if (posix_memalign(&ptr, 16u, SC_ALIGN_TO_16(bytes)) != 0) {
        return NULL;
    }
    return (uint8_t *)ptr;
#else
    /* Fallback to regular malloc, possibly misaligned. */
    return (uint8_t *)malloc(bytes);
#endif
}

/*=========================================================*/
/*  Public API                                             */
/*=========================================================*/
sc_audio_err_t
sc_audio_stream_create(uint32_t          rate,
                       uint8_t           channels,
                       sc_audio_format_t fmt,
                       size_t            cap_frames,
                       sc_audio_stream_t **out)
{
    if (!out || rate == 0 || channels == 0 || fmt >= SC_AUDIO_FORMAT__COUNT || cap_frames == 0) {
        return SC_AUDIO_EINVAL;
    }

    sc_audio_stream_t *s = calloc(1, sizeof(*s));
    if (!s) {
        return SC_AUDIO_ENOMEM;
    }

    const uint8_t sample_bytes = sc_audio_format_bytes(fmt);
    s->frame_size       = (size_t)sample_bytes * channels;
    s->capacity_frames  = cap_frames;
    s->sample_rate      = rate;
    s->channels         = channels;
    s->fmt              = fmt;
    s->active           = ATOMIC_VAR_INIT(false);
    s->write_idx        = ATOMIC_VAR_INIT(0);
    s->read_idx         = ATOMIC_VAR_INIT(0);

    if (pthread_mutex_init(&s->fallback_lock, NULL) != 0) {
        free(s);
        return SC_AUDIO_ENOMEM;
    }

    const size_t buffer_bytes = s->frame_size * cap_frames;
    s->buffer = sc_malloc_aligned(buffer_bytes);
    if (!s->buffer) {
        pthread_mutex_destroy(&s->fallback_lock);
        free(s);
        return SC_AUDIO_ENOMEM;
    }

    *out = s;
    return SC_AUDIO_OK;
}

void
sc_audio_stream_destroy(sc_audio_stream_t *s)
{
    if (!s) return;

    sc_audio_stream_deactivate(s);

    free(s->buffer);
    pthread_mutex_destroy(&s->fallback_lock);
    free(s);
}

void
sc_audio_stream_activate(sc_audio_stream_t *s)
{
    if (!s) return;
    atomic_store_explicit(&s->active, true, memory_order_release);
}

void
sc_audio_stream_deactivate(sc_audio_stream_t *s)
{
    if (!s) return;
    atomic_store_explicit(&s->active, false, memory_order_release);
}

static inline bool
sc_audio_stream_is_active(const sc_audio_stream_t *s)
{
    return atomic_load_explicit(&s->active, memory_order_acquire);
}

static inline size_t
min_size_t(size_t a, size_t b) { return (a < b) ? a : b; }

size_t
sc_audio_stream_write(sc_audio_stream_t *s,
                      const void *data,
                      size_t frames,
                      sc_audio_err_t *err)
{
    if (err) *err = SC_AUDIO_OK;

    if (!s || !data || frames == 0) {
        if (err) *err = SC_AUDIO_EINVAL;
        return 0;
    }
    if (!sc_audio_stream_is_active(s)) {
        if (err) *err = SC_AUDIO_ECLOSED;
        return 0;
    }

    const size_t cap = s->capacity_frames;
    const size_t fs  = s->frame_size;

    /* Atomically fetch current positions */
    uint64_t w = atomic_load_explicit(&s->write_idx, memory_order_acquire);
    uint64_t r = atomic_load_explicit(&s->read_idx,  memory_order_acquire);

    const size_t used   = (size_t)(w - r);
    const size_t free_space = cap - used;

    /* Non-blocking write */
    size_t to_write = min_size_t(frames, free_space);

    if (to_write == 0) {
        if (err) *err = SC_AUDIO_EOVERFLOW;
        return 0;
    }

    const size_t offset = (size_t)(w % cap);
    const uint8_t *src  = (const uint8_t *)data;

    /* Two-part copy when wrapping */
    size_t first_part = min_size_t(to_write, cap - offset);
    size_t second_part= to_write - first_part;

    memcpy(s->buffer + (offset * fs), src, first_part * fs);
    if (second_part) {
        memcpy(s->buffer, src + first_part * fs, second_part * fs);
    }

    /* Publish new write index */
    atomic_store_explicit(&s->write_idx, w + to_write, memory_order_release);

    return to_write;
}

size_t
sc_audio_stream_read(sc_audio_stream_t *s,
                     void *out,
                     size_t max_frames,
                     sc_audio_err_t *err)
{
    if (err) *err = SC_AUDIO_OK;

    if (!s || !out || max_frames == 0) {
        if (err) *err = SC_AUDIO_EINVAL;
        return 0;
    }
    if (!sc_audio_stream_is_active(s)) {
        if (err) *err = SC_AUDIO_ECLOSED;
        return 0;
    }

    const size_t cap = s->capacity_frames;
    const size_t fs  = s->frame_size;

    uint64_t w = atomic_load_explicit(&s->write_idx, memory_order_acquire);
    uint64_t r = atomic_load_explicit(&s->read_idx,  memory_order_acquire);

    const size_t available = (size_t)(w - r);
    size_t to_read = min_size_t(max_frames, available);

    if (to_read == 0) {
        if (err) *err = SC_AUDIO_EUNDERFLOW;
        return 0;
    }

    size_t offset = (size_t)(r % cap);
    uint8_t *dst  = (uint8_t *)out;

    size_t first_part = min_size_t(to_read, cap - offset);
    size_t second_part= to_read - first_part;

    memcpy(dst, s->buffer + (offset * fs), first_part * fs);
    if (second_part) {
        memcpy(dst + first_part * fs, s->buffer, second_part * fs);
    }

    atomic_store_explicit(&s->read_idx, r + to_read, memory_order_release);

    return to_read;
}

#endif /* SC_AUDIO_STREAM_IMPLEMENTATION */
```