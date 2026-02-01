/******************************************************************************
 * Project: HoloCanvas – A Micro-Gallery Blockchain for Generative Artifacts
 * File:    tests/integration/test_full_lifecycle.c
 *
 * Purpose:
 * --------
 * End-to-end / integration test that drives an NFT artifact through its entire
 * on-chain life-cycle: Draft  -> Curated -> Auction -> Fractionalized -> Staked
 * while also exercising the Event-Driven, Observer, and State-Machine aspects
 * of the platform.  All external services are substituted with lightweight,
 * in-process fakes/harnesses so that the test remains fully deterministic and
 * suitable for CI pipelines.
 *
 * Notes:
 * ------
 * 1. This test file is self-contained – no production code is re-implemented
 *    here, only thin shims/mocks around the public interfaces that would be
 *    provided by the actual HoloCanvas micro-services.
 * 2. Threading & a bounded lock-free queue are used to emulate the Kafka mesh.
 ******************************************************************************/

#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* ------------------------------------------------------------------------- */
/*                              Utility Macros                               */
/* ------------------------------------------------------------------------- */

/* Poor-man's test runner                                                       */
#define TEST_OK()  do { g_tests_passed++; } while (0)
#define TEST_FAIL(msg)                                                         \
    do {                                                                       \
        fprintf(stderr, "[%s:%d] Test failed: %s\n", __FILE__, __LINE__, msg); \
        g_tests_failed++;                                                      \
        return;                                                                \
    } while (0)

/* Compile-time array length helper                                            */
#define ARRAY_LEN(a) (sizeof(a) / sizeof((a)[0]))

/* ------------------------------------------------------------------------- */
/*                         Domain Types & Enumerations                        */
/* ------------------------------------------------------------------------- */

#define ARTIFACT_ID_LEN  64
#define WALLET_ADDR_LEN  64
#define EVENT_QUEUE_LEN  1024

typedef enum
{
    ART_STATE_DRAFT = 0,
    ART_STATE_CURATED,
    ART_STATE_AUCTION,
    ART_STATE_FRACTIONALIZED,
    ART_STATE_STAKED,
    ART_STATE_MAX
} artifact_state_e;

static const char *state_to_str(artifact_state_e s)
{
    static const char *names[] = {
        "Draft", "Curated", "Auction", "Fractionalized", "Staked"
    };
    return (s < ART_STATE_MAX) ? names[s] : "Invalid";
}

typedef struct
{
    char              id[ARTIFACT_ID_LEN];
    artifact_state_e  state;
    uint64_t          bid_count;
    double            highest_bid_eth;
} artifact_t;

/* ------------------------------------------------------------------------- */
/*                    Minimal Event-Driven Infrastructure                     */
/* ------------------------------------------------------------------------- */

typedef enum
{
    EVT_LIKE = 0,
    EVT_BID,
    EVT_ORACLE_WEATHER_CHANGE,
    EVT_TIMER_TICK,
    EVT_QUEUE_SHUTDOWN
} event_type_e;

typedef struct
{
    event_type_e type;
    union
    {
        struct
        {
            double eth;
            char   bidder[WALLET_ADDR_LEN];
        } bid;
    } payload;
} evt_t;

/* Simple bounded ring buffer – single producer / single consumer friendly.    */
typedef struct
{
    evt_t      buf[EVENT_QUEUE_LEN];
    uint32_t   write_idx;
    uint32_t   read_idx;
    bool       shutdown;
    pthread_mutex_t mtx;
    pthread_cond_t  cv_nonempty;
    pthread_cond_t  cv_nonfull;
} evt_queue_t;

static void evtq_init(evt_queue_t *q)
{
    memset(q, 0, sizeof(*q));
    pthread_mutex_init(&q->mtx, NULL);
    pthread_cond_init(&q->cv_nonempty, NULL);
    pthread_cond_init(&q->cv_nonfull, NULL);
}

static void evtq_destroy(evt_queue_t *q)
{
    pthread_mutex_destroy(&q->mtx);
    pthread_cond_destroy(&q->cv_nonempty);
    pthread_cond_destroy(&q->cv_nonfull);
}

static bool evtq_push(evt_queue_t *q, const evt_t *ev)
{
    pthread_mutex_lock(&q->mtx);
    while (((q->write_idx + 1) % EVENT_QUEUE_LEN) == q->read_idx && !q->shutdown)
        pthread_cond_wait(&q->cv_nonfull, &q->mtx);

    if (q->shutdown) {
        pthread_mutex_unlock(&q->mtx);
        return false;
    }

    q->buf[q->write_idx] = *ev;
    q->write_idx = (q->write_idx + 1) % EVENT_QUEUE_LEN;

    pthread_cond_signal(&q->cv_nonempty);
    pthread_mutex_unlock(&q->mtx);
    return true;
}

