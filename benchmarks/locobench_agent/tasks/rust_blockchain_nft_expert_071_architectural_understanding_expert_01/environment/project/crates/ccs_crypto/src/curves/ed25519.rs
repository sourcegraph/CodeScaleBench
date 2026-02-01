```rust
//! Ed25519 cryptographic backend for CanvasChain Symphony
//!
//! The code in this module is ** self-contained ** so that it can be used as a
//! drop–in implementation of the high-level `CryptoScheme` strategy trait
//! exported in `crate::curves::traits`.  
//!
//! Reasons for picking `ed25519-dalek`:
//!   * Pure-Rust implementation with no native dependencies.
//!   * Actively audited and widely used in the ecosystem (Solana, IOTA, etc.).
//!
//! ## TL;DR
//!
//! ```rust
//! use ccs_crypto::curves::ed25519::{Ed25519, CryptoScheme};
//!
//! // Generate a new key-pair
//! let (sk, pk) = Ed25519::generate_keypair(&mut rand::thread_rng()).unwrap();
//!
//! // Sign & verify a message
//! let msg = b"hello CanvasChain";
//! let sig = Ed25519::sign(&sk, msg).unwrap();
//! Ed25519::verify(&pk, msg, &sig).unwrap();
//! ```

#![allow(clippy::module_name_repetitions)]

use core::{fmt, str::FromStr};
use std::sync::Arc;

use ed25519_dalek::{
    self as dalek, Signer, Verifier, KEYPAIR_LENGTH, PUBLIC_KEY_LENGTH, SECRET_KEY_LENGTH,
    SIGNATURE_LENGTH,
};
use rand_core::{CryptoRng, RngCore};
use serde::{de, Deserialize, Deserializer, Serialize, Serializer};
use sha2::{Digest, Sha256};
use thiserror::Error;
use zeroize::{Zeroize, ZeroizeOnDrop};

/// Re-export the public dependencies so downstream crates don’t have to add
/// them explicitly when they only need the high-level API.
pub use ed25519_dalek as dalek_impl;

/// Human-readable address prefix (similar to bech32 HRP or cosmos SDK).
const ADDRESS_PREFIX: &str = "ccs";

/// Convenient alias for the result used by this module.
pub type Result<T, E = CryptoError> = core::result::Result<T, E>;

/// Unified error type for all crypto-related fallible operations.
#[derive(Debug, Error)]
pub enum CryptoError {
    #[error("invalid length: expected {expected} bytes, got {actual}")]
    InvalidLength { expected: usize, actual: usize },

    #[error("ed25519 error: {0}")]
    Dalek(#[from] dalek::SignatureError),

    #[error("serde error: {0}")]
    Serde(#[from] serde_json::Error),

    #[error("base58 error: {0}")]
    Bs58(#[from] bs58::decode::Error),

    #[error("unknown error: {0}")]
    Other(String),
}

/// Strategy trait every curve implementation must satisfy.
///
/// The trait is intentionally object-safe so that multiple curve backends can
/// be selected at runtime (e.g. by CLI flag or network upgrade).
pub trait CryptoScheme: Send + Sync + 'static {
    type PrivateKey: Clone + Send + Sync + ZeroizeOnDrop + fmt::Debug + PartialEq + Eq;
    type PublicKey: Clone + Send + Sync + fmt::Debug + PartialEq + Eq;
    type Signature: Clone + Send + Sync + fmt::Debug + PartialEq + Eq;

    fn generate_keypair<R: RngCore + CryptoRng>(rng: &mut R) -> Result<(Self::PrivateKey, Self::PublicKey)>;

    fn sign(sk: &Self::PrivateKey, msg: &[u8]) -> Result<Self::Signature>;

    fn verify(pk: &Self::PublicKey, msg: &[u8], sig: &Self::Signature) -> Result<()>;

    fn derive_public(sk: &Self::PrivateKey) -> Result<Self::PublicKey>;

    /// Hash & encode the public key into a short, user–friendly address.
    fn address(pk: &Self::PublicKey) -> String;
}

/* -------------------------------------------------------------------------- */
/*                                   Types                                    */
/* -------------------------------------------------------------------------- */

/// Thin wrapper around `dalek::SecretKey` that provides
/// – `ZeroizeOnDrop` to avoid leaking secrets
/// – Serde implementations to exchange keys via JSON / TOML
#[derive(Clone, Zeroize, ZeroizeOnDrop, Eq, PartialEq)]
pub struct Ed25519PrivateKey([u8; SECRET_KEY_LENGTH]);

impl fmt::Debug for Ed25519PrivateKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("Ed25519PrivateKey(<redacted>)")
    }
}

/// Public keys are safe to share; we derive `Copy` for ergonomic APIs such as
/// `fn my_fn(pk: Ed25519PublicKey)`.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct Ed25519PublicKey([u8; PUBLIC_KEY_LENGTH]);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash)]
pub struct Ed25519Signature([u8; SIGNATURE_LENGTH]);

