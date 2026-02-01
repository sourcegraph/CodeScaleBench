```rust
//! services/api_gateway/src/event_listener.rs
//!
//! CanvasChain Symphony – API Gateway
//! ----------------------------------
//! Event listener that bridges the internal event-bus (NATS) with the rest of
//! the API-Gateway subsystem.  It is responsible for:
//!   • Maintaining a resilient connection to the NATS cluster
//!   • Deserialising and validating blockchain / NFT events
//!   • Broadcasting strongly-typed events to in-process consumers
//!   • Handling graceful shutdown initiated by the service supervisor
//!
//! The listener uses Tokio for async runtime, Serde for (de)serialisation, and
//! tracing for structured logging.  Errors are mapped into a dedicated
//! `ListenerError` enum so they can be handled upstream in a uniform manner.

use std::time::Duration;

use async_nats::{ConnectOptions, Message, ServerAddr};
use futures::{StreamExt, TryStreamExt};
use serde::Deserialize;
use tokio::{
    select,
    sync::{broadcast, mpsc},
    task,
    time::sleep,
};
use tracing::{debug, error, info, warn};

/// Default subject (topic) pattern for CanvasChain events.
const DEFAULT_EVENT_SUBJECT: &str = "canvaschain.events.>";

/// The capacity of the broadcast channel that the listener publishes events to.
/// Consumers will receive an [`Err(broadcast::error::RecvError::Lagged)`] if they
/// cannot keep up with the throughput.
const EVENT_DISPATCH_CAPACITY: usize = 256;

/// A strongly-typed wrapper around all events that may traverse the event-bus.
/// New events should be added here.
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum ChainEvent {
    #[serde(rename = "nft_minted")]
    NftMinted(NftMintedEvent),

    #[serde(rename = "ownership_transferred")]
    OwnershipTransferred(OwnershipTransferredEvent),

    #[serde(rename = "governance_vote_cast")]
    GovernanceVoteCast(GovernanceVoteCastEvent),
}

/// Event emitted when a new NFT has been minted.
#[derive(Debug, Clone, Deserialize)]
pub struct NftMintedEvent {
    pub token_id: String,
    pub creator_wallet: String,
    pub block_height: u64,
}

/// Event emitted when ownership changed.
#[derive(Debug, Clone, Deserialize)]
pub struct OwnershipTransferredEvent {
    pub token_id: String,
    pub from_wallet: String,
    pub to_wallet: String,
    pub block_height: u64,
}

/// Event emitted when a governance vote has been cast.
#[derive(Debug, Clone, Deserialize)]
pub struct GovernanceVoteCastEvent {
    pub proposal_id: String,
    pub voter_wallet: String,
    pub support: bool,
    pub voting_power: u128,
    pub block_height: u64,
}

/// Type alias used internally.
pub type Result<T> = std::result::Result<T, ListenerError>;

/// Domain-specific error for the [`EventListener`].
#[derive(thiserror::Error, Debug)]
pub enum ListenerError {
    #[error("failed to connect to NATS: {0}")]
    NatsConnect(#[from] async_nats::ConnectError),

    #[error("failed to subscribe to NATS subject: {0}")]
    NatsSubscribe(#[from] async_nats::SubscribeError),

    #[error("nats connection dropped")]
    NatsDisconnected,

    #[error("failed to decode event: {0}")]
    Decode(#[from] serde_json::Error),

    #[error("internal channel closed")]
    ChannelClosed,
}

/// Handles external CanvasChain event stream and re-emits events inside the API
/// gateway via broadcast channels.
///
/// # Example
///
/// ```no_run
/// use tokio::sync::broadcast;
///
/// # #[tokio::main]
/// # async fn main() -> anyhow::Result<()> {
/// let (_tx, _rx) = broadcast::channel(128);
/// // let listener = EventListener::new("nats://127.0.0.1:4222", _tx).await?;
/// // listener.start().await?;
/// # Ok(())
/// # }
/// ```
pub struct EventListener {
    /// NATS connection handle.
    nats: async_nats::Client,

    /// Broadcast sender used to dispatch events to in-process subscribers.
    dispatcher: broadcast::Sender<ChainEvent>,

    /// Used to notify the background task to shut down.
    shutdown_tx: mpsc::Sender<()>,

    /// Receiver side for the shutdown signal.
    shutdown_rx: mpsc::Receiver<()>,
}

