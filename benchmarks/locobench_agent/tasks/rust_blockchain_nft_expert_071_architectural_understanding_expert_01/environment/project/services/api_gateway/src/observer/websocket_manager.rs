use std::{net::SocketAddr, sync::Arc};

use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Extension,
    },
    response::IntoResponse,
    routing::get,
    Router,
};
use futures::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::{
    sync::{broadcast, mpsc, Mutex},
    task,
};
use tracing::{error, info};

/// Domain events pushed by the backend and streamed to WebSocket clients.
///
/// Every CanvasChain micro-service emits JSON messages on the event bus; the API
/// gateway translates them into strongly-typed `Event`s and fans them out.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum Event {
    NftMinted { nft_id: String, creator: String },
    NftTransferred { nft_id: String, from: String, to: String },
    GovernanceProposalCreated { proposal_id: u64, proposer: String },
    DefiPositionUpdated { user: String, position_value_usd: f64 },
    SystemHealth { component: String, status: String },
}

impl Event {
    /// Convert the event to JSON for WebSocket transmission.
    pub fn to_json(&self) -> Result<String, serde_json::Error> {
        serde_json::to_string(self)
    }
}

/// Broadcast channel used to implement the Observer pattern for all live
/// WebSocket clients.
type EventBus = broadcast::Sender<Event>;

/// Manages all WebSocket connections and propagates events to them.
///
/// A single `WebSocketManager` instance lives for the lifetime of the API
/// gateway process. Internally it hosts a Tokio broadcast channel so that every
/// connected peer gets its own receiver.
#[derive(Clone)]
pub struct WebSocketManager {
    bus: EventBus,
}

impl WebSocketManager {
    /// Create a new manager with `capacity` buffered events.
    ///
    /// Back-pressure is applied once the buffer is full. Production deployments
    /// should size this according to expected burst rates.
    pub fn new(capacity: usize) -> Self {
        let (bus, _) = broadcast::channel(capacity);
        Self { bus }
    }

    /// Turn the manager into an `axum::Router` exposing a `/ws` endpoint.
    pub fn into_router(self) -> Router {
        Router::new()
            .route("/ws", get(Self::ws_handler))
            .layer(Extension(Arc::new(self)))
    }

    /// Publish an event to every connected client.
    pub fn publish(&self, event: Event) {
        let _ = self.bus.send(event); // ignore lagging clients
    }

    /// Internal: provide a dedicated receiver for each client.
    fn subscribe(&self) -> broadcast::Receiver<Event> {
        self.bus.subscribe()
    }

    // ─────────────────────────────────────────────────────────────────────────
    // WebSocket plumbing
    // ─────────────────────────────────────────────────────────────────────────

    async fn ws_handler(
        ws: WebSocketUpgrade,
        Extension(manager): Extension<Arc<WebSocketManager>>,
    ) -> impl IntoResponse {
        ws.on_upgrade(|socket| async move {
            if let Err(e) = manager.clone().handle_socket(socket).await {
                error!("websocket error: {e:?}");
            }
        })
    }

    async fn handle_socket(self: Arc<Self>, socket: WebSocket) -> anyhow::Result<()> {
        let (mut ws_tx, mut ws_rx) = socket.split();
        let mut bus_rx = self.subscribe();

        // Notify send-loop when the read-loop terminates.
        let (shutdown_tx, mut shutdown_rx) = mpsc::unbounded_channel::<()>();

        // Task forwarding events → WebSocket
        let send_loop = {
            let shutdown_tx = shutdown_tx.clone();
            task::spawn(async move {
                loop {
                    tokio::select! {
                        _ = shutdown_rx.recv() => break,
                        result = bus_rx.recv() => match result {
                            Ok(event) => {
                                match event.to_json() {
                                    Ok(json) => {
                                        if ws_tx.send(Message::Text(json)).await.is_err() {
                                            // Client disconnected.
                                            break;
                                        }
                                    }
                                    Err(err) => error!("serialization error: {err:?}"),
                                }
                            }
                            Err(broadcast::error::RecvError::Closed) => break,
                            Err(broadcast::error::RecvError::Lagged(skipped)) => {
                                error!("client lagged behind {skipped} messages");
                            }
                        }
                    }
                }
                let _ = shutdown_tx.send(());
            })
        };

        // Read-loop: handle inbound messages.
        while let Some(Ok(msg)) = ws_rx.next().await {
            match msg {
                Message::Ping(payload) => {
                    ws_tx.send(Message::Pong(payload)).await?;
                }
                Message::Close(_) => break,
                _ => {
                    // Future: authentication, filters, etc.
                }
            }
        }

        // Signal send-loop to stop and wait for completion.
        let _ = shutdown_tx.send(());
        let _ = send_loop.await;

        Ok(())
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Event-bus integration
// ─────────────────────────────────────────────────────────────────────────────

/// Spawn a background task that listens to NATS and forwards events to the
/// `WebSocketManager`.
///
/// Automatically reconnects with exponential back-off.
pub async fn spawn_nats_listener(
    nats_addr: String,
    subject: String,
    manager: WebSocketManager,
) -> anyhow::Result<()> {
    use async_nats::ConnectOptions;
    use futures::StreamExt;
    use tokio::time::{sleep, Duration};

    let manager = Arc::new(manager);
    let mut backoff = Duration::from_secs(1);

    loop {
        match ConnectOptions::new().connect(&nats_addr).await {
            Ok(client) => {
                info!("connected to NATS @ {nats_addr}");
                match client.subscribe(subject.clone()).await {
                    Ok(mut subscription) => {
                        while let Some(message) = subscription.next().await {
                            match serde_json::from_slice::<Event>(&message.payload) {
                                Ok(event) => manager.publish(event),
                                Err(err) => error!(
                                    "invalid event on {}: {err:?} – payload: {:?}",
                                    message.subject, message.payload
                                ),
                            }
                        }
                    }
                    Err(err) => error!("subscription error: {err:?}"),
                }
            }
            Err(err) => error!("NATS connection failed: {err:?}"),
        }

        // Reconnect with back-off.
        error!("lost NATS connection, retrying in {backoff:?}");
        sleep(backoff).await;
        backoff = (backoff * 2).min(Duration::from_secs(30));
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Convenience one-liner to spin up a standalone WebSocket server.
// ─────────────────────────────────────────────────────────────────────────────

/// Run a self-contained WebSocket server—useful for integration tests or local
/// development.
///
/// Production deployments typically merge this into the broader HTTP gateway
/// that also exposes REST and gRPC transports.
pub async fn serve(addr: SocketAddr, manager: WebSocketManager) -> anyhow::Result<()> {
    let app = manager.clone().into_router();

    info!("🎨  CanvasChain WebSocket gateway listening on {addr}");
    axum::Server::bind(&addr)
        .serve(app.into_make_service())
        .await?;

    Ok(())
}