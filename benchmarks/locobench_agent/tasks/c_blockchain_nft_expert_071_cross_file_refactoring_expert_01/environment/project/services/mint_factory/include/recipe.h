```c
/*======================================================================
 * File:    services/mint_factory/include/recipe.h
 * Project: HoloCanvas – Mint-Factory Micro-service
 *
 * Description:
 *   A “recipe” is the immutable blueprint for an audiovisual NFT.  It
 *   records the ordered set of shader, audio and metadata fragments
 *   selected by the creator, along with a manifest hash and the
 *   creator’s Ed25519 signature.  Once persisted on-chain, the recipe
 *   guarantees deterministic re-construction of the artifact while
 *   allowing higher-level DAO mechanisms to mutate the *state* (e.g.,
 *   which layer is currently active) without ever altering the recipe
 *   itself.
 *
 *   This header is self-contained:  add
 *       #define HOLOCANVAS_RECIPE_IMPLEMENTATION
 *   in *one* C/C++ translation unit before including this header to pull
 *   in the full implementation.  All other units should simply include
 *   the header for access to the public API.
 *
 *   External Dependencies (compile-time):
 *     • BLAKE3   – https://github.com/BLAKE3-team/BLAKE3
 *     • TinyCBOR – https://github.com/intel/tinycbor
 *     • an Ed25519 provider (tweetnacl / libsodium, etc.)
 *
 *   The implementation only touches the generic Ed25519 API via an
 *   injected callback, so you stay free to select your crypto backend.
 *====================================================================*/

#ifndef HOLOCANVAS_MINT_FACTORY_RECIPE_H
#define HOLOCANVAS_MINT_FACTORY_RECIPE_H

/*--------------------------------------------------------------------
 * Standard & system includes
 *------------------------------------------------------------------*/
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <time.h>
#include <stdio.h>
#include <string.h>

/*--------------------------------------------------------------------
 * Compile-time configuration
 *------------------------------------------------------------------*/
#ifndef RECIPE_MAX_ID_LEN
#   define RECIPE_MAX_ID_LEN          64      /* UUID v4 string */
#endif

#ifndef RECIPE_MAX_CREATOR_LEN
#   define RECIPE_MAX_CREATOR_LEN     64      /* ENS or user handle */
#endif

#ifndef RECIPE_MAX_SEGMENTS
#   define RECIPE_MAX_SEGMENTS        32
#endif

#define RECIPE_HASH_SIZE              32      /* BLAKE3 output */
#define RECIPE_SIG_SIZE               64      /* Ed25519 sig */
#define RECIPE_NONCE_SIZE             12

#define RECIPE_SCHEMA_VERSION         1U

/*--------------------------------------------------------------------
 * Public data types
 *------------------------------------------------------------------*/
#ifdef __cplusplus
extern "C" {
#endif

typedef enum
{
    RECIPE_SEG_SHADER = 0,
    RECIPE_SEG_AUDIO  = 1,
    RECIPE_SEG_META   = 2,
    RECIPE_SEG_CUSTOM = 3
} recipe_segment_type_t;


/* One entry in the ordered segment list */
typedef struct
{
    recipe_segment_type_t type;                         /* shader/audio/... */
    uint8_t               hash[RECIPE_HASH_SIZE];       /* BLAKE3 of blob   */
    uint32_t              size_bytes;                   /* original length  */
} recipe_segment_t;


/* The full recipe payload */
typedef struct
{
    /* ---- Header ---- */
    char      artifact_id[RECIPE_MAX_ID_LEN];           /* UUID v4 (ASCII)  */
    char      creator[RECIPE_MAX_CREATOR_LEN];          /* creator handle   */
    uint8_t   version;                                  /* schema version   */
    time_t    timestamp;                                /* UNIX epoch       */

    uint8_t   nonce[RECIPE_NONCE_SIZE];                 /* 96-bit entropy   */

    /* ---- Segments ---- */
    recipe_segment_t segments[RECIPE_MAX_SEGMENTS];
    size_t           seg_count;                         /* number used      */

    /* Manifest hash = BLAKE3(concat(segment.hash))      */
    uint8_t   manifest_hash[RECIPE_HASH_SIZE];

    /* Capabilities bitset (DAO may read this)           */
    uint32_t  capabilities;                             /* 0–31 reserved    */

    /* Creator’s Ed25519 signature over CBOR encoding    */
    uint8_t   signature[RECIPE_SIG_SIZE];
} recipe_t;

/*--------------------------------------------------------------------
 * Public API
 *------------------------------------------------------------------*/

/* Zero-init with defaults. */
void recipe_init(recipe_t *r);

/* Append a segment; fails if capacity exhausted or args invalid. */
int  recipe_add_segment(recipe_t                    *r,
                        recipe_segment_type_t        type,
                        const uint8_t                hash[RECIPE_HASH_SIZE],
                        uint32_t                     size_bytes);

/* (Re-)calculate manifest_hash from segment list. */
int  recipe_compute_manifest(recipe_t *r);

/*
 * Encode recipe as canonical CBOR (Deterministic, per RFC 8949 §4.2.1).
 * If `buf` is NULL, `*buf_len` will be set to the required size.
 * Returns 0 on success, –1 on error.
 */
int  recipe_encode_cbor(const recipe_t *r,
                        uint8_t        *buf,
                        size_t         *buf_len);

/*
 * Decode CBOR into struct; performs basic sanity checks.
 * Returns 0 on success, –1 on error.
 */
int  recipe_decode_cbor(const uint8_t *buf,
                        size_t         buf_len,
                        recipe_t      *out);

/*
 * Verify manifest and Ed25519 signature.
 *
 *   verify_sig – user-supplied callback:
 *       int cb(const uint8_t *msg, size_t msg_len,
 *              const uint8_t *sig,
 *              const uint8_t *pubkey);   // returns 0 = valid
 *
 * Returns 0 if OK, –1 otherwise.
 */
int  recipe_verify(const recipe_t *r,
                   int (*verify_sig)(const uint8_t *msg,
                                      size_t        msg_len,
                                      const uint8_t *sig,
                                      const uint8_t *pubkey));

/* Pretty-print to stdout (debug only). */
void recipe_print(const recipe_t *r);

/* Securely wipe entire struct from memory. */
void recipe_wipe(recipe_t *r);

#ifdef __cplusplus
} /* extern "C" */
#endif


/*======================================================================
 *                       IMPLEMENTATION SECTION
 *====================================================================*/
#ifdef HOLOCANVAS_RECIPE_IMPLEMENTATION

/*--------------------------------------------------------------------
 * Third-party libraries
 *------------------------------------------------------------------*/
#include <blake3.h>
#include <tinycbor/cbor.h>
#include <tinycbor/cborjson.h>

/*--------------------------------------------------------------------
 * Internal helpers
 *------------------------------------------------------------------*/
#define CHECK(expr)          do { if (!(expr)) return -1; } while(0)
#define MIN(a,b)             ((a) < (b) ? (a) : (b))

static inline void
secure_memzero(void *p, size_t n)
{
#if defined(__STDC_LIB_EXT1__)
    memset_s(p, n, 0, n);
#elif defined(_WIN32)
    SecureZeroMemory(p, n);
#else
    volatile uint8_t *vp = (volatile uint8_t *)p;
    while (n--) *vp++ = 0;
#endif
}

/*--------------------------------------------------------------------
 * Public functions
 *------------------------------------------------------------------*/
void
recipe_init(recipe_t *r)
{
    if (!r) return;
    memset(r, 0, sizeof(*r));
    r->version    = RECIPE_SCHEMA_VERSION;
    r->timestamp  = time(NULL);

    /* Grab entropy for nonce (best effort). */
    FILE *urnd = fopen("/dev/urandom", "rb");
    if (urnd && fread(r->nonce, 1, RECIPE_NONCE_SIZE, urnd) == RECIPE_NONCE_SIZE)
        ; /* success */
    else
        /* fallback (NOT cryptographically strong; acceptable for nonce) */
        for (size_t i = 0; i < RECIPE_NONCE_SIZE; ++i)
            r->nonce[i] = (uint8_t)rand();
    if (urnd) fclose(urnd);
}

int
recipe_add_segment(recipe_t                    *r,
                   recipe_segment_type_t        type,
                   const uint8_t                hash[RECIPE_HASH_SIZE],
                   uint32_t                     size_bytes)
{
    if (!r || !hash) return -1;
    CHECK(r->seg_count < RECIPE_MAX_SEGMENTS);

    recipe_segment_t *seg = &r->segments[r->seg_count++];
    seg->type       = type;
    memcpy(seg->hash, hash, RECIPE_HASH_SIZE);
    seg->size_bytes = size_bytes;
    return 0;
}

int
recipe_compute_manifest(recipe_t *r)
{
    if (!r) return -1;
    blake3_hasher h;
    blake3_hasher_init(&h);

    for (size_t i = 0; i < r->seg_count; ++i)
        blake3_hasher_update(&h, r->segments[i].hash, RECIPE_HASH_SIZE);

    blake3_hasher_finalize(&h, r->manifest_hash, RECIPE_HASH_SIZE);
    return 0;
}

/*----------------- CBOR helper: encode a single segment -------------*/
static int
_cbor_encode_segment(CborEncoder *enc_map,
                     const recipe_segment_t *s)
{
    CborError err;
    CborEncoder map;
    err = cbor_encoder_create_map(enc_map, &map, 3);
    CHECK(err == CborNoError);

    err |= cbor_encode_text_stringz(&map, "t");   /* type  */
    err |= cbor_encode_uint(&map, s->type);

    err |= cbor_encode_text_stringz(&map, "h");   /* hash  */
    err |= cbor_encode_byte_string(&map, s->hash, RECIPE_HASH_SIZE);

    err |= cbor_encode_text_stringz(&map, "s");   /* size  */
    err |= cbor_encode_uint(&map, s->size_bytes);

    err |= cbor_encoder_close_container(enc_map, &map);
    return err == CborNoError ? 0 : -1;
}

int
recipe_encode_cbor(const recipe_t *r,
                   uint8_t        *buf,
                   size_t         *buf_len)
{
    if (!r || !buf_len) return -1;

    CborEncoder root;
    CborEncoder map, array;
    CborError   err;

    /* First pass: only size calculation? */
    size_t dummy_len = 0;
    uint8_t dummy[1];
    uint8_t *out_buf   = buf ? buf : dummy;
    size_t   out_len   = buf ? *buf_len : 0;

    cbor_encoder_init(&root, out_buf, out_len, CborEncodingIndefiniteLength);

    err = cbor_encoder_create_map(&root, &map, 10);
    CHECK(err == CborNoError);

    /* (1) primitive fields */
    err |= cbor_encode_text_stringz(&map, "id");
    err |= cbor_encode_text_stringz(&map, r->artifact_id);

    err |= cbor_encode_text_stringz(&map, "cr");
    err |= cbor_encode_text_stringz(&map, r->creator);

    err |= cbor_encode_text_stringz(&map, "v");
    err |= cbor_encode_uint(&map, r->version);

    err |= cbor_encode_text_stringz(&map, "ts");
    err |= cbor_encode_uint(&map, (uint64_t)r->timestamp);

    err |= cbor_encode_text_stringz(&map, "n");
    err |= cbor_encode_byte_string(&map, r->nonce, RECIPE_NONCE_SIZE);

    /* (2) segments list */
    err |= cbor_encode_text_stringz(&map, "seg");
    err |= cbor_encoder_create_array(&map, &array, r->seg_count);

    for (size_t i = 0; i < r->seg_count; ++i)
        err |= _cbor_encode_segment(&array, &r->segments[i]);

    err |= cbor_encoder_close_container(&map, &array);

    /* (3) manifest */
    err |= cbor_encode_text_stringz(&map, "m");
    err |= cbor_encode_byte_string(&map, r->manifest_hash, RECIPE_HASH_SIZE);

    /* (4) capabilities */
    err |= cbor_encode_text_stringz(&map, "cap");
    err |= cbor_encode_uint(&map, r->capabilities);

    /* (5) signature */
    err |= cbor_encode_text_stringz(&map, "sig");
    err |= cbor_encode_byte_string(&map, r->signature, RECIPE_SIG_SIZE);

    err |= cbor_encoder_close_container(&root, &map);
    err |= cbor_encoder_close_container(&root, NULL); /* Indefinite root */

    if (err != CborNoError) return -1;

    size_t encoded = cbor_encoder_get_buffer_size(&root, out_buf);
    if (buf == NULL)
    {
        *buf_len = encoded;
        return 0;
    }
    if (encoded > *buf_len) return -1;
    *buf_len = encoded;
    return 0;
}

/*--------------------------- CBOR decode ---------------------------*/
static int
_cbor_get_required_bytes(const CborValue *v, const char *label,
                         const uint8_t **out, size_t *out_len)
{
    if (!cbor_value_is_byte_string(v)) return -1;
    CborError err = cbor_value_dup_byte_string(v, (uint8_t**)out, out_len, NULL);
    (void)label; /* unused in NDEBUG but helpful in debug */
    return err == CborNoError ? 0 : -1;
}

static int
_cbor_decode_segment(const CborValue *it, recipe_segment_t *s)
{
    if (!cbor_value_is_map(it)) return -1;
    CborValue map_it;
    CborError err = cbor_value_enter_container(it, &map_it);
    CHECK(err == CborNoError);

    while (!cbor_value_at_end(&map_it))
    {
        char key[4] = {0};
        size_t klen = sizeof(key) - 1;

        err = cbor_value_copy_text_string(&map_it, key, &klen, &map_it);
        CHECK(err == CborNoError);

        if (strcmp(key, "t") == 0)
        {
            uint64_t val;
            err = cbor_value_get_uint64(&map_it, &val);
            CHECK(err == CborNoError);
            s->type = (recipe_segment_type_t)val;
        }
        else if (strcmp(key, "h") == 0)
        {
            size_t len = RECIPE_HASH_SIZE;
            err = cbor_value_copy_byte_string(&map_it, s->hash, &len, &map_it);
            CHECK(err == CborNoError && len == RECIPE_HASH_SIZE);
        }
        else if (strcmp(key, "s") == 0)
        {
            uint64_t val;
            err = cbor_value_get_uint64(&map_it, &val);
            CHECK(err == CborNoError);
            s->size_bytes = (uint32_t)val;
        }
        else
        {
            /* skip unknown */
            err = cbor_value_advance_fixed(&map_it);
            CHECK(err == CborNoError);
        }
        err = cbor_value_advance(&map_it);
    }
    err = cbor_value_leave_container(it, &map_it);
    return err == CborNoError ? 0 : -1;
}

int
recipe_decode_cbor(const uint8_t *buf,
                   size_t         buf_len,
                   recipe_t      *out)
{
    if (!buf || !out) return -1;
    memset(out, 0, sizeof(*out));

    CborParser parser;
    CborValue  it;
    CborError  err = cbor_parser_init(buf, buf_len, 0, &parser, &it);
    CHECK(err == CborNoError);

    /* Root must be a map */
    if (!cbor_value_is_map(&it)) return -1;
    CborValue map_it;
    err = cbor_value_enter_container(&it, &map_it);
    CHECK(err == CborNoError);

    while (!cbor_value_at_end(&map_it))
    {
        char key[8] = {0};
        size_t klen = sizeof(key)-1;
        err = cbor_value_copy_text_string(&map_it, key, &klen, &map_it);
        CHECK(err == CborNoError);

        if (strcmp(key, "id") == 0)
        {
            size_t len = RECIPE_MAX_ID_LEN;
            err = cbor_value_copy_text_string(&map_it, out->artifact_id, &len, &map_it);
            CHECK(err == CborNoError);
        }
        else if (strcmp(key, "cr") == 0)
        {
            size_t len = RECIPE_MAX_CREATOR_LEN;
            err = cbor_value_copy_text_string(&map_it, out->creator, &len, &map_it);
            CHECK(err == CborNoError);
        }
        else if (strcmp(key, "v") == 0)
        {
            uint64_t v;
            err = cbor_value_get_uint64(&map_it, &v);
            CHECK(err == CborNoError);
            out->version = (uint8_t)v;
        }
        else if (strcmp(key, "ts") == 0)
        {
            uint64_t v;
            err = cbor_value_get_uint64(&map_it, &v);
            CHECK(err == CborNoError);
            out->timestamp = (time_t)v;
        }
        else if (strcmp(key, "n") == 0)
        {
            size_t len = RECIPE_NONCE_SIZE;
            err = cbor_value_copy_byte_string(&map_it, out->nonce, &len, &map_it);
            CHECK(err == CborNoError && len == RECIPE_NONCE_SIZE);
        }
        else if (strcmp(key, "seg") == 0)
        {
            if (!cbor_value_is_array(&map_it)) return -1;
            CborValue arr_it;
            err = cbor_value_enter_container(&map_it, &arr_it);
            CHECK(err == CborNoError);

            while (!cbor_value_at_end(&arr_it))
            {
                CHECK(out->seg_count < RECIPE_MAX_SEGMENTS);
                err = _cbor_decode_segment(&arr_it, &out->segments[out->seg_count++]);
                CHECK(err == CborNoError);
                err = cbor_value_advance(&arr_it);
            }
            err = cbor_value_leave_container(&map_it, &arr_it);
            CHECK(err == CborNoError);
        }
        else if (strcmp(key, "m") == 0)
        {
            size_t len = RECIPE_HASH_SIZE;
            err = cbor_value_copy_byte_string(&map_it, out->manifest_hash, &len, &map_it);
            CHECK(err == CborNoError && len == RECIPE_HASH_SIZE);
        }
        else if (strcmp(key, "cap") == 0)
        {
            uint64_t v;
            err = cbor_value_get_uint64(&map_it, &v);
            CHECK(err == CborNoError);
            out->capabilities = (uint32_t)v;
        }
        else if (strcmp(key, "sig") == 0)
        {
            size_t len = RECIPE_SIG_SIZE;
            err = cbor_value_copy_byte_string(&map_it, out->signature, &len, &map_it);
            CHECK(err == CborNoError && len == RECIPE_SIG_SIZE);
        }
        else
        {
            /* Skip unknown key */
            err = cbor_value_advance_fixed(&map_it);
            CHECK(err == CborNoError);
        }
        err = cbor_value_advance(&map_it);
    }

    err = cbor_value_leave_container(&it, &map_it);
    return err == CborNoError ? 0 : -1;
}

/*--------------------------------------------------------------------
 * Verification
 *------------------------------------------------------------------*/
int
recipe_verify(const recipe_t *r,
              int (*verify_sig)(const uint8_t *, size_t,
                                const uint8_t *, const uint8_t *))
{
    if (!r || !verify_sig) return -1;

    /* 1) Recompute manifest and compare */
    uint8_t calc_manifest[RECIPE_HASH_SIZE];
    {
        blake3_hasher h;
        blake3_hasher_init(&h);
        for (size_t i = 0; i < r->seg_count; ++i)
            blake3_hasher_update(&h, r->segments[i].hash, RECIPE_HASH_SIZE);
        blake3_hasher_finalize(&h, calc_manifest, RECIPE_HASH_SIZE);

        if (memcmp(calc_manifest, r->manifest_hash, RECIPE_HASH_SIZE) != 0)
            return -1; /* tampered */
    }

    /* 2) CBOR-encode without the signature field to build the message */
    recipe_t tmp = *r;
    memset(tmp.signature, 0, RECIPE_SIG_SIZE);

    uint8_t msg[1024]; /* Should fit typical recipe; else caller can encode separately */
    size_t  msg_len = sizeof(msg);
    CHECK(recipe_encode_cbor(&tmp, msg, &msg_len) == 0);

    /* 3) Derive pubkey from creator field (example: not in spec) */
    /* This demo expects creator to contain the hex of the Ed25519 pubkey. */
    uint8_t pubkey[32] = {0};
    size_t  pk_len = strlen(r->creator);
    CHECK(pk_len == 64); /* 32-byte hex */
    for (size_t i = 0; i < 32; ++i)
    {
        sscanf(&r->creator[i*2], "%2hhx", &pubkey[i]);
    }

    /* 4) Verify signature */
    return verify_sig(msg, msg_len, r->signature, pubkey);
}

/*--------------------------------------------------------------------
 * Misc utilities
 *------------------------------------------------------------------*/
void
recipe_print(const recipe_t *r)
{
    if (!r) return;
    printf("Recipe [%s]\n", r->artifact_id);
    printf("  Creator     : %s\n", r->creator);
    printf("  Timestamp   : %lld\n", (long long)r->timestamp);
    printf("  Segments    : %zu\n", r->seg_count);
    for (size_t i = 0; i < r->seg_count; ++i)
    {
        printf("    %02zu) type=%d size=%u hash=", i,
               r->segments[i].type, r->segments[i].size_bytes);
        for (size_t j = 0; j < 4; ++j) /* first 4 bytes for brevity */
            printf("%02x", r->segments[i].hash[j]);
        printf("…\n");
    }
}

void
recipe_wipe(recipe_t *r)
{
    if (!r) return;
    secure_memzero(r, sizeof(*r));
}

#endif /* HOLOCANVAS_RECIPE_IMPLEMENTATION */
#endif /* HOLOCANVAS_MINT_FACTORY_RECIPE_H */
```