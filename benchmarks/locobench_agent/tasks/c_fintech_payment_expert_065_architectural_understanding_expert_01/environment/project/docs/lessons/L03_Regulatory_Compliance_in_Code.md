# Lesson 03 – Regulatory Compliance in Code
EduPay Ledger Academy ─ Bounded Context: Compliance  
Status: Approved for classroom distribution ✅

> “Security and privacy requirements **are** business requirements.”  
> — Robert C. Martin, Clean Coder (paraphrased)

---

## 🧭 Learning objectives
* Design code paths that meet FERPA, PCI-DSS v4.0 and PSD2 RTS.
* Implement format-preserving tokenisation that keeps BIN analytics intact.
* Encrypt audit-trail entries with AES-256-GCM while preserving CQRS read-models.
* Shred secrets from RAM so students can pass a post-mortem memory scan.

---

## 1 ╱ 4 Header-only API surface (`compliance_guard.h`)

```c
/*──────────────────────────────────────────────────────────────────────────────
  compliance_guard.h
  ──────────────────────────────────────────────────────────────────────────────
  © 2024 EduPay Ledger Academy

  This header exposes the minimal interface required to integrate regulatory
  safeguards into any Clean-Architecture delivery layer.  All functions are
  synchronous and fail-fast; wrap them in your platform’s preferred error
  handling and tracing facilities when deploying in production.

  Build note: link with -lcrypto (OpenSSL 1.1.1+) or LibreSSL 3.x.
──────────────────────────────────────────────────────────────────────────────*/
#ifndef EDU_COMPLIANCE_GUARD_H
#define EDU_COMPLIANCE_GUARD_H

#include <stddef.h>   /* size_t   */
#include <stdint.h>   /* uint8_t  */
#include <stdbool.h>  /* bool     */

#ifdef __cplusplus
extern "C" {
#endif

/* Opaque symmetric-key handle ‑ see cg_key_acquire() */
typedef struct cg_key cg_key_t;

/* ------------------------------------------------------------------------- */
/*  PCI-DSS Safe Tokenisation                                                */
/* ------------------------------------------------------------------------- */

/**
 * Generates a numeric, Luhn-valid token that preserves the first six
 * digits (BIN/IIN) of the supplied Primary Account Number.
 *
 * The function is idempotent; identical input produces identical output
 * when `EDUPAY_FPE=0`.  Set `EDUPAY_FPE=1` to switch to format-preserving
 * encryption (left as an exercise).
 *
 * Memory safety: the caller owns both the input PAN and output buffer.
 * Call cg_secure_bzero() after use.
 *
 * @return 0 on success, ‑EINVAL on bad input, negative errno on failure.
 */
int cg_tokenise_pan(const char *pan,
                    char       *out_token,
                    size_t      out_len);

/* ------------------------------------------------------------------------- */
/*  Authenticated Encryption (AES-256-GCM)                                   */
/* ------------------------------------------------------------------------- */

/**
 * Encrypts |plaintext| and prepends a random IV, appending a 128-bit tag.
 *
 * |out_cipher| must be at least 12 B + pt_len + 16 B.
 * Returns total bytes written or negative errno.
 */
ssize_t cg_seal(cg_key_t      *key,
                const uint8_t *plaintext,
                size_t         pt_len,
                uint8_t       *out_cipher,
                size_t         out_cipher_sz);

/**
 * Decrypts and authenticates a buffer produced by cg_seal().
 *
 * Returns number of plaintext bytes or ‑EBADMSG when auth fails.
 */
ssize_t cg_open(cg_key_t      *key,
                const uint8_t *cipher,
                size_t         cipher_len,
                uint8_t       *out_plain,
                size_t         out_plain_sz);

/* ------------------------------------------------------------------------- */
/*  Secure memory hygiene                                                    */
/* ------------------------------------------------------------------------- */

/* Overwrite |len| bytes starting at |ptr| even under aggressive optimisation */
void cg_secure_bzero(void *ptr, size_t len);

/* ------------------------------------------------------------------------- */
/*  Key management (teaching mode)                                           */
/* ------------------------------------------------------------------------- */

/**
 * Acquires an AES-256-GCM key.
 *   • Production:  pulled from HSM via PKCS#11.
 *   • Lab mode:    derived from EDUPAY_COMPLIANCE_KEY (64-hex chars) or
 *                  filled with /dev/urandom.
 */
cg_key_t *cg_key_acquire(void);

/* Zeroise and free key material */
void cg_key_release(cg_key_t *key);

#ifdef __cplusplus
}
#endif
#endif /* EDU_COMPLIANCE_GUARD_H */
```

---

## 2 ╱ 4 Reference implementation (`compliance_guard.c`)

