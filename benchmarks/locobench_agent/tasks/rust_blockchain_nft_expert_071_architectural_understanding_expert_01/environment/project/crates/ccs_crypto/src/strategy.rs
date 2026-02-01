```rust
//! Strategy layer for pluggable signature algorithms.
//!
//! CanvasChain Symphony lets collectives experiment with
//! different cryptographic curves (Ed25519, BLS12-381, PQ-Falcon,
//! …) without recompiling the whole chain.  The Strategy pattern
//! exposed here makes the concrete algorithm an implementation
//! detail that can be selected at runtime through configuration or
//! on-chain governance upgrades.

#![allow(clippy::module_name_repetitions)]

use std::{
    fmt::{self, Debug, Display},
    sync::Arc,
};

use base64::{engine::general_purpose as b64, Engine};
use rand_core::{CryptoRng, RngCore};
use thiserror::Error;

/// Public algorithm identifier.
///
/// NOTE:  Keep numeric discriminants stable – they appear on-chain.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[repr(u16)]
pub enum CurveKind {
    /// Ed25519 (ristretto) – fast, battle-tested, default choice.
    Ed25519 = 0x01,
    /// BLS12-381 – aggregate-friendly, used for signature-of-stake.
    Bls12381 = 0x02,
    /// Falcon-512 – post-quantum lattice scheme (draft).
    Falcon512 = 0x03,
}

/// Top-level error for the crypto subsystem.
#[derive(Debug, Error)]
pub enum CryptoError {
    #[error("invalid key bytes: {0}")]
    InvalidKey(String),

    #[error("signature verification failed")]
    BadSignature,

    #[error("unsupported operation: {0}")]
    Unsupported(&'static str),

    #[error("crypto backend error: {0}")]
    Backend(String),
}

/// Strategy interface – all curve backends implement this.
///
/// All inputs / outputs are raw byte vectors to keep the trait
/// object-safe and provide full runtime polymorphism (no generic
/// parameters leaking out of the public API).
///
/// Key / signature encoding MUST be canonical – each strategy
/// decides *which* canonical form is used (e.g. compressed points,
/// DER, etc.) but guarantees round-trip safety.
pub trait CurveStrategy: Send + Sync + 'static {
    /// Which curve do we implement?
    fn kind(&self) -> CurveKind;

    /// Generate a fresh keypair.
    ///
    /// Returns `(public_key, private_key)`.
    fn generate_keypair(&self, rng: &mut (impl RngCore + CryptoRng)) -> Result<(Vec<u8>, Vec<u8>), CryptoError>;

    /// Sign arbitrary message bytes.
    ///
    /// `private_key` must be a key previously produced by
    /// `generate_keypair` or imported via `import_private_key`.
    fn sign(&self, private_key: &[u8], message: &[u8]) -> Result<Vec<u8>, CryptoError>;

    /// Verify `signature` was created by `public_key` over `message`.
    fn verify(&self, public_key: &[u8], message: &[u8], signature: &[u8]) -> Result<(), CryptoError>;

    /// Human-friendly base64 helpers useful for configs / CLI.
    fn pk_to_b64(&self, pk: &[u8]) -> String {
        b64::STANDARD.encode(pk)
    }

    fn sk_to_b64(&self, sk: &[u8]) -> String {
        b64::STANDARD.encode(sk)
    }

    fn sig_to_b64(&self, sig: &[u8]) -> String {
        b64::STANDARD.encode(sig)
    }
}

/* ---------------------------------------------------------------- *
 *                 ========  Ed25519 backend  ========              *
 * ---------------------------------------------------------------- */

mod ed25519_backend {
    use super::*;
    use ed25519_dalek::{
        Signature as DalekSig, Signer, SigningKey, Verifier, VerifyingKey, SECRET_KEY_LENGTH,
    };

    pub struct Ed25519Strategy;

    impl Debug for Ed25519Strategy {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            f.debug_struct("Ed25519Strategy").finish()
        }
    }

    impl CurveStrategy for Ed25519Strategy {
        fn kind(&self) -> CurveKind {
            CurveKind::Ed25519
        }

        fn generate_keypair(
            &self,
            rng: &mut (impl RngCore + CryptoRng),
        ) -> Result<(Vec<u8>, Vec<u8>), CryptoError> {
            let sk = SigningKey::generate(rng);
            let pk = sk.verifying_key();

            Ok((pk.to_bytes().to_vec(), sk.to_bytes().to_vec()))
        }

        fn sign(&self, private_key: &[u8], message: &[u8]) -> Result<Vec<u8>, CryptoError> {
            let sk = SigningKey::from_bytes(
                private_key
                    .try_into()
                    .map_err(|_| CryptoError::InvalidKey("ed25519 secret key length".into()))?,
            );

            let sig: DalekSig = sk.sign(message);
            Ok(sig.to_bytes().to_vec())
        }

        fn verify(
            &self,
            public_key: &[u8],
            message: &[u8],
            signature: &[u8],
        ) -> Result<(), CryptoError> {
            let pk = VerifyingKey::from_bytes(
                public_key
                    .try_into()
                    .map_err(|_| CryptoError::InvalidKey("ed25519 public key length".into()))?,
            )
            .map_err(|e| CryptoError::InvalidKey(e.to_string()))?;

            let sig = DalekSig::from_bytes(
                signature
                    .try_into()
                    .map_err(|_| CryptoError::InvalidKey("ed25519 signature length".into()))?,
            );

            pk.verify(message, &sig)
                .map_err(|_| CryptoError::BadSignature)
        }
    }

    /// Re-export so downstream crates can opt-in for
    /// algorithm-specific features when desired.
    pub use ed25519_dalek::{SigningKey as Ed25519PrivateKey, VerifyingKey as Ed25519PublicKey};
}

/* ---------------------------------------------------------------- *
 *                 ========  BLS12-381 backend  ========            *
 * ---------------------------------------------------------------- */

#[cfg(feature = "bls")]
mod bls_backend {
    use super::*;
    use blstrs::{hash_to_g2, Scalar as Fr, Signature as BlsSignature};
    use groupy::Curve;

    pub struct Bls12381Strategy;

    impl Debug for Bls12381Strategy {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            f.debug_struct("Bls12381Strategy").finish()
        }
    }

    impl CurveStrategy for Bls12381Strategy {
        fn kind(&self) -> CurveKind {
            CurveKind::Bls12381
        }

        fn generate_keypair(
            &self,
            rng: &mut (impl RngCore + CryptoRng),
        ) -> Result<(Vec<u8>, Vec<u8>), CryptoError> {
            let sk = Fr::random(rng);
            let pk = (blstrs::G1Affine::generator() * sk).to_affine();

            Ok((pk.to_compressed(), sk.to_bytes().to_vec()))
        }

        fn sign(&self, private_key: &[u8], message: &[u8]) -> Result<Vec<u8>, CryptoError> {
            let sk =
                Fr::from_bytes(private_key.try_into().map_err(|_| CryptoError::InvalidKey(
                    "bls12-381 secret key length".into()
                ))?)
                .ok_or_else(|| CryptoError::InvalidKey("bls12-381 secret key invalid".into()))?;

            // Hash message to curve
            let hashed = hash_to_g2(message, b"BLS_SIG_DOMAIN");
            let sig = hashed * sk;

            Ok(BlsSignature::from(sig.to_affine()).to_bytes().to_vec())
        }

        fn verify(
            &self,
            public_key: &[u8],
            message: &[u8],
            signature: &[u8],
        ) -> Result<(), CryptoError> {
            use blstrs::{pairing, G1Affine, G2Affine};

            let pk =
                G1Affine::from_compressed(public_key.try_into().map_err(|_| CryptoError::InvalidKey(
                    "bls12-381 public key length".into()
                ))?)
                .map_err(|_| CryptoError::InvalidKey("invalid bls12-381 public key".into()))?;

            let sig =
                G2Affine::from_compressed(signature.try_into().map_err(|_| CryptoError::InvalidKey(
                    "bls12-381 signature length".into()
                ))?)
                .map_err(|_| CryptoError::InvalidKey("invalid bls12-381 signature".into()))?;

            let msg_hash = hash_to_g2(message, b"BLS_SIG_DOMAIN").to_affine();

            let lhs = pairing(&pk, &msg_hash);
            let rhs = pairing(&G1Affine::generator(), &sig);

            if lhs == rhs {
                Ok(())
            } else {
                Err(CryptoError::BadSignature)
            }
        }
    }
}

/* ---------------------------------------------------------------- *
 *        ========  Post-Quantum (Falcon) backend  ========         *
 * ---------------------------------------------------------------- */

/// Placeholder skeleton to allow PQ experimentation without adding
/// heavyweight dependencies by default.  Enable the `falcon` crate
/// and fill in the gaps to obtain a full implementation.
#[cfg(feature = "pq")]
mod falcon_backend {
    use super::*;

    pub struct Falcon512Strategy;

    impl Debug for Falcon512Strategy {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            f.debug_struct("Falcon512Strategy").finish()
        }
    }

    impl CurveStrategy for Falcon512Strategy {
        fn kind(&self) -> CurveKind {
            CurveKind::Falcon512
        }

        fn generate_keypair(
            &self,
            _rng: &mut (impl RngCore + CryptoRng),
        ) -> Result<(Vec<u8>, Vec<u8>), CryptoError> {
            Err(CryptoError::Unsupported("Falcon not compiled in"))
        }

        fn sign(&self, _private_key: &[u8], _message: &[u8]) -> Result<Vec<u8>, CryptoError> {
            Err(CryptoError::Unsupported("Falcon not compiled in"))
        }

        fn verify(
            &self,
            _public_key: &[u8],
            _message: &[u8],
            _signature: &[u8],
        ) -> Result<(), CryptoError> {
            Err(CryptoError::Unsupported("Falcon not compiled in"))
        }
    }
}

/* ---------------------------------------------------------------- *
 *                    ========  Facade  ========                    *
 * ---------------------------------------------------------------- */

/// Public façade – thin wrapper around `Arc<dyn CurveStrategy>` that
/// provides ergonomic helpers and shields callers from needing to
/// deal with trait objects directly.
#[derive(Clone)]
pub struct CryptoEngine {
    strategy: Arc<dyn CurveStrategy>,
}

impl Debug for CryptoEngine {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("CryptoEngine")
            .field("curve", &self.strategy.kind())
            .finish()
    }
}

impl CryptoEngine {
    /// Construct an engine for the requested curve.
    pub fn with_curve(curve: CurveKind) -> Result<Self, CryptoError> {
        let strategy: Arc<dyn CurveStrategy> = match curve {
            CurveKind::Ed25519 => Arc::new(ed25519_backend::Ed25519Strategy),
            CurveKind::Bls12381 => {
                #[cfg(feature = "bls")]
                {
                    Arc::new(bls_backend::Bls12381Strategy)
                }
                #[cfg(not(feature = "bls"))]
                {
                    return Err(CryptoError::Unsupported(
                        "BLS backend not compiled in – enable `bls` feature",
                    ));
                }
            }
            CurveKind::Falcon512 => {
                #[cfg(feature = "pq")]
                {
                    Arc::new(falcon_backend::Falcon512Strategy)
                }
                #[cfg(not(feature = "pq"))]
                {
                    return Err(CryptoError::Unsupported(
                        "Falcon backend not compiled in – enable `pq` feature",
                    ));
                }
            }
        };

        Ok(Self { strategy })
    }

    pub fn kind(&self) -> CurveKind {
        self.strategy.kind()
    }

    /* -------------  High-level wrappers  ------------- */

    pub fn generate_keypair(&self) -> Result<(Vec<u8>, Vec<u8>), CryptoError> {
        let mut rng = rand_core::OsRng;
        self.strategy.generate_keypair(&mut rng)
    }

    pub fn sign(&self, private_key: &[u8], msg: &[u8]) -> Result<Vec<u8>, CryptoError> {
        self.strategy.sign(private_key, msg)
    }

    pub fn verify(&self, public_key: &[u8], msg: &[u8], sig: &[u8]) -> Result<(), CryptoError> {
        self.strategy.verify(public_key, msg, sig)
    }

    /* -------------  Base64 helpers  ------------- */

    pub fn pk_to_b64(&self, pk: &[u8]) -> String {
        self.strategy.pk_to_b64(pk)
    }

    pub fn sk_to_b64(&self, sk: &[u8]) -> String {
        self.strategy.sk_to_b64(sk)
    }

    pub fn sig_to_b64(&self, sig: &[u8]) -> String {
        self.strategy.sig_to_b64(sig)
    }
}

/* ---------------------------------------------------------------- *
 *                     ========  Tests  ========                    *
 * ---------------------------------------------------------------- */

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ed25519_sign_roundtrip() {
        let engine = CryptoEngine::with_curve(CurveKind::Ed25519).unwrap();
        let (pk, sk) = engine.generate_keypair().unwrap();

        let msg = b"Hello CanvasChain!";
        let sig = engine.sign(&sk, msg).unwrap();
        engine.verify(&pk, msg, &sig).unwrap();
    }

    #[cfg(feature = "bls")]
    #[test]
    fn bls_sign_roundtrip() {
        let engine = CryptoEngine::with_curve(CurveKind::Bls12381).unwrap();
        let (pk, sk) = engine.generate_keypair().unwrap();

        let msg = b"Composable signatures rock!";
        let sig = engine.sign(&sk, msg).unwrap();
        engine.verify(&pk, msg, &sig).unwrap();
    }
}
```