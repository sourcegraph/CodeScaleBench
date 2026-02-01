```rust
//! Canonical, cross-crate types for the CanvasChain Symphony code-base.
//!
//! This module is **dependency-light** and **stable**, making it safe to be
//! imported by every micro-service, CLI tool and smart-contract runtime.

// ----------------------------------------------------------------------------
// Std & external imports
// ----------------------------------------------------------------------------
use std::{fmt, str::FromStr};

use hex::{FromHex, ToHex};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use uuid::Uuid;

// ----------------------------------------------------------------------------
// Re-exports & simple aliases
// ----------------------------------------------------------------------------

/// Unix timestamp in milliseconds (UTC).
pub type Timestamp = i64;
/// On-chain block height.
pub type BlockNumber = u64;
/// 128-bit balance type—enough for 1e29 units at 18 decimals.
pub type Balance = u128;

/// Result alias pre-filled with [`CcsCommonError`].
pub type Result<T, E = CcsCommonError> = std::result::Result<T, E>;

// ----------------------------------------------------------------------------
// Error handling
// ----------------------------------------------------------------------------

/// Error type shared by helpers contained in this crate.
///
/// NB: the enum is kept deliberately small; specialised subsystems should
/// create their own error enums and simply `#[from]` this one where needed.
#[derive(Debug, Error)]
pub enum CcsCommonError {
    /// Malformed address or ID strings.
    #[error("Malformed data: {0}")]
    Malformed(String),

    /// Hex decoding failure.
    #[error(transparent)]
    Hex(#[from] hex::FromHexError),

    /// UUID parsing failure.
    #[error(transparent)]
    Uuid(#[from] uuid::Error),

    /// Catch-all variant for misc. string messages.
    #[error("{0}")]
    Other(String),
}

// ----------------------------------------------------------------------------
// Primitive new-types
// ----------------------------------------------------------------------------

/// A 32-byte account address.
///
/// Display/parse as lowercase, “0x”-prefixed hex string.
#[derive(
    Copy, Clone, Default, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize,
)]
pub struct Address([u8; 32]);

impl Address {
    pub const LEN: usize = 32;

    #[inline]
    pub fn new(bytes: [u8; 32]) -> Self {
        Self(bytes)
    }

    #[inline]
    pub fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }

    #[inline]
    pub fn into_inner(self) -> [u8; 32] {
        self.0
    }
}

impl fmt::Display for Address {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "0x{}", self.0.encode_hex::<String>())
    }
}

impl fmt::Debug for Address {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, f)
    }
}

impl FromStr for Address {
    type Err = CcsCommonError;

    fn from_str(s: &str) -> Result<Self> {
        let raw = s.strip_prefix("0x").unwrap_or(s).to_ascii_lowercase();

        if raw.len() != Self::LEN * 2 {
            return Err(CcsCommonError::Malformed(format!(
                "address length mismatch (expected {} hex chars, got {})",
                Self::LEN * 2,
                raw.len()
            )));
        }

        let bytes = <[u8; Self::LEN]>::from_hex(raw)?;
        Ok(Self(bytes))
    }
}

/// A globally unique 64-bit identifier for NFTs and fungible token classes.
///
/// By convention:
///   - upper 16 bits encode a micro-service namespace
///   - lower 48 bits are an incrementing counter
#[derive(
    Copy, Clone, Debug, Default, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize,
)]
pub struct TokenId(pub u64);

impl fmt::Display for TokenId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "#{:016X}", self.0)
    }
}

impl From<u64> for TokenId {
    fn from(v: u64) -> Self {
        TokenId(v)
    }
}

impl From<TokenId> for u64 {
    fn from(v: TokenId) -> Self {
        v.0
    }
}

