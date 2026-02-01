/**
 * @file text_cleaner.h
 * @author 
 * @brief Public API for the LexiLearn NLP text-preprocessing module.
 *
 * This component is responsible for turning raw textual inputs
 * (e.g., essays, discussion-board posts, transcribed speech) into a
 * canonical form before they are fed into higher-level feature
 * extractors and model pipelines.
 *
 * Design highlights
 * -----------------
 * • Strategy-Friendly: The TextCleaner exposes a narrowly-scoped C API so
 *   that different concrete implementations (rule-based, ICU-powered,
 *   language-specific tokenizers, etc.) can be swapped at link-time or
 *   run-time through the Strategy Pattern embraced by the wider project.
 * • Thread-Safe: All state is encapsulated in an opaque handle
 *   (TextCleaner), allowing multiple independent cleaners to run in
 *   parallel processing pipelines.
 * • MLOps-Ready: Rich structured logging hooks are provided in order to
 *   propagate preprocessing statistics to the centralized Model Registry.
 *
 * The corresponding implementation lives in
 * `text_cleaner.c`.  No implementation details leak into this header.
 *
 * 2024 © LexiLearn Consortium — All rights reserved.
 */

#ifndef LEXILEARN_MODEL_PREPROCESSING_TEXT_CLEANER_H
#define LEXILEARN_MODEL_PREPROCESSING_TEXT_CLEANER_H

/* -------------------------------------------------------------------------- */
/* Dependencies                                                               */
/* -------------------------------------------------------------------------- */
#include <stddef.h>   /* size_t */
#include <stdint.h>   /* uint32_t */
#include <stdbool.h>  /* bool   */

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------- */
/* Versioning                                                                 */
/* -------------------------------------------------------------------------- */
#define TEXT_CLEANER_VERSION_MAJOR 1
#define TEXT_CLEANER_VERSION_MINOR 0
#define TEXT_CLEANER_VERSION_PATCH 0

/* Helper macro for compile-time version checking. */
#define TEXT_CLEANER_VERSION_ENCODE(maj, min, pat) (((maj) << 16) | ((min) << 8) | (pat))
#define TEXT_CLEANER_VERSION \
    TEXT_CLEANER_VERSION_ENCODE(TEXT_CLEANER_VERSION_MAJOR, \
                                TEXT_CLEANER_VERSION_MINOR, \
                                TEXT_CLEANER_VERSION_PATCH)

/* -------------------------------------------------------------------------- */
/* Error Codes                                                                */
/* -------------------------------------------------------------------------- */
typedef enum {
    TC_OK = 0,
    TC_ERR_INVALID_ARGUMENT,   /* Null ptrs, invalid enum, … */
    TC_ERR_IO,                 /* Failed to open stop-word list, etc. */
    TC_ERR_MEMORY,             /* malloc/calloc failed               */
    TC_ERR_BUFFER_TOO_SMALL,   /* Output buffer insufficient          */
    TC_ERR_INTERNAL            /* Any non-recoverable error           */
} tc_status_t;

/* -------------------------------------------------------------------------- */
/* Configuration                                                              */
/* -------------------------------------------------------------------------- */

/**
 * @brief Bit-mask for enabling optional cleaning passes.
 *
 * The default pass is the “core” pass which lower-cases UTF-8, strips
 * punctuation, and normalizes whitespace.
 */
typedef enum {
    TC_CLEAN_NONE          = 0u,
    TC_CLEAN_STRIP_DIGITS  = 1u << 0, /* Remove ASCII and Unicode digits. */
    TC_CLEAN_STRIP_HTML    = 1u << 1, /* Remove simple HTML tags          */
    TC_CLEAN_STRIP_STOPW   = 1u << 2, /* Remove stop-words (requires list)*/
    TC_CLEAN_STEM_TOKENS   = 1u << 3, /* Apply Porter stemmer             */
    TC_CLEAN_DEFAULT       = TC_CLEAN_STRIP_HTML | TC_CLEAN_STRIP_STOPW
} tc_clean_pass_t;

/**
 * @brief Optional structured logging callback.
 *
 * Allows the broader MLOps pipeline to collect preprocessing metrics
 * (e.g., # of tokens kept vs. removed) in a decentralized fashion.
 *
 * The `user_ctx` pointer can be used to pass arbitrary application data.
 */
