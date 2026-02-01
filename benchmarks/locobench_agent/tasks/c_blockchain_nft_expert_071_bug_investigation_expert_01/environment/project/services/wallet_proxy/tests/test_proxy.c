/*
 * HoloCanvas – Wallet-Proxy Unit-Tests
 * File: HoloCanvas/services/wallet_proxy/tests/test_proxy.c
 *
 * These tests exercise the public surface of the Wallet-Proxy
 * micro-service.  All upstream dependencies (RPC layer, crypto
 * primitives, configuration loader, etc.) are link-time wrapped with
 * cmocka test doubles so that the unit under test can be evaluated in
 * strict isolation.
 *
 * Build:
 *   gcc -I../../../include -I/usr/include -Wall -Wextra -pedantic \
 *       test_proxy.c -lcmocka -o test_proxy
 *
 * Run:
 *   ./test_proxy
 */

#include <stdarg.h>
#include <stddef.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <cmocka.h>

/* ------------------------------------------------------------------------- *
 * SUT Header
 * ------------------------------------------------------------------------- */
#include "wallet_proxy.h" /* <project>/include/wallet_proxy.h */

/*
 *  If the real header is not present (e.g., the test is built in
 *  isolation), provide a minimal stub so that this file remains
 *  self-contained.  These stubs will be ignored when the genuine header
 *  is available.
 */
#ifndef HOLOCANVAS_WALLET_PROXY_H
#define HOLOCANVAS_WALLET_PROXY_H

typedef struct {
    char *endpoint;
    char *api_key;
} wp_config_t;

typedef struct wallet_proxy wallet_proxy_t;

int  wp_init(const wp_config_t *cfg, wallet_proxy_t **proxy_out);
int  wp_send_transaction(wallet_proxy_t *proxy,
                         const char    *from,
                         const char    *to,
                         uint64_t       amount,
                         char         **tx_hash_out);
int  wp_sign_message(wallet_proxy_t *proxy,
                     const uint8_t  *msg,
                     size_t          msg_len,
                     uint8_t       **sig_out,
                     size_t         *sig_len);
void wp_free(wallet_proxy_t *proxy);

/* Fail-fast reference implementations (never called thanks to mocks). */
int  wp_init(const wp_config_t *cfg, wallet_proxy_t **proxy_out)
{ (void)cfg; (void)proxy_out; return -1; }
int  wp_send_transaction(wallet_proxy_t *proxy, const char *from,
                         const char *to, uint64_t amount, char **tx_hash_out)
{ (void)proxy; (void)from; (void)to; (void)amount; (void)tx_hash_out; return -1; }
int  wp_sign_message(wallet_proxy_t *proxy, const uint8_t *msg,
                     size_t msg_len, uint8_t **sig_out, size_t *sig_len)
{ (void)proxy; (void)msg; (void)msg_len; (void)sig_out; (void)sig_len; return -1; }
void wp_free(wallet_proxy_t *proxy) { (void)proxy; }

#endif /* HOLOCANVAS_WALLET_PROXY_H */

/* ------------------------------------------------------------------------- *
 * Upstream Dependency – RPC Client (Function We Intend To Mock)
 * ------------------------------------------------------------------------- */
int rpc_client_send(const char *endpoint,
                    const char *payload,
                    char      **response_out);

/*
 *  Link-time wrapper:  our implementation will replace the production
 *  symbol when the test is linked with ‑Wl,--wrap=rpc_client_send.
 *  However, relying on ‑wrap is compiler-specific.  We therefore
 *  compile the same name directly and ensure it is visible to the
 *  linker before the real object files, which achieves the same result
 *  in a portable way.
 */
int rpc_client_send(const char *endpoint,
                    const char *payload,
                    char      **response_out)
{
    check_expected_ptr(endpoint);
    check_expected_ptr(payload);

    /* Drive the behaviour via cmocka's will_return() facility. */
    int retval = mock_type(int);
    if (retval == 0) {
        const char *mock_json = mock_ptr_type(const char *);
        *response_out = strdup(mock_json);
    }
    return retval;
}

/* ------------------------------------------------------------------------- *
 * Upstream Dependency – Cryptographic Signer (Mock)
 * ------------------------------------------------------------------------- */
int crypto_sign(const uint8_t *priv_key,
                size_t         key_len,
                const uint8_t *msg,
                size_t         msg_len,
                uint8_t       *sig_out,
                size_t        *sig_len);