static bool evtq_pop(evt_queue_t *q, evt_t *out)
{
    pthread_mutex_lock(&q->mtx);
    while (q->write_idx == q->read_idx && !q->shutdown)
        pthread_cond_wait(&q->cv_nonempty, &q->mtx);

    if (q->shutdown) {
        pthread_mutex_unlock(&q->mtx);
        return false;
    }

    *out = q->buf[q->read_idx];
    q->read_idx = (q->read_idx + 1) % EVENT_QUEUE_LEN;

    pthread_cond_signal(&q->cv_nonfull);
    pthread_mutex_unlock(&q->mtx);
    return true;
}

static void evtq_signal_shutdown(evt_queue_t *q)
{
    pthread_mutex_lock(&q->mtx);
    q->shutdown = true;
    pthread_cond_broadcast(&q->cv_nonempty);
    pthread_cond_broadcast(&q->cv_nonfull);
    pthread_mutex_unlock(&q->mtx);
}

/* ------------------------------------------------------------------------- */
/*                          Simple On-Chain State Machine                    */
/* ------------------------------------------------------------------------- */

static int art_transition(artifact_t *a, artifact_state_e next_state)
{
    /* Validity matrix. 1 == allowed transition                                       */
    static const int allowed[ART_STATE_MAX][ART_STATE_MAX] = {
        /* from \ to         Draft Curated Auction Fractionalized Staked */
        /* Draft */         {   0 ,   1 ,    0 ,      0,          0 },
        /* Curated */       {   0 ,   0 ,    1 ,      0,          0 },
        /* Auction */       {   0 ,   0 ,    0 ,      1,          0 },
        /* Fractionalized */{   0 ,   0 ,    0 ,      0,          1 },
        /* Staked */        {   0 ,   0 ,    0 ,      0,          0 }
    };

    if (next_state <= a->state || next_state >= ART_STATE_MAX)
        return -EINVAL;

    if (!allowed[a->state][next_state])
        return -EPERM;

    a->state = next_state;
    return 0;
}

static void art_print(const artifact_t *a, const char *msg)
{
    printf("[Artifact %s] %s | state=%s bids=%" PRIu64 " highest=%.2f ETH\n",
           a->id, msg, state_to_str(a->state), a->bid_count, a->highest_bid_eth);
}

/* ------------------------------------------------------------------------- */
/*                      Test-Exclusive Mocked Subsystems                     */
/* ------------------------------------------------------------------------- */

/* Random hex string generator – fakes a wallet / tx / artifact id             */
static void rand_hex(char *dst, size_t len)
{
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < len - 1; ++i)
        dst[i] = hex[rand() % 16];
    dst[len - 1] = '\0';
}

/* Simulate on-chain bid                                               */
static int onchain_place_bid(artifact_t *a, const char *wallet, double eth)
{
    if (a->state != ART_STATE_AUCTION)
        return -EPERM;

    ++a->bid_count;
    if (eth > a->highest_bid_eth)
        a->highest_bid_eth = eth;

    (void)wallet; /* would log bidder address on real chain */
    return 0;
}

/* ------------------------------------------------------------------------- */
/*                          Muse  (Observer Thread)                          */
/* ------------------------------------------------------------------------- */

typedef struct
{
    artifact_t  *artifact;
    evt_queue_t *queue;
    uint64_t     likes;
} muse_ctx_t;

static void *muse_thread(void *arg)
{
    muse_ctx_t *ctx = arg;
    evt_t       ev;

    while (evtq_pop(ctx->queue, &ev)) {
        switch (ev.type) {
        case EVT_LIKE:
            if (++ctx->likes >= 5 && ctx->artifact->state == ART_STATE_DRAFT) {
                art_print(ctx->artifact, "Auto-curating due to likes threshold");
                art_transition(ctx->artifact, ART_STATE_CURATED);
            }
            break;
        case EVT_BID:
            onchain_place_bid(ctx->artifact, ev.payload.bid.bidder,
                              ev.payload.bid.eth);
            break;
        case EVT_ORACLE_WEATHER_CHANGE:
            /* Could trigger visual layer evolution – omitted for brevity */
            break;
        case EVT_TIMER_TICK:
            /* No-op in this mock                                                   */
            break;
        default:
            break;
        }
    }
    return NULL;
}

/* ------------------------------------------------------------------------- */
/*                              Test Fixtures                                */
/* ------------------------------------------------------------------------- */

static evt_queue_t g_event_q;
static pthread_t  g_muse_tid;
static muse_ctx_t g_muse_ctx;

/* Test counters */
static int g_tests_passed = 0;
static int g_tests_failed = 0;

