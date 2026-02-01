/*
 * EduPay Ledger Academy - Shared Kernel
 * -------------------------------------
 * File:    src/shared_kernel/domain/transaction_id.c
 * Purpose: Domain primitive for strongly-typed Transaction Identifiers.
 *
 * Transaction IDs are implemented as ULIDs (Universally Unique
 * Lexicographically Sortable Identifiers).  ULIDs have several properties
 * beneficial to a high-throughput payment rail:
 *
 *   1. 128-bit uniqueness across distributed nodes.
 *   2. Time-ordered lexicographical sorting (first 48 bits embed timestamp).
 *   3. URL-safe Base32 string representation (26 chars).
 *
 * Although this module depends only on POSIX libc, it attempts to source
 * cryptographically-secure random bytes via getrandom(2) or /dev/urandom.
 * When neither is available, it falls back to `rand(3)` and marks the ID as
 * “best-effort” by returning TXN_ID_ERR_WEAK_RANDOM.  Callers MAY propagate
 * that warning to observability pipelines for auditability.
 *
 * Author: EduPay Engineering Team
 * SPDX-License-Identifier: MIT
 */

#include "transaction_id.h"           /* Public interface */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#if defined(__linux__)
#   include <sys/random.h>            /* getrandom(2) */
#endif

/*───────────────────────────────────────────────────────────────────────────*/
/* Internal constants                                                       */
/*───────────────────────────────────────────────────────────────────────────*/

#define ULID_TOTAL_BYTES   16          /* 128 bit (timestamp 6 + randomness 10) */
#define ULID_STR_LENGTH    26
#define CROCKFORD_ALPHABET "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

/*───────────────────────────────────────────────────────────────────────────*/
/* Utility: secure random bytes                                            */
/*───────────────────────────────────────────────────────────────────────────*/

