```rust
//! services/node_service/src/consensus_handler.rs
//!
//! ConsensusHandler orchestrates CanvasChain Symphony’s custom
//! Proof-of-Inspiration consensus algorithm.  The handler listens
//! to the global async event bus for `SlotTick`s emitted by the
//! scheduler service.  At every slot the handler:
//!   1. Retrieves the node’s current stake.
//!   2. Generates a VRF output & proof (simulated with Ed25519).
//!   3. Computes a weight-adjusted threshold to decide leadership.
//!   4. If elected “Composer”, produces a `ComposeProposal` and
//!      publishes it back onto the bus for validation.
//!
//! The module purposefully hides the heavy cryptography behind a
//! `VrfProvider` strategy so alternative curves (BLS, PQ, …) can be
//! swapped without recompilation—fulfilling the Symphony’s
//! `Strategy_Pattern` mandate.

use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use async_trait::async_trait;
use ed25519_dalek::{Keypair, PublicKey, Signature, Signer};
use rand::rngs::OsRng;
use thiserror::Error;
use tokio::{
    select,
    sync::{broadcast, mpsc, oneshot, RwLock},
    task::JoinHandle,
    time,
};

use crate::contracts::CanvasBlock; // Provided by `smart_contracts` feature.
use crate::events::{
    BusEvent,
    BusEvent::{ComposeProposal, NewBlock, SlotTick, StakeChanged},
    EventBus,
};

/// The ratio between maximum possible VRF output and 100 % probability.
/// Used for leadership-selection thresholding.
const VRF_MAX: u128 = u128::MAX;

/// All consensus-related errors emitted by the [`ConsensusHandler`].
#[derive(Debug, Error)]
pub enum ConsensusError {
    #[error("event bus closed")]
    BusClosed,
    #[error("stake information unavailable for node")]
    StakeMissing,
    #[error("internal channel dropped")]
    ChannelDropped,
    #[error("I/O: {0}")]
    Io(#[from] std::io::Error),
    #[error("cryptography error: {0}")]
    Crypto(#[from] ed25519_dalek::SignatureError),
}

/// Runtime configuration for the consensus engine.
#[derive(Debug, Clone)]
pub struct ConsensusConfig {
    /// Duration of a slot (i.e., leadership evaluation period).
    pub slot_duration: Duration,
    /// Minimum required stake to be considered for leadership.
    pub min_stake: u64,
}

/// Trait representing a pluggable VRF provider.
///
/// Implementations can fallback to BLS or a post-quantum scheme
/// without affecting the rest of the system.
#[async_trait]
pub trait VrfProvider: Send + Sync {
    /// Generates a (pseudo-)random VRF output & cryptographic proof
    /// bound to `slot` and `public_key`.
    async fn prove(&self, slot: u64, public_key: &PublicKey) -> (u128, Vec<u8>);
}

/// Default Ed25519-backed VRF provider (simulation only).
pub struct Ed25519Vrf {
    keypair: Keypair,
}

impl Ed25519Vrf {
    pub fn new(keypair: Keypair) -> Self {
        Self { keypair }
    }
}

#[async_trait]
impl VrfProvider for Ed25519Vrf {
    async fn prove(&self, slot: u64, public_key: &PublicKey) -> (u128, Vec<u8>) {
        // NOTE: This is NOT a real VRF.  We derive randomness from
        // a signature over (slot || pk) solely for demo purposes.
        let mut msg = slot.to_le_bytes().to_vec();
        msg.extend_from_slice(public_key.as_bytes());
        let signature: Signature = self.keypair.sign(&msg);
        let output = blake3::hash(signature.as_ref()).into();
        (output, signature.to_bytes().to_vec())
    }
}

/// In-memory view into chain state relevant to consensus.
#[derive(Debug, Default)]
struct ConsensusState {
    /// `PublicKey` → staked tokens (μART)
    stake_table: HashMap<PublicKey, u64>,
    /// Latest accepted block height.
    last_block_height: u64,
}

type SharedState = Arc<RwLock<ConsensusState>>;

/// High-level async consensus engine.
pub struct ConsensusHandler {
    /// Node identity keypair.
    keypair: Keypair,
    /// Service configuration.
    cfg: ConsensusConfig,
    /// Shared atomic state.
    state: SharedState,
    /// Event bus sender for publishing new events.
    bus_tx: broadcast::Sender<BusEvent>,
    /// Dedicated subscription for consuming events.
    bus_rx: broadcast::Receiver<BusEvent>,
    /// VRF provider (strategy pattern).
    vrf: Arc<dyn VrfProvider>,
}

impl ConsensusHandler {
    /// Instantiate and spawn the consensus task, returning its
    /// [`JoinHandle`].  Dropping the handle will not stop the task;
    /// that’s governed by the event bus.
    pub fn spawn(
        cfg: ConsensusConfig,
        keypair: Keypair,
        bus: &EventBus,
    ) -> JoinHandle<Result<(), ConsensusError>> {
        let state = Arc::new(RwLock::new(ConsensusState::default()));
        let vrf = Arc::new(Ed25519Vrf::new(keypair.clone())) as Arc<dyn VrfProvider>;
        let (bus_tx, bus_rx) = (bus.sender(), bus.subscribe());

        let handler = Self {
            keypair,
            cfg,
            state,
            bus_tx,
            bus_rx,
            vrf,
        };

        tokio::spawn(async move { handler.run().await })
    }

    /// Core event loop.
    async fn run(mut self) -> Result<(), ConsensusError> {
        let mut ticker = time::interval(self.cfg.slot_duration);

        loop {
            select! {
                _ = ticker.tick() => {
                    // Emit synthetic SlotTick so other services stay deterministic.
                    let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
                    let slot = now.as_secs() / self.cfg.slot_duration.as_secs();
                    self.bus_tx.send(SlotTick(slot)).map_err(|_| ConsensusError::BusClosed)?;
                },

                // Consume events from the global bus.
                result = self.bus_rx.recv() => {
                    let evt = result.map_err(|_| ConsensusError::BusClosed)?;
                    self.handle_event(evt).await?;
                }
            }
        }
    }

    async fn handle_event(&mut self, evt: BusEvent) -> Result<(), ConsensusError> {
        match evt {
            SlotTick(slot) => self.attempt_leadership(slot).await?,
            NewBlock(block) => self.apply_new_block(block).await?,
            StakeChanged(pk, amount) => {
                self.state.write().await.stake_table.insert(pk, amount);
            }
            _ => { /* ignore other events */ }
        }
        Ok(())
    }

    /// Decides whether the current node is elected leader for `slot`.
    async fn attempt_leadership(&self, slot: u64) -> Result<(), ConsensusError> {
        let pk = self.keypair.public;
        let stake = {
            let state = self.state.read().await;
            *state.stake_table.get(&pk).unwrap_or(&0)
        };

        // Not enough skin in the game → skip.
        if stake < self.cfg.min_stake {
            return Ok(());
        }

        // Get VRF output & proof.
        let (vrf_out, vrf_proof) = self.vrf.prove(slot, &pk).await;

        // Convert stake to probability weight.
        let total_stake: u64 = {
            let state = self.state.read().await;
            state.stake_table.values().copied().sum()
        };

        // In case of genesis / testing.
        if total_stake == 0 {
            return Ok(());
        }

        let weight_ratio = stake as f64 / total_stake as f64;
        let threshold = (VRF_MAX as f64 * weight_ratio) as u128;

        if vrf_out <= threshold {
            // 🎉 Node is elected. Craft a ComposeProposal.
            let proposal = ComposeProposalPayload {
                composer: pk,
                slot,
                vrf_proof,
            };
            self.bus_tx.send(ComposeProposal(proposal)).map_err(|_| ConsensusError::BusClosed)?;
        }

        Ok(())
    }

    async fn apply_new_block(&self, block: CanvasBlock) -> Result<(), ConsensusError> {
        let mut state = self.state.write().await;
        if block.header.height > state.last_block_height {
            state.last_block_height = block.header.height;
        }
        Ok(())
    }
}

/* -------------------------------------------------------------------------- */
/* ------------------------- Event Bus Data Types --------------------------- */
/* -------------------------------------------------------------------------- */

/// Payload emitted when a node believes it is the slot leader.
#[derive(Debug, Clone)]
pub struct ComposeProposalPayload {
    pub composer: PublicKey,
    pub slot: u64,
    pub vrf_proof: Vec<u8>,
}

/// Events routed through the global broadcast bus.
///
/// NOTE: The exhaustive list is declared in a central `events` crate.  A
/// small subset is re-exported here so `consensus_handler.rs` compiles
/// cleanly when tested in isolation.
#[derive(Debug, Clone)]
pub enum BusEvent {
    /// Produced by the scheduler every N seconds.
    SlotTick(u64),
    /// Another service submitted a new block.
    NewBlock(CanvasBlock),
    /// Stake table update (`PublicKey`, new_balance).
    StakeChanged(PublicKey, u64),
    /// Node claims leadership and proposes to compose.
    ComposeProposal(ComposeProposalPayload),
}

/// Thin wrapper around Tokio broadcast channels.
/// Other microservices rely on the same interface.
#[derive(Clone)]
pub struct EventBus {
    tx: broadcast::Sender<BusEvent>,
}

impl EventBus {
    pub fn new(buffer: usize) -> Self {
        let (tx, _) = broadcast::channel(buffer);
        Self { tx }
    }

    pub fn sender(&self) -> broadcast::Sender<BusEvent> {
        self.tx.clone()
    }

    pub fn subscribe(&self) -> broadcast::Receiver<BusEvent> {
        self.tx.subscribe()
    }
}

/* -------------------------------------------------------------------------- */
/* --------------------------------- Tests ---------------------------------- */
/* -------------------------------------------------------------------------- */

#[cfg(test)]
mod tests {
    use super::*;
    use rand::rngs::OsRng;

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn node_with_stake_can_be_selected() {
        let keypair = Keypair::generate(&mut OsRng);
        let bus = EventBus::new(16);

        // Give the node plenty of stake so the probability is high.
        let stake_evt = StakeChanged(keypair.public, 1_000_000);
        bus.sender().send(stake_evt).unwrap();

        let cfg = ConsensusConfig {
            slot_duration: Duration::from_millis(200),
            min_stake: 1,
        };

        let _handle = ConsensusHandler::spawn(cfg, keypair.clone(), &bus);

        // Wait a few slots, listening for ComposeProposal.
        let mut rx = bus.subscribe();
        let mut won = false;

        let timeout = time::sleep(Duration::from_secs(5));
        tokio::pin!(timeout);

        loop {
            select! {
                Ok(evt) = rx.recv() => {
                    if let ComposeProposal(payload) = evt {
                        if payload.composer == keypair.public {
                            won = true;
                            break;
                        }
                    }
                }
                _ = &mut timeout => break,
            }
        }

        assert!(won, "node failed to win leadership within timeframe");
    }
}
```