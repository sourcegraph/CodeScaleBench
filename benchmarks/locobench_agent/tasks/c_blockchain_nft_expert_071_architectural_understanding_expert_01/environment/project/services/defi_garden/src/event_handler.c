/*
 * HoloCanvas – DeFi-Garden Microservice
 * File: event_handler.c
 *
 * Description:
 *   Central Kafka-consumer loop that ingests on-chain & DeFi events,
 *   parses JSON payloads, and forwards state transitions to the local
 *   State-Machine client as well as other internal subsystems.
 *
 *   This unit purposefully avoids any business logic; instead, it plays
 *   traffic-cop by routing well-formed events to specialised handlers.
 *
 * Build:
 *   gcc -std=c11 -Wall -Wextra -pedantic -o event_handler \
 *       event_handler.c -lrdkafka -lcjson -lpthread
 *
 * NOTE:
 *   Requires:
 *       - librdkafka                (https://github.com/edenhill/librdkafka)
 *       - cJSON                     (https://github.com/DaveGamble/cJSON)
 *       - state_machine_client.h    (local project header, see include/)
 *       - defi_garden_log.h         (local lightweight logger)
 */

#define _GNU_SOURCE     /* for strndup() */
#include <assert.h>
#include <errno.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <librdkafka/rdkafka.h>
#include <syslog.h>

#include "cJSON.h"

#include "state_machine_client.h"   /* Local project header. */
#include "defi_garden_log.h"        /* Lightweight wrapper over syslog. */


/* -------------------------------------------------------------------------- */
/*                               Compile-time CFG                             */
/* -------------------------------------------------------------------------- */

#ifndef DG_KAFKA_DEFAULT_BROKERS
#  define DG_KAFKA_DEFAULT_BROKERS  "localhost:9092"
#endif

#ifndef DG_KAFKA_GROUP_ID
#  define DG_KAFKA_GROUP_ID         "defi-garden-event-handler"
#endif

/* Topic list that this microservice is interested in. */
static const char *kTopics[] = {
    "ledger.events",
    "governance.events",
    "defi-garden.commands",
    NULL
};

/* -------------------------------------------------------------------------- */
/*                                  Typedefs                                  */
/* -------------------------------------------------------------------------- */

typedef enum {
    EVT_BID_PLACED,
    EVT_STAKE_DEPOSITED,
    EVT_GOVERNANCE_VOTE,
    EVT_UNKNOWN
} dg_event_type_t;

/* Forward declaration. */
struct dg_event_handler_ctx;

/* Callback invoked for each parsed event. */
typedef int (*dg_event_cb)(struct dg_event_handler_ctx *ctx,
                           const cJSON                 *payload);

/* Dispatch entry. */
typedef struct {
    dg_event_type_t   type;
    const char       *type_str;   /* JSON value */
    dg_event_cb       cb;
} dg_dispatch_entry_t;


/* Runtime context. */
typedef struct dg_event_handler_ctx {
    rd_kafka_t                       *rk;          /* Kafka consumer handle   */
    rd_kafka_conf_t                  *conf;        /* Kafka conf object       */
    rd_kafka_topic_partition_list_t  *subs;        /* Subscription topics     */
    volatile sig_atomic_t             run;         /* Set to 0 on shutdown    */

    /* Connection handle to local State-Machine client. */
    sm_client_t                      *sm;
} dg_event_handler_ctx_t;


/* -------------------------------------------------------------------------- */
/*                              Static Prototypes                             */
/* -------------------------------------------------------------------------- */

static bool            kafka_init(dg_event_handler_ctx_t *ctx);
static void            kafka_cleanup(dg_event_handler_ctx_t *ctx);
static void            install_signal_handlers(void);
static void            sig_handler(int sig);

static dg_event_type_t event_type_from_json(const char *s);
static int             dispatch_event(dg_event_handler_ctx_t *ctx,
                                      const cJSON            *root);

static int handle_bid_placed       (dg_event_handler_ctx_t *ctx,
                                    const cJSON *payload);
static int handle_stake_deposited  (dg_event_handler_ctx_t *ctx,
                                    const cJSON *payload);