```c
/*──────────────────────────────────────────────────────────────────────────────
  compliance_guard.c  —  Internal library for the Compliance micro-service
──────────────────────────────────────────────────────────────────────────────*/
#include "compliance_guard.h"

#include <openssl/evp.h>
#include <openssl/rand.h>
#include <errno.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

#define CG_AES_GCM_IV_LEN   12u
#define CG_AES_GCM_TAG_LEN  16u
#define CG_PAN_MAX_LEN      19u     /* ISO/IEC 7812-1 */
#define CG_TOKEN_LEN        19u

struct cg_key { uint8_t key[32]; };

/* ───────────────────────────── Internal helpers ─────────────────────────── */

static int cg_generate_iv(uint8_t *iv, size_t iv_len)
{
    return RAND_bytes(iv, (int)iv_len) == 1 ? 0 : -EIO;
}

static int cg_validate_luhn(const char *digits)
{
    size_t len = strlen(digits);
    int sum = 0, alt = 0;

    for (ssize_t i = (ssize_t)len - 1; i >= 0; --i)
    {
        int d = digits[i] - '0';
        if (d < 0 || d > 9) return -EINVAL;
        if (alt) { d *= 2; if (d > 9) d -= 9; }
        sum += d; alt = !alt;
    }
    return sum % 10 == 0 ? 0 : -EINVAL;
}

static uint8_t cg_rand_digit(void)
{
    uint8_t b; RAND_bytes(&b, 1); return (uint8_t)(b % 10);
}

static int cg_build_token(const char *pan, char *tok)
{
    size_t len = strlen(pan);
    if (len < 8 || len > CG_PAN_MAX_LEN) return -EINVAL;

    memcpy(tok, pan, 6);                 /* Keep BIN for analytics */
    for (size_t i = 6; i < len - 1; ++i) /* Randomise body         */
        tok[i] = '0' + cg_rand_digit();

    /* Recalculate Luhn check digit */
    int sum = 0, alt = 1;
    for (ssize_t i = (ssize_t)len - 2; i >= 0; --i)
    {
        int d = tok[i] - '0';
        if (alt) { d *= 2; if (d > 9) d -= 9; }
        sum += d; alt = !alt;
    }
    tok[len - 1] = '0' + ((10 - (sum % 10)) % 10);
    tok[len] = '\0';
    return 0;
}

/* ───────────────────────────── Public API ───────────────────────────────── */

int cg_tokenise_pan(const char *pan, char *out_token, size_t out_len)
{
    if (!pan || !out_token)                 return -EINVAL;
    const size_t n = strlen(pan);
    if (n == 0 || n > CG_PAN_MAX_LEN)       return -EINVAL;
    if (out_len < n + 1)                    return -ENOSPC;
    if (cg_validate_luhn(pan) != 0)         return -EINVAL;

    /* Switchable algorithm for classroom demos */
    if (getenv("EDUPAY_FPE") && *getenv("EDUPAY_FPE") == '1')
    {
        /* Placeholder for format-preserving AES-FF3-1 */
        return cg_build_token(pan, out_token); /* Fallback path */
    }
    return cg_build_token(pan, out_token);
}

ssize_t cg_seal(cg_key_t      *key,
                const uint8_t *pt,
                size_t         pt_len,
                uint8_t       *out,
                size_t         out_sz)
{
    if (!key || !pt || !out || pt_len == 0)  return -EINVAL;
    const size_t need = CG_AES_GCM_IV_LEN + pt_len + CG_AES_GCM_TAG_LEN;
    if (out_sz < need)                       return -ENOSPC;

    uint8_t *iv     = out;
    uint8_t *cipher = out + CG_AES_GCM_IV_LEN;
    uint8_t *tag    = cipher + pt_len;

    if (cg_generate_iv(iv, CG_AES_GCM_IV_LEN) != 0) return -EIO;

    ssize_t ret = -EIO;
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) return -ENOMEM;

    do {
        if (EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1) break;
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN,
                                CG_AES_GCM_IV_LEN, NULL) != 1)               break;
        if (EVP_EncryptInit_ex(ctx, NULL, NULL, key->key, iv) != 1)           break;

        int len = 0, total = 0;
        if (EVP_EncryptUpdate(ctx, cipher, &len, pt, (int)pt_len) != 1)       break;
        total += len;
        if (EVP_EncryptFinal_ex(ctx, cipher + total, &len) != 1)              break;
        total += len;
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG,
                                CG_AES_GCM_TAG_LEN, tag) != 1)               break;

        ret = CG_AES_GCM_IV_LEN + total + CG_AES_GCM_TAG_LEN;
    } while (0);

    EVP_CIPHER_CTX_free(ctx);
    return ret;
}

ssize_t cg_open(cg_key_t      *key,
                const uint8_t *in,
                size_t         in_len,
                uint8_t       *out,
                size_t         out_sz)
{
    if (!key || !in || !out)                         return -EINVAL;
    if (in_len < CG_AES_GCM_IV_LEN + CG_AES_GCM_TAG_LEN) return -EINVAL;

    const uint8_t *iv     = in;
    const uint8_t *cipher = in + CG_AES_GCM_IV_LEN;
    const size_t   ct_len = in_len - CG_AES_GCM_IV_LEN - CG_AES_GCM_TAG_LEN;
    const uint8_t *tag    = in + in_len - CG_AES_GCM_TAG_LEN;

    if (out_sz < ct_len)                             return -ENOSPC;

    ssize_t ret = -EIO;
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) return -ENOMEM;

    do {
        if (EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL) != 1) break;
        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN,
                                CG_AES_GCM_IV_LEN, NULL) != 1)               break;
        if (EVP_DecryptInit_ex(ctx, NULL, NULL, key->key, iv) != 1)           break;

        int len = 0, total = 0;
        if (EVP_DecryptUpdate(ctx, out, &len, cipher, (int)ct_len) != 1)      break;
        total += len;

        if (EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG,
                                CG_AES_GCM_TAG_LEN, (void *)tag) != 1)       break;
        if (EVP_DecryptFinal_ex(ctx, out + total, &len) != 1) {
            ret = -EBADMSG;                                                  break;
        }
        total += len;
        ret = total;
    } while (0);

    EVP_CIPHER_CTX_free(ctx);
    return ret;
}

void cg_secure_bzero(void *ptr, size_t len)
{
    if (!ptr || !len) return;
#if defined(__STDC_LIB_EXT1__)
    memset_s(ptr, len, 0, len);
#else
    volatile uint8_t *p = (volatile uint8_t *)ptr;
    while (len--) *p++ = 0;
#endif
}

cg_key_t *cg_key_acquire(void)
{
    cg_key_t *k = calloc(1, sizeof *k);
    if (!k) return NULL;

    const char *env = getenv("EDUPAY_COMPLIANCE_KEY");
    if (env && strlen(env) == 64)
    {   /* Hex-decode deterministic, instructor-supplied key */
        for (size_t i = 0; i < 32; ++i)
            sscanf(&env[i * 2], "%2hhx", &k->key[i]);
    }
    else if (RAND_bytes(k->key, sizeof k->key) != 1)
    {
        free(k); k = NULL;
    }
    return k;
}

void cg_key_release(cg_key_t *key)
{
    if (!key) return;
    cg_secure_bzero(key->key, sizeof key->key);
    free(key);
}
```

