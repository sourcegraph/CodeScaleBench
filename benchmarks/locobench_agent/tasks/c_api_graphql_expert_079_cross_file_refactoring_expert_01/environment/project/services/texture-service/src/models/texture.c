/*
 * SynestheticCanvas - Texture Service
 * File: models/texture.c
 *
 * This module implements the Texture domain object used by the texture-service.
 * A texture is an immutable chunk of pixel data that can be shared across
 * multiple worker threads.  To achieve zero-copy behaviour we rely on
 * reference counting with C11 atomics.
 *
 * Features implemented in this file:
 *   • Texture lifecycle helpers (create, clone, destroy)
 *   • Reference counting with thread-safety
 *   • Serialization / deserialization to JSON using cJSON
 *   • UUID-v4 identity generation (libuuid)
 *   • Error handling with a small enumeration
 *   • Optional file loading / saving via STB (compile–time switch)
 *
 * Author: SynestheticCanvas Core Team
 * License: MIT
 */

#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <uuid/uuid.h>

#include <cjson/cJSON.h>

#ifdef TEXTURE_ENABLE_STB_IO
/* These headers are only required when texture IO is enabled. */
#define STB_IMAGE_IMPLEMENTATION
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include <stb_image.h>
#include <stb_image_write.h>
#endif /* TEXTURE_ENABLE_STB_IO */

#include "texture.h"
#include "logging.h" /* Internal lightweight logging wrapper */

/* ────────────────────────────────────────────────────────────────────────── */
/* Private helpers                                                           */
/* ────────────────────────────────────────────────────────────────────────── */

static inline uint64_t
unix_epoch_millis(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return ((uint64_t)ts.tv_sec * 1000) + (uint64_t)(ts.tv_nsec / 1000000);
}

