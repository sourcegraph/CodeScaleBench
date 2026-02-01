```rust
//! CanvasChain Symphony – Crypto Strategy Layer
//!
//! This crate exposes a thin yet powerful abstraction over several signature
//! schemes that may be hot–swapped at runtime through the `Strategy` design
//! pattern.  All CanvasChain micro-services depend exclusively on the
//! high-level `SignatureScheme` trait, never on individual back-ends.  This
//! enables experimental collectives to compile their own chain with an exotic
//! curve without patching the remaining code base.
//!
//! The initial implementation ships with two production-ready schemes:
//!   • Ed25519  – blazingly fast, widely battle-tested
//!   • BLS12-381 – aggregate-friendly, used for consensus messages
//!
//! A post-quantum placeholder is available for future work.  Each back-end is
//! feature-gated, so node operators may disable what they do not need.
//!
//! ```text
//!  +---------------+
//!  |  Application  |  <- gRPC, REST, WASM, etc.
//!  +---------------+
//!          |
//!          v
//!  +---------------------+
//!  |  SignatureScheme<T> |  <- Strategy trait (this crate)
//!  +---------------------+
//!      /            \
//!     v              v
//! +---------+   +---------+
//! | Ed25519 |   |  BLS   |
//! +---------+   +---------+
//! ```
//!
//! # Feature flags
//!
//!   • `ed25519`   (default) – enable Ed25519 back-end  
//!   • `bls12_381`           – enable BLS12-381 back-end
//!
//! ```bash
//! # Example: only BLS
//! cargo build --no-default-features --features bls12_381
//! ```

#![deny(clippy::all, missing_docs, unsafe_code)]
#![forbid(unsafe_code)]

use std::sync::Arc;

use rand_core::{CryptoRng, RngCore};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use zeroize::Zeroize;

/// Alias used across the project for a heap-allocated, thread-safe scheme.
pub type DynScheme = Arc<dyn SignatureScheme + Send + Sync + 'static>;

/// Enumeration of all signature schemes recognised by CanvasChain.
#[derive(Debug, Copy, Clone, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SchemeType {
    /// Ed25519 – RFC-8032
    Ed25519,
    /// BLS12-381 – IETF draft-irtf-cfrg-bls-signatures-05
    #[cfg(feature = "bls12_381")]
    Bls12381,
    /// Placeholder for PQ
    #[cfg(feature = "pq")]
    PostQuantum,
}

impl std::fmt::Display for SchemeType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SchemeType::Ed25519 => write!(f, "ed25519"),
            #[cfg(feature = "bls12_381")]
            SchemeType::Bls12381 => write!(f, "bls12_381"),
            #[cfg(feature = "pq")]
            SchemeType::PostQuantum => write!(f, "post_quantum"),
        }
    }
}