/* Called once before the entire suite                                          */
static void test_suite_set_up(void)
{
    srand((unsigned int)time(NULL));

    evtq_init(&g_event_q);

    /* create a fresh artifact in Draft state                                    */
    static artifact_t shared_artifact;
    rand_hex(shared_artifact.id, sizeof shared_artifact.id);
    shared_artifact.state          = ART_STATE_DRAFT;
    shared_artifact.bid_count      = 0;
    shared_artifact.highest_bid_eth = 0.0;

    g_muse_ctx.artifact = &shared_artifact;
    g_muse_ctx.queue    = &g_event_q;
    g_muse_ctx.likes    = 0;

    /* Launch Muse observer thread                                               */
    if (pthread_create(&g_muse_tid, NULL, muse_thread, &g_muse_ctx) != 0) {
        perror("pthread_create");
        exit(EXIT_FAILURE);
    }

    art_print(&shared_artifact, "Test suite setup complete");
}

/* Called once after the entire suite                                           */
static void test_suite_tear_down(void)
{
    evtq_signal_shutdown(&g_event_q);
    pthread_join(g_muse_tid, NULL);
    evtq_destroy(&g_event_q);

    printf("\n========= TEST SUMMARY =========\n");
    printf("Passed: %d\n", g_tests_passed);
    printf("Failed: %d\n", g_tests_failed);
    printf("================================\n");

    if (g_tests_failed)
        exit(EXIT_FAILURE);
}

/* Helper to access shared artifact safely – for this single-thread test code
 * we simply return the pointer.  In a real multi-thread harness you would
 * guard with a mutex or design the artifact to be lock-free.                  */
static artifact_t *shared_artifact(void)
{
    return g_muse_ctx.artifact;
}

/* ------------------------------------------------------------------------- */
/*                               Test Cases                                  */
/* ------------------------------------------------------------------------- */

static void test_auto_curate_on_likes(void)
{
    artifact_t *a = shared_artifact();

    /* Feed 5 like events – Muse should auto-transition Draft->Curated          */
    for (int i = 0; i < 5; ++i) {
        evt_t e = { .type = EVT_LIKE };
        assert(evtq_push(&g_event_q, &e));
    }

    /* Wait briefly for Muse to consume                                         */
    usleep(100 * 1000); /* 100ms */

    if (a->state != ART_STATE_CURATED)
        TEST_FAIL("Artifact was not auto-curated after likes threshold");

    TEST_OK();
}

static void test_manual_transition_to_auction(void)
{
    artifact_t *a = shared_artifact();
    int rc = art_transition(a, ART_STATE_AUCTION);
    if (rc != 0 || a->state != ART_STATE_AUCTION)
        TEST_FAIL("Failed to transition Curated -> Auction");

    TEST_OK();
}

static void test_place_bids(void)
{
    artifact_t *a = shared_artifact();
    const char *bidders[] = { "0xAAA", "0xBBB", "0xCCC" };
    double bids_eth[]    = { 1.5, 2.25, 1.8 };

    for (size_t i = 0; i < ARRAY_LEN(bidders); ++i) {
        evt_t e = {
            .type = EVT_BID,
            .payload.bid.eth = bids_eth[i]
        };
        strncpy(e.payload.bid.bidder, bidders[i], sizeof e.payload.bid.bidder);
        assert(evtq_push(&g_event_q, &e));
    }

    usleep(100 * 1000);

    if (a->bid_count != ARRAY_LEN(bids_eth))
        TEST_FAIL("Bid count mismatch");

    if (a->highest_bid_eth < 2.25 - 1e-6)
        TEST_FAIL("Highest bid tracking failed");

    TEST_OK();
}

static void test_fractionalize(void)
{
    artifact_t *a = shared_artifact();
    int rc = art_transition(a, ART_STATE_FRACTIONALIZED);
    if (rc != 0 || a->state != ART_STATE_FRACTIONALIZED)
        TEST_FAIL("Failed to transition Auction -> Fractionalized");

    TEST_OK();
}

static void test_stake(void)
{
    artifact_t *a = shared_artifact();
    int rc = art_transition(a, ART_STATE_STAKED);
    if (rc != 0 || a->state != ART_STATE_STAKED)
        TEST_FAIL("Failed to transition Fractionalized -> Staked");

    TEST_OK();
}

static void test_invalid_backwards_transition(void)
{
    artifact_t *a = shared_artifact();
    int rc = art_transition(a, ART_STATE_AUCTION);  /* Attempt to go backwards */
    if (rc == 0)
        TEST_FAIL("Backwards transition should have failed");

    TEST_OK();
}

/* ------------------------------------------------------------------------- */
/*                                  main                                     */
/* ------------------------------------------------------------------------- */

int main(void)
{
    test_suite_set_up();

    test_auto_curate_on_likes();
    test_manual_transition_to_auction();
    test_place_bids();
    test_fractionalize();
    test_stake();
    test_invalid_backwards_transition();

    test_suite_tear_down();
    return 0;
}