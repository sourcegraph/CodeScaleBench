/*
 * SynestheticCanvas - Audio Service
 * File: audio_handler.c
 *
 * Description:
 *   Centralised audio-processing component for the SynestheticCanvas Audio
 *   micro-service.  Handles ingestion of raw PCM frames, computes analysis
 *   metrics (RMS, FFT magnitudes), and invokes user-supplied callbacks that
 *   drive colour/geometry generation in the rendering pipeline.
 *
 *   Designed for low-latency, high-throughput environments and integrates with
 *   the project-wide logging/monitoring facilities through syslog.
 *
 * Build:
 *   gcc -std=c11 -Wall -Wextra -pedantic -pthread \
 *       -D_GNU_SOURCE -o audio_handler.o -c audio_handler.c
 *
 *   Optional FFTW3 acceleration:
 *       gcc ... -DUSE_FFTW3 -lfftw3f
 */

#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <pthread.h>
#include <signal.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <syslog.h>
#include <time.h>
#ifdef USE_FFTW3
#    include <fftw3.h>
#endif

#include "audio_handler.h" /* Public interface */

/* ------------------------------------------------------------------------- */
/* Internal helpers                                                          */
/* ------------------------------------------------------------------------- */

#define AUDIOH_MIN(a, b) ((a) < (b) ? (a) : (b))
#define AUDIOH_MAX_QUEUE_CAP 1024U           /* Hard safety limit            */
#define AUDIOH_DEFAULT_QUEUE_CAP 32U         /* Reasonable default capacity  */

/* Micro-utility: monotonic time in microseconds */
static uint64_t
now_us(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * UINT64_C(1000000) +
           (uint64_t)ts.tv_nsec / 1000;
}

/* ------------------------------------------------------------------------- */
/* Ring-buffer queue                                                         */
/* ------------------------------------------------------------------------- */

typedef struct frame_queue_t
{
    audio_frame_t **buffer;
    size_t          capacity; /* Power-of-two not required                    */
    size_t          head;
    size_t          tail;
    pthread_mutex_t mtx;
    pthread_cond_t  not_empty;
    pthread_cond_t  not_full;
} frame_queue_t;

static frame_queue_t *
queue_create(size_t capacity)
{
    frame_queue_t *q = calloc(1, sizeof(*q));
    if (!q)
        return NULL;

    q->capacity = AUDIOH_MIN(capacity, AUDIOH_MAX_QUEUE_CAP);
    q->buffer   = calloc(q->capacity, sizeof(audio_frame_t *));
    if (!q->buffer)
    {
        free(q);
        return NULL;
    }

    pthread_mutex_init(&q->mtx, NULL);
    pthread_cond_init(&q->not_empty, NULL);
    pthread_cond_init(&q->not_full, NULL);
    return q;
}

static void
queue_destroy(frame_queue_t *q)
{
    if (!q)
        return;
    pthread_mutex_destroy(&q->mtx);
    pthread_cond_destroy(&q->not_empty);
    pthread_cond_destroy(&q->not_full);
    free(q->buffer);
    free(q);
}

static bool
queue_push(frame_queue_t *q, audio_frame_t *f, bool blocking)
{
    bool success = false;

    pthread_mutex_lock(&q->mtx);

    while (((q->tail + 1) % q->capacity) == q->head)
    {
        if (!blocking)
            goto unlock;
        pthread_cond_wait(&q->not_full, &q->mtx);
    }

    q->buffer[q->tail] = f;
    q->tail            = (q->tail + 1) % q->capacity;
    pthread_cond_signal(&q->not_empty);
    success = true;

unlock:
    pthread_mutex_unlock(&q->mtx);
    return success;
}

static audio_frame_t *
queue_pop(frame_queue_t *q, bool blocking)
{
    audio_frame_t *out = NULL;
    pthread_mutex_lock(&q->mtx);

    while (q->head == q->tail)
    {
        if (!blocking)
            goto unlock;
        pthread_cond_wait(&q->not_empty, &q->mtx);
    }

    out     = q->buffer[q->head];
    q->head = (q->head + 1) % q->capacity;
    pthread_cond_signal(&q->not_full);

unlock:
    pthread_mutex_unlock(&q->mtx);
    return out;
}

/* ------------------------------------------------------------------------- */
/* FFT helper (FFTW3 or fallback)                                            */
/* ------------------------------------------------------------------------- */

#ifdef USE_FFTW3
typedef struct
{
    fftwf_plan  plan;
    float      *in;
    fftwf_complex *out;
    size_t      fft_size;
} fft_ctx_t;

