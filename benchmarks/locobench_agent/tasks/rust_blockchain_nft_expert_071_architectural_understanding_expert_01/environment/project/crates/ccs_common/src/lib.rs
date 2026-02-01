```rust
//! CanvasChain Symphony – Common primitives & helpers
//!
//! This crate is the canonical place for *shared* types that are re-exported by
//! every micro-service in the CanvasChain Symphony stack.  Keeping them in an
//! isolated crate avoids cyclic dependencies and makes sure we never end up
//! with two incompatible versions of the same `NodeId`, `Event`, or crypto
//! trait floating around in the dependency graph.
//!
//! The crate purposefully stays *lightweight*:  Only foundational, non-domain
//! specific abstractions live here.  Anything that is specific to a single
//! service (e.g. the Marketplace API) must go to the respective crate.

// ─────────────────────────────────────────────────────────────────────────────
// LINTING & CLIPPY
// ─────────────────────────────────────────────────────────────────────────────
#![deny(
    elided_lifetimes_in_paths,
    missing_copy_implementations,
    missing_debug_implementations,
    missing_docs,
    unreachable_pub,
    unused_results,
    clippy::all,
    clippy::pedantic,
    clippy::cargo,
    clippy::unwrap_used,
    clippy::expect_used
)]
#![forbid(unsafe_code)]

use chrono::{DateTime, Utc};
use rand::RngCore;
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use std::{
    fmt,
    sync::Arc,
    time::{Duration, SystemTime},
};
use thiserror::Error;
use uuid::Uuid;

// ─────────────────────────────────────────────────────────────────────────────
// PUBLIC RE-EXPORTS
// ─────────────────────────────────────────────────────────────────────────────

pub use crate::{
    config::{load_configuration, AppConfig},
    crypto::{CryptoScheme, DynSigner},
    error::CcsCommonError,
    events::{EventEnvelope, SymphonyEvent},
    types::{NetworkId, NodeId, Snowflake},
};

// ─────────────────────────────────────────────────────────────────────────────
// MODULE DECLARATIONS
// ─────────────────────────────────────────────────────────────────────────────

mod config;
mod crypto;
mod error;
mod events;
mod types;

// ─────────────────────────────────────────────────────────────────────────────
// PRELUDE
// ─────────────────────────────────────────────────────────────────────────────

/// Wildcard import for convenience.
///
/// Example:
/// ```ignore
/// use ccs_common::prelude::*;
/// ```
pub mod prelude {
    pub use super::{
        load_configuration, AppConfig, CcsCommonError, CryptoScheme, DynSigner, EventEnvelope,
        NetworkId, NodeId, Snowflake, SymphonyEvent,
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// CONFIGURATION MODULE
// ─────────────────────────────────────────────────────────────────────────────

mod config {
    //! Lightweight, layered configuration loader.
    //!
    //! It merges—in the following order—(later overrides earlier):
    //! 1. Static `Settings.toml` file shipped alongside the binary
    //! 2. Environment specific `Settings.{env}.toml`
    //! 3. Environment variables in the `CCS_*` namespace

    use super::*;

    /// Canonical runtime configuration consumed by all services.
    #[derive(Debug, Clone, Deserialize)]
    pub struct AppConfig {
        /// `NATS`, `RabbitMQ`, or `Kafka` URL for the event bus.
        pub event_bus_url: String,
        /// The canonical on-chain network identifier.
        pub network_id: NetworkId,
        /// Human readable service name, used for tracing.
        pub service_name: String,
        /// Crypto configuration.
        pub crypto: CryptoSection,
    }

    /// Crypto related settings.
    #[derive(Debug, Clone, Deserialize)]
    pub struct CryptoSection {
        /// What signature scheme to use (`ed25519`, `bls`, `pq`…).
        pub scheme: CryptoScheme,
        /// Path to the private key file on disk.  If omitted, a fresh key is
        /// generated and kept in memory for the process lifetime.
        pub key_path: Option<String>,
    }

    /// Load configuration by reading layered configuration sources.
    ///
    /// # Errors
    /// * Returns `CcsCommonError::Configuration` if the config could not be
    ///   loaded or deserialized.
    pub fn load_configuration() -> Result<AppConfig, CcsCommonError> {
        let mut settings = config::Config::builder()
            .set_default("service_name", "unnamed_service")
            .map_err(CcsCommonError::configuration)?
            .add_source(config::File::with_name("Settings").required(false))
            // `$CCS_ENV` chooses the environment variant, defaults to `local`.
            .add_source(
                config::File::with_name(&format!(
                    "Settings.{}",
                    std::env::var("CCS_ENV").unwrap_or_else(|_| "local".to_owned())
                ))
                .required(false),
            )
            .add_source(config::Environment::with_prefix("CCS").separator("__"))
            .build()
            .map_err(CcsCommonError::configuration)?;

        // We want *strongly typed* config reading—`serde` deserializes into our
        // struct and fails when unknown / missing keys occur.
        settings
            .try_deserialize::<AppConfig>()
            .map_err(CcsCommonError::configuration)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// ERROR MODULE
// ─────────────────────────────────────────────────────────────────────────────

mod error {
    //! Error helpers shared across crates.

    use super::*;

    /// Top-level, catch-all error enum for the `ccs_common` crate.
    #[derive(Debug, Error)]
    #[non_exhaustive]
    pub enum CcsCommonError {
        /// Crypto related error.
        #[error("crypto error: {0}")]
        Crypto(String),

        /// Serialization / deserialization failed.
        #[error("serde error: {0}")]
        Serde(#[from] serde_json::Error),

        /// IO failed.
        #[error("io error: {0}")]
        Io(#[from] std::io::Error),

        /// Invalid data encountered.
        #[error("validation error: {0}")]
        Validation(String),

        /// Time or clock error.
        #[error("time error: {0}")]
        Time(#[from] humantime::DurationError),

        /// Configuration parsing failed.
        #[error("configuration error: {0}")]
        Configuration(String),

        /// Catch-all variant.
        #[error("internal error: {0}")]
        Internal(String),
    }

    impl CcsCommonError {
        pub(crate) fn crypto<E: fmt::Display>(err: E) -> Self {
            Self::Crypto(err.to_string())
        }
        pub(crate) fn configuration<E: fmt::Display>(err: E) -> Self {
            Self::Configuration(err.to_string())
        }
    }

    // Conveniences for `Result<_, CcsCommonError>`
    pub type Result<T, E = CcsCommonError> = std::result::Result<T, E>;
}

// ─────────────────────────────────────────────────────────────────────────────
// TYPES MODULE
// ─────────────────────────────────────────────────────────────────────────────

mod types {
    //! Lightweight, plainly copyable type aliases.

    use super::*;

    /// Unique identifier for every CanvasChain node.
    pub type NodeId = Uuid;

    /// Global network identifier (`mainnet`, `testnet`, `local`, …).
    #[derive(
        Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq, Ord, PartialOrd, Hash,
    )]
    #[serde(rename_all = "snake_case")]
    pub enum NetworkId {
        Mainnet,
        Testnet,
        Local,
        Other(&'static str),
    }

    impl fmt::Display for NetworkId {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            match self {
                Self::Mainnet => write!(f, "mainnet"),
                Self::Testnet => write!(f, "testnet"),
                Self::Local => write!(f, "local"),
                Self::Other(id) => write!(f, "{id}"),
            }
        }
    }

    /// Snowflake style (time-sortable) 64-bit ID used for NFTs, movements, …
    ///
    /// Most services require globally unique yet *increasing* identifiers so
    /// they can order events without extra DB round-trips.
    #[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq, Hash)]
    #[repr(transparent)]
    pub struct Snowflake(pub u64);

    impl Snowflake {
        /// Generate a new snowflake using system time and random entropy.
        pub fn new() -> Self {
            // 41 bits millisecond timestamp, 23 bits random entropy.
            let millis = SystemTime::now()
                .duration_since(SystemTime::UNIX_EPOCH)
                .expect("time went backwards")
                .as_millis() as u64
                & 0x1ffff_ffff_ffff; // 41 bits

            let mut rng = rand::thread_rng();
            let random: u64 = rng.next_u32() as u64 & 0x7f_ffff; // 23 bits

            Snowflake((millis << 23) | random)
        }

        /// Extract creation time.
        #[must_use]
        pub fn timestamp(&self) -> DateTime<Utc> {
            let millis = self.0 >> 23;
            Utc.timestamp_millis(i64::try_from(millis).unwrap_or_default())
        }
    }

    impl fmt::Display for Snowflake {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            write!(f, "{:x}", self.0)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// EVENTS MODULE
// ─────────────────────────────────────────────────────────────────────────────

mod events {
    //! Generic event envelope shared by every micro-service.
    //!
    //! The actual event payload is encoded in `body` and can be any serializable
    //! type implementing [`SymphonyEvent`].

    use super::*;

    /// Blanket trait for event payloads.
    pub trait SymphonyEvent:
        fmt::Debug + Serialize + DeserializeOwned + Send + Sync + 'static
    {
        /// Category string used for routing (`nft.minted`, …).
        const TOPIC: &'static str;
    }

    /// Thin wrapper adding tracing / metadata around events.
    #[derive(Debug, Clone, Serialize, Deserialize)]
    pub struct EventEnvelope<T: SymphonyEvent> {
        /// Unique identifier for de-duplication.
        pub id: Snowflake,
        /// ID of the node that *originated* the event.
        pub origin: NodeId,
        /// Event creation time in UTC.
        pub timestamp: DateTime<Utc>,
        /// Arbitrary correlation / request id used for tracing.
        pub correlation_id: Uuid,
        /// Actual business event.
        pub body: T,
    }

    impl<T: SymphonyEvent> EventEnvelope<T> {
        /// Wrap a raw business event in an [`EventEnvelope`].
        #[must_use]
        pub fn new(origin: NodeId, body: T) -> Self {
            Self {
                id: Snowflake::new(),
                origin,
                timestamp: Utc::now(),
                correlation_id: Uuid::new_v4(),
                body,
            }
        }

        /// Propagate existing `correlation_id` (useful for RPC).
        #[must_use]
        pub fn propagate(origin: NodeId, parent: &Self, body: T) -> Self {
            Self {
                id: Snowflake::new(),
                origin,
                timestamp: Utc::now(),
                correlation_id: parent.correlation_id,
                body,
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// CRYPTO MODULE
// ─────────────────────────────────────────────────────────────────────────────

mod crypto {
    //! Strategy based cryptography helpers.
    //!
    //! The node can plug & play different signature schemes without recompiling
    //! the whole stack thanks to `dyn` dispatch.  A pointer to the concrete
    //! implementation is stored in [`DynSigner`].

    use super::*;
    use async_trait::async_trait;

    /// Supported signature schemes.  More can be added behind feature flags
    /// without breaking the API surface.
    #[derive(
        Debug, Clone, Copy, Eq, PartialEq, Hash, Serialize, Deserialize, Ord, PartialOrd,
    )]
    #[serde(rename_all = "snake_case")]
    pub enum CryptoScheme {
        /// Ed25519 (default)
        Ed25519,
        /// BLS12-381 aggregate signatures
        #[cfg(feature = "bls")]
        Bls,
        /// Experimental post-quantum lattice signatures
        #[cfg(feature = "pq")]
        PostQuantum,
    }

    /// Signature bytes (scheme dependent length).
    pub type Signature = Vec<u8>;

    /// Unified async trait for signing and verifying payloads.
    ///
    /// The trait is async because implementations may delegate to HSMs or other
    /// *slow* hardware devices.
    #[async_trait]
    pub trait Signer: Send + Sync + fmt::Debug {
        /// Identify the underlying scheme.
        fn scheme(&self) -> CryptoScheme;

        /// Return the public key as raw bytes (for network propagation).
        fn public_key_raw(&self) -> Vec<u8>;

        /// Sign an arbitrary message.
        ///
        /// # Errors
        /// * Returns [`CcsCommonError::Crypto`] on failure.
        async fn sign(&self, message: &[u8]) -> Result<Signature, CcsCommonError>;

        /// Verify a signature for a message.
        async fn verify(
            &self,
            message: &[u8],
            signature: &[u8],
        ) -> Result<bool, CcsCommonError>;
    }

    /// Ergonomic type alias.
    pub type DynSigner = Arc<dyn Signer>;

    // ─────────────────────────────────────────────────────────────────────────
    // ED25519 IMPLEMENTATION
    // ─────────────────────────────────────────────────────────────────────────
    #[cfg(feature = "ed25519")]
    mod ed25519_impl {
        use super::*;
        use ed25519_dalek::{Keypair, PublicKey, Signature as DalekSig, Signer as _, Verifier as _};
        use rand::thread_rng;
        use tokio::task;

        /// Thin wrapper around an Ed25519 keypair.
        #[derive(Debug)]
        pub(crate) struct Ed25519Signer(Keypair);

        impl Ed25519Signer {
            /// Load from disk or generate a fresh random keypair.
            pub fn load_or_generate(path: Option<&str>) -> Result<Self, CcsCommonError> {
                if let Some(p) = path {
                    if std::path::Path::new(p).exists() {
                        let bytes = std::fs::read(p)?;
                        let keypair =
                            Keypair::from_bytes(&bytes).map_err(CcsCommonError::crypto)?;
                        Ok(Self(keypair))
                    } else {
                        // Generate and store.
                        let mut rng = thread_rng();
                        let keypair = Keypair::generate(&mut rng);
                        std::fs::write(p, &keypair.to_bytes())?;
                        Ok(Self(keypair))
                    }
                } else {
                    let mut rng = thread_rng();
                    Ok(Self(Keypair::generate(&mut rng)))
                }
            }
        }

        #[async_trait]
        impl Signer for Ed25519Signer {
            fn scheme(&self) -> CryptoScheme {
                CryptoScheme::Ed25519
            }

            fn public_key_raw(&self) -> Vec<u8> {
                self.0.public.to_bytes().to_vec()
            }

            async fn sign(&self, message: &[u8]) -> Result<Signature, CcsCommonError> {
                let keypair = self.0.clone();
                let msg = message.to_vec();
                task::spawn_blocking(move || {
                    let sig: DalekSig = keypair.sign(&msg);
                    Ok(sig.to_bytes().to_vec())
                })
                .await
                .map_err(|e| CcsCommonError::crypto(e))?
            }

            async fn verify(
                &self,
                message: &[u8],
                signature: &[u8],
            ) -> Result<bool, CcsCommonError> {
                let pk: PublicKey = self.0.public;
                let sig = DalekSig::from_bytes(signature).map_err(CcsCommonError::crypto)?;
                let msg = message.to_vec();
                task::spawn_blocking(move || Ok(pk.verify(&msg, &sig).is_ok()))
                    .await
                    .map_err(|e| CcsCommonError::crypto(e))
            }
        }

        /// Factory helper
        pub(crate) fn build(path: Option<&str>) -> Result<DynSigner, CcsCommonError> {
            Ok(Arc::new(Ed25519Signer::load_or_generate(path)?))
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // BLS IMPLEMENTATION (optional)
    // ─────────────────────────────────────────────────────────────────────────
    #[cfg(feature = "bls")]
    mod bls_impl {
        // Placeholder—full BLS implementation omitted for brevity.
    }

    // ─────────────────────────────────────────────────────────────────────────
    // PUBLIC FACTORY
    // ─────────────────────────────────────────────────────────────────────────

    /// Build an implementation for the requested scheme.
    ///
    /// # Errors
    /// * Returns [`CcsCommonError::Crypto`] if the scheme is not compiled in or
    ///   the keyfile could not be read.
    pub fn build_signer(
        scheme: CryptoScheme,
        key_path: Option<&str>,
    ) -> Result<DynSigner, CcsCommonError> {
        match scheme {
            #[cfg(feature = "ed25519")]
            CryptoScheme::Ed25519 => ed25519_impl::build(key_path),
            #[cfg(feature = "bls")]
            CryptoScheme::Bls => bls_impl::build(key_path),
            _ => Err(CcsCommonError::crypto(format!(
                "scheme {scheme:?} not supported in this build"
            ))),
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// SEMVER GUARANTEES
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn roundtrip_sign_verify() {
        let signer = crypto::build_signer(CryptoScheme::Ed25519, None).unwrap();
        let msg = b"hello symphony";
        let sig = signer.sign(msg).await.unwrap();
        assert!(signer.verify(msg, &sig).await.unwrap());
    }

    #[test]
    fn snowflake_monotonicity() {
        let a = Snowflake::new();
        let b = Snowflake::new();
        assert!(b.0 > a.0);
    }
}
```