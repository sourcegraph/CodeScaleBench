```c
/**
 * HoloCanvas – DeFi-Garden Microservice
 * -------------------------------------
 * File: staking_pool.c
 *
 * A thread-safe, on-chain staking pool implementation used by the
 * DeFi-Garden microservice to incentivise participation in the
 * HoloCanvas ecosystem.  The pool keeps an internal reward-per-token
 * accumulator so rewards may be distributed in O(1) time regardless of
 * the number of stakers, while still allowing constant-time look-ups
 * per staker via a hash map.
 *
 * NOTE: External subsystems (Kafka event-bus, LedgerCore, persistence
 * layer, etc.) are referenced through thin façade header files that are
 * expected to be provided elsewhere in the code base.
 *
 * Build flags:
 *     cc -Wall -Wextra -pedantic -pthread -lcjson -lcrypto -o staking_pool staking_pool.c
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <pthread.h>
#include <inttypes.h>
#include <time.h>
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <openssl/sha.h>
#include <cjson/cJSON.h>

#include "event_bus.h"      /* Kafka / gRPC façade                */
#include "ledger_core.h"    /* Token transfers & balances          */
#include "metrics.h"        /* Prom-style metrics instrumentation  */
#include "uthash.h"         /* Hash-table (https://troydhanson.github.io/uthash/) */

/* ----------------------------------------------------------------------
 * Build-time configuration
 * --------------------------------------------------------------------*/
#ifndef STAKING_STATE_DIR
#define STAKING_STATE_DIR "/var/lib/holocanvas/defi_garden/pools"
#endif

#define POOL_STATE_FILE_EXT ".json"
#define POOL_STATE_TMP_EXT  ".tmp"
#define FILE_MODE           (S_IRUSR | S_IWUSR | S_IRGRP) /* 0640 */

/* Flush pool state to disk at least every N seconds. */
#define PERSIST_INTERVAL_SEC 60

/* ----------------------------------------------------------------------
 * Logging helpers
 * --------------------------------------------------------------------*/
#define LOG_PREFIX "[staking_pool] "

#define LOG_ERROR(fmt, ...)   fprintf(stderr, LOG_PREFIX "ERROR: " fmt "\n", ##__VA_ARGS__)
#define LOG_WARN(fmt, ...)    fprintf(stderr, LOG_PREFIX "WARN : " fmt "\n", ##__VA_ARGS__)
#define LOG_INFO(fmt, ...)    fprintf(stdout, LOG_PREFIX "INFO : " fmt "\n", ##__VA_ARGS__)

/* ----------------------------------------------------------------------
 * Data structures
 * --------------------------------------------------------------------*/

/**
 * One stake entry per user (address -> balance + reward debt).
 * reward_debt keeps track of rewards already accounted for.
 */
typedef struct stake_entry {
    char           *user_address;       /* hex-encoded wallet address    */
    uint64_t        amount;             /* tokens staked (wei)           */
    double          reward_debt;        /* rewards already claimed       */
    UT_hash_handle  hh;                 /* uthash handle                 */
} stake_entry_t;

/**
 * The staking pool object.
 */
typedef struct staking_pool {
    char             id[64];            /* human-readable pool id        */
    uint64_t         total_staked;      /* total tokens staked           */
    double           acc_reward_pt;     /* accumulated reward per token  */
    stake_entry_t   *ledger;            /* address -> stake entry        */
    pthread_mutex_t  lock;              /* protects the above fields     */
    time_t           last_persist;      /* unix ts of last disk flush    */
} staking_pool_t;

/* ----------------------------------------------------------------------
 * Forward declarations
 * --------------------------------------------------------------------*/
static int  persist_state_locked(const staking_pool_t *pool);
static int  load_state_locked(staking_pool_t *pool);
static void publish_event_reward(const char *pool_id, uint64_t reward);
static void publish_event_stake(const char *pool_id,
                                const char *user,
                                uint64_t     amount,
                                int          direction);

/* ----------------------------------------------------------------------
 * Pool initialisation / destruction
 * --------------------------------------------------------------------*/

/**
 * Create (or load) a staking pool.
 *
 * @param id  Pool identifier (human readable, <= 63 bytes).
 * @return    Pointer to pool on success, NULL on failure.
 */
staking_pool_t *staking_pool_open(const char *id)
{
    if (!id || strlen(id) >= sizeof(((staking_pool_t *)0)->id)) {
        errno = EINVAL;
        LOG_ERROR("invalid pool id");
        return NULL;
    }

    staking_pool_t *pool = calloc(1, sizeof(*pool));
    if (!pool) {
        LOG_ERROR("calloc failed: %s", strerror(errno));
        return NULL;
    }

    strncpy(pool->id, id, sizeof(pool->id) - 1);

    if (pthread_mutex_init(&pool->lock, NULL) != 0) {
        LOG_ERROR("mutex init failed");
        free(pool);
        return NULL;
    }

    if (load_state_locked(pool) != 0) {
        /* First time?  Start with empty state. */
        LOG_WARN("starting new pool '%s'", pool->id);
    } else {
        LOG_INFO("loaded pool '%s' (total_staked=%" PRIu64 ")",
                 pool->id, pool->total_staked);
    }

    pool->last_persist = time(NULL);
    return pool;
}

/**
 * Shutdown pool and flush state to disk.
 */
void staking_pool_close(staking_pool_t *pool)
{
    if (!pool) return;

    pthread_mutex_lock(&pool->lock);
    if (persist_state_locked(pool) != 0) {
        LOG_ERROR("final persist failed – data may be lost");
    }
    pthread_mutex_unlock(&pool->lock);

    /* Free hash table entries */
    stake_entry_t *cur, *tmp;
    HASH_ITER(hh, pool->ledger, cur, tmp)
    {
        HASH_DEL(pool->ledger, cur);
        free(cur->user_address);
        free(cur);
    }

    pthread_mutex_destroy(&pool->lock);
    free(pool);
}

/* ----------------------------------------------------------------------
 * Core staking operations
 * --------------------------------------------------------------------*/

/**
 * Stake tokens into the pool.
 *
 * Transfers tokens from user wallet → pool escrow (handled by LedgerCore).
 *
 * @return 0 on success, -1 on failure.
 */
int staking_pool_stake(staking_pool_t *pool,
                       const char     *user,
                       uint64_t        amount)
{
    if (!pool || !user || amount == 0) {
        errno = EINVAL;
        return -1;
    }

    /* Transfer tokens via LedgerCore BEFORE mutating local state. */
    if (ledger_debit(user, amount) != 0 ||
        ledger_credit(pool->id, amount) != 0) {
        LOG_ERROR("ledger transfer failed for %s", user);
        return -1;
    }

    pthread_mutex_lock(&pool->lock);

    /* Get or create stake entry. */
    stake_entry_t *entry = NULL;
    HASH_FIND_STR(pool->ledger, user, entry);
    if (!entry) {
        entry = calloc(1, sizeof(*entry));
        if (!entry) {
            pthread_mutex_unlock(&pool->lock);
            LOG_ERROR("calloc entry failed");
            return -1;
        }
        entry->user_address = strdup(user);
        if (!entry->user_address) {
            free(entry);
            pthread_mutex_unlock(&pool->lock);
            LOG_ERROR("strdup failed");
            return -1;
        }
        entry->amount = 0;
        entry->reward_debt = pool->acc_reward_pt;
        HASH_ADD_KEYPTR(hh, pool->ledger, entry->user_address,
                        strlen(entry->user_address), entry);
    }

    /* Update user balance and global totals. */
    entry->amount += amount;
    pool->total_staked += amount;

    /* Adjust reward debt so pending rewards remain unchanged.   */
    entry->reward_debt = entry->amount * pool->acc_reward_pt;

    /* Optionally flush state to disk. */
    time_t now = time(NULL);
    if (now - pool->last_persist >= PERSIST_INTERVAL_SEC) {
        persist_state_locked(pool);
        pool->last_persist = now;
    }

    pthread_mutex_unlock(&pool->lock);

    /* Emit event after releasing the lock to avoid dead-locks. */
    publish_event_stake(pool->id, user, amount, +1);
    metrics_inc_counter("defi_garden_staked", amount);

    return 0;
}

/**
 * Unstake tokens and (optionally) claim pending rewards.
 *
 * @param claim_reward  if non-zero, also transfer pending rewards.
 */
int staking_pool_unstake(staking_pool_t *pool,
                         const char     *user,
                         uint64_t        amount,
                         int             claim_reward)
{
    if (!pool || !user || amount == 0) {
        errno = EINVAL;
        return -1;
    }

    pthread_mutex_lock(&pool->lock);
    stake_entry_t *entry = NULL;
    HASH_FIND_STR(pool->ledger, user, entry);
    if (!entry || entry->amount < amount) {
        pthread_mutex_unlock(&pool->lock);
        LOG_ERROR("insufficient stake for %s", user);
        errno = EPERM;
        return -1;
    }

    /* Calculate pending reward before changing stake amount. */
    double pending = ((double)entry->amount * pool->acc_reward_pt)
                     - entry->reward_debt;

    entry->amount -= amount;
    pool->total_staked -= amount;

    /* Update reward debt to new stake. */
    entry->reward_debt = (double)entry->amount * pool->acc_reward_pt;

    /* Flush state periodically. */
    time_t now = time(NULL);
    if (now - pool->last_persist >= PERSIST_INTERVAL_SEC) {
        persist_state_locked(pool);
        pool->last_persist = now;
    }
    pthread_mutex_unlock(&pool->lock);

    /* Ledger transfers: tokens back to user. */
    if (ledger_debit(pool->id, amount) != 0 ||
        ledger_credit(user, amount) != 0) {
        LOG_ERROR("ledger transfer failed during unstake for %s", user);
        return -1;
    }

    /* Transfer reward if asked. */
    if (claim_reward && pending > 0.0) {
        uint64_t reward_tokens = (uint64_t)pending;
        if (ledger_debit(pool->id, reward_tokens) != 0 ||
            ledger_credit(user, reward_tokens) != 0) {
            LOG_ERROR("failed to transfer reward to %s", user);
            /* Best effort: reward remains in pool. */
        } else {
            publish_event_reward(pool->id, reward_tokens);
            metrics_inc_counter("defi_garden_reward_paid", reward_tokens);
        }
    }

    publish_event_stake(pool->id, user, amount, -1);
    metrics_inc_counter("defi_garden_unstaked", amount);

    return 0;
}

/**
 * Deposit rewards into the staking pool.
 *
 * Rewards are transferred from the caller’s wallet into the pool, then
 * added to the acc_reward_pt accumulator so that each staker’s share
 * can be withdrawn lazily.
 */
int staking_pool_deposit_reward(staking_pool_t *pool,
                                const char     *from,
                                uint64_t        reward_amount)
{
    if (!pool || !from || reward_amount == 0) {
        errno = EINVAL;
        return -1;
    }

    /* Transfer tokens into pool escrow first. */
    if (ledger_debit(from, reward_amount) != 0 ||
        ledger_credit(pool->id, reward_amount) != 0) {
        LOG_ERROR("ledger reward transfer failed");
        return -1;
    }

    pthread_mutex_lock(&pool->lock);

    if (pool->total_staked == 0) {
        /*
         * No one is staking right now – hold reward in pool until the
         * first staker arrives (avoids division by zero).
         */
        LOG_WARN("reward deposited but no stakers – holding funds");
    } else {
        pool->acc_reward_pt +=
            (double)reward_amount / (double)pool->total_staked;
    }

    /* Persist state asynchronously. */
    time_t now = time(NULL);
    if (now - pool->last_persist >= PERSIST_INTERVAL_SEC) {
        persist_state_locked(pool);
        pool->last_persist = now;
    }

    pthread_mutex_unlock(&pool->lock);

    publish_event_reward(pool->id, reward_amount);
    metrics_inc_counter("defi_garden_reward_deposit", reward_amount);

    return 0;
}

/**
 * Return the pending reward for a given user without mutating state.
 */
double staking_pool_pending_reward(staking_pool_t *pool, const char *user)
{
    if (!pool || !user) return 0.0;

    pthread_mutex_lock(&pool->lock);
    stake_entry_t *entry = NULL;
    HASH_FIND_STR(pool->ledger, user, entry);
    double pending = 0.0;
    if (entry) {
        pending = ((double)entry->amount * pool->acc_reward_pt)
                  - entry->reward_debt;
    }
    pthread_mutex_unlock(&pool->lock);

    return pending;
}

/* ----------------------------------------------------------------------
 * Persistence helpers
 * --------------------------------------------------------------------*/

/* Build canonical file path: <STAKING_STATE_DIR>/<poolId>.json */
static void state_file_path(const staking_pool_t *pool,
                            char                 *buf,
                            size_t                len,
                            const char           *suffix)
{
    snprintf(buf, len, "%s/%s%s",
             STAKING_STATE_DIR, pool->id, suffix ? suffix : POOL_STATE_FILE_EXT);
}

/* Serialise current pool state into a cJSON object. */
static cJSON *serialise_pool_locked(const staking_pool_t *pool)
{
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "id", pool->id);
    cJSON_AddNumberToObject(root, "total_staked", (double)pool->total_staked);
    cJSON_AddNumberToObject(root, "acc_reward_pt", pool->acc_reward_pt);

    cJSON *stakes = cJSON_AddArrayToObject(root, "ledger");
    stake_entry_t *entry, *tmp;
    HASH_ITER(hh, pool->ledger, entry, tmp)
    {
        cJSON *item = cJSON_CreateObject();
        cJSON_AddStringToObject(item, "user", entry->user_address);
        cJSON_AddNumberToObject(item, "amount", (double)entry->amount);
        cJSON_AddNumberToObject(item, "reward_debt", entry->reward_debt);
        cJSON_AddItemToArray(stakes, item);
    }
    return root;
}

/**
 * Persist state; caller must hold pool->lock.
 *
 * We write to a temporary file first and then atomically rename to avoid
 * partial files when the process crashes.
 */
static int persist_state_locked(const staking_pool_t *pool)
{
    char path[PATH_MAX];
    char tmp [PATH_MAX];

    state_file_path(pool, path, sizeof(path), POOL_STATE_FILE_EXT);
    state_file_path(pool, tmp,  sizeof(tmp),  POOL_STATE_TMP_EXT);

    /* Ensure directory exists (mkdir ‑p style). */
    char dir[PATH_MAX];
    strncpy(dir, STAKING_STATE_DIR, sizeof(dir));
    dir[sizeof(dir) - 1] = '\0';
    if (mkdir(dir, 0750) != 0 && errno != EEXIST) {
        LOG_ERROR("mkdir %s failed: %s", dir, strerror(errno));
        return -1;
    }

    FILE *fp = fopen(tmp, "w");
    if (!fp) {
        LOG_ERROR("fopen %s failed: %s", tmp, strerror(errno));
        return -1;
    }

    /* Obtain exclusive lock while writing. */
    if (flock(fileno(fp), LOCK_EX) != 0) {
        LOG_ERROR("flock failed: %s", strerror(errno));
        fclose(fp);
        return -1;
    }

    cJSON *root = serialise_pool_locked(pool);
    char *json  = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    if (!json) {
        flock(fileno(fp), LOCK_UN);
        fclose(fp);
        LOG_ERROR("json serialise failed");
        return -1;
    }

    if (fprintf(fp, "%s\n", json) < 0) {
        LOG_ERROR("fwrite failed: %s", strerror(errno));
        free(json);
        flock(fileno(fp), LOCK_UN);
        fclose(fp);
        return -1;
    }
    free(json);

    fflush(fp);
    fsync(fileno(fp));
    flock(fileno(fp), LOCK_UN);
    fclose(fp);

    /* Atomic rename */
    if (rename(tmp, path) != 0) {
        LOG_ERROR("rename failed: %s", strerror(errno));
        return -1;
    }

    return 0;
}

/**
 * Load pool state from disk.  Called during pool initialisation while
 * no other thread has access, therefore no need to lock().
 *
 * Return 0 on success, non-zero if file missing or corrupted.
 */
static int load_state_locked(staking_pool_t *pool)
{
    char path[PATH_MAX];
    state_file_path(pool, path, sizeof(path), POOL_STATE_FILE_EXT);

    FILE *fp = fopen(path, "r");
    if (!fp) {
        return -1; /* probably first time */
    }

    fseek(fp, 0, SEEK_END);
    long len = ftell(fp);
    rewind(fp);

    char *buf = malloc(len + 1);
    if (!buf) {
        fclose(fp);
        return -1;
    }
    fread(buf, 1, len, fp);
    buf[len] = '\0';
    fclose(fp);

    cJSON *root = cJSON_Parse(buf);
    free(buf);
    if (!root) {
        return -1;
    }

    cJSON *total_staked = cJSON_GetObjectItem(root, "total_staked");
    cJSON *acc_rpt      = cJSON_GetObjectItem(root, "acc_reward_pt");
    cJSON *ledger_arr   = cJSON_GetObjectItem(root, "ledger");

    if (!cJSON_IsNumber(total_staked) ||
        !cJSON_IsNumber(acc_rpt)      ||
        !cJSON_IsArray(ledger_arr)) {
        cJSON_Delete(root);
        return -1;
    }

    pool->total_staked  = (uint64_t)total_staked->valuedouble;
    pool->acc_reward_pt = acc_rpt->valuedouble;

    /* Rebuild ledger hash map. */
    int arr_size = cJSON_GetArraySize(ledger_arr);
    for (int i = 0; i < arr_size; ++i) {
        cJSON *item  = cJSON_GetArrayItem(ledger_arr, i);
        cJSON *user  = cJSON_GetObjectItem(item, "user");
        cJSON *amt   = cJSON_GetObjectItem(item, "amount");
        cJSON *rdebt = cJSON_GetObjectItem(item, "reward_debt");
        if (!cJSON_IsString(user) || !cJSON_IsNumber(amt) ||
            !cJSON_IsNumber(rdebt))
            continue;

        stake_entry_t *entry = calloc(1, sizeof(*entry));
        if (!entry) continue;
        entry->user_address = strdup(user->valuestring);
        entry->amount       = (uint64_t)amt->valuedouble;
        entry->reward_debt  = rdebt->valuedouble;
        HASH_ADD_KEYPTR(hh, pool->ledger, entry->user_address,
                        strlen(entry->user_address), entry);
    }

    cJSON_Delete(root);
    return 0;
}

/* ----------------------------------------------------------------------
 * Event-bus helpers
 * --------------------------------------------------------------------*/

static void publish_event_reward(const char *pool_id, uint64_t reward)
{
    event_t ev = {
        .topic = "defi.reward",
        .key   = pool_id,
    };
    cJSON *payload = cJSON_CreateObject();
    cJSON_AddStringToObject(payload, "pool_id", pool_id);
    cJSON_AddNumberToObject(payload, "reward", (double)reward);
    ev.payload = cJSON_PrintUnformatted(payload);
    cJSON_Delete(payload);

    if (event_bus_publish(&ev) != 0) {
        LOG_WARN("failed to publish reward event");
    }
    free(ev.payload);
}

static void publish_event_stake(const char *pool_id,
                                const char *user,
                                uint64_t     amount,
                                int          direction)
{
    event_t ev = {
        .topic = "defi.stake",
        .key   = pool_id,
    };
    cJSON *payload = cJSON_CreateObject();
    cJSON_AddStringToObject(payload, "pool_id", pool_id);
    cJSON_AddStringToObject(payload, "user", user);
    cJSON_AddNumberToObject(payload, "delta", (double)(direction * (double)amount));
    ev.payload = cJSON_PrintUnformatted(payload);
    cJSON_Delete(payload);

    if (event_bus_publish(&ev) != 0) {
        LOG_WARN("failed to publish stake event");
    }
    free(ev.payload);
}

/* ----------------------------------------------------------------------
 * House-keeping thread
 * --------------------------------------------------------------------*/

/**
 * Background thread periodically persists state and reports metrics.
 */
static void *housekeeping_thread(void *arg)
{
    staking_pool_t *pool = arg;
    const int interval   = 15; /* seconds */

    for (;;) {
        sleep(interval);

        pthread_mutex_lock(&pool->lock);
        persist_state_locked(pool);
        pthread_mutex_unlock(&pool->lock);

        metrics_set_gauge("defi_garden_total_staked", pool->total_staked);
    }
    return NULL;
}

/**
 * Spawn housekeeping thread; call right after creating pool.
 */
int staking_pool_start_housekeeping(staking_pool_t *pool)
{
    pthread_t tid;
    int rc = pthread_create(&tid, NULL, housekeeping_thread, pool);
    if (rc != 0) {
        LOG_ERROR("failed to start housekeeping thread");
        return -1;
    }
    /* Detach – will exit with the process. */
    pthread_detach(tid);
    return 0;
}

/* ----------------------------------------------------------------------
 * Simple self-test when run as a standalone binary.
 * --------------------------------------------------------------------*/
#ifdef STAKING_POOL_SELFTEST

static void assert_true(int cond, const char *msg)
{
    if (!cond) {
        fprintf(stderr, "ASSERT FAILED: %s\n", msg);
        exit(EXIT_FAILURE);
    }
}

int main(void)
{
    staking_pool_t *pool = staking_pool_open("test-pool");
    assert_true(pool != NULL, "pool open");

    assert_true(staking_pool_stake(pool, "0xABC", 1000) == 0, "stake 1000");
    assert_true(staking_pool_deposit_reward(pool, "treasury", 500) == 0, "deposit reward 500");

    double pending = staking_pool_pending_reward(pool, "0xABC");
    assert_true((uint64_t)pending == 500, "pending reward == 500");

    assert_true(staking_pool_unstake(pool, "0xABC", 1000, 1) == 0, "unstake + claim");

    staking_pool_close(pool);
    printf("Self-test passed.\n");
    return 0;
}

#endif /* STAKING_POOL_SELFTEST */
```