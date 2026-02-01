```rust
//! CanvasChain Symphony – API Gateway
//! ==================================
//! The API-gateway is the single entry point exposed to wallets, DApps and
//! dashboards.  It is responsible for:
//
//! 1. Accepting public-facing HTTP/JSON requests
//! 2. Forwarding them to the appropriate internal gRPC micro-services
//! 3. Publishing / subscribing to the event-bus (NATS) for real-time updates
//! 4. Applying cross-cutting concerns (authN/Z, time-outs, retries, tracing)
//!
//! Each micro-service hides behind a strongly-typed client defined in this
//! crate, so that the remainder of the gateway can stay oblivious to the
//! transport details.
//!
//! ────────────────────────────────────────────────────────────────────────────

use std::{net::SocketAddr, sync::Arc, time::Duration};

use axum::{
    extract::{Extension, Path},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use nats::{self, Connection as NatsConnection};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokio::signal;
use tonic::transport::{Channel, Endpoint};
use tower::{limit::ConcurrencyLimitLayer, ServiceBuilder};
use tower_http::{cors::CorsLayer, trace::TraceLayer};
use tracing::{error, info, instrument};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

// ────────────────────────────────────────────────────────────────────────────
//  Configuration helpers
// ────────────────────────────────────────────────────────────────────────────

/// Runtime configuration.
///
/// Values are read from the environment using the [`envy`] crate
/// or can be supplied through a `config.*` file by the workspace.
#[derive(Clone, Debug, Deserialize)]
pub struct Config {
    /// HTTP address the gateway listens on
    #[serde(default = "defaults::http_addr")]
    pub http_addr: SocketAddr,

    /// Endpoint of the Composition gRPC service
    #[serde(default = "defaults::composition_ep")]
    pub composition_ep: String,

    /// Endpoint of the Minting gRPC service
    #[serde(default = "defaults::minting_ep")]
    pub minting_ep: String,

    /// Endpoint of the Marketplace gRPC service
    #[serde(default = "defaults::market_ep")]
    pub marketplace_ep: String,

    /// NATS connection string
    #[serde(default = "defaults::nats_url")]
    pub nats_url: String,

    /// Maximum number of concurrent HTTP requests
    #[serde(default = "defaults::concurrency_limit")]
    pub concurrency_limit: usize,
}

mod defaults {
    use std::{net::SocketAddr, str::FromStr};

    pub(super) fn http_addr() -> SocketAddr {
        SocketAddr::from_str("0.0.0.0:8080").expect("valid default addr")
    }
    pub(super) fn composition_ep() -> String {
        "http://composition:50051".into()
    }
    pub(super) fn minting_ep() -> String {
        "http://minting:50052".into()
    }
    pub(super) fn market_ep() -> String {
        "http://marketplace:50053".into()
    }
    pub(super) fn nats_url() -> String {
        "nats://nats:4222".into()
    }
    pub(super) fn concurrency_limit() -> usize {
        1024
    }
}

impl Config {
    pub fn from_env() -> anyhow::Result<Self> {
        Ok(envy::prefixed("CANVAS_").from_env::<Self>()?)
    }
}

// ────────────────────────────────────────────────────────────────────────────
//  Domain DTOs (only the subset required by the gateway)
// ────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize)]
pub struct NftMintRequest {
    pub name: String,
    pub description: String,
    #[serde(default)]
    pub attributes: serde_json::Value,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Nft {
    pub id: String,
    pub owner: String,
    pub metadata: serde_json::Value,
}

// ────────────────────────────────────────────────────────────────────────────
//  Error handling
// ────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum GatewayError {
    #[error("gRPC transport error: {0}")]
    Transport(#[from] tonic::transport::Error),

    #[error("gRPC status: {0}")]
    GrpcStatus(#[from] tonic::Status),

    #[error("NATS error: {0}")]
    Nats(#[from] nats::Error),

    #[error("invalid request: {0}")]
    Invalid(String),
}

impl IntoResponse for GatewayError {
    fn into_response(self) -> Response {
        error!("responding with error: {self}");
        let body = Json(serde_json::json!({ "error": self.to_string() }));
        (StatusCode::BAD_REQUEST, body).into_response()
    }
}

// ────────────────────────────────────────────────────────────────────────────
//  Micro-service gRPC clients (manually declared thin wrappers)
// ────────────────────────────────────────────────────────────────────────────

mod clients {
    use super::*;

    /// Blanket builder for all gRPC channels so we don't
    /// repeat the same TLS / timeout configs.
    async fn channel(endpoint: &str) -> Result<Channel, GatewayError> {
        let ep = Endpoint::from_shared(endpoint.to_string())?
            .timeout(Duration::from_secs(5))
            .concurrency_limit(256)
            .tcp_keepalive(Some(Duration::from_secs(30)));

        Ok(ep.connect().await?)
    }

    // We don’t have the generated proto-code in this snippet, therefore we define
    // minimal traits to satisfy the compiler.  In a real project each client would
    // be generated by `tonic-build` and re-exported by its own crate.

    pub mod composition {
        tonic::include_proto!("composition");
    }
    pub mod minting {
        tonic::include_proto!("minting");
    }
    pub mod marketplace {
        tonic::include_proto!("marketplace");
    }

    // Concrete wrappers.  Only the subset of methods required by the HTTP API is
    // exposed, but the inner generated client is still available for power-users.

    #[derive(Clone)]
    pub struct CompositionClient {
        inner: composition::composer_client::ComposerClient<Channel>,
    }

    impl CompositionClient {
        pub async fn connect(endpoint: &str) -> Result<Self, GatewayError> {
            let inner = composition::composer_client::ComposerClient::new(channel(endpoint).await?);
            Ok(Self { inner })
        }
        #[allow(dead_code)]
        pub async fn latest_piece(&mut self) -> Result<String, GatewayError> {
            // placeholder
            Ok("latest-piece-hash".into())
        }
    }

    #[derive(Clone)]
    pub struct MintingClient {
        inner: minting::minter_client::MinterClient<Channel>,
    }

    impl MintingClient {
        pub async fn connect(endpoint: &str) -> Result<Self, GatewayError> {
            let inner = minting::minter_client::MinterClient::new(channel(endpoint).await?);
            Ok(Self { inner })
        }
        pub async fn mint(
            &mut self,
            req: super::NftMintRequest,
        ) -> Result<String, GatewayError> {
            use minting::MintNftRequest;

            let request = tonic::Request::new(MintNftRequest {
                name: req.name,
                description: req.description,
                attributes_json: serde_json::to_string(&req.attributes)
                    .unwrap_or_else(|_| "{}".into()),
            });

            let response = self.inner.mint_nft(request).await?.into_inner();
            Ok(response.nft_id)
        }
    }

    #[derive(Clone)]
    pub struct MarketplaceClient {
        inner: marketplace::market_client::MarketClient<Channel>,
    }

    impl MarketplaceClient {
        pub async fn connect(endpoint: &str) -> Result<Self, GatewayError> {
            let inner = marketplace::market_client::MarketClient::new(channel(endpoint).await?);
            Ok(Self { inner })
        }

        pub async fn nft(&mut self, nft_id: String) -> Result<super::Nft, GatewayError> {
            use marketplace::GetNftRequest;

            let request = tonic::Request::new(GetNftRequest { nft_id });

            let resp = self.inner.get_nft(request).await?.into_inner();

            Ok(super::Nft {
                id: resp.id,
                owner: resp.owner,
                metadata: serde_json::from_str(&resp.metadata_json)
                    .unwrap_or_else(|_| serde_json::json!({})),
            })
        }
    }
}

// ────────────────────────────────────────────────────────────────────────────
//  Shared application-state
// ────────────────────────────────────────────────────────────────────────────

#[derive(Clone)]
pub struct AppState {
    pub cfg: Config,
    pub composition: clients::CompositionClient,
    pub minting: clients::MintingClient,
    pub marketplace: clients::MarketplaceClient,
    pub nats: NatsConnection,
}

// ────────────────────────────────────────────────────────────────────────────
//  HTTP handlers
// ────────────────────────────────────────────────────────────────────────────

#[instrument(skip(state))]
async fn mint_nft(
    Extension(state): Extension<Arc<AppState>>,
    Json(req): Json<NftMintRequest>,
) -> Result<impl IntoResponse, GatewayError> {
    let mut minting = state.minting.clone();

    // Mint through gRPC
    let nft_id = minting.mint(req.clone()).await?;

    // Broadcast via NATS (fire-and-forget)
    state
        .nats
        .publish(
            "events.nft.minted",
            serde_json::to_vec(&serde_json::json!({ "nft_id": nft_id }))?,
        )
        .ok(); // ignore failures for now

    Ok((StatusCode::CREATED, Json(serde_json::json!({ "id": nft_id }))))
}

#[instrument(skip(state))]
async fn get_nft(
    Path(nft_id): Path<String>,
    Extension(state): Extension<Arc<AppState>>,
) -> Result<impl IntoResponse, GatewayError> {
    let mut market = state.marketplace.clone();
    let nft = market.nft(nft_id).await?;
    Ok(Json(nft))
}

async fn healthcheck() -> impl IntoResponse {
    (StatusCode::OK, "ok")
}

// ────────────────────────────────────────────────────────────────────────────
//  Startup
// ────────────────────────────────────────────────────────────────────────────

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // ───── Logger/Tracing ───────────────────────────────────────────────────
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::fmt::layer()
                .with_target(false)
                .with_timer(tracing_subscriber::fmt::time::ChronoUtc::rfc3339()),
        )
        .with(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    // ───── Configuration ────────────────────────────────────────────────────
    let cfg = Config::from_env()?;
    info!(?cfg, "configuration loaded");

    // ───── Service-clients ──────────────────────────────────────────────────
    let composition = clients::CompositionClient::connect(&cfg.composition_ep).await?;
    let minting = clients::MintingClient::connect(&cfg.minting_ep).await?;
    let marketplace = clients::MarketplaceClient::connect(&cfg.marketplace_ep).await?;

    // ───── NATS (event-bus) ─────────────────────────────────────────────────
    let nats = nats::connect(&cfg.nats_url)?;

    let state = Arc::new(AppState {
        cfg: cfg.clone(),
        composition,
        minting,
        marketplace,
        nats,
    });

    // ───── HTTP Router ──────────────────────────────────────────────────────
    let router = Router::new()
        .route("/healthz", get(healthcheck))
        .route("/nfts/:id", get(get_nft))
        .route("/nfts", post(mint_nft))
        .layer(
            ServiceBuilder::new()
                .layer(TraceLayer::new_for_http())
                .layer(CorsLayer::permissive())
                .layer(ConcurrencyLimitLayer::new(cfg.concurrency_limit))
                .layer(axum::extract::ExtensionLayer::new(state)),
        );

    // ───── Server ───────────────────────────────────────────────────────────
    info!("🚀  API-gateway listening on {}", cfg.http_addr);
    axum::Server::bind(&cfg.http_addr)
        .serve(router.into_make_service())
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    Ok(())
}

/// Blocks until the process receives `SIGTERM` / `Ctrl-C`.
async fn shutdown_signal() {
    let ctrl_c = async {
        signal::ctrl_c()
            .await
            .expect("failed to install Ctrl-C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        use tokio::signal::unix::{signal, SignalKind};
        signal(SignalKind::terminate())
            .expect("failed to install signal handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }

    info!("signal received, shutting down");
}
```
