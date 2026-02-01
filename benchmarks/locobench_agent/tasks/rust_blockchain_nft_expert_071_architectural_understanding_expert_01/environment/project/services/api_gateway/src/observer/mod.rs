```rust
//! Observer module for the `api_gateway` micro–service.
//!
//! This module implements an in-process event bus built on top of
//! `tokio::sync::broadcast` and an Observer registry.  
//!
//! Each micro-service inside CanvasChain Symphony publishes domain events
//! (e.g. NFT minted, ownership transferred, trait evolved, governance vote
//! tallied). The API-gateway subscribes to these events and pushes the
//! relevant subset to external clients via WebSockets / SSE or caches them
//! for REST endpoints.
//!
//! We rely on the classic *Observer Pattern*: observers register themselves
//! to the [`EventBus`]; when an [`Event`] is emitted, the bus fan-outs the
//! message to all live observers asynchronously.
//!
//! A small ergonomics layer is provided so that each observer can be a plain
//! Rust type implementing [`Observer`]. Internally a Tokio task is spawned
//! per observer to listen for events and call the handler.

use std::{
    future::Future,
    pin::Pin,
    sync::Arc,
    time::{Duration, SystemTime},
};

use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokio::{
    select,
    sync::{broadcast, oneshot},
    task::JoinHandle,
};
use tracing::{debug, error, info, instrument, warn};

/// Maximum number of events kept in the channel’s ring-buffer.
///
/// If subscribers can’t keep up, the oldest events will be dropped and an
/// [`RecvError::Lagged`](tokio::sync::broadcast::error::RecvError::Lagged)
/// will be returned to the slow consumer.
const EVENT_BUS_CAPACITY: usize = 1_024;

/// Domain events that can be published on the [`EventBus`].
///
/// The enum should be extended whenever a new micro-service introduces a new
/// type of event worth observing from the API-gateway layer.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Event {
    /// A brand-new NFT was minted on-chain.
    NftMinted {
        nft_id: String,
        creator_wallet: String,
        timestamp: u64,
    },
    /// Ownership of an NFT has changed.
    OwnershipTransferred {
        nft_id: String,
        from_wallet: String,
        to_wallet: String,
        timestamp: u64,
    },
    /// An on-chain generative trait evolved.
    TraitEvolved {
        nft_id: String,
        trait_key: String,
        old_value: String,
        new_value: String,
        block_height: u64,
    },
    /// A new composer node was elected by the Proof-of-Inspiration consensus.
    ComposerSelected {
        node_id: String,
        stake: u128,
        round: u64,
        vrf_proof: String,
    },
    /// A governance proposal was resolved.
    GovernanceResult {
        proposal_id: String,
        passed: bool,
        yes_stake: u128,
        no_stake: u128,
    },
}

/// General error type for the Observer subsystem.
#[derive(Debug, Error)]
pub enum ObserverError {
    #[error("observer handler failed: {0}")]
    Handler(String),

    #[error("failed to send event on broadcast channel: {0}")]
    Send(#[from] broadcast::error::SendError<Arc<Event>>),
}

/// Trait that every Observer must implement.
///
/// The handler is asynchronous and non-blocking; it will be polled on a Tokio
/// runtime.  Handlers should strive to return quickly, off-loading heavy work
/// to dedicated tasks if needed.
#[async_trait::async_trait]
pub trait Observer: Send + Sync + 'static {
    /// Human-readable name, mostly for logging purposes.
    fn name(&self) -> &'static str;

    /// Process a new event.
    async fn on_event(&self, event: Arc<Event>) -> Result<(), ObserverError>;
}

/// Handle returned by [`EventBus::register_observer`]. Dropping it stops the
/// background task listening for events.
pub struct ObserverHandle {
    shutdown_tx: Option<oneshot::Sender<()>>,
    join_handle: JoinHandle<()>,
}

impl ObserverHandle {
    /// Blocks until the observer task has terminated.
    pub async fn await_termination(mut self) {
        if let Some(tx) = self.shutdown_tx.take() {
            // Ignore failure – it just means task already ended.
            let _ = tx.send(());
        }
        let _ = self.join_handle.await;
    }
}

impl Drop for ObserverHandle {
    fn drop(&mut self) {
        if let Some(tx) = self.shutdown_tx.take() {
            let _ = tx.send(());
        }
    }
}

/// Central, in-memory event bus for the current process.
#[derive(Clone)]
pub struct EventBus {
    sender: broadcast::Sender<Arc<Event>>,
}

impl Default for EventBus {
    fn default() -> Self {
        let (sender, _) = broadcast::channel(EVENT_BUS_CAPACITY);
        EventBus { sender }
    }
}

impl EventBus {
    /// Publish a new [`Event`].
    ///
    /// Returns an error only if the channel is closed (which shouldn’t happen
    /// under normal circumstances).
    #[instrument(level = "debug", skip(self, event))]
    pub fn publish(&self, event: Event) -> Result<(), ObserverError> {
        let wrapped = Arc::new(event);
        self.sender.send(wrapped)?;
        Ok(())
    }

    /// Register a new [`Observer`].  
    ///
    /// A dedicated task is spawned; the caller receives an [`ObserverHandle`]
    /// to control its life-cycle.
    pub fn register_observer<O>(&self, observer: O) -> ObserverHandle
    where
        O: Observer,
    {
        let mut receiver = self.sender.subscribe();
        let (shutdown_tx, mut shutdown_rx) = oneshot::channel::<()>();
        let name = observer.name();
        let observer = Arc::new(observer);

        let join_handle = tokio::spawn(async move {
            info!(observer = %name, "observer started");
            loop {
                select! {
                    biased;
                    _ = &mut shutdown_rx => {
                        info!(observer = %name, "observer shutdown requested");
                        break;
                    }
                    recv = receiver.recv() => {
                        match recv {
                            Ok(event) => {
                                let span = tracing::info_span!("observer_on_event", observer = %name);
                                let _enter = span.enter();
                                if let Err(e) = observer.on_event(event).await {
                                    error!(observer = %name, error = %e, "observer failed");
                                }
                            }
                            Err(broadcast::error::RecvError::Closed) => {
                                warn!(observer = %name, "event channel closed");
                                break;
                            }
                            Err(broadcast::error::RecvError::Lagged(skipped)) => {
                                warn!(observer = %name, skipped, "observer lagged behind");
                                // Continue – the receiver is automatically synced to the newest message.
                            }
                        }
                    }
                }
            }
            info!(observer = %name, "observer terminated");
        });

        ObserverHandle {
            shutdown_tx: Some(shutdown_tx),
            join_handle,
        }
    }
}

/* -------------------------------------------------------------------------
 * Example observers
 * ---------------------------------------------------------------------- */

/// Example observer that simply logs every incoming event.
///
/// In production this could push updates to Redis or forward them to a
/// WebSocket room.
pub struct LoggerObserver;

#[async_trait::async_trait]
impl Observer for LoggerObserver {
    fn name(&self) -> &'static str {
        "logger_observer"
    }

    #[instrument(level = "debug", skip(self, event))]
    async fn on_event(&self, event: Arc<Event>) -> Result<(), ObserverError> {
        debug!(?event, "event received by logger");
        Ok(())
    }
}

/// Observer that keeps an in-memory cache of the latest ownership of every NFT.
///
/// The cache can be exposed via a REST endpoint to provide instant answers
/// without hitting the underlying storage or smart contract.
pub struct OwnershipCache {
    /// nft_id -> wallet
    inner: dashmap::DashMap<String, String>,
}

impl OwnershipCache {
    pub fn new() -> Self {
        Self {
            inner: dashmap::DashMap::new(),
        }
    }

    /// Reads the current owner of an NFT, if known.
    pub fn current_owner(&self, nft_id: &str) -> Option<String> {
        self.inner.get(nft_id).map(|v| v.value().clone())
    }
}

#[async_trait::async_trait]
impl Observer for OwnershipCache {
    fn name(&self) -> &'static str {
        "ownership_cache"
    }

    #[instrument(level = "debug", skip(self, event))]
    async fn on_event(&self, event: Arc<Event>) -> Result<(), ObserverError> {
        if let Event::OwnershipTransferred {
            nft_id,
            to_wallet,
            ..
        } = &*event
        {
            self.inner.insert(nft_id.clone(), to_wallet.clone());
            debug!(nft_id, new_owner = to_wallet, "cache updated");
        }
        Ok(())
    }
}

/* -------------------------------------------------------------------------
 * Helpers
 * ---------------------------------------------------------------------- */

/// Utility to get a UNIX timestamp in milliseconds.
///
/// We avoid depending on `chrono` to keep the dependency list small inside
/// this crate.
pub fn now_millis() -> u64 {
    SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_else(|_| Duration::from_secs(0))
        .as_millis() as u64
}

/* -------------------------------------------------------------------------
 * (Optional) module tests
 * ---------------------------------------------------------------------- */

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn smoke_test_observer_registration() {
        let bus = EventBus::default();

        let cache = OwnershipCache::new();
        let _handle = bus.register_observer(cache);

        bus.publish(Event::OwnershipTransferred {
            nft_id: "abc123".into(),
            from_wallet: "A".into(),
            to_wallet: "B".into(),
            timestamp: now_millis(),
        })
        .unwrap();

        // Wait a bit to allow the async task to process the event.
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}
```