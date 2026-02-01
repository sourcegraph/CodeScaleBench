```rust
//! services/minting_service/src/logic/metadata_handler.rs
//!
//! Contains the logic for building, validating and publishing NFT metadata
//! during the minting phase of CanvasChain Symphony.
//!
//! The handler is intentionally decoupled from any concrete storage backend
//! (e.g. IPFS, Arweave, S3).  A pluggable [`MetadataStore`] trait makes it
//! possible to swap the persistence layer without changing business logic,
//! allowing integrators to choose whatever content-addressable storage best
//! fits their operational constraints.
//!
//! The module is `async`-first and designed to be used inside a Tokio runtime
//! by the minting gRPC service.

use std::{
    collections::hash_map::DefaultHasher,
    hash::{Hash, Hasher},
    num::NonZeroUsize,
    sync::Arc,
};

use async_trait::async_trait;
use lru::LruCache;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use thiserror::Error;
use tokio::sync::Mutex;

/// A succinct alias for a URI returned by a [`MetadataStore`] implementation.
///
/// The URI SHOULD be content-addressable (e.g. `ipfs://<cid>`, `ar://<txid>`),
/// but this is not enforced by the interface.
pub type MetadataUri = String;

/// Business errors that might occur while building or persisting metadata.
#[derive(Debug, Error)]
pub enum MetadataError {
    #[error("metadata validation failed: {0}")]
    Validation(String),

