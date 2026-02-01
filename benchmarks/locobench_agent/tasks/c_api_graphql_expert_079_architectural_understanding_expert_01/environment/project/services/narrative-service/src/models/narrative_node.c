/**
 * SynestheticCanvas Narrative Service
 *
 * File: narrative_node.c
 * Description: Data-model implementation for an interactive narrative node.
 * Each node represents a “beat” in a branching storyline and can reference
 * external media items (textures, audio, etc.) that other services render
 * in real-time.  Nodes are transferred between services as JSON payloads,
 * so this module also provides robust (de)serialization utilities
 * built on top of the Jansson library.
 *
 * Author: SynestheticCanvas Core Team
 * License: MIT
 */

#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <syslog.h>
#include <time.h>
#include <uuid/uuid.h>
#include <jansson.h>

#include "narrative_node.h"

/* -------------------------------------------------------------------------
 * Internal constants & helpers
 * ------------------------------------------------------------------------- */
#define ISO_8601_BUFSZ 32

static inline char *dupstr(const char *s)
{
    if (!s) return NULL;
    char *copy = strdup(s);
    if (!copy) syslog(LOG_ERR, "strdup failed: %s", strerror(errno));
    return copy;
}

static char *timestamp_to_iso8601(time_t ts)
{
    static const char *fmt = "%Y-%m-%dT%H:%M:%SZ";
    char *buf = calloc(ISO_8601_BUFSZ, 1);
    if (!buf) {
        syslog(LOG_ERR, "calloc failed: %s", strerror(errno));
        return NULL;
    }

    struct tm tm_utc;
#if defined(_POSIX_THREAD_SAFE_FUNCTIONS) && !defined(__APPLE__)
    gmtime_r(&ts, &tm_utc);
#else
    /* gmtime_r is unavailable on some platforms (e.g. macOS + older SDKs) */
    struct tm *tmp = gmtime(&ts);
    if (!tmp) {
        free(buf);
        return NULL;
    }
    tm_utc = *tmp; /* struct copy */
#endif
    size_t len = strftime(buf, ISO_8601_BUFSZ, fmt, &tm_utc);
    if (len == 0) {
        free(buf);
        return NULL;
    }
    return buf;
}

/* -------------------------------------------------------------------------
 * NarrativeOption implementation
 * ------------------------------------------------------------------------- */
static void narrative_option_free(struct NarrativeOption *opt)
{
    if (!opt) return;
    free(opt->label);
    free(opt->target_uuid);
}

/* -------------------------------------------------------------------------
 * Public API — NarrativeNode
 * ------------------------------------------------------------------------- */

struct NarrativeNode *narrative_node_new(void)
{
    struct NarrativeNode *node = calloc(1, sizeof *node);
    if (!node) {
        syslog(LOG_ERR, "Failed to allocate NarrativeNode: %s", strerror(errno));
        return NULL;
    }

    /* Generate a fresh UUID (version 4) */
    uuid_t uuid;
    uuid_generate_random(uuid);
    char uuid_str[UUID_STRING_LEN] = {0};
    uuid_unparse_lower(uuid, uuid_str);
    node->uuid = dupstr(uuid_str);
    if (!node->uuid) goto fail;

    node->created_at = node->updated_at = time(NULL);
    node->version_major = 1;
    node->version_minor = 0;
    return node;

fail:
    narrative_node_free(node);
    return NULL;
}

/**
 * Caller owns returned memory.
 */
char *narrative_node_generate_etag(const struct NarrativeNode *node)
{
    assert(node);
    /* A naive but sufficient ETag: weak validator based on UUID + version */
    char buf[128];
    snprintf(buf, sizeof buf, "W/\"%s-%u.%u\"", node->uuid,
             node->version_major, node->version_minor);
    return strdup(buf);
}

bool narrative_node_add_tag(struct NarrativeNode *node, const char *tag)
{
    assert(node && tag);
    char **tmp = reallocarray(node->tags, node->tags_count + 1, sizeof(char *));
    if (!tmp) {
        syslog(LOG_ERR, "Failed to realloc tags: %s", strerror(errno));
        return false;
    }
    node->tags = tmp;
    node->tags[node->tags_count] = dupstr(tag);
    if (!node->tags[node->tags_count]) return false;
    node->tags_count++;
    return true;
}

