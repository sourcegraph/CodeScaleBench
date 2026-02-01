/*
 *  HoloCanvas // shared // common // types.h
 *  -------------------------------------------------
 *  Author  : HoloCanvas Core Team
 *  License : Apache-2.0
 *
 *  Description
 *  -----------
 *  Canonical primitive types, error codes, and helper macros shared by all
 *  HoloCanvas micro-services.  This header purposefully contains only POD
 *  declarations and header-only utilities; it must remain standalone and
 *  dependency-light so that every component—from on-chain WASM contracts to
 *  off-chain gRPC gateways—can include it without linking concerns.
 */

#ifndef HOLOCANVAS_SHARED_COMMON_TYPES_H
#define HOLOCANVAS_SHARED_COMMON_TYPES_H

/* --- Standard Library ---------------------------------------------------- */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <string.h>
#include <inttypes.h>

#if defined(__cplusplus)
extern "C" {
#endif

/* --- Compiler / Platform Detection --------------------------------------- */
#if defined(_MSC_VER)
#   define HC_ALWAYS_INLINE __forceinline
#   define HC_PACKED_STRUCT(decl) __pragma(pack(push, 1)) decl __pragma(pack(pop))
#elif defined(__GNUC__) || defined(__clang__)
#   define HC_ALWAYS_INLINE __attribute__((always_inline)) inline
#   define HC_PACKED_STRUCT(decl) decl __attribute__((packed))
#else
#   define HC_ALWAYS_INLINE inline
#   define HC_PACKED_STRUCT(decl) decl
#endif

/* Portable export / import (Windows DLL vs. *nix .so) */
#if defined(_WIN32) && defined(HC_SHARED_LIB)
#   if defined(HC_BUILD_DLL)
#       define HC_API __declspec(dllexport)
#   else
#       define HC_API __declspec(dllimport)
#   endif
#else
#   define HC_API __attribute__((visibility("default")))
#endif

/* --- Fixed-Width Aliases -------------------------------------------------- */
typedef uint8_t   u8;
typedef uint16_t  u16;
typedef uint32_t  u32;
typedef uint64_t  u64;
typedef int8_t    i8;
typedef int16_t   i16;
typedef int32_t   i32;
typedef int64_t   i64;

/* --- Size / Time Units ---------------------------------------------------- */
#define HC_NANOSECONDS_PER_SEC  (1000000000ULL)
#define HC_MILLISECONDS_PER_SEC (1000ULL)

/* 128-bit and 256-bit opaque blobs for hashes, keys, & signatures.  */
HC_PACKED_STRUCT(
typedef struct hc_hash128_s {
    u8 bytes[16];
}) hc_hash128_t);

HC_PACKED_STRUCT(
typedef struct hc_hash256_s {
    u8 bytes[32];
}) hc_hash256_t);

/* 512-bit signatures (e.g., ECDSA-secp256k1 + recovery id) */
HC_PACKED_STRUCT(
typedef struct hc_sig512_s {
    u8 bytes[64];
}) hc_sig512_t);

/* Wallet / Contract address (20 bytes + optional network discriminator) */
#define HC_ADDRESS_LEN 20

HC_PACKED_STRUCT(
typedef struct hc_address_s {
    u8  network;                 /* L2 rollup id or chain id segment  */
    u8  bytes[HC_ADDRESS_LEN];   /* EVM-style 160-bit address         */
}) hc_address_t);

/* --- Compile-Time Validation --------------------------------------------- */
#define HC_STATIC_ASSERT(expr, msg) _Static_assert((expr), msg)

/* Validate fundamental assumptions once during build. */
HC_STATIC_ASSERT(sizeof(hc_hash256_t) == 32,  "Hash256 size must be 32 bytes");
HC_STATIC_ASSERT(sizeof(hc_sig512_t)  == 64,  "Sig512 size must be 64 bytes");
HC_STATIC_ASSERT(sizeof(hc_address_t) == 1 + HC_ADDRESS_LEN,
                 "Address size mismatch");