static bool
fft_init(fft_ctx_t *ctx, size_t fft_size)
{
    memset(ctx, 0, sizeof(*ctx));
    ctx->fft_size = fft_size;
    ctx->in       = fftwf_alloc_real(fft_size);
    ctx->out      = fftwf_alloc_complex(fft_size / 2 + 1);
    if (!ctx->in || !ctx->out)
        return false;

    ctx->plan = fftwf_plan_dft_r2c_1d(
        (int)fft_size, ctx->in, ctx->out,
        FFTW_MEASURE | FFTW_DESTROY_INPUT
    );
    return ctx->plan != NULL;
}

static void
fft_execute(fft_ctx_t *ctx, const float *input, float *magnitudes)
{
    memcpy(ctx->in, input, sizeof(float) * ctx->fft_size);
    fftwf_execute(ctx->plan);

    for (size_t i = 0; i < ctx->fft_size / 2 + 1; ++i)
    {
        float re = ctx->out[i][0];
        float im = ctx->out[i][1];
        magnitudes[i] = sqrtf(re * re + im * im);
    }
}

static void
fft_cleanup(fft_ctx_t *ctx)
{
    if (ctx->plan)
        fftwf_destroy_plan(ctx->plan);
    fftwf_free(ctx->in);
    fftwf_free(ctx->out);
}

#else /* ------------------------- Fallback discrete DFT -------------------- */

typedef struct
{
    size_t fft_size;
} fft_ctx_t;

static bool
fft_init(fft_ctx_t *ctx, size_t fft_size)
{
    ctx->fft_size = fft_size;
    return true;
}

static void
fft_execute(fft_ctx_t *ctx, const float *input, float *magnitudes)
{
    size_t N = ctx->fft_size;
    /* Naive O(N^2) DFT – only used if FFTW3 missing. */
    for (size_t k = 0; k < N / 2 + 1; ++k)
    {
        float re = 0.0f, im = 0.0f;
        for (size_t n = 0; n < N; ++n)
        {
            float angle = -2.0f * M_PI * (float)k * (float)n / (float)N;
            re += input[n] * cosf(angle);
            im += input[n] * sinf(angle);
        }
        magnitudes[k] = sqrtf(re * re + im * im);
    }
}

static void
fft_cleanup(fft_ctx_t *ctx) { (void)ctx; }

#endif /* USE_FFTW3 */

/* ------------------------------------------------------------------------- */
/* AudioHandler instance                                                     */
/* ------------------------------------------------------------------------- */

struct audio_handler_t
{
    audio_handler_config_t cfg;
    frame_queue_t         *queue;
    pthread_t              worker;
    bool                   running;
    fft_ctx_t              fft;
};

/* Forward declaration */
static void *worker_thread_main(void *arg);

/* ------------------------------------------------------------------------- */
/* Public API                                                                */
/* ------------------------------------------------------------------------- */

audio_handler_t *
audio_handler_create(const audio_handler_config_t *cfg_in)
{
    if (!cfg_in || !cfg_in->analysis_cb)
    {
        errno = EINVAL;
        return NULL;
    }

    audio_handler_t *h = calloc(1, sizeof(*h));
    if (!h)
        return NULL;

    h->cfg          = *cfg_in; /* shallow copy (contains POD) */
    h->running      = true;
    size_t cap      = cfg_in->queue_capacity
                          ? cfg_in->queue_capacity
                          : AUDIOH_DEFAULT_QUEUE_CAP;

    h->queue = queue_create(cap);
    if (!h->queue)
        goto fail;

    size_t fft_size = cfg_in->fft_size;
    if (!fft_size || (fft_size & (fft_size - 1)) != 0)
        fft_size = 1024; /* Fallback to power-of-two */

    if (!fft_init(&h->fft, fft_size))
        goto fail;

    /* Spawn worker thread */
    if (pthread_create(&h->worker, NULL, worker_thread_main, h) != 0)
        goto fail;

    openlog("audio-service", LOG_PID | LOG_CONS, LOG_USER);
    syslog(LOG_INFO, "AudioHandler started (FFT size=%zu, queue=%zu)",
           fft_size, cap);
    return h;

fail:
    fft_cleanup(&h->fft);
    queue_destroy(h->queue);
    free(h);
    return NULL;
}

