```rust
//! BLS12-381 (minimal public key) signature implementation used by CanvasChain
//! Symphony.  
//!
//! The code below wraps the `blst` library and exposes a curve-agnostic
//! interface (`SignatureScheme`) so that higher-level components can switch
//! between Ed25519, BLS or any other algorithm at runtime using the Strategy
//! pattern.
//!
//! • Public keys live in G1  
//! • Signatures live in G2  
//! • We use the “minimal-pubkey” variant because it yields the smallest on-
//!   chain footprint for public keys which appear far more frequently than
//!   signatures in CanvasChain’s consensus layer.
//!
//! IMPORTANT:  The pairing check is *constant-time* inside `blst`; do **NOT**
//! attempt to optimise it yourself unless you really know what you are doing.

// External crates ----------------------------------------------------------------

use blst::min_pk as blst_core;
use blst_core::{PublicKey as BlstPk, SecretKey as BlstSk, Signature as BlstSig};
use rand_core::{CryptoRng, RngCore};
use serde::{Deserialize, Serialize};
use thiserror::Error;

// Internal exports ---------------------------------------------------------------

pub use blst_core::BLST_ERROR;

// Constants ----------------------------------------------------------------------

/// Domain-separation tag as recommended by IETF draft-irtf-cfrg-bls-sign.
const BLS_DST: &[u8] = b"BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_CANVASCHAIN";

// Error handling -----------------------------------------------------------------

/// Canonical error type returned by the crypto layer.
#[derive(Debug, Error)]
pub enum CryptoError {
    #[error("BLST error: {0:?}")]
    Blst(BLST_ERROR),

    #[error("Aggregation failed: inconsistent lengths")]
    LengthMismatch,

    #[error("Invalid serialization: {0}")]
    Bincode(String),

    #[error("{0}")]
    Generic(&'static str),
}

impl From<BLST_ERROR> for CryptoError {
    fn from(err: BLST_ERROR) -> Self {
        // BLST_OK (0) never maps here because callers short-circuit.
        CryptoError::Blst(err)
    }
}

impl From<bincode::Error> for CryptoError {
    fn from(err: bincode::Error) -> Self {
        CryptoError::Bincode(err.to_string())
    }
}

// Strategy trait ------------------------------------------------------------------

/// Generic interface implemented by every signature scheme in `ccs_crypto`.
pub trait SignatureScheme: Send + Sync + 'static {
    type PrivateKey: Sized + Serialize + for<'de> Deserialize<'de>;
    type PublicKey: Sized + Serialize + for<'de> Deserialize<'de>;
    type Signature: Sized + Serialize + for<'de> Deserialize<'de>;

    /// Human-readable algorithm name (e.g. `"BLS12-381 MinPk"`).
    const NAME: &'static str;

    /// Create a new keypair using the supplied CSPRNG.
    fn keypair<R: RngCore + CryptoRng>(
        rng: &mut R,
    ) -> Result<(Self::PrivateKey, Self::PublicKey), CryptoError>;

    /// Sign an arbitrary byte slice.
    fn sign(
        sk: &Self::PrivateKey,
        msg: &[u8],
        dst: &[u8],
    ) -> Result<Self::Signature, CryptoError>;

    /// Verify a signature.
    fn verify(
        pk: &Self::PublicKey,
        msg: &[u8],
        sig: &Self::Signature,
        dst: &[u8],
    ) -> Result<(), CryptoError>;
}

// BLS key types -------------------------------------------------------------------

/// Wrapper around `blst::min_pk::SecretKey` so we can derive `Serialize`.
#[derive(Clone, Serialize, Deserialize)]
pub struct BlsPrivateKey(
    #[serde(with = "serde_bytes")] Vec<u8>, /* 32 bytes, little-endian */
);

/// Wrapper around `blst::min_pk::PublicKey`.
#[derive(Clone, Serialize, Deserialize)]
pub struct BlsPublicKey(
    #[serde(with = "serde_bytes")] Vec<u8>, /* 48 bytes (compressed G1) */
);

/// Wrapper around `blst::min_pk::Signature`.
#[derive(Clone, Serialize, Deserialize)]
pub struct BlsSignature(
    #[serde(with = "serde_bytes")] Vec<u8>, /* 96 bytes (compressed G2) */
);

// Helper conversions --------------------------------------------------------------

impl TryFrom<&BlsPrivateKey> for BlstSk {
    type Error = CryptoError;

    fn try_from(value: &BlsPrivateKey) -> Result<Self, Self::Error> {
        Ok(BlstSk::from_bytes(&value.0)?)
    }
}

impl TryFrom<&BlsPublicKey> for BlstPk {
    type Error = CryptoError;

    fn try_from(value: &BlsPublicKey) -> Result<Self, Self::Error> {
        Ok(BlstPk::from_bytes(&value.0)?)
    }
}

impl TryFrom<&BlsSignature> for BlstSig {
    type Error = CryptoError;

    fn try_from(value: &BlsSignature) -> Result<Self, Self::Error> {
        Ok(BlstSig::from_bytes(&value.0)?)
    }
}

// The concrete strategy -----------------------------------------------------------

/// BLS12-381 minimal-pubkey signature scheme.
pub struct Bls12381MinPk;

impl SignatureScheme for Bls12381MinPk {
    type PrivateKey = BlsPrivateKey;
    type PublicKey = BlsPublicKey;
    type Signature = BlsSignature;

    const NAME: &'static str = "BLS12-381 MinPk";

    fn keypair<R: RngCore + CryptoRng>(
        rng: &mut R,
    ) -> Result<(Self::PrivateKey, Self::PublicKey), CryptoError> {
        // Secret key: random 256-bit scalar.
        let sk = BlstSk::generate(rng);
        let pk = BlstPk::from(&sk);
        Ok((
            BlsPrivateKey(sk.to_bytes().to_vec()),
            BlsPublicKey(pk.compress().to_vec()),
        ))
    }

    fn sign(
        sk: &Self::PrivateKey,
        msg: &[u8],
        dst: &[u8],
    ) -> Result<Self::Signature, CryptoError> {
        let sk = BlstSk::try_from(sk)?;
        let sig = sk.sign(msg, dst, &[]); // no aug, no optional key-info
        Ok(BlsSignature(sig.compress().to_vec()))
    }

    fn verify(
        pk: &Self::PublicKey,
        msg: &[u8],
        sig: &Self::Signature,
        dst: &[u8],
    ) -> Result<(), CryptoError> {
        let pk = BlstPk::try_from(pk)?;
        let sig = BlstSig::try_from(sig)?;

        // Constant-time affine conversion happens inside `verify`.
        match sig.verify(true, msg, dst, &pk, &[]) {
            BLST_ERROR::BLST_SUCCESS => Ok(()),
            e => Err(e.into()),
        }
    }
}

// Aggregation helpers -------------------------------------------------------------

impl Bls12381MinPk {
    /// Aggregate many signatures into one, returning the compressed
    /// representation that can be further verified or aggregated.
    pub fn aggregate(signatures: &[BlsSignature]) -> Result<BlsSignature, CryptoError> {
        let mut agg = BlstSig::aggregate(
            &signatures
                .iter()
                .map(BlstSig::try_from)
                .collect::<Result<Vec<_>, _>>()?,
            true, /* verify individually before adding */
        )?;
        agg.to_affine(); // required before compression
        Ok(BlsSignature(agg.compress().to_vec()))
    }

    /// Verify an aggregate signature against individual public keys and
    /// messages. All slices must have identical length.
    pub fn verify_aggregate(
        pks: &[BlsPublicKey],
        msgs: &[&[u8]],
        sig: &BlsSignature,
        dst: &[u8],
    ) -> Result<(), CryptoError> {
        if pks.len() != msgs.len() {
            return Err(CryptoError::LengthMismatch);
        }

        let sig = BlstSig::try_from(sig)?;
        let pks: Vec<BlstPk> = pks.iter().map(BlstPk::try_from).collect::<Result<_, _>>()?;

        // SAFETY: The `msgs` slice lives for the entirety of this function.
        let msg_refs: Vec<_> = msgs.iter().map(|m| *m).collect();

        match sig.aggregate_verify(true, &pks, &msg_refs, dst) {
            BLST_ERROR::BLST_SUCCESS => Ok(()),
            e => Err(e.into()),
        }
    }
}

// Serde helpers -------------------------------------------------------------------

mod serde_bytes {
    use serde::{Deserialize, Deserializer, Serializer};

    pub fn serialize<S: Serializer>(bytes: &Vec<u8>, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_bytes(bytes)
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<u8>, D::Error> {
        Ok(<Vec<u8>>::deserialize(d)?)
    }
}

// Tests ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use rand_core::OsRng;

    #[test]
    fn roundtrip() {
        let msg = b"CanvasChain symphony 🎶";
        let (sk, pk) = Bls12381MinPk::keypair(&mut OsRng).unwrap();
        let sig = Bls12381MinPk::sign(&sk, msg, BLS_DST).unwrap();
        assert!(Bls12381MinPk::verify(&pk, msg, &sig, BLS_DST).is_ok());
    }

    #[test]
    fn aggregation() {
        const N: usize = 8;
        let mut pks = Vec::with_capacity(N);
        let mut sigs = Vec::with_capacity(N);
        let mut msgs = Vec::with_capacity(N);

        for i in 0..N {
            let msg = format!("note #{i}");
            let (sk, pk) = Bls12381MinPk::keypair(&mut OsRng).unwrap();
            let sig = Bls12381MinPk::sign(&sk, msg.as_bytes(), BLS_DST).unwrap();

            pks.push(pk);
            sigs.push(sig);
            msgs.push(msg); // store as String to keep ownership
        }

        let agg = Bls12381MinPk::aggregate(&sigs).unwrap();
        let msg_refs: Vec<&[u8]> = msgs.iter().map(|s| s.as_bytes()).collect();

        assert!(Bls12381MinPk::verify_aggregate(&pks, &msg_refs, &agg, BLS_DST).is_ok());
    }
}
```