/// 256-bit content hash (CIDv1 raw-binary multihash).
///
/// Serialised as [base58btc] to remain URL-safe and human-friendly.
#[derive(Clone, Debug, Hash, PartialEq, Eq, Serialize, Deserialize)]
pub struct ContentHash(
    #[serde(
        serialize_with = "crate::types::helpers::serialize_b58",
        deserialize_with = "crate::types::helpers::deserialize_b58"
    )]
    pub [u8; 32],
);

impl ContentHash {
    pub fn new(bytes: [u8; 32]) -> Self {
        Self(bytes)
    }

    pub fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }
}

impl fmt::Display for ContentHash {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&bs58::encode(self.0).into_string())
    }
}

impl FromStr for ContentHash {
    type Err = CcsCommonError;

    fn from_str(s: &str) -> Result<Self> {
        let decoded = bs58::decode(s)
            .into_vec()
            .map_err(|e| CcsCommonError::Malformed(format!("base58 decode: {e}")))?;

        if decoded.len() != 32 {
            return Err(CcsCommonError::Malformed(format!(
                "hash length mismatch (expected 32 bytes, got {})",
                decoded.len()
            )));
        }

        let mut bytes = [0u8; 32];
        bytes.copy_from_slice(&decoded);
        Ok(Self(bytes))
    }
}

/// Unique identifier grouping a set of on-chain operations that form a single
/// artistic “movement”.
#[derive(
    Copy, Clone, Debug, Hash, PartialEq, Eq, Ord, PartialOrd, Serialize, Deserialize,
)]
pub struct MovementId(Uuid);

impl MovementId {
    #[inline]
    pub fn new() -> Self {
        MovementId(Uuid::new_v4())
    }

    #[inline]
    pub fn as_uuid(&self) -> &Uuid {
        &self.0
    }
}

impl fmt::Display for MovementId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}

impl FromStr for MovementId {
    type Err = CcsCommonError;

    fn from_str(s: &str) -> Result<Self> {
        Ok(MovementId(Uuid::parse_str(s)?))
    }
}

// ----------------------------------------------------------------------------
// Enum types
// ----------------------------------------------------------------------------

/// CanvasChain runtime networks.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(tag = "type", content = "custom_id")]
#[non_exhaustive]
pub enum Network {
    Mainnet,
    Testnet,
    Devnet,
    Custom(u32),
}

impl fmt::Display for Network {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Network::Mainnet => f.write_str("mainnet"),
            Network::Testnet => f.write_str("testnet"),
            Network::Devnet => f.write_str("devnet"),
            Network::Custom(id) => write!(f, "custom-{}", id),
        }
    }
}

/// Signature curve algorithms supported by the Strategy pattern.
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum CurveAlgo {
    Ed25519,
    Sr25519,
    Secp256k1,
    Bls12381,
    PostQuantumDilithium,
}

impl fmt::Display for CurveAlgo {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        use CurveAlgo::*;
        let name = match self {
            Ed25519 => "ed25519",
            Sr25519 => "sr25519",
            Secp256k1 => "secp256k1",
            Bls12381 => "bls12381",
            PostQuantumDilithium => "pq-dilithium",
        };
        f.write_str(name)
    }
}

// ----------------------------------------------------------------------------
// Serde helpers (kept private; do *not* export)
// ----------------------------------------------------------------------------

pub mod helpers {
    use super::*;
    use serde::{de::Error as _, Deserializer, Serializer};

    pub fn serialize_b58<S>(bytes: &[u8; 32], ser: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        ser.serialize_str(&bs58::encode(bytes).into_string())
    }

    pub fn deserialize_b58<'de, D>(de: D) -> Result<[u8; 32], D::Error>
    where
        D: Deserializer<'de>,
    {
        let s = String::deserialize(de)?;
        let vec = bs58::decode(&s).into_vec().map_err(D::Error::custom)?;
        if vec.len() != 32 {
            return Err(D::Error::custom(format!(
                "invalid length: expected 32 bytes, got {}",
                vec.len()
            )));
        }
        let mut bytes = [0u8; 32];
        bytes.copy_from_slice(&vec);
        Ok(bytes)
    }
}
```