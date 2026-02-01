/**
 * File: palette.h
 * Path: SynestheticCanvas/services/palette-service/include/models/palette.h
 * Project: SynestheticCanvas API Suite (api_graphql)
 *
 * Description:
 *   Public data-model for the Palette domain used by the Palette Service.
 *   A palette is a mutable, versioned collection of colors (RGBA) with
 *   optional metadata.  The model is designed for low-latency operations
 *   and zero-copy interchange between REST / GraphQL layers and the
 *   underlying repository-adapter.
 *
 *   The palette API uses opaque handles—clients only see a forward
 *   declaration of the struct and must interact through the provided
 *   functions.  This allows the backing store to switch between heap,
 *   shared-memory, or memory-mapped files without breaking ABI.
 *
 *   Thread-safety:
 *     The palette API is NOT thread-safe by default.  Callers must
 *     provide their own concurrency control (e.g., via the locking
 *     utilities in  <utils/rwlock.h>).
 *
 * Copyright:
 *   © 2023-2024 SynestheticCanvas Contributors. Distributed under the
 *   Apache-2.0 license.  See LICENSE.txt for details.
 */

#ifndef SYNESTHETIC_CANVAS_PALETTE_H
#define SYNESTHETIC_CANVAS_PALETTE_H

/* ────────────────────────────────────────────────────────────────────────── */
/* System headers                                                            */
#include <stdbool.h>    /* bool                                             */
#include <stddef.h>     /* size_t                                           */
#include <stdint.h>     /* uint*_t                                          */

#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Constants                                                                 */

/* Maximum UTF-8 code-units allocated for palette name (excludes null byte) */
#define SC_PALETTE_MAX_NAME_LEN  64U

/* Maximum number of colors a palette may hold in memory.  Repository layers
 * MAY override this via configuration, but the compile-time bound prevents
 * runaway allocations when hydration is bypassed.
 */
#define SC_PALETTE_MAX_COLORS    4096U

/* ────────────────────────────────────────────────────────────────────────── */
/* Public data types                                                         */

/**
 * A single RGBA color (8-bit channels).
 *
 * Layout is identical to many GPU APIs and can be streamed directly
 * to little-endian frame-buffers.
 */
typedef struct
{
    uint8_t r;  /* Red   [0-255] */
    uint8_t g;  /* Green [0-255] */
    uint8_t b;  /* Blue  [0-255] */
    uint8_t a;  /* Alpha [0-255] */
} sc_color_t;


/**
 * Error/Status codes returned by palette operations.
 *
 * All functions return one of these values.  The enum is stable and can
 * be surfaced over FFI / RPC boundaries.
 */
typedef enum
{
    SC_PALETTE_OK = 0,

    /* Standard failures */
    SC_PALETTE_ERR_NULL_PTR,
    SC_PALETTE_ERR_OOM,
    SC_PALETTE_ERR_INDEX_OOB,
    SC_PALETTE_ERR_CAPACITY,          /* Exceeded SC_PALETTE_MAX_COLORS */
    SC_PALETTE_ERR_NAME_TOO_LONG,
    SC_PALETTE_ERR_SERIALIZE,
    SC_PALETTE_ERR_DESERIALIZE,
    SC_PALETTE_ERR_VALIDATION,

    /* I/O / Repository */
    SC_PALETTE_ERR_IO,
    SC_PALETTE_ERR_NOT_FOUND,
    SC_PALETTE_ERR_CONFLICT,

    /* Unknown/unexpected */
    SC_PALETTE_ERR_UNKNOWN
} sc_palette_status_t;


/* Forward declaration — struct layout hidden from consumers */
typedef struct sc_palette sc_palette_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Life-cycle management                                                     */

/**
 * Allocate a new palette.
 *
 * Parameters:
 *   name   Optional, NULL-terminated UTF-8 string. A copy is made;
 *          truncated if longer than SC_PALETTE_MAX_NAME_LEN.
 *   out    (out-param) Receives pointer to allocated palette on success.
 *
 * Returns:
 *   SC_PALETTE_OK if successful, error code otherwise.
 */
sc_palette_status_t
sc_palette_create(const char *name, sc_palette_t **out);

