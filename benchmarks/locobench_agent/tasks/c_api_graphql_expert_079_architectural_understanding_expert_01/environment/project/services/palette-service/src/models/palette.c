/*
 * SynestheticCanvas Palette Service
 * File: models/palette.c
 *
 * Description:
 *   Core Palette model implementation for the Palette micro-service.
 *   Contains helpers for palette lifecycle management, JSON (de)serialisation,
 *   validation and color conversions. This code purposefully avoids
 *   application-layer concerns (HTTP, GraphQL, persistence) and focuses strictly
 *   on the in-memory representation and business-logic rules.
 *
 * Author: SynestheticCanvas Engineering
 * SPDX-License-Identifier: MIT
 */

#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#include <stdbool.h>
#include <syslog.h>

#include "cJSON.h"           /* 3rd-party, MIT-licensed JSON parser  */
#include "palette.h"         /* Corresponding header ‑ public API    */

/* --------------------------------------------------------------------------
 *  Internal constants & macros
 * -------------------------------------------------------------------------- */

#define PALETTE_INITIAL_CAPACITY  8U      /* Initial color buffer size    */
#define PALETTE_VERSION_MAX_LEN   7U      /* e.g. "v2023.4" + '\0'        */
#define HEX_COLOR_LEN_SHORT       7U      /* #RRGGBB                      */
#define HEX_COLOR_LEN_LONG        9U      /* #AARRGGBB                    */

/* Macro for safe FREE */
#define SAFE_FREE(ptr) do { \
        if ((ptr) != NULL) { \
            free(ptr);      \
            (ptr) = NULL;   \
        }                   \
    } while (0)

/* --------------------------------------------------------------------------
 *  Static utility prototypes
 * -------------------------------------------------------------------------- */

static bool palette_expand_buffer(Palette *palette);
static bool is_valid_hex_color(const char *hex);
static uint32_t hex_to_argb(const char *hex, bool *ok);
static char *argb_to_hex(uint32_t argb);
static void log_errno(const char *ctx);

/* --------------------------------------------------------------------------
 *  Public API implementation
 * -------------------------------------------------------------------------- */

Palette *palette_create(const char *name, const char *version)
{
    if (name == NULL || version == NULL ||
        strlen(version) >= PALETTE_VERSION_MAX_LEN) {
        syslog(LOG_ERR, "palette_create: invalid arguments");
        errno = EINVAL;
        return NULL;
    }

    Palette *p = calloc(1, sizeof(*p));
    if (!p) {
        log_errno("calloc");
        return NULL;
    }

    p->name = strdup(name);
    if (!p->name) {
        log_errno("strdup(name)");
        free(p);
        return NULL;
    }

    strncpy(p->version, version, sizeof(p->version) - 1);
    p->version[sizeof(p->version) - 1] = '\0';

    p->capacity    = PALETTE_INITIAL_CAPACITY;
    p->color_count = 0;

    p->colors = calloc(p->capacity, sizeof(uint32_t));
    if (!p->colors) {
        log_errno("calloc(colors)");
        palette_free(p);
        return NULL;
    }

    return p;
}

bool palette_add_color_hex(Palette *palette, const char *hex_color)
{
    if (!palette || !hex_color) {
        errno = EINVAL;
        return false;
    }

    /* Validate the color string and convert */
    bool ok = false;
    uint32_t argb = hex_to_argb(hex_color, &ok);
    if (!ok) {
        syslog(LOG_WARNING, "palette_add_color_hex: invalid hex '%s'", hex_color);
        errno = EINVAL;
        return false;
    }

    /* Grow buffer if necessary */
    if (palette->color_count == palette->capacity &&
        !palette_expand_buffer(palette)) {
        return false; /* errno set by palette_expand_buffer */
    }

    palette->colors[palette->color_count++] = argb;
    return true;
}

bool palette_get_color_hex(const Palette *palette, size_t index, char **out_hex)
{
    if (!palette || !out_hex || index >= palette->color_count) {
        errno = EINVAL;
        return false;
    }

    char *hex = argb_to_hex(palette->colors[index]);
    if (!hex) {
        /* errno propagated by malloc */
        return false;
    }

    *out_hex = hex;
    return true;
}

char *palette_to_json(const Palette *palette)
{
    if (!palette) {
        errno = EINVAL;
        return NULL;
    }

    cJSON *root = cJSON_CreateObject();
    if (!root) {
        errno = ENOMEM;
        return NULL;
    }

    cJSON_AddStringToObject(root, "name", palette->name);
    cJSON_AddStringToObject(root, "version", palette->version);

    cJSON *colors_arr = cJSON_AddArrayToObject(root, "colors");
    if (!colors_arr) {
        cJSON_Delete(root);
        errno = ENOMEM;
        return NULL;
    }

    for (size_t i = 0; i < palette->color_count; ++i) {
        char *hex = argb_to_hex(palette->colors[i]);
        if (!hex) {          /* errno propagated */
            cJSON_Delete(root);
            return NULL;
        }
        cJSON_AddItemToArray(colors_arr, cJSON_CreateString(hex));
        free(hex);
    }

    char *json_str = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    if (!json_str) {
        errno = ENOMEM;
        return NULL;
    }

    return json_str;
}

