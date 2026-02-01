```rust
//! CanvasChain Symphony – CCS Consensus Crate
//!
//! The `ccs_consensus` crate provides the core logic for the Proof-of-Inspiration
//! consensus algorithm.  The algorithm combines *Proof-of-Stake* weighted
//! elections with a Verifiable Random Function (VRF) to pseudo-randomly choose a
//! “composer node’’ that is allowed to append the next **art-movement block** to
//! the chain.
//!
//! High-level flow
//! ---------------
//! 1. At the beginning of every epoch each validator signs the previous block
//!    hash with its secret key, yielding a VRF output + proof.
//! 2. The output is mapped to a 128-bit integer and divided by the validator’s
//!    effective stake.  The *lowest* score wins.
//! 3. Peers verify the proof and score locally.  Upon super-majority agreement,
//!    an event is broadcast on the CanvasChain event bus.
//!
//! Design patterns demonstrated
//! ----------------------------
//! • Strategy pattern for pluggable cryptographic curves (`Ed25519` / `BLS12-381`)
//! • State-machine pattern for the consensus engine
//! • Observer pattern to publish events to the global bus
//! • Error handling with `thiserror`
//!
//! The code purposefully avoids hard-coding a networking layer; instead an
//! `EventSink` trait is provided so that each micro-service can wire its own
//! transport (e.g. gRPC, NATS, Kafka).

#![deny(missing_docs)]
#![forbid(unsafe_code)]

mod crypto;
mod error;
mod state;

pub use crypto::{Ed25519Provider, VrfProvider};
pub use error::ConsensusError;
pub use state::{Candidate, ConsensusConfig, ConsensusEngine, ConsensusEvent, NodeId, Stake};

use async_trait::async_trait;

/// An async sink that can be used to publish [`ConsensusEvent`]s.
///
/// The *observer pattern* is implemented via this trait.  Implementors may
/// forward events to Kafka, NATS, gRPC streams—whatever the application needs.
#[async_trait]
pub trait EventSink: Send + Sync + 'static {
    /// Push an event into the sink.
    async fn emit(&self, event: ConsensusEvent) -> Result<(), ConsensusError>;
}

#[cfg(test)]
mod tests {
    use super::*;
    use crypto::Ed25519Provider;
    use rand_chacha::ChaCha20Rng;
    use rand_core::SeedableRng;
    use std::collections::HashMap;
    use tokio::runtime::Runtime;

    struct VecSink(tokio::sync::Mutex<Vec<ConsensusEvent>>);

    #[async_trait::async_trait]
    impl EventSink for VecSink {
        async fn emit(&self, event: ConsensusEvent) -> Result<(), ConsensusError> {
            self.0.lock().await.push(event);
            Ok(())
        }
    }

    #[test]
    fn selects_winner_consistently() {
        let mut rt = Runtime::new().unwrap();
        rt.block_on(async {
            let cfg = ConsensusConfig {
                epoch: 1,
                min_stake: 1,
            };

            let mut rng = ChaCha20Rng::from_seed([7u8; 32]);

            // ── Create three dummy validators ───────────────────────────────────
            let mut stakes = HashMap::new();
            for i in 0..3_u8 {
                stakes.insert(NodeId::from([i; 32]), Stake::new(100));
            }

            let sink = VecSink(tokio::sync::Mutex::new(Vec::new()));
            let provider = Ed25519Provider::new(&mut rng);
            let mut engine = ConsensusEngine::new(cfg, provider, sink);

            // Register validators
            for (id, stake) in &stakes {
                engine.register_validator(*id, *stake).unwrap();
            }

            // ── Run selection ────────────────────────────────────────────────────
            engine.select_composer(b"prev_block_hash").await.unwrap();

            // Ensure an event was emitted
            let events = engine
                .event_sink()
                .downcast_ref::<VecSink>()
                .unwrap()
                .0
                .lock()
                .await
                .clone();

            assert_eq!(events.len(), 1);
            if let ConsensusEvent::ComposerSelected { candidate, .. } = &events[0] {
                assert!(stakes.contains_key(&candidate.node_id));
            } else {
                panic!("unexpected event");
            }
        });
    }
}
```