/// High-level cryptographic failures propagated to callers.
#[derive(Debug, Error)]
pub enum CryptoError {
    /// The requested scheme is not available in the current build.
    #[error("signature scheme `{0}` is not supported in this build")]
    UnsupportedScheme(SchemeType),
    /// Malformed key material.
    #[error("invalid key data – {0}")]
    InvalidKey(&'static str),
    /// Malformed signature or failed verification.
    #[error("signature verification failed")]
    VerificationFailed,
    /// Underlying crypto back-end raised an unrecoverable error.
    #[error("crypto backend error – {0}")]
    Backend(&'static str),
    /// Entropy source failed.
    #[error("could not access secure RNG – {0}")]
    Rng(&'static str),
}

/// Trait implemented by every supported signature scheme.
///
/// The associated types are required to be (de)serialisable because key material
/// will be persisted in encrypted form to disk and frequently transmitted over
/// the network (e.g. consensus votes, marketplace orders).  `Zeroize` ensures
/// that secrets are wiped from memory as soon as the last reference goes out
/// of scope.
pub trait SignatureScheme {
    /// Public key type – may be compressed or raw, depending on back-end.
    type PublicKey: Clone
        + Send
        + Sync
        + Serialize
        + for<'de> Deserialize<'de>
        + std::fmt::Debug
        + Eq
        + PartialEq
        + 'static;
    /// Secret key or keypair type.
    type SecretKey: Clone
        + Send
        + Sync
        + Serialize
        + for<'de> Deserialize<'de>
        + std::fmt::Debug
        + Zeroize
        + 'static;
    /// Binary signature.
    type Signature: Clone
        + Send
        + Sync
        + Serialize
        + for<'de> Deserialize<'de>
        + std::fmt::Debug
        + Eq
        + PartialEq
        + 'static;

    /// Returns the identifier of this scheme.
    fn scheme(&self) -> SchemeType;

    /// Generates a fresh keypair.  The caller may pass its own CSPRNG
    /// implementation (useful in deterministic tests) or rely on `/dev/urandom`.
    fn generate<R: RngCore + CryptoRng>(
        &self,
        rng: &mut R,
    ) -> Result<(Self::PublicKey, Self::SecretKey), CryptoError>;

    /// Sign an arbitrary message.
    fn sign(&self, sk: &Self::SecretKey, msg: &[u8]) -> Result<Self::Signature, CryptoError>;

    /// Verify that `sig` is a valid signature of `msg` under `pk`.
    fn verify(
        &self,
        pk: &Self::PublicKey,
        msg: &[u8],
        sig: &Self::Signature,
    ) -> Result<(), CryptoError>;
}

/* -------------------------------------------------------------------------
 * Factory
 * ---------------------------------------------------------------------- */

/// Resolves a concrete signer from a [`SchemeType`].  The function returns
/// an `Arc` so that the instance may be cheaply cloned across tasks.
///
/// ```
/// use ccs_crypto::{resolve_scheme, SchemeType};
/// let ed = resolve_scheme(SchemeType::Ed25519).unwrap();
/// let (pk, sk) = ed.generate(&mut rand::thread_rng()).unwrap();
/// let msg = b"CanvasChain ♥";
/// let sig = ed.sign(&sk, msg).unwrap();
/// ed.verify(&pk, msg, &sig).unwrap();
/// ```
pub fn resolve_scheme(ty: SchemeType) -> Result<DynScheme, CryptoError> {
    let scheme: DynScheme = match ty {
        SchemeType::Ed25519 => Arc::new(ed25519::Ed25519Scheme::default()),
        #[cfg(feature = "bls12_381")]
        SchemeType::Bls12381 => Arc::new(bls12381::BlsScheme::default()),
        #[cfg(feature = "pq")]
        SchemeType::PostQuantum => return Err(CryptoError::UnsupportedScheme(ty)),
        #[allow(unreachable_patterns)]
        _ => return Err(CryptoError::UnsupportedScheme(ty)),
    };
    Ok(scheme)
}

/* -------------------------------------------------------------------------
 * Ed25519 implementation
 * ---------------------------------------------------------------------- */

/// Ed25519 back-end – **always enabled** unless the caller explicitly disables
/// the default feature.
#[cfg(feature = "ed25519")]
mod ed25519 {
    use super::{CryptoError, SchemeType, SignatureScheme};
    use ed25519_dalek::{
        Keypair, PublicKey, SecretKey as DalekSecret, Signature, Signer, Verifier,
    };
    use rand_core::{CryptoRng, RngCore};
    use serde::{Deserialize, Serialize};
    use zeroize::Zeroize;

    /// A thin wrapper around `Keypair` that implements `Zeroize`.
    #[derive(Clone, Debug, Serialize, Deserialize)]
    pub struct SecretKey(
        #[serde(with = "serde_bytes")] #[serde(
            serialize_with = "serialize_keypair",
            deserialize_with = "deserialize_keypair"
        )]
        Keypair,
    );

    impl Zeroize for SecretKey {
        fn zeroize(&mut self) {
            // `Keypair` already wipes its secret part on drop, but we do it just in case.
            self.0.secret.zeroize();
        }
    }

    /// Serialises a `Keypair` as raw bytes.
    fn serialize_keypair<S>(kp: &Keypair, s: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serde_bytes::SerializeBytes::serialize_as_bytes(kp.as_bytes(), s)
    }

    /// De-serialises a `Keypair` from raw bytes.
    fn deserialize_keypair<'de, D>(deserializer: D) -> Result<Keypair, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let bytes: &[u8] = serde_bytes::ByteBuf::deserialize(deserializer)?;
        Keypair::from_bytes(bytes).map_err(serde::de::Error::custom)
    }

