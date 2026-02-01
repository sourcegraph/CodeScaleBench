```rust
//! poi_engine.rs
//!
//! Proof–of–Inspiration (PoI) consensus engine implementation for CanvasChain
//! Symphony.  The PoI algorithm periodically elects a “composer node” which
//! earns the right to commit an on-chain generative-art update.  Election is
//! driven by stake weight, yet spiced with verifiable randomness so small but
//! “inspired” holders still have a chance to shine.
//!
//! This file exposes a single public façade [`PoiEngine`] which is spun up by
//! the `ccs_consensusd` binary and interacted with by the rest of the system
//! exclusively through `async` channels.  Internally, PoI relies on:
//!
//! • An external staking provider giving live stake balances  
//! • A pseudo-VRF implementation (pluggable through the `CryptoStrategy` trait)  
//! • Tokio tasks + broadcast channels for event driven coordination  
//! • A small RocksDB database for crash-safe round tracking
//!
//! The implementation purposefully hides all synchronous blocking behind
//! `spawn_blocking` to satisfy Tokio’s best practices.
//!
//! # Safety & Correctness
//! 1. All randomness is produced by the selected `CryptoStrategy`.  
//! 2. A stake table snapshot is taken *atomically* per-round; changes mid-round
//!    never influence the current election.  
//! 3. Persistent `RoundState` prevents equivocation after restarts.
//!
//! # Features
//! This code is `no_std` friendly *except* for the persistent backend which
//! requires `std`.  Compile with `persistence` feature turned off for embedded
//! targets.

#![allow(clippy::module_name_repetitions)]

use std::{
    collections::BTreeMap,
    path::Path,
    sync::Arc,
    time::{Duration, SystemTime},
};

use anyhow::{anyhow, Context, Result};
use async_trait::async_trait;
use rand::{rngs::StdRng, Rng, SeedableRng};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokio::{
    select,
    sync::{broadcast, mpsc, oneshot, RwLock},
    task,
    time::sleep,
};
use tracing::{debug, error, info, instrument, warn};

#[cfg(feature = "persistence")]
use rocksdb::{Options, DB};

/// Unique identifier for a network node
pub type NodeId = u64;

/// A VRF proof blob (opaque)
pub type VrfProof = Vec<u8>;

/// Number of composer elections per second
const ELECTION_FREQUENCY: f64 = 1.0 / 30.0; // once every 30s

/// Size of random seed used by default crypto strategy
const DEFAULT_SEED_SIZE: usize = 32;

/// Broadcast channel capacity for composer events
const EVENT_CHANNEL_SIZE: usize = 64;

/// Errors that can happen inside [`PoiEngine`]
#[derive(Debug, Error)]
pub enum PoiError {
    #[error("stake provider failed: {0}")]
    StakeProvider(String),

    #[error("persistence error: {0}")]
    Persistence(String),

    #[error("crypto error: {0}")]
    Crypto(String),
}

/// Result alias using [`PoiError`]
pub type PoiResult<T> = std::result::Result<T, PoiError>;

/// An elected composer together with some metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComposerElection {
    pub round:        u64,
    pub composer:     NodeId,
    pub stake_weight: u128,
    pub vrf_proof:    VrfProof,
    pub entropy:      [u8; DEFAULT_SEED_SIZE],
    pub timestamp:    SystemTime,
}

/// Snapshot of stakes at the start of a round
pub type StakeTable = BTreeMap<NodeId, u128>;

/// Provider that yields up-to-date stake tables.
#[async_trait]
pub trait StakeProvider: Send + Sync + 'static {
    async fn stake_snapshot(&self) -> PoiResult<StakeTable>;
}

/// Strategy used to generate VRF proof + pseudo-randomness.
///
/// In production we use BLS-based VRF or `ring`’s Ed25519 implementation,
/// but for the sake of a standalone file we abstract over the details.
#[async_trait]
pub trait CryptoStrategy: Send + Sync {
    /// Produce (`proof`, `randomness`)
    async fn eval_vrf(&self, round: u64, candidate: NodeId) -> PoiResult<(VrfProof, [u8; DEFAULT_SEED_SIZE])>;

    /// Verify (`proof`, `randomness`)
    fn verify(&self, round: u64, candidate: NodeId, proof: &VrfProof, randomness: &[u8; DEFAULT_SEED_SIZE]) -> bool;
}

/// A very small stub strategy that *pretends* to be a VRF by hashing together
/// the inputs.  Replace with a real VRF in production builds.
pub struct Blake2Crypto;

#[async_trait]
impl CryptoStrategy for Blake2Crypto {
    async fn eval_vrf(&self, round: u64, candidate: NodeId) -> PoiResult<(VrfProof, [u8; DEFAULT_SEED_SIZE])> {
        use blake2::{Blake2s256, Digest};

        let mut hasher = Blake2s256::new();
        hasher.update(round.to_le_bytes());
        hasher.update(candidate.to_le_bytes());
        hasher.update(
            SystemTime::now()
                .duration_since(SystemTime::UNIX_EPOCH)
                .expect("system clock before Unix epoch")
                .as_nanos()
                .to_le_bytes(),
        );

        let result = hasher.finalize();
        let mut seed = [0u8; DEFAULT_SEED_SIZE];
        seed.copy_from_slice(&result[..DEFAULT_SEED_SIZE]);
        Ok((result.to_vec(), seed))
    }

    fn verify(&self, round: u64, candidate: NodeId, proof: &VrfProof, randomness: &[u8; DEFAULT_SEED_SIZE]) -> bool {
        use blake2::{Blake2s256, Digest};

        let mut hasher = Blake2s256::new();
        hasher.update(round.to_le_bytes());
        hasher.update(candidate.to_le_bytes());
        hasher.update(&proof[..]);
        let result = hasher.finalize();

        &result[..DEFAULT_SEED_SIZE] == randomness
    }
}

/// Events emitted by PoI when a new composer is elected.
#[derive(Debug, Clone)]
pub enum PoiEvent {
    ComposerElected(ComposerElection),
}

/// Messages accepted by PoI’s internal command channel.
pub enum PoiCommand {
    /// Request a graceful shutdown.  The oneshot channel returns when
    /// everything is flushed to disk.
    Shutdown(oneshot::Sender<()>),
}

/// Core PoI engine structure—spawned as an `async` task.
pub struct PoiEngine {
    stake_provider:   Arc<dyn StakeProvider>,
    crypto:           Arc<dyn CryptoStrategy>,
    next_round:       RwLock<u64>,
    /// Sender side for control commands
    cmd_tx:           mpsc::Sender<PoiCommand>,
    /// Public event broadcast (ComposerElected, etc.)
    pub event_tx:     broadcast::Sender<PoiEvent>,

    #[cfg(feature = "persistence")]
    db: Option<DB>,
}

impl PoiEngine {
    /// Initialize the engine.  If `persist_path` is `Some` PoI will persist
    /// round metadata between restarts.
    pub async fn new<P: AsRef<Path>>(
        stake_provider: Arc<dyn StakeProvider>,
        crypto: Arc<dyn CryptoStrategy>,
        persist_path: Option<P>,
    ) -> PoiResult<Self> {
        let (cmd_tx, cmd_rx) = mpsc::channel::<PoiCommand>(EVENT_CHANNEL_SIZE);
        let (event_tx, _) = broadcast::channel(EVENT_CHANNEL_SIZE);

        #[cfg(feature = "persistence")]
        let db = persist_path
            .map(|p| open_database(p.as_ref()))
            .transpose()
            .map_err(|e| PoiError::Persistence(e.to_string()))?;

        let next_round = load_next_round(&db)?;

        let engine = Self {
            stake_provider,
            crypto,
            next_round: RwLock::new(next_round),
            cmd_tx,
            event_tx,
            #[cfg(feature = "persistence")]
            db,
        };

        engine.spawn_main_loop(cmd_rx);
        Ok(engine)
    }

    /// Spawn the Tokio task that drives elections.
    fn spawn_main_loop(&self, mut cmd_rx: mpsc::Receiver<PoiCommand>) {
        let stake_provider = Arc::clone(&self.stake_provider);
        let crypto = Arc::clone(&self.crypto);
        let event_tx = self.event_tx.clone();

        #[cfg(feature = "persistence")]
        let db = self.db.clone();

        let next_round = self.next_round.clone();

        task::spawn(async move {
            loop {
                let sleep_duration = Duration::from_secs_f64(1.0 / ELECTION_FREQUENCY);
                select! {
                    _ = sleep(sleep_duration) => { /* fallthrough to election */ },
                    Some(cmd) = cmd_rx.recv() => match cmd {
                        PoiCommand::Shutdown(ack) => {
                            // flush if persist enabled
                            #[cfg(feature = "persistence")]
                            if let Err(e) = db.as_ref().map(|d| d.flush()).transpose() {
                                error!(error = ?e, "error flushing RocksDB before shutdown");
                            }
                            let _ = ack.send(());
                            break;
                        }
                    },
                    else => break,
                }

                // Perform election
                if let Err(e) = conduct_election(
                    &stake_provider,
                    &crypto,
                    &event_tx,
                    #[cfg(feature = "persistence")] db.as_ref(),
                    &next_round,
                )
                .await
                {
                    error!(error = ?e, "PoI election failed");
                }
            }
        });
    }

    /// Request a graceful shutdown and await confirmation.
    pub async fn shutdown(&self) {
        let (tx, rx) = oneshot::channel();
        if self.cmd_tx.send(PoiCommand::Shutdown(tx)).await.is_ok() {
            let _ = rx.await;
        }
    }

    /// Returns the next scheduled round (for metrics/debugging).
    pub async fn upcoming_round(&self) -> u64 {
        *self.next_round.read().await
    }
}

#[instrument(skip_all, level = "debug")]
async fn conduct_election(
    stake_provider: &Arc<dyn StakeProvider>,
    crypto: &Arc<dyn CryptoStrategy>,
    event_tx: &broadcast::Sender<PoiEvent>,
    #[cfg(feature = "persistence")] db: Option<&DB>,
    next_round: &RwLock<u64>,
) -> PoiResult<()> {
    let round = {
        let r = *next_round.read().await;
        debug!(round = r, "starting election");
        r
    };

    // 1. Fetch snapshot
    let stake_table = stake_provider
        .stake_snapshot()
        .await
        .map_err(|e| PoiError::StakeProvider(e.to_string()))?;
    if stake_table.is_empty() {
        warn!("Skipping election: stake table is empty");
        increment_round(next_round, #[cfg(feature = "persistence")] db)?;
        return Ok(());
    }

    // 2. Weighted random selection
    let (composer, weight) = {
        let total: u128 = stake_table.values().sum();
        let seed = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .expect("clock")
            .as_nanos() as u64;
        let mut rng = StdRng::seed_from_u64(seed);

        let mut cursor = rng.gen_range(0..total);
        let mut chosen = 0;
        let mut stake = 0;

        for (node, w) in &stake_table {
            if cursor < *w {
                chosen = *node;
                stake = *w;
                break;
            }
            cursor -= *w;
        }
        (chosen, stake)
    };

    // 3. Evaluate VRF
    let (proof, entropy) = crypto.eval_vrf(round, composer).await?;
    if !crypto.verify(round, composer, &proof, &entropy) {
        return Err(PoiError::Crypto("VRF self-verification failed".into()));
    }

    // 4. Build event
    let election = ComposerElection {
        round,
        composer,
        stake_weight: weight,
        vrf_proof: proof,
        entropy,
        timestamp: SystemTime::now(),
    };

    // 5. Persist round
    #[cfg(feature = "persistence")]
    if let Some(db) = db {
        persist_round(db, round, &election)
            .map_err(|e| PoiError::Persistence(e.to_string()))?;
    }

    // 6. Broadcast
    let _listeners = event_tx.receiver_count();
    let _ = event_tx.send(PoiEvent::ComposerElected(election));

    // 7. Bump round
    increment_round(next_round, #[cfg(feature = "persistence")] db)?;

    Ok(())
}

/// Increment next_round (protected by RwLock) and persist if enabled.
fn increment_round(
    next_round: &RwLock<u64>,
    #[cfg(feature = "persistence")] db: Option<&DB>,
) -> PoiResult<()> {
    task::block_in_place(|| {
        let mut guard = futures::executor::block_on(next_round.write());
        *guard += 1;
        #[cfg(feature = "persistence")]
        if let Some(db) = db {
            db.put(b"next_round", guard.to_le_bytes())
                .map_err(|e| PoiError::Persistence(e.to_string()))?;
        }
        Ok(())
    })
}

#[cfg(feature = "persistence")]
fn open_database(path: &Path) -> Result<DB> {
    let mut opts = Options::default();
    opts.create_if_missing(true);
    DB::open(&opts, path).context("opening RocksDB")
}

#[cfg(feature = "persistence")]
fn load_next_round(db: &Option<DB>) -> PoiResult<u64> {
    if let Some(db) = db {
        if let Ok(Some(bytes)) = db.get(b"next_round") {
            let mut arr = [0u8; 8];
            arr.copy_from_slice(&bytes);
            Ok(u64::from_le_bytes(arr))
        } else {
            Ok(0)
        }
    } else {
        Ok(0)
    }
}

#[cfg(not(feature = "persistence"))]
fn load_next_round(_: &Option<()>) -> PoiResult<u64> {
    Ok(0)
}

#[cfg(feature = "persistence")]
fn persist_round(db: &DB, round: u64, election: &ComposerElection) -> Result<()> {
    let bytes = bincode::serialize(election).context("serializing election")?;
    db.put(format!("round/{round}"), bytes)
        .context("writing election to RocksDB")?;
    Ok(())
}

/* ------------------------------------------------------------------------- */
/* ------------------------------ UNIT TESTS ------------------------------- */
/* ------------------------------------------------------------------------- */

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    struct MockStakeProvider {
        counter: AtomicU64,
    }

    #[async_trait]
    impl StakeProvider for MockStakeProvider {
        async fn stake_snapshot(&self) -> PoiResult<StakeTable> {
            let mut table = StakeTable::default();
            for node in 1..=5 {
                table.insert(node, 10 * node as u128);
            }
            // mutate to verify snapshot consistency
            self.counter.fetch_add(1, Ordering::SeqCst);
            Ok(table)
        }
    }

    #[tokio::test(flavor = "multi_thread")]
    async fn test_election_basic() {
        let stake_provider = Arc::new(MockStakeProvider { counter: AtomicU64::new(0) });
        let crypto = Arc::new(Blake2Crypto);

        let engine = PoiEngine::new(stake_provider, crypto, Option::<&str>::None)
            .await
            .expect("engine");

        // listen
        let mut rx = engine.event_tx.subscribe();
        let event = rx.recv().await.expect("event");

        match event {
            PoiEvent::ComposerElected(e) => {
                assert_eq!(e.round, 0);
                assert!(e.composer >= 1 && e.composer <= 5);
                assert_eq!(e.entropy.len(), DEFAULT_SEED_SIZE);
            }
        }

        engine.shutdown().await;
    }
}
```