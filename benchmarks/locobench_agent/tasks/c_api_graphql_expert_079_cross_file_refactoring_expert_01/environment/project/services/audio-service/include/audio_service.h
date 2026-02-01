/*
 * SynestheticCanvas - Audio Service
 * ---------------------------------
 * Production-grade public API for low-latency audio capture/playback
 * and analysis used by the “audio-reactive animation” micro-service
 * of the SynestheticCanvas constellation.
 *
 * This header purposefully hides implementation details and exposes
 * a minimal, backend-agnostic surface that can be consumed by the HTTP/
 * GraphQL façade or by other internal services (texture-synthesis,
 * narrative engine, etc.).
 *
 * Author:  SynestheticCanvas Core Team
 * License: MIT (see LICENSE file at repository root)
 */

#ifndef SYNESTHETIC_CANVAS_AUDIO_SERVICE_H
#define SYNESTHETIC_CANVAS_AUDIO_SERVICE_H

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------------- */
/*  Standard Library                                                          */
/* ------------------------------------------------------------------------- */
#include <stddef.h>     /* size_t                                            */
#include <stdint.h>     /* uint32_t, uint64_t                                */
#include <stdbool.h>    /* bool                                              */
#include <math.h>       /* sqrtf                                             */

/* ------------------------------------------------------------------------- */
/*  Versioning                                                                */
/* ------------------------------------------------------------------------- */
#define AUDIO_SERVICE_MAJOR_VERSION  1
#define AUDIO_SERVICE_MINOR_VERSION  2
#define AUDIO_SERVICE_PATCH_VERSION  0
#define AUDIO_SERVICE_VERSION_STRING "1.2.0"

/* Compile-time helper to guard against mixing incompatible headers/binaries */
#define AUDIO_SERVICE_CHECK_VERSION(maj, min) \
    ((maj) == AUDIO_SERVICE_MAJOR_VERSION &&  \
     (min) <= AUDIO_SERVICE_MINOR_VERSION)

/* ------------------------------------------------------------------------- */
/*  Enumerations                                                              */
/* ------------------------------------------------------------------------- */

/* Backend enumerations – automatically selected when set to AUTO            */
typedef enum
{
    AUDIO_BACKEND_AUTO = 0,
    AUDIO_BACKEND_ALSA,
    AUDIO_BACKEND_PULSEAUDIO,
    AUDIO_BACKEND_COREAUDIO,
    AUDIO_BACKEND_WASAPI,
    AUDIO_BACKEND_JACK,
    AUDIO_BACKEND_DUMMY     /* no-op fake backend used in CI                 */
} audio_backend_t;

/* Unified error codes returned by every public function                     */
typedef enum
{
    AUDIO_SERVICE_OK = 0,
    AUDIO_SERVICE_ERR_INVALID_ARGUMENT,
    AUDIO_SERVICE_ERR_BACKEND_UNAVAILABLE,
    AUDIO_SERVICE_ERR_DEVICE_NOT_FOUND,
    AUDIO_SERVICE_ERR_STREAM_ALREADY_RUNNING,
    AUDIO_SERVICE_ERR_STREAM_CLOSED,
    AUDIO_SERVICE_ERR_NOT_INITIALISED,
    AUDIO_SERVICE_ERR_OUT_OF_MEMORY,
    AUDIO_SERVICE_ERR_INTERNAL,
    AUDIO_SERVICE_ERR_UNSUPPORTED
} audio_service_error_t;

/* Log severity used by the user-supplied logger callback                    */
typedef enum
{
    AUDIO_LOG_TRACE = 0,
    AUDIO_LOG_DEBUG,
    AUDIO_LOG_INFO,
    AUDIO_LOG_WARN,
    AUDIO_LOG_ERROR,
    AUDIO_LOG_FATAL
} audio_log_severity_t;

/* ------------------------------------------------------------------------- */
/*  Forward Declarations & Typedefs                                           */
/* ------------------------------------------------------------------------- */
typedef struct audio_service       audio_service_t; /* Opaque service handle */

typedef struct
{
    const float *interleaved_samples;     /* Interleaved PCM frames          */
    uint32_t     frames;                  /* Frames per channel              */
    uint32_t     channels;                /* 1 = mono, 2 = stereo, …         */
    uint32_t     sample_rate;             /* Hz                               */
    uint64_t     presentation_timestamp;  /* µs, monotonic clock             */
} audio_frame_t;

/* Delivered every time a new buffer is ready (called from I/O thread)       */
typedef void (*audio_frame_cb)(const audio_frame_t *frame, void *user_data);

/* User-provided logger                                                      */
typedef void (*audio_log_cb)(audio_log_severity_t sev,
                             const char          *component,
                             const char          *message,
                             void                *user_data);

/* ------------------------------------------------------------------------- */
/*  Configuration struct                                                      */
/* ------------------------------------------------------------------------- */
typedef struct
{
    /* I/O setup ----------------------------------------------------------- */
    audio_backend_t backend;               /* AUTO picks best possible       */
    const char     *device;                /* NULL = default device          */
    uint32_t        desired_sample_rate;   /* 0 = backend default            */
    uint32_t        desired_channels;      /* 0 = backend default            */
    uint32_t        buffer_frames;         /* Block size for callback        */
    bool            enable_input;          /* Capture microphone/line-in     */
    bool            enable_output;         /* Allow playback                 */

    /* Logging ------------------------------------------------------------- */
    audio_log_cb            log_fn;        /* Optional                       */
    void                   *log_userdata;  /* User data for logger           */
    audio_log_severity_t    log_level;     /* Minimum severity accepted      */

    /* Advanced ------------------------------------------------------------ */
    uint32_t        startup_timeout_ms;    /* Fail fast on slow backends     */
} audio_service_config_t;

