/*
 * HoloCanvas – DeFi Garden
 * ========================================
 * File:    defi.h
 * Author:  HoloCanvas Core Team
 * License: MIT
 *
 * Public interface for the DeFi-Garden micro-service.  The API enables
 * Liquidity-Pool (LP) management, yield-farming, and staking operations
 * against NFT-backed synthetic tokens minted by the HoloCanvas
 * Mint-Factory.  All calls are fully thread-safe and re-entrant.
 *
 * NOTE:
 *   This header purposefully contains zero private implementation details.
 *   Equivalent .c files must include <defi_internal.h> for access
 *   to opaque structures.
 */

#ifndef HOLOCANVAS_DEFI_H
#define HOLOCANVAS_DEFI_H

#ifdef __cplusplus
extern "C" {
#endif

/* =======  Standard Library  =========================================== */

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* =======  Platform / Visibility  ====================================== */

#if defined(_WIN32) && !defined(__MINGW32__)
  #ifdef HOLOCANVAS_DEFI_BUILD
    #define DEFI_API __declspec(dllexport)
  #else
    #define DEFI_API __declspec(dllimport)
  #endif
#else
  #define DEFI_API __attribute__((visibility("default")))
#endif

/* =======  Versioning  ================================================== */

#define DEFI_MAJOR_VERSION 1
#define DEFI_MINOR_VERSION 0
#define DEFI_PATCH_VERSION 3

#define DEFI_VERSION_STR  "1.0.3"

/* =======  Compile-Time Configuration  ================================= */

#ifndef DEFI_MAX_SYMBOL_LEN
  #define DEFI_MAX_SYMBOL_LEN  16
#endif

#ifndef DEFI_MAX_ADDRESS_LEN
  #define DEFI_MAX_ADDRESS_LEN 48
#endif

/* =======  Error Handling  ============================================= */

typedef enum {
    DEFI_OK = 0,

    /* Generic errors */
    DEFI_ERR_UNKNOWN          = -1,
    DEFI_ERR_NOMEM            = -2,
    DEFI_ERR_INVALID_ARGUMENT = -3,
    DEFI_ERR_OVERFLOW         = -4,
    DEFI_ERR_UNSUPPORTED      = -5,
    DEFI_ERR_IO               = -6,

    /* Domain-specific errors */
    DEFI_ERR_POOL_NOT_FOUND       = -100,
    DEFI_ERR_POOL_ALREADY_EXISTS  = -101,
    DEFI_ERR_INSUFFICIENT_FUNDS   = -102,
    DEFI_ERR_SLIPPAGE_TOO_HIGH    = -103,
    DEFI_ERR_POSITION_NOT_FOUND   = -104,
    DEFI_ERR_TX_REJECTED          = -105,
    DEFI_ERR_CONTRACT_REVERT      = -106,

    /* Network / consensus */
    DEFI_ERR_CONSENSUS            = -200,
    DEFI_ERR_CHAIN_FORK_DETECTED  = -201,
    DEFI_ERR_TIMEOUT              = -202,

} defi_err_t;

/* =======  Domain Types  =============================================== */

/* 128-bit unsigned integer used for atomic accounting. */
typedef unsigned __int128 defi_u128;

/* Ensures structure packing is consistent network-wide. */
#pragma pack(push, 1)

/* Human-readable token symbol (e.g., "HLC", "hETH"). */
typedef struct {
    char symbol[DEFI_MAX_SYMBOL_LEN];
} defi_symbol_t;

/* On-chain address / public key (Base58 or Bech32 encoded). */
typedef struct {
    char addr[DEFI_MAX_ADDRESS_LEN];
} defi_address_t;

/* Emitted event descriptor (opaque). */
typedef struct defi_event_s defi_event_t;

/* Pool life-cycle */
typedef enum {
    DEFI_POOL_STATE_INACTIVE = 0,
    DEFI_POOL_STATE_ACTIVE,
    DEFI_POOL_STATE_PAUSED,
    DEFI_POOL_STATE_RETIRED
} defi_pool_state_t;

/* Transaction intent */
typedef enum {
    DEFI_TX_DEPOSIT = 0,
    DEFI_TX_WITHDRAW,
    DEFI_TX_HARVEST,
    DEFI_TX_STAKE,
    DEFI_TX_UNSTAKE,
    DEFI_TX_REWARD
} defi_tx_type_t;

/* Liquidity pool descriptor (opaque). */
typedef struct defi_pool_s defi_pool_t;

/* Farming / staking position (opaque). */
typedef struct defi_position_s defi_position_t;

#pragma pack(pop)

/* =======  Callbacks & Observers  ====================================== */

typedef void (*defi_event_cb)(
        const defi_event_t *event,
        void               *user_data);

/* ====  Global Lifecycle ================================================= */

/**
 * Initialize DeFi-Garden runtime. Must be called once per process before
 * any other API call.  Thread-safe: concurrent callers are ignored after
 * the first success.
 *
 * @return DEFI_OK on success, otherwise error code.
 */
DEFI_API defi_err_t
defi_initialize(void);

/**
 * Shutdown runtime and release global resources.  Blocks until all
 * outstanding asynchronous operations are completed or canceled.
 *
 * @return DEFI_OK or an error if shutdown fails.
 */
DEFI_API defi_err_t
defi_shutdown(void);

/* ====  Pool Management ================================================== */

/**
 * Create a new liquidity pool identified by `symbol_pair`
 * (e.g., "HLC/hETH").  The caller becomes the pool's operator.
 *
 * @param operator_addr   Address of pool creator (must be EOA).
 * @param symbol_pair     ERC-20 or native asset pair, slash-separated.
 * @param init_liquidity  Amount for bootstrapping the pool.
 * @param out_pool        [out] Newly created pool handle.
 *
 * @return DEFI_OK or error code.
 */
DEFI_API defi_err_t
defi_create_pool(const defi_address_t *operator_addr,
                 const char           *symbol_pair,
                 defi_u128             init_liquidity,
                 defi_pool_t         **out_pool);

/**
 * Obtain immutable information about a pool.
 *
 * @param pool           Pool handle.
 * @param out_state      Current pool state.
 * @param out_tvl        Total value locked (may be NULL).
 *
 * @return DEFI_OK or error code.
 */
DEFI_API defi_err_t
defi_get_pool_info(const defi_pool_t  *pool,
                   defi_pool_state_t  *out_state,
                   defi_u128          *out_tvl);

/**
 * Pause or unpause a pool.  Only callable by pool operator or governance
 * contract.
 *
 * @param pool      Pool handle.
 * @param paused    true => pause, false => resume
 *
 * @return DEFI_OK or error code.
 */
DEFI_API defi_err_t
defi_set_pool_paused(defi_pool_t *pool, bool paused);

/* ====  Liquidity Operations ============================================ */

/**
 * Deposit liquidity into `pool`.
 *
 * @param pool          Target pool.
 * @param depositor     Sender's address.
 * @param amount        Amount of base tokens to add.
 * @param slippage_bps  Maximum slippage in basis points (1/100%).
 * @param block_deadline Block height after which tx is invalid.
 * @param out_position  [out] Position handle (optional, may be NULL).
 *
 * @return DEFI_OK or error code.
 */
DEFI_API defi_err_t
defi_deposit(defi_pool_t           *pool,
             const defi_address_t  *depositor,
             defi_u128              amount,
             uint16_t               slippage_bps,
             uint64_t               block_deadline,
             defi_position_t      **out_position);

/**
 * Withdraw liquidity or rewards.
 *
 * @param position     Position handle obtained from deposit.
 * @param withdraw_all true to withdraw everything.
 * @param amount       Specific amount (ignored if withdraw_all=true).
 *
 * @return DEFI_OK or error code.
 */
DEFI_API defi_err_t
defi_withdraw(defi_position_t *position,
              bool             withdraw_all,
              defi_u128        amount);

/**
 * Harvest farming rewards without affecting principal.
 *
 * @param position  Farming / staking position.
 *
 * @return DEFI_OK or error code.
 */
DEFI_API defi_err_t
defi_harvest(defi_position_t *position);

/* ====  Event Subscription ============================================== */

/**
 * Subscribe to garden-wide events (new pools, TVL updates, etc.).
 *
 * @param cb         Callback invoked from a worker thread.
 * @param user_data  Opaque pointer passed to callback.
 *
 * @return DEFI_OK or error code.
 */
DEFI_API defi_err_t
defi_subscribe_events(defi_event_cb cb, void *user_data);

/**
 * Unsubscribe the callback previously registered.
 *
 * @param cb         Same function pointer provided to subscribe.
 *
 * @return DEFI_OK or error code.
 */
DEFI_API defi_err_t
defi_unsubscribe_events(defi_event_cb cb);

/* ====  Utility Functions =============================================== */

/**
 * Convert a defi_u128 amount to decimal string; caller frees the returned
 * buffer with free(3).  Thread-safe.
 *
 * @param value       128-bit unsigned integer.
 * @param decimals    Number of decimal places to format.
 *
 * @return malloc'ed null-terminated string, or NULL on error.
 */
DEFI_API char *
defi_u128_to_str(defi_u128 value, uint8_t decimals);

/**
 * Parse a decimal string into defi_u128.  Thread-safe.
 *
 * @param str       ASCII decimal string (no exponent).
 * @param out_val   [out] Parsed integer.
 *
 * @return DEFI_OK or error code.
 */
DEFI_API defi_err_t
defi_str_to_u128(const char *str, defi_u128 *out_val);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* HOLOCANVAS_DEFI_H */