bool narrative_node_add_option(struct NarrativeNode *node,
                               const char *label,
                               const char *target_uuid)
{
    assert(node && label && target_uuid);
    struct NarrativeOption *tmp =
        reallocarray(node->options, node->options_count + 1,
                     sizeof(struct NarrativeOption));
    if (!tmp) {
        syslog(LOG_ERR, "Failed to realloc options: %s", strerror(errno));
        return false;
    }
    node->options = tmp;

    struct NarrativeOption *opt = &node->options[node->options_count];
    memset(opt, 0, sizeof *opt);
    opt->label = dupstr(label);
    opt->target_uuid = dupstr(target_uuid);
    if (!opt->label || !opt->target_uuid) {
        narrative_option_free(opt);
        return false;
    }
    node->options_count++;
    return true;
}

bool narrative_node_validate(const struct NarrativeNode *node,
                             char **errmsg_out)
{
    if (!node) {
        if (errmsg_out) *errmsg_out = dupstr("Node pointer is NULL");
        return false;
    }
    if (!node->uuid) {
        if (errmsg_out) *errmsg_out = dupstr("UUID is missing");
        return false;
    }
    if (!node->content || strlen(node->content) == 0) {
        if (errmsg_out) *errmsg_out = dupstr("Content cannot be empty");
        return false;
    }
    /* Basic sanity: terminal nodes should not have outgoing options */
    if (node->is_terminal && node->options_count > 0) {
        if (errmsg_out)
            *errmsg_out = dupstr("Terminal node cannot have options");
        return false;
    }
    return true;
}

static json_t *json_from_tags(const struct NarrativeNode *node)
{
    json_t *arr = json_array();
    if (!arr) return NULL;

    for (size_t i = 0; i < node->tags_count; ++i) {
        if (json_array_append_new(arr, json_string(node->tags[i])) < 0) {
            json_decref(arr);
            return NULL;
        }
    }
    return arr;
}

static json_t *json_from_options(const struct NarrativeNode *node)
{
    json_t *arr = json_array();
    if (!arr) return NULL;

    for (size_t i = 0; i < node->options_count; ++i) {
        const struct NarrativeOption *opt = &node->options[i];
        json_t *obj = json_pack("{s:s, s:s}",
                                "label", opt->label,
                                "target_uuid", opt->target_uuid);
        if (!obj || json_array_append_new(arr, obj) < 0) {
            json_decref(obj);
            json_decref(arr);
            return NULL;
        }
    }
    return arr;
}

char *narrative_node_to_json(const struct NarrativeNode *node)
{
    assert(node);

    json_t *root = json_object();
    if (!root) return NULL;

    char *created_iso = timestamp_to_iso8601(node->created_at);
    char *updated_iso = timestamp_to_iso8601(node->updated_at);

    json_t *tags = json_from_tags(node);
    json_t *options = json_from_options(node);

    if (json_object_set_new(root, "uuid", json_string(node->uuid)) < 0 ||
        json_object_set_new(root, "content", json_string(node->content)) < 0 ||
        json_object_set_new(root, "media_ref",
                            node->media_ref ? json_string(node->media_ref)
                                            : json_null()) < 0 ||
        json_object_set_new(root, "is_terminal",
                            json_boolean(node->is_terminal)) < 0 ||
        json_object_set_new(root, "tags", tags ? tags : json_array()) < 0 ||
        json_object_set_new(root, "options", options ? options : json_array()) < 0 ||
        json_object_set_new(root, "version",
                            json_pack("{s:i, s:i}",
                                      "major", (int)node->version_major,
                                      "minor", (int)node->version_minor)) < 0 ||
        json_object_set_new(root, "created_at",
                            created_iso ? json_string(created_iso)
                                        : json_null()) < 0 ||
        json_object_set_new(root, "updated_at",
                            updated_iso ? json_string(updated_iso)
                                        : json_null()) < 0) {
        json_decref(root);
        free(created_iso);
        free(updated_iso);
        return NULL;
    }

    free(created_iso);
    free(updated_iso);

    /* Dump as a compact string. The caller must free the returned char* */
    char *dump = json_dumps(root, JSON_COMPACT);
    json_decref(root);
    return dump;
}