typedef void (*tc_log_fn)(
        const char *event_key,
        const char *json_payload,
        void       *user_ctx);

/**
 * @brief Runtime configuration object for a TextCleaner.
 *
 * The struct may be stack-allocated by callers and passed by value to
 * `tc_create()`.  All members have sensible defaults; callers may
 * zero-initialize the struct and then override as needed.
 */
typedef struct tc_config {
    uint32_t       passes;            /* Bit-mask from tc_clean_pass_t      */
    const char    *stopword_path;     /* UTF-8 file containing stop words   */
    tc_log_fn      log_cb;            /* Optional logging callback          */
    void          *log_user_ctx;      /* Passed back to logger verbatim     */
    size_t         max_token_len;     /* Hard cap to guard against OOMs     */
} tc_config_t;

/* -------------------------------------------------------------------------- */
/* Opaque Handle                                                              */
/* -------------------------------------------------------------------------- */
typedef struct text_cleaner  TextCleaner; /* Forward declaration (opaque)    */

/* -------------------------------------------------------------------------- */
/* Public API                                                                 */
/* -------------------------------------------------------------------------- */

/**
 * @brief Instantiate a new TextCleaner with the supplied configuration.
 *
 * Thread-safe: multiple independent cleaners may be created
 * concurrently.  Returns NULL and sets `*status` on failure.
 *
 * @param cfg     Pointer to a tc_config_t (may be NULL for defaults).
 * @param status  Optional out-param for detailed error reporting.
 */
TextCleaner *tc_create(const tc_config_t *cfg, tc_status_t *status);

/**
 * @brief Destroy a TextCleaner and free all associated resources.
 *
 * Passing NULL is a no-op.
 */
void tc_destroy(TextCleaner *cleaner);

/**
 * @brief Clean the supplied UTF-8 text into the provided output buffer.
 *
 * The input string does not have to be NUL-terminated; length in bytes
 * must be supplied.  Output will be NUL-terminated on success.  If the
 * buffer is too small, `TC_ERR_BUFFER_TOO_SMALL` is returned and the
 * required size (including NUL terminator) is written to `*bytes_written`.
 *
 * @note The function performs zero dynamic allocations in the hot path
 *       for predictable latency in real-time pipelines.
 *
 * @param cleaner        Valid TextCleaner handle.
 * @param in_utf8        Pointer to raw UTF-8 text.
 * @param in_len         Length of input (bytes).
 * @param out_buf        Caller-allocated buffer to receive cleaned text.
 * @param out_buf_size   Size of `out_buf` in bytes.
 * @param bytes_written  Out-param; set to # of bytes written or required.
 *
 * @return tc_status_t   TC_OK on success or an error code.
 */
tc_status_t tc_clean(
        TextCleaner   *cleaner,
        const char    *in_utf8,
        size_t         in_len,
        char          *out_buf,
        size_t         out_buf_size,
        size_t        *bytes_written);

/**
 * @brief Convenience wrapper that allocates an output buffer internally.
 *
 * This helper hides dynamic allocation details from the caller.  The
 * buffer is allocated using `malloc()` and must be freed with `free()`
 * by the caller when no longer needed.
 *
 * @param cleaner      Valid TextCleaner handle.
 * @param in_utf8      Pointer to raw UTF-8 text (NUL-terminated).
 * @param out_str      Out-param; on success points to malloc'd string.
 *
 * @return tc_status_t TC_OK on success or an error code on failure.
 */
tc_status_t tc_clean_dup(
        TextCleaner *cleaner,
        const char  *in_utf8,
        char       **out_str);

/* -------------------------------------------------------------------------- */
/* Utility Helpers                                                            */
/* -------------------------------------------------------------------------- */

/**
 * @brief Retrieve the human-readable string associated with an error code.
 *
 * Returned pointer is to a static, immutable string; no free required.
 */
const char *tc_status_string(tc_status_t code);

/**
 * @brief Returns the compile-time version of the library that the header
 *        was built with.  Useful for ensuring ABI compatibility.
 */
static inline uint32_t tc_version(void)
{
    return TEXT_CLEANER_VERSION;
}

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* LEXILEARN_MODEL_PREPROCESSING_TEXT_CLEANER_H */