/* --- Error Codes ---------------------------------------------------------- */
typedef enum hc_err_e {
    HC_ERR_OK            =  0,  /* Success, no error                  */
    HC_ERR_UNKNOWN       = -1,  /* Unclassified error                 */
    HC_ERR_OOM           = -2,  /* Out of memory                      */
    HC_ERR_TIMEOUT       = -3,  /* Timeout / deadline exceeded        */
    HC_ERR_NETWORK       = -4,  /* Network I/O error                  */
    HC_ERR_CRYPTO        = -5,  /* Cryptographic failure              */
    HC_ERR_INVALID_ARG   = -6,  /* Invalid argument / bad API usage   */
    HC_ERR_STATE         = -7,  /* Invalid state for operation        */
    HC_ERR_PERMISSION    = -8,  /* Permission / role denied           */
    HC_ERR_NOT_FOUND     = -9,  /* Entity not found                   */
    HC_ERR_EXISTS        = -10  /* Already exists / uniqueness clash  */
} hc_err_t;

/* Convert error code to string (header-only). */
static HC_ALWAYS_INLINE const char *
hc_err_str(hc_err_t err)
{
    switch (err) {
        case HC_ERR_OK:          return "OK";
        case HC_ERR_UNKNOWN:     return "Unknown Error";
        case HC_ERR_OOM:         return "Out of Memory";
        case HC_ERR_TIMEOUT:     return "Timeout";
        case HC_ERR_NETWORK:     return "Network Error";
        case HC_ERR_CRYPTO:      return "Cryptography Error";
        case HC_ERR_INVALID_ARG: return "Invalid Argument";
        case HC_ERR_STATE:       return "Invalid State";
        case HC_ERR_PERMISSION:  return "Permission Denied";
        case HC_ERR_NOT_FOUND:   return "Not Found";
        case HC_ERR_EXISTS:      return "Already Exists";
        default:                 return "Unrecognized Error";
    }
}

/* --- Artifact Lifecycle --------------------------------------------------- */
typedef enum hc_artifact_state_e {
    HC_ARTIFACT_DRAFT          = 0,
    HC_ARTIFACT_CURATED        = 1,
    HC_ARTIFACT_AUCTION        = 2,
    HC_ARTIFACT_FRACTIONALIZED = 3,
    HC_ARTIFACT_STAKED         = 4,
    HC_ARTIFACT_ARCHIVED       = 5
} hc_artifact_state_t;

/* --- Service Identifiers -------------------------------------------------- */
typedef enum hc_service_id_e {
    HC_SVC_LEDGER_CORE    = 0x01,
    HC_SVC_MINT_FACTORY   = 0x02,
    HC_SVC_GALLERY_GATE   = 0x03,
    HC_SVC_DEFI_GARDEN    = 0x04,
    HC_SVC_ORACLE_BRIDGE  = 0x05,
    HC_SVC_WALLET_PROXY   = 0x06,
    HC_SVC_GOVERNANCE_HALL= 0x07,
    HC_SVC_MUSE_OBSERVER  = 0x08
} hc_service_id_t;

/* --- Transaction / Event Identifiers ------------------------------------- */
typedef struct hc_tx_id_s {
    hc_hash256_t hash;          /* Keccak-256 of the RLP-encoded tx   */
} hc_tx_id_t;

typedef struct hc_evt_id_s {
    hc_hash256_t hash;          /* Topic hash of event                */
    u64          index;         /* Log index within block             */
} hc_evt_id_t;

/* --- JSON / CBOR Token Types (for streaming parsers) ---------------------- */
typedef enum hc_token_type_e {
    HC_TOK_NONE,
    HC_TOK_BEGIN_OBJ,
    HC_TOK_END_OBJ,
    HC_TOK_BEGIN_ARR,
    HC_TOK_END_ARR,
    HC_TOK_KEY,
    HC_TOK_STRING,
    HC_TOK_NUMBER,
    HC_TOK_TRUE,
    HC_TOK_FALSE,
    HC_TOK_NULL
} hc_token_type_t;

/* --- Macro Helpers -------------------------------------------------------- */
#define HC_UNUSED(x) (void)(x)

#define HC_MIN(a, b) ({          \
    typeof(a) _a = (a);          \
    typeof(b) _b = (b);          \
    _a < _b ? _a : _b;           \
})

#define HC_MAX(a, b) ({          \
    typeof(a) _a = (a);          \
    typeof(b) _b = (b);          \
    _a > _b ? _a : _b;           \
})

/* --- End of File ---------------------------------------------------------- */
#if defined(__cplusplus)
} /* extern "C" */
#endif

#endif /* HOLOCANVAS_SHARED_COMMON_TYPES_H */
