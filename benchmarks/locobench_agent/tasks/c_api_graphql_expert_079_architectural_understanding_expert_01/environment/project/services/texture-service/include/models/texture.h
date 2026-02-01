/*
 * SynestheticCanvas Texture Model
 * File: SynestheticCanvas/services/texture-service/include/models/texture.h
 *
 * Description:
 *   Core data structures and helper utilities required by the Texture-Service
 *   to represent raw and compressed texture payloads travelling between the
 *   service layer, repository adapters, and network serializers (GraphQL/REST).
 *
 *   The interface purposefully hides implementation detail behind a narrow,
 *   C-friendly API boundary.  Callers are expected to treat sc_texture_t as an
 *   opaque value – with the exception of read-only meta-data fields that are
 *   explicitly documented below.
 *
 * Copyright (c) 2024
 * SPDX-License-Identifier: MIT
 */

#ifndef SC_TEXTURE_H
#define SC_TEXTURE_H

/* ────────────────────────────────────────────────────────────────────────── */
#include <stdbool.h>   /* bool, true, false                     */
#include <stddef.h>    /* size_t                                */
#include <stdint.h>    /* uint32_t, uint8_t                     */
#include <time.h>      /* time_t                                */

#ifdef __cplusplus
extern "C" {
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Symbol visibility / linkage                                               */
#if defined(_WIN32) && defined(SC_TEXTURE_DLL)
  #ifdef SC_TEXTURE_DLL_EXPORTS
    #define SC_TEXTURE_API __declspec(dllexport)
  #else
    #define SC_TEXTURE_API __declspec(dllimport)
  #endif
#elif defined(__GNUC__)
  #define SC_TEXTURE_API __attribute__((visibility("default")))
#else
  #define SC_TEXTURE_API
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/* Public constants                                                          */
#define SC_TEXTURE_UUID_STR_LEN 36  /* 8-4-4-4-12  (without NUL)           */
#define SC_TEXTURE_NAME_MAX     64
#define SC_TEXTURE_ERROR_MAX   256  /* Convenience ‑ internal scratch buf */

/* ────────────────────────────────────────────────────────────────────────── */
/* Enumerations                                                              */

/* Possible pixel formats accepted by the Texture Service.                   */
typedef enum
{
    SC_PIXEL_FORMAT_UNKNOWN = 0,
    SC_PIXEL_FORMAT_RGB8,            /* 24-bit, Little-End, RGB order      */
    SC_PIXEL_FORMAT_RGBA8,           /* 32-bit, Little-End, RGBA order     */
    SC_PIXEL_FORMAT_BGR8,            /* 24-bit, Little-End, BGR order      */
    SC_PIXEL_FORMAT_BGRA8,           /* 32-bit, Little-End, BGRA order     */
    SC_PIXEL_FORMAT_GRAYSCALE8,      /* 8-bit,  Luma                       */
    SC_PIXEL_FORMAT_GRAYSCALE16,     /* 16-bit, Luma, Little-End           */
    SC_PIXEL_FORMAT__COUNT
} sc_pixel_format_t;

/* Color spaces supported by downstream GPU / renderer pipelines.            */
typedef enum
{
    SC_COLOR_SPACE_SRGB = 0,
    SC_COLOR_SPACE_DISPLAY_P3,
    SC_COLOR_SPACE_ADOBE_RGB,
    SC_COLOR_SPACE_REC2020,
    SC_COLOR_SPACE__COUNT
} sc_color_space_t;

/* Compression algorithms – extend as additional codecs are introduced.      */
typedef enum
{
    SC_COMPRESSION_NONE = 0,
    SC_COMPRESSION_LZ4,
    SC_COMPRESSION_ZSTD,
    SC_COMPRESSION__COUNT
} sc_compression_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Data structures                                                           */

/*
 * sc_texture_t
 *
 * Abstraction representing a 2-D bitmap; optionally compressed.  Ownership
 * rules follow standard C conventions:
 *
 *   ‑ Pixels (pixel_data) are heap-allocated unless created via
 *     sc_texture_from_buffer() with take_ownership==false, in which case the
 *     caller maintains responsibility for freeing the buffer.
 *
 *   ‑ All string fields (id, name) are heap allocated and owned by the struct.
 *
 * Thread safety:
 *   A texture instance is NOT thread-safe.  External synchronisation is
 *   required if the same instance is shared across threads.
 */
typedef struct sc_texture
{
    char                *id;             /* UUID v4 (lowercase, no braces)  */
    char                *name;           /* Human-readable label            */
    uint32_t             width;          /* Pixel width                     */
    uint32_t             height;         /* Pixel height                    */
    sc_pixel_format_t    pixel_format;   /* Data ordering                   */
    sc_color_space_t     color_space;    /* Transfer characteristics        */

    sc_compression_t     compression;    /* Compression scheme              */
    bool                 compressed;     /* Hint: pixel_data is compressed? */

    uint8_t             *pixel_data;     /* Raw or compressed data buffer   */
    size_t               data_size;      /* Total bytes stored in buffer    */

    time_t               created_at;     /* UNIX epoch                      */
    time_t               updated_at;
} sc_texture_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* Forward declarations                                                      */

SC_TEXTURE_API sc_texture_t *
sc_texture_new(const char            *name,
               uint32_t               width,
               uint32_t               height,
               sc_pixel_format_t      fmt,
               sc_color_space_t       cs,
               bool                   allocate_pixels);

SC_TEXTURE_API sc_texture_t *
sc_texture_from_buffer(const char      *name,
                       uint32_t         width,
                       uint32_t         height,
                       sc_pixel_format_t fmt,
                       sc_color_space_t cs,
                       sc_compression_t  compression,
                       uint8_t          *buffer,
                       size_t            buffer_size,
                       bool              take_ownership);

SC_TEXTURE_API sc_texture_t *
sc_texture_clone(const sc_texture_t *src);

SC_TEXTURE_API void
sc_texture_free(sc_texture_t *texture);

SC_TEXTURE_API bool
sc_texture_validate(const sc_texture_t *texture,
                    char               **error_out); /* malloc()-ed if non-NULL */

SC_TEXTURE_API uint32_t
sc_texture_calculate_stride(uint32_t width, sc_pixel_format_t fmt);

SC_TEXTURE_API size_t
sc_texture_calculate_buffer_size(uint32_t width,
                                 uint32_t height,
                                 sc_pixel_format_t fmt);

/* Optional convenience utility */
SC_TEXTURE_API const char *
sc_texture_pixel_format_to_string(sc_pixel_format_t fmt);

/* ────────────────────────────────────────────────────────────────────────── */
/* Inline helpers                                                            */

static inline uint8_t
sc_pixel_format_bytes_per_pixel(sc_pixel_format_t fmt)
{
    switch (fmt)
    {
        case SC_PIXEL_FORMAT_RGB8:
        case SC_PIXEL_FORMAT_BGR8:
            return 3U;
        case SC_PIXEL_FORMAT_RGBA8:
        case SC_PIXEL_FORMAT_BGRA8:
            return 4U;
        case SC_PIXEL_FORMAT_GRAYSCALE8:
            return 1U;
        case SC_PIXEL_FORMAT_GRAYSCALE16:
            return 2U;
        default:
            return 0U;
    }
}

static inline uint32_t
sc_texture_calculate_stride(uint32_t width, sc_pixel_format_t fmt)
{
    const uint8_t bpp = sc_pixel_format_bytes_per_pixel(fmt);
    return (bpp == 0U) ? 0U : width * (uint32_t)bpp;
}

static inline size_t
sc_texture_calculate_buffer_size(uint32_t width,
                                 uint32_t height,
                                 sc_pixel_format_t fmt)
{
    return (size_t)sc_texture_calculate_stride(width, fmt) * height;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Implementation – header-only (can be toggled off to compile separately)   */
#ifndef SC_TEXTURE_DECL_ONLY
#include <stdlib.h>  /* malloc, free, calloc, realloc                         */
#include <string.h>  /* memset, memcpy, strdup                                */
#include <stdio.h>   /* snprintf                                              */
#if defined(__linux__) || defined(__APPLE__)
  #include <uuid/uuid.h> /* libuuid – common on *nix systems                 */
#endif

/* Internal helper: allocate and copy string */
static char *sc__strdup(const char *s)
{
#if defined(_MSC_VER)
    return _strdup(s ? s : "");
#else
    return strdup(s ? s : "");
#endif
}

/* Internal helper: generate UUID4 string */
static char *sc__generate_uuid(void)
{
    char *out = malloc(SC_TEXTURE_UUID_STR_LEN + 1);
    if (!out) return NULL;

#if defined(__linux__) || defined(__APPLE__)
    uuid_t uuid;
    uuid_generate_random(uuid);
    uuid_unparse_lower(uuid, out);
#else
    /* Fallback: pseudo-UUID when libuuid not available – NOT cryptographically
     * secure, but sufficient for internal resource identification.            */
    snprintf(out, SC_TEXTURE_UUID_STR_LEN + 1,
             "%08x-%04x-%04x-%04x-%04x%04x%04x",
             rand(), rand() & 0xffff, (rand() & 0x0fff) | 0x4000,
             (rand() & 0x3fff) | 0x8000, rand() & 0xffff,
             rand() & 0xffff, rand() & 0xffff);
#endif
    return out;
}

/* Public API implementations ------------------------------------------------*/

SC_TEXTURE_API sc_texture_t *
sc_texture_new(const char            *name,
               uint32_t               width,
               uint32_t               height,
               sc_pixel_format_t      fmt,
               sc_color_space_t       cs,
               bool                   allocate_pixels)
{
    sc_texture_t *tex = calloc(1, sizeof *tex);
    if (!tex) return NULL;

    tex->id            = sc__generate_uuid();
    tex->name          = sc__strdup(name);
    tex->width         = width;
    tex->height        = height;
    tex->pixel_format  = fmt;
    tex->color_space   = cs;
    tex->compression   = SC_COMPRESSION_NONE;
    tex->compressed    = false;
    tex->created_at    = time(NULL);
    tex->updated_at    = tex->created_at;

    if (allocate_pixels)
    {
        tex->data_size = sc_texture_calculate_buffer_size(width, height, fmt);
        if (tex->data_size == 0)
        {
            sc_texture_free(tex);
            return NULL;
        }

        tex->pixel_data = calloc(1, tex->data_size);
        if (!tex->pixel_data)
        {
            sc_texture_free(tex);
            return NULL;
        }
    }

    return tex;
}

SC_TEXTURE_API sc_texture_t *
sc_texture_from_buffer(const char      *name,
                       uint32_t         width,
                       uint32_t         height,
                       sc_pixel_format_t fmt,
                       sc_color_space_t  cs,
                       sc_compression_t  compression,
                       uint8_t          *buffer,
                       size_t            buffer_size,
                       bool              take_ownership)
{
    if (!buffer || buffer_size == 0) return NULL;

    sc_texture_t *tex = calloc(1, sizeof *tex);
    if (!tex) return NULL;

    tex->id            = sc__generate_uuid();
    tex->name          = sc__strdup(name);
    tex->width         = width;
    tex->height        = height;
    tex->pixel_format  = fmt;
    tex->color_space   = cs;
    tex->compression   = compression;
    tex->compressed    = (compression != SC_COMPRESSION_NONE);
    tex->data_size     = buffer_size;
    tex->created_at    = time(NULL);
    tex->updated_at    = tex->created_at;

    if (take_ownership)
    {
        tex->pixel_data = buffer;              /* Transfer ownership */
    }
    else
    {
        tex->pixel_data = malloc(buffer_size); /* Deep copy          */
        if (!tex->pixel_data)
        {
            sc_texture_free(tex);
            return NULL;
        }
        memcpy(tex->pixel_data, buffer, buffer_size);
    }

    return tex;
}

SC_TEXTURE_API sc_texture_t *
sc_texture_clone(const sc_texture_t *src)
{
    if (!src) return NULL;

    sc_texture_t *copy = calloc(1, sizeof *copy);
    if (!copy) return NULL;

    *copy = *src; /* Shallow fields first */

    /* Deep-copy dynamic members */
    copy->id   = sc__strdup(src->id);
    copy->name = sc__strdup(src->name);

    if (src->pixel_data && src->data_size)
    {
        copy->pixel_data = malloc(src->data_size);
        if (!copy->pixel_data)
        {
            sc_texture_free(copy);
            return NULL;
        }
        memcpy(copy->pixel_data, src->pixel_data, src->data_size);
    }

    return copy;
}

SC_TEXTURE_API void
sc_texture_free(sc_texture_t *texture)
{
    if (!texture) return;

    free(texture->id);
    free(texture->name);

    /* Only free pixel_data if we own it (always true for current constructors) */
    free(texture->pixel_data);

    /* Zero out memory to avoid accidental reuse after free */
    memset(texture, 0, sizeof *texture);
    free(texture);
}

SC_TEXTURE_API bool
sc_texture_validate(const sc_texture_t *texture,
                    char               **error_out)
{
    static char err_buf[SC_TEXTURE_ERROR_MAX];

    if (!texture)
    {
        if (error_out)
            *error_out = sc__strdup("texture pointer is NULL");
        return false;
    }

    if (texture->width == 0 || texture->height == 0)
    {
        snprintf(err_buf, sizeof err_buf, "invalid dimensions: %ux%u",
                 texture->width, texture->height);
        if (error_out) *error_out = sc__strdup(err_buf);
        return false;
    }

    if (texture->pixel_format <= SC_PIXEL_FORMAT_UNKNOWN ||
        texture->pixel_format >= SC_PIXEL_FORMAT__COUNT)
    {
        if (error_out)
            *error_out = sc__strdup("unsupported pixel format");
        return false;
    }

    const size_t expected =
        sc_texture_calculate_buffer_size(texture->width,
                                         texture->height,
                                         texture->pixel_format);
    if (!texture->compressed && expected != texture->data_size)
    {
        snprintf(err_buf, sizeof err_buf,
                 "data_size mismatch – expected %zu, got %zu",
                 expected, texture->data_size);
        if (error_out) *error_out = sc__strdup(err_buf);
        return false;
    }

    /* Additional semantic checks can be performed here */

    if (error_out) *error_out = NULL;
    return true;
}

SC_TEXTURE_API const char *
sc_texture_pixel_format_to_string(sc_pixel_format_t fmt)
{
    switch (fmt)
    {
        case SC_PIXEL_FORMAT_RGB8:        return "RGB8";
        case SC_PIXEL_FORMAT_RGBA8:       return "RGBA8";
        case SC_PIXEL_FORMAT_BGR8:        return "BGR8";
        case SC_PIXEL_FORMAT_BGRA8:       return "BGRA8";
        case SC_PIXEL_FORMAT_GRAYSCALE8:  return "GRAY8";
        case SC_PIXEL_FORMAT_GRAYSCALE16: return "GRAY16";
        default:                          return "UNKNOWN";
    }
}

#endif /* SC_TEXTURE_DECL_ONLY */

/* ────────────────────────────────────────────────────────────────────────── */

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* SC_TEXTURE_H */
