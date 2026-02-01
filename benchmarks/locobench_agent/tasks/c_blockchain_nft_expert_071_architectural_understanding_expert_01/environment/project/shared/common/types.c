/**
 * HoloCanvas – shared/common/types.c
 *
 * Cross-service common type helpers used by all micro-services.
 *
 * This compilation unit purposefully avoids pulling in heavyweight project
 * dependencies so that it can be freely reused by bootstrap utilities and test
 * fixtures.  All routines are written to be:
 *   • Portable          – Linux / macOS / Windows
 *   • Allocation-free   – unless explicitly documented
 *   • Thread-safe       – no hidden global state
 *   • Hardened          – defensive argument checks & constant-time where needed
 *
 * NOTE: Public declarations live in “shared/common/types.h”
 */

#include "types.h"     /* Project header – expected to declare public symbols  */
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ------------------------------------------------------------------------- */
/*  Portable compile-time assertions (C11 and fallback)                      */
/* ------------------------------------------------------------------------- */
#if defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L
  #include <assert.h>
  #define STATIC_ASSERT(expr, msg) _Static_assert((expr), msg)
#else
  #define STATIC_ASSERT(expr, msg) typedef char static_assertion_##msg[(expr) ? 1 : -1]
#endif

/* ------------------------------------------------------------------------- */
/*  stricmp / strnicmp portability                                           */
/* ------------------------------------------------------------------------- */
#if defined(_WIN32)
  #define stricmp  _stricmp
  #define strnicmp _strnicmp
#else
  #include <strings.h>
  #define stricmp  strcasecmp
  #define strnicmp strncasecmp
#endif

/* ------------------------------------------------------------------------- */
/*  Secure random bytes abstraction                                          */
/* ------------------------------------------------------------------------- */
#if defined(__linux__)
  #include <sys/random.h>
#elif defined(__APPLE__)
  #include <Security/SecRandom.h>
#elif defined(_WIN32)
  #include <windows.h>
  #include <bcrypt.h>
  #pragma comment(lib, "bcrypt.lib")
#endif