    #[error("failed to serialize metadata to JSON: {0}")]
    Serialization(#[from] serde_json::Error),

    #[error("persistence layer error: {0}")]
    Store(#[from] anyhow::Error),

    #[error("unexpected internal error: {0}")]
    Internal(String),
}

/// Generic, async persistence layer for NFT metadata.
///
/// The implementation can be backed by IPFS, Arweave, S3, a local file system,
/// or any content-addressable store that returns a stable URI.
#[async_trait]
pub trait MetadataStore: Send + Sync {
    /// Persists raw JSON and returns its URI once available on the network.
    async fn put(&self, json: &[u8]) -> Result<MetadataUri, MetadataError>;
}

/// Concrete IPFS implementation (feature-gated for optional compilation).
/// Requires the `ipfs-api` crate.
#[cfg(feature = "ipfs")]
pub mod ipfs_store {
    use super::*;
    use ipfs_api::IpfsClient;

    /// Wraps an `IpfsClient` and implements [`MetadataStore`].
    pub struct IpfsMetadataStore {
        client: IpfsClient,
    }

    impl IpfsMetadataStore {
        pub fn new(client: IpfsClient) -> Self {
            Self { client }
        }
    }

    #[async_trait]
    impl MetadataStore for IpfsMetadataStore {
        async fn put(&self, json: &[u8]) -> Result<MetadataUri, MetadataError> {
            use futures::StreamExt;

            let data = bytes::Bytes::copy_from_slice(json);
            let res = self
                .client
                .add(data.into())
                .map(|result| result.map(|added| format!("ipfs://{}", added.hash)))
                .await;

            res.map_err(|e| MetadataError::Store(anyhow::anyhow!(e)))
        }
    }
}

/// EIP-721 & EIP-1155 compatible attribute.
#[derive(Debug, Serialize, Deserialize, Clone, PartialEq, Eq, Hash)]
pub struct Attribute {
    pub trait_type: String,
    pub value: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub display_type: Option<String>,
}

/// Canonical metadata schema used across CanvasChain Symphony.
///
/// Additional fields can be added by individual *movements* of the symphony
/// through the `extra` map, keeping the core schema forward-compatible.
#[derive(Debug, Serialize, Deserialize, Clone, PartialEq, Eq, Hash)]
pub struct Metadata {
    pub name: String,
    pub description: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub image: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub animation_url: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty", default)]
    pub attributes: Vec<Attribute>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub external_url: Option<String>,
    #[serde(flatten)]
    pub extra: std::collections::BTreeMap<String, serde_json::Value>,
}

/// Validates that a [`Metadata`] instance follows the minimum Symphony
/// requirements. External contracts may employ stricter rules.
fn validate_metadata(meta: &Metadata) -> Result<(), MetadataError> {
    if meta.name.trim().is_empty() {
        return Err(MetadataError::Validation("name is mandatory".into()));
    }
    if meta.description.trim().is_empty() {
        return Err(MetadataError::Validation("description is mandatory".into()));
    }
    Ok(())
}

/// Container for building, caching and persisting NFT metadata.
pub struct MetadataHandler {
    store: Arc<dyn MetadataStore>,
    cache: Mutex<LruCache<u64, MetadataUri>>,
}

impl MetadataHandler {
    /// Constructs a new handler with a supplied persistence layer.
    ///
    /// `cache_size` determines how many metadata blobs are memoized in-memory.
    /// A sensible default is 1024 for a micro-service.
    pub fn new(store: Arc<dyn MetadataStore>, cache_size: NonZeroUsize) -> Self {
        Self {
            store,
            cache: Mutex::new(LruCache::new(cache_size)),
        }
    }

    /// Hashes a [`Metadata`] instance into a stable `u64` key for `LruCache`.
    fn cache_key(meta: &Metadata) -> u64 {
        let mut hasher = DefaultHasher::new();
        meta.hash(&mut hasher);
        hasher.finish()
    }

    /// Generates JSON, validates the metadata, persists it through the chosen
    /// [`MetadataStore`] and returns the resulting URI.
    ///
    /// The operation is cached to avoid re-uploading identical blobs.
    pub async fn handle(&self, meta: Metadata) -> Result<MetadataUri, MetadataError> {
        validate_metadata(&meta)?;

        let key = Self::cache_key(&meta);

        // Fast path: in-memory cache hit
        {
            let mut cache = self.cache.lock().await;
            if let Some(uri) = cache.get(&key) {
                return Ok(uri.clone());
            }
        }

        // Serialize to canonical, deterministic JSON
        let json_blob = serde_json::to_vec(&meta)?;
        let _sha256 = sha256_hex(&json_blob); // keep for debugging / auditing

        // Persist using the concrete store
        let uri = self.store.put(&json_blob).await?;

        // Memorize result
        {
            let mut cache = self.cache.lock().await;
            cache.put(key, uri.clone());
        }

        Ok(uri)
    }
}

/// Computes a hex-encoded SHA-256 digest for diagnostic purposes.
pub fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hex::encode(hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    /// Simple in-memory dummy store used for unit tests.
    struct DummyStore {
        // Simulate deduplication by storing unique hashes
        counter: AtomicUsize,
    }

    #[async_trait]
    impl MetadataStore for DummyStore {
        async fn put(&self, _json: &[u8]) -> Result<MetadataUri, MetadataError> {
            let id = self.counter.fetch_add(1, Ordering::SeqCst);
            Ok(format!("mem://{}", id))
        }
    }

    #[tokio::test]
    async fn test_handler_deduplication() {
        let store = Arc::new(DummyStore {
            counter: AtomicUsize::new(0),
        });
        let handler = MetadataHandler::new(store, NonZeroUsize::new(16).unwrap());

        let meta = Metadata {
            name: "Canvas #1".into(),
            description: "Genesis piece".into(),
            image: Some("ipfs://Qm123".into()),
            animation_url: None,
            attributes: vec![],
            external_url: None,
            extra: Default::default(),
        };

        let uri1 = handler.handle(meta.clone()).await.unwrap();
        let uri2 = handler.handle(meta).await.unwrap();

        assert_eq!(uri1, uri2, "cached URI should be identical");
    }

    #[tokio::test]
    async fn test_validation_failure() {
        let store = Arc::new(DummyStore {
            counter: AtomicUsize::new(0),
        });
        let handler = MetadataHandler::new(store, NonZeroUsize::new(16).unwrap());

        let bad_meta = Metadata {
            name: "".into(),
            description: "".into(),
            image: None,
            animation_url: None,
            attributes: vec![],
            external_url: None,
            extra: Default::default(),
        };

        let err = handler.handle(bad_meta).await.unwrap_err();
        matches!(err, MetadataError::Validation(_));
    }
}
```