```rust
//! CanvasChain Symphony – Core protocol types and helpers
//!
//! This crate contains the canonical, prost-based protobuf definitions that are
//! shared between every CanvasChain Symphony (CCS) micro-service.  
//!
//! The code purposefully keeps the public API **small and stable** while still
//! allowing each service to share rich data structures without having to
//! re-compile the entire workspace every time a field is added. To achieve
//! this we follow a versioned, additive-only approach (fields are never
//! removed—only soft-deprecated).

// Lints & crate features ------------------------------------------------------------------------
#![forbid(unsafe_code)]
#![deny(missing_docs)]
#![deny(unused_crate_dependencies)]

use prost::Message;

/// Wire-level version of the protobuf schema.
///
/// Increment the value **only** if a wire-incompatible change has been
/// introduced (e.g. changing field numbers or types). Adding new optional
/// fields is backwards compatible and *does not* require a version bump.
pub const PROTO_VERSION: u32 = 1;

// =================================================================================================
// Generic helper traits
// =================================================================================================

/// Blanket helper trait that simplifies encode/decode round-trips.
///
/// Any protobuf [`Message`] that also implements [`Default`] automatically
/// gains these convenience methods. The implementation lives at the bottom of
/// this file to avoid compiler confusion around coherence rules.
pub trait ProtoSerializable: Message + Default {
    /// Encode `self` into a freshly allocated `Vec<u8>`.
    fn encode_to_vec(&self) -> Vec<u8>;

    /// Decode `Self` from a raw byte slice.
    fn decode_from_slice(bytes: &[u8]) -> Result<Self, prost::DecodeError>
    where
        Self: Sized;
}

// =================================================================================================
// Staking & Composer election
// =================================================================================================

pub mod staking {
    //! Messages used by the staking micro-service as well as the
    //! *Proof-of-Inspiration* composer-election flow.

    use super::*;

    /// Client request for staking CCS tokens.
    #[derive(Clone, PartialEq, Message)]
    pub struct StakeRequest {
        /// Wallet that performs the stake.
        #[prost(string, tag = "1")]
        pub wallet: String,

        /// Amount in atomic units (18 decimals)
        #[prost(uint64, tag = "2")]
        pub amount: u64,
    }

    /// Acknowledgement emitted by the staking service.
    #[derive(Clone, PartialEq, Message)]
    pub struct StakeResponse {
        /// `true` if the stake was accepted.  
        /// `false` if it failed (see [`reason`]).
        #[prost(bool, tag = "1")]
        pub accepted: bool,

        /// Human-readable error (e.g. “insufficient balance”).
        #[prost(string, tag = "2")]
        pub reason: String,
    }

    /// Trigger a distributed VRF draw for the currently active epoch.
    #[derive(Clone, PartialEq, Message)]
    pub struct ElectRequest {
        /// Epoch number for which the election should occur.
        #[prost(uint64, tag = "1")]
        pub epoch: u64,
    }

    /// Result of the *Proof-of-Inspiration* VRF draw.
    #[derive(Clone, PartialEq, Message)]
    pub struct ElectResult {
        /// Wallet that won the composer slot.
        #[prost(string, tag = "1")]
        pub composer_wallet: String,

        /// Binary VRF proof which validators can verify on-chain.
        #[prost(bytes = "vec", tag = "2")]
        pub vrf_proof: Vec<u8>,
    }
}

// =================================================================================================
// Multilayer NFTs
// =================================================================================================

pub mod nft {
    //! Core primitives for multilayer NFTs.
    //!
    //! The structs live in their own module because multiple services
    //! (minting, remixing, marketplace, royalty streaming …) interact with
    //! them.

    use super::*;

    /// Single expressive layer of a multilayer NFT (e.g. “bassline”, “brush
    /// strokes”, “metadata”).
    #[derive(Clone, PartialEq, Message)]
    pub struct NftLayer {
        /// Human readable descriptor (“drums”, “particles”, “haptics”…)
        #[prost(string, tag = "1")]
        pub name: String,

        /// Raw, possibly compressed payload (WAV, GLSL, WASM, …)
        #[prost(bytes = "vec", tag = "2")]
        pub payload: Vec<u8>,

        /// MIME type of the payload so UIs know how to interpret it.
        #[prost(string, tag = "3")]
        pub content_type: String,
    }

    /// Full NFT containing any number of individual layers.
    #[derive(Clone, PartialEq, Message)]
    pub struct NftArtifact {
        /// Unique identifier (could be a hash or incremental id).
        #[prost(string, tag = "1")]
        pub id: String,

        /// Dynamic set of layers.
        #[prost(message, repeated, tag = "2")]
        pub layers: Vec<NftLayer>,

        /// RFC 3339 timestamp (seconds since epoch).
        #[prost(uint64, tag = "3")]
        pub created_at: u64,

        /// Optional timestamp of the *last* on-chain update.
        #[prost(uint64, optional, tag = "4")]
        pub updated_at: Option<u64>,
    }

    /// Encapsulates a delta that should be applied to an existing NFT.
    /// This is what the *composer node* broadcasts on chain.
    #[derive(Clone, PartialEq, Message)]
    pub struct NftMutation {
        /// ID of the target NFT.
        #[prost(string, tag = "1")]
        pub nft_id: String,

        /// Index of the layer that will be mutated.
        #[prost(uint32, tag = "2")]
        pub layer_index: u32,

        /// New payload that should replace the layer’s current data.
        #[prost(bytes = "vec", tag = "3")]
        pub new_payload: Vec<u8>,

        /// VRF proof that the composer node was legitimately elected.
        #[prost(bytes = "vec", tag = "4")]
        pub vrf_proof: Vec<u8>,
    }
}

// =================================================================================================
// Governance
// =================================================================================================

pub mod governance {
    //! Protobufs for the on-chain governance micro-service.

    use super::*;

    /// A binary on-chain governance vote.
    #[derive(Clone, PartialEq, Message)]
    pub struct GovernanceVote {
        /// Hash of the proposal that is being voted on.
        #[prost(string, tag = "1")]
        pub proposal_hash: String,

        /// Wallet that casts the vote.
        #[prost(string, tag = "2")]
        pub voter_wallet: String,

        /// `true` == Yay, `false` == Nay
        #[prost(bool, tag = "3")]
        pub approve: bool,

        /// Weight of the vote in atomic units.
        #[prost(uint64, tag = "4")]
        pub weight: u64,
    }
}

// =================================================================================================
// Blanket impls
// =================================================================================================

impl<T> ProtoSerializable for T
where
    T: Message + Default,
{
    #[inline]
    fn encode_to_vec(&self) -> Vec<u8> {
        let mut buf = Vec::with_capacity(self.encoded_len());
        // Should never fail for in-memory buffers.
        self.encode(&mut buf)
            .expect("encoding protobuf message into Vec<u8> failed");
        buf
    }

    #[inline]
    fn decode_from_slice(bytes: &[u8]) -> Result<Self, prost::DecodeError> {
        Self::decode(bytes)
    }
}

// =================================================================================================
// Tests
// =================================================================================================

#[cfg(test)]
mod tests {
    use super::{nft::NftArtifact, ProtoSerializable};

    #[test]
    fn roundtrip_serialization() {
        let nft = NftArtifact {
            id: "artifact:001".into(),
            layers: vec![],
            created_at: 1_685_000_000,
            updated_at: None,
        };

        let bytes = nft.encode_to_vec();
        let decoded = NftArtifact::decode_from_slice(&bytes).unwrap();

        assert_eq!(decoded.id, "artifact:001");
        assert_eq!(decoded.created_at, 1_685_000_000);
    }
}
```