/*
 * EduPay Ledger Academy — Shared Kernel
 * -------------------------------------
 *
 * transaction_id.h
 *
 * Domain-level unique identifier for monetary transactions processed by the
 * EduPay Ledger Academy payment rail.  A TransactionID is intentionally kept
 * free of storage/UI concerns so that it can travel safely across bounded
 * contexts (Admissions, Bursar, Financial-Aid, etc.) without leaking any
 * framework-specific details.
 *
 *  • Backed by a RFC-4122 UUID v4 (128-bit random value)
 *  • Header-only and freestanding; no external dependencies beyond libc
 *  • Cross-platform secure-random generation (WinCrypt or /dev/urandom)
 *  • Serialization helpers for audit-log hashing, event-sourcing, & saga-keys
 *
 * Usage Example:
 *
 *      transaction_id_t id;
 *      if (!transaction_id_generate(&id)) {
 *          // Handle entropy failure (e.g., abort payment pipeline)
 *      }
 *
 *      char buf[TRANSACTION_ID_STRING_SIZE];
 *      transaction_id_to_string(&id, buf, sizeof(buf));
 *      printf("New Txn Id: %s\n", buf);
 *
 *  © 2024 EduPay Ledger Academy — MIT License
 */

#ifndef EDU_PAY_LEDGER_ACADEMY_SHARED_KERNEL_DOMAIN_TRANSACTION_ID_H_
#define EDU_PAY_LEDGER_ACADEMY_SHARED_KERNEL_DOMAIN_TRANSACTION_ID_H_

/* ────────────────────────────────────────────────────────────────────────── */
/*  Standard Library                                                         */
/* ────────────────────────────────────────────────────────────────────────── */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/*
 * Some libc implementations (e.g., uClibc) omit inttypes.h by default; we
 * include it defensively so that PRIu64 et al. are always available.
 */
#include <inttypes.h>

/* ────────────────────────────────────────────────────────────────────────── */
/*  Constants & Types                                                        */
/* ────────────────────────────────────────────────────────────────────────── */

#define TRANSACTION_ID_NUM_BYTES   (16u)          /* 128-bit UUID            */
#define TRANSACTION_ID_STRING_SIZE (37u)          /* 36 chars + null         */

/*
 * Domain-level TransactionID.
 * NOTE: Treat as an opaque value; direct access is permitted for
 *       serialization but never for semantic logic.
 */
typedef struct {
    uint8_t bytes[TRANSACTION_ID_NUM_BYTES];
} transaction_id_t;

/* ────────────────────────────────────────────────────────────────────────── */
/*  Platform Abstraction for Secure Random                                   */
/* ────────────────────────────────────────────────────────────────────────── */

static bool
transaction_id__get_secure_bytes(void *buf, size_t len)
{
#if defined(_WIN32) || defined(_WIN64)
    /* Windows CryptGenRandom API */
    #define WIN32_LEAN_AND_MEAN
    #include <windows.h>
    #include <wincrypt.h>

    HCRYPTPROV hProv = 0;
    bool ok = false;

    if (CryptAcquireContext(&hProv, NULL, NULL, PROV_RSA_FULL,
                            CRYPT_VERIFYCONTEXT | CRYPT_SILENT)) {
        ok = CryptGenRandom(hProv, (DWORD)len, (BYTE *)buf) == TRUE;
        CryptReleaseContext(hProv, 0);
    }
    return ok;
#else
    /* POSIX: read from /dev/urandom */
    #include <unistd.h>
    #include <fcntl.h>

    int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        return false;
    }

    size_t read_total = 0;
    while (read_total < len) {
        ssize_t n = read(fd, (uint8_t *)buf + read_total, len - read_total);
        if (n <= 0) {
            close(fd);
            return false;  /* Interrupted or I/O error */
        }
        read_total += (size_t)n;
    }

    close(fd);
    return true;
#endif
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Internal Helpers                                                         */
/* ────────────────────────────────────────────────────────────────────────── */

