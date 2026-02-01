```rust
//! Delegation domain layer for the Staking Service.
//!
//! This module encapsulates the core business-logic for delegating stake to
//! validators and revoking it again.  It is 100 % independent from any I/O or
//! persistence layer so that the same logic can be reused inside the gRPC API,
//! an HTTP API, a CLI or off-chain workers.
//!
//! Patterns demonstrated
//! ---------------------
//! • State-Machine – Every [`DelegationState`] transition is modelled
//!   explicitly and validated at runtime.
//! • Observer – [`DelegationEventSink`] allows the surrounding application to
//!   react to domain events (e.g. publish them on the global event bus).
//! • Strategy – [`RewardStrategy`] lets us plug in alternative reward curves
//!   without touching the delegation code.
//!
//! Concurrency
//! -----------
//! Internally we protect the in-memory store by an [`RwLock`].  Each public
//! method is `async` so it can be awaited from asynchronous runtimes such as
//! Tokio or async-std.
//!
//! Error handling
//! --------------
//! Errors are collected in a single [`DelegationError`] enum that implements
//! [`std::error::Error`] via `thiserror::Error`.
//!
//! NOTE: In an actual production system the *persistent* state would live in
//! a database (e.g. Postgres, RocksDB or Substrate storage) and the in-memory
//! HashMap would be removed.  For the sake of this example the map gives us a
//! self-contained implementation without external dependencies.

use chrono::{DateTime, Utc};
use log::{debug, info, warn};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    fmt,
    sync::Arc,
};
use tokio::sync::RwLock;
use uuid::Uuid;

use thiserror::Error;

/// Type-alias used throughout the staking service for account identifiers.
///
/// For the real chain you may want to new-type this around a `blake2_256` hash
/// or similar.  At the domain layer it is sufficient to stick to UTF-8 strings
/// to preserve human readability.
pub type AccountId = String;

/// Amount of tokens in the smallest on-chain denomination (e.g. Wei).
pub type TokenAmount = u128;

/// Unique identifier for a validator (e.g. ed25519 public key).
pub type ValidatorId = String;

/* ------------------------------------------------------------------------- */
/*                                 Domain                                    */
/* ------------------------------------------------------------------------- */

/// Possible life-cycle states of a delegation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum DelegationState {
    /// Tokens are actively bonded to a validator and accrue rewards.
    Active,
    /// Delegation was revoked – tokens are currently in the unbonding period.
    ///
    /// They do not accrue rewards any more but are not free either.
    Revoking,
    /// Tokens are fully unlocked and can be transferred or delegated again.
    Unbonded,
}

/// Immutable record of a single delegation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Delegation {
    pub id:           Uuid,
    pub delegator:    AccountId,
    pub validator:    ValidatorId,
    pub amount:       TokenAmount,
    pub state:        DelegationState,
    pub created_at:   DateTime<Utc>,
    pub updated_at:   DateTime<Utc>,
}

impl Delegation {
    /// Helper to build a new active delegation.
    fn new_active(delegator: AccountId, validator: ValidatorId, amount: TokenAmount) -> Self {
        let now = Utc::now();
        Self {
            id: Uuid::new_v4(),
            delegator,
            validator,
            amount,
            state: DelegationState::Active,
            created_at: now,
            updated_at: now,
        }
    }
}

/* ------------------------------------------------------------------------- */
/*                                  Events                                   */
/* ------------------------------------------------------------------------- */

/// Domain events emitted by the delegation module.
#[derive(Debug, Clone)]
pub enum DelegationEvent {
    Delegated {
        id:        Uuid,
        delegator: AccountId,
        validator: ValidatorId,
        amount:    TokenAmount,
    },
    Increased {
        id:        Uuid,
        amount:    TokenAmount,
        new_total: TokenAmount,
    },
    Revoked {
        id:        Uuid,
    },
    Withdrawn {
        id:        Uuid,
        amount:    TokenAmount,
    },
}

/// Observer interface for receiving events.
///
/// Implementors can forward events to an event-bus, write audit logs, update an
/// analytics cache, …
#[async_trait::async_trait]
pub trait DelegationEventSink: Send + Sync + 'static {
    async fn publish(&self, event: DelegationEvent);
}

#[async_trait::async_trait]
impl DelegationEventSink for () {
    async fn publish(&self, _event: DelegationEvent) {
        // no-op sink
    }
}

/* ------------------------------------------------------------------------- */
/*                              Reward Strategy                              */
/* ------------------------------------------------------------------------- */

/// Decouples reward computation from the delegation logic.
pub trait RewardStrategy: Send + Sync + 'static {
    /// Calculate rewards for a given `stake` over `elapsed_seconds`.
    fn reward(&self, stake: TokenAmount, elapsed_seconds: u64) -> TokenAmount;
}

/// A naïve, constant APR reward strategy used as default.
pub struct FixedAprStrategy {
    /// Annual percentage rate scaled by 10,000  
    /// (`5 %` = `500`, `7.25 %` = `725`).
    apr_bps: u32,
}

impl FixedAprStrategy {
    pub fn new(apr_bps: u32) -> Self {
        Self { apr_bps }
    }
}

impl RewardStrategy for FixedAprStrategy {
    fn reward(&self, stake: TokenAmount, elapsed_seconds: u64) -> TokenAmount {
        // APR is yearly.  Convert elapsed time to fraction of a year.
        const SECONDS_PER_YEAR: u64 = 365 * 24 * 60 * 60;
        let fraction = elapsed_seconds as f64 / SECONDS_PER_YEAR as f64;
        let rate      = self.apr_bps as f64 / 10_000_f64;
        let reward    = stake as f64 * rate * fraction;

        reward.round() as TokenAmount
    }
}

/* ------------------------------------------------------------------------- */
/*                                   Error                                   */
/* ------------------------------------------------------------------------- */

/// All possible errors produced by the delegation module.
#[derive(Error, Debug)]
pub enum DelegationError {
    #[error("delegation {0} not found")]
    NotFound(Uuid),

    #[error("delegation {id} is in invalid state: {state:?}")]
    InvalidState {
        id:    Uuid,
        state: DelegationState,
    },

    #[error("insufficient stake to decrease by {requested}, only {available} available")]
    InsufficientStake {
        requested: TokenAmount,
        available: TokenAmount,
    },

    #[error("delegator {delegator} already delegated to validator {validator}")]
    AlreadyDelegated {
        delegator: AccountId,
        validator: ValidatorId,
    },
}

pub type Result<T> = std::result::Result<T, DelegationError>;

/* ------------------------------------------------------------------------- */
/*                          Delegation State Manager                         */
/* ------------------------------------------------------------------------- */

/// Public façade for all delegation operations.
///
/// # Thread-safety
/// Internally protected by an `Arc<RwLock<…>>` to allow concurrent reads and
/// exclusive writes.
#[derive(Clone)]
pub struct DelegationManager<Ev = ()> {
    inner:      Arc<RwLock<HashMap<Uuid, Delegation>>>,
    sink:       Arc<Ev>,
}

impl<Ev: DelegationEventSink> DelegationManager<Ev> {
    /// Create a new manager with an external [`DelegationEventSink`].
    pub fn with_sink(sink: Ev) -> Self {
        Self {
            inner: Arc::new(RwLock::new(HashMap::new())),
            sink:  Arc::new(sink),
        }
    }

    /// Convenience constructor with a no-op event sink.
    pub fn new() -> Self
    where
        Ev: Default,
    {
        Self::with_sink(Ev::default())
    }

    /// Delegate `amount` tokens from `delegator` to `validator`.
    pub async fn delegate(
        &self,
        delegator: AccountId,
        validator: ValidatorId,
        amount: TokenAmount,
    ) -> Result<Uuid> {
        // Check uniqueness (one delegator->validator pair)
        {
            let store = self.inner.read().await;
            if store.values().any(|d| {
                d.delegator == delegator && d.validator == validator && d.state == DelegationState::Active
            }) {
                return Err(DelegationError::AlreadyDelegated { delegator, validator });
            }
        }

        // Create delegation
        let delegation = Delegation::new_active(delegator.clone(), validator.clone(), amount);
        let id         = delegation.id;

        {
            let mut store = self.inner.write().await;
            store.insert(id, delegation);
        }

        // Fire event
        self.sink
            .publish(DelegationEvent::Delegated {
                id,
                delegator,
                validator,
                amount,
            })
            .await;

        info!("New delegation {id} created");
        Ok(id)
    }

    /// Increase stake for an existing delegation.
    pub async fn increase_stake(&self, id: Uuid, additional: TokenAmount) -> Result<TokenAmount> {
        let mut store = self.inner.write().await;
        let delegation = store.get_mut(&id).ok_or(DelegationError::NotFound(id))?;

        if delegation.state != DelegationState::Active {
            return Err(DelegationError::InvalidState { id, state: delegation.state });
        }

        delegation.amount = delegation
            .amount
            .checked_add(additional)
            .expect("overflow on stake increase");
        delegation.updated_at = Utc::now();

        let new_total = delegation.amount;
        self.sink
            .publish(DelegationEvent::Increased {
                id,
                amount: additional,
                new_total,
            })
            .await;

        debug!("Delegation {id} increased by {additional} to {new_total}");
        Ok(new_total)
    }

    /// Initiate revocation.  The delegation enters `Revoking` state.
    pub async fn revoke(&self, id: Uuid) -> Result<()> {
        let mut store = self.inner.write().await;
        let delegation = store.get_mut(&id).ok_or(DelegationError::NotFound(id))?;

        if delegation.state != DelegationState::Active {
            return Err(DelegationError::InvalidState { id, state: delegation.state });
        }

        delegation.state       = DelegationState::Revoking;
        delegation.updated_at  = Utc::now();

        self.sink.publish(DelegationEvent::Revoked { id }).await;
        warn!("Delegation {id} revoked");
        Ok(())
    }

    /// Complete unbonding process – delegation moves to `Unbonded` state.
    ///
    /// The caller (e.g. a scheduled task) is responsible for ensuring the
    /// unbonding period has passed.
    pub async fn finalize_unbonding(&self, id: Uuid) -> Result<()> {
        let mut store = self.inner.write().await;
        let delegation = store.get_mut(&id).ok_or(DelegationError::NotFound(id))?;

        if delegation.state != DelegationState::Revoking {
            return Err(DelegationError::InvalidState { id, state: delegation.state });
        }

        delegation.state      = DelegationState::Unbonded;
        delegation.updated_at = Utc::now();

        Ok(())
    }

    /// Withdraw tokens from an *UNBONDED* delegation.  
    /// The delegation will be removed entirely afterwards.
    pub async fn withdraw(&self, id: Uuid) -> Result<TokenAmount> {
        let mut store = self.inner.write().await;
        let delegation = store.remove(&id).ok_or(DelegationError::NotFound(id))?;

        if delegation.state != DelegationState::Unbonded {
            // Put it back in the map before returning
            store.insert(id, delegation.clone());
            return Err(DelegationError::InvalidState { id, state: delegation.state });
        }

        let amount = delegation.amount;
        self.sink.publish(DelegationEvent::Withdrawn { id, amount }).await;
        Ok(amount)
    }

    /// Get a copy of a delegation.
    pub async fn get(&self, id: Uuid) -> Result<Delegation> {
        let store = self.inner.read().await;
        store.get(&id).cloned().ok_or(DelegationError::NotFound(id))
    }

    /// Calculate current reward using the provided strategy.
    pub async fn pending_reward(
        &self,
        id: Uuid,
        strategy: &dyn RewardStrategy,
    ) -> Result<TokenAmount> {
        let store   = self.inner.read().await;
        let deleg   = store.get(&id).ok_or(DelegationError::NotFound(id))?;

        if deleg.state != DelegationState::Active {
            return Err(DelegationError::InvalidState { id, state: deleg.state });
        }

        let elapsed = (Utc::now() - deleg.updated_at).num_seconds().try_into().unwrap_or(0);
        Ok(strategy.reward(deleg.amount, elapsed))
    }

    /// List all active delegations for a given delegator.
    pub async fn list_by_delegator(&self, delegator: &AccountId) -> Vec<Delegation> {
        let store = self.inner.read().await;
        store
            .values()
            .filter(|d| &d.delegator == delegator)
            .cloned()
            .collect()
    }

    /// List all delegations for a validator.
    pub async fn list_by_validator(&self, validator: &ValidatorId) -> Vec<Delegation> {
        let store = self.inner.read().await;
        store
            .values()
            .filter(|d| &d.validator == validator)
            .cloned()
            .collect()
    }

    /// Calculate the *total* stake bonded to `validator`.
    pub async fn total_stake_for_validator(&self, validator: &ValidatorId) -> TokenAmount {
        let store = self.inner.read().await;
        store
            .values()
            .filter(|d| &d.validator == validator && d.state == DelegationState::Active)
            .map(|d| d.amount)
            .sum()
    }
}

/* ------------------------------------------------------------------------- */
/*                               Unit tests                                  */
/* ------------------------------------------------------------------------- */

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn happy_path_delegate_and_withdraw() {
        let mgr = DelegationManager::<()>::new();

        let delegator = "alice".to_owned();
        let validator = "validator-01".to_owned();

        let id = mgr
            .delegate(delegator.clone(), validator.clone(), 1_000)
            .await
            .expect("delegate");

        mgr.increase_stake(id, 500).await.expect("increase");
        mgr.revoke(id).await.expect("revoke");
        mgr.finalize_unbonding(id).await.expect("finalize");
        let withdrawn = mgr.withdraw(id).await.expect("withdraw");

        assert_eq!(withdrawn, 1_500);
    }

    #[tokio::test]
    async fn cannot_delegate_twice_to_same_validator() {
        let mgr = DelegationManager::<()>::new();
        let delegator = "bob".to_owned();
        let validator = "validator-02".to_owned();

        mgr.delegate(delegator.clone(), validator.clone(), 1_000)
            .await
            .expect("first delegation ok");

        let err = mgr
            .delegate(delegator, validator, 500)
            .await
            .expect_err("second delegation should fail");

        matches!(err, DelegationError::AlreadyDelegated { .. });
    }
}
```