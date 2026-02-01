#ifndef EDU_PAY_LEDGER_ACADEMY_SHARED_KERNEL_DOMAIN_STUDENT_ID_H
#define EDU_PAY_LEDGER_ACADEMY_SHARED_KERNEL_DOMAIN_STUDENT_ID_H
/*
 * EduPay Ledger Academy – Shared Kernel
 * -------------------------------------
 *  student_id.h
 *
 *  A cryptographically–strong, RFC-4122 version-4 UUID wrapper that functions
 *  as the system-wide StudentId value-object.  The implementation is designed
 *  for portability, deterministic behaviour, and pedagogical clarity so that
 *  professors may lift the file into coursework with minimal ceremony.
 *
 *  Usage:
 *
 *      #define EDU_PAY_LEDGER_ACADEMY_STUDENT_ID_IMPLEMENTATION
 *      #include "student_id.h"
 *
 *      int main(void)
 *      {
 *          student_id_t id;
 *          char buf[STUDENT_ID_STR_SIZE];
 *
 *          if (student_id_generate(&id) != STUDENT_ID_OK) { abort(); }
 *          student_id_to_string(&id, buf, sizeof buf);
 *          printf("New student id = %s\n", buf);
 *      }
 *
 *  Only ONE translation unit should define
 *  EDU_PAY_LEDGER_ACADEMY_STUDENT_ID_IMPLEMENTATION.
 */

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*— Compile-time constants —*/
#define STUDENT_ID_NUM_BYTES 16          /* 128-bit UUID payload           */
#define STUDENT_ID_STR_LEN   36          /* Canonical length, no NUL       */
#define STUDENT_ID_STR_SIZE  (STUDENT_ID_STR_LEN + 1)

/*— Type —*/
typedef struct student_id {
    uint8_t bytes[STUDENT_ID_NUM_BYTES];
} student_id_t;

/*— Status codes —*/
typedef enum {
    STUDENT_ID_OK               =  0,
    STUDENT_ID_INVALID_ARGUMENT = -1,
    STUDENT_ID_PARSE_ERROR      = -2,
    STUDENT_ID_BUFFER_TOO_SMALL = -3,
    STUDENT_ID_RANDOM_FAILURE   = -4
} student_id_status_t;

/*— Public API —*/
/* Generation */
student_id_status_t student_id_generate(student_id_t *out_id);

/* Serialisation ↔︎ String */
student_id_status_t student_id_to_string(const student_id_t *id,
                                         char               *buffer,
                                         size_t              buffer_size);
student_id_status_t student_id_from_string(const char      *str,
                                           student_id_t     *out);

/* Equality / Utility */
static inline bool student_id_equal(const student_id_t *lhs,
                                    const student_id_t *rhs)
{
    if (!lhs || !rhs) return false;

    uint8_t diff = 0;
    for (size_t i = 0; i < STUDENT_ID_NUM_BYTES; ++i) {
        diff |= (uint8_t)(lhs->bytes[i] ^ rhs->bytes[i]);
    }
    return diff == 0;
}

static inline bool student_id_is_nil(const student_id_t *id)
{
    if (!id) return true;
    for (size_t i = 0; i < STUDENT_ID_NUM_BYTES; ++i)
        if (id->bytes[i] != 0) return false;
    return true;
}

static inline void student_id_set_nil(student_id_t *id)
{
    if (!id) return;
    for (size_t i = 0; i < STUDENT_ID_NUM_BYTES; ++i) id->bytes[i] = 0;
}

/*───────────────────────────────────────────────────────────────────────────*/
#ifdef EDU_PAY_LEDGER_ACADEMY_STUDENT_ID_IMPLEMENTATION
/*  Implementation – include once in single TU                           */

#include <string.h>
#include <stdio.h>
#include <errno.h>

/*-- Platform-specific secure RNG ‑-*/
#if defined(_WIN32) || defined(_WIN64)
/* Windows: BCryptGenRandom (CNG) */
  #define _CRT_RAND_S
  #include <windows.h>
  #include <bcrypt.h>
  #pragma comment(lib, "bcrypt.lib")
  static int _student_id_secure_random(void *buf, size_t len)
  {
      return BCryptGenRandom(NULL, buf, (ULONG)len,
                             BCRYPT_USE_SYSTEM_PREFERRED_RNG) == 0 ? 0 : -1;
  }