static int
secure_random_bytes(void *buf, size_t len)
{
#if defined(__linux__)
    ssize_t r = getrandom(buf, len, GRND_NONBLOCK);
    if (r == (ssize_t)len) {
        return TXN_ID_SUCCESS;
    }
    /* fall back if interrupted or not enough entropy */
#endif

    /* Try /dev/urandom */
    int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (fd >= 0) {
        size_t read_total = 0;
        while (read_total < len) {
            ssize_t n = read(fd, (uint8_t *)buf + read_total, len - read_total);
            if (n <= 0) {
                if (errno == EINTR) continue;
                close(fd);
                break;
            }
            read_total += (size_t)n;
        }
        close(fd);
        if (read_total == len) {
            return TXN_ID_SUCCESS;
        }
    }

    /* Last-ditch (weak) fallback */
    uint8_t *dst = buf;
    for (size_t i = 0; i < len; ++i) {
        dst[i] = (uint8_t)(rand() & 0xFF);
    }
    return TXN_ID_ERR_WEAK_RANDOM;
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Internal: Crockford Base32 encoder                                       */
/*───────────────────────────────────────────────────────────────────────────*/

static void
encode_crockford_base32(const uint8_t *src, char *dst)
{
    /* Encode 128-bit ULID (16 bytes) into 26 Crockford base32 chars. */
    static const char *alphabet = CROCKFORD_ALPHABET;

    /*
     * The bit-packing layout below follows the ULID specification verbatim.
     * We pre-aggregate the full 128-bit sequence into a 5-bit window stream.
     */
    uint8_t bits[26] = {0};

    /* Convert into 5-bit groups (26 groups → 26 chars) */
    int bit_index = 0;
    for (int char_idx = 0; char_idx < ULID_STR_LENGTH; ++char_idx) {
        int byte_idx = bit_index / 8;
        int intra    = bit_index % 8;

        uint16_t chunk =
            (src[byte_idx] << 8) | (byte_idx + 1 < ULID_TOTAL_BYTES ? src[byte_idx + 1] : 0);
        chunk = (uint16_t)(chunk << intra);          /* align to MSB */

        bits[char_idx] = (uint8_t)((chunk & 0xFF00) >> 11); /* top 5 bits */

        bit_index += 5;
    }

    /* Map 5-bit groups to alphabet */
    for (int i = 0; i < ULID_STR_LENGTH; ++i) {
        dst[i] = alphabet[bits[i] & 0x1F];
    }
    dst[ULID_STR_LENGTH] = '\0';
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Generation                                                               */
/*───────────────────────────────────────────────────────────────────────────*/

int
transaction_id_generate(TransactionId *out)
{
    if (!out) return TXN_ID_ERR_NULL;

    uint8_t ulid_raw[ULID_TOTAL_BYTES] = {0};

    /* 1) Timestamp: 48 bits in milliseconds since Unix epoch. */
    struct timespec ts;
    if (clock_gettime(CLOCK_REALTIME, &ts) != 0) {
        return TXN_ID_ERR_SYS;
    }
    uint64_t ts_ms =
        (uint64_t)ts.tv_sec * 1000ULL + (uint64_t)(ts.tv_nsec / 1000000ULL);

    ulid_raw[0] = (uint8_t)(ts_ms >> 40);
    ulid_raw[1] = (uint8_t)(ts_ms >> 32);
    ulid_raw[2] = (uint8_t)(ts_ms >> 24);
    ulid_raw[3] = (uint8_t)(ts_ms >> 16);
    ulid_raw[4] = (uint8_t)(ts_ms >> 8);
    ulid_raw[5] = (uint8_t)(ts_ms);

    /* 2) Randomness: 80 bits */
    int rc = secure_random_bytes(&ulid_raw[6], 10);

    /* 3) Base32 encode */
    encode_crockford_base32(ulid_raw, out->value);

    return rc;   /* May be TXN_ID_SUCCESS or TXN_ID_ERR_WEAK_RANDOM */
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Validation                                                               */
/*───────────────────────────────────────────────────────────────────────────*/

static inline int
is_crockford_char(char c)
{
    /* Accept lower-case input as well */
    if (c >= 'a' && c <= 'z') c -= 32;

    switch (c) {
        case '0'...'9':
        case 'A':
        case 'B':
        case 'C':
        case 'D':
        case 'E':
        case 'F':
        case 'G':
        case 'H':
        case 'J':
        case 'K':
        case 'M':
        case 'N':
        case 'P':
        case 'Q':
        case 'R':
        case 'S':
        case 'T':
        case 'V':
        case 'W':
        case 'X':
        case 'Y':
        case 'Z':
            return 1;
        default:
            return 0;
    }
}

int
transaction_id_is_valid(const char *str)
{
    if (!str) return 0;
    size_t len = strlen(str);
    if (len != ULID_STR_LENGTH) return 0;

    for (size_t i = 0; i < len; ++i) {
        if (!is_crockford_char(str[i])) return 0;
    }
    return 1;
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Parsing                                                                  */
/*───────────────────────────────────────────────────────────────────────────*/

int
transaction_id_parse(TransactionId *out, const char *str)
{
    if (!out || !str) return TXN_ID_ERR_NULL;
    if (!transaction_id_is_valid(str)) return TXN_ID_ERR_INVALID;

    strncpy(out->value, str, ULID_STR_LENGTH + 1);
    out->value[ULID_STR_LENGTH] = '\0';
    return TXN_ID_SUCCESS;
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Comparison & Accessors                                                   */
/*───────────────────────────────────────────────────────────────────────────*/

const char *
transaction_id_to_string(const TransactionId *id)
{
    if (!id) return NULL;
    return id->value;
}

int
transaction_id_compare(const TransactionId *a, const TransactionId *b)
{
    if (!a || !b) return (a == b) ? 0 : (a ? 1 : -1);
    return strncmp(a->value, b->value, ULID_STR_LENGTH);
}

/*───────────────────────────────────────────────────────────────────────────*/
/* Simple self-test (may be compiled out in release builds)                 */
/*───────────────────────────────────────────────────────────────────────────*/

#ifdef EDUPAY_TXN_ID_SELFTEST

#include <assert.h>

static void
selftest(void)
{
    TransactionId id1, id2;
    int rc = transaction_id_generate(&id1);
    assert(rc == TXN_ID_SUCCESS || rc == TXN_ID_ERR_WEAK_RANDOM);
    assert(transaction_id_is_valid(id1.value));

    rc = transaction_id_parse(&id2, id1.value);
    assert(rc == TXN_ID_SUCCESS);
    assert(transaction_id_compare(&id1, &id2) == 0);

    /* Negative cases */
    assert(!transaction_id_is_valid("BAD_ID"));
    assert(transaction_id_parse(&id2, "BAD_ID") == TXN_ID_ERR_INVALID);
}

__attribute__((constructor))
static void
run_selftest(void)
{
    selftest();
}

#endif /* EDUPAY_TXN_ID_SELFTEST */
