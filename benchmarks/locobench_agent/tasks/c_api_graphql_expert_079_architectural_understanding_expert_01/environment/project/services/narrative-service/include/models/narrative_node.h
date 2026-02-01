/**
 * SynestheticCanvas Narrative Service
 * File: models/narrative_node.h
 *
 * Description:
 *   Data model and utility helpers for a single branching-story node that can be
 *   persisted in, or retrieved from, the Narrative-Service domain.  The data
 *   structure is intentionally “fat” because narrative nodes travel through
 *   many layers (GraphQL resolvers, REST handlers, repository adapters, and
 *   observers).  Each field is therefore self-contained so that downstream
 *   services can cache, serialize, and validate without additional look-ups.
 *
 *   NOTE: This header provides fully-inline implementations for convenience.
 *         Move heavy-weight functions into a dedicated *.c translation unit
 *         when the calling graph grows, or when you need stricter visibility
 *         control / LTO wins.
 */

#ifndef SYNESTHETIC_CANVAS_NARRATIVE_NODE_H
#define SYNESTHETIC_CANVAS_NARRATIVE_NODE_H

/* ────────────────────────────────────────────────────────────────────────── */
/* System headers                                                            */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* 3rd-party                                                              */
#include <jansson.h>       /* https://digip.org/jansson/ */
#include <uuid/uuid.h>     /* libuuid */

/* ────────────────────────────────────────────────────────────────────────── */
/* Macro helpers                                                            */
#define SCNARR_SUCCESS                (0)
#define SCNARR_ERR_NOMEM             (-ENOMEM)
#define SCNARR_ERR_INVALID_ARGUMENT  (-EINVAL)

/* ────────────────────────────────────────────────────────────────────────── */
/* Internal utility wrappers                                                */

/* strdup is not part of ISO C, so wrap it for portability */
static inline char *scnarr_strdup(const char *s)
{
    if (!s) return NULL;

    char *dup = strdup(s);
    if (!dup) {
        /* Calling functions translate NULL into -ENOMEM. */
    }
    return dup;
}

static inline char *scnarr_gen_uuid(void)
{
    uuid_t uuid;
    uuid_generate(uuid);

    char *buf = malloc(37); /* 36 + '\0' */
    if (!buf) {
        return NULL;
    }
    uuid_unparse_lower(uuid, buf);
    return buf;
}

/* ────────────────────────────────────────────────────────────────────────── */
/* Data structures                                                          */

/* A choice (“edge”) that leads from the current node to another node. */
typedef struct scnarr_choice {
    char *choice_id;        /* Unique identifier (uuid) for this choice      */
    char *description;      /* What the user sees                            */
    char *target_node_id;   /* Foreign key to the next narrative node        */
} scnarr_choice_t;

/* Main narrative node.                                                      */
typedef struct scnarr_node {
    char           *node_id;         /* Primary key (uuid)                   */
    char           *title;           /* Short label                          */
    char           *content;         /* Long-form prose / markdown           */
    char           *media_reference; /* Optional external media locator      */
    char           *author;          /* Attribution                          */

    /* Tags for classification and search. */
    char          **tags;
    size_t          tag_count;

    /* Branching choices. */
    scnarr_choice_t *choices;
    size_t           choice_count;

    /* Auditing / concurrency control. */
    time_t           created_at;
    time_t           updated_at;
} scnarr_node_t;

/* ────────────────────────────────────────────────────────────────────────── */
/* API declarations (documentation only, see static inline impl. below)     */

/**
 * scnarr_node_create
 *   Allocate and fully initialize a new narrative node.
 *
 * Parameters:
 *   title   - Display title (copied)
 *   content - Body text (copied)
 *   author  - Author identifier (copied)
 *
 * Returns:
 *   Pointer to a new scnarr_node_t on success, NULL otherwise (errno-style
 *   error codes returned via `errno`).
 */
static inline scnarr_node_t *
scnarr_node_create(const char *title,
                   const char *content,
                   const char *author);

/**
 * scnarr_node_set_media_reference
 *   Assign or replace media reference URL/path.
 */
static inline int
scnarr_node_set_media_reference(scnarr_node_t *node,
                                const char     *media_ref);

/**
 * scnarr_node_add_tag
 *   Append a tag.
 */
static inline int
scnarr_node_add_tag(scnarr_node_t *node,
                    const char    *tag);

/**
 * scnarr_node_add_choice
 *   Append a branching choice.
 */
static inline int
scnarr_node_add_choice(scnarr_node_t *node,
                       const char    *description,
                       const char    *target_node_id);