```rust
// src/crypto.rs
//! Cryptography utilities and abstractions for VRF providers.

use crate::error::ConsensusError;
use ed25519_dalek::{
    ed25519::signature::Signer, ed25519::signature::Verifier, Keypair, Signature, PUBLIC_KEY_LENGTH,
    SECRET_KEY_LENGTH,
};
use rand_core::{CryptoRng, RngCore};
use sha2::{Digest, Sha512};

/// Result of a VRF proof.
#[derive(Debug, Clone)]
pub struct VrfProof {
    /// Raw VRF output bytes (the hash of the signature).
    pub output: [u8; 32],
    /// Signature used as proof.
    pub proof: Signature,
}

/// Abstract VRF provider (strategy pattern).
pub trait VrfProvider: Clone + Send + Sync + 'static {
    /// Generate a VRF proof given a message.
    fn prove(&self, msg: &[u8]) -> Result<VrfProof, ConsensusError>;

    /// Verify a VRF proof for a public key and message.
    fn verify(
        &self,
        public_key: &[u8],
        msg: &[u8],
        proof: &VrfProof,
    ) -> Result<bool, ConsensusError>;
}

/// Ed25519-based implementation of [`VrfProvider`].
#[derive(Clone)]
pub struct Ed25519Provider {
    keypair: Keypair,
}

impl Ed25519Provider {
    /// Construct a new provider using a random keypair.
    pub fn new<R>(rng: &mut R) -> Self
    where
        R: CryptoRng + RngCore,
    {
        Self {
            keypair: Keypair::generate(rng),
        }
    }

    /// Returns the public key bytes.
    pub fn public_key_bytes(&self) -> [u8; PUBLIC_KEY_LENGTH] {
        self.keypair.public.to_bytes()
    }
}

impl VrfProvider for Ed25519Provider {
    fn prove(&self, msg: &[u8]) -> Result<VrfProof, ConsensusError> {
        let signature = self.keypair.sign(msg);
        let mut hasher = Sha512::default();
        hasher.update(signature.to_bytes());
        let digest = hasher.finalize();
        let mut output = [0u8; 32];
        output.copy_from_slice(&digest[..32]);

        Ok(VrfProof {
            output,
            proof: signature,
        })
    }

    fn verify(
        &self,
        public_key: &[u8],
        msg: &[u8],
        proof: &VrfProof,
    ) -> Result<bool, ConsensusError> {
        if public_key.len() != PUBLIC_KEY_LENGTH {
            return Err(ConsensusError::InvalidPublicKey);
        }
        let pk = ed25519_dalek::PublicKey::from_bytes(public_key)?;
        pk.verify(msg, &proof.proof)
            .map(|_| true)
            .map_err(ConsensusError::from)
    }
}
```

```rust
// src/error.rs
//! Common error types for the consensus engine.

use ed25519_dalek::ed25519::signature::Error as SigError;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ConsensusError {
    /// Validator already registered.
    #[error("validator already registered")]
    DuplicateValidator,

    /// Unknown validator.
    #[error("unknown validator")]
    UnknownValidator,

    /// The stake provided is below the configured minimum.
    #[error("stake below minimum threshold")]
    InsufficientStake,

    /// Failed to verify VRF proof.
    #[error("VRF verification failed")]
    VrfVerificationFailed,

    /// Invalid or malformed public key.
    #[error("invalid public key")]
    InvalidPublicKey,

    /// Wrapper for cryptographic errors.
    #[error("crypto error: {0}")]
    Crypto(#[from] SigError),

    /// Generic IO / transport error.
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    /// Catch-all.
    #[error("other error: {0}")]
    Other(String),
}
```

