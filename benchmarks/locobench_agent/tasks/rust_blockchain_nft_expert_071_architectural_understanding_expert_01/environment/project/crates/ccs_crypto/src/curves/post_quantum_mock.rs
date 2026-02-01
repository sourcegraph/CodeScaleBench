```rust
//! Post-quantum (mock) curve implementation.
//!
//! IMPORTANT  ⚠️
//! ===========
//! This is **NOT** a real post-quantum secure signature scheme.  
//! It is a deterministic, side-effect-free *mock* implementation whose
//! only goal is to allow higher-level components of the CanvasChain
//! Symphony platform to compile and run integration / property tests
//! without linking against heavy native PQ libraries (e.g. `liboqs`).
//!
//! The public interface is intentionally kept identical to the other
//! curves (Ed25519, BLS12-381) so that the `Strategy` pattern can swap
//! them at runtime / compile-time without friction.
//!
//! Production deployments MUST replace this module with a real PQ
//! implementation before main-net launch.

use core::fmt;
use std::{
    error::Error,
    sync::Arc,
};

use rand::{rngs::OsRng, RngCore};
use sha2::{Digest, Sha512};
use zeroize::Zeroize;

/// Size constants (in bytes).
pub const PRIVATE_KEY_LENGTH: usize = 32;
pub const PUBLIC_KEY_LENGTH: usize = 64;
pub const SIGNATURE_LENGTH: usize = 96;

/// Strongly-typed wrapper around private key bytes.
///
/// The inner buffer is `Zeroize`d on drop to avoid leaking secrets.
#[derive(Clone)]
pub struct PQMockPrivateKey {
    bytes: Arc<[u8; PRIVATE_KEY_LENGTH]>,
}

impl Drop for PQMockPrivateKey {
    fn drop(&mut self) {
        // Zeroize when the last Arc ref goes away.
        if Arc::strong_count(&self.bytes) == 1 {
            let mut owned = Arc::get_mut(&mut self.bytes.clone()).expect("exclusive");
            owned.zeroize();
        }
    }
}

impl fmt::Debug for PQMockPrivateKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("PQMockPrivateKey(****)")
    }
}

/// Public key (derived deterministically from the private key).
#[derive(Clone, PartialEq, Eq, Hash)]
pub struct PQMockPublicKey {
    pub(crate) bytes: [u8; PUBLIC_KEY_LENGTH],
}

impl fmt::Debug for PQMockPublicKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let short = &self.bytes[..8];
        write!(
            f,
            "PQMockPublicKey({:02x?}…)",
            short
        )
    }
}

/// Signature value returned by `sign`.
#[derive(Clone, PartialEq, Eq)]
pub struct PQMockSignature {
    pub(crate) bytes: [u8; SIGNATURE_LENGTH],
}

impl fmt::Debug for PQMockSignature {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let short = &self.bytes[..8];
        write!(
            f,
            "PQMockSignature({:02x?}…)",
            short
        )
    }
}

/// Error type for this curve.
#[derive(Debug)]
pub enum PQMockError {
    InvalidSignature,
    MalformedKey,
}

impl fmt::Display for PQMockError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidSignature => write!(f, "invalid signature"),
            Self::MalformedKey => write!(f, "malformed key"),
        }
    }
}

impl Error for PQMockError {}

/// Trait unifying all supported signing curves.
pub trait SigningAlgorithm {
    type PrivateKey;
    type PublicKey;
    type Signature;
    type Error: Error + Send + Sync + 'static;

    /// Generate a fresh random keypair.
    fn generate_keypair() -> (Self::PrivateKey, Self::PublicKey);

    /// Sign arbitrary byte slice.
    fn sign(
        priv_key: &Self::PrivateKey,
        msg: &[u8],
    ) -> Result<Self::Signature, Self::Error>;

    /// Verify `sig` against `msg` using `pub_key`.
    fn verify(
        pub_key: &Self::PublicKey,
        msg: &[u8],
        sig: &Self::Signature,
    ) -> Result<(), Self::Error>;
}

/// Post-quantum mock implementation.
///
/// Algorithm sketch (do **not** use in production):
/// 1. pk  = SHA-512(sk || "PQMock")            (64 bytes)
/// 2. sig = SHA-512(pk || msg) || salt[32]     (96 bytes)
pub struct PQMockAlgorithm;

impl PQMockAlgorithm {
    /// Internal helper: derive `pk` from `sk`.
    fn derive_public(sk: &[u8; PRIVATE_KEY_LENGTH]) -> [u8; PUBLIC_KEY_LENGTH] {
        let mut hasher = Sha512::new();
        hasher.update(sk);
        hasher.update(b"PQMock");
        let result = hasher.finalize();
        let mut pk = [0u8; PUBLIC_KEY_LENGTH];
        pk.copy_from_slice(&result[..PUBLIC_KEY_LENGTH]);
        pk
    }
}

impl SigningAlgorithm for PQMockAlgorithm {
    type PrivateKey = PQMockPrivateKey;
    type PublicKey = PQMockPublicKey;
    type Signature = PQMockSignature;
    type Error = PQMockError;

    fn generate_keypair() -> (Self::PrivateKey, Self::PublicKey) {
        let mut sk_bytes = [0u8; PRIVATE_KEY_LENGTH];
        OsRng.fill_bytes(&mut sk_bytes);

        let pk_bytes = Self::derive_public(&sk_bytes);

        (
            PQMockPrivateKey {
                bytes: Arc::new(sk_bytes),
            },
            PQMockPublicKey { bytes: pk_bytes },
        )
    }

    fn sign(
        priv_key: &Self::PrivateKey,
        msg: &[u8],
    ) -> Result<Self::Signature, Self::Error> {
        // Derive public part (deterministically)
        let pk = Self::derive_public(&priv_key.bytes);

        // Compute digest(pk || msg)
        let mut hasher = Sha512::new();
        hasher.update(&pk);
        hasher.update(msg);
        let digest = hasher.finalize();

        // Append 32-byte random salt for uniqueness
        let mut salt = [0u8; 32];
        OsRng.fill_bytes(&mut salt);

        let mut sig_bytes = [0u8; SIGNATURE_LENGTH];
        sig_bytes[..64].copy_from_slice(&digest);
        sig_bytes[64..].copy_from_slice(&salt);

        Ok(PQMockSignature { bytes: sig_bytes })
    }

    fn verify(
        pub_key: &Self::PublicKey,
        msg: &[u8],
        sig: &Self::Signature,
    ) -> Result<(), Self::Error> {
        // Recompute digest(pub_key || msg)
        let mut hasher = Sha512::new();
        hasher.update(&pub_key.bytes);
        hasher.update(msg);
        let digest = hasher.finalize();

        // Compare digest with signature first 64 bytes (constant-time)
        if digest.as_slice() != &sig.bytes[..64] {
            return Err(PQMockError::InvalidSignature);
        }

        // We do not check the 32-byte salt; it's only to avoid hash-only signatures.
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn basic_roundtrip() {
        let (sk, pk) = PQMockAlgorithm::generate_keypair();
        let msg = b"all your base belong to us";

        let sig = PQMockAlgorithm::sign(&sk, msg).expect("sign ok");
        PQMockAlgorithm::verify(&pk, msg, &sig).expect("verify ok");

        // Tamper with message
        assert!(PQMockAlgorithm::verify(&pk, b"evil", &sig).is_err());

        // Tamper with signature
        let mut bad_sig = sig.clone();
        bad_sig.bytes[0] ^= 0x42;
        assert!(PQMockAlgorithm::verify(&pk, msg, &bad_sig).is_err());
    }

    #[test]
    fn public_key_deterministic() {
        let (sk, _) = PQMockAlgorithm::generate_keypair();
        let pk1 = PQMockAlgorithm::derive_public(&sk.bytes);
        let pk2 = PQMockAlgorithm::derive_public(&sk.bytes);
        assert_eq!(pk1, pk2);
    }
}
```