/* Convert a single hex character to its nibble value (0-15); returns -1 on err */
static int
transaction_id__hex_char_to_nibble(char c)
{
    if (c >= '0' && c <= '9')   return c - '0';
    if (c >= 'a' && c <= 'f')   return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')   return c - 'A' + 10;
    return -1;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Public Interface                                                         */
/* ────────────────────────────────────────────────────────────────────────── */

/*
 * transaction_id_generate
 * -----------------------
 * Populates `out` with a freshly generated UUIDv4.  Returns `true` if and
 * only if cryptographically secure randomness is available.
 */
static inline bool
transaction_id_generate(transaction_id_t *out)
{
    if (!out) {
        return false;
    }

    if (!transaction_id__get_secure_bytes(out->bytes, TRANSACTION_ID_NUM_BYTES)) {
        return false;
    }

    /* Conform to RFC-4122 variant & version fields */
    out->bytes[6] = (uint8_t)((out->bytes[6] & 0x0F) | 0x40); /* Version 4 */
    out->bytes[8] = (uint8_t)((out->bytes[8] & 0x3F) | 0x80); /* Variant    */

    return true;
}

/*
 * transaction_id_is_nil
 * ---------------------
 * Checks whether all 16 bytes are zero — useful for guard clauses or
 * detecting uninitialized IDs.
 */
static inline bool
transaction_id_is_nil(const transaction_id_t *id)
{
    if (!id) {
        return true;
    }

    for (size_t i = 0; i < TRANSACTION_ID_NUM_BYTES; ++i) {
        if (id->bytes[i] != 0u) {
            return false;
        }
    }
    return true;
}

/*
 * transaction_id_equals
 * ---------------------
 * Constant-time equality comparison to avoid timing side-channel leaks during
 * fraud-detection heuristics or compliance audits.
 */
static inline bool
transaction_id_equals(const transaction_id_t *lhs, const transaction_id_t *rhs)
{
    if (!lhs || !rhs) {
        return false;
    }

    uint8_t diff = 0u;
    for (size_t i = 0; i < TRANSACTION_ID_NUM_BYTES; ++i) {
        diff |= (uint8_t)(lhs->bytes[i] ^ rhs->bytes[i]);
    }
    return diff == 0u;
}

/*
 * transaction_id_to_string
 * ------------------------
 * Converts a TransactionID to its canonical textual representation
 * (36 hexadecimal characters plus four hyphens).
 *
 *      01234567-89ab-cdef-0123-456789abcdef\0
 *
 * `buf`  must be at least TRANSACTION_ID_STRING_SIZE bytes long.
 * Returns false if `buf` is too small.
 */
static inline bool
transaction_id_to_string(const transaction_id_t *id, char *buf, size_t buf_len)
{
    if (!id || !buf || buf_len < TRANSACTION_ID_STRING_SIZE) {
        return false;
    }

    /* clang-format off */
    static const int indices[36] = {
        0,1,2,3, 4,5,6,7, -1,
        8,9, -2,
        10,11, -3,
        12,13, -4,
        14,15
    };
    /* clang-format on */

    size_t b = 0; /* byte index in id->bytes */
    size_t p = 0; /* position in string */

    /* Manual loop avoids sprintf overhead and enforces constant format */
    for (int i = 0; i < 36; ++i) {
        /* Hyphen insertion at standard UUID positions */
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            buf[p++] = '-';
            continue;
        }

        uint8_t val = i & 1 ? (id->bytes[b++] & 0x0F)
                            : (id->bytes[b] >> 4);
        buf[p++] = (char)(val < 10 ? '0' + val : 'a' + (val - 10));
    }
    buf[p] = '\0';
    return true;
}

/*
 * transaction_id_parse
 * --------------------
 * Inverse of `to_string`.  Accepts several relaxed formats:
 *      • Canonical RFC format:  123e4567-e89b-12d3-a456-426614174000
 *      • Without dashes:       123e4567e89b12d3a456426614174000
 *
 * Returns true on success; false if the input is malformed.
 */
static inline bool
transaction_id_parse(const char *str, transaction_id_t *out)
{
    if (!str || !out) {
        return false;
    }

    size_t len = strlen(str);
    if (len != 36 && len != 32) {
        return false;
    }

    size_t str_i = 0;
    size_t byte_i = 0;

    while (byte_i < TRANSACTION_ID_NUM_BYTES && str[str_i] != '\0') {
        /* Skip dash characters */
        if (str[str_i] == '-') {
            ++str_i;
            continue;
        }

        int hi = transaction_id__hex_char_to_nibble(str[str_i++]);
        int lo = transaction_id__hex_char_to_nibble(str[str_i++]);
        if (hi < 0 || lo < 0) {
            return false;
        }
        out->bytes[byte_i++] = (uint8_t)((hi << 4) | lo);
    }

    return byte_i == TRANSACTION_ID_NUM_BYTES;
}

#endif /* EDU_PAY_LEDGER_ACADEMY_SHARED_KERNEL_DOMAIN_TRANSACTION_ID_H_ */