    /// New-type around `Signature` to enable **serde**.
    #[derive(Clone, Debug, Serialize, Deserialize, Eq, PartialEq)]
    pub struct SerSignature(#[serde(with = "serde_bytes")] pub(crate) Vec<u8>);

    impl From<Signature> for SerSignature {
        fn from(sig: Signature) -> Self {
            Self(sig.to_bytes().to_vec())
        }
    }

    impl TryFrom<&SerSignature> for Signature {
        type Error = CryptoError;
        fn try_from(value: &SerSignature) -> Result<Self, Self::Error> {
            Signature::from_bytes(&value.0).map_err(|_| CryptoError::InvalidKey("signature"))
        }
    }

    /// Ed25519 implementation of [`SignatureScheme`].
    #[derive(Default)]
    pub struct Ed25519Scheme;

    impl SignatureScheme for Ed25519Scheme {
        type PublicKey = PublicKey;
        type SecretKey = SecretKey;
        type Signature = SerSignature;

        fn scheme(&self) -> SchemeType {
            SchemeType::Ed25519
        }

        fn generate<R: RngCore + CryptoRng>(
            &self,
            rng: &mut R,
        ) -> Result<(Self::PublicKey, Self::SecretKey), CryptoError> {
            let kp = Keypair::generate(rng);
            let pk = kp.public.clone();
            Ok((pk, SecretKey(kp)))
        }

        fn sign(
            &self,
            sk: &Self::SecretKey,
            msg: &[u8],
        ) -> Result<Self::Signature, CryptoError> {
            Ok(sk.0.sign(msg).into())
        }

        fn verify(
            &self,
            pk: &Self::PublicKey,
            msg: &[u8],
            sig: &Self::Signature,
        ) -> Result<(), CryptoError> {
            let sig: Signature = sig.try_into()?;
            pk.verify(msg, &sig)
                .map_err(|_| CryptoError::VerificationFailed)
        }
    }

    /* ---------------------------------------------------------------------
     * serde helper for zero-copy performance
     * ------------------------------------------------------------------ */

    mod serde_bytes {
        pub use serde_bytes::{ByteBuf, Bytes, SerializeBytes};
    }
}

/* -------------------------------------------------------------------------
 * BLS12-381 implementation
 * ---------------------------------------------------------------------- */
#[cfg(feature = "bls12_381")]
mod bls12381 {
    use super::{CryptoError, SchemeType, SignatureScheme};
    use blst::{min_sig, BLST_ERROR};
    use rand_core::{CryptoRng, OsRng, RngCore};
    use serde::{Deserialize, Serialize};
    use zeroize::Zeroize;

    /// Domain Separation Tag as recommended by the IETF draft.
    const DST: &[u8] = b"BLS_SIG_BLS12381G1_XMD:SHA-256_SSWU_RO_NUL_";

    #[derive(Clone, Debug, Serialize, Deserialize, Eq, PartialEq)]
    pub struct PublicKey(
        #[serde(with = "serde_bytes")] pub(crate) Vec<u8>, // compressed 48 bytes
    );

    #[derive(Clone, Debug, Serialize, Deserialize)]
    pub struct SecretKey(
        #[serde(with = "serde_bytes")] pub(crate) Vec<u8>, // 32 bytes
    );

    impl Zeroize for SecretKey {
        fn zeroize(&mut self) {
            self.0.zeroize();
        }
    }

