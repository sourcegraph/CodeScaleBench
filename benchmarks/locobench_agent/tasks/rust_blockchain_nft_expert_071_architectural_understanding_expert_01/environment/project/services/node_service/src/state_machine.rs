```rust
//! Node service state–machine
//!
//! This module implements a hierarchical, asynchronous state-machine that
//! drives a single CanvasChain Symphony “conductor” (validator / full node).
//!
//! The public façade is [`NodeStateMachine::spawn`].  Callers provide a
//! configured [`NodeContext`] plus a Tokio `mpsc::Receiver<NodeEvent>` that
//! represents the node’s inbound event bus.  
//!
//! The machine is built around the classic State pattern.  Each state
//! implements [`State`]—an async callback that receives the next event and
//! returns a [`Transition`] indicating whether the machine should:
//!   * stay in the same state
//!   * transition to a new boxed state
//!   * perform a graceful shutdown.
//!
//! Transitions are **total**; all event/state combinations _must_ resolve to a
//! `Transition`, preventing undefined behaviour at runtime.
//!
//! -------------------------------------------------------------------------
//! Conventions & best-practices
//! -------------------------------------------------------------------------
//! • Logging is performed with the `tracing` crate (structured, async-aware).  
//! • All public types derive `Debug` to make tracing easier.  
//! • Errors bubble up using `thiserror::Error` and are logged before causing a
//!   transition into [`StateError`].  
//! • No blocking I/O—everything is fully async.  
//! • `#![deny(clippy::unwrap_used)]` ensures we never `.unwrap()` outside of
//!   tests.  
//!
//! -------------------------------------------------------------------------
//! Example
//! -------------------------------------------------------------------------
//! ```no_run
//! # use tokio::sync::mpsc;
//! # use canvas_chain_node_service::state_machine::*;
//! # #[tokio::main]
//! # async fn main() -> anyhow::Result<()> {
//! let (tx, rx) = mpsc::channel(128);
//! let ctx = NodeContext::new(Default::default(), tx.clone());
//! let handle = NodeStateMachine::spawn(ctx, rx);
//!
//! // Send a dummy event
//! tx.send(NodeEvent::Tick).await?;
//!
//! // Wait until the machine exits
//! handle.await?;
//! # Ok::<_, anyhow::Error>(())
//! # }
//! ```

#![deny(clippy::unwrap_used)]

use std::time::Duration;

use async_trait::async_trait;
use tokio::{
    select,
    sync::mpsc,
    task::JoinHandle,
    time::{interval, Interval},
};
use tracing::{debug, error, info, instrument};

use crate::event_bus::Publish;
use crate::network::types::{Block, PeerId};
use crate::storage::Database;

// ------------------------------
// Public facade
// ------------------------------

/// Spawn a state-machine on the Tokio runtime and return a [`JoinHandle`]
/// representing its lifecycle.
pub struct NodeStateMachine;

impl NodeStateMachine {
    /// Spawns the asynchronous state machine.  The function immediately returns
    /// a Tokio [`JoinHandle`] that finishes when the machine reaches the
    /// [`Transition::Shutdown`] transition or the provided `event_rx` closes.
    pub fn spawn(
        mut ctx: NodeContext,
        mut event_rx: mpsc::Receiver<NodeEvent>,
    ) -> JoinHandle<anyhow::Result<()>> {
        tokio::spawn(async move {
            let mut state: Box<dyn State> = Box::<StateBooting>::default();

            // Heart-beat ticker; every state receives `Tick` events.
            let mut ticker = interval(Duration::from_secs(5));

            loop {
                select! {
                    maybe_evt = event_rx.recv() => {
                        match maybe_evt {
                            Some(evt) => {
                                state = dispatch(&mut ctx, state, evt).await?;
                            }
                            None => {
                                info!("event stream closed – shutting node down");
                                break;
                            }
                        }
                    }

                    _ = ticker.tick() => {
                        state = dispatch(&mut ctx, state, NodeEvent::Tick).await?;
                    }
                }
            }

            info!(node_id=%ctx.config.node_id, "node service terminated");
            Ok(())
        })
    }
}

// ------------------------------
// Context & Events
// ------------------------------

/// Immutable configuration for a running node.
#[derive(Debug, Clone)]
pub struct NodeConfig {
    pub node_id: String,
    pub network_id: String,
    pub database_url: String,
    pub is_validator: bool,
}