static bool secure_random(void *buf, size_t len)
{
#if defined(__linux__)
    ssize_t r = 0;
    while (len > 0) {
        r = getrandom(buf, len, 0);
        if (r < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        buf  = (uint8_t *)buf + r;
        len -= (size_t)r;
    }
    return true;

#elif defined(__APPLE__)
    return (SecRandomCopyBytes(kSecRandomDefault, len, buf) == errSecSuccess);

#elif defined(_WIN32)
    return (BCryptGenRandom(NULL, buf, (ULONG)len, BCRYPT_USE_SYSTEM_PREFERRED_RNG) == 0);

#else   /* Fallback – /dev/urandom */
    FILE *f = fopen("/dev/urandom", "rb");
    if (!f) { return false; }
    size_t have = fread(buf, 1, len, f);
    fclose(f);
    return have == len;
#endif
}

/* ------------------------------------------------------------------------- */
/*  Helpers                                                                  */
/* ------------------------------------------------------------------------- */
static inline uint8_t from_hex(char c)
{
    if ('0' <= c && c <= '9') return (uint8_t)(c - '0');
    if ('a' <= c && c <= 'f') return (uint8_t)(c - 'a' + 10);
    if ('A' <= c && c <= 'F') return (uint8_t)(c - 'A' + 10);
    return 0xFF;
}

/* ------------------------------------------------------------------------- */
/*  Artifact State enum ↔ string                                             */
/* ------------------------------------------------------------------------- */

static const char *k_state_str[] = {
    [ARTIFACT_STATE_DRAFT]         = "Draft",
    [ARTIFACT_STATE_CURATED]       = "Curated",
    [ARTIFACT_STATE_AUCTION]       = "Auction",
    [ARTIFACT_STATE_FRACTIONALIZED]= "Fractionalized",
    [ARTIFACT_STATE_STAKED]        = "Staked"
};

const char *artifact_state_to_str(artifact_state_t s)
{
    if (s < 0 || s >= ARTIFACT_STATE_END) { return "Unknown"; }
    return k_state_str[s];
}

bool artifact_state_from_str(const char *str, artifact_state_t *out_state)
{
    if (!str || !out_state) { return false; }

    for (artifact_state_t i = 0; i < ARTIFACT_STATE_END; ++i) {
        if (stricmp(str, k_state_str[i]) == 0) {
            *out_state = i;
            return true;
        }
    }
    return false;
}

/* ------------------------------------------------------------------------- */
/*  hash256_t (32-byte digest)                                               */
/* ------------------------------------------------------------------------- */

STATIC_ASSERT(sizeof(hash256_t) == 32, hash256_size_mismatch);

void hash256_to_hex(const hash256_t *h, char out_hex[HASH256_HEX_BYTES])
{
    static const char *kHex = "0123456789abcdef";
    for (size_t i = 0; i < sizeof(h->bytes); ++i) {
        out_hex[i*2]     = kHex[h->bytes[i] >> 4];
        out_hex[i*2 + 1] = kHex[h->bytes[i] & 0x0F];
    }
    out_hex[64] = '\0';
}

bool hash256_from_hex(const char *hex, hash256_t *out_hash)
{
    if (!hex || !out_hash) { return false; }

    for (size_t i = 0; i < 64; i += 2) {
        uint8_t hi = from_hex(hex[i]);
        uint8_t lo = from_hex(hex[i+1]);

        if (hi == 0xFF || lo == 0xFF) { return false; }

        out_hash->bytes[i/2] = (hi << 4) | lo;
    }
    return true;
}

/* ------------------------------------------------------------------------- */
/*  UUID v4                                                                  */
/* ------------------------------------------------------------------------- */

STATIC_ASSERT(sizeof(uuid_t) == 16, uuid_size_mismatch);

bool uuid_generate_v4(uuid_t *out)
{
    if (!out) { return false; }

    if (!secure_random(out->bytes, sizeof(out->bytes))) {
        return false;
    }

    /* RFC-4122 §4.4 – Set the four most significant bits of the 7th byte to 0100b */
    out->bytes[6] = (out->bytes[6] & 0x0F) | 0x40;

    /* Set the two most significant bits of the 9th byte to 10b */
    out->bytes[8] = (out->bytes[8] & 0x3F) | 0x80;

    return true;
}

void uuid_to_str(const uuid_t *u, char out[UUID_STR_BYTES])
{
    static const char *kHex = "0123456789abcdef";
    size_t o = 0;

    for (size_t i = 0; i < 16; ++i) {
        uint8_t byte = u->bytes[i];
        out[o++] = kHex[byte >> 4];
        out[o++] = kHex[byte & 0x0F];

        if (i == 3 || i == 5 || i == 7 || i == 9) {
            out[o++] = '-';
        }
    }
    out[o] = '\0';
}

bool uuid_from_str(const char *str, uuid_t *out)
{
    if (!str || !out) { return false; }
    if (strlen(str) != 36)        { return false; }
    /* Expected pattern: 8-4-4-4-12 */
    int map[36] = {
        0,1,2,3,4,5,6,7,          /* 8  */
        -1,                       /* -  */
        8,9,10,11,                /* 4  */
        -1,
        12,13,14,15,
        -1,
        16,17,18,19,
        -1,
        20,21,22,23,24,25,26,27,28,29,30,31
    };

    for (size_t i = 0; i < 36; ++i) {
        if (map[i] == -1) {              /* Hyphen positions */
            if (str[i] != '-') return false;
            continue;
        }
        uint8_t v = from_hex(str[i]);
        if (v == 0xFF) return false;

        size_t byte_index = (size_t)map[i] / 2;
        if (map[i] % 2 == 0) {
            out->bytes[byte_index] = (v << 4);
        } else {
            out->bytes[byte_index] |= v;
        }
    }
    return true;
}

/* ------------------------------------------------------------------------- */
/*  Endian helpers                                                           */
/* ------------------------------------------------------------------------- */
uint32_t u32_from_be(const uint8_t be[4])
{
    return ((uint32_t)be[0] << 24) |
           ((uint32_t)be[1] << 16) |
           ((uint32_t)be[2] <<  8) |
            (uint32_t)be[3];
}

uint64_t u64_from_be(const uint8_t be[8])
{
    return ((uint64_t)be[0] << 56) |
           ((uint64_t)be[1] << 48) |
           ((uint64_t)be[2] << 40) |
           ((uint64_t)be[3] << 32) |
           ((uint64_t)be[4] << 24) |
           ((uint64_t)be[5] << 16) |
           ((uint64_t)be[6] <<  8) |
            (uint64_t)be[7];
}

void u32_to_be(uint32_t v, uint8_t out[4])
{
    out[0] = (uint8_t)(v >> 24);
    out[1] = (uint8_t)(v >> 16);
    out[2] = (uint8_t)(v >>  8);
    out[3] = (uint8_t)(v);
}

void u64_to_be(uint64_t v, uint8_t out[8])
{
    out[0] = (uint8_t)(v >> 56);
    out[1] = (uint8_t)(v >> 48);
    out[2] = (uint8_t)(v >> 40);
    out[3] = (uint8_t)(v >> 32);
    out[4] = (uint8_t)(v >> 24);
    out[5] = (uint8_t)(v >> 16);
    out[6] = (uint8_t)(v >>  8);
    out[7] = (uint8_t)(v);
}

/* ------------------------------------------------------------------------- */
/*  Chain Environment ↔ string                                               */
/* ------------------------------------------------------------------------- */

static const char *k_env_str[] = {
    [CHAIN_ENV_MAINNET] = "mainnet",
    [CHAIN_ENV_TESTNET] = "testnet",
    [CHAIN_ENV_DEVNET]  = "devnet",
};

const char *chain_env_to_str(chain_env_t env)
{
    if (env < 0 || env >= CHAIN_ENV_END) { return "unknown"; }
    return k_env_str[env];
}

bool chain_env_from_str(const char *str, chain_env_t *out)
{
    if (!str || !out) { return false; }

    for (chain_env_t i = 0; i < CHAIN_ENV_END; ++i) {
        if (stricmp(str, k_env_str[i]) == 0) {
            *out = i;
            return true;
        }
    }
    return false;
}

/* ------------------------------------------------------------------------- */
/*  Checksum utilities –  CRC32 (Castagnoli polynomial)                      */
/* ------------------------------------------------------------------------- */
#define CRC32C_POLY 0x1EDC6F41u

static uint32_t crc32c_table[256];
static once_flag crc32c_init_flag = ONCE_FLAG_INIT;

/* Build LUT at runtime the first time we need it */
static void crc32c_init(void)
{
    for (uint32_t i = 0; i < 256; ++i) {
        uint32_t c = i;
        for (int k = 0; k < 8; ++k)
            c = (c & 1) ? (CRC32C_POLY ^ (c >> 1)) : (c >> 1);
        crc32c_table[i] = c;
    }
}

uint32_t crc32c(const void *data, size_t len)
{
    call_once(&crc32c_init_flag, crc32c_init);

    const uint8_t *p = (const uint8_t *)data;
    uint32_t crc = ~0u;
    while (len--) {
        crc = crc32c_table[(crc ^ *p++) & 0xFFu] ^ (crc >> 8);
    }
    return ~crc;
}

/* ------------------------------------------------------------------------- */
/*  Self-test (only compiled when ENABLE_TYPES_SELFTEST is defined)          */
/* ------------------------------------------------------------------------- */

#ifdef ENABLE_TYPES_SELFTEST
#include <assert.h>

static void selftest(void)
{
    /* hash roundtrip */
    hash256_t h1 = { .bytes = {0} };
    for (int i = 0; i < 32; ++i) h1.bytes[i] = (uint8_t)i;

    char hex[HASH256_HEX_BYTES];
    hash256_to_hex(&h1, hex);

    hash256_t h2;
    assert(hash256_from_hex(hex, &h2));
    assert(memcmp(&h1, &h2, sizeof(h1)) == 0);

    /* uuid roundtrip */
    uuid_t u1;
    assert(uuid_generate_v4(&u1));

    char us[UUID_STR_BYTES];
    uuid_to_str(&u1, us);

    uuid_t u2;
    assert(uuid_from_str(us, &u2));
    assert(memcmp(&u1, &u2, sizeof(u1)) == 0);

    /* artifact state parsing */
    artifact_state_t st;
    assert(artifact_state_from_str("Fractionalized", &st));
    assert(st == ARTIFACT_STATE_FRACTIONALIZED);
    assert(strcmp(artifact_state_to_str(st), "Fractionalized") == 0);

    /* chain env parsing */
    chain_env_t env;
    assert(chain_env_from_str("mainnet", &env) && env == CHAIN_ENV_MAINNET);
    assert(strcmp(chain_env_to_str(env), "mainnet") == 0);

    /* crc32c */
    const char *hello = "hello world";
    assert(crc32c(hello, strlen(hello)) == 0xc99465aa);

    fprintf(stderr, "types.c self-test passed.\n");
}

int main(void) { selftest(); return 0; }
#endif /* ENABLE_TYPES_SELFTEST */