/* -------------------------------------------------------------------------- */
/*                         Type <-> Byte conversions                          */
/* -------------------------------------------------------------------------- */

impl Ed25519PrivateKey {
    pub fn to_bytes(&self) -> [u8; SECRET_KEY_LENGTH] {
        self.0
    }

    pub fn from_bytes(bytes: impl AsRef<[u8]>) -> Result<Self> {
        let slice = bytes.as_ref();
        if slice.len() != SECRET_KEY_LENGTH {
            return Err(CryptoError::InvalidLength {
                expected: SECRET_KEY_LENGTH,
                actual: slice.len(),
            });
        }

        let mut arr = [0u8; SECRET_KEY_LENGTH];
        arr.copy_from_slice(slice);
        Ok(Self(arr))
    }
}

impl Ed25519PublicKey {
    pub fn to_bytes(&self) -> [u8; PUBLIC_KEY_LENGTH] {
        self.0
    }

    pub fn from_bytes(bytes: impl AsRef<[u8]>) -> Result<Self> {
        let slice = bytes.as_ref();
        if slice.len() != PUBLIC_KEY_LENGTH {
            return Err(CryptoError::InvalidLength {
                expected: PUBLIC_KEY_LENGTH,
                actual: slice.len(),
            });
        }

        let mut arr = [0u8; PUBLIC_KEY_LENGTH];
        arr.copy_from_slice(slice);
        Ok(Self(arr))
    }
}

impl Ed25519Signature {
    pub fn to_bytes(&self) -> [u8; SIGNATURE_LENGTH] {
        self.0
    }

    pub fn from_bytes(bytes: impl AsRef<[u8]>) -> Result<Self> {
        let slice = bytes.as_ref();
        if slice.len() != SIGNATURE_LENGTH {
            return Err(CryptoError::InvalidLength {
                expected: SIGNATURE_LENGTH,
                actual: slice.len(),
            });
        }

        let mut arr = [0u8; SIGNATURE_LENGTH];
        arr.copy_from_slice(slice);
        Ok(Self(arr))
    }
}

/* -------------------------------------------------------------------------- */
/*                               Serde support                                */
/* -------------------------------------------------------------------------- */

impl Serialize for Ed25519PrivateKey {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        // Base58 encode — shorter than hex and URL safe.
        serializer.serialize_str(&bs58::encode(self.0).with_check().into_string())
    }
}

impl<'de> Deserialize<'de> for Ed25519PrivateKey {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> core::result::Result<Self, D::Error> {
        let s = String::deserialize(deserializer)?;
        let bytes = bs58::decode(s)
            .with_check(None)
            .into_vec()
            .map_err(de::Error::custom)?;
        Ed25519PrivateKey::from_bytes(bytes).map_err(de::Error::custom)
    }
}

impl Serialize for Ed25519PublicKey {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&bs58::encode(self.0).with_check().into_string())
    }
}

impl<'de> Deserialize<'de> for Ed25519PublicKey {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> core::result::Result<Self, D::Error> {
        let s = String::deserialize(deserializer)?;
        let bytes = bs58::decode(s)
            .with_check(None)
            .into_vec()
            .map_err(de::Error::custom)?;
        Ed25519PublicKey::from_bytes(bytes).map_err(de::Error::custom)
    }
}

impl Serialize for Ed25519Signature {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&hex::encode(self.0))
    }
}

impl<'de> Deserialize<'de> for Ed25519Signature {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> core::result::Result<Self, D::Error> {
        let s = String::deserialize(deserializer)?;
        let bytes = hex::decode(&s).map_err(de::Error::custom)?;
        Ed25519Signature::from_bytes(bytes).map_err(de::Error::custom)
    }
}

/* -------------------------------------------------------------------------- */
/*                             Implementation                                 */
/* -------------------------------------------------------------------------- */

/// The unit struct that implements `CryptoScheme` for Ed25519.
///
/// We wrap the backing Dalek types into our own newtype-style wrappers in order
/// to keep the external surface area stable even if we swap out or upgrade the
/// Dalek crate internally.
#[derive(Clone, Default)]
pub struct Ed25519;

/// Cheap clone because the heavy lifting is done by `Arc`.
pub type DynCryptoScheme = Arc<dyn CryptoScheme<PrivateKey = Ed25519PrivateKey, PublicKey = Ed25519PublicKey, Signature = Ed25519Signature>>;

impl CryptoScheme for Ed25519 {
    type PrivateKey = Ed25519PrivateKey;
    type PublicKey = Ed25519PublicKey;
    type Signature = Ed25519Signature;

    fn generate_keypair<R: RngCore + CryptoRng>(rng: &mut R) -> Result<(Self::PrivateKey, Self::PublicKey)> {
        let mut seed = [0u8; dalek::SECRET_KEY_LENGTH];
        rng.fill_bytes(&mut seed);

        let secret = dalek::SecretKey::from_bytes(&seed)?;
        let public: dalek::PublicKey = (&secret).into();

        Ok((Ed25519PrivateKey(secret.to_bytes()), Ed25519PublicKey(public.to_bytes())))
    }