bool palette_from_json(const char *json_str, Palette **out_palette)
{
    if (!json_str || !out_palette) {
        errno = EINVAL;
        return false;
    }

    bool ok           = false;
    cJSON *root       = NULL;
    Palette *palette  = NULL;

    root = cJSON_Parse(json_str);
    if (!root) {
        syslog(LOG_ERR, "palette_from_json: malformed JSON");
        errno = EINVAL;
        goto cleanup;
    }

    const cJSON *name     = cJSON_GetObjectItemCaseSensitive(root, "name");
    const cJSON *version  = cJSON_GetObjectItemCaseSensitive(root, "version");
    const cJSON *colors   = cJSON_GetObjectItemCaseSensitive(root, "colors");

    if (!cJSON_IsString(name)   || !cJSON_IsString(version) ||
        !cJSON_IsArray(colors)) {
        syslog(LOG_ERR, "palette_from_json: invalid JSON schema");
        errno = EINVAL;
        goto cleanup;
    }

    palette = palette_create(name->valuestring, version->valuestring);
    if (!palette) {
        /* errno propagated */
        goto cleanup;
    }

    cJSON_ArrayForEach(colors, colors)
    {
        if (!cJSON_IsString(colors)) {
            syslog(LOG_WARNING, "palette_from_json: skipping non-string color");
            continue;
        }
        if (!palette_add_color_hex(palette, colors->valuestring)) {
            /* palette_add_color_hex sets errno */
            goto cleanup;
        }
    }

    *out_palette = palette;
    ok = true;

cleanup:
    if (!ok) {
        palette_free(palette);
    }
    cJSON_Delete(root);
    return ok;
}

void palette_free(Palette *palette)
{
    if (!palette) return;

    SAFE_FREE(palette->name);
    SAFE_FREE(palette->colors);
    SAFE_FREE(palette);
}

/* --------------------------------------------------------------------------
 *  Static helpers
 * -------------------------------------------------------------------------- */

static bool palette_expand_buffer(Palette *palette)
{
    size_t new_cap = palette->capacity * 2U;
    uint32_t *tmp  = realloc(palette->colors, new_cap * sizeof(uint32_t));
    if (!tmp) {
        log_errno("realloc(colors)");
        return false;
    }

    palette->colors   = tmp;
    palette->capacity = new_cap;
    return true;
}

/* Validates #RRGGBB or #AARRGGBB */
static bool is_valid_hex_color(const char *hex)
{
    if (!hex) return false;

    size_t len = strlen(hex);
    if (len != HEX_COLOR_LEN_SHORT && len != HEX_COLOR_LEN_LONG) {
        return false;
    }
    if (hex[0] != '#') {
        return false;
    }

    for (size_t i = 1; i < len; ++i) {
        char c = hex[i];
        bool valid_digit = (c >= '0' && c <= '9') ||
                           (c >= 'a' && c <= 'f') ||
                           (c >= 'A' && c <= 'F');
        if (!valid_digit) return false;
    }
    return true;
}

static uint32_t hex_to_argb(const char *hex, bool *ok)
{
    if (ok) *ok = false;

    if (!is_valid_hex_color(hex)) {
        return 0;
    }

    char buf[3] = { 0 };
    const char *ptr = hex + 1; /* skip '#' */
    uint32_t components[4] = { 0 }; /* A, R, G, B */
    size_t comp_index = 0;

    /* If we have 6 digits -> no alpha, assume FF */
    if (strlen(hex) == HEX_COLOR_LEN_SHORT) {
        components[comp_index++] = 0xFF; /* Alpha */
    }

    for (; *ptr && comp_index < 4; ptr += 2, ++comp_index) {
        buf[0] = ptr[0];
        buf[1] = ptr[1];
        components[comp_index] = (uint32_t)strtoul(buf, NULL, 16);
    }

    uint32_t argb = (components[0] << 24) |
                    (components[1] << 16) |
                    (components[2] << 8)  |
                    (components[3]);

    if (ok) *ok = true;
    return argb;
}

static char *argb_to_hex(uint32_t argb)
{
    /* Always include alpha channel for round-trip integrity */
    char *hex = malloc(HEX_COLOR_LEN_LONG + 1); /* '#'+8 digits + '\0' */
    if (!hex) {
        log_errno("malloc(hex)");
        return NULL;
    }

    int written = snprintf(hex, HEX_COLOR_LEN_LONG + 1,
                           "#%02X%02X%02X%02X",
                           (argb >> 24) & 0xFF,  /* A */
                           (argb >> 16) & 0xFF,  /* R */
                           (argb >> 8)  & 0xFF,  /* G */
                           argb & 0xFF);         /* B */

    if (written != (int)HEX_COLOR_LEN_LONG) { /* Should never happen */
        SAFE_FREE(hex);
        errno = EFAULT;
        return NULL;
    }
    return hex;
}

static void log_errno(const char *ctx)
{
    syslog(LOG_ERR, "%s failed: %s", ctx, strerror(errno));
}