#else /* POSIX-ish */

  #include <unistd.h>
  #include <fcntl.h>
  #if defined(__linux__)
    #include <sys/random.h>
  #endif

  static int _student_id_secure_random(void *buf, size_t len)
  {
  #if defined(__linux__)
      /* use getrandom when available */
      ssize_t r = getrandom(buf, len, 0);
      if (r == (ssize_t)len) return 0;
      if (r != -1 || errno != ENOSYS) return -1; /* hard failure */
      /* fallthrough to /dev/urandom */
  #endif
      int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC);
      if (fd < 0) return -1;

      size_t off = 0;
      while (off < len) {
          ssize_t rd = read(fd, (uint8_t *)buf + off, len - off);
          if (rd <= 0) { close(fd); return -1; }
          off += (size_t)rd;
      }
      close(fd);
      return 0;
  }
#endif /* platform rng */

/*-- Public API definitions ‑-*/
student_id_status_t student_id_generate(student_id_t *out_id)
{
    if (!out_id) return STUDENT_ID_INVALID_ARGUMENT;

    if (_student_id_secure_random(out_id->bytes, STUDENT_ID_NUM_BYTES) != 0)
        return STUDENT_ID_RANDOM_FAILURE;

    /* Wire RFC-4122 version (4) & variant (1) bits */
    out_id->bytes[6] = (uint8_t)((out_id->bytes[6] & 0x0F) | 0x40);
    out_id->bytes[8] = (uint8_t)((out_id->bytes[8] & 0x3F) | 0x80);
    return STUDENT_ID_OK;
}

student_id_status_t student_id_to_string(const student_id_t *id,
                                         char               *buffer,
                                         size_t              buffer_size)
{
    if (!id || !buffer)      return STUDENT_ID_INVALID_ARGUMENT;
    if (buffer_size < STUDENT_ID_STR_SIZE)
        return STUDENT_ID_BUFFER_TOO_SMALL;

    /* clang-format off */
    int n = snprintf(buffer, buffer_size,
                     "%02x%02x%02x%02x-"
                     "%02x%02x-"
                     "%02x%02x-"
                     "%02x%02x-"
                     "%02x%02x%02x%02x%02x%02x",
                     id->bytes[0],  id->bytes[1],  id->bytes[2],  id->bytes[3],
                     id->bytes[4],  id->bytes[5],
                     id->bytes[6],  id->bytes[7],
                     id->bytes[8],  id->bytes[9],
                     id->bytes[10], id->bytes[11], id->bytes[12],
                     id->bytes[13], id->bytes[14], id->bytes[15]);
    /* clang-format on */

    return (n == STUDENT_ID_STR_LEN) ? STUDENT_ID_OK
                                     : STUDENT_ID_BUFFER_TOO_SMALL;
}

static int _hexval(char c, uint8_t *out)
{
    if ('0' <= c && c <= '9') { *out = (uint8_t)(c - '0');      return 0; }
    if ('a' <= c && c <= 'f') { *out = (uint8_t)(c - 'a' + 10); return 0; }
    if ('A' <= c && c <= 'F') { *out = (uint8_t)(c - 'A' + 10); return 0; }
    return -1;
}

student_id_status_t student_id_from_string(const char *str,
                                           student_id_t *out)
{
    if (!str || !out)           return STUDENT_ID_INVALID_ARGUMENT;
    if (strlen(str) != STUDENT_ID_STR_LEN) return STUDENT_ID_PARSE_ERROR;

    size_t idx = 0, bi = 0;
    while (idx < STUDENT_ID_STR_LEN) {
        if (str[idx] == '-') { ++idx; continue; }

        uint8_t hi, lo;
        if (_hexval(str[idx++], &hi) != 0) return STUDENT_ID_PARSE_ERROR;
        if (_hexval(str[idx++], &lo) != 0) return STUDENT_ID_PARSE_ERROR;

        out->bytes[bi++] = (uint8_t)((hi << 4) | lo);
    }

    return (bi == STUDENT_ID_NUM_BYTES) ? STUDENT_ID_OK
                                        : STUDENT_ID_PARSE_ERROR;
}

#endif /* EDU_PAY_LEDGER_ACADEMY_STUDENT_ID_IMPLEMENTATION */
/*───────────────────────────────────────────────────────────────────────────*/
#ifdef __cplusplus
} /* extern "C" */
#endif
#endif /* EDU_PAY_LEDGER_ACADEMY_SHARED_KERNEL_DOMAIN_STUDENT_ID_H */
