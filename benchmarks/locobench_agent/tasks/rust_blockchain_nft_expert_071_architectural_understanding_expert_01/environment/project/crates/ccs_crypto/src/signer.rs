```rust
//! signer.rs
//!
//! Cryptographic signer abstraction for CanvasChain Symphony.
//! The module is deliberately decoupled from specific curve
//! implementations through a Strategy pattern.  Consumers can
//! swap algorithms at runtime without recompiling other crates.
//!
//! Supported algorithms (compile-time feature flags):
//!   • `ed25519` (default) – uses `ed25519-dalek`
//!   • `bls`            – uses `blst`
//!
//! # Examples
//! ```rust,no_run
//! use ccs_crypto::signer::{Curve, Keypair, Signer};
//!
//! // create a random Ed25519 keypair
//! let keypair = Keypair::random(Curve::Ed25519).unwrap();
//!
//! // sign a message
//! let message = b"gm web3!";
//! let sig = keypair.sign(message).unwrap();
//!
//! // verify
//! assert!(keypair.verify(message, &sig).is_ok());
//! ```
//!
//! NOTE: This file intentionally does **not** expose the concrete
//! secret key types of the underlying libraries.  Secret material is
//! kept inside the strategy objects and wiped on drop (via `zeroize`).

use std::{fmt, sync::Arc};

use rand_core::{CryptoRng, OsRng, RngCore};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use zeroize::{Zeroize, ZeroizeOnDrop};

/// Enumeration of supported signature curves
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[repr(u8)]
pub enum Curve {
    Ed25519 = 1,
    #[cfg(feature = "bls")]
    Bls12381 = 2,
}

impl fmt::Display for Curve {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let s = match self {
            Curve::Ed25519 => "ed25519",
            #[cfg(feature = "bls")]
            Curve::Bls12381 => "bls12-381",
        };
        write!(f, "{s}")
    }
}

/// Error variants returned by the signer subsystem.
#[derive(Error, Debug)]
pub enum SignerError {
    #[error("unsupported curve")]
    UnsupportedCurve,
    #[error("signature verification failed")]
    InvalidSignature,
    #[error("library error: {0}")]
    Library(String),
}

/// Opaque wrapper around a signature.
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Signature {
    pub curve: Curve,
    #[serde(with = "serde_bytes")]
    bytes: Vec<u8>,
}

impl fmt::Debug for Signature {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Signature")
            .field("curve", &self.curve)
            .field("bytes(len)", &self.bytes.len())
            .finish()
    }
}

impl Signature {
    pub fn as_bytes(&self) -> &[u8] {
        &self.bytes
    }
}

/// A keypair capable of signing / verifying messages.
///
/// This is a thin, reference counted handle around a concrete signer
/// strategy so cloning `Keypair` is cheap.
#[derive(Clone)]
pub struct Keypair {
    inner: Arc<dyn Signer + Send + Sync>,
}

impl Keypair {
    /// Generate a new keypair from a cryptographically secure RNG.
    pub fn random(curve: Curve) -> Result<Self, SignerError> {
        Self::generate_with_rng(curve, &mut OsRng)
    }

    /// Generate a keypair, injecting an external `CryptoRng` (useful
    /// for deterministic tests or hardware RNGs).
    pub fn generate_with_rng<R: RngCore + CryptoRng>(
        curve: Curve,
        rng: &mut R,
    ) -> Result<Self, SignerError> {
        Ok(Self {
            inner: match curve {
                Curve::Ed25519 => Arc::new(ed25519::Ed25519Signer::generate(rng)),
                #[cfg(feature = "bls")]
                Curve::Bls12381 => Arc::new(bls::BlsSigner::generate(rng)),
                #[allow(unreachable_patterns)]
                _ => return Err(SignerError::UnsupportedCurve),
            },
        })
    }

