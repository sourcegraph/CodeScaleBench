/*
 * EduPay Ledger Academy
 * Shared Kernel / Domain
 *
 * student_id.c
 *
 * A Student ID is a value-object that uniquely identifies a learner in a
 * multi-tenant, multi-currency payment context.  It wraps a RFC-4122 UUIDv4
 * (16-octet / 128-bit) with domain-specific validation and utility helpers.
 *
 * This file purposefully contains no dependencies on storage engines,
 * message-brokers, or web frameworks—ensuring the domain model remains
 * isolated and unit-testable per Clean Architecture principles.
 */

#include <stdio.h>      /* snprintf                     */
#include <stdlib.h>     /* size_t, abort                */
#include <stdint.h>     /* uint8_t, uint32_t            */
#include <stdbool.h>    /* bool                         */
#include <string.h>     /* memset, memcmp               */
#include <errno.h>      /* errno                        */
#include <ctype.h>      /* isxdigit, tolower            */

#if defined(__linux__) || defined(__APPLE__) || defined(__FreeBSD__)
    #define EDU_HAS_POSIX_RANDOM   1
#else
    #define EDU_HAS_POSIX_RANDOM   0
#endif

#if defined(_WIN32) || defined(_WIN64)
    #define EDU_HAS_WINCRYPT       1
    #include <windows.h>
    #include <bcrypt.h>
    #pragma comment(lib, "bcrypt.lib")
#else
    #define EDU_HAS_WINCRYPT       0
#endif

#if EDU_HAS_POSIX_RANDOM
    #include <fcntl.h>
    #include <unistd.h>
    #if defined(__linux__)
        #include <sys/random.h>
    #endif
#endif

/* ────────────────────────────────────────────────────────────────────────── */
/*  Public API                                                              */
/* ────────────────────────────────────────────────────────────────────────── */

#define STUDENT_ID_OCTETS                16U
#define STUDENT_ID_STRING_LENGTH         36U  /* Excluding NUL terminator    */
#define STUDENT_ID_STRING_BUFFER_SIZE    (STUDENT_ID_STRING_LENGTH + 1U)

typedef struct StudentId {
    uint8_t bytes[STUDENT_ID_OCTETS];
} student_id_t;

/* Status codes returned by operations */
typedef enum StudentIdStatus {
    STUDENT_ID_OK                = 0,
    STUDENT_ID_ERR_INVALID_ARG   = 1,
    STUDENT_ID_ERR_PARSE         = 2,
    STUDENT_ID_ERR_RANDOM        = 3,
} student_id_status_t;

/*
 * Generates a new random (UUIDv4) StudentId.
 */
student_id_status_t student_id_generate(student_id_t *out);

/*
 * Parses a textual StudentId in 8-4-4-4-12 canonical form.
 */
student_id_status_t student_id_from_string(const char *ascii,
                                           student_id_t    *out);

/*
 * Serialises a StudentId to canonical form.
 * Caller MUST supply a char[STUDENT_ID_STRING_BUFFER_SIZE] buffer.
 */
void student_id_to_string(const student_id_t *id, char *ascii_out);

/* Equality helpers */
static inline bool
student_id_equal(const student_id_t *a, const student_id_t *b)
{
    return memcmp(a->bytes, b->bytes, STUDENT_ID_OCTETS) == 0;
}

