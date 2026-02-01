```rust
//! Proxy minter implementation for the CanvasChain Symphony minting
//! micro-service.  
//!
//! The proxy routes incoming “mint” requests to a concrete backend that
//! understands how to talk to the target blockchain (e.g. CanvasChain,
//! Ethereum, Solana).  
//!
//! Motivations & design notes
//! --------------------------
//! • Avoids direct dependency between the public gRPC API layer and any
//!   single blockchain implementation (Proxy Pattern).  
//! • Enables hot-swapping of minters at runtime (e.g. blue/green
//!   deployments or chain upgrades).  
//! • Decouples side-effects (event emission, metrics) via small traits so
//!   the code can be re-used in unit tests without spinning the whole
//!   service.  
//!
//! # Examples
//!
//! ```no_run
//! use std::sync::Arc;
//! use minting_service::logic::proxy_minter::*;
//!
//! #[tokio::main]
//! async fn main() -> anyhow::Result<()> {
//!     let mut proxy = ProxyMinter::default();
//!
//!     // Register a dummy backend for the "localnet" network.
//!     proxy.register_backend(
//!         "localnet".to_owned(),
//!         Arc::new(DummyBackend::default()),
//!     );
//!
//!     let req = MintRequest {
//!         network: "localnet".into(),
//!         creator: "0xDEADBEEF".into(),
//!         payload: b"hello-world".to_vec(),
//!         royalties_bps: 500, // 5%
//!     };
//!
//!     let res = proxy.mint(req).await?;
//!     println!("Token minted: {:?}", res.token_id);
//!     Ok(())
//! }
//! ```
//!
//! Production backends live in `services/minting_service/src/backends`.

use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, SystemTime},
};

use async_trait::async_trait;
use parking_lot::RwLock;
use rand::{distributions::Alphanumeric, Rng};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokio::{task, time};

/// Strongly-typed error returned from mint operations.
#[derive(Debug, Error)]
pub enum MintError {
    #[error("backend for network `{0}` not found")]
    BackendNotFound(String),

    #[error("backend rejected request: {0}")]
    BackendRejected(String),

    #[error("backend returned malformed data: {0}")]
    MalformedBackendResponse(String),

    #[error("internal IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("internal channel error: {0}")]
    Channel(#[from] tokio::sync::oneshot::error::RecvError),

    #[error("unexpected: {0}")]
    Unexpected(String),
}

/// Request data needed to mint a new multilayer NFT.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MintRequest {
    /// Target network (e.g. "canvas", "ethereum-goerli", "solana-dev").
    pub network: String,

    /// Wallet/creator address.
    pub creator: String,

    /// Raw bytes of the art seed or metadata root CID.
    pub payload: Vec<u8>,

    /// Royalties in basis point (0-10000).
    pub royalties_bps: u16,
}

/// Successful mint response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MintResponse {
    /// Chain-specific token identifier.  
    /// Could be `u128` for CanvasChain or `String` for Ethereum.
    pub token_id: String,

    /// When the mint was finalized (epoch ms).
    pub timestamp: u64,

    /// Network echo.
    pub network: String,
}

#[async_trait]
pub trait MinterBackend: Send + Sync + 'static {
    /// Perform the actual minting transaction.
    ///
    /// Implementations should be **idempotent**; the proxy can retry the call
    /// if the previous attempt timed out.
    async fn mint(&self, req: MintRequest) -> Result<MintResponse, MintError>;

    /// Optional liveness probe. Defaults to healthy.
    async fn health_check(&self) -> bool {
        true
    }
}

/// Simple bus so we can fire-and-forget events without forcing a concrete
/// implementation (Kafka, NATS, Postgres LISTEN/NOTIFY …).
#[async_trait]
pub trait EventBus: Send + Sync {
    async fn publish<T: Serialize + Send + Sync>(&self, topic: &str, payload: &T);
}

/// Proxy that multiplexes mint requests to registered backends.
pub struct ProxyMinter {
    backends: RwLock<HashMap<String, Arc<dyn MinterBackend>>>,
    bus: Arc<dyn EventBus>,
    /// Timeout for backend calls.
    backend_timeout: Duration,
}

impl Default for ProxyMinter {
    fn default() -> Self {
        Self::with_event_bus(Arc::new(NullBus))
    }
}