/* ------------------------------------------------------------------------- */
/*  Public API                                                                */
/* ------------------------------------------------------------------------- */

/*
 * audio_service_create()
 * ----------------------
 * Instantiates a new audio_service_t handle. The function will probe the
 * requested backend (or automatically pick the most suitable one) and open
 * the audio device. All heavy lifting (allocation, thread creation, etc.) is
 * performed here so that subsequent operations are low-latency.
 *
 * The call is thread-safe and may be invoked concurrently for multiple
 * independent instances.
 */
audio_service_error_t
audio_service_create(const audio_service_config_t *cfg,
                     audio_service_t             **out_service);

/*
 * audio_service_destroy()
 * -----------------------
 * Frees all resources associated with a service instance. If streaming is
 * currently active it will be stopped first.
 *
 * The pointer is set to NULL on return to avoid accidental reuse.
 */
void
audio_service_destroy(audio_service_t **svc);

/*
 * audio_service_get_config()
 * --------------------------
 * Returns the (read-only) configuration used during initialisation.
 */
const audio_service_config_t *
audio_service_get_config(const audio_service_t *svc);

/*
 * audio_service_start()
 * ---------------------
 * Starts the I/O thread and begins pulling / pushing audio buffers from /
 * to the selected backend. Sample blocks are delivered to the user callback
 * registered via audio_service_set_frame_callback().
 *
 * Returns AUDIO_SERVICE_ERR_STREAM_ALREADY_RUNNING when called again.
 */
audio_service_error_t
audio_service_start(audio_service_t *svc);

/*
 * audio_service_stop()
 * --------------------
 * Stops the streaming thread and flushes remaining buffers.
 */
audio_service_error_t
audio_service_stop(audio_service_t *svc);

/*
 * audio_service_flush()
 * ---------------------
 * Blocks until internal ring-buffers are empty or the timeout (in ms)
 * elapses. Pass 0 to wait indefinitely.
 */
audio_service_error_t
audio_service_flush(audio_service_t *svc,
                    uint32_t         timeout_ms);

/*
 * audio_service_is_running()
 * --------------------------
 * Cheap query used by monitoring endpoints.
 */
bool
audio_service_is_running(const audio_service_t *svc);

/*
 * audio_service_set_frame_callback()
 * ----------------------------------
 * Registers (or replaces) the function that receives audio frames. Passing
 * NULL disables callbacks completely (useful for silent capture).
 */
void
audio_service_set_frame_callback(audio_service_t *svc,
                                 audio_frame_cb   cb,
                                 void            *user_data);

/*
 * audio_service_fft()
 * -------------------
 * Provides a one-stop convenience wrapper around the platform’s FFT
 * implementation, automatically vectorised where available (NEON/SSE/AVX).
 *
 * The caller supplies an aligned buffer of ‘sample_count * 2’ floats
 * containing time-domain samples (imag part implicitly zero) which will be
 * transformed in place into frequency-domain complex numbers
 * (interleaved real/imag). If ‘out_spectra’ is non-NULL, the magnitude for
 * each bin (sqrt(re²+im²)) will be written.
 *
 * The function is *not* real-time safe and should be executed off the audio
 * thread.
 */
audio_service_error_t
audio_service_fft(audio_service_t *svc,
                  float           *samples,
                  size_t           sample_count,
                  float           *out_spectra);

/* ------------------------------------------------------------------------- */
/*  Inline Utilities                                                          */
/* ------------------------------------------------------------------------- */

/* Convert error code to human-readable string ----------------------------- */
static inline const char *
audio_service_error_str(audio_service_error_t err)
{
    switch (err)
    {
        case AUDIO_SERVICE_OK:                     return "ok";
        case AUDIO_SERVICE_ERR_INVALID_ARGUMENT:   return "invalid argument";
        case AUDIO_SERVICE_ERR_BACKEND_UNAVAILABLE:return "backend unavailable";
        case AUDIO_SERVICE_ERR_DEVICE_NOT_FOUND:   return "device not found";
        case AUDIO_SERVICE_ERR_STREAM_ALREADY_RUNNING:return "stream already running";
        case AUDIO_SERVICE_ERR_STREAM_CLOSED:      return "stream closed";
        case AUDIO_SERVICE_ERR_NOT_INITIALISED:    return "not initialised";
        case AUDIO_SERVICE_ERR_OUT_OF_MEMORY:      return "out of memory";
        case AUDIO_SERVICE_ERR_INTERNAL:           return "internal error";
        case AUDIO_SERVICE_ERR_UNSUPPORTED:        return "unsupported";
        default:                                   return "unknown error";
    }
}

/* Convert severity enum to string ----------------------------------------- */
static inline const char *
audio_log_severity_str(audio_log_severity_t sev)
{
    switch (sev)
    {
        case AUDIO_LOG_TRACE: return "TRACE";
        case AUDIO_LOG_DEBUG: return "DEBUG";
        case AUDIO_LOG_INFO:  return "INFO";
        case AUDIO_LOG_WARN:  return "WARN";
        case AUDIO_LOG_ERROR: return "ERROR";
        case AUDIO_LOG_FATAL: return "FATAL";
        default:              return "UNKNOWN";
    }
}

/* Simple RMS helper (branch-free inner loop) ------------------------------ */
static inline float
audio_service_rms(const float *samples,
                  size_t       sample_count,
                  uint32_t     channels)
{
    if (!samples || sample_count == 0 || channels == 0)
        return 0.0f;

    const size_t total = sample_count * channels;
    double sum = 0.0;

    for (size_t i = 0; i < total; ++i)
    {
        const double s = samples[i];
        sum += s * s;
    }

    return (float)sqrt(sum / (double)total);
}

#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* SYNESTHETIC_CANVAS_AUDIO_SERVICE_H */
