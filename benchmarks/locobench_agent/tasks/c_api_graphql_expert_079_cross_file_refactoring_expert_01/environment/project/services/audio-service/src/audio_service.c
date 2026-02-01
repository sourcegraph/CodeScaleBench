```c
/*
 *  SynestheticCanvas – Audio Service
 *  File: services/audio-service/src/audio_service.c
 *
 *  Description
 *  -----------
 *  A high-throughput, low-latency audio analysis service that converts
 *  incoming PCM streams into colour-coded “brush-stroke” events consumable
 *  by the SynestheticCanvas API-Gateway (GraphQL subscriptions & REST web-hooks).
 *
 *  Responsibilities
 *  ---------------
 *   • Ingest interleaved 16-bit PCM frames from upstream producers
 *   • Perform spectral analysis using FFTW3 (or a light-weight fallback)
 *   • Map frequency-band energy to RGB colour space
 *   • Emit colour events through a user-supplied callback
 *   • Provide thread-safe start/stop/submit API
 *
 *  Build
 *  -----
 *      gcc -std=c11 -Wall -Wextra -O2 -pthread -lfftw3f \
 *          -I./services/audio-service/include \
 *          -o audio_service services/audio-service/src/audio_service.c
 *
 *  Copyright
 *  ---------
 *  © 2024 SynestheticCanvas Contributors – MIT License
 */

#include <errno.h>
#include <fftw3.h>
#include <math.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

/* ================================================================
 *                            CONFIG
 * ================================================================ */

#ifndef AUDIO_SERVICE_SAMPLE_RATE
#define AUDIO_SERVICE_SAMPLE_RATE 44100U /* Hz */
#endif

/* Window length for FFT (must be power of two) */
#ifndef AUDIO_SERVICE_FFT_SIZE
#define AUDIO_SERVICE_FFT_SIZE 1024U
#endif

/* Maximum number of interleaved channels supported (1=mono, 2=stereo) */
#ifndef AUDIO_SERVICE_MAX_CHANNELS
#define AUDIO_SERVICE_MAX_CHANNELS 2U
#endif

/* Ring-buffer capacity expressed in FFT windows */
#ifndef AUDIO_SERVICE_RING_CAP
#define AUDIO_SERVICE_RING_CAP 256U
#endif

/* Pretty-print macros */
#define LOG_TAG "audio-service"
#define LOG_ERROR(fmt, ...) \
    fprintf(stderr, "[%s] ERROR: " fmt "\n", LOG_TAG, ##__VA_ARGS__)
#define LOG_INFO(fmt, ...) \
    fprintf(stdout, "[%s] INFO:  " fmt "\n", LOG_TAG, ##__VA_ARGS__)
#define LOG_DEBUG(fmt, ...) \
    do {                                                         \
        if (getenv("AUDIO_SERVICE_DEBUG") != NULL)               \
            fprintf(stdout, "[%s] DEBUG: " fmt "\n", LOG_TAG,    \
                    ##__VA_ARGS__);                              \
    } while (0)

/* ================================================================
 *                       DATA DECLARATIONS
 * ================================================================ */

/* Colour event emitted to upper layers */
typedef struct color_event_t {
    struct timeval timestamp;
    float r; /* 0.0 – 1.0 */
    float g;
    float b;
    float energy; /* Overall RMS energy 0.0 – 1.0 */
} color_event_t;

/* Forward declaration */
struct audio_service_t;
typedef struct audio_service_t audio_service_t;

/* Event callback signature */
typedef void (*audio_event_cb)(const color_event_t *evt, void *user_ctx);

/* ------------------------------------------------
 * Ring-buffer for PCM frames (will hold float mono
 * stream already mixed down if needed).
 * ------------------------------------------------ */
typedef struct {
    float          *data;        /* Linear buffer (size = cap * FFT_SIZE) */
    size_t          cap;         /* window capacity                        */
    size_t          wr;          /* write index (window units)             */
    size_t          rd;          /* read index (window units)              */
    pthread_mutex_t mtx;
    pthread_cond_t  cv_has_data;
    pthread_cond_t  cv_has_room;
    bool            stop;
} pcm_ring_t;

/* ------------------------------------------------
 * Service handle
 * ------------------------------------------------ */
struct audio_service_t {
    pcm_ring_t       ring;
    pthread_t        worker;
    bool             running;
    audio_event_cb   cb;
    void            *cb_ctx;

    /* FFTW scratch */
    fftwf_plan       plan;
    float           *fft_in;
    fftwf_complex   *fft_out;

    /* configuration */
    uint32_t         sample_rate;
    uint8_t          channels;
};

/* ================================================================
 *                         PROTOTYPES
 * ================================================================ */
static int  ring_init(pcm_ring_t *rb, size_t win_cap);
static void ring_dispose(pcm_ring_t *rb);
static void ring_write_blocking(pcm_ring_t *rb, const float *samples);
static bool ring_read_blocking(pcm_ring_t *rb, float *out_samples);

static void *worker_thread_fn(void *arg);
static void   analyse_window(audio_service_t *svc, const float *win);
static float  hz_from_bin(uint32_t bin_idx, uint32_t fft_size,
                          uint32_t sample_rate);
static void   map_energy_to_colour(float low, float mid, float high,
                                   float *r, float *g, float *b);

/* ================================================================
 *                       PUBLIC API
 * ================================================================ */

/**
 * audio_service_create
 *
 * Create a new service instance.
 *
 * @param sample_rate  Expected PCM sample rate (Hz)
 * @param channels     Number of interleaved channels (1 or 2)
 * @param cb           Event callback (may be NULL)
 * @param cb_ctx       Opaque pointer passed verbatim to callback
 * @return             Newly allocated handle or NULL on error
 */
audio_service_t *audio_service_create(uint32_t sample_rate,
                                      uint8_t  channels,
                                      audio_event_cb cb,
                                      void *cb_ctx)
{
    if (channels == 0 || channels > AUDIO_SERVICE_MAX_CHANNELS) {
        errno = EINVAL;
        return NULL;
    }

    audio_service_t *svc = calloc(1, sizeof(*svc));
    if (!svc) {
        return NULL;
    }

    svc->sample_rate = sample_rate ? sample_rate : AUDIO_SERVICE_SAMPLE_RATE;
    svc->channels    = channels;
    svc->cb          = cb;
    svc->cb_ctx      = cb_ctx;

    if (ring_init(&svc->ring, AUDIO_SERVICE_RING_CAP) != 0) {
        free(svc);
        return NULL;
    }

    /* Allocate FFT buffers */
    svc->fft_in  = fftwf_alloc_real(AUDIO_SERVICE_FFT_SIZE);
    svc->fft_out = fftwf_alloc_complex(AUDIO_SERVICE_FFT_SIZE / 2 + 1);
    if (!svc->fft_in || !svc->fft_out) {
        LOG_ERROR("Failed to allocate FFT buffers");
        ring_dispose(&svc->ring);
        free(svc);
        return NULL;
    }

    /* Create FFTW plan (single-threaded, measure for speed) */
    svc->plan = fftwf_plan_dft_r2c_1d((int)AUDIO_SERVICE_FFT_SIZE,
                                      svc->fft_in,
                                      svc->fft_out,
                                      FFTW_MEASURE);
    if (!svc->plan) {
        LOG_ERROR("Failed to create FFTW plan");
        ring_dispose(&svc->ring);
        fftwf_free(svc->fft_in);
        fftwf_free(svc->fft_out);
        free(svc);
        return NULL;
    }

    return svc;
}

/**
 * audio_service_start
 *
 * Spawn analysis worker thread.
 *
 * @return 0 on success, -1 on failure
 */
int audio_service_start(audio_service_t *svc)
{
    if (!svc) {
        errno = EINVAL;
        return -1;
    }
    if (svc->running) {
        return 0;
    }
    svc->running = true;
    if (pthread_create(&svc->worker, NULL, worker_thread_fn, svc) != 0) {
        svc->running = false;
        LOG_ERROR("Worker thread creation failed: %s", strerror(errno));
        return -1;
    }
    LOG_INFO("Audio service started (SR=%uHz, CH=%u)",
             svc->sample_rate, svc->channels);
    return 0;
}

/**
 * audio_service_submit_frames
 *
 * Feed raw interleaved frames (16-bit signed samples) to the service.
 * This call blocks if ring-buffer is full.
 */
int audio_service_submit_frames(audio_service_t *svc,
                                const int16_t   *frames,
                                size_t           frame_count)
{
    if (!svc || !frames || frame_count == 0) {
        errno = EINVAL;
        return -1;
    }

    const float norm = 1.0f / 32768.0f;
    float window[AUDIO_SERVICE_FFT_SIZE];

    size_t idx = 0;
    while (idx < frame_count) {
        size_t remaining_frames = frame_count - idx;
        size_t needed           = AUDIO_SERVICE_FFT_SIZE;

        /* If we don't have enough for a full window, copy what we can
         * and zero-pad the rest (simple approach). */
        for (size_t s = 0; s < needed; ++s) {
            if (s < remaining_frames) {
                int16_t sample =
                    frames[(idx + s) * svc->channels]; /* mix-down L */
                if (svc->channels == 2) {
                    /* Very naive stereo-to-mono: average L+R */
                    sample = (sample + frames[(idx + s) * svc->channels + 1]) /
                             2;
                }
                window[s] = sample * norm;
            } else {
                window[s] = 0.0f;
            }
        }

        /* Write window to ring buffer */
        ring_write_blocking(&svc->ring, window);

        idx += needed;
    }
    return 0;
}

/**
 * audio_service_stop
 *
 * Stop worker thread and flush.
 */
void audio_service_stop(audio_service_t *svc)
{
    if (!svc || !svc->running)
        return;

    /* Signal termination */
    pthread_mutex_lock(&svc->ring.mtx);
    svc->ring.stop = true;
    pthread_cond_broadcast(&svc->ring.cv_has_data);
    pthread_mutex_unlock(&svc->ring.mtx);

    pthread_join(svc->worker, NULL);
    svc->running = false;
    LOG_INFO("Audio service stopped");
}

/**
 * audio_service_destroy
 *
 * Dispose all resources. Must be called after stop().
 */
void audio_service_destroy(audio_service_t *svc)
{
    if (!svc)
        return;

    ring_dispose(&svc->ring);

    if (svc->plan)
        fftwf_destroy_plan(svc->plan);
    fftwf_free(svc->fft_in);
    fftwf_free(svc->fft_out);
    free(svc);
}

/* ================================================================
 *                  INTERNAL – RING BUFFER IMPL
 * ================================================================ */

static int ring_init(pcm_ring_t *rb, size_t win_cap)
{
    memset(rb, 0, sizeof(*rb));
    rb->cap = win_cap;
    rb->data =
        calloc(win_cap * AUDIO_SERVICE_FFT_SIZE, sizeof(float));
    if (!rb->data)
        return -1;

    if (pthread_mutex_init(&rb->mtx, NULL) != 0)
        goto fail;
    if (pthread_cond_init(&rb->cv_has_data, NULL) != 0)
        goto fail;
    if (pthread_cond_init(&rb->cv_has_room, NULL) != 0)
        goto fail;

    return 0;
fail:
    free(rb->data);
    return -1;
}

static void ring_dispose(pcm_ring_t *rb)
{
    if (!rb->data)
        return;

    pthread_mutex_destroy(&rb->mtx);
    pthread_cond_destroy(&rb->cv_has_data);
    pthread_cond_destroy(&rb->cv_has_room);
    free(rb->data);
    rb->data = NULL;
}

static void ring_write_blocking(pcm_ring_t *rb, const float *samples)
{
    pthread_mutex_lock(&rb->mtx);
    while (((rb->wr + 1) % rb->cap) == rb->rd && !rb->stop) {
        pthread_cond_wait(&rb->cv_has_room, &rb->mtx);
    }
    if (rb->stop) {
        pthread_mutex_unlock(&rb->mtx);
        return;
    }

    memcpy(&rb->data[rb->wr * AUDIO_SERVICE_FFT_SIZE],
           samples,
           sizeof(float) * AUDIO_SERVICE_FFT_SIZE);
    rb->wr = (rb->wr + 1) % rb->cap;

    pthread_cond_signal(&rb->cv_has_data);
    pthread_mutex_unlock(&rb->mtx);
}

static bool ring_read_blocking(pcm_ring_t *rb, float *out_samples)
{
    pthread_mutex_lock(&rb->mtx);
    while (rb->wr == rb->rd && !rb->stop) {
        pthread_cond_wait(&rb->cv_has_data, &rb->mtx);
    }
    if (rb->stop && rb->wr == rb->rd) {
        pthread_mutex_unlock(&rb->mtx);
        return false;
    }

    memcpy(out_samples,
           &rb->data[rb->rd * AUDIO_SERVICE_FFT_SIZE],
           sizeof(float) * AUDIO_SERVICE_FFT_SIZE);
    rb->rd = (rb->rd + 1) % rb->cap;

    pthread_cond_signal(&rb->cv_has_room);
    pthread_mutex_unlock(&rb->mtx);
    return true;
}

/* ================================================================
 *                WORKER THREAD & ANALYSIS ROUTINES
 * ================================================================ */

static void *worker_thread_fn(void *arg)
{
    audio_service_t *svc = arg;
    float            window[AUDIO_SERVICE_FFT_SIZE];

    while (ring_read_blocking(&svc->ring, window)) {
        analyse_window(svc, window);
    }
    return NULL;
}

static void analyse_window(audio_service_t *svc, const float *win)
{
    /* Copy window & apply Hann window function */
    for (size_t i = 0; i < AUDIO_SERVICE_FFT_SIZE; ++i) {
        float w = 0.5f * (1.0f - cosf(2.0f * M_PI * i /
                                      (AUDIO_SERVICE_FFT_SIZE - 1)));
        svc->fft_in[i] = win[i] * w;
    }

    fftwf_execute(svc->plan);

    /* Sum magnitudes for low/mid/high bands */
    float low  = 0.0f, mid = 0.0f, high = 0.0f;
    for (uint32_t i = 0; i < AUDIO_SERVICE_FFT_SIZE / 2 + 1; ++i) {
        float re = svc->fft_out[i][0];
        float im = svc->fft_out[i][1];
        float mag = sqrtf(re * re + im * im);

        float hz = hz_from_bin(i, AUDIO_SERVICE_FFT_SIZE,
                               svc->sample_rate);

        if (hz < 250.0f) {
            low += mag;
        } else if (hz < 4000.0f) {
            mid += mag;
        } else {
            high += mag;
        }
    }

    float total = low + mid + high + 1e-9f;
    low  /= total;
    mid  /= total;
    high /= total;

    float r, g, b;
    map_energy_to_colour(low, mid, high, &r, &g, &b);

    color_event_t evt;
    gettimeofday(&evt.timestamp, NULL);
    evt.r      = r;
    evt.g      = g;
    evt.b      = b;
    evt.energy = total / (AUDIO_SERVICE_FFT_SIZE / 2.0f);

    /* Dispatch */
    if (svc->cb) {
        svc->cb(&evt, svc->cb_ctx);
    }

    LOG_DEBUG("Event r=%.2f g=%.2f b=%.2f energy=%.3f",
              evt.r, evt.g, evt.b, evt.energy);
}

static float hz_from_bin(uint32_t bin_idx, uint32_t fft_size,
                         uint32_t sample_rate)
{
    return (float)bin_idx * (float)sample_rate / (float)fft_size;
}

/* Very naive mapping: low→R, mid→G, high→B */
static void map_energy_to_colour(float low, float mid, float high,
                                 float *r, float *g, float *b)
{
    *r = fminf(low * 2.0f, 1.0f);
    *g = fminf(mid * 2.0f, 1.0f);
    *b = fminf(high * 2.0f, 1.0f);
}

/* ================================================================
 *                           END OF FILE
 * ================================================================ */
```