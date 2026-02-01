```c
/*
 *  SynestheticCanvas/api-gateway/tests/test_middleware.c
 *
 *  Unit-tests for the API-gateway middleware layer.
 *  These tests exercise logging, rate-limiting and version-routing
 *  behaviour that is critical for production stability.
 *
 *  The tests are written with the Check unit-testing framework.
 *  Compile with:
 *
 *      gcc -Wall -Wextra -pedantic -pthread \
 *          -I../include -o test_middleware \
 *          test_middleware.c \
 *          $(pkg-config --cflags --libs check)
 *
 *  or use CMake / Meson integration shipped with the project.
 */

#include <check.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <pthread.h>
#include <stdatomic.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>

/* --------------------------------------------------------------------------
 *  Project headers
 * -------------------------------------------------------------------------- */
#include "middleware.h"          /* Production middleware contracts           */
#include "http_types.h"          /* sc_request_t / sc_response_t              */

/*
 *  When someone tries to build the tests without the full project sources,
 *  we still want compilation to succeed.  Provide minimal fall-back
 *  definitions that are automatically shadowed by the real headers when
 *  they are available.
 */
#ifndef SYN_CANVAS_MIDDLEWARE_H
#define SYN_CANVAS_MIDDLEWARE_H

#define SC_MW_OK               (0)
#define SC_MW_RATE_LIMIT_HIT   (1)
#define SC_MW_BAD_VERSION      (2)

typedef struct sc_request_t {
    char   method[8];
    char   path[256];
    char   accept_version[16];  /* SemVer string: "1.0" / "2.3" / etc.    */
    char   remote_addr[64];
} sc_request_t;

typedef struct sc_response_t {
    int    status;              /* HTTP status code                         */
    char  *body;                /* Dynamically allocated; NULL if empty     */
} sc_response_t;

/* Stubbed middleware implementations.
 * The real gateway provides production code—these variants are only
 * used when the gateway is not linked in.
 */
static int
sc_middleware_log_request(const sc_request_t *req,
                           const sc_response_t *res,
                           FILE *log_sink)
{
    if (!req || !log_sink) return EINVAL;
    /* Very bare-bone: write a single-line entry */
    return fprintf(log_sink,
                   "%s %s -> %d [%s]\n",
                   req->method,
                   req->path,
                   res ? res->status : 0,
                   req->remote_addr) < 0 ? EIO : SC_MW_OK;
}

/* Simple token bucket — 5 req/second, global */
static atomic_uint_fast64_t bucket    = 5;   /* available tokens          */
static atomic_uint_fast64_t timestamp = 0;   /* epoch sec when bucket set */

static int
sc_middleware_rate_limit(const sc_request_t *req)
{
    (void)req;
    time_t now = time(NULL);
    time_t t   = atomic_load_explicit(&timestamp, memory_order_acquire);

    if (now != t) {
        atomic_store(&bucket, 5);
        atomic_store(&timestamp, now);
    }

    uint_fast64_t tokens = atomic_load(&bucket);
    while (tokens) {
        if (atomic_compare_exchange_weak(&bucket, &tokens, tokens - 1))
            return SC_MW_OK;
    }
    return SC_MW_RATE_LIMIT_HIT;
}

static int
sc_middleware_version_route(const sc_request_t *req,
                            const char **target_service_out)
{
    if (!req || !target_service_out) return EINVAL;
    /* Demo: only v1 and v2 exist */
    if (strncmp(req->accept_version, "1.", 2) == 0) {
        *target_service_out = "palette-v1";
        return SC_MW_OK;
    }
    if (strncmp(req->accept_version, "2.", 2) == 0) {
        *target_service_out = "palette-v2";
        return SC_MW_OK;
    }
    return SC_MW_BAD_VERSION;
}

#endif /* SYN_CANVAS_MIDDLEWARE_H */

/* --------------------------------------------------------------------------
 *  Helpers
 * -------------------------------------------------------------------------- */

/* Capture written log lines in a dynamically growing memory buffer.
 * We use a FILE* obtained through open_memstream(3), which is GNU / POSIX.
 */
typedef struct {
    FILE  *stream;
    char  *data;
    size_t size;
} memlog_t;

static void
memlog_open(memlog_t *ml)
{
    ml->stream = open_memstream(&ml->data, &ml->size);
    ck_assert_ptr_ne(ml->stream, NULL);
}

static void
memlog_close(memlog_t *ml)
{
    fflush(ml->stream);
    fclose(ml->stream);
    ml->stream = NULL;
}

static const char*
memlog_cstr(memlog_t *ml)
{
    fflush(ml->stream);
    return ml->data ? ml->data : "";
}

/* Build a dummy request with sane defaults */
static void
make_request(sc_request_t *req,
             const char   *method,
             const char   *path,
             const char   *version,
             const char   *remote)
{
    strncpy(req->method,        method  ? method  : "GET", sizeof(req->method)        - 1);
    strncpy(req->path,          path    ? path    : "/",   sizeof(req->path)          - 1);
    strncpy(req->accept_version,version ? version : "1.0",sizeof(req->accept_version)- 1);
    strncpy(req->remote_addr,   remote  ? remote  : "127.0.0.1",
                                   sizeof(req->remote_addr) - 1);
}

/* --------------------------------------------------------------------------
 *  TEST CASES: Logging
 * -------------------------------------------------------------------------- */
START_TEST(test_log_writes_single_line)
{
    sc_request_t  req;
    sc_response_t res = { .status = 200, .body = NULL };
    memlog_t      ml;

    make_request(&req, "POST", "/v1/palette", "1.0", "198.51.100.3");

    memlog_open(&ml);
    int rc = sc_middleware_log_request(&req, &res, ml.stream);
    memlog_close(&ml);

    ck_assert_int_eq(rc, SC_MW_OK);

    const char *log_line = memlog_cstr(&ml);
    /* Expected format: "POST /v1/palette -> 200 [198.51.100.3]\n" */
    ck_assert_msg(strstr(log_line, "POST /v1/palette") != NULL,
                  "Log line must contain method & path");
    ck_assert_msg(strstr(log_line, "200") != NULL,
                  "Log line must contain status code");
    ck_assert_msg(strstr(log_line, "198.51.100.3") != NULL,
                  "Log line must contain remote address");

    free(ml.data);
}
END_TEST

/* --------------------------------------------------------------------------
 *  TEST CASES: Rate Limiting
 * -------------------------------------------------------------------------- */

#define RL_WORKERS          16
#define RL_REQ_PER_WORKER   20
#define RL_TOTAL_REQUESTS   (RL_WORKERS * RL_REQ_PER_WORKER)

static atomic_uint_fast64_t rl_success_cnt = 0;
static atomic_uint_fast64_t rl_reject_cnt  = 0;

static void*
rate_limit_worker(void *arg)
{
    (void)arg;
    sc_request_t req;
    make_request(&req, "GET", "/v1/color", "1.0", "203.0.113.10");

    for (unsigned i = 0; i < RL_REQ_PER_WORKER; ++i) {
        int rc = sc_middleware_rate_limit(&req);
        if (rc == SC_MW_OK)
            atomic_fetch_add_explicit(&rl_success_cnt, 1, memory_order_relaxed);
        else if (rc == SC_MW_RATE_LIMIT_HIT)
            atomic_fetch_add_explicit(&rl_reject_cnt, 1, memory_order_relaxed);
        else
            ck_abort_msg("Unexpected return code from rate-limit middleware");
        /* Sleep 10ms to spread the load */
        usleep(10 * 1000);
    }
    return NULL;
}

START_TEST(test_rate_limit_concurrent)
{
    pthread_t th[RL_WORKERS];

    atomic_store(&rl_success_cnt, 0);
    atomic_store(&rl_reject_cnt,  0);

    /* Spawn workers */
    for (size_t i = 0; i < RL_WORKERS; ++i)
        ck_assert_int_eq(pthread_create(&th[i], NULL, rate_limit_worker, NULL), 0);

    /* Join */
    for (size_t i = 0; i < RL_WORKERS; ++i)
        ck_assert_int_eq(pthread_join(th[i], NULL), 0);

    unsigned long succ = atomic_load(&rl_success_cnt);
    unsigned long rej  = atomic_load(&rl_reject_cnt);

    /* We expect some requests to be dropped */
    ck_assert_msg(succ + rej == RL_TOTAL_REQUESTS,
                  "All requests must be accounted for");
    ck_assert_msg(rej > 0,
                  "At least one request should be rate-limited under stress");
}
END_TEST

/* --------------------------------------------------------------------------
 *  TEST CASES: Version Routing
 * -------------------------------------------------------------------------- */
START_TEST(test_version_route_success)
{
    sc_request_t req;
    make_request(&req, "GET", "/palette", "2.1", "192.0.2.44");

    const char *service = NULL;
    int rc = sc_middleware_version_route(&req, &service);

    ck_assert_int_eq(rc, SC_MW_OK);
    ck_assert_str_eq(service, "palette-v2");
}
END_TEST

START_TEST(test_version_route_invalid)
{
    sc_request_t req;
    make_request(&req, "GET", "/palette", "3.0", "192.0.2.44");

    const char *service = NULL;
    int rc = sc_middleware_version_route(&req, &service);

    ck_assert_int_eq(rc, SC_MW_BAD_VERSION);
    ck_assert_ptr_eq(service, NULL);
}
END_TEST

/* --------------------------------------------------------------------------
 *  Suite / Runner
 * -------------------------------------------------------------------------- */
static Suite*
middleware_suite(void)
{
    Suite *s = suite_create("middleware");

    TCase *tc_log   = tcase_create("logging");
    TCase *tc_rl    = tcase_create("rate-limiting");
    TCase *tc_ver   = tcase_create("version-routing");

    /* Logging */
    tcase_add_test(tc_log, test_log_writes_single_line);

    /* Rate-limiting */
    tcase_set_timeout(tc_rl, 10);          /* generous timeout for threads */
    tcase_add_test(tc_rl, test_rate_limit_concurrent);

    /* Version routing */
    tcase_add_test(tc_ver, test_version_route_success);
    tcase_add_test(tc_ver, test_version_route_invalid);

    suite_add_tcase(s, tc_log);
    suite_add_tcase(s, tc_rl);
    suite_add_tcase(s, tc_ver);

    return s;
}

int
main(void)
{
    int number_failed;
    Suite *s       = middleware_suite();
    SRunner *sr    = srunner_create(s);

    /* Run suites */
    srunner_run_all(sr, CK_ENV);      /* honour CK_* env vars for verbosity */
    number_failed = srunner_ntests_failed(sr);
    srunner_free(sr);

    return (number_failed == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
}
```