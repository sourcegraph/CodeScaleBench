```rust
//! Cryptographic curve abstraction layer for CanvasChain Symphony
//!
//! This module uses the Strategy pattern to expose a *single* trait
//! (`DigitalSignature`) that can be implemented by multiple signature
//! schemes (Ed25519, BLS12-381, post-quantum, …).  Supply the desired
//! curve through Cargo feature-flags and the rest of the codebase can
//! stay completely agnostic to the underlying mathematics.
//!
//! Feature flags (only one, many or none can be enabled):
//!   `ed25519`   – enables Ed25519 via `ed25519-dalek`
//!   `bls`       – enables BLS12-381 (min-sig) via `blst`
//!   `falcon`    – enables Falcon-512 (post-quantum) via `pqcrypto`
#![allow(clippy::needless_lifetimes)]

use core::fmt::Debug;

pub type Result<T> = core::result::Result<T, CryptoError>;

/// Canonical error type for all crypto operations
#[derive(Debug)]
pub enum CryptoError {
    RandomnessError(String),
    InvalidKey(String),
    InvalidSignature(String),
    VerificationFailed,
    CurveUnavailable(&'static str),
    Other(String),
}

impl core::fmt::Display for CryptoError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        use CryptoError::*;
        match self {
            RandomnessError(e) => write!(f, "randomness error: {e}"),
            InvalidKey(e) => write!(f, "invalid key: {e}"),
            InvalidSignature(e) => write!(f, "invalid signature: {e}"),
            VerificationFailed => write!(f, "signature verification failed"),
            CurveUnavailable(name) => write!(f, "curve `{name}` is not compiled in"),
            Other(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for CryptoError {}

/// Core behaviour expected from any signature scheme
///
/// The trait is intentionally object-safe so a `Box<dyn DigitalSignature>`
/// can be handed around by higher-level orchestration code.
pub trait DigitalSignature: Debug + Send + Sync {
    type PrivateKey: Debug + Send + Sync;
    type PublicKey: Debug + Send + Sync;
    type Signature: Debug + Send + Sync;

    /// Generate a new key-pair using the given CSPRNG instance.
    fn generate_keys<R: rand_core::CryptoRng + rand_core::RngCore>(
        rng: &mut R,
    ) -> Result<(Self::PrivateKey, Self::PublicKey)>;

    /// Sign an arbitrary message with the corresponding private key.
    fn sign(sk: &Self::PrivateKey, msg: &[u8]) -> Result<Self::Signature>;

    /// Verify a message/signature pair against a public key.
    fn verify(pk: &Self::PublicKey, msg: &[u8], sig: &Self::Signature) -> Result<()>;
}

/// Convenience enum to refer to a concrete curve at run-time.
/// Use this if you need to dynamically choose an algorithm.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CurveKind {
    Ed25519,
    Bls12381,
    Falcon512,
}

impl CurveKind {
    /// Returns `true` if the curve was compiled in.
    pub fn is_available(self) -> bool {
        match self {
            CurveKind::Ed25519 => cfg!(feature = "ed25519"),
            CurveKind::Bls12381 => cfg!(feature = "bls"),
            CurveKind::Falcon512 => cfg!(feature = "falcon"),
        }
    }

    /// Human-readable name
    pub fn name(self) -> &'static str {
        match self {
            CurveKind::Ed25519 => "ed25519",
            CurveKind::Bls12381 => "bls12-381",
            CurveKind::Falcon512 => "falcon-512",
        }
    }
}

/* ---------------------------------------------------------------- *\
 *  Ed25519 implementation
\* ---------------------------------------------------------------- */

#[cfg(feature = "ed25519")]
pub mod ed25519 {
    use super::{CryptoError, DigitalSignature, Result};
    use ed25519_dalek::{Keypair, PublicKey, Signature, Signer, Verifier};
    use rand_core::{CryptoRng, RngCore};

    /// Marker type for the Ed25519 curve
    #[derive(Debug, Default)]
    pub struct Ed25519;

    impl DigitalSignature for Ed25519 {
        type PrivateKey = Keypair;
        type PublicKey = PublicKey;
        type Signature = Signature;

        fn generate_keys<R: CryptoRng + RngCore>(
            rng: &mut R,
        ) -> Result<(Self::PrivateKey, Self::PublicKey)> {
            let kp = Keypair::generate(rng);
            Ok((kp.clone(), kp.public))
        }

        fn sign(sk: &Self::PrivateKey, msg: &[u8]) -> Result<Self::Signature> {
            Ok(sk.sign(msg))
        }

        fn verify(pk: &Self::PublicKey, msg: &[u8], sig: &Self::Signature) -> Result<()> {
            pk.verify(msg, sig)
                .map_err(|_| CryptoError::VerificationFailed)
        }
    }
}

/* ---------------------------------------------------------------- *\
 *  BLS12-381 (min-sig) implementation
\* ---------------------------------------------------------------- */

#[cfg(feature = "bls")]
pub mod bls12381 {
    use super::{CryptoError, DigitalSignature, Result};
    use blst::*;
    use rand_core::{CryptoRng, RngCore};

    /// Domain separation tag per https://datatracker.ietf.org/doc/html/draft-irtf-cfrg-bls-signature
    const DST: &[u8] = b"BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_NUL_";

    #[derive(Debug, Default)]
    pub struct Bls12381;

    impl DigitalSignature for Bls12381 {
        type PrivateKey = SecretKey;
        type PublicKey = PublicKey;
        type Signature = Signature;

        fn generate_keys<R: CryptoRng + RngCore>(
            rng: &mut R,
        ) -> Result<(Self::PrivateKey, Self::PublicKey)> {
            // Generate 32 random bytes of input keying material
            let mut ikm = [0u8; 32];
            rng.fill_bytes(&mut ikm);

            let sk = SecretKey::key_gen(&ikm, &[])
                .map_err(|_| CryptoError::RandomnessError("BLS key generation failed".into()))?;
            let pk = sk.sk_to_pk();
            Ok((sk, pk))
        }

        fn sign(sk: &Self::PrivateKey, msg: &[u8]) -> Result<Self::Signature> {
            Ok(sk.sign(msg, DST, &[]))
        }

        fn verify(pk: &Self::PublicKey, msg: &[u8], sig: &Self::Signature) -> Result<()> {
            let res = sig.verify(true, msg, DST, &[], pk, DST, &[]);
            match res {
                BLST_ERROR::BLST_SUCCESS => Ok(()),
                _ => Err(super::CryptoError::VerificationFailed),
            }
        }
    }
}

/* ---------------------------------------------------------------- *\
 *  Falcon-512 (Post-Quantum) implementation
 *
 *  NOTE:  The `pqcrypto` ecosystem is still in flux.  Large sections
 *  of the interface may change; use with caution.
\* ---------------------------------------------------------------- */

#[cfg(feature = "falcon")]
pub mod falcon512 {
    use super::{CryptoError, DigitalSignature, Result};
    use pqcrypto_falcon::falcon512::{
        detached_sign as pq_sign, detached_signature_bytes as sig_len, keypair, public_key_bytes,
        secret_key_bytes, verify_detached_signature as pq_verify, PublicKey, SecretKey,
        Signature as PqSignature,
    };
    use rand_core::{CryptoRng, RngCore};

    #[derive(Debug, Default)]
    pub struct Falcon512;

    impl DigitalSignature for Falcon512 {
        type PrivateKey = SecretKey;
        type PublicKey = PublicKey;
        type Signature = PqSignature;

        fn generate_keys<R: CryptoRng + RngCore>(
            _rng: &mut R,
        ) -> Result<(Self::PrivateKey, Self::PublicKey)> {
            // pqcrypto provides its own RNG wrappers internally
            let (pk, sk) = keypair();
            Ok((sk, pk))
        }

        fn sign(sk: &Self::PrivateKey, msg: &[u8]) -> Result<Self::Signature> {
            Ok(pq_sign(msg, sk))
        }

        fn verify(pk: &Self::PublicKey, msg: &[u8], sig: &Self::Signature) -> Result<()> {
            pq_verify(sig, msg, pk).map_err(|_| CryptoError::VerificationFailed)
        }
    }
}

/* ---------------------------------------------------------------- *\
 *  Re-exports for ergonomics
\* ---------------------------------------------------------------- */

cfg_if::cfg_if! {
    if #[cfg(feature = "ed25519")] {
        pub use ed25519::Ed25519;
    }
}
cfg_if::cfg_if! {
    if #[cfg(feature = "bls")] {
        pub use bls12381::Bls12381;
    }
}
cfg_if::cfg_if! {
    if #[cfg(feature = "falcon")] {
        pub use falcon512::Falcon512;
    }
}

/* ---------------------------------------------------------------- *\
 *  Tests
\* ---------------------------------------------------------------- */

#[cfg(all(test, feature = "ed25519"))]
mod tests_ed25519 {
    use super::{DigitalSignature, Result};
    use crate::curves::Ed25519;
    use rand_core::OsRng;

    #[test]
    fn ed25519_sign_and_verify_roundtrip() -> Result<()> {
        let mut rng = OsRng;

        // --- key generation
        let (sk, pk) = Ed25519::generate_keys(&mut rng)?;

        // --- sign / verify
        let message = b"CanvasChain – unleash generative art!";
        let sig = Ed25519::sign(&sk, message)?;
        Ed25519::verify(&pk, message, &sig)?;

        // --- tampering should fail
        let bogus = b"tampered message";
        assert!(Ed25519::verify(&pk, bogus, &sig).is_err());

        Ok(())
    }
}

#[cfg(all(test, feature = "bls"))]
mod tests_bls {
    use super::{DigitalSignature, Result};
    use crate::curves::Bls12381;
    use rand_core::OsRng;

    #[test]
    fn bls_sign_and_verify_roundtrip() -> Result<()> {
        let mut rng = OsRng;

        let (sk, pk) = Bls12381::generate_keys(&mut rng)?;
        let msg = b"Symphonic harmony through cryptography 🎶";
        let sig = Bls12381::sign(&sk, msg)?;

        Bls12381::verify(&pk, msg, &sig)?;

        // wrong message:
        assert!(Bls12381::verify(&pk, b"off-key note", &sig).is_err());
        Ok(())
    }
}
```