/**
 * Release resources held by a palette.
 *
 *   After return, *palette is set to NULL to avoid dangling pointers.
 *   Safe to pass NULL.
 */
void
sc_palette_destroy(sc_palette_t **palette);

/* ────────────────────────────────────────────────────────────────────────── */
/* Metadata                                                                  */

/**
 * Returns a read-only pointer to the palette's name (null-terminated).
 * String is owned by the palette instance and must NOT be freed.
 *
 * Returns NULL if palette is NULL.
 */
const char *
sc_palette_name(const sc_palette_t *palette);

/**
 * Overwrite the palette name.
 *
 * Params:
 *   palette  Palette instance.
 *   name     UTF-8 string to copy.
 *
 * Returns:
 *   SC_PALETTE_OK or SC_PALETTE_ERR_NAME_TOO_LONG / _NULL_PTR.
 */
sc_palette_status_t
sc_palette_set_name(sc_palette_t *palette, const char *name);

/**
 * Current number of colors held by the palette.
 *
 * Returns 0 if palette is NULL.
 */
size_t
sc_palette_size(const sc_palette_t *palette);

/* ────────────────────────────────────────────────────────────────────────── */
/* Mutation                                                                  */

/**
 * Append a color to the end of the palette.
 *
 * Returns SC_PALETTE_ERR_CAPACITY if SC_PALETTE_MAX_COLORS reached.
 */
sc_palette_status_t
sc_palette_push(sc_palette_t *palette, sc_color_t color);

/**
 * Insert color at index, shifting subsequent colors right.
 *
 * Params:
 *   index 0-based.  Must be <= size (inserting at end is allowed).
 */
sc_palette_status_t
sc_palette_insert(sc_palette_t *palette, size_t index, sc_color_t color);

/**
 * Remove color at index, shifting subsequent colors left.
 *
 * Out param (removed) may be NULL if caller uninterested.
 */
sc_palette_status_t
sc_palette_remove(sc_palette_t *palette, size_t index, sc_color_t *removed);

/* ────────────────────────────────────────────────────────────────────────── */
/* Query                                                                     */

/**
 * Retrieve color at index.
 */
sc_palette_status_t
sc_palette_get(const sc_palette_t *palette, size_t index, sc_color_t *out);

/**
 * Find the first occurrence of a color within the palette.  Color
 * equality is byte-wise (r, g, b, a all equal).
 *
 * On success, *index is set to the match location.
 *
 * Returns:
 *   SC_PALETTE_OK       if found
 *   SC_PALETTE_ERR_NOT_FOUND if no match
 */
sc_palette_status_t
sc_palette_find(const sc_palette_t *palette,
                sc_color_t           needle,
                size_t              *index);

/* ────────────────────────────────────────────────────────────────────────── */
/* Serialization                                                             */

/**
 * Serialize palette to a JSON document compatible with GraphQL clients.
 *
 * Caller owns the returned buffer and must free() it.  Length (in bytes)
 * is written to *out_len if that pointer is non-NULL.
 *
 * Format:
 *   {
 *     "name": "<name>",
 *     "colors": ["#RRGGBBAA", ...]
 *   }
 */
sc_palette_status_t
sc_palette_to_json(const sc_palette_t *palette, char **out_json, size_t *out_len);

/**
 * Deserialize a palette from JSON (same schema as sc_palette_to_json).
 *
 * Existing *palette will be destroyed if supplied.  When *palette is NULL,
 * the function allocates a new instance.
 */
sc_palette_status_t
sc_palette_from_json(const char *json, sc_palette_t **palette);

/* ────────────────────────────────────────────────────────────────────────── */
/* Validation                                                                */

/**
 * Validate that the palette adheres to all service invariants, including:
 *   - Non-empty name
 *   - At least one color
 *
 * Returns:
 *   SC_PALETTE_OK        if valid
 *   SC_PALETTE_ERR_VALIDATION otherwise
 */
sc_palette_status_t
sc_palette_validate(const sc_palette_t *palette);

/* ────────────────────────────────────────────────────────────────────────── */

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* SYNESTHETIC_CANVAS_PALETTE_H */