static TextureError
generate_uuid(char out[TEXTURE_UUID_STRLEN])
{
    uuid_t uuid;
    uuid_generate_random(uuid);
    uuid_unparse_lower(uuid, out);
    return TEXTURE_OK;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Public API                                                                */
/* ────────────────────────────────────────────────────────────────────────── */

Texture *
texture_create(uint32_t width,
               uint32_t height,
               TextureFormat fmt,
               const uint8_t *pixels,
               size_t pixel_len,
               TextureError *err_out)
{
    if (err_out)
        *err_out = TEXTURE_OK;

    /* Validate dimensions */
    if (width == 0 || height == 0)
    {
        if (err_out)
            *err_out = TEXTURE_ERR_INVALID_DIM;
        return NULL;
    }

    /* Calculate expected buffer length and validate */
    uint8_t channels = texture_format_channels(fmt);
    size_t required_len = (size_t)width * height * channels;

    if (pixel_len && pixel_len < required_len)
    {
        if (err_out)
            *err_out = TEXTURE_ERR_INSUFFICIENT_DATA;
        return NULL;
    }

    Texture *t = calloc(1, sizeof(Texture));
    if (!t)
    {
        if (err_out)
            *err_out = TEXTURE_ERR_OOM;
        return NULL;
    }

    t->width  = width;
    t->height = height;
    t->format = fmt;
    t->bytes  = required_len;
    t->created_at = unix_epoch_millis();
    t->updated_at = t->created_at;

    generate_uuid(t->id);

    /* Allocate and copy pixel buffer if provided; otherwise allocate zeroed
     * buffer so that the memory is always owned by this instance. */
    t->data = malloc(required_len);
    if (!t->data)
    {
        if (err_out)
            *err_out = TEXTURE_ERR_OOM;
        free(t);
        return NULL;
    }

    if (pixels)
        memcpy(t->data, pixels, required_len);
    else
        memset(t->data, 0, required_len);

    /* Initialize atomic reference counter to 1 (creator owns it) */
    atomic_init(&t->ref_count, 1u);

    return t;
}

Texture *
texture_clone(Texture *src)
{
    if (!src)
        return NULL;

    atomic_fetch_add_explicit(&src->ref_count, 1u, memory_order_relaxed);
    return src;
}

void
texture_release(Texture *t)
{
    if (!t)
        return;

    if (atomic_fetch_sub_explicit(&t->ref_count, 1u,
                                  memory_order_acq_rel) == 1u)
    {
        /* Last reference: destroy resources */
        free(t->data);
        t->data = NULL;
        free(t);
    }
}

uint8_t
texture_format_channels(TextureFormat fmt)
{
    switch (fmt)
    {
    case TEXTURE_FORMAT_GRAY8:
        return 1u;
    case TEXTURE_FORMAT_RGB8:
        return 3u;
    case TEXTURE_FORMAT_RGBA8:
        return 4u;
    default:
        return 0u;
    }
}

const char *
texture_format_to_string(TextureFormat fmt)
{
    switch (fmt)
    {
    case TEXTURE_FORMAT_GRAY8:
        return "GRAY8";
    case TEXTURE_FORMAT_RGB8:
        return "RGB8";
    case TEXTURE_FORMAT_RGBA8:
        return "RGBA8";
    default:
        return "UNKNOWN";
    }
}

TextureFormat
texture_format_from_string(const char *s)
{
    if (!s)
        return TEXTURE_FORMAT_UNKNOWN;

    if (strcmp(s, "GRAY8") == 0)
        return TEXTURE_FORMAT_GRAY8;
    if (strcmp(s, "RGB8") == 0)
        return TEXTURE_FORMAT_RGB8;
    if (strcmp(s, "RGBA8") == 0)
        return TEXTURE_FORMAT_RGBA8;
    return TEXTURE_FORMAT_UNKNOWN;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* JSON Serialization                                                        */
/* ────────────────────────────────────────────────────────────────────────── */

char *
texture_to_json(const Texture *t)
{
    if (!t)
        return NULL;

    cJSON *root = cJSON_CreateObject();
    if (!root)
        return NULL;

    cJSON_AddStringToObject(root, "id", t->id);
    cJSON_AddNumberToObject(root, "width", t->width);
    cJSON_AddNumberToObject(root, "height", t->height);
    cJSON_AddStringToObject(root, "format",
                            texture_format_to_string(t->format));
    cJSON_AddNumberToObject(root, "bytes", (double)t->bytes);
    cJSON_AddNumberToObject(root, "created_at", (double)t->created_at);
    cJSON_AddNumberToObject(root, "updated_at", (double)t->updated_at);

    /* To avoid blowing up payload size we base64-encode pixel data.  This is
     * performant enough for metadata calls, while production bulk transfers
     * use separate binary channels (gRPC, WebRTC, etc.). */
    char *b64 = texture_base64_encode(t->data, t->bytes);
    if (!b64)
    {
        cJSON_Delete(root);
        return NULL;
    }
    cJSON_AddStringToObject(root, "pixel_data", b64);
    free(b64);

    char *json_str = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    return json_str;
}

Texture *
texture_from_json(const char *json, TextureError *err_out)
{
    if (err_out)
        *err_out = TEXTURE_OK;

    if (!json)
    {
        if (err_out)
            *err_out = TEXTURE_ERR_INVALID_JSON;
        return NULL;
    }

    cJSON *root = cJSON_Parse(json);
    if (!root)
    {
        if (err_out)
            *err_out = TEXTURE_ERR_INVALID_JSON;
        return NULL;
    }

    /* Mandatory fields */
    const cJSON *id        = cJSON_GetObjectItemCaseSensitive(root, "id");
    const cJSON *width     = cJSON_GetObjectItemCaseSensitive(root, "width");
    const cJSON *height    = cJSON_GetObjectItemCaseSensitive(root, "height");
    const cJSON *format    = cJSON_GetObjectItemCaseSensitive(root, "format");
    const cJSON *pixel_b64 = cJSON_GetObjectItemCaseSensitive(root, "pixel_data");

    if (!cJSON_IsString(id)     || !cJSON_IsNumber(width)  ||
        !cJSON_IsNumber(height) || !cJSON_IsString(format) ||
        !cJSON_IsString(pixel_b64))
    {
        if (err_out)
            *err_out = TEXTURE_ERR_INVALID_JSON;
        cJSON_Delete(root);
        return NULL;
    }

    TextureFormat fmt = texture_format_from_string(format->valuestring);
    size_t pixel_len  = 0;
    uint8_t *pixels   = texture_base64_decode(pixel_b64->valuestring,
                                              &pixel_len);
    if (!pixels)
    {
        if (err_out)
            *err_out = TEXTURE_ERR_INVALID_BASE64;
        cJSON_Delete(root);
        return NULL;
    }

    Texture *t = texture_create((uint32_t)width->valuedouble,
                                (uint32_t)height->valuedouble,
                                fmt,
                                pixels,
                                pixel_len,
                                err_out);
    free(pixels);

    if (!t)
    {
        cJSON_Delete(root);
        return NULL;
    }

    strncpy(t->id, id->valuestring, TEXTURE_UUID_STRLEN - 1);
    t->id[TEXTURE_UUID_STRLEN - 1] = '\0';

    const cJSON *created_at = cJSON_GetObjectItemCaseSensitive(root, "created_at");
    const cJSON *updated_at = cJSON_GetObjectItemCaseSensitive(root, "updated_at");

    if (cJSON_IsNumber(created_at))
        t->created_at = (uint64_t)created_at->valuedouble;
    if (cJSON_IsNumber(updated_at))
        t->updated_at = (uint64_t)updated_at->valuedouble;

    cJSON_Delete(root);
    return t;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Base64 helpers (tiny self-contained implementation)                       */
/* ────────────────────────────────────────────────────────────────────────── */

static const char _tbl[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

char *
texture_base64_encode(const uint8_t *data, size_t len)
{
    if (!data || len == 0)
        return NULL;

    size_t out_len = 4 * ((len + 2) / 3);
    char *out = malloc(out_len + 1);
    if (!out)
        return NULL;

    size_t i = 0, j = 0;
    while (i < len)
    {
        uint32_t octet_a = i < len ? data[i++] : 0;
        uint32_t octet_b = i < len ? data[i++] : 0;
        uint32_t octet_c = i < len ? data[i++] : 0;

        uint32_t triple = (octet_a << 16u) | (octet_b << 8u) | octet_c;

        out[j++] = _tbl[(triple >> 18u) & 0x3Fu];
        out[j++] = _tbl[(triple >> 12u) & 0x3Fu];
        out[j++] = (i > len + 1) ? '=' : _tbl[(triple >> 6u) & 0x3Fu];
        out[j++] = (i > len)     ? '=' : _tbl[triple & 0x3Fu];
    }
    out[out_len] = '\0';
    return out;
}

uint8_t *
texture_base64_decode(const char *in, size_t *out_len)
{
    if (!in)
        return NULL;

    size_t len = strlen(in);
    if (len % 4 != 0)
        return NULL;

    size_t padding = 0;
    if (len >= 2 && in[len - 1] == '=')
        padding++;
    if (len >= 2 && in[len - 2] == '=')
        padding++;

    size_t decoded_len = (len / 4) * 3 - padding;
    uint8_t *out = malloc(decoded_len);
    if (!out)
        return NULL;

    uint32_t sextet[4];
    size_t i = 0, j = 0;
    while (i < len)
    {
        for (int k = 0; k < 4; ++k)
        {
            char c = in[i++];
            if (c >= 'A' && c <= 'Z')
                sextet[k] = c - 'A';
            else if (c >= 'a' && c <= 'z')
                sextet[k] = c - 'a' + 26;
            else if (c >= '0' && c <= '9')
                sextet[k] = c - '0' + 52;
            else if (c == '+')
                sextet[k] = 62;
            else if (c == '/')
                sextet[k] = 63;
            else if (c == '=')
                sextet[k] = 0;
            else /* Invalid char */
            {
                free(out);
                return NULL;
            }
        }

        uint32_t triple = (sextet[0] << 18u) |
                          (sextet[1] << 12u) |
                          (sextet[2] << 6u)  |
                          sextet[3];

        if (j < decoded_len)
            out[j++] = (triple >> 16u) & 0xFFu;
        if (j < decoded_len)
            out[j++] = (triple >> 8u) & 0xFFu;
        if (j < decoded_len)
            out[j++] = triple & 0xFFu;
    }

    if (out_len)
        *out_len = decoded_len;
    return out;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Optional: Load / Save                                                     */
/* ────────────────────────────────────────────────────────────────────────── */

#ifdef TEXTURE_ENABLE_STB_IO
Texture *
texture_load_from_file(const char *path, TextureError *err_out)
{
    if (err_out)
        *err_out = TEXTURE_OK;

    if (!path)
    {
        if (err_out)
            *err_out = TEXTURE_ERR_INVALID_IO;
        return NULL;
    }

    int w, h, n;
    uint8_t *pixels = stbi_load(path, &w, &h, &n, 0);
    if (!pixels)
    {
        if (err_out)
            *err_out = TEXTURE_ERR_IO_READ;
        return NULL;
    }

    TextureFormat fmt;
    switch (n)
    {
    case 1:
        fmt = TEXTURE_FORMAT_GRAY8;
        break;
    case 3:
        fmt = TEXTURE_FORMAT_RGB8;
        break;
    case 4:
        fmt = TEXTURE_FORMAT_RGBA8;
        break;
    default:
        stbi_image_free(pixels);
        if (err_out)
            *err_out = TEXTURE_ERR_UNSUPPORTED_FMT;
        return NULL;
    }

    Texture *t = texture_create((uint32_t)w, (uint32_t)h, fmt,
                                pixels,
                                (size_t)w * h * n,
                                err_out);
    stbi_image_free(pixels);
    return t;
}

TextureError
texture_save_to_png(const Texture *t, const char *path)
{
    if (!t || !path)
        return TEXTURE_ERR_INVALID_IO;

    int stride = (int)t->width * texture_format_channels(t->format);

    if (!stbi_write_png(path, (int)t->width, (int)t->height,
                        texture_format_channels(t->format),
                        t->data,
                        stride))
    {
        return TEXTURE_ERR_IO_WRITE;
    }
    return TEXTURE_OK;
}
#endif /* TEXTURE_ENABLE_STB_IO */

/* ────────────────────────────────────────────────────────────────────────── */
/* Debug helper                                                              */
/* ────────────────────────────────────────────────────────────────────────── */

void
texture_dump(const Texture *t)
{
    if (!t)
    {
        LOG_ERROR("texture_dump called with NULL");
        return;
    }

    LOG_INFO("Texture{id=%s, %ux%u, fmt=%s, bytes=%zu, refs=%u}",
             t->id,
             t->width,
             t->height,
             texture_format_to_string(t->format),
             t->bytes,
             atomic_load(&t->ref_count));
}

/* ────────────────────────────────────────────────────────────────────────── */