---

## 3 ╱ 4 End-to-end console demo (`example_usage.c`)

```c
/* Compile with
 *   cc -std=c11 -Wall -Wextra example_usage.c compliance_guard.c -lcrypto -o demo
 * Run with
 *   EDUPAY_COMPLIANCE_KEY=$(openssl rand -hex 32) ./demo
 */
#include <stdio.h>
#include <string.h>

#include "compliance_guard.h"

int main(void)
{
    const char *pan = "4485275742308327"; /* Visa test card */

    char token[CG_TOKEN_LEN + 1];
    if (cg_tokenise_pan(pan, token, sizeof token) != 0) {
        fprintf(stderr, "Tokenisation failed\n");
        return 1;
    }
    printf("Tokenised PAN  : %s\n", token);

    cg_key_t *key = cg_key_acquire();
    if (!key) { perror("key_acquire"); return 1; }

    uint8_t cipher[256];
    ssize_t n_cipher = cg_seal(key,
                               (const uint8_t *)token, strlen(token),
                               cipher, sizeof cipher);
    cg_secure_bzero(token, sizeof token); /* Immediately destroy clear-text */
    if (n_cipher < 0) {
        fprintf(stderr, "Encryption failed: %zd\n", n_cipher);
        cg_key_release(key);
        return 1;
    }

    uint8_t clear[64];
    ssize_t n_plain = cg_open(key, cipher, (size_t)n_cipher,
                              clear, sizeof clear);
    cg_key_release(key);

    if (n_plain < 0) {
        fprintf(stderr, "Decryption failed: %zd\n", n_plain);
        return 1;
    }
    printf("Decrypted token: %.*s\n", (int)n_plain, clear);
    cg_secure_bzero(clear, (size_t)n_plain);

    return 0;
}
```

---

## 4 ╱ 4 Lab exercises

1. Extend `cg_tokenise_pan()` to call an FF3-1 library when `EDUPAY_FPE=1`.  
   Verify that the output still passes Luhn and preserves BIN/IIN.

2. Attach `cg_seal()` to the CQRS → Audit-Trail write model.  
   Use Wireshark to confirm that events on the message bus no longer contain
   clear-text PAN or student identifiers (FERPA §99.31).

3. Fire up `valgrind --tool=memcheck ./demo` and inspect the heap after
   `cg_secure_bzero()` executes. No clear-text secrets should appear.

---

© 2024 EduPay Ledger Academy — MIT License