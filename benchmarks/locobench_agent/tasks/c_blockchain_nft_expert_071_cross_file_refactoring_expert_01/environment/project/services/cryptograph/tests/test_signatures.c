/*
 * File:    test_signatures.c
 * Author:  HoloCanvas Cryptograph Service Team
 * Licence: Apache-2.0
 *
 * Unit-tests for the Cryptograph micro-service’s signature helper
 * utilities.  The tests exercise happy-path signing / verification as
 * well as a selection of negative scenarios (tampered message,
 * corrupted signature, size mismatches, …).
 *
 * The production code under test is located in
 *      services/cryptograph/include/cryptograph/signatures.h
 *      services/cryptograph/src/signatures.c
 *
 * The implementation is a thin wrapper around libsodium’s Ed25519
 * primitives, adding high-level error handling, constant-time
 * comparisons, and defensive parameter validation.  We therefore link
 * against both libsodium and CMocka when compiling this test file:
 *
 *      cc -Isrc -Iinclude -o test_signatures \
 *         services/cryptograph/tests/test_signatures.c \
 *         -lcryptograph -lsodium -lcmocka
 */

#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <stdint.h>
#include <string.h>

#include <cmocka.h>
#include <sodium.h>

#include "cryptograph/signatures.h"   /* Public API under test          */
#include "cryptograph/utils/hex.h"    /* Helper for {hex}<->{bin} utils */

/* ------------------------------------------------------------------------- */
/* Shared test fixtures                                                      */
/* ------------------------------------------------------------------------- */

/* Known-answer-test (KAT) vectors sourced from Wycheproof. */
static const char *kat_sk_hex =
        "b18e1d004ee06c69b67db8326efed497"
        "3d2f8e11fb1738d4ab146c49cbbd4600";         /* 32-byte secret key */

static const char *kat_pk_hex =
        "77f48b59caeda8f19133fbdc9c41b76e"
        "8a12219d12b42377f28b9ade28f8a463";         /* 32-byte public key */

static const char *kat_msg_hex =
        "546865206d61676963206d6f6f6e2072"
        "616273206b697373657320736d6f6f6f"
        "7468206f6620686f6d6520706c756d73";         /* “The magic moon …” */

static const char *kat_sig_hex =
        "0aab4c900501b3e24d7cdf4663326a3a"
        "87df5e4843b2cbdb67cbf6e460fec350"
        "aa5371b1508f9f4528ecea23c436d94b"
        "5e8fcd4f681e30a6ac00a9704a188a03";         /* 64-byte signature */

typedef struct
{
        uint8_t sk[CRYPTOGRAPH_SECRET_KEY_BYTES];
        uint8_t pk[CRYPTOGRAPH_PUBLIC_KEY_BYTES];
        uint8_t msg[128];
        size_t  msg_len;
        uint8_t sig[CRYPTOGRAPH_SIGNATURE_BYTES];
} fixture_t;

/* Called once for the entire test binary. */
static int
cryptograph_tests_global_setup(void **state)
{
        (void) state;

        if (sodium_init() == -1)
                return -1;

        return 0;
}

/* Per-test fixture allocation. */
static int
fixture_setup(void **state)
{
        fixture_t *fx = malloc(sizeof *fx);
        assert_non_null(fx);

        memset(fx, 0, sizeof *fx);

        /* Populate KAT vectors ------------------------------------------------*/
        assert_int_equal(sodium_hex2bin(fx->sk, sizeof fx->sk,
                                        kat_sk_hex, strlen(kat_sk_hex),
                                        NULL, NULL, NULL), 0);

        assert_int_equal(sodium_hex2bin(fx->pk, sizeof fx->pk,
                                        kat_pk_hex, strlen(kat_pk_hex),
                                        NULL, NULL, NULL), 0);

        fx->msg_len = sodium_hex2bin(fx->msg, sizeof fx->msg,
                                     kat_msg_hex, strlen(kat_msg_hex),
                                     NULL, NULL, NULL);
        assert_true(fx->msg_len > 0);

        assert_int_equal(sodium_hex2bin(fx->sig, sizeof fx->sig,
                                        kat_sig_hex, strlen(kat_sig_hex),
                                        NULL, NULL, NULL),
                         CRYPTOGRAPH_SIGNATURE_BYTES);

        /* Pass fixture to test */
        *state = fx;
        return 0;
}

/* Per-test fixture teardown. */
static int
fixture_teardown(void **state)
{
        fixture_t *fx = *state;
        sodium_memzero(fx, sizeof *fx);
        free(fx);
        return 0;
}

/* ------------------------------------------------------------------------- */
/* Positive paths                                                            */
/* ------------------------------------------------------------------------- */

/* Happy-path: generated signature verifies with matching public key. */
static void
test_sign_and_verify_success(void **state)
{
        fixture_t *fx = *state;
        uint8_t   sig[CRYPTOGRAPH_SIGNATURE_BYTES] = {0};
        size_t    sig_len = 0;

        assert_int_equal(
                hcrypt_sign_detached(sig, sizeof sig, &sig_len,
                                     fx->msg, fx->msg_len,
                                     fx->sk),
                HCRYPT_SUCCESS);

        assert_int_equal(sig_len, CRYPTOGRAPH_SIGNATURE_BYTES);

        assert_int_equal(
                hcrypt_verify_detached(sig, sig_len,
                                       fx->msg, fx->msg_len,
                                       fx->pk),
                HCRYPT_SUCCESS);
}