impl ProxyMinter {
    /// Build a new proxy with a custom event bus.
    pub fn with_event_bus(bus: Arc<dyn EventBus>) -> Self {
        Self {
            backends: RwLock::new(HashMap::new()),
            bus,
            // 15s is a reasonable default given our block time.
            backend_timeout: Duration::from_secs(15),
        }
    }

    /// Register (or override) a backend for the given network.
    pub fn register_backend(&self, network: String, backend: Arc<dyn MinterBackend>) {
        self.backends.write().insert(network, backend);
    }

    /// Returns the list of networks currently supported.
    pub fn supported_networks(&self) -> Vec<String> {
        self.backends.read().keys().cloned().collect()
    }

    /// Mint an NFT, selecting the backend by `req.network`.
    pub async fn mint(&self, req: MintRequest) -> Result<MintResponse, MintError> {
        let backend = {
            let map = self.backends.read();
            map.get(&req.network)
                .cloned()
                .ok_or_else(|| MintError::BackendNotFound(req.network.clone()))?
        };

        // Spawn a timeout wrapper so we don’t wait forever if the chain stalls.
        let (tx, rx) = tokio::sync::oneshot::channel();

        let req_clone = req.clone();
        task::spawn(async move {
            let _ = tx.send(backend.mint(req_clone).await);
        });

        let res = time::timeout(self.backend_timeout, rx)
            .await
            .map_err(|_| MintError::BackendRejected("timeout".into()))??;

        // Fire side-effects *after* the mint succeeded so we don’t spam events.
        self.bus
            .publish("minting.events.v1", &res)
            .await; /* ignoring result intentionally */

        Ok(res)
    }
}

/* -------------------------------------------------------------------------- */
/*                               Dummy helpers                                */
/* -------------------------------------------------------------------------- */

/// No-op event bus for unit tests & local dev.
pub struct NullBus;

#[async_trait]
impl EventBus for NullBus {
    async fn publish<T: Serialize + Send + Sync>(&self, _topic: &str, _payload: &T) {
        // swallow all messages
    }
}

/// Extremely naive backend for tests/dev.  
/// Generates random token IDs and sleeps a bit to simulate chain latency.
#[derive(Default)]
pub struct DummyBackend;

#[async_trait]
impl MinterBackend for DummyBackend {
    async fn mint(&self, req: MintRequest) -> Result<MintResponse, MintError> {
        // Fake argument validation.
        if req.royalties_bps > 10_000 {
            return Err(MintError::BackendRejected(
                "royalties cannot exceed 100%".into(),
            ));
        }

        // Simulate some async work.
        time::sleep(Duration::from_millis(400)).await;

        let token_id: String = rand::thread_rng()
            .sample_iter(&Alphanumeric)
            .take(12)
            .map(char::from)
            .collect();

        Ok(MintResponse {
            token_id,
            timestamp: SystemTime::now()
                .duration_since(SystemTime::UNIX_EPOCH)
                .map_err(|e| MintError::Unexpected(e.to_string()))?
                .as_millis() as u64,
            network: req.network,
        })
    }
}

/* -------------------------------------------------------------------------- */
/*                                   Tests                                    */
/* -------------------------------------------------------------------------- */

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn dummy_backend_works() {
        let proxy = ProxyMinter::default();
        proxy.register_backend("local".into(), Arc::new(DummyBackend));

        let req = MintRequest {
            network: "local".into(),
            creator: "artist01".into(),
            payload: vec![1, 2, 3],
            royalties_bps: 750,
        };

        let res = proxy.mint(req.clone()).await.unwrap();
        assert_eq!(res.network, "local");
        assert!(!res.token_id.is_empty());

        // Repeat the same request to ensure idempotency ->
        // DummyBackend always succeeds, but in real life backends
        // should detect duplicates.
        let _ = proxy.mint(req).await.unwrap();
    }

    #[tokio::test]
    async fn unsupported_network_fails() {
        let proxy = ProxyMinter::default();
        let err = proxy
            .mint(MintRequest {
                network: "unknown".into(),
                creator: "x".into(),
                payload: vec![],
                royalties_bps: 0,
            })
            .await
            .unwrap_err();

        matches!(err, MintError::BackendNotFound(_));
    }
}
```