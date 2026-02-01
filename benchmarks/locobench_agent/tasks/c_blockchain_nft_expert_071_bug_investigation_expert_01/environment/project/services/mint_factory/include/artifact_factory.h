#ifndef HOLOCANVAS_SERVICES_MINT_FACTORY_INCLUDE_ARTIFACT_FACTORY_H
#define HOLOCANVAS_SERVICES_MINT_FACTORY_INCLUDE_ARTIFACT_FACTORY_H
/*
 * artifact_factory.h
 *
 * Public interface for the HoloCanvas “Mint-Factory” micro-service.
 *
 * The Factory composes user-submitted media fragments into a canonical
 * “Artifact Recipe”, signs a minting transaction, stores the recipe in
 * LedgerCore (the L2 roll-up), and broadcasts a Kafka event.
 *
 * This header purposely exposes only the higher-level, project-internal
 * API.  Wire protocols (gRPC protobufs / Kafka schemas) are defined in
 * separate IDL files and are intentionally hidden from service clients.
 *
 * Thread-safety
 * -------------
 * All opaque handles returned by the API are *reference counted* and
 * thus safe for concurrent use.  Callers must adhere to retain/release
 * discipline.  All functions are re-entrant unless explicitly noted.
 *
 * Error-handling
 * --------------
 * Every function that can fail returns an `artifact_err_t`.  Helper
 * `artifact_strerror()` can be used to obtain human-readable messages.
 */

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------
 * Standard dependencies
 * ---------------------------------------------------------- */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <time.h>

/* ------------------------------------------------------------
 * Constants & limits
 * ---------------------------------------------------------- */
#define ARTIFACT_UUID_BYTES    16     /* Raw UUIDv4 bytes      */
#define ARTIFACT_UUID_STRLEN   36     /* Printable string size */
#define ARTIFACT_HASH_MAXLEN  128     /* Hex-encoded SHA-256   */

/* ------------------------------------------------------------
 * Typedefs
 * ---------------------------------------------------------- */
typedef uint64_t artist_id_t;

/* Handle forward declarations (opaque to callers) */
typedef struct artifact       artifact_t;
typedef struct artifact_pkg   artifact_pkg_t;
typedef struct factory_ctx    factory_ctx_t;
typedef struct factory_cfg    factory_cfg_t;
typedef struct tx_context     tx_context_t;

/* ------------------------------------------------------------
 * Error codes
 * ---------------------------------------------------------- */
typedef enum artifact_err {
    ARTIFACT_OK               =  0,
    ARTIFACT_ERR_NO_MEMORY    = -1,
    ARTIFACT_ERR_INVALID_ARG  = -2,
    ARTIFACT_ERR_STATE        = -3,
    ARTIFACT_ERR_IO           = -4,
    ARTIFACT_ERR_CRYPTO       = -5,
    ARTIFACT_ERR_NETWORK      = -6,
    ARTIFACT_ERR_NOT_FOUND    = -7,
    ARTIFACT_ERR_TIMEOUT      = -8,
    ARTIFACT_ERR_INTERNAL     = -9
} artifact_err_t;

/* ------------------------------------------------------------
 * Life-cycle state machine (mirrors consensus layer)
 * ---------------------------------------------------------- */
typedef enum artifact_state {
    ARTIFACT_STATE_DRAFT          = 0,
    ARTIFACT_STATE_CURATED        = 1,
    ARTIFACT_STATE_AUCTION        = 2,
    ARTIFACT_STATE_FRACTIONALIZED = 3,
    ARTIFACT_STATE_STAKED         = 4,
    ARTIFACT_STATE_RETIRED        = 5
} artifact_state_t;

/* ------------------------------------------------------------
 * Artifact specification supplied by creators
 * ---------------------------------------------------------- */
typedef struct artifact_spec {
    artist_id_t  creator_id;                                 /* wallet id */
    char         uuid[ARTIFACT_UUID_STRLEN + 1];             /* canonical */
    char         shader_hash[ARTIFACT_HASH_MAXLEN];          /* SHA-256   */
    char         audio_hash[ARTIFACT_HASH_MAXLEN];
    char         metadata_hash[ARTIFACT_HASH_MAXLEN];
    uint64_t     created_at_ms;                              /* epoch ms  */
} artifact_spec_t;

/* ------------------------------------------------------------
 * Configuration helpers
 * ---------------------------------------------------------- */
/* Allocate config with sane defaults (caller owns) */
factory_cfg_t *factory_cfg_new(void);

/* Configure Kafka broker list (string is strdup()’d) */
artifact_err_t factory_cfg_set_kafka_brokers(factory_cfg_t *cfg,
                                             const char    *brokers);

/* Configure encrypted keystore path (for tx signing) */
artifact_err_t factory_cfg_set_keystore_path(factory_cfg_t *cfg,
                                             const char    *path);

/* Destroy config and free memory */
void factory_cfg_free(factory_cfg_t *cfg);

/* ------------------------------------------------------------
 * Boot / shutdown
 * ---------------------------------------------------------- */
factory_ctx_t *factory_ctx_bootstrap(const factory_cfg_t *cfg,
                                     artifact_err_t      *out_err);

void factory_ctx_shutdown(factory_ctx_t *ctx);

/* ------------------------------------------------------------
 * Artifact spec validation
 * ---------------------------------------------------------- */
artifact_err_t artifact_spec_validate(const artifact_spec_t *spec);

/* ------------------------------------------------------------
 * Minting / life-cycle management
 * ---------------------------------------------------------- */
artifact_t *artifact_mint(factory_ctx_t           *ctx,
                          const artifact_spec_t   *spec,
                          artifact_err_t          *out_err);

/* Ref-count helpers */
artifact_t *artifact_retain(artifact_t *artifact);
void        artifact_release(artifact_t *artifact);

/* State & metadata accessors */
artifact_state_t artifact_get_state(const artifact_t *artifact);
const char      *artifact_get_uuid(const artifact_t *artifact);

/* Serialize recipe + proof into self-contained package */
artifact_pkg_t *artifact_serialize(const artifact_t *artifact,
                                   artifact_err_t   *out_err);
void            artifact_pkg_free(artifact_pkg_t *pkg);

/* ------------------------------------------------------------
 * Transaction helper API (internal use)
 * ---------------------------------------------------------- */
tx_context_t *factory_begin_tx(factory_ctx_t *ctx,
                               artifact_err_t *out_err);
artifact_err_t factory_commit_tx(tx_context_t *tx);
void           factory_rollback_tx(tx_context_t *tx);

/* ------------------------------------------------------------
 * Utility functions
 * ---------------------------------------------------------- */
const char *artifact_strerror(artifact_err_t err_code);

/* Generate UUIDv4 (dest must be >= 37 bytes incl. NUL) */
void artifact_generate_uuid(char dest[ARTIFACT_UUID_STRLEN + 1]);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* HOLOCANVAS_SERVICES_MINT_FACTORY_INCLUDE_ARTIFACT_FACTORY_H */