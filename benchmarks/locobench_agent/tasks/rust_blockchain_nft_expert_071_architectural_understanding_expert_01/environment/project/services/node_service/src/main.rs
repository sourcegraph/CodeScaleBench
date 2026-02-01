```rust
// services/node_service/src/main.rs

//! CanvasChain Symphony – Node Service
//! -----------------------------------
//! This micro–service is responsible for:
//!   • participating in Proof-of-Inspiration consensus
//!   • exposing a gRPC API for peer / client interaction
//!   • publishing & consuming chain events through an event-bus
//!   • performing health / readiness reporting
//!
//! The implementation purposefully focuses on composability and separation
//! of concerns so that components (signature schemes, transports, storage
//! back-ends …) can be swapped without painful refactors.

#![forbid(unsafe_code)]
#![allow(clippy::missing_errors_doc)]

use clap::{Parser, Subcommand};
use std::{net::SocketAddr, sync::Arc};
use tokio::signal;
use tracing::{error, info};

mod cfg;
mod error;
mod event_bus;
mod grpc;
mod health;
mod signature;

use cfg::NodeConfig;
use error::NodeResult;
use event_bus::{EventBus, NatsEventBus};
use signature::{Ed25519Scheme, SignatureScheme};

/// CLI entry-point.
#[derive(Debug, Parser)]
#[clap(name = "CanvasChain Node", author, version, about)]
struct Cli {
    /// Explicit path to a configuration file (overrides default discovery)
    #[clap(short, long)]
    config: Option<std::path::PathBuf>,

    #[clap(subcommand)]
    command: Option<Commands>,
}

#[derive(Debug, Subcommand)]
enum Commands {
    /// Generate a new Ed25519 key pair and dump the public key
    Keygen,
    /// Run the node with the provided / discovered configuration
    Run,
}

#[tokio::main]
async fn main() -> NodeResult<()> {
    // 1. Parse CLI & bootstrap instrumentation
    let cli = Cli::parse();
    cfg::init_tracing();

    // 2. Dispatch sub-commands
    match cli.command.unwrap_or(Commands::Run) {
        Commands::Keygen => {
            let keypair = Ed25519Scheme::generate();
            println!("Public  key (hex): {}", hex::encode(keypair.public.to_bytes()));
            println!("Secret key (hex): {}", hex::encode(keypair.secret.to_bytes()));
            return Ok(());
        }
        Commands::Run => run_node(cli.config).await,
    }
}

/// Spawns all long-running services required by the node.
async fn run_node(explicit_cfg: Option<std::path::PathBuf>) -> NodeResult<()> {
    // 1. Resolve configuration (env-vars → file → defaults)
    let cfg = NodeConfig::load(explicit_cfg)?;

    info!(node_id = %cfg.identity.id, "🎶 starting CanvasChain node");

    // 2. Initialise dependencies ---------------------------------------------------------------

    // 2a. Event-bus (NATS)
    let event_bus = Arc::new(NatsEventBus::connect(&cfg.event_bus).await?);

    // 2b. Cryptographic strategy (the node can swap curves at runtime if needed)
    let signature_scheme: Arc<dyn SignatureScheme> = match cfg.crypto.curve.as_str() {
        "ed25519" => Arc::new(Ed25519Scheme::new(&cfg.crypto)?),
        unsupported => {
            return Err(error::NodeError::Config(format!("unsupported curve {unsupported}")));
        }
    };

    // 3. Spawn async workers -------------------------------------------------------------------

    // 3a. gRPC API
    let grpc_handle = {
        let service = grpc::NodeGrpc::new(event_bus.clone(), signature_scheme.clone());
        tokio::spawn(async move {
            grpc::serve(service, cfg.rpc.addr()).await;
        })
    };

    // 3b. HTTP health & metrics
    let health_handle = tokio::spawn(async move {
        health::serve(cfg.http.addr()).await;
    });

    // 3c. Signal handling for graceful shutdown
    tokio::select! {
        _ = grpc_handle => {
            error!("gRPC task terminated unexpectedly"); }
        _ = health_handle => {
            error!("HTTP health task terminated unexpectedly"); }
        _ = signal::ctrl_c() => {
            info!("received <ctrl-c>; shutting down"); }
    }

    Ok(())
}

////////////////////////////////////////////////////////////////////////////////////////////////
//  Configuration                                                                              //
////////////////////////////////////////////////////////////////////////////////////////////////

mod cfg {
    use super::*;
    use config::{Config, ConfigError, Environment, File};
    use serde::Deserialize;
    use tracing_subscriber::{fmt, EnvFilter};

    /// Initialises `tracing` with sensible production defaults.
    pub(crate) fn init_tracing() {
        let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
        fmt()
            .with_env_filter(filter)
            .with_target(false)
            .json()
            .init();
    }

    // =========================================================================================
    // Configuration schema
    // =========================================================================================

    #[derive(Debug, Deserialize, Clone)]
    pub struct NodeConfig {
        pub identity: Identity,
        pub rpc: Rpc,
        pub http: Http,
        pub event_bus: EventBus,
        pub crypto: Crypto,
    }

    #[derive(Debug, Deserialize, Clone)]
    pub struct Identity {
        pub id: String,
    }

    #[derive(Debug, Deserialize, Clone)]
    pub struct Rpc {
        pub host: String,
        pub port: u16,
    }
    impl Rpc {
        pub fn addr(&self) -> SocketAddr {
            SocketAddr::new(
                self.host
                    .parse()
                    .expect("RPC host should be a valid IP or hostname"),
                self.port,
            )
        }
    }

    #[derive(Debug, Deserialize, Clone)]
    pub struct Http {
        pub host: String,
        pub port: u16,
    }
    impl Http {
        pub fn addr(&self) -> SocketAddr {
            SocketAddr::new(
                self.host
                    .parse()
                    .expect("HTTP host should be a valid IP or hostname"),
                self.port,
            )
        }
    }

    #[derive(Debug, Deserialize, Clone)]
    pub struct EventBus {
        pub nats_url: String,
        #[serde(default = "default_subject")]
        pub subject: String,
    }
    fn default_subject() -> String {
        "canvas-chain".to_string()
    }

    #[derive(Debug, Deserialize, Clone)]
    pub struct Crypto {
        #[serde(default = "default_curve")]
        pub curve: String,
        /// hex-encoded secret key; if absent a random one will be generated at
        /// first start and persisted to `key_path`.
        pub secret_key: Option<String>,
        /// Path on disk where the node writes / reads its key material.
        pub key_path: Option<std::path::PathBuf>,
    }
    fn default_curve() -> String {
        "ed25519".into()
    }

    // =========================================================================================
    // Loading logic
    // =========================================================================================

    impl NodeConfig {
        pub fn load(explicit: Option<std::path::PathBuf>) -> Result<Self, ConfigError> {
            let mut cfg = Config::builder()
                .add_source(Environment::with_prefix("CC").separator("__"));

            if let Some(path) = explicit {
                cfg = cfg.add_source(File::from(path));
            } else {
                cfg = cfg
                    .add_source(File::with_name("Settings").required(false))
                    .add_source(File::with_name("/etc/canvas-chain/node").required(false));
            }

            cfg.build()?.try_deserialize()
        }
    }
}

////////////////////////////////////////////////////////////////////////////////////////////////
//  Error handling                                                                             //
////////////////////////////////////////////////////////////////////////////////////////////////

mod error {
    use thiserror::Error;

    pub type NodeResult<T> = Result<T, NodeError>;

    /// High-level node errors.
    #[derive(Debug, Error)]
    pub enum NodeError {
        #[error("config error: {0}")]
        Config(String),
        #[error("network error: {0}")]
        Network(String),
        #[error("event-bus error: {0}")]
        Bus(String),
        #[error("crypto error: {0}")]
        Crypto(String),
        #[error("internal: {0}")]
        Internal(String),
    }

    impl From<config::ConfigError> for NodeError {
        fn from(e: config::ConfigError) -> Self {
            Self::Config(e.to_string())
        }
    }

    impl From<nats::Error> for NodeError {
        fn from(e: nats::Error) -> Self {
            Self::Bus(e.to_string())
        }
    }
}

////////////////////////////////////////////////////////////////////////////////////////////////
//  Event-bus (NATS)                                                                           //
////////////////////////////////////////////////////////////////////////////////////////////////

mod event_bus {
    use super::error::{NodeError, NodeResult};
    use async_trait::async_trait;
    use nats::{self, asynk::Connection};
    use serde::{de::DeserializeOwned, Serialize};
    use std::sync::Arc;
    use tokio::sync::broadcast;
    use tracing::info;

    /// Domain event published by services.
    #[derive(Debug, Serialize, Deserialize)]
    pub struct ChainEvent {
        pub kind: String,
        pub payload: serde_json::Value,
    }

    #[async_trait]
    pub trait EventBus: Send + Sync {
        async fn publish<T: Serialize + Send + Sync>(&self, event: &T) -> NodeResult<()>;
        async fn subscribe<T: DeserializeOwned + Send + Sync>(&self) -> NodeResult<broadcast::Receiver<T>>;
    }

    /// NATS-based implementation. Internally uses a `broadcast` channel so
    /// multiple local tasks can consume the same stream without re-subscription.
    pub struct NatsEventBus {
        conn: Connection,
        subject: String,
        tx: broadcast::Sender<serde_json::Value>,
    }

    impl NatsEventBus {
        pub async fn connect(cfg: &super::cfg::EventBus) -> NodeResult<Self> {
            let conn = nats::asynk::connect(&cfg.nats_url).await.map_err(NodeError::from)?;
            let subject = cfg.subject.clone();
            let (tx, _rx) = broadcast::channel(1024);

            // Spawn NATS listener → broadcast
            {
                let tx = tx.clone();
                let mut sub = conn.subscribe(subject.clone()).await?;
                tokio::spawn(async move {
                    while let Some(msg) = sub.next().await {
                        if let Ok(json) = serde_json::from_slice::<serde_json::Value>(&msg.data) {
                            let _ = tx.send(json);
                        }
                    }
                    info!("NATS listener closed");
                });
            }

            Ok(Self { conn, subject, tx })
        }
    }

    #[async_trait]
    impl EventBus for NatsEventBus {
        async fn publish<T: Serialize + Send + Sync>(&self, event: &T) -> NodeResult<()> {
            let bytes = serde_json::to_vec(event).map_err(|e| NodeError::Bus(e.to_string()))?;
            self.conn
                .publish(&self.subject, bytes)
                .await
                .map_err(NodeError::from)
        }

        async fn subscribe<T: DeserializeOwned + Send + Sync>(&self) -> NodeResult<broadcast::Receiver<T>> {
            let rx = self.tx.subscribe();
            let mapped = broadcast::ReceiverStream::new(rx).filter_map(|msg| async move {
                msg.ok()
                    .and_then(|json| serde_json::from_value::<T>(json).ok())
            });
            Ok(mapped.into_inner())
        }
    }
}

////////////////////////////////////////////////////////////////////////////////////////////////
//  Signature strategy                                                                         //
////////////////////////////////////////////////////////////////////////////////////////////////

mod signature {
    use super::error::{NodeError, NodeResult};
    use async_trait::async_trait;
    use ed25519_dalek::{Keypair, PublicKey, SecretKey, Signer, Verifier};
    use rand::rngs::OsRng;
    use serde::{Deserialize, Serialize};
    use tracing::info;

    #[async_trait]
    pub trait SignatureScheme: Send + Sync {
        fn public_key(&self) -> &[u8];
        fn sign(&self, message: &[u8]) -> NodeResult<Vec<u8>>;
        fn verify(&self, message: &[u8], sig: &[u8], pk: &[u8]) -> NodeResult<bool>;
    }

    // =========================================================================================
    // Ed25519 implementation
    // =========================================================================================

    #[derive(Clone)]
    pub struct Ed25519Scheme {
        keypair: Keypair,
    }

    impl Ed25519Scheme {
        pub fn new(cfg: &super::cfg::Crypto) -> NodeResult<Self> {
            // 1. Try to load from disk or env
            if let Some(hex_sk) = &cfg.secret_key {
                let sk_bytes = hex::decode(hex_sk).map_err(|e| NodeError::Crypto(e.to_string()))?;
                let secret = SecretKey::from_bytes(&sk_bytes)
                    .map_err(|e| NodeError::Crypto(e.to_string()))?;
                let public: PublicKey = (&secret).into();
                let keypair = Keypair { secret, public };
                Ok(Self { keypair })
            } else {
                // 2. Generate new pair
                Self::generate()
            }
        }

        pub fn generate() -> NodeResult<Self> {
            let mut csprng = OsRng;
            let keypair = Keypair::generate(&mut csprng);
            info!(public_key = %hex::encode(keypair.public.to_bytes()), "generated new keypair");
            Ok(Self { keypair })
        }
    }

    #[async_trait]
    impl SignatureScheme for Ed25519Scheme {
        fn public_key(&self) -> &[u8] {
            self.keypair.public.as_bytes()
        }

        fn sign(&self, message: &[u8]) -> NodeResult<Vec<u8>> {
            Ok(self.keypair.sign(message).to_bytes().to_vec())
        }

        fn verify(&self, message: &[u8], sig: &[u8], pk: &[u8]) -> NodeResult<bool> {
            let public = PublicKey::from_bytes(pk).map_err(|e| NodeError::Crypto(e.to_string()))?;
            let sig = ed25519_dalek::Signature::from_bytes(sig)
                .map_err(|e| NodeError::Crypto(e.to_string()))?;
            Ok(public.verify(message, &sig).is_ok())
        }
    }
}

////////////////////////////////////////////////////////////////////////////////////////////////
//  gRPC service                                                                               //
////////////////////////////////////////////////////////////////////////////////////////////////

mod grpc {
    use super::error::{NodeError, NodeResult};
    use super::event_bus::EventBus;
    use super::signature::SignatureScheme;
    use async_trait::async_trait;
    use prost::Message;
    use serde::{Deserialize, Serialize};
    use std::sync::Arc;
    use tonic::{transport::Server, Request, Response, Status};
    use tracing::info;

    // =========================================================================================
    // Proto-like structs (avoids external .proto generation for the sake of example)
    // =========================================================================================

    #[derive(Clone, Serialize, Deserialize, Message)]
    pub struct GetStatusRequest {}

    #[derive(Clone, Serialize, Deserialize, Message)]
    pub struct GetStatusResponse {
        #[prost(string, tag = "1")]
        pub node_id: String,
        #[prost(bytes, tag = "2")]
        pub public_key: Vec<u8>,
    }

    #[derive(Clone, Serialize, Deserialize, Message)]
    pub struct SubmitEventRequest {
        #[prost(string, tag = "1")]
        pub kind: String,
        #[prost(string, tag = "2")]
        pub payload: String,
        #[prost(bytes, tag = "3")]
        pub signature: Vec<u8>,
    }

    #[derive(Clone, Serialize, Deserialize, Message)]
    pub struct SubmitEventResponse {}

    // =========================================================================================
    // Service trait
    // =========================================================================================

    #[async_trait]
    pub trait NodeApi: Send + Sync + 'static {
        async fn get_status(
            &self,
            request: Request<GetStatusRequest>,
        ) -> Result<Response<GetStatusResponse>, Status>;

        async fn submit_event(
            &self,
            request: Request<SubmitEventRequest>,
        ) -> Result<Response<SubmitEventResponse>, Status>;
    }

    // =========================================================================================
    // Concrete service
    // =========================================================================================

    #[derive(Clone)]
    pub struct NodeGrpc {
        events: Arc<dyn EventBus>,
        sigs: Arc<dyn SignatureScheme>,
    }

    impl NodeGrpc {
        pub fn new(events: Arc<dyn EventBus>, sigs: Arc<dyn SignatureScheme>) -> Self {
            Self { events, sigs }
        }
    }

    #[async_trait]
    impl NodeApi for NodeGrpc {
        async fn get_status(
            &self,
            _request: Request<GetStatusRequest>,
        ) -> Result<Response<GetStatusResponse>, Status> {
            let rsp = GetStatusResponse {
                node_id: hex::encode(self.sigs.public_key()),
                public_key: self.sigs.public_key().to_vec(),
            };
            Ok(Response::new(rsp))
        }

        async fn submit_event(
            &self,
            request: Request<SubmitEventRequest>,
        ) -> Result<Response<SubmitEventResponse>, Status> {
            let req = request.into_inner();

            // Verify signature
            let ok = self
                .sigs
                .verify(req.payload.as_bytes(), &req.signature, self.sigs.public_key())
                .map_err(node_to_status)?;
            if !ok {
                return Err(Status::permission_denied("invalid signature"));
            }

            // Publish to event bus
            self.events
                .publish(&serde_json::json!({
                    "kind": req.kind,
                    "payload": req.payload,
                }))
                .await
                .map_err(node_to_status)?;

            Ok(Response::new(SubmitEventResponse {}))
        }
    }

    // =========================================================================================
    // Tonic plumbing
    // =========================================================================================

    pub async fn serve<S>(svc: S, addr: std::net::SocketAddr)
    where
        S: NodeApi + 'static,
    {
        info!(%addr, "🚀 gRPC listening");
        // Build router from the NodeApi implementation using tonic's `service_fn`
        let service = tonic::transport::server::Router::new()
            .add_service(tonic::codegen::server::interceptor(
                tonic::codegen::service_fn(move |req| {
                    let svc = svc.clone();
                    async move {
                        match req.uri().path() {
                            "/node.Node/GetStatus" => {
                                let data = req.into_body().collect().await?;
                                let input =
                                    GetStatusRequest::decode(data.reader()).map_err(node_to_status)?;
                                svc.get_status(Request::new(input)).await
                            }
                            "/node.Node/SubmitEvent" => {
                                let data = req.into_body().collect().await?;
                                let input =
                                    SubmitEventRequest::decode(data.reader()).map_err(node_to_status)?;
                                svc.submit_event(Request::new(input)).await
                            }
                            _ => Err(Status::unimplemented("unknown path")),
                        }
                    }
                }),
                |req| Ok(req),
            ));

        Server::builder()
            .add_service(service)
            .serve(addr)
            .await
            .unwrap();
    }

    fn node_to_status(err: NodeError) -> Status {
        Status::internal(err.to_string())
    }
}

////////////////////////////////////////////////////////////////////////////////////////////////
//  Health / metrics                                                                           //
////////////////////////////////////////////////////////////////////////////////////////////////

mod health {
    use axum::{
        routing::{get, Router},
        Json,
    };
    use serde_json::json;
    use std::net::SocketAddr;
    use tokio::time::{interval, Duration};
    use tracing::{error, info};

    pub async fn serve(addr: SocketAddr) {
        // background liveness probe for readiness detection
        tokio::spawn(async {
            let mut ticker = interval(Duration::from_secs(30));
            loop {
                ticker.tick().await;
                info!("heartbeat – node is alive");
            }
        });

        let app = Router::new().route("/health", get(health));

        info!(%addr, "🌡️  health endpoint listening");

        if let Err(err) = axum::Server::bind(&addr).serve(app.into_make_service()).await {
            error!(?err, "HTTP server crashed");
        }
    }

    async fn health() -> Json<serde_json::Value> {
        Json(json!({
            "status": "ok",
            "timestamp": chrono::Utc::now(),
        }))
    }
}
```