int crypto_sign(const uint8_t *priv_key,
                size_t         key_len,
                const uint8_t *msg,
                size_t         msg_len,
                uint8_t       *sig_out,
                size_t        *sig_len)
{
    check_expected_ptr(priv_key);
    check_expected_ptr(msg);
    assert_true(key_len > 0);
    assert_true(msg_len > 0);

    int retval = mock_type(int);
    if (retval == 0) {
        const uint8_t *mock_sig = mock_ptr_type(const uint8_t *);
        size_t         mock_len = mock_type(size_t);
        memcpy(sig_out, mock_sig, mock_len);
        *sig_len = mock_len;
    }
    return retval;
}

/* ------------------------------------------------------------------------- *
 * Test Suite Helpers
 * ------------------------------------------------------------------------- */

/* Generate a deterministic dummy signature for repeatability. */
static const uint8_t *dummy_signature(size_t *len_out)
{
    static const uint8_t sig_bytes[64] = {
        0xde, 0xad, 0xbe, 0xef, 0xca, 0xfe, 0xba, 0xbe,
        0x12, 0x34, 0x56, 0x78, 0x9a, 0xbc, 0xde, 0xf0,
        0x10, 0x32, 0x54, 0x76, 0x98, 0xba, 0xdc, 0xfe,
        0xff, 0xee, 0xdd, 0xcc, 0xbb, 0xaa, 0x99, 0x88,
        0x77, 0x66, 0x55, 0x44, 0x33, 0x22, 0x11, 0x00,
        0xba, 0xad, 0xf0, 0x0d, 0xbe, 0xad, 0x0b, 0xad,
        0xfa, 0xce, 0xb0, 0x0c, 0x12, 0x21, 0x34, 0x43,
        0x56, 0x65, 0x78, 0x87, 0x9a, 0xa9, 0xbc, 0xcb
    };
    if (len_out) *len_out = sizeof(sig_bytes);
    return sig_bytes;
}

/* ------------------------------------------------------------------------- *
 * Individual Unit-Tests
 * ------------------------------------------------------------------------- */

/* 1. Happy-path initialisation */
static void test_wp_init_success(void **state)
{
    (void)state;

    /* Prepare config */
    wp_config_t cfg = {
        .endpoint = "https://testnet.holocanvas.org",
        .api_key  = "unit-test-key"
    };

    /* Expect that wp_init will perform an RPC health-check under the hood. */
    expect_string(rpc_client_send, endpoint, cfg.endpoint);
    expect_any(rpc_client_send, payload);
    will_return(rpc_client_send, 0); /* success */
    will_return(rpc_client_send, "{\"status\":\"ok\"}");

    wallet_proxy_t *proxy = NULL;
    assert_int_equal(wp_init(&cfg, &proxy), 0);
    assert_non_null(proxy);

    wp_free(proxy);
}

/* 2. Failed initialisation due to missing endpoint */
static void test_wp_init_missing_config(void **state)
{
    (void)state;

    wp_config_t cfg = {
        .endpoint = NULL,
        .api_key  = "no-endpoint"
    };

    wallet_proxy_t *proxy = (wallet_proxy_t *)0xdeadbeef;
    assert_int_not_equal(wp_init(&cfg, &proxy), 0);
    assert_null(proxy);
}

/* 3. Transaction submission – success path */
static void test_wp_send_transaction_success(void **state)
{
    (void)state;

    const char *endpoint  = "https://testnet.holocanvas.org";
    const char *from_addr = "0xFaa11cafe...";
    const char *to_addr   = "0xBead5babe...";
    const char *mock_tx_hash_json = "{\"tx_hash\":\"0xdeadbeefcafebabe\"}";

    /* Initialise proxy (mocked). */
    expect_string(rpc_client_send, endpoint, endpoint);
    expect_any(rpc_client_send, payload);
    will_return(rpc_client_send, 0);
    will_return(rpc_client_send, "{\"status\":\"ok\"}");

    wp_config_t cfg = { .endpoint = (char *)endpoint,
                        .api_key  = "submit-tx-key" };
    wallet_proxy_t *proxy = NULL;
    assert_int_equal(wp_init(&cfg, &proxy), 0);

    /* Expect the actual transaction broadcast. */
    expect_string(rpc_client_send, endpoint, endpoint);
    expect_any(rpc_client_send, payload);
    will_return(rpc_client_send, 0);
    will_return(rpc_client_send, mock_tx_hash_json);

    char *tx_hash = NULL;
    assert_int_equal(wp_send_transaction(proxy, from_addr, to_addr,
                                         1'000'000, &tx_hash), 0);
    assert_non_null(tx_hash);
    assert_string_equal(tx_hash, "0xdeadbeefcafebabe");

    free(tx_hash);
    wp_free(proxy);
}