/**
 * scnarr_node_serialize
 *   Convert structure into a Jansson JSON object.  Caller owns the reference
 *   on success and must json_decref(result) later.
 */
static inline json_t *
scnarr_node_serialize(const scnarr_node_t *node);

/**
 * scnarr_node_deserialize
 *   Inverse of _serialize.  Returns heap-allocated node or NULL on error.
 */
static inline scnarr_node_t *
scnarr_node_deserialize(const json_t *json);

/**
 * scnarr_node_destroy
 *   Recursively free all heap memory owned by the node.
 */
static inline void
scnarr_node_destroy(scnarr_node_t *node);

/* ────────────────────────────────────────────────────────────────────────── */
/* Implementation                                                            */

static inline scnarr_node_t *
scnarr_node_create(const char *title,
                   const char *content,
                   const char *author)
{
    /* Validate */
    if (!title || !content || !author) {
        errno = EINVAL;
        return NULL;
    }

    scnarr_node_t *node = calloc(1, sizeof(*node));
    if (!node) {
        errno = ENOMEM;
        return NULL;
    }

    /* Copy immutable data */
    node->node_id  = scnarr_gen_uuid();
    node->title    = scnarr_strdup(title);
    node->content  = scnarr_strdup(content);
    node->author   = scnarr_strdup(author);

    if (!node->node_id || !node->title || !node->content || !node->author) {
        scnarr_node_destroy(node);
        errno = ENOMEM;
        return NULL;
    }

    node->created_at = node->updated_at = time(NULL);
    return node;
}

static inline int
scnarr_node_set_media_reference(scnarr_node_t *node,
                                const char     *media_ref)
{
    if (!node) return SCNARR_ERR_INVALID_ARGUMENT;

    /* Free previous value if any */
    free(node->media_reference);
    node->media_reference = NULL;

    if (media_ref) {
        node->media_reference = scnarr_strdup(media_ref);
        if (!node->media_reference)
            return SCNARR_ERR_NOMEM;
    }

    node->updated_at = time(NULL);
    return SCNARR_SUCCESS;
}

static inline int
scnarr_node_add_tag(scnarr_node_t *node,
                    const char    *tag)
{
    if (!node || !tag) return SCNARR_ERR_INVALID_ARGUMENT;

    char **tmp = realloc(node->tags, sizeof(char *) * (node->tag_count + 1));
    if (!tmp) return SCNARR_ERR_NOMEM;

    node->tags = tmp;
    node->tags[node->tag_count] = scnarr_strdup(tag);
    if (!node->tags[node->tag_count])
        return SCNARR_ERR_NOMEM;

    node->tag_count++;
    node->updated_at = time(NULL);
    return SCNARR_SUCCESS;
}

static inline int
scnarr_node_add_choice(scnarr_node_t *node,
                       const char    *description,
                       const char    *target_node_id)
{
    if (!node || !description || !target_node_id)
        return SCNARR_ERR_INVALID_ARGUMENT;

    scnarr_choice_t *tmp = realloc(
        node->choices,
        sizeof(scnarr_choice_t) * (node->choice_count + 1)
    );
    if (!tmp) return SCNARR_ERR_NOMEM;

    node->choices = tmp;

    scnarr_choice_t *choice = &node->choices[node->choice_count];
    memset(choice, 0, sizeof(*choice));

    choice->choice_id      = scnarr_gen_uuid();
    choice->description    = scnarr_strdup(description);
    choice->target_node_id = scnarr_strdup(target_node_id);

    if (!choice->choice_id || !choice->description || !choice->target_node_id)
        return SCNARR_ERR_NOMEM;

    node->choice_count++;
    node->updated_at = time(NULL);
    return SCNARR_SUCCESS;
}