static inline bool
student_id_is_nil(const student_id_t *id)
{
    /* All-zero UUID (“nil”) */
    for (size_t i = 0; i < STUDENT_ID_OCTETS; ++i)
        if (id->bytes[i] != 0) return false;
    return true;
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Implementation                                                          */
/* ────────────────────────────────────────────────────────────────────────── */

/* Forward declaration */
static student_id_status_t
fill_secure_random(void *dst, size_t len);

/*  Converts two hexadecimal characters to a byte.
 *  Returns STUDENT_ID_ERR_PARSE on invalid input.
 */
static student_id_status_t
hexpair_to_byte(char high, char low, uint8_t *out_byte)
{
    if (!isxdigit((unsigned char)high) ||
        !isxdigit((unsigned char)low))
        return STUDENT_ID_ERR_PARSE;

    auto hexval = [](char c) -> uint8_t {
        c = (char)tolower((unsigned char)c);
        return (uint8_t)((c >= '0' && c <= '9') ? (c - '0')
                                                : (c - 'a' + 10));
    };

    *out_byte = (uint8_t)((hexval(high) << 4) | hexval(low));
    return STUDENT_ID_OK;
}

/*  Converts a single byte to two hex chars (lower-case). */
static void
byte_to_hexpair(uint8_t byte, char *out_high, char *out_low)
{
    static const char HEX[] = "0123456789abcdef";
    *out_high = HEX[(byte >> 4) & 0xF];
    *out_low  = HEX[ byte       & 0xF];
}

/* ------------------------------------------------------------------ */
/*  Generation (UUIDv4 compliant)                                     */
/* ------------------------------------------------------------------ */
student_id_status_t
student_id_generate(student_id_t *out)
{
    if (out == NULL) return STUDENT_ID_ERR_INVALID_ARG;

    student_id_status_t st = fill_secure_random(out->bytes,
                                                STUDENT_ID_OCTETS);
    if (st != STUDENT_ID_OK) return st;

    /* Conform to RFC-4122 variant & version fields. */
    out->bytes[6] = (uint8_t)((out->bytes[6] & 0x0F) | 0x40); /* Version 4 */
    out->bytes[8] = (uint8_t)((out->bytes[8] & 0x3F) | 0x80); /* Variant 1 */

    return STUDENT_ID_OK;
}

/* ------------------------------------------------------------------ */
/*  Parsing from ASCII                                                */
/* ------------------------------------------------------------------ */
student_id_status_t
student_id_from_string(const char *ascii, student_id_t *out)
{
    if (ascii == NULL || out == NULL)
        return STUDENT_ID_ERR_INVALID_ARG;

    if (strlen(ascii) != STUDENT_ID_STRING_LENGTH)
        return STUDENT_ID_ERR_PARSE;

    /* Expected positions of dashes */
    const int DASH_IDX[] = {8, 13, 18, 23};

    size_t src = 0;      /* index in ascii        */
    size_t dst = 0;      /* index in out->bytes   */

    for (size_t i = 0; i < STUDENT_ID_STRING_LENGTH; ) {

        /* Handle dash positions */
        bool is_dash_position = false;
        for (size_t d = 0; d < sizeof(DASH_IDX)/sizeof(DASH_IDX[0]); ++d)
            if (i == (size_t)DASH_IDX[d]) { is_dash_position = true; break; }

        if (is_dash_position) {
            if (ascii[i] != '-') return STUDENT_ID_ERR_PARSE;
            ++i;
            continue;
        }

        /* Need two hex chars */
        char h = ascii[i++];
        char l = ascii[i++];

        uint8_t byte;
        student_id_status_t st = hexpair_to_byte(h, l, &byte);
        if (st != STUDENT_ID_OK) return st;

        out->bytes[dst++] = byte;
    }

    return STUDENT_ID_OK;
}

/* ------------------------------------------------------------------ */
/*  Serialisation to ASCII                                            */
/* ------------------------------------------------------------------ */
void
student_id_to_string(const student_id_t *id, char *ascii_out)
{
    static const int DASH_IDX[] = {8, 13, 18, 23};

    size_t src = 0;
    size_t dst = 0;

    for (size_t i = 0; i < STUDENT_ID_STRING_LENGTH; ++i) {

        bool is_dash_position = false;
        for (size_t d = 0; d < sizeof(DASH_IDX)/sizeof(DASH_IDX[0]); ++d)
            if (i == (size_t)DASH_IDX[d]) { is_dash_position = true; break; }

        if (is_dash_position) {
            ascii_out[dst++] = '-';
            continue;
        }

        char hi, lo;
        byte_to_hexpair(id->bytes[src++], &hi, &lo);
        ascii_out[dst++] = hi;
        ascii_out[dst++] = lo;
        ++i; /* consumed an extra char */
    }

    ascii_out[dst] = '\0';
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Secure Random Source                                                    */
/* ────────────────────────────────────────────────────────────────────────── */
static student_id_status_t
fill_secure_random(void *dst, size_t len)
{
#if EDU_HAS_POSIX_RANDOM
    /* ------------------------------------------------------------------
     * Attempt getrandom(2) — Linux 3.17+.  This avoids /dev/urandom FDs.
     * ------------------------------------------------------------------ */
    #if defined(__linux__)
        ssize_t n = getrandom(dst, len, 0);
        if (n == (ssize_t)len) return STUDENT_ID_OK;
        /* Fallthrough if not supported or partial read */
    #endif

    /* ------------------------------------------------------------------
     * Fallback to arc4random_buf — BSDs, macOS
     * ------------------------------------------------------------------ */
    #if defined(__APPLE__) || defined(__FreeBSD__)
        arc4random_buf(dst, len);
        return STUDENT_ID_OK;
    #endif

    /* ------------------------------------------------------------------
     * Fallback to /dev/urandom
     * ------------------------------------------------------------------ */
    int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
    if (fd < 0) return STUDENT_ID_ERR_RANDOM;

    uint8_t *buf = (uint8_t *)dst;
    size_t remaining = len;
    while (remaining) {
        ssize_t rd = read(fd, buf, remaining);
        if (rd <= 0) { close(fd); return STUDENT_ID_ERR_RANDOM; }
        buf       += rd;
        remaining -= rd;
    }

    close(fd);
    return STUDENT_ID_OK;

#elif EDU_HAS_WINCRYPT
    /* ------------------------------------------------------------------
     * Windows CNG (BCrypt) API
     * ------------------------------------------------------------------ */
    if (BCryptGenRandom(NULL,
                        (PUCHAR)dst,
                        (ULONG)len,
                        BCRYPT_USE_SYSTEM_PREFERRED_RNG) == 0)
        return STUDENT_ID_OK;
    return STUDENT_ID_ERR_RANDOM;
#else
    /* No secure random source available */
    (void)dst; (void)len;
    return STUDENT_ID_ERR_RANDOM;
#endif
}

/* ────────────────────────────────────────────────────────────────────────── */
/*  Self-diagnostic main (only compiled with UNIT_TEST macro)               */
/* ────────────────────────────────────────────────────────────────────────── */
#ifdef STUDENT_ID_UNIT_TEST
int main(void)
{
    student_id_t id;
    if (student_id_generate(&id) != STUDENT_ID_OK)
        abort();

    char buf[STUDENT_ID_STRING_BUFFER_SIZE];
    student_id_to_string(&id, buf);
    printf("Generated ID: %s\n", buf);

    student_id_t parsed;
    if (student_id_from_string(buf, &parsed) != STUDENT_ID_OK)
        abort();

    if (!student_id_equal(&id, &parsed) || student_id_is_nil(&id))
        abort();

    puts("StudentId: self-test OK");
    return 0;
}
#endif