struct NarrativeNode *narrative_node_from_json(const char *json_str,
                                               char **errmsg_out)
{
    json_error_t jerr;
    json_t *root = json_loads(json_str, 0, &jerr);
    if (!root) {
        if (errmsg_out)
            asprintf(errmsg_out, "JSON parse error: %s (line %d, column %d)",
                     jerr.text, jerr.line, jerr.column);
        return NULL;
    }

    struct NarrativeNode *node = narrative_node_new();
    if (!node) {
        json_decref(root);
        return NULL;
    }

    /* UUID */
    json_t *uuid_val = json_object_get(root, "uuid");
    if (json_is_string(uuid_val)) {
        free(node->uuid);
        node->uuid = dupstr(json_string_value(uuid_val));
    }

    /* Content */
    json_t *content_val = json_object_get(root, "content");
    if (json_is_string(content_val)) {
        node->content = dupstr(json_string_value(content_val));
    }

    /* Media ref */
    json_t *media_val = json_object_get(root, "media_ref");
    if (json_is_string(media_val)) {
        node->media_ref = dupstr(json_string_value(media_val));
    }

    /* Tags */
    json_t *tags_val = json_object_get(root, "tags");
    if (json_is_array(tags_val)) {
        size_t index;
        json_t *tag;
        json_array_foreach(tags_val, index, tag)
        {
            if (json_is_string(tag))
                narrative_node_add_tag(node, json_string_value(tag));
        }
    }

    /* Options */
    json_t *opts_val = json_object_get(root, "options");
    if (json_is_array(opts_val)) {
        size_t index;
        json_t *opt;
        json_array_foreach(opts_val, index, opt)
        {
            json_t *lbl = json_object_get(opt, "label");
            json_t *tgt = json_object_get(opt, "target_uuid");
            if (json_is_string(lbl) && json_is_string(tgt)) {
                narrative_node_add_option(node,
                                          json_string_value(lbl),
                                          json_string_value(tgt));
            }
        }
    }

    /* Version */
    json_t *ver_val = json_object_get(root, "version");
    if (json_is_object(ver_val)) {
        json_t *maj = json_object_get(ver_val, "major");
        json_t *min = json_object_get(ver_val, "minor");
        if (json_is_integer(maj))
            node->version_major = (unsigned)json_integer_value(maj);
        if (json_is_integer(min))
            node->version_minor = (unsigned)json_integer_value(min);
    }

    /* Terminal flag */
    json_t *term_val = json_object_get(root, "is_terminal");
    if (json_is_boolean(term_val)) {
        node->is_terminal = json_boolean_value(term_val);
    }

    json_decref(root);
    return node;
}

void narrative_node_free(struct NarrativeNode *node)
{
    if (!node) return;

    free(node->uuid);
    free(node->content);
    free(node->media_ref);

    for (size_t i = 0; i < node->tags_count; ++i)
        free(node->tags[i]);
    free(node->tags);

    for (size_t i = 0; i < node->options_count; ++i)
        narrative_option_free(&node->options[i]);
    free(node->options);

    free(node);
}

/* -------------------------------------------------------------------------
 * Debug & testing utilities
 * ------------------------------------------------------------------------- */
#ifdef SYN_CANVAS_ENABLE_UNIT_TESTS
#include <stdio.h>

static void dump_node(const struct NarrativeNode *node)
{
    char *json = narrative_node_to_json(node);
    if (json) {
        printf("%s\n", json);
        free(json);
    } else {
        printf("Failed to serialize node\n");
    }
}

int main(void)
{
    openlog("narrative_node", LOG_PERROR | LOG_PID, LOG_USER);

    struct NarrativeNode *node = narrative_node_new();
    narrative_node_add_tag(node, "opening");
    narrative_node_add_tag(node, "noir");

    node->content = dupstr(
        "The rain-soaked neon signs flicker as you step into the alley.");
    node->media_ref = dupstr("texture://rain_alley");

    narrative_node_add_option(node, "Follow the cat", "c77eb4fd-e623-426c-a9fa-be3ca0104b6e");
    narrative_node_add_option(node, "Inspect the dumpster", "dbf51fdd-fb7f-4efe-b2b7-a33649f2e5ee");

    char *etag = narrative_node_generate_etag(node);
    printf("ETag: %s\n", etag);
    free(etag);

    dump_node(node);

    narrative_node_free(node);

    closelog();
    return 0;
}
#endif /* SYN_CANVAS_ENABLE_UNIT_TESTS */