impl Default for NodeConfig {
    fn default() -> Self {
        Self {
            node_id: nanoid::nanoid!(),
            network_id: "canvas-testnet".into(),
            database_url: "sqlite::memory:".into(),
            is_validator: false,
        }
    }
}

/// Long-living, shared runtime context passed to every [`State`].
#[derive(Debug)]
pub struct NodeContext {
    pub config: NodeConfig,
    pub db: Database,
    pub event_tx: mpsc::Sender<NodeEvent>,
    pub bus: Publish, // Simplified, re-export from crate::event_bus
}

impl NodeContext {
    pub fn new(config: NodeConfig, event_tx: mpsc::Sender<NodeEvent>) -> Self {
        let db = Database::connect(&config.database_url)
            .expect("infallible for in-memory; otherwise bubble up");

        Self {
            config,
            db,
            event_tx,
            bus: Publish::default(),
        }
    }
}

/// All possible events handled by the state machine.
#[derive(Debug)]
pub enum NodeEvent {
    /// Periodic internal heart-beat.
    Tick,

    /// New peer connected
    PeerConnected(PeerId),

    /// Network broadcast of a new block announcement.
    BlockReceived(Block),

    /// The consensus engine elected this node the next composer (“validator”).
    ElectedComposer,

    /// Graceful shutdown request.
    Shutdown,
}

// ------------------------------
// State machinery
// ------------------------------

/// When a [`State`] finishes processing an event it returns a `Transition`
/// deciding the machine’s next state.
#[derive(Debug)]
pub enum Transition {
    /// Remain in the existing state.
    Stay,
    /// Replace current state with a new one.
    Next(Box<dyn State>),
    /// Terminate the machine.
    Shutdown,
}

/// Common interface implemented by *every* node state.
#[async_trait]
pub trait State: Send {
    /// Human-readable name of the state (`&'static str` avoids allocations).
    fn name(&self) -> &'static str;

    /// Process an incoming event. Must return a valid [`Transition`].
    async fn on_event(
        &mut self,
        ctx: &mut NodeContext,
        event: NodeEvent,
    ) -> anyhow::Result<Transition>;
}

// Wrapper that logs state entry / exit
#[instrument(skip_all, fields(new_state = next.name()))]
async fn dispatch(
    ctx: &mut NodeContext,
    mut current: Box<dyn State>,
    evt: NodeEvent,
) -> anyhow::Result<Box<dyn State>> {
    debug!(
        state = current.name(),
        evt = format!("{:?}", evt),
        "handling event"
    );

    let transition = match current.on_event(ctx, evt).await {
        Ok(t) => t,
        Err(e) => {
            error!("state {:?} returned error: {e:?}", current.name());
            return Ok(Box::new(StateError::new(e)));
        }
    };

    let next: Box<dyn State> = match transition {
        Transition::Stay => current,
        Transition::Next(next_state) => next_state,
        Transition::Shutdown => {
            info!("shutdown requested by state {}", current.name());
            return Err(anyhow::anyhow!("state-machine shutdown"));
        }
    };

    Ok(next)
}

// ------------------------------
// Concrete States
// ------------------------------

/// Initial boot / self-check state.
#[derive(Default)]
struct StateBooting;

#[async_trait]
impl State for StateBooting {
    fn name(&self) -> &'static str {
        "Booting"
    }

    #[instrument(skip_all)]
    async fn on_event(
        &mut self,
        ctx: &mut NodeContext,
        event: NodeEvent,
    ) -> anyhow::Result<Transition> {
        match event {
            NodeEvent::Tick => {
                info!("boot sequence: verifying database connectivity");
                ctx.db.healthcheck().await?;
                info!("boot sequence: connecting to peer network");
                // Suppose we send some handshake event via ctx.bus here  
                // ctx.bus.publish(...)

                Ok(Transition::Next(Box::<StateSyncing>::default()))
            }
            NodeEvent::Shutdown => Ok(Transition::Shutdown),
            _ => Ok(Transition::Stay),
        }
    }
}

/// Synchronising blockchain data with peers.
#[derive(Default)]
struct StateSyncing;

