```rust
//! CanvasChain Symphony – P2P subsystem
//!
//! This module encapsulates all peer-to-peer logic required by the
//! `node_service` micro-service.  We rely on `libp2p` for transport and
//! leverage a blend of
//!   * Gossipsub – broadcast artist movements / blocks;
//!   * Kademlia  – DHT based peer discovery / content routing;
//!   * MDNS      – local network discovery during development;
//!   * Identify  – node metadata exchange (agent/version/network).
//!
//! The service exposes two channels:
//!   * `Command` – control-plane requests coming from the rest of the node;
//!   * `NetworkEvent` – data-plane events streaming *out* of the swarm.
//!
//! Architecture wise the module follows an *actor* model: a
//! `P2PNode` is spawned on its own Tokio task that owns the
//! `libp2p::Swarm`. Communication happens via asynchronous channels which
//! nicely plays along with the overall event-driven design of
//! CanvasChain Symphony.
//!
//! ─────────────────────────────────────────────────────────────────────────────

use std::{collections::HashSet, task::Poll};

use anyhow::Context;
use futures::{future::BoxFuture, prelude::*};
use libp2p::{
    core::upgrade,
    gossipsub::{
        self, Gossipsub, GossipsubEvent, IdentTopic, MessageId, ValidationMode,
    },
    identify::{Behaviour as Identify, Config as IdentifyConfig, Event as IdentifyEvent},
    kad::{store::MemoryStore, Behaviour as Kademlia, Event as KadEvent, KademliaConfig},
    mdns::{tokio::Behaviour as Mdns, Event as MdnsEvent},
    noise, swarm,
    swarm::{NetworkBehaviour, Swarm, SwarmEvent},
    tcp, yamux, Multiaddr, PeerId, Transport,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokio::{
    select,
    sync::{broadcast, mpsc},
};
use tracing::{debug, error, info, instrument, warn};

// ════════════════════════════════════════════════════════════════════════════
// Public API
// ════════════════════════════════════════════════════════════════════════════

/// Control-plane commands that can be sent *into* the P2P service.
#[derive(Debug)]
pub enum Command {
    /// Publish a payload to a given topic.
    Publish {
        topic: String,
        data: Vec<u8>,
    },
    /// Dial a peer at a specific address.
    Dial { address: Multiaddr },
    /// Gracefully shut the swarm down.
    Shutdown,
}

/// Data-plane events emitted by the service back to the caller.
#[derive(Debug, Clone)]
pub enum NetworkEvent {
    /// A message has been received on a subscribed topic.
    Gossipsub {
        source: PeerId,
        topic: String,
        data: Vec<u8>,
    },
    /// We discovered a new peer.
    PeerDiscovered(PeerId),
    /// A peer has explicitly disconnected.
    PeerDisconnected(PeerId),
}

/// End-user configuration for the P2P layer.
#[derive(Clone, Debug)]
pub struct P2PConfig {
    /// Node's Ed25519 keypair (required).
    pub keypair: libp2p::identity::Keypair,
    /// Addresses on which the node should listen.
    pub listen_addresses: Vec<Multiaddr>,
    /// Bootstrap nodes for initial peer discovery.
    pub bootstrap: Vec<(PeerId, Multiaddr)>,
    /// Name of the logical network (used by Identify).
    pub network_name: String,
    /// Enable local-LAN MDNS discovery (useful for dev).
    pub enable_mdns: bool,
    /// Enable the DHT.
    pub enable_kad: bool,
    /// Topics we automatically subscribe to on boot.
    pub gossipsub_topics: Vec<String>,
}

impl P2PConfig {
    /// Convenience constructor to spin up a localhost development node.
    pub fn development(net: impl Into<String>) -> Self {
        Self {
            keypair: libp2p::identity::Keypair::generate_ed25519(),
            listen_addresses: vec![
                "/ip4/0.0.0.0/tcp/0"
                    .parse()
                    .expect("Hard-coded Multiaddr to be valid"),
            ],
            bootstrap: Vec::new(),
            network_name: net.into(),
            enable_mdns: true,
            enable_kad: true,
            gossipsub_topics: vec!["canvaschain.global".into()],
        }
    }
}

/// Handle returned by [`spawn`] used to interact with the P2P node.
#[derive(Debug, Clone)]
pub struct P2PHandle {
    cmd_tx: mpsc::Sender<Command>,
    evt_rx: broadcast::Receiver<NetworkEvent>,
}

impl P2PHandle {
    /// Send a command to the underlying swarm.
    pub async fn send(&self, cmd: Command) -> Result<(), P2PError> {
        self.cmd_tx
            .send(cmd)
            .await
            .map_err(|_| P2PError::ChannelClosed)
    }

    /// Subscribe to network events.
    pub fn subscribe(&self) -> broadcast::Receiver<NetworkEvent> {
        self.evt_rx.resubscribe()
    }
}

/// Spawn a brand-new P2P actor on its own asynchronous task.
///
/// Returns a [`P2PHandle`] that can be used to talk to it.
pub fn spawn(cfg: P2PConfig) -> Result<P2PHandle, P2PError> {
    let (cmd_tx, cmd_rx) = mpsc::channel::<Command>(64);
    let (evt_tx, evt_rx) = broadcast::channel::<NetworkEvent>(1024);

    let node = P2PNode::new(cfg, cmd_rx, evt_tx.clone())?;
    tokio::spawn(async move {
        if let Err(e) = node.run().await {
            error!(error = %e, "P2P node terminated with failure");
        }
    });

    Ok(P2PHandle { cmd_tx, evt_rx })
}

// ════════════════════════════════════════════════════════════════════════════
// Implementation
// ════════════════════════════════════════════════════════════════════════════

#[derive(Error, Debug)]
pub enum P2PError {
    #[error("internal communication channel closed unexpectedly")]
    ChannelClosed,
    #[error("transport error: {0}")]
    Transport(String),
    #[error("anyhow: {0}")]
    Anyhow(#[from] anyhow::Error),
}

/// The libp2p behaviour composed for CanvasChain.
///
/// `derive(NetworkBehaviour)` will automatically create the delegation glue
/// for the individual sub-behaviours we embed here.
#[derive(NetworkBehaviour)]
#[behaviour(out_event = "OutEvent")]
struct CanvasBehaviour {
    gossipsub: Gossipsub,
    identify: Identify,
    #[behaviour(ignore)]
    #[allow(dead_code)]
    #[cfg(feature = "experimental")]
    _autonat: libp2p::autonat::Behaviour,
    #[behaviour(ignore)]
    #[allow(dead_code)]
    relay: Option<libp2p::relay::client::Behaviour>,
    mdns: Option<Mdns>,
    kad: Option<Kademlia<MemoryStore>>,
}

#[allow(clippy::large_enum_variant)]
#[derive(Debug)]
enum OutEvent {
    Gossipsub(GossipsubEvent),
    Identify(IdentifyEvent),
    Mdns(MdnsEvent),
    Kad(KadEvent),
}

impl From<GossipsubEvent> for OutEvent {
    fn from(e: GossipsubEvent) -> Self {
        Self::Gossipsub(e)
    }
}
impl From<IdentifyEvent> for OutEvent {
    fn from(e: IdentifyEvent) -> Self {
        Self::Identify(e)
    }
}
impl From<MdnsEvent> for OutEvent {
    fn from(e: MdnsEvent) -> Self {
        Self::Mdns(e)
    }
}
impl From<KadEvent> for OutEvent {
    fn from(e: KadEvent) -> Self {
        Self::Kad(e)
    }
}

/// Internal actor wrapping the swarm and control channels.
struct P2PNode {
    swarm: Swarm<CanvasBehaviour>,
    cmd_rx: mpsc::Receiver<Command>,
    evt_tx: broadcast::Sender<NetworkEvent>,

    // keep track of connected peers
    connected: HashSet<PeerId>,
}

impl P2PNode {
    fn new(
        cfg: P2PConfig,
        cmd_rx: mpsc::Receiver<Command>,
        evt_tx: broadcast::Sender<NetworkEvent>,
    ) -> Result<Self, P2PError> {
        // Build the transport stack (TCP/Yamux/Noise).
        let noise_keys = noise::Keypair::<noise::X25519Spec>::new()
            .into_authentic(&cfg.keypair)
            .map_err(|e| P2PError::Transport(format!("{e}")))?;

        let transport = tcp::tokio::Transport::new(tcp::Config::default().nodelay(true))
            .upgrade(upgrade::Version::V1)
            .authenticate(noise::NoiseConfig::xx(noise_keys).into_authenticated())
            .multiplex(yamux::Config::default())
            .timeout(std::time::Duration::from_secs(20))
            .boxed();

        // ─── Gossipsub ───────────────────────────────────────────────────────
        let peer_id = PeerId::from(cfg.keypair.public());
        let mut gossipsub_cfg = gossipsub::ConfigBuilder::default();
        gossipsub_cfg
            .validation_mode(ValidationMode::Strict)
            .mesh_n_low(4)
            .mesh_n_high(12)
            .build();

        let message_authenticity = gossipsub::MessageAuthenticity::Signed(cfg.keypair.clone());
        let mut gossipsub =
            Gossipsub::new(message_authenticity, gossipsub_cfg.build().unwrap())
                .context("constructing gossipsub")?;

        for topic in &cfg.gossipsub_topics {
            let topic = IdentTopic::new(topic.clone());
            gossipsub.subscribe(&topic)?;
        }

        // ─── Identify ───────────────────────────────────────────────────────
        let identify = Identify::new(IdentifyConfig::new(
            "/canvaschain/1.0".into(),
            cfg.keypair.public(),
        ));

        // ─── MDNS (optional) ────────────────────────────────────────────────
        let mdns = if cfg.enable_mdns {
            Some(Mdns::new(Default::default(), peer_id)?)
        } else {
            None
        };

        // ─── Kademlia (optional) ────────────────────────────────────────────
        let kad = if cfg.enable_kad {
            let mut store = MemoryStore::new(peer_id);
            for (peer, addr) in &cfg.bootstrap {
                store.add_address(peer, addr.clone());
            }
            let mut cfg_kad = KademliaConfig::default();
            cfg_kad.set_record_filtering(libp2p::kad::store::Filter::All);
            Some(Kademlia::with_config(peer_id, store, cfg_kad))
        } else {
            None
        };

        let behaviour = CanvasBehaviour {
            gossipsub,
            identify,
            mdns,
            kad,
            relay: None,
            #[cfg(feature = "experimental")]
            _autonat: libp2p::autonat::Behaviour::new(
                peer_id,
                libp2p::autonat::Config::default(),
            ),
        };

        let mut swarm = Swarm::with_tokio_executor(transport, behaviour, peer_id);

        for addr in &cfg.listen_addresses {
            swarm.listen_on(addr.clone())?;
        }

        for (peer, addr) in &cfg.bootstrap {
            swarm.dial(addr.clone())?;
            debug!(peer = %peer, "Dialing bootstrap peer");
        }

        Ok(Self {
            swarm,
            cmd_rx,
            evt_tx,
            connected: HashSet::new(),
        })
    }

    /// Main loop: drive the libp2p swarm & command receiver.
    #[instrument(name = "p2p-event-loop", skip(self))]
    async fn run(mut self) -> Result<(), P2PError> {
        loop {
            select! {
                swarm_event = self.swarm.select_next_some() => {
                    if let Err(e) = self.handle_swarm_event(swarm_event).await {
                        warn!(error = %e,"error while processing swarm event");
                    }
                },
                cmd = self.cmd_rx.recv() => {
                    if let Some(cmd) = cmd {
                        if let Err(e) = self.handle_cmd(cmd).await {
                            warn!(error = %e,"error while processing command");
                        }
                    } else {
                        // All senders dropped — we should shutdown.
                        info!("Command channel closed, shutting P2P node down.");
                        break;
                    }
                }
            }
        }

        Ok(())
    }

    async fn handle_cmd(&mut self, cmd: Command) -> Result<(), P2PError> {
        match cmd {
            Command::Publish { topic, data } => {
                let topic = IdentTopic::new(topic);
                self.swarm
                    .behaviour_mut()
                    .gossipsub
                    .publish(topic, data)
                    .map_err(|e| P2PError::Transport(format!("{e}")))?;
            }
            Command::Dial { address } => {
                self.swarm.dial(address)?;
            }
            Command::Shutdown => {
                info!("Received shutdown command");
                // Drop the receiver to exit the run() loop
                self.cmd_rx.close();
            }
        }
        Ok(())
    }

    async fn handle_swarm_event(
        &mut self,
        event: SwarmEvent<OutEvent, swarm::DialError>,
    ) -> anyhow::Result<()> {
        match event {
            SwarmEvent::NewListenAddr { address, .. } => {
                info!(%address, "Listening on");
            }
            SwarmEvent::Behaviour(OutEvent::Gossipsub(GossipsubEvent::Message {
                propagation_source,
                message_id: MessageId::Sha256(hash),
                message,
            })) => {
                debug!(peer = %propagation_source, id = ?hash, "gossip message received");
                let _ = self.evt_tx.send(NetworkEvent::Gossipsub {
                    source: propagation_source,
                    topic: message.topic.as_str().to_string(),
                    data: message.data.clone(),
                });
            }
            SwarmEvent::Behaviour(OutEvent::Mdns(event)) => match event {
                MdnsEvent::Discovered(list) => {
                    for (peer, _addr) in list {
                        if self.connected.insert(peer) {
                            debug!(%peer, "mdns discovered");
                            self.evt_tx.send(NetworkEvent::PeerDiscovered(peer)).ok();
                        }
                    }
                }
                MdnsEvent::Expired(list) => {
                    for (peer, _addr) in list {
                        if self.connected.remove(&peer) {
                            debug!(%peer, "mdns peer expired");
                            self.evt_tx.send(NetworkEvent::PeerDisconnected(peer)).ok();
                        }
                    }
                }
            },
            SwarmEvent::Behaviour(OutEvent::Identify(IdentifyEvent::Received { peer_id, .. })) => {
                self.connected.insert(peer_id);
                self.evt_tx
                    .send(NetworkEvent::PeerDiscovered(peer_id))
                    .ok();
            }
            SwarmEvent::ConnectionClosed {
                peer_id, remaining, ..
            } => {
                if remaining == 0 {
                    self.connected.remove(&peer_id);
                    self.evt_tx
                        .send(NetworkEvent::PeerDisconnected(peer_id))
                        .ok();
                }
            }
            _ => {}
        }
        Ok(())
    }
}

// ════════════════════════════════════════════════════════════════════════════
// Messages useful for higher-level application
// ════════════════════════════════════════════════════════════════════════════

/// High-level message representing an “on-chain art movement”.
///
/// These messages are simply *payloads* for Gossipsub; actual blockchain
/// consensus/validation is handled elsewhere.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArtMovementMessage {
    pub block_hash: String,
    pub composer: PeerId,
    pub compressed_diff: Vec<u8>,
}

// Convenience helpers for serialization
impl ArtMovementMessage {
    pub fn to_vec(&self) -> anyhow::Result<Vec<u8>> {
        Ok(bincode::serialize(self)?)
    }
    pub fn from_slice(data: &[u8]) -> anyhow::Result<Self> {
        Ok(bincode::deserialize(data)?)
    }
}

// ════════════════════════════════════════════════════════════════════════════
// Tests – run with `cargo test -p node_service -- --nocapture`
// ════════════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time::{sleep, Duration};

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn smoke_two_nodes_can_talk() -> anyhow::Result<()> {
        tracing_subscriber::fmt::try_init().ok();

        let cfg_a = P2PConfig::development("testnet");
        let cfg_b = P2PConfig::development("testnet");

        let node_a = spawn(cfg_a)?;
        let node_b = spawn(cfg_b)?;

        // Wait a bit to let mdns discover peers.
        sleep(Duration::from_secs(2)).await;

        let topic = "canvaschain.global";
        let payload = b"hello-world".to_vec();
        node_a
            .send(Command::Publish {
                topic: topic.into(),
                data: payload.clone(),
            })
            .await?;

        let mut rx_b = node_b.subscribe();

        let mut received = false;
        let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            if let Ok(NetworkEvent::Gossipsub { data, .. }) = rx_b.recv().await {
                if data == payload {
                    received = true;
                    break;
                }
            }
        }
        assert!(received, "node B did not receive gossipsub message");

        Ok(())
    }
}
```