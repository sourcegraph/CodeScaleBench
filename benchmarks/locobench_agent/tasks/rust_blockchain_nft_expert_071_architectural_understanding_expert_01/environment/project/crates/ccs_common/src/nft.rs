```rust
//! Core NFT domain types and evolution/state-machine logic for the
//! CanvasChain Symphony platform.
//!
//! This module purposefully remains *no_std*-friendly (with an opt-in
//! `std` feature for clients that need heap allocation) so it can be
//! reused inside on-chain WASM smart contracts as well as off-chain
//! micro-services.
//!
//! Key design goals:
//! 1. Multi-layer NFTs with independent ownership & royalty streams.
//! 2. Fine-grained state transitions driven by user interaction,
//!    governance votes, staking incentives and DeFi metrics.
//! 3. Pluggable cryptography via Strategy pattern (`SignatureScheme`).
//!
//! NOTE: Heavy business logic such as VRF computation or signature
//! verification lives in dedicated crates (`ccs_cryptography`, …).
#![cfg_attr(not(feature = "std"), no_std)]

extern crate alloc;

use alloc::{
    string::{String, ToString},
    vec::Vec,
    collections::BTreeMap,
};
use core::{
    fmt::{self, Display},
    time::Duration,
};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// New-type wrapper to avoid mixing addresses with other textual IDs.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct WalletAddress(pub String);

impl Display for WalletAddress {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

/// Token amount in smallest denomination (e.g. wei, gwei, …).
pub type TokenAmount = u128;

/// Percentage represented in basis points (1/100th of a percent).
/// Allowed range: 0..=10_000.
#[derive(
    Copy, Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize,
)]
pub struct BasisPoints(u16);

impl BasisPoints {
    pub const MAX: u16 = 10_000;

    pub fn new(bp: u16) -> Result<Self, NftError> {
        if bp > Self::MAX {
            Err(NftError::InvalidBasisPoints(bp))
        } else {
            Ok(Self(bp))
        }
    }

    pub fn as_u16(self) -> u16 {
        self.0
    }
}

/// Signature strategy interface (Strategy pattern).
/// Implementations live in the `ccs_cryptography` crate.
pub trait SignatureScheme {
    type PublicKey;
    type Signature;

    fn verify(
        pk: &Self::PublicKey,
        msg: &[u8],
        sig: &Self::Signature,
    ) -> bool;
}

/// High-level NFT error enumeration.
#[derive(Debug, thiserror::Error, Serialize, Deserialize)]
pub enum NftError {
    #[error("invalid basis points: {0}")]
    InvalidBasisPoints(u16),

    #[error("layer is frozen and can’t be modified: {0}")]
    LayerFrozen(Uuid),

    #[error("layer not found: {0}")]
    UnknownLayer(Uuid),

    #[error("ownership mismatch: expected {expected}, got {actual}")]
    OwnershipMismatch {
        expected: WalletAddress,
        actual: WalletAddress,
    },

    #[error("invalid state transition from {from:?} to {to:?}")]
    InvalidStateTransition {
        from: LayerState,
        to: LayerState,
    },

    #[error("governance vote failed: {0}")]
    Governance(String),

    #[error("royalty overflow")]
    RoyaltyOverflow,
}

/// Layer category used for rendering, royalties etc.
#[derive(
    Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize,
)]
pub enum NftLayerKind {
    Visual,
    Audio,
    Haptic,
    Metadata,
    Custom(String),
}

/// Finite state machine for a layer’s lifecycle.
#[derive(
    Copy, Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize,
)]
pub enum LayerState {
    Draft,
    Active,
    Frozen,
    Retired,
}

impl LayerState {
    pub fn can_transition(self, next: LayerState) -> bool {
        use LayerState::*;
        matches!(
            (self, next),
            (Draft, Active)
                | (Active, Frozen)
                | (Active, Retired)
                | (Frozen, Retired) // irreversible freeze
        )
    }
}

/// Event that may trigger NFT mutations.
/// This is serialized and sent over the event bus.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum EvolutionEvent {
    /// A wallet interacted with the NFT (likes, remix, …).
    Interaction {
        wallet: WalletAddress,
        payload: alloc::vec::Vec<u8>,
    },

    /// Snapshot of staking position for DeFi incentives.
    Staked {
        wallet: WalletAddress,
        amount: TokenAmount,
        duration: Duration,
    },

    /// Governance vote outcome with yes/no ratio in basis points.
    GovernanceResult {
        proposal_id: Uuid,
        approve_ratio: BasisPoints,
    },
}

/// Single NFT layer with independent ownership & royalties.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct NftLayer {
    pub id: Uuid,
    pub kind: NftLayerKind,
    pub cid: String, // IPFS / Arweave content hash
    pub state: LayerState,
    pub owner: WalletAddress,
    pub royalty_bp: BasisPoints,
    pub created_at: u64,
    pub last_updated: u64,
}

impl NftLayer {
    pub fn freeze(&mut self) -> Result<(), NftError> {
        if self.state == LayerState::Frozen {
            return Ok(());
        }
        if self.state.can_transition(LayerState::Frozen) {
            self.state = LayerState::Frozen;
            Ok(())
        } else {
            Err(NftError::InvalidStateTransition {
                from: self.state,
                to: LayerState::Frozen,
            })
        }
    }

    /// Transfer ownership, enforcing the layer’s frozen status.
    pub fn transfer(
        &mut self,
        from: &WalletAddress,
        to: WalletAddress,
    ) -> Result<(), NftError> {
        if &self.owner != from {
            return Err(NftError::OwnershipMismatch {
                expected: self.owner.clone(),
                actual: from.clone(),
            });
        }

        if self.state == LayerState::Frozen {
            return Err(NftError::LayerFrozen(self.id));
        }

        self.owner = to;
        Ok(())
    }
}

/// Distribution of royalties across multiple stakeholders.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RoyaltySchedule {
    recipients: BTreeMap<WalletAddress, BasisPoints>,
}

impl RoyaltySchedule {
    /// Build a new schedule. The sum of `BasisPoints` must be ≤ 10k.
    pub fn new(
        recipients: BTreeMap<WalletAddress, BasisPoints>,
    ) -> Result<Self, NftError> {
        let total: u32 = recipients
            .values()
            .map(|bp| bp.as_u16() as u32)
            .sum();
        if total > BasisPoints::MAX as u32 {
            return Err(NftError::RoyaltyOverflow);
        }
        Ok(Self { recipients })
    }

    /// Resolve the royalty amount for each recipient given a sale price.
    pub fn split(
        &self,
        sale_price: TokenAmount,
    ) -> BTreeMap<WalletAddress, TokenAmount> {
        self.recipients
            .iter()
            .map(|(addr, bp)| {
                let amount = sale_price * bp.as_u16() as u128
                    / BasisPoints::MAX as u128;
                (addr.clone(), amount)
            })
            .collect()
    }
}

/// Governance parameters per NFT.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GovernancePolicy {
    pub quorum_bp: BasisPoints,
    pub super_majority_bp: BasisPoints,
    pub voting_period: Duration,
}

/// The main multi-layer NFT object.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MultiLayerNft {
    pub id: Uuid,
    pub name: String,
    pub creator: WalletAddress,
    pub layers: BTreeMap<Uuid, NftLayer>,
    pub governance: GovernancePolicy,
    pub royalties: RoyaltySchedule,
}

impl MultiLayerNft {
    /// Builder pattern entry point.
    pub fn builder<S: Into<String>>(
        name: S,
        creator: WalletAddress,
    ) -> NftBuilder {
        NftBuilder::new(name.into(), creator)
    }

    /// Compute a deterministic content digest of all layers (Merkle root
    /// is preferable, but we hash a concatenation for simplicity).
    pub fn digest(&self) -> blake3::Hash {
        let mut hasher = blake3::Hasher::new();
        for layer in self.layers.values() {
            hasher.update(layer.cid.as_bytes());
        }
        hasher.finalize()
    }

    /// Attempt to mutate the NFT based on an external event.
    pub fn evolve(
        &mut self,
        event: EvolutionEvent,
    ) -> Result<(), NftError> {
        match event {
            EvolutionEvent::Interaction { wallet, payload } => {
                self.handle_interaction(wallet, payload)
            }
            EvolutionEvent::Staked {
                wallet,
                amount,
                duration,
            } => self.handle_stake(wallet, amount, duration),
            EvolutionEvent::GovernanceResult {
                proposal_id: _,
                approve_ratio,
            } => self.handle_governance(approve_ratio),
        }
    }

    fn handle_interaction(
        &mut self,
        wallet: WalletAddress,
        _payload: Vec<u8>,
    ) -> Result<(), NftError> {
        // Simple rule: first interaction grants temporary co-ownership
        // (until frozen) of layer[0] (Visual) if not already owned.
        if let Some(first_layer) = self.layers.values_mut().next() {
            if first_layer.state == LayerState::Active
                && first_layer.owner != wallet
            {
                first_layer.owner = wallet;
            }
        }
        Ok(())
    }

    fn handle_stake(
        &mut self,
        _wallet: WalletAddress,
        amount: TokenAmount,
        duration: Duration,
    ) -> Result<(), NftError> {
        // Increase royalty shares proportionally to stake (toy logic).
        let bonus_bp = (amount / 1_000_000_000_000_000_000u128) as u16; // 1 ETH == 10 bp
        let bonus_bp = bonus_bp.min(1000); // cap at +10%
        let adjusted = BasisPoints::new(bonus_bp)?;
        // Add a dummy recipient (treasury) with the bonus share.
        self.royalties.recipients.insert(
            WalletAddress("canvas_treasury".into()),
            adjusted,
        );
        // Re-balance to avoid overflow (leftover goes to creator).
        self.normalize_royalties()?;
        // Freeze if stake duration > 30 days.
        if duration.as_secs() >= 30 * 24 * 3600 {
            for layer in self.layers.values_mut() {
                layer.freeze()?;
            }
        }
        Ok(())
    }

    fn handle_governance(
        &mut self,
        approve_ratio: BasisPoints,
    ) -> Result<(), NftError> {
        if approve_ratio.as_u16() >= self.governance.super_majority_bp.as_u16()
        {
            // Promote all `Draft` layers to `Active`.
            for layer in self.layers.values_mut() {
                if layer.state == LayerState::Draft {
                    layer.state = LayerState::Active;
                }
            }
            Ok(())
        } else {
            Err(NftError::Governance(
                "proposal rejected".to_string(),
            ))
        }
    }

    fn normalize_royalties(&mut self) -> Result<(), NftError> {
        let total: u32 = self
            .royalties
            .recipients
            .values()
            .map(|bp| bp.as_u16() as u32)
            .sum();
        if total > BasisPoints::MAX as u32 {
            return Err(NftError::RoyaltyOverflow);
        }
        Ok(())
    }

    /// Transfer a specific layer to a new owner.
    pub fn transfer_layer(
        &mut self,
        layer_id: Uuid,
        from: &WalletAddress,
        to: WalletAddress,
    ) -> Result<(), NftError> {
        let layer = self
            .layers
            .get_mut(&layer_id)
            .ok_or(NftError::UnknownLayer(layer_id))?;
        layer.transfer(from, to)
    }
}

/// Fluent builder for `MultiLayerNft`.
pub struct NftBuilder {
    id: Uuid,
    name: String,
    creator: WalletAddress,
    layers: BTreeMap<Uuid, NftLayer>,
    governance: Option<GovernancePolicy>,
    royalties: Option<RoyaltySchedule>,
}

impl NftBuilder {
    fn new(name: String, creator: WalletAddress) -> Self {
        Self {
            id: Uuid::new_v4(),
            name,
            creator,
            layers: BTreeMap::new(),
            governance: None,
            royalties: None,
        }
    }

    pub fn add_layer(
        mut self,
        kind: NftLayerKind,
        cid: impl Into<String>,
        initial_state: LayerState,
        royalty_bp: BasisPoints,
    ) -> Self {
        let layer = NftLayer {
            id: Uuid::new_v4(),
            kind,
            cid: cid.into(),
            state: initial_state,
            owner: self.creator.clone(),
            royalty_bp,
            created_at: Self::now(),
            last_updated: Self::now(),
        };
        self.layers.insert(layer.id, layer);
        self
    }

    pub fn governance_policy(
        mut self,
        policy: GovernancePolicy,
    ) -> Self {
        self.governance = Some(policy);
        self
    }

    pub fn royalty_schedule(
        mut self,
        schedule: RoyaltySchedule,
    ) -> Self {
        self.royalties = Some(schedule);
        self
    }

    pub fn build(self) -> Result<MultiLayerNft, NftError> {
        let governance = self.governance.unwrap_or(GovernancePolicy {
            quorum_bp: BasisPoints::new(2_000)?,
            super_majority_bp: BasisPoints::new(6_600)?,
            voting_period: Duration::from_secs(7 * 24 * 3600),
        });

        let royalties = self.royalties.unwrap_or_else(|| {
            let mut map = BTreeMap::new();
            map.insert(self.creator.clone(), BasisPoints(1_000)); // 10%
            RoyaltySchedule { recipients: map }
        });

        Ok(MultiLayerNft {
            id: self.id,
            name: self.name,
            creator: self.creator,
            layers: self.layers,
            governance,
            royalties,
        })
    }

    #[inline(always)]
    fn now() -> u64 {
        // Use UNIX time in seconds. On chain we replace this with
        // block-timestamp to avoid dependence on wall clock.
        #[cfg(feature = "std")]
        {
            use std::time::{SystemTime, UNIX_EPOCH};
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs()
        }
        #[cfg(not(feature = "std"))]
        {
            0
        }
    }
}
```