static int handle_governance_vote  (dg_event_handler_ctx_t *ctx,
                                    const cJSON *payload);

/* -------------------------------------------------------------------------- */
/*                                Dispatch Table                              */
/* -------------------------------------------------------------------------- */

static const dg_dispatch_entry_t kDispatchTable[] = {
    { EVT_BID_PLACED,       "BidPlaced",       handle_bid_placed      },
    { EVT_STAKE_DEPOSITED,  "StakeDeposited",  handle_stake_deposited },
    { EVT_GOVERNANCE_VOTE,  "GovernanceVote",  handle_governance_vote },
    { EVT_UNKNOWN,          NULL,              NULL                  }
};


/* -------------------------------------------------------------------------- */
/*                               Implementation                               */
/* -------------------------------------------------------------------------- */

/* Global ctx pointer for signal handler. */
static dg_event_handler_ctx_t *g_ctx = NULL;


/*
 * Public entry point for producers that embed this handler as a library.
 */
int dg_event_handler_run(void)
{
    dg_event_handler_ctx_t ctx = {0};
    g_ctx = &ctx;

    /* ------------------------------------------------------------------ */
    /* Initialise dependencies: syslog, state machine, kafka.             */
    /* ------------------------------------------------------------------ */
    dg_log_init("defi_garden:event_handler", LOG_PID | LOG_PERROR, LOG_USER);

    ctx.sm = sm_client_connect(SM_DEFAULT_ENDPOINT);
    if (!ctx.sm) {
        DG_LOG_FATAL("failed to connect to local state-machine service");
        return EXIT_FAILURE;
    }

    if (!kafka_init(&ctx)) {
        sm_client_disconnect(ctx.sm);
        dg_log_close();
        return EXIT_FAILURE;
    }

    install_signal_handlers();
    ctx.run = 1;

    DG_LOG_INFO("event handler started; awaiting messages…");

    /* ------------------------------------------------------------------ */
    /* Main poll loop.                                                    */
    /* ------------------------------------------------------------------ */
    while (ctx.run) {
        rd_kafka_message_t *rkmsg =
            rd_kafka_consumer_poll(ctx.rk, 1000 /* timeout ms */);

        if (!rkmsg)                           /* Timed out */
            continue;

        if (rkmsg->err) {
            if (rkmsg->err == RD_KAFKA_RESP_ERR__PARTITION_EOF) {
                DG_LOG_DEBUG("reached end of %s [%"PRId32"] @ %"PRId64,
                             rd_kafka_topic_name(rkmsg->rkt),
                             rkmsg->partition,
                             rkmsg->offset);
            } else {
                DG_LOG_ERROR("consume error: %s",
                             rd_kafka_message_errstr(rkmsg));
            }
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        /* Parse payload as JSON. */
        const char *payload = (const char *)rkmsg->payload;
        cJSON *root = cJSON_ParseWithLength(payload, (int)rkmsg->len);
        if (!root) {
            DG_LOG_WARN("invalid JSON from topic %s",
                        rd_kafka_topic_name(rkmsg->rkt));
            rd_kafka_message_destroy(rkmsg);
            continue;
        }

        dispatch_event(&ctx, root);

        cJSON_Delete(root);
        rd_kafka_message_destroy(rkmsg);
    }

    /* ------------------------------------------------------------------ */
    /* Shutdown sequence.                                                 */
    /* ------------------------------------------------------------------ */
    DG_LOG_INFO("shutting down…");

    kafka_cleanup(&ctx);
    sm_client_disconnect(ctx.sm);
    dg_log_close();

    return EXIT_SUCCESS;
}


/* -------------------------------------------------------------------------- */
/*                              Helper functions                              */
/* -------------------------------------------------------------------------- */

/*
 * Build librdkafka consumer.
 */
static bool kafka_init(dg_event_handler_ctx_t *ctx)
{
    char errstr[512];

    ctx->conf = rd_kafka_conf_new();

    if (rd_kafka_conf_set(ctx->conf, "bootstrap.servers",
                          getenv("DG_KAFKA_BROKERS") ? getenv("DG_KAFKA_BROKERS")
                                                     : DG_KAFKA_DEFAULT_BROKERS,
                          errstr, sizeof(errstr)) != RD_KAFKA_CONF_OK) {
        DG_LOG_ERROR("kafka conf: %s", errstr);
        return false;
    }

    if (rd_kafka_conf_set(ctx->conf, "group.id",
                          getenv("DG_KAFKA_GROUP_ID") ?
                            getenv("DG_KAFKA_GROUP_ID") : DG_KAFKA_GROUP_ID,
                          errstr, sizeof(errstr)) != RD_KAFKA_CONF_OK) {
        DG_LOG_ERROR("kafka conf: %s", errstr);
        return false;
    }

    /* Enable auto-commit but be explicit about interval. */
    rd_kafka_conf_set(ctx->conf, "enable.auto.commit", "true", NULL, 0);
    rd_kafka_conf_set(ctx->conf, "auto.commit.interval.ms", "5000", NULL, 0);

    /* Create consumer instance. */
    ctx->rk = rd_kafka_new(RD_KAFKA_CONSUMER, ctx->conf,
                           errstr, sizeof(errstr));
    if (!ctx->rk) {
        DG_LOG_ERROR("failed to create Kafka consumer: %s", errstr);
        return false;
    }

    /* Redirect kafka logging to syslog. */
    rd_kafka_set_log_level(ctx->rk, LOG_NOTICE);

    /* Subscribe to topics. */
    ctx->subs = rd_kafka_topic_partition_list_new(8);

    for (size_t i = 0; kTopics[i]; ++i) {
        rd_kafka_topic_partition_list_add(ctx->subs, kTopics[i],
                                          RD_KAFKA_PARTITION_UA);
    }

    rd_kafka_resp_err_t err =
        rd_kafka_subscribe(ctx->rk, ctx->subs);

    if (err) {
        DG_LOG_ERROR("failed to subscribe to topics: %s",
                     rd_kafka_err2str(err));
        return false;
    }

    return true;
}

static void kafka_cleanup(dg_event_handler_ctx_t *ctx)
{
    if (!ctx || !ctx->rk)
        return;

    rd_kafka_consumer_close(ctx->rk);
    rd_kafka_topic_partition_list_destroy(ctx->subs);
    rd_kafka_destroy(ctx->rk);

    /* rd_kafka_conf_destroy is NOT needed – ownership transferred. */
}

static void install_signal_handlers(void)
{
    struct sigaction sa = {0};
    sa.sa_handler = sig_handler;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;

    sigaction(SIGINT,  &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGQUIT, &sa, NULL);
}

static void sig_handler(int sig)
{
    (void)sig;
    if (g_ctx)
        g_ctx->run = 0;
}

/* -------------------------------------------------------------------------- */
/*                             Dispatch Functions                             */
/* -------------------------------------------------------------------------- */

/* Map JSON "event_type" string to enum. */
static dg_event_type_t event_type_from_json(const char *s)
{
    for (size_t i = 0; kDispatchTable[i].type_str; ++i)
        if (strcmp(kDispatchTable[i].type_str, s) == 0)
            return kDispatchTable[i].type;

    return EVT_UNKNOWN;
}

static int dispatch_event(dg_event_handler_ctx_t *ctx,
                          const cJSON            *root)
{
    const cJSON *type_json = cJSON_GetObjectItemCaseSensitive(root, "event_type");
    const cJSON *payload   = cJSON_GetObjectItemCaseSensitive(root, "payload");

    if (!cJSON_IsString(type_json) || !payload) {
        DG_LOG_WARN("event missing required fields");
        return -EINVAL;
    }

    dg_event_type_t type = event_type_from_json(type_json->valuestring);

    for (size_t i = 0; kDispatchTable[i].type_str; ++i) {
        if (kDispatchTable[i].type == type) {
            int rc = kDispatchTable[i].cb(ctx, payload);
            if (rc != 0)
                DG_LOG_ERROR("handler returned %d for event %s",
                             rc, type_json->valuestring);
            return rc;
        }
    }

    DG_LOG_DEBUG("unhandled event type: %s", type_json->valuestring);
    return 0;
}


/* -------------------------------------------------------------------------- */
/*                         Individual Event Handlers                          */
/* -------------------------------------------------------------------------- */

static int handle_bid_placed(dg_event_handler_ctx_t *ctx,
                             const cJSON *payload)
{
    (void)ctx;

    const cJSON *artifact_id = cJSON_GetObjectItem(payload, "artifact_id");
    const cJSON *bidder      = cJSON_GetObjectItem(payload, "bidder");
    const cJSON *amount      = cJSON_GetObjectItem(payload, "amount_wei");

    if (!cJSON_IsString(artifact_id) ||
        !cJSON_IsString(bidder) ||
        !cJSON_IsString(amount)) {
        DG_LOG_WARN("BidPlaced event: missing fields");
        return -EINVAL;
    }

    DG_LOG_INFO("BidPlaced: artifact=%s, bidder=%s, amount=%s",
                artifact_id->valuestring,
                bidder->valuestring,
                amount->valuestring);

    /* Forward to state-machine. */
    sm_bid_t bid = {
        .artifact_id = artifact_id->valuestring,
        .bidder      = bidder->valuestring,
        .amount_wei  = amount->valuestring
    };

    if (sm_client_submit_bid(ctx->sm, &bid) != 0) {
        DG_LOG_ERROR("StateMachine rejected bid for %s", artifact_id->valuestring);
        return -EIO;
    }

    return 0;
}

static int handle_stake_deposited(dg_event_handler_ctx_t *ctx,
                                  const cJSON *payload)
{
    const cJSON *pool_id = cJSON_GetObjectItem(payload, "pool_id");
    const cJSON *user    = cJSON_GetObjectItem(payload, "user");
    const cJSON *amount  = cJSON_GetObjectItem(payload, "amount_wei");

    if (!cJSON_IsString(pool_id) ||
        !cJSON_IsString(user) ||
        !cJSON_IsString(amount)) {
        DG_LOG_WARN("StakeDeposited event: malformed");
        return -EINVAL;
    }

    DG_LOG_INFO("StakeDeposited: pool=%s, user=%s, amount=%s",
                pool_id->valuestring,
                user->valuestring,
                amount->valuestring);

    sm_stake_t st = {
        .pool_id   = pool_id->valuestring,
        .staker    = user->valuestring,
        .amount_wei= amount->valuestring
    };

    if (sm_client_deposit_stake(ctx->sm, &st) != 0) {
        DG_LOG_ERROR("StateMachine failed stake for pool %s", pool_id->valuestring);
        return -EIO;
    }

    return 0;
}

static int handle_governance_vote(dg_event_handler_ctx_t *ctx,
                                  const cJSON *payload)
{
    const cJSON *proposal_id = cJSON_GetObjectItem(payload, "proposal_id");
    const cJSON *voter       = cJSON_GetObjectItem(payload, "voter");
    const cJSON *option      = cJSON_GetObjectItem(payload, "option");

    if (!cJSON_IsString(proposal_id) ||
        !cJSON_IsString(voter) ||
        !cJSON_IsString(option)) {
        DG_LOG_WARN("GovernanceVote event: malformed");
        return -EINVAL;
    }

    DG_LOG_INFO("GovernanceVote: proposal=%s, voter=%s, option=%s",
                proposal_id->valuestring,
                voter->valuestring,
                option->valuestring);

    sm_vote_t vote = {
        .proposal_id = proposal_id->valuestring,
        .voter       = voter->valuestring,
        .option      = option->valuestring
    };

    if (sm_client_submit_vote(ctx->sm, &vote) != 0) {
        DG_LOG_ERROR("StateMachine failed vote for proposal %s",
                     proposal_id->valuestring);
        return -EIO;
    }

    return 0;
}


/* -------------------------------------------------------------------------- */
/*                                Unit Testing                                */
/* -------------------------------------------------------------------------- */
#ifdef DG_EVENT_HANDLER_TEST

int main(void)
{
    return dg_event_handler_run();
}

#endif /* DG_EVENT_HANDLER_TEST */



/* -------------------------------------------------------------------------- */
/*                                   EOF                                      */
/* -------------------------------------------------------------------------- */