```rust
// src/state.rs
//! Consensus state machine and business logic.

use crate::crypto::{VrfProof, VrfProvider};
use crate::error::ConsensusError;
use crate::EventSink;
use async_trait::async_trait;
use rand_core::RngCore;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{Mutex, RwLock};

/// Unique identifier for a validator node (32-byte public key hash).
#[derive(Debug, Copy, Clone, Hash, PartialEq, Eq, Serialize, Deserialize)]
pub struct NodeId([u8; 32]);

impl From<[u8; 32]> for NodeId {
    fn from(b: [u8; 32]) -> Self {
        Self(b)
    }
}

/// Amount of stake bonded by a validator.
#[derive(Debug, Copy, Clone, Serialize, Deserialize)]
pub struct Stake(u128);

impl Stake {
    pub fn new(amount: u128) -> Self {
        Stake(amount)
    }

    pub fn as_u128(&self) -> u128 {
        self.0
    }
}

/// Static consensus configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConsensusConfig {
    /// Number of blocks per epoch.
    pub epoch: u64,
    /// Minimum stake required to become a validator.
    pub min_stake: u128,
}

/// Candidate produced during composer selection.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Candidate {
    /// ID of the validator.
    pub node_id: NodeId,
    /// VRF proof data.
    pub vrf: VrfProof,
    /// Computed score used for winner determination.
    pub score: u128,
}

/// Events emitted by [`ConsensusEngine`].
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ConsensusEvent {
    /// A composer has been selected for the next block.
    ComposerSelected {
        /// The epoch number.
        epoch: u64,
        /// Winning candidate.
        candidate: Candidate,
    },
}

/// Main consensus state machine.
///
/// The struct is parameterised over a [`VrfProvider`] to allow different
/// cryptographic back-ends (strategy pattern).
pub struct ConsensusEngine<P, S>
where
    P: VrfProvider,
    S: EventSink,
{
    cfg: ConsensusConfig,
    vrf: P,
    epoch: RwLock<u64>,
    validators: RwLock<HashMap<NodeId, Stake>>,
    rng: Mutex<rand_chacha::ChaCha20Rng>,
    sink: Arc<S>,
}

impl<P, S> ConsensusEngine<P, S>
where
    P: VrfProvider,
    S: EventSink,
{
    /// Construct a new engine.
    pub fn new<R>(
        cfg: ConsensusConfig,
        vrf: P,
        sink: S,
        mut rng: R,
    ) -> Self
    where
        R: RngCore,
    {
        use rand_core::SeedableRng;
        let seed: [u8; 32] = (0..32).map(|_| rng.next_u32() as u8).collect::<Vec<_>>()[..]
            .try_into()
            .unwrap_or([0u8; 32]);
        let rng = rand_chacha::ChaCha20Rng::from_seed(seed);
        Self {
            cfg,
            vrf,
            epoch: RwLock::new(0),
            validators: RwLock::new(HashMap::new()),
            rng: Mutex::new(rng),
            sink: Arc::new(sink),
        }
    }

    /// Borrow immutable reference to the event sink (for test introspection).
    pub fn event_sink(&self) -> Arc<S> {
        self.sink.clone()
    }

    /// Register or update a validator’s stake.
    pub fn register_validator(
        &self,
        node_id: NodeId,
        stake: Stake,
    ) -> Result<(), ConsensusError> {
        if stake.as_u128() < self.cfg.min_stake {
            return Err(ConsensusError::InsufficientStake);
        }
        let mut map = self.validators.blocking_write();
        map.insert(node_id, stake);
        Ok(())
    }

    /// Remove a validator from the set.
    pub fn unregister_validator(&self, node_id: &NodeId) -> Result<(), ConsensusError> {
        let mut map = self.validators.blocking_write();
        map.remove(node_id).ok_or(ConsensusError::UnknownValidator)?;
        Ok(())
    }

    /// Select the composer for the next block and broadcast an event.
    pub async fn select_composer(&self, prev_block_hash: &[u8]) -> Result<(), ConsensusError> {
        let validators = self.validators.read().await;
        let epoch = *self.epoch.read().await + 1;
        if validators.is_empty() {
            return Err(ConsensusError::Other("no validators".into()));
        }

        // ── Each validator produces a VRF candidate ────────────────────────
        let mut best: Option<Candidate> = None;
        for (node_id, stake) in validators.iter() {
            let proof = self.vrf.prove(prev_block_hash)?;
            let score = Self::score(&proof, stake.as_u128());
            let cand = Candidate {
                node_id: *node_id,
                vrf: proof,
                score,
            };

            if best
                .as_ref()
                .map(|c| cand.score < c.score)
                .unwrap_or(true)
            {
                best = Some(cand);
            }
        }

        let winner = best.expect("best candidate exists; qed");

        // ── Sanity-check proof for the winner ──────────────────────────────
        let ok = self.vrf.verify(
            &winner.node_id.0,
            prev_block_hash,
            &winner.vrf,
        )?;
        if !ok {
            return Err(ConsensusError::VrfVerificationFailed);
        }

        // ── Update epoch and broadcast event ───────────────────────────────
        {
            let mut e = self.epoch.write().await;
            *e = epoch;
        }

        let event = ConsensusEvent::ComposerSelected { epoch, candidate: winner };
        self.sink.emit(event).await?;

        Ok(())
    }

    /// Deterministically derive a numeric score from VRF output + stake.
    ///
    /// Lower is better.
    fn score(vrf: &VrfProof, stake: u128) -> u128 {
        let mut arr = [0u8; 16]; // 128-bit
        arr.copy_from_slice(&vrf.output[..16]);
        let raw = u128::from_le_bytes(arr);
        raw / stake.max(1) // avoid div-by-zero though stake >= 1 in practice
    }
}

#[async_trait]
impl<P, S> EventSink for ConsensusEngine<P, S>
where
    P: VrfProvider,
    S: EventSink,
{
    async fn emit(&self, event: ConsensusEvent) -> Result<(), ConsensusError> {
        self.sink.emit(event).await
    }
}
```