/* 4. Sign message – failure due to invalid key */
static void test_wp_sign_message_failure_invalid_key(void **state)
{
    (void)state;

    const char *endpoint = "https://testnet.holocanvas.org";

    /* Proxy initialisation stub. */
    expect_string(rpc_client_send, endpoint, endpoint);
    expect_any(rpc_client_send, payload);
    will_return(rpc_client_send, 0);
    will_return(rpc_client_send, "{\"status\":\"ok\"}");

    wp_config_t cfg = { .endpoint = (char *)endpoint,
                        .api_key  = "sign-fail-key" };
    wallet_proxy_t *proxy = NULL;
    assert_int_equal(wp_init(&cfg, &proxy), 0);

    /* Prepare message */
    const char msg[] = "HoloCanvas rocks!";
    const uint8_t *sig_dummy = NULL;
    size_t         sig_dummy_len = 0;

    /* The invalid key is signalled via crypto_sign returning error. */
    expect_any(crypto_sign, priv_key);
    expect_memory(crypto_sign, msg, msg, sizeof(msg) - 1);
    will_return(crypto_sign, -1);  /* retval */
    will_return(crypto_sign, sig_dummy);
    will_return(crypto_sign, sig_dummy_len);

    uint8_t *sig  = NULL;
    size_t   sLen = 0;
    assert_int_not_equal(wp_sign_message(proxy,
                                         (const uint8_t *)msg, sizeof(msg) - 1,
                                         &sig, &sLen), 0);
    assert_null(sig);
    assert_int_equal(sLen, 0);

    wp_free(proxy);
}

/* 5. Sign message – success path */
static void test_wp_sign_message_success(void **state)
{
    (void)state;

    const char *endpoint = "https://testnet.holocanvas.org";

    /* Proxy initialisation */
    expect_string(rpc_client_send, endpoint, endpoint);
    expect_any(rpc_client_send, payload);
    will_return(rpc_client_send, 0);
    will_return(rpc_client_send, "{\"status\":\"ok\"}");

    wp_config_t cfg = { .endpoint = (char *)endpoint,
                        .api_key  = "sign-success-key" };
    wallet_proxy_t *proxy = NULL;
    assert_int_equal(wp_init(&cfg, &proxy), 0);

    /* Prepare message & expect crypto_sign */
    const char msg[] = "Curate the future.";
    size_t      sig_len_ref = 0;
    const uint8_t *sig_ref = dummy_signature(&sig_len_ref);

    expect_any(crypto_sign, priv_key);
    expect_memory(crypto_sign, msg, msg, sizeof(msg) - 1);
    will_return(crypto_sign, 0);               /* success */
    will_return(crypto_sign, sig_ref);         /* ptr to sig */
    will_return(crypto_sign, sig_len_ref);     /* sig length */

    uint8_t *sig_out = NULL;
    size_t   sig_len = 0;
    assert_int_equal(wp_sign_message(proxy,
                                     (const uint8_t *)msg, sizeof(msg) - 1,
                                     &sig_out, &sig_len), 0);

    assert_non_null(sig_out);
    assert_int_equal(sig_len, sig_len_ref);
    assert_memory_equal(sig_out, sig_ref, sig_len_ref);

    free(sig_out);
    wp_free(proxy);
}

/* ------------------------------------------------------------------------- *
 * Test Runner
 * ------------------------------------------------------------------------- */
int main(void)
{
    const struct CMUnitTest tests[] = {
        cmocka_unit_test(test_wp_init_success),
        cmocka_unit_test(test_wp_init_missing_config),
        cmocka_unit_test(test_wp_send_transaction_success),
        cmocka_unit_test(test_wp_sign_message_failure_invalid_key),
        cmocka_unit_test(test_wp_sign_message_success)
    };
    return cmocka_run_group_tests_name("HoloCanvas Wallet-Proxy", tests, NULL, NULL);
}