    fn sign(sk: &Self::PrivateKey, msg: &[u8]) -> Result<Self::Signature> {
        let secret = dalek::SecretKey::from_bytes(&sk.0)?;
        let public: dalek::PublicKey = (&secret).into();
        let keypair = dalek::Keypair { secret, public };

        let sig = keypair.sign(msg);
        Ok(Ed25519Signature(sig.to_bytes()))
    }

    fn verify(pk: &Self::PublicKey, msg: &[u8], sig: &Self::Signature) -> Result<()> {
        let public = dalek::PublicKey::from_bytes(&pk.0)?;
        let sig = dalek::Signature::from_bytes(&sig.0)?;

        public.verify(msg, &sig)?;
        Ok(())
    }

    fn derive_public(sk: &Self::PrivateKey) -> Result<Self::PublicKey> {
        let secret = dalek::SecretKey::from_bytes(&sk.0)?;
        let public: dalek::PublicKey = (&secret).into();
        Ok(Ed25519PublicKey(public.to_bytes()))
    }

    fn address(pk: &Self::PublicKey) -> String {
        // SHA-256 & Base58Check encode
        let digest = Sha256::digest(pk.0);
        // Use first 20 bytes (160-bit) similar to Ethereum addresses
        let mut addr = [0u8; 20];
        addr.copy_from_slice(&digest[..20]);
        format!("{}{}", ADDRESS_PREFIX, bs58::encode(addr).with_check().into_string())
    }
}

/* -------------------------------------------------------------------------- */
/*                               From / Into                                  */
/* -------------------------------------------------------------------------- */

impl From<dalek::SecretKey> for Ed25519PrivateKey {
    fn from(value: dalek::SecretKey) -> Self {
        Self(value.to_bytes())
    }
}

impl TryFrom<Ed25519PrivateKey> for dalek::SecretKey {
    type Error = CryptoError;
    fn try_from(value: Ed25519PrivateKey) -> Result<Self> {
        dalek::SecretKey::from_bytes(&value.0).map_err(Into::into)
    }
}

impl From<dalek::PublicKey> for Ed25519PublicKey {
    fn from(value: dalek::PublicKey) -> Self {
        Self(value.to_bytes())
    }
}

impl TryFrom<Ed25519PublicKey> for dalek::PublicKey {
    type Error = CryptoError;
    fn try_from(value: Ed25519PublicKey) -> Result<Self> {
        dalek::PublicKey::from_bytes(&value.0).map_err(Into::into)
    }
}

impl From<dalek::Signature> for Ed25519Signature {
    fn from(value: dalek::Signature) -> Self {
        Self(value.to_bytes())
    }
}

impl TryFrom<Ed25519Signature> for dalek::Signature {
    type Error = CryptoError;
    fn try_from(value: Ed25519Signature) -> Result<Self> {
        dalek::Signature::from_bytes(&value.0).map_err(Into::into)
    }
}

/* -------------------------------------------------------------------------- */
/*                                   Misc                                     */
/* -------------------------------------------------------------------------- */

impl fmt::Display for Ed25519PublicKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&bs58::encode(self.0).with_check().into_string())
    }
}

impl FromStr for Ed25519PublicKey {
    type Err = CryptoError;
    fn from_str(s: &str) -> Result<Self> {
        let bytes = bs58::decode(s).with_check(None).into_vec()?;
        Self::from_bytes(bytes)
    }
}

/* -------------------------------------------------------------------------- */
/*                                   Tests                                    */
/* -------------------------------------------------------------------------- */

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_sign_verify() {
        let mut rng = rand_core::OsRng;
        let (sk, pk) = Ed25519::generate_keypair(&mut rng).unwrap();
        let msg = b"CanvasChain 🎨";

        let sig = Ed25519::sign(&sk, msg).unwrap();
        Ed25519::verify(&pk, msg, &sig).unwrap();
    }

    #[test]
    fn invalid_signature_fails() {
        let mut rng = rand_core::OsRng;
        let (sk, pk) = Ed25519::generate_keypair(&mut rng).unwrap();

        let sig = Ed25519::sign(&sk, b"message A").unwrap();
        assert!(Ed25519::verify(&pk, b"message B", &sig).is_err());
    }

    #[test]
    fn serde_roundtrip() {
        let mut rng = rand_core::OsRng;
        let (_sk, pk) = Ed25519::generate_keypair(&mut rng).unwrap();

        let json = serde_json::to_string(&pk).unwrap();
        let de: Ed25519PublicKey = serde_json::from_str(&json).unwrap();
        assert_eq!(pk, de);
    }

    #[test]
    fn address_format() {
        let mut rng = rand_core::OsRng;
        let (_sk, pk) = Ed25519::generate_keypair(&mut rng).unwrap();

        let addr = Ed25519::address(&pk);
        assert!(addr.starts_with(super::ADDRESS_PREFIX));
    }
}
```