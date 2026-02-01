```c
/**
 *  SynestheticCanvas – Narrative Service
 *  -------------------------------------
 *  Public interface definition for the Narrative Service component.
 *
 *  The Narrative Service is responsible for storing, retrieving, and manipulating
 *  branching-narrative graphs that may be consumed by the SynestheticCanvas
 *  Gateway through GraphQL or REST.  A “narrative” is modeled as a directed
 *  acyclic graph (DAG) whose vertices are narrative nodes (story beats) and whose
 *  edges are user-selectable options that determine the next node.  Each node can
 *  be augmented with arbitrarily-typed metadata (e.g., palette hints,
 *  soundtrack IDs, or procedural-generation seeds).
 *
 *  Thread-safety
 *  -------------
 *  The service is fully thread-safe.  A global context is produced by
 *  `ns_init()` and must live for the lifetime of the process.  All mutating
 *  functions employ optimistic locking and will return
 *  `NS_ERR_CONCURRENT_UPDATE` if a version conflict is detected.
 *
 *  Memory ownership
 *  ----------------
 *  All getters allocate deep copies that the caller MUST release via the
 *  provided `ns_free_*` helpers.
 *
 *  Build integration
 *  -----------------
 *  Define `NS_STATIC` to build the library as a header-only component.  In that
 *  case *all* functions become `static inline`.  Otherwise, build the
 *  accompanying `narrative_service.c` and link against the resulting object or
 *  archive.
 *
 *  Copyright (c) 2024
 */

#ifndef SYNESTHETIC_CANVAS_NARRATIVE_SERVICE_H
#define SYNESTHETIC_CANVAS_NARRATIVE_SERVICE_H

/*─ Dependencies ─────────────────────────────────────────────────────────────*/
#include <stddef.h>     /* size_t      */
#include <stdint.h>     /* uint*_t     */
#include <stdbool.h>    /* bool        */
#include <time.h>       /* time_t      */

#ifdef __cplusplus
extern "C" {
#endif

/*─ Symbol export handling (Windows & others) ────────────────────────────────*/
#if defined(_WIN32) && !defined(NS_STATIC)
#  if defined(NS_BUILD_DLL)
#    define NS_API __declspec(dllexport)
#  else
#    define NS_API __declspec(dllimport)
#  endif
#else
#  define NS_API
#endif

/*─ Versioning ───────────────────────────────────────────────────────────────*/
#define NS_VERSION_MAJOR 1
#define NS_VERSION_MINOR 0
#define NS_VERSION_PATCH 0

#define NS_MAKE_VERSION(maj, min, pat)  (((maj) << 16) | ((min) << 8) | (pat))
#define NS_VERSION \
    NS_MAKE_VERSION(NS_VERSION_MAJOR, NS_VERSION_MINOR, NS_VERSION_PATCH)

/*────────────────────────────────────────────────────────────────────────────*
 *  Error handling                                                           *
 *────────────────────────────────────────────────────────────────────────────*/
typedef enum ns_error_e
{
    NS_OK                        = 0, /* Success                                      */
    NS_ERR_UNKNOWN               = 1, /* Unknown / generic failure                    */
    NS_ERR_NOT_INITIALIZED       = 2, /* Service context was not initialised          */
    NS_ERR_INVALID_ARGUMENT      = 3, /* Null or out-of-range argument                */
    NS_ERR_NOT_FOUND             = 4, /* Narrative or node not found                  */
    NS_ERR_CONCURRENT_UPDATE     = 5, /* Optimistic-locking failure                   */
    NS_ERR_PERSISTENCE           = 6, /* Repository/database error                    */
    NS_ERR_OUT_OF_MEMORY         = 7, /* Allocation failed                            */
    NS_ERR_IO                    = 8, /* File or network I/O failure                  */
    NS_ERR_UNSUPPORTED           = 9  /* Operation not supported in current build     */
} ns_error_t;

/*────────────────────────────────────────────────────────────────────────────*
 *  Forward declarations                                                     *
 *────────────────────────────────────────────────────────────────────────────*/
struct ns_narrative_node_s;
struct ns_narrative_s;

/*────────────────────────────────────────────────────────────────────────────*
 *  Narrative node (vertex)                                                  *
 *────────────────────────────────────────────────────────────────────────────*/
typedef struct ns_narrative_node_s
{
    uint64_t           id;              /* Globally unique node identifier            */
    char              *text;            /* UTF-8 narrative text                       */

    /*  Options: arrays are 1-to-1 correlated                                       */
    char             **options;         /* Display text for each user choice          */
    uint64_t          *next_ids;        /* Node IDs reached by corresponding option   */
    size_t             option_cnt;      /* Number of outgoing edges                   */

    /*  Optional metadata                                                           */
    char              *meta_json;       /* JSON blob with arbitrary per-node data     */

    /*  Versioning for optimistic locking                                           */
    uint32_t           rev;             /* Incremented on every write                 */

} ns_narrative_node_t;

/*────────────────────────────────────────────────────────────────────────────*
 *  Narrative graph                                                          *
 *────────────────────────────────────────────────────────────────────────────*/
typedef struct ns_narrative_s
{
    uint64_t              id;           /* Monotonic ID assigned by the repository    */
    char                 *title;        /* Human-readable name                        */
    uint32_t              version;      /* Semantic version of the narrative          */

    ns_narrative_node_t  *nodes;        /* Dynamic array of nodes                     */
    size_t                node_cnt;     /* Number of nodes in the narrative           */

    time_t                created_at;   /* Server-side timestamp                      */
    time_t                updated_at;   /* Last modified                              */

} ns_narrative_t;

/*────────────────────────────────────────────────────────────────────────────*
 *  Pagination descriptor                                                    *
 *────────────────────────────────────────────────────────────────────────────*/
typedef struct ns_page_s
{
    size_t page;         /* 0-based page index (input)                            */
    size_t per_page;     /* requested entities per page (input)                  */
    size_t total;        /* total entities in result set (output)                */
} ns_page_t;

/*────────────────────────────────────────────────────────────────────────────*
 *  Monitoring & tracing callback                                            *
 *────────────────────────────────────────────────────────────────────────────*/
typedef void (*ns_audit_cb)(
        const char   *event_id,
        const char   *payload_json,
        void         *user_data);

/*────────────────────────────────────────────────────────────────────────────*
 *  Service life-cycle                                                       *
 *────────────────────────────────────────────────────────────────────────────*/

/**
 *  ns_init
 *  ----------------------------------------------------------------------------
 *  Initialize the Narrative Service run-time and connect to its backing store.
 *
 *  Parameters
 *  ----------
 *  repo_uri    Zero-terminated URI describing the repository backend.
 *              Example: "postgresql://user:pass@host:5432/syn_canvas"
 *  audit_cb    Optional callback for audit events.  May be NULL.
 *  user_data   Opaque context forwarded to `audit_cb`.
 *
 *  Returns
 *  -------
 *  NS_OK on success, NS_ERR_* otherwise.
 */
NS_API ns_error_t
ns_init(const char *repo_uri, ns_audit_cb audit_cb, void *user_data);

/**
 *  ns_shutdown
 *  ----------------------------------------------------------------------------
 *  Cleanly release all resources previously allocated by `ns_init`.
 */
NS_API void
ns_shutdown(void);

/*────────────────────────────────────────────────────────────────────────────*
 *  CRUD operations                                                          *
 *────────────────────────────────────────────────────────────────────────────*/

/**
 *  ns_narrative_create
 *  ----------------------------------------------------------------------------
 *  Insert a new narrative into the repository.
 *
 *  The caller provides `narr_in` (title, nodes etc.).  On success, `narr_out`
 *  receives a deep copy that owns its memory.  Caller MUST free via
 *  `ns_narrative_free()`.
 */
NS_API ns_error_t
ns_narrative_create(const ns_narrative_t *narr_in, ns_narrative_t **narr_out);

/**
 *  ns_narrative_get
 *  ----------------------------------------------------------------------------
 *  Retrieve a narrative by ID.  The returned object is a deep copy.
 */
NS_API ns_error_t
ns_narrative_get(uint64_t id, ns_narrative_t **narr_out);

/**
 *  ns_narrative_update
 *  ----------------------------------------------------------------------------
 *  Update an existing narrative.  The `rev` field of every node is validated
 *  for optimistic locking.  If mismatched, returns NS_ERR_CONCURRENT_UPDATE.
 */
NS_API ns_error_t
ns_narrative_update(uint64_t id, const ns_narrative_t *narr_in);

/**
 *  ns_narrative_delete
 *  ----------------------------------------------------------------------------
 *  Remove a narrative and all its nodes from the repository.
 */
NS_API ns_error_t
ns_narrative_delete(uint64_t id);

/**
 *  ns_narrative_list
 *  ----------------------------------------------------------------------------
 *  List narratives with pagination.  The function allocates an array of
 *  `ns_narrative_t` of length `*out_count` which the caller must release with
 *  `ns_narrative_array_free`.
 */
NS_API ns_error_t
ns_narrative_list(const ns_page_t *page_req,
                  ns_narrative_t  **out_array,
                  size_t          *out_count,
                  ns_page_t       *out_page);

/*────────────────────────────────────────────────────────────────────────────*
 *  Memory management helpers                                                *
 *────────────────────────────────────────────────────────────────────────────*/

/**
 *  ns_narrative_node_free
 *  ----------------------------------------------------------------------------
 *  Recursively deallocate a single node (including text, options, etc.).
 */
NS_API void
ns_narrative_node_free(ns_narrative_node_t *node);

/**
 *  ns_narrative_free
 *  ----------------------------------------------------------------------------
 *  Release an entire narrative graph.
 */
NS_API void
ns_narrative_free(ns_narrative_t *narr);

/**
 *  ns_narrative_array_free
 *  ----------------------------------------------------------------------------
 *  Free an array previously allocated by `ns_narrative_list`.
 */
NS_API void
ns_narrative_array_free(ns_narrative_t *narr_array, size_t count);

/*────────────────────────────────────────────────────────────────────────────*
 *  Validation utilities                                                     *
 *────────────────────────────────────────────────────────────────────────────*/

/**
 *  ns_narrative_validate
 *  ----------------------------------------------------------------------------
 *  Synchronously validate a narrative object according to service rules.
 *  (e.g., no dangling edges, graph forms a DAG, option counts match).
 */
NS_API ns_error_t
ns_narrative_validate(const ns_narrative_t *narr);

/*────────────────────────────────────────────────────────────────────────────*
 *  Miscellaneous                                                            *
 *────────────────────────────────────────────────────────────────────────────*/

/**
 *  ns_strerror
 *  ----------------------------------------------------------------------------
 *  Return a human-readable string describing an error code.  The pointer is
 *  long-lived and must not be freed by the caller.
 */
NS_API const char *
ns_strerror(ns_error_t err);

/**
 *  ns_set_log_level
 *  ----------------------------------------------------------------------------
 *  Adjust run-time log-verbosity.  Affects only this service.
 */
typedef enum ns_log_level_e
{
    NS_LOG_FATAL = 0,
    NS_LOG_ERROR,
    NS_LOG_WARN,
    NS_LOG_INFO,
    NS_LOG_DEBUG,
    NS_LOG_TRACE
} ns_log_level_t;

NS_API void
ns_set_log_level(ns_log_level_t lvl);

/*────────────────────────────────────────────────────────────────────────────*/
#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* SYNESTHETIC_CANVAS_NARRATIVE_SERVICE_H */
```