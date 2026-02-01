```rust
//! Verifiable Random Function (VRF) utilities for CanvasChain Symphony
//!
//! Abstractions in this module allow the rest of the code-base to remain
//! crypto-agnostic.  Switching from one curve or VRF algorithm to another is
//! therefore a matter of enabling the corresponding Cargo feature, without
//! recompiling the entire chain or touching business logic.
//!
//! The default implementation uses `schnorrkel` (Ristretto-based) because it is
//! audited, battle-tested in Substrate / Polkadot, and fast.  The trait based
//! “strategy” design means additional algorithms – BLS, post-quantum, etc. –
//! can live in sibling modules that implement [`VrfProvider`].
//!
//! This file purposefully owns zero global state.  Consumers can instantiate
//! their own [`VrfContext`] or use the free helpers in this module.

// ─────────────────────────────────────────────────────────────────────────────
// Std / 3rd-party imports
// ─────────────────────────────────────────────────────────────────────────────
use rand_core::{CryptoRng, RngCore};
use serde::{Deserialize, Serialize};
use std::fmt;

#[cfg(feature = "schnorrkel")]
use schnorrkel::{
    vrf::{VRFOutput, VRFProof, VRFSignature},
    Keypair, PublicKey, SecretKey, SignatureError,
};

// ─────────────────────────────────────────────────────────────────────────────
// Public types & traits
// ─────────────────────────────────────────────────────────────────────────────

/// Unified error type for all VRF operations.
///
/// The enum purposefully collapses error values from external libraries to a
/// thin wrapper, so that the rest of the codebase never depends on the exact
/// crypto crate we are using internally.
#[derive(Debug, thiserror::Error)]
pub enum VrfError {
    /// The provided proof fails verification.
    #[error("invalid VRF proof")]
    InvalidProof,

    /// The underlying crypto library reported an internal error.
    #[error("cryptographic error: {0}")]
    Crypto(#[from] Box<dyn std::error::Error + Send + Sync>),

    /// Input or output size mismatch.
    #[error("malformed input")]
    MalformedInput,
}

/// A minimal façade over a VRF algorithm.
///
/// Implementations must be deterministic, collision-resistant and produce
/// 32-byte outputs (see `output_size()`).
pub trait VrfProvider: Send + Sync + 'static {
    /// Secret key type – must implement `Serialize` + `Deserialize`
    type Sk: Serialize + for<'de> Deserialize<'de> + Send + Sync;
    /// Public key type – must implement `Serialize` + `Deserialize`
    type Pk: Serialize + for<'de> Deserialize<'de> + Send + Sync + Clone;
    /// Proof type – must implement `Serialize` + `Deserialize`
    type Proof: Serialize + for<'de> Deserialize<'de> + Send + Sync;

    /// Generate a random keypair from a user supplied RNG.
    fn keypair<R: CryptoRng + RngCore>(rng: &mut R) -> (Self::Sk, Self::Pk);

    /// Compute VRF output and proof.
    ///
    /// Returns `(output, proof)`.
    fn prove(
        sk: &Self::Sk,
        message: &[u8],
    ) -> Result<([u8; 32], Self::Proof), VrfError>;

    /// Verify proof and return the VRF output, or an error if proof is invalid.
    fn verify(
        pk: &Self::Pk,
        message: &[u8],
        proof: &Self::Proof,
    ) -> Result<[u8; 32], VrfError>;

    /// Output size in bytes.  Fixed to 32 for now – changing it breaks
    /// consensus, hence the explicit constant method.
    #[inline(always)]
    fn output_size() -> usize {
        32
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Schnorrkel implementation (default)
// ─────────────────────────────────────────────────────────────────────────────
#[cfg(feature = "schnorrkel")]
mod schnorrkel_impl {
    use super::*;
    use rand_core::OsRng;

    /// Wrapper struct used only to satisfy Rust’s orphan rule.
    pub struct SchnorrkelVrf;

    impl VrfProvider for SchnorrkelVrf {
        type Sk = SecretKey;
        type Pk = PublicKey;
        type Proof = VRFSignature;

        fn keypair<R: CryptoRng + RngCore>(rng: &mut R) -> (Self::Sk, Self::Pk) {
            let kp = Keypair::generate_with(rng);
            (kp.secret, kp.public)
        }

        fn prove(
            sk: &Self::Sk,
            message: &[u8],
        ) -> Result<([u8; 32], Self::Proof), VrfError> {
            let ctx = b"CanvasChainSchnorrkelDomainSep";
            let (io, proof, _) = sk.vrf_sign(ctx, message);
            Ok((io.make_bytes::<[u8; 32]>(b"chain-random"), proof))
        }

        fn verify(
            pk: &Self::Pk,
            message: &[u8],
            proof: &Self::Proof,
        ) -> Result<[u8; 32], VrfError> {
            let ctx = b"CanvasChainSchnorrkelDomainSep";
            match pk.vrf_verify(ctx, proof, message) {
                Ok((io, _)) => Ok(io.make_bytes::<[u8; 32]>(b"chain-random")),
                Err(SignatureError::EquationFalse | SignatureError::PointDecompressionError(_)) => {
                    Err(VrfError::InvalidProof)
                }
                Err(e) => Err(VrfError::Crypto(Box::new(e))),
            }
        }
    }

    /// A convenience re-export so callers can simply use `SchnorrkelVrf`.
    pub use SchnorrkelVrf as DefaultVrf;
}

// If the `schnorrkel` feature is not enabled, callers must pick a provider
// manually.  Export a dummy type so that `DefaultVrf` always exists in the
// public API, minimizing `#[cfg]` usage elsewhere.
#[cfg(not(feature = "schnorrkel"))]
pub struct DefaultVrf; // compile-error on use, unless another feature is chosen