/* Verify the hard-coded Wycheproof KAT vector. */
static void
test_verify_known_answer(void **state)
{
        fixture_t *fx = *state;

        assert_int_equal(
                hcrypt_verify_detached(fx->sig, sizeof fx->sig,
                                       fx->msg, fx->msg_len,
                                       fx->pk),
                HCRYPT_SUCCESS);
}

/* ------------------------------------------------------------------------- */
/* Negative paths                                                            */
/* ------------------------------------------------------------------------- */

/* Failure expected when message is modified post-signing. */
static void
test_fail_on_tampered_message(void **state)
{
        fixture_t *fx = *state;
        uint8_t   sig[CRYPTOGRAPH_SIGNATURE_BYTES];
        size_t    sig_len = 0;
        uint8_t   msg_copy[128];

        memcpy(msg_copy, fx->msg, fx->msg_len);

        /* Sign original -------------------------------------------------------*/
        assert_int_equal(
                hcrypt_sign_detached(sig, sizeof sig, &sig_len,
                                     msg_copy, fx->msg_len,
                                     fx->sk),
                HCRYPT_SUCCESS);

        /* Tamper with the message */
        msg_copy[0] ^= 0x01;

        assert_int_not_equal(
                hcrypt_verify_detached(sig, sig_len,
                                       msg_copy, fx->msg_len,
                                       fx->pk),
                HCRYPT_SUCCESS);
}

/* Failure expected when the signature is corrupted. */
static void
test_fail_on_corrupted_signature(void **state)
{
        fixture_t *fx = *state;
        uint8_t   sig[CRYPTOGRAPH_SIGNATURE_BYTES];
        size_t    sig_len = 0;

        /* Valid sign ----------------------------------------------------------*/
        assert_int_equal(
                hcrypt_sign_detached(sig, sizeof sig, &sig_len,
                                     fx->msg, fx->msg_len,
                                     fx->sk),
                HCRYPT_SUCCESS);

        /* Corrupt 1 byte of signature. */
        sig[31] ^= 0x23;

        assert_int_not_equal(
                hcrypt_verify_detached(sig, sig_len,
                                       fx->msg, fx->msg_len,
                                       fx->pk),
                HCRYPT_SUCCESS);
}

/* Failure expected when the signature length is invalid. */
static void
test_fail_on_size_mismatch(void **state)
{
        fixture_t *fx = *state;
        uint8_t   sig[CRYPTOGRAPH_SIGNATURE_BYTES];
        size_t    sig_len = 0;

        /* Valid sign first ----------------------------------------------------*/
        assert_int_equal(
                hcrypt_sign_detached(sig, sizeof sig, &sig_len,
                                     fx->msg, fx->msg_len,
                                     fx->sk),
                HCRYPT_SUCCESS);

        /* Try to verify with truncated length. */
        assert_int_not_equal(
                hcrypt_verify_detached(sig, sig_len - 1,
                                       fx->msg, fx->msg_len,
                                       fx->pk),
                HCRYPT_SUCCESS);
}

/* ------------------------------------------------------------------------- */
/* Determinism / Idempotency                                                 */
/* ------------------------------------------------------------------------- */

/*
 * hcrypt_sign_detached() is specified to produce deterministic
 * Ed25519 signatures (RFC 8032, no random nonce).  Calling the
 * function twice with the same inputs MUST therefore yield identical
 * outputs.
 */
static void
test_deterministic_signing(void **state)
{
        fixture_t *fx = *state;
        uint8_t   sig1[CRYPTOGRAPH_SIGNATURE_BYTES], sig2[CRYPTOGRAPH_SIGNATURE_BYTES];
        size_t    len1 = 0, len2 = 0;

        assert_int_equal(
                hcrypt_sign_detached(sig1, sizeof sig1, &len1,
                                     fx->msg, fx->msg_len,
                                     fx->sk),
                HCRYPT_SUCCESS);

        assert_int_equal(
                hcrypt_sign_detached(sig2, sizeof sig2, &len2,
                                     fx->msg, fx->msg_len,
                                     fx->sk),
                HCRYPT_SUCCESS);

        assert_int_equal(len1, CRYPTOGRAPH_SIGNATURE_BYTES);
        assert_int_equal(len2, CRYPTOGRAPH_SIGNATURE_BYTES);
        assert_memory_equal(sig1, sig2, CRYPTOGRAPH_SIGNATURE_BYTES);
}

/* ------------------------------------------------------------------------- */
/* Main                                                                      */
/* ------------------------------------------------------------------------- */

int
main(void)
{
        const struct CMUnitTest tests[] = {
                cmocka_unit_test_setup_teardown(test_sign_and_verify_success,
                                                fixture_setup,
                                                fixture_teardown),
                cmocka_unit_test_setup_teardown(test_verify_known_answer,
                                                fixture_setup,
                                                fixture_teardown),
                cmocka_unit_test_setup_teardown(test_fail_on_tampered_message,
                                                fixture_setup,
                                                fixture_teardown),
                cmocka_unit_test_setup_teardown(test_fail_on_corrupted_signature,
                                                fixture_setup,
                                                fixture_teardown),
                cmocka_unit_test_setup_teardown(test_fail_on_size_mismatch,
                                                fixture_setup,
                                                fixture_teardown),
                cmocka_unit_test_setup_teardown(test_deterministic_signing,
                                                fixture_setup,
                                                fixture_teardown),
        };

        /* Run with global libsodium initialisation. */
        return cmocka_run_group_tests(tests,
                                      cryptograph_tests_global_setup,
                                      NULL);
}