    #[derive(Clone, Debug, Serialize, Deserialize, Eq, PartialEq)]
    pub struct Signature(
        #[serde(with = "serde_bytes")] pub(crate) Vec<u8>, // compressed 96 bytes
    );

    #[derive(Default)]
    pub struct BlsScheme;

    impl SignatureScheme for BlsScheme {
        type PublicKey = PublicKey;
        type SecretKey = SecretKey;
        type Signature = Signature;

        fn scheme(&self) -> SchemeType {
            SchemeType::Bls12381
        }

        fn generate<R: RngCore + CryptoRng>(
            &self,
            rng: &mut R,
        ) -> Result<(Self::PublicKey, Self::SecretKey), CryptoError> {
            // `min_sig::SecretKey::key_gen` expects IKM >= 32 bytes.
            let mut ikm = [0u8; 32];
            rng.try_fill_bytes(&mut ikm)
                .map_err(|_| CryptoError::Rng("failed to read entropy"))?;
            let sk = min_sig::SecretKey::key_gen(&ikm, &[])
                .map_err(|_| CryptoError::Backend("keygen failed"))?;
            let pk = sk.sk_to_pk();
            Ok((
                PublicKey(pk.compress().to_vec()),
                SecretKey(sk.to_bytes().to_vec()),
            ))
        }

        fn sign(
            &self,
            sk: &Self::SecretKey,
            msg: &[u8],
        ) -> Result<Self::Signature, CryptoError> {
            let sk = min_sig::SecretKey::from_bytes(&sk.0)
                .map_err(|_| CryptoError::InvalidKey("secret key"))?;
            let sig = sk.sign(msg, DST, &[]);
            Ok(Signature(sig.compress().to_vec()))
        }

        fn verify(
            &self,
            pk: &Self::PublicKey,
            msg: &[u8],
            sig: &Self::Signature,
        ) -> Result<(), CryptoError> {
            let pk = min_sig::PublicKey::from_bytes(&pk.0)
                .map_err(|_| CryptoError::InvalidKey("public key"))?;
            let sig = min_sig::Signature::from_bytes(&sig.0)
                .map_err(|_| CryptoError::InvalidKey("signature"))?;
            let result = sig.verify(true, msg, DST, &[], &pk, true);
            if result == BLST_ERROR::BLST_SUCCESS {
                Ok(())
            } else {
                Err(CryptoError::VerificationFailed)
            }
        }
    }

    /* ---------------------------------------------------------------------
     * serde shortcut
     * ------------------------------------------------------------------ */
    mod serde_bytes {
        pub use serde_bytes::{ByteBuf, Bytes};
    }
}

/* -------------------------------------------------------------------------
 * Unit-tests (enabled with `cargo test`)
 * ---------------------------------------------------------------------- */

#[cfg(test)]
mod tests {
    use super::*;

    fn round_trip(scheme: SchemeType) {
        let signer = resolve_scheme(scheme).unwrap();
        let mut rng = rand::thread_rng();
        let (pk, sk) = signer.generate(&mut rng).unwrap();

        let msg = b"Alice pays Bob 42 Ξ";
        let sig = signer.sign(&sk, msg).unwrap();
        signer.verify(&pk, msg, &sig).unwrap();

        // Corrupt message must fail.
        let err = signer.verify(&pk, b"tampered", &sig).unwrap_err();
        assert!(matches!(err, CryptoError::VerificationFailed));
    }

    #[test]
    fn ed25519_round_trip() {
        round_trip(SchemeType::Ed25519);
    }

    #[cfg(feature = "bls12_381")]
    #[test]
    fn bls_round_trip() {
        round_trip(SchemeType::Bls12381);
    }

    #[test]
    fn unsupported_scheme() {
        #[cfg(not(feature = "pq"))]
        assert!(matches!(
            resolve_scheme(SchemeType::PostQuantum).unwrap_err(),
            CryptoError::UnsupportedScheme(_)
        ));
    }
}
```