```rust
//! staking_logic.rs
//!
//! Core staking & composer–selection logic for the CanvasChain Symphony
//! staking micro-service.  This file purposefully contains no gRPC or HTTP
//! plumbing;  it is meant to be embedded by the service‐layer binary and
//! driven by the surrounding transport / storage adapters.
//!
//! Architectural notes
//! -------------------
//! • State is kept in-memory behind a `RwLock` and checkpointed by the
//!   service into persistent storage (e.g. Postgres, RocksDB) – that part is
//!   out-of-scope here.
//! • Composer selection follows a simplified Proof-of-Inspiration algorithm:
//!      1. Each staker submits a *VRF proof* for a given round‐seed.
//!      2. The hash output is mapped to `[0, 1)`.  The staker wins if
//!         output / stake_total < staker_weight.
//!      3. Ties are broken deterministically by lowest hash.
//! • A Strategy pattern exposes pluggable `VrfProvider`s so that collectives
//!   can experiment with different curves (Ed25519, BLS, PQ, …) without
//!   recompilation of the other micro-services.

use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, SystemTime},
};

use chrono::{DateTime, Utc};
use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha256};
use tokio::{
    sync::{broadcast, RwLock},
    time,
};

use thiserror::Error;

/// Unique user/staker identifier (e.g. wallet address).
pub type StakerId = String;
/// Result shorthand used throughout the stake logic.
pub type Result<T> = std::result::Result<T, StakingError>;

/// Public event types that can be subscribed to by other micro-services
/// through the event-bus (`broadcast::Sender`).
#[derive(Debug, Clone)]
pub enum StakingEvent {
    StakeAdded {
        staker: StakerId,
        amount: u128,
        new_total: u128,
    },
    StakeWithdrawn {
        staker: StakerId,
        amount: u128,
        new_total: u128,
    },
    ComposerSelected {
        round: u64,
        staker: StakerId,
    },
}

/// Domain errors emitted by staking logic.
#[derive(Error, Debug)]
pub enum StakingError {
    #[error("insufficient stake: requested {requested}, available {available}")]
    InsufficientStake { requested: u128, available: u128 },
    #[error("staker `{0}` is not registered")]
    UnknownStaker(StakerId),
    #[error("VRF verification failed: {0}")]
    VrfFailed(String),
    #[error("no stakers registered")]
    EmptyPool,
    #[error("attempted to withdraw zero tokens")]
    ZeroWithdrawal,
}

/// Represents an individual staking participant.
#[derive(Debug, Clone)]
pub struct Staker {
    pub id: StakerId,
    pub stake: u128,
    pub last_active: DateTime<Utc>,
    pub vrf_pubkey: Vec<u8>, // curve is provider specific
}

impl Staker {
    fn new(id: StakerId, initial: u128, vrf_pubkey: Vec<u8>) -> Self {
        Self {
            id,
            stake: initial,
            last_active: Utc::now(),
            vrf_pubkey,
        }
    }
}

/// Abstraction for a Verifiable Random Function provider.
pub trait VrfProvider: Send + Sync + 'static {
    /// Produces a VRF proof and output hash for `message` using the *private*
    /// part of the provider implementation.
    fn prove(&self, message: &[u8]) -> (Vec<u8> /*proof*/, Vec<u8> /*hash*/);

    /// Verify a proof & hash produced by `prove`.
    fn verify(
        &self,
        public_key: &[u8],
        message: &[u8],
        proof: &[u8],
        hash: &[u8],
    ) -> std::result::Result<(), String>;
}

/// Fallback VRF provider that is *not* secure; meant only for local-dev and
/// CI where cryptography isn’t the focus.  It deterministically hashes the
/// message + static `private_key`.
pub struct Sha256Vrf {
    private_key: Vec<u8>,
}

impl Sha256Vrf {
    pub fn new() -> Self {
        let mut pk = vec![0u8; 32];
        OsRng.fill_bytes(&mut pk);
        Self { private_key: pk }
    }
}

impl VrfProvider for Sha256Vrf {
    fn prove(&self, message: &[u8]) -> (Vec<u8>, Vec<u8>) {
        let mut hasher = Sha256::new();
        hasher.update(&self.private_key);
        hasher.update(message);
        let hash = hasher.finalize().to_vec();
        // `proof` is meaningless here ‑ we return the key for “verification”
        (self.private_key.clone(), hash)
    }

    fn verify(
        &self,
        public_key: &[u8],
        message: &[u8],
        proof: &[u8],
        hash: &[u8],
    ) -> std::result::Result<(), String> {
        if public_key != proof {
            return Err("public key mismatch".into());
        }
        let mut hasher = Sha256::new();
        hasher.update(proof); // same as private_key in this dummy impl
        hasher.update(message);
        let expected = hasher.finalize();
        if expected.as_slice() == hash {
            Ok(())
        } else {
            Err("hash mismatch".into())
        }
    }
}

/// Shared staking state guarded by `RwLock`.
#[derive(Default)]
struct StakePoolInner {
    stakers: HashMap<StakerId, Staker>,
    total_stake: u128,
    current_round: u64,
}

/// Public handle for performing staking operations + composer selection.
#[derive(Clone)]
pub struct StakePool {
    inner: Arc<RwLock<StakePoolInner>>,
    vrf: Arc<dyn VrfProvider>,
    event_tx: broadcast::Sender<StakingEvent>,
}

impl StakePool {
    /// Create a new [`StakePool`] with the provided `VrfProvider`.
    pub fn new(vrf: Arc<dyn VrfProvider>) -> Self {
        let (event_tx, _) = broadcast::channel(256);
        Self {
            inner: Arc::default(),
            vrf,
            event_tx,
        }
    }

    /// Subscribe to [`StakingEvent`]s.
    pub fn subscribe(&self) -> broadcast::Receiver<StakingEvent> {
        self.event_tx.subscribe()
    }

    /// Register a new staker or top-up their existing stake.
    pub async fn add_stake(
        &self,
        staker_id: StakerId,
        vrf_pubkey: Vec<u8>,
        amount: u128,
    ) -> Result<()> {
        let mut inner = self.inner.write().await;

        let entry = inner.stakers.entry(staker_id.clone()).or_insert_with(|| {
            Staker::new(staker_id.clone(), 0, vrf_pubkey.clone())
        });

        entry.stake = entry.stake.saturating_add(amount);
        entry.last_active = Utc::now();
        inner.total_stake = inner.total_stake.saturating_add(amount);

        self.event_tx.send(StakingEvent::StakeAdded {
            staker: staker_id,
            amount,
            new_total: entry.stake,
        }).ok();

        Ok(())
    }

    /// Withdraw stake.  Fails if the caller tries to withdraw more than they have.
    pub async fn withdraw_stake(&self, staker_id: &str, amount: u128) -> Result<()> {
        if amount == 0 {
            return Err(StakingError::ZeroWithdrawal);
        }

        let mut inner = self.inner.write().await;
        let staker = inner
            .stakers
            .get_mut(staker_id)
            .ok_or_else(|| StakingError::UnknownStaker(staker_id.into()))?;

        if staker.stake < amount {
            return Err(StakingError::InsufficientStake {
                requested: amount,
                available: staker.stake,
            });
        }

        staker.stake -= amount;
        staker.last_active = Utc::now();
        inner.total_stake -= amount;

        self.event_tx.send(StakingEvent::StakeWithdrawn {
            staker: staker_id.into(),
            amount,
            new_total: staker.stake,
        }).ok();

        Ok(())
    }

    /// Internal helper to draw a random seed for the next composer round.
    fn next_round_seed() -> [u8; 32] {
        let mut seed = [0u8; 32];
        OsRng.fill_bytes(&mut seed);
        seed
    }

    /// Schedule automatic composer selection every `interval`.
    pub async fn run_composer_election(self: Arc<Self>, interval: Duration) {
        let mut ticker = time::interval(interval);

        loop {
            ticker.tick().await;
            let seed = Self::next_round_seed();
            match self.select_composer(seed).await {
                Ok(Some(winner)) => {
                    tracing::info!(round = self.current_round().await, %winner, "composer selected");
                }
                Ok(None) => {
                    // pool is empty
                }
                Err(e) => tracing::error!("failed to select composer: {e}"),
            };
        }
    }

    /// Return current round number without locking write.
    pub async fn current_round(&self) -> u64 {
        self.inner.read().await.current_round
    }

    /// Execute a single composer election round with the provided seed.
    /// Returns `Ok(Some(staker_id))` on success, `Ok(None)` if pool empty.
    /// State changes (round increment) are committed atomically.
    pub async fn select_composer(&self, seed: [u8; 32]) -> Result<Option<StakerId>> {
        let mut inner = self.inner.write().await;

        if inner.stakers.is_empty() {
            return Ok(None);
        }

        let message = seed; // serialized seed acts as VRF message
        let mut best_candidate: Option<(StakerId, Vec<u8>)> = None;

        for staker in inner.stakers.values() {
            // Build domain-separated message: seed || staker-id
            let mut msg_vec = message.to_vec();
            msg_vec.extend(staker.id.as_bytes());

            // Each candidate derives a VRF output (hash) – prove/verify may
            // happen off-chain in a real system; we shortcut here.
            let (_proof, hash) = self.vrf.prove(&msg_vec);

            // Map first 16 bytes → u128 for uniform comparison
            let mut buf = [0u8; 16];
            buf.copy_from_slice(&hash[..16]);
            let rnd = u128::from_be_bytes(buf);

            // Calculate target: (rnd / 2^128) < (stake / total)
            // Reorder: rnd * total < stake * 2^128
            let left = rnd.saturating_mul(inner.total_stake);
            let right = staker.stake.saturating_mul(u128::MAX);

            let eligible = left < right;
            if eligible {
                // Keep the lowest hash to break ties deterministically
                match &mut best_candidate {
                    None => best_candidate = Some((staker.id.clone(), hash)),
                    Some((_best_id, best_hash)) => {
                        if hash < *best_hash {
                            *best_hash = hash;
                            *_best_id = staker.id.clone();
                        }
                    }
                }
            }
        }

        inner.current_round += 1;

        if let Some((winner, _)) = &best_candidate {
            self.event_tx
                .send(StakingEvent::ComposerSelected {
                    round: inner.current_round,
                    staker: winner.clone(),
                })
                .ok();
        }

        Ok(best_candidate.map(|(id, _)| id))
    }

    /// Utility used primarily by tests & admin dashboards.
    pub async fn snapshot(&self) -> (u128, Vec<Staker>) {
        let inner = self.inner.read().await;
        (inner.total_stake, inner.stakers.values().cloned().collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[tokio::test]
    async fn test_stake_add_withdraw() {
        let pool = StakePool::new(Arc::new(Sha256Vrf::new()));
        pool.add_stake("alice".into(), vec![1, 2, 3], 1_000).await.unwrap();
        pool.add_stake("bob".into(), vec![4, 5, 6], 2_000).await.unwrap();
        let (total, _) = pool.snapshot().await;
        assert_eq!(total, 3_000);

        pool.withdraw_stake("bob", 500).await.unwrap();
        let (total, stakers) = pool.snapshot().await;
        assert_eq!(total, 2_500);

        let bob_stake = stakers.iter().find(|s| s.id == "bob").unwrap().stake;
        assert_eq!(bob_stake, 1_500);
    }

    #[tokio::test]
    async fn test_composer_selection() {
        let pool = StakePool::new(Arc::new(Sha256Vrf::new()));
        // Ensure deterministic test by using static VRF keys
        pool.add_stake("alice".into(), vec![1; 32], 1_000).await.unwrap();
        pool.add_stake("bob".into(), vec![2; 32], 10_000).await.unwrap();

        let seed = [42u8; 32];
        let winner = pool.select_composer(seed).await.unwrap().unwrap();
        assert!(["alice", "bob"].contains(&winner.as_str()));
    }

    #[tokio::test]
    async fn test_event_broadcast() {
        let pool = StakePool::new(Arc::new(Sha256Vrf::new()));
        let mut rx = pool.subscribe();

        pool.add_stake("carol".into(), vec![1; 32], 5_000).await.unwrap();

        let event = rx.recv().await.unwrap();
        if let StakingEvent::StakeAdded { staker, amount, .. } = event {
            assert_eq!(staker, "carol");
            assert_eq!(amount, 5_000);
        } else {
            panic!("unexpected event variant");
        }
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_multiple_rounds_no_panic() {
        let pool = Arc::new(StakePool::new(Arc::new(Sha256Vrf::new())));
        pool.add_stake("dave".into(), vec![9; 32], 15_000).await.unwrap();

        let sp = pool.clone();
        tokio::spawn(async move {
            sp.run_composer_election(Duration::from_millis(200))
                .await;
        });

        // Wait for a few rounds
        time::sleep(Duration::from_secs(1)).await;
        let round = pool.current_round().await;
        assert!(round >= 3);
    }

    #[tokio::test]
    async fn test_unique_event_order() {
        let pool = StakePool::new(Arc::new(Sha256Vrf::new()));

        // subscribe *before* any event
        let mut rx = pool.subscribe();

        pool.add_stake("eve".into(), vec![0; 32], 1_000).await.unwrap();
        pool.withdraw_stake("eve", 200).await.unwrap();

        let mut kinds = HashSet::new();
        for _ in 0..2 {
            let ev = rx.recv().await.unwrap();
            kinds.insert(std::mem::discriminant(&ev));
        }
        assert_eq!(kinds.len(), 2); // received two distinct event types
    }
}
```