static inline json_t *
scnarr_node_serialize(const scnarr_node_t *node)
{
    if (!node) {
        errno = EINVAL;
        return NULL;
    }

    json_t *root = json_object();
    if (!root) goto oom;

    #define ADD_STRING(key, val)                        \
        do {                                            \
            if (val) {                                  \
                if (json_object_set_new(                \
                        root, key, json_string(val)))   \
                    goto oom;                           \
            }                                           \
        } while (0)

    ADD_STRING("nodeId",  node->node_id);
    ADD_STRING("title",   node->title);
    ADD_STRING("content", node->content);
    ADD_STRING("media",   node->media_reference);
    ADD_STRING("author",  node->author);

    json_object_set_new(root, "createdAt", json_integer(node->created_at));
    json_object_set_new(root, "updatedAt", json_integer(node->updated_at));

    /* Tags */
    if (node->tag_count) {
        json_t *tags = json_array();
        if (!tags) goto oom;
        for (size_t i = 0; i < node->tag_count; ++i) {
            json_array_append_new(tags, json_string(node->tags[i]));
        }
        json_object_set_new(root, "tags", tags);
    }

    /* Choices */
    if (node->choice_count) {
        json_t *choices = json_array();
        if (!choices) goto oom;
        for (size_t i = 0; i < node->choice_count; ++i) {
            const scnarr_choice_t *c = &node->choices[i];
            json_t *jc = json_object();
            if (!jc) goto oom;

            ADD_STRING("choiceId",  c->choice_id);
            ADD_STRING("text",      c->description);
            ADD_STRING("targetId",  c->target_node_id);

            json_array_append_new(choices, jc);
        }
        json_object_set_new(root, "choices", choices);
    }

    #undef ADD_STRING

    return root;

oom:
    json_decref(root);
    errno = ENOMEM;
    return NULL;
}

static inline scnarr_node_t *
scnarr_node_deserialize(const json_t *json)
{
    if (!json || !json_is_object(json)) {
        errno = EINVAL;
        return NULL;
    }

    #define GET_STRING(obj, key)                                     \
        (json_object_get(obj, key) &&                                \
         json_is_string(json_object_get(obj, key))                   \
             ? json_string_value(json_object_get(obj, key))          \
             : NULL)

    scnarr_node_t *node = scnarr_node_create(
        GET_STRING(json, "title")   ?: "",
        GET_STRING(json, "content") ?: "",
        GET_STRING(json, "author")  ?: ""
    );
    if (!node) return NULL;

    /* Overwrite nodeId if present */
    const char *nid = GET_STRING(json, "nodeId");
    if (nid) {
        free(node->node_id);
        node->node_id = scnarr_strdup(nid);
        if (!node->node_id) goto oom;
    }

    /* Media */
    const char *media = GET_STRING(json, "media");
    if (media && scnarr_node_set_media_reference(node, media) != SCNARR_SUCCESS)
        goto oom;

    /* Tags */
    json_t *tags_json = json_object_get(json, "tags");
    if (tags_json && json_is_array(tags_json)) {
        size_t idx;
        json_t *tag;
        json_array_foreach(tags_json, idx, tag) {
            if (!json_is_string(tag) ||
                scnarr_node_add_tag(node, json_string_value(tag)) != SCNARR_SUCCESS)
                goto oom;
        }
    }

    /* Choices */
    json_t *choices_json = json_object_get(json, "choices");
    if (choices_json && json_is_array(choices_json)) {
        size_t idx;
        json_t *cj;
        json_array_foreach(choices_json, idx, cj) {
            const char *desc = GET_STRING(cj, "text");
            const char *tgt  = GET_STRING(cj, "targetId");

            if (!desc || !tgt ||
                scnarr_node_add_choice(node, desc, tgt) != SCNARR_SUCCESS)
                goto oom;

            /* Override generated choiceId if provided */
            const char *cid = GET_STRING(cj, "choiceId");
            if (cid) {
                scnarr_choice_t *c = &node->choices[node->choice_count - 1];
                free(c->choice_id);
                c->choice_id = scnarr_strdup(cid);
                if (!c->choice_id) goto oom;
            }
        }
    }

    node->created_at =
        json_integer_value(json_object_get(json, "createdAt")) ?: node->created_at;
    node->updated_at =
        json_integer_value(json_object_get(json, "updatedAt")) ?: node->updated_at;

    #undef GET_STRING
    return node;

oom:
    scnarr_node_destroy(node);
    errno = ENOMEM;
    return NULL;
}

static inline void
scnarr_node_destroy(scnarr_node_t *node)
{
    if (!node) return;

    /* Simple fields */
    free(node->node_id);
    free(node->title);
    free(node->content);
    free(node->media_reference);
    free(node->author);

    /* Tags */
    for (size_t i = 0; i < node->tag_count; ++i)
        free(node->tags[i]);
    free(node->tags);

    /* Choices */
    for (size_t i = 0; i < node->choice_count; ++i) {
        scnarr_choice_t *c = &node->choices[i];
        free(c->choice_id);
        free(c->description);
        free(c->target_node_id);
    }
    free(node->choices);

    free(node);
}

#endif /* SYNESTHETIC_CANVAS_NARRATIVE_NODE_H */