    /// Re-hydrate a keypair from raw secret bytes.
    ///
    /// NOTE: The format of `secret_key_bytes` is curve-specific and not
    /// considered part of the stable API.  Prefer the Keyfile format
    /// in `ccs_keystore` for persistence.
    pub fn from_secret(curve: Curve, secret_key_bytes: &[u8]) -> Result<Self, SignerError> {
        Ok(Self {
            inner: match curve {
                Curve::Ed25519 => Arc::new(ed25519::Ed25519Signer::from_secret(secret_key_bytes)?),
                #[cfg(feature = "bls")]
                Curve::Bls12381 => Arc::new(bls::BlsSigner::from_secret(secret_key_bytes)?),
                #[allow(unreachable_patterns)]
                _ => return Err(SignerError::UnsupportedCurve),
            },
        })
    }

    /// Sign a message, returning the raw signature bytes.
    pub fn sign(&self, message: &[u8]) -> Result<Signature, SignerError> {
        self.inner.sign(message)
    }

    /// Verify a signature.
    pub fn verify(&self, message: &[u8], sig: &Signature) -> Result<(), SignerError> {
        // avoid confusion if wrong curve is supplied
        if sig.curve != self.inner.curve() {
            return Err(SignerError::InvalidSignature);
        }
        self.inner.verify(message, sig)
    }

    /// Return the public key in compressed form.
    pub fn public_key(&self) -> Vec<u8> {
        self.inner.public_key()
    }

    /// Reveal the curve in use.
    pub fn curve(&self) -> Curve {
        self.inner.curve()
    }
}

/// Trait implemented by algorithm-specific signer strategies.
trait Signer {
    fn curve(&self) -> Curve;
    fn public_key(&self) -> Vec<u8>;
    fn sign(&self, message: &[u8]) -> Result<Signature, SignerError>;
    fn verify(&self, message: &[u8], sig: &Signature) -> Result<(), SignerError>;
}

/* -------------------------------------------------------------
 *  Ed25519 implementation
 * ---------------------------------------------------------- */
#[cfg(feature = "ed25519")]
mod ed25519 {
    use super::*;
    use ed25519_dalek::{
        ed25519::signature::{Signer as DalekSigner, Verifier as DalekVerifier},
        Keypair as DalekKeypair, PublicKey, SecretKey, Signature as DalekSignature, Signer,
    };

    /// New-type wrapper that zeroizes secret key material on drop.
    #[derive(Zeroize, ZeroizeOnDrop)]
    struct DalekKeypairBox(DalekKeypair);

    pub(super) struct Ed25519Signer {
        kp: DalekKeypairBox,
    }

    impl Ed25519Signer {
        pub fn generate<R: CryptoRng + RngCore>(rng: &mut R) -> Self {
            let dalek_kp = DalekKeypair::generate(rng);
            Self {
                kp: DalekKeypairBox(dalek_kp),
            }
        }

        pub fn from_secret(bytes: &[u8]) -> Result<Self, SignerError> {
            if bytes.len() != SecretKey::BYTE_SIZE {
                return Err(SignerError::Library("invalid secret key length".into()));
            }
            let secret =
                SecretKey::from_bytes(bytes).map_err(|e| SignerError::Library(e.to_string()))?;
            let public: PublicKey = (&secret).into();
            let dalek_kp = DalekKeypair { secret, public };
            Ok(Self {
                kp: DalekKeypairBox(dalek_kp),
            })
        }
    }

    impl Signer for Ed25519Signer {
        fn curve(&self) -> Curve {
            Curve::Ed25519
        }

        fn public_key(&self) -> Vec<u8> {
            self.kp.0.public.to_bytes().to_vec()
        }

        fn sign(&self, message: &[u8]) -> Result<Signature, SignerError> {
            let sig: DalekSignature = self.kp.0.sign(message);
            Ok(Signature {
                curve: Curve::Ed25519,
                bytes: sig.to_bytes().to_vec(),
            })
        }

        fn verify(&self, message: &[u8], sig: &Signature) -> Result<(), SignerError> {
            let dalek_sig = DalekSignature::from_bytes(&sig.bytes)
                .map_err(|_| SignerError::InvalidSignature)?;
            self.kp
                .0
                .public
                .verify(message, &dalek_sig)
                .map_err(|_| SignerError::InvalidSignature)
        }
    }
}