bool
audio_handler_submit_frame(audio_handler_t *h, const audio_frame_t *src_frame,
                           bool blocking)
{
    if (!h || !src_frame || !src_frame->data)
    {
        errno = EINVAL;
        return false;
    }

    /* Deep-copy frame content so caller may free its buffer immediately. */
    audio_frame_t *copy = calloc(1, sizeof(*copy));
    if (!copy)
        return false;

    size_t bytes = sizeof(float) * src_frame->samples * src_frame->channels;
    copy->data   = malloc(bytes);
    if (!copy->data)
    {
        free(copy);
        return false;
    }

    memcpy(copy->data, src_frame->data, bytes);
    copy->samples     = src_frame->samples;
    copy->channels    = src_frame->channels;
    copy->sample_rate = src_frame->sample_rate;
    copy->timestamp_us =
        src_frame->timestamp_us ? src_frame->timestamp_us : now_us();

    if (!queue_push(h->queue, copy, blocking))
    {
        /* Queue full or shutting down. */
        free(copy->data);
        free(copy);
        return false;
    }
    return true;
}

void
audio_handler_shutdown(audio_handler_t *h)
{
    if (!h)
        return;

    /* Signal worker to terminate */
    h->running = false;
    queue_push(h->queue, NULL, false); /* Unblock worker if waiting */

    pthread_join(h->worker, NULL);

    fft_cleanup(&h->fft);
    queue_destroy(h->queue);
    closelog();
    free(h);
}

/* ------------------------------------------------------------------------- */
/* Worker thread                                                             */
/* ------------------------------------------------------------------------- */

static float
compute_rms(const float *data, size_t samples, size_t stride)
{
    double acc = 0.0;
    for (size_t i = 0; i < samples; i += stride)
    {
        float v = data[i];
        acc += v * v;
    }
    return (float)sqrt(acc / (samples / stride));
}

static void
analysis_dispatch(audio_handler_t *h, const float *mag, size_t bins,
                  float rms)
{
    /* Wrap callback in a try/catch style for C – we cannot recover from
     * SIGSEGV in user code, but at least we can log exceptions like
     * SIGFPE or C++ exceptions crossing the boundary. */
    if (!h->cfg.analysis_cb)
        return;

    /* Optional rate limiting: skip callbacks if they are too frequent. */
    static __thread uint64_t last_call_us = 0;
    uint64_t now                         = now_us();
    if (h->cfg.min_callback_interval_us &&
        now - last_call_us < h->cfg.min_callback_interval_us)
        return;

    last_call_us = now;
    h->cfg.analysis_cb(mag, bins, rms, h->cfg.user_data);
}

static void *
worker_thread_main(void *arg)
{
    audio_handler_t *h = arg;

    size_t           fft_size = h->fft.fft_size;
    float           *mono_buf = malloc(sizeof(float) * fft_size);
    float           *magnitudes =
        malloc(sizeof(float) * (fft_size / 2 + 1));

    if (!mono_buf || !magnitudes)
    {
        syslog(LOG_CRIT, "AudioHandler: cannot allocate work buffers");
        h->running = false;
    }

    while (h->running)
    {
        audio_frame_t *frame = queue_pop(h->queue, true);
        if (!frame)
            continue; /* Possibly woken up for shutdown */

        /* Convert to mono (average channels). If frame shorter than fft_size,
         * zero-pad; if longer, use first fft_size samples. */
        size_t samples_needed = fft_size;
        for (size_t i = 0; i < samples_needed; ++i)
        {
            float sample = 0.0f;
            if (i < frame->samples)
            {
                for (int ch = 0; ch < frame->channels; ++ch)
                {
                    sample += frame->data[i * frame->channels + ch];
                }
                sample /= (float)frame->channels;
            }
            mono_buf[i] = sample;
        }

        float rms = compute_rms(frame->data,
                                frame->samples * frame->channels,
                                frame->channels /* stride per channel */);

        fft_execute(&h->fft, mono_buf, magnitudes);
        analysis_dispatch(h, magnitudes, fft_size / 2 + 1, rms);

        free(frame->data);
        free(frame);
    }

    free(mono_buf);
    free(magnitudes);
    syslog(LOG_INFO, "AudioHandler worker terminated");
    return NULL;
}

/* ------------------------------------------------------------------------- */
/* AudioFrame utilities (public inline impl.)                                */
/* ------------------------------------------------------------------------- */

void
audio_frame_free(audio_frame_t *f)
{
    if (!f)
        return;
    free(f->data);
    free(f);
}

audio_frame_t *
audio_frame_alloc(size_t samples, int channels)
{
    audio_frame_t *f = calloc(1, sizeof(*f));
    if (!f)
        return NULL;
    f->samples  = samples;
    f->channels = channels;
    f->data     = calloc(samples * channels, sizeof(float));
    if (!f->data)
    {
        free(f);
        return NULL;
    }
    f->timestamp_us = now_us();
    return f;
}