impl EventListener {
    /// Establish a new [`EventListener`] and the underlying NATS connection.
    ///
    /// The function will attempt to connect to the cluster with defaults tuned
    /// for low-latency streaming workloads.
    pub async fn new<S: Into<String>>(
        nats_url: S,
        dispatcher: Option<broadcast::Sender<ChainEvent>>,
    ) -> Result<Self> {
        // Build connection options with limited reconnect back-off.
        let connect_opts = ConnectOptions::with_user_agent("CanvasChain-API-Gateway")
            .connect_timeout(Duration::from_secs(5))
            .retry_on_failed_connect(true)
            .max_reconnects(5);

        let nats = connect_opts
            .connect(ServerAddr::new(nats_url))
            .await
            .map_err(ListenerError::NatsConnect)?;

        let dispatcher = dispatcher.unwrap_or_else(|| {
            let (tx, _rx) = broadcast::channel(EVENT_DISPATCH_CAPACITY);
            tx
        });

        let (shutdown_tx, shutdown_rx) = mpsc::channel(1);

        Ok(Self {
            nats,
            dispatcher,
            shutdown_tx,
            shutdown_rx,
        })
    }

    /// Returns a clone of the broadcast receiver so other components can
    /// subscribe to incoming events without holding a mutable reference.
    pub fn subscribe(&self) -> broadcast::Receiver<ChainEvent> {
        self.dispatcher.subscribe()
    }

    /// Exposes a handle that lets the caller trigger a graceful shutdown.
    pub fn shutdown_handle(&self) -> mpsc::Sender<()> {
        self.shutdown_tx.clone()
    }

    /// Spawn the event listener loop in a detached Tokio task.
    ///
    /// This method returns immediately. Use the receiver returned by
    /// [`EventListener::subscribe`] to listen for decoded events.
    pub fn spawn(mut self) {
        task::spawn(async move {
            loop {
                // Try to (re-)subscribe; bail if the shutdown signal was received.
                match self.run_subscription_loop().await {
                    Ok(_) => {
                        info!("event subscription loop terminated gracefully");
                        break;
                    }
                    Err(ListenerError::NatsDisconnected) => {
                        warn!("lost connection to NATS – attempting to reconnect in 3s");
                        sleep(Duration::from_secs(3)).await;
                    }
                    Err(err) => {
                        error!("irrecoverable event listener error: {err:?}");
                        break;
                    }
                }
            }
        });
    }

    /// Blocking event receipt loop. Returns only when:
    ///   • Shutdown signal arrives, OR
    ///   • The underlying NATS connection was lost, OR
    ///   • An unrecoverable error occurred.
    async fn run_subscription_loop(&mut self) -> Result<()> {
        let mut subscription = self
            .nats
            .subscribe(DEFAULT_EVENT_SUBJECT)
            .await
            .map_err(ListenerError::NatsSubscribe)?;

        info!(
            subject = DEFAULT_EVENT_SUBJECT,
            "subscribed to CanvasChain event stream"
        );

        loop {
            select! {
                maybe_msg = subscription.next() => {
                    match maybe_msg {
                        Some(Ok(msg)) => self.handle_message(msg).await?,
                        Some(Err(_)) => {
                            return Err(ListenerError::NatsDisconnected)
                        }
                        None => {
                            // Stream ended
                            return Err(ListenerError::NatsDisconnected)
                        }
                    }
                }
                _ = self.shutdown_rx.recv() => {
                    info!("shutdown signal received – terminating event listener");
                    return Ok(())
                }
            }
        }
    }

    /// Handle a single NATS message: decode JSON payload and broadcast event.
    async fn handle_message(&self, msg: Message) -> Result<()> {
        let payload_str = std::str::from_utf8(&msg.payload)
            .map_err(|e| ListenerError::Decode(serde_json::Error::custom(e)))?;

        let event: ChainEvent = serde_json::from_str(payload_str)?;
        debug!(subject=%msg.subject, ?event, "received chain event");

        // Dispatch. Ignore lagged receivers.
        let _ = self.dispatcher.send(event);

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time::timeout;

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn test_event_deserialization() {
        let json = r#"
            {
                "type":"nft_minted",
                "payload":{
                    "token_id":"abc123",
                    "creator_wallet":"0xDEADBEEF",
                    "block_height":42
                }
            }
        "#;

        let evt: ChainEvent = serde_json::from_str(json).expect("deserialise event");
        match evt {
            ChainEvent::NftMinted(e) => assert_eq!(e.token_id, "abc123"),
            _ => panic!("unexpected event variant"),
        }
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn test_broadcast_no_lag() {
        // Create a dummy dispatcher with small capacity to induce lag.
        let (tx, mut rx) = broadcast::channel(2);

        // Send 2 events — should succeed.
        tx.send(ChainEvent::NftMinted(NftMintedEvent {
            token_id: "1".into(),
            creator_wallet: "wallet".into(),
            block_height: 1,
        }))
        .unwrap();

        // Receiver should get the first event.
        let evt = timeout(Duration::from_millis(100), rx.recv())
            .await
            .expect("timed out")
            .expect("receive failed");
        matches!(evt, ChainEvent::NftMinted(_));
    }
}
```