/* -------------------------------------------------------------
 *  BLS12-381 implementation (feature gated)
 * ---------------------------------------------------------- */
#[cfg(feature = "bls")]
mod bls {
    use super::*;
    use blst::{min_pk as blst_core, BLST_ERROR};

    /// Wrapper that zeroizes secret key on drop.
    #[derive(Zeroize, ZeroizeOnDrop)]
    struct BlsSecret(blst_core::SecretKey);

    pub(super) struct BlsSigner {
        sk: BlsSecret,
        pk_bytes: Vec<u8>,
    }

    impl BlsSigner {
        pub fn generate<R: RngCore + CryptoRng>(rng: &mut R) -> Self {
            let mut ikm = [0u8; 32];
            rng.fill_bytes(&mut ikm);
            let sk = blst_core::SecretKey::key_gen(&ikm, &[]).expect("ikm length");
            let pk = sk.sk_to_pk();
            Self {
                sk: BlsSecret(sk),
                pk_bytes: pk.to_bytes().to_vec(),
            }
        }

        pub fn from_secret(bytes: &[u8]) -> Result<Self, SignerError> {
            let sk = blst_core::SecretKey::from_bytes(bytes)
                .map_err(|_| SignerError::Library("invalid bls secret key".into()))?;
            let pk = sk.sk_to_pk();
            Ok(Self {
                sk: BlsSecret(sk),
                pk_bytes: pk.to_bytes().to_vec(),
            })
        }
    }

    impl Signer for BlsSigner {
        fn curve(&self) -> Curve {
            Curve::Bls12381
        }

        fn public_key(&self) -> Vec<u8> {
            self.pk_bytes.clone()
        }

        fn sign(&self, message: &[u8]) -> Result<Signature, SignerError> {
            use blst_core::Signature as BlstSignature;
            let sig = self.sk.0.sign(message, &[], &[]);
            Ok(Signature {
                curve: Curve::Bls12381,
                bytes: sig.to_bytes().to_vec(),
            })
        }

        fn verify(&self, message: &[u8], sig: &Signature) -> Result<(), SignerError> {
            use blst_core::{PublicKey as BlstPublicKey, Signature as BlstSignature};
            let pk = BlstPublicKey::from_bytes(&self.pk_bytes)
                .map_err(|_| SignerError::InvalidSignature)?;
            let sig = BlstSignature::from_bytes(&sig.bytes)
                .map_err(|_| SignerError::InvalidSignature)?;
            let err = sig.verify(true, message, &[], &[], &pk, true);
            match err {
                BLST_ERROR::BLST_SUCCESS => Ok(()),
                _ => Err(SignerError::InvalidSignature),
            }
        }
    }
}

/* -------------------------------------------------------------
 *  Tests
 * ---------------------------------------------------------- */
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ed25519_sign_verify() {
        let kp = Keypair::random(Curve::Ed25519).unwrap();
        let msg = b"hello 🎨";
        let sig = kp.sign(msg).unwrap();
        assert!(kp.verify(msg, &sig).is_ok());
    }

    #[cfg(feature = "bls")]
    #[test]
    fn bls_sign_verify() {
        let kp = Keypair::random(Curve::Bls12381).unwrap();
        let msg = b"canvas_chain";
        let sig = kp.sign(msg).unwrap();
        assert!(kp.verify(msg, &sig).is_ok());
    }

    #[test]
    fn curve_mismatch() {
        let ed_kp = Keypair::random(Curve::Ed25519).unwrap();
        #[cfg(feature = "bls")]
        let bls_kp = Keypair::random(Curve::Bls12381).unwrap();

        let msg = b"oops";
        let sig = ed_kp.sign(msg).unwrap();

        #[cfg(feature = "bls")]
        assert!(bls_kp.verify(msg, &sig).is_err());
    }
}
```