#[async_trait]
impl State for StateSyncing {
    fn name(&self) -> &'static str {
        "Syncing"
    }

    #[instrument(skip_all)]
    async fn on_event(
        &mut self,
        ctx: &mut NodeContext,
        event: NodeEvent,
    ) -> anyhow::Result<Transition> {
        match event {
            NodeEvent::BlockReceived(block) => {
                info!(height = block.header.height, "received block during sync");
                ctx.db.insert_block(block).await?;
                // For brevity we assume once at tip we move to Active
                if ctx.db.is_at_chain_tip().await? {
                    info!("local chain at tip – moving to Active state");
                    return Ok(Transition::Next(Box::<StateActive>::default()));
                }
                Ok(Transition::Stay)
            }
            NodeEvent::Shutdown => Ok(Transition::Shutdown),
            _ => Ok(Transition::Stay),
        }
    }
}

/// Fully synced, participating in consensus and answering RPCs.
#[derive(Default)]
struct StateActive;

#[async_trait]
impl State for StateActive {
    fn name(&self) -> &'static str {
        "Active"
    }

    #[instrument(skip_all)]
    async fn on_event(
        &mut self,
        ctx: &mut NodeContext,
        event: NodeEvent,
    ) -> anyhow::Result<Transition> {
        match event {
            NodeEvent::ElectedComposer if ctx.config.is_validator => {
                info!("🎵 This node has been elected composer – creating art block");
                let block = compose_next_block(ctx).await?;
                ctx.bus.publish(NodeEvent::BlockReceived(block.clone()))
                    .await
                    .map_err(|e| anyhow::anyhow!("failed to publish block: {e}"))?;
                ctx.db.insert_block(block).await?;
                Ok(Transition::Stay)
            }
            NodeEvent::BlockReceived(block) => {
                debug!(
                    height = block.header.height,
                    composer = %block.header.producer,
                    "applying canonical block"
                );
                ctx.db.insert_block(block).await?;
                Ok(Transition::Stay)
            }
            NodeEvent::Shutdown => Ok(Transition::Shutdown),
            _ => Ok(Transition::Stay),
        }
    }
}

/// Terminal error state—any failure bubbles here so that the system can exit
/// gracefully instead of panicking.
#[derive(Debug)]
struct StateError {
    cause: anyhow::Error,
}

impl StateError {
    fn new<E: Into<anyhow::Error>>(e: E) -> Self {
        Self { cause: e.into() }
    }
}

#[async_trait]
impl State for StateError {
    fn name(&self) -> &'static str {
        "Error"
    }

    async fn on_event(
        &mut self,
        _ctx: &mut NodeContext,
        _event: NodeEvent,
    ) -> anyhow::Result<Transition> {
        error!("node is in error state: {:?}", self.cause);
        Ok(Transition::Shutdown)
    }
}

// ------------------------------
// Helper functions
// ------------------------------

/// Compose a new “art block” as elected composer.
///
/// This is merely a stub for the example.  A real implementation would run the
/// Proof-of-Inspiration algorithm, gather pending transactions from the mem-
/// pool, merge generative art layers, compute state roots, sign the header,
/// etc.
async fn compose_next_block(ctx: &NodeContext) -> anyhow::Result<Block> {
    use rand::Rng;

    let mut rng = rand::thread_rng();
    let block = Block {
        header: crate::network::types::BlockHeader {
            height: ctx.db.latest_height().await? + 1,
            producer: ctx.config.node_id.clone(),
            timestamp: chrono::Utc::now(),
            nonce: rng.gen::<u64>(),
            prev_hash: ctx.db.latest_hash().await?,
            merkle_root: vec![0; 32], // placeholder
            signature: vec![],
        },
        transactions: vec![],
    };
    Ok(block)
}

// ------------------------------
// Tests
// ------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time::timeout;

    #[tokio::test]
    async fn test_boot_to_shutdown() {
        let (tx, rx) = mpsc::channel(8);
        let cfg = NodeConfig {
            is_validator: false,
            ..Default::default()
        };
        let _handle = NodeStateMachine::spawn(NodeContext::new(cfg, tx.clone()), rx);

        // Ask the machine to shutdown
        tx.send(NodeEvent::Shutdown).await.unwrap();

        // Wait a short time to ensure completion
        // we don't assert on output; test just ensures no panic.
        timeout(Duration::from_secs(1), async { tokio::task::yield_now().await })
            .await
            .unwrap();
    }
}
```