// ─────────────────────────────────────────────────────────────────────────────
// Higher-level helper utilities
// ─────────────────────────────────────────────────────────────────────────────

/// Convenience struct holding a keypair for repeated VRF operations.
///
/// This is *not* globally accessible – if you want to run a validator node you
/// have to load your secret key from secure storage and instantiate a
/// `VrfContext` in your own process.
#[derive(Clone)]
pub struct VrfContext<P: VrfProvider> {
    pub secret: P::Sk,
    pub public: P::Pk,
}

impl<P: VrfProvider> VrfContext<P> {
    /// Sign a message, returning `(output, proof)`.
    pub fn prove(&self, msg: &[u8]) -> Result<([u8; 32], P::Proof), VrfError> {
        P::prove(&self.secret, msg)
    }

    /// Verify someone else’s proof.
    pub fn verify(
        &self,
        msg: &[u8],
        proof: &P::Proof,
    ) -> Result<[u8; 32], VrfError> {
        P::verify(&self.public, msg, proof)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Domain-specific helpers
// ─────────────────────────────────────────────────────────────────────────────

/// Given a list of validators and their public keys, use VRF outputs to select
/// the next “composer” in our custom *Proof-of-Inspiration* consensus.
///
/// The algorithm is intentionally deterministic and replayable – all
/// validators compute the same winner once they receive the previous block.
pub fn select_composer<P, I>(
    validators: I,
    round_seed: &[u8; 32],
) -> Result<P::Pk, VrfError>
where
    P: VrfProvider,
    I: IntoIterator<Item = (P::Pk, P::Proof)>,
{
    // Iterate over all VRF proofs, find the minimum hash as winner
    validators
        .into_iter()
        .map(|(pk, proof)| {
            let output = P::verify(&pk, round_seed, &proof)?;
            Ok((pk, output))
        })
        .try_fold(
            None,
            |acc: Option<(P::Pk, [u8; 32])>, item| -> Result<_, VrfError> {
                match (acc, item?) {
                    (None, x) => Ok(Some(x)),
                    (Some((best_pk, best_out)), (pk, out)) => {
                        if out < best_out {
                            Ok(Some((pk, out)))
                        } else {
                            Ok(Some((best_pk, best_out)))
                        }
                    }
                }
            },
        )
        .and_then(|opt| opt.map(|(pk, _)| pk).ok_or(VrfError::MalformedInput))
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────────────
#[cfg(all(test, feature = "schnorrkel"))]
mod tests {
    use super::*;
    use rand_core::OsRng;

    type Provider = schnorrkel_impl::DefaultVrf;

    #[test]
    fn smoke_test_vrf() {
        let mut rng = OsRng;
        let (sk, pk) = Provider::keypair(&mut rng);

        let msg = b"🎨: generative motion blur";
        let (out1, proof) = Provider::prove(&sk, msg).expect("able to sign");
        let out2 = Provider::verify(&pk, msg, &proof).expect("able to verify");
        assert_eq!(out1, out2);
    }

    #[test]
    fn deterministic_selection() {
        let mut rng = OsRng;

        // prepare 5 validators
        let mut validators = Vec::new();
        let round_seed = b"block-1024-seed-beacon";
        for _ in 0..5 {
            let (sk, pk) = Provider::keypair(&mut rng);
            let (_output, proof) =
                Provider::prove(&sk, round_seed).expect("sign");
            validators.push((pk, proof));
        }

        // run selection twice – should pick the same winner
        let winner1 = select_composer::<Provider, _>(validators.clone(), round_seed)
            .expect("selected");
        let winner2 = select_composer::<Provider, _>(validators, round_seed)
            .expect("selected again");
        assert_eq!(
            serde_json::to_string(&winner1).unwrap(),
            serde_json::to_string(&winner2).unwrap()
        );
    }
}
```