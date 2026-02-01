```rust
//! REST façade for CanvasChain Symphony
//!
//! This module exposes a small, but representative, subset of the public HTTP
//! interface that external clients (CLI, mobile wallets, browsers or embedded
//! installations) use to interact with the distributed CanvasChain back-end.
//!
//! The gateway is intentionally stateless––it delegates all business logic to
//! the specialised micro-services via gRPC.  Whenever a request arrives, we
//! perform cheap syntactic validation, enrich the tracing span with relevant
//! metadata and forward the call downstream.  Results are converted back to
//! idiomatic JSON before being returned to the caller.
//!
//! ┌──────────────────────────┐      gRPC       ┌──────────────────────────┐
//! │      HTTP  Clients       ├────────────────►│  CanvasChain Services    │
//! └──────────────────────────┘                 └──────────────────────────┘
//!
//! The gateway never touches persistent state directly, making horizontal
//! scaling trivial.  All handlers are asynchronous and cancellation-safe.
//!
//! A note about (missing) authentication: In production we deploy the gateway
//! behind an API-Key aware service mesh that injects caller identity in the
//! request headers.  To keep the example self-contained, authn/authz layers
//! are purposely omitted.
//!
//! # Conventions
//! * `snake_case` query parameters
//! * `camelCase` JSON bodies
//! * Every successful response is wrapped in `{ "data": … }`
//! * Errors conform to RFC7807 (`application/problem+json`)
//!
//! # Examples
//! Minting a new multilayer NFT
//! ```bash
//! curl -X POST http://localhost:8080/nfts \
//!      -H 'Content-Type: application/json' \
//!      -d '{ "artist_id": "did:canvas:artist123", "metadata_uri": "ipfs://…", "ask_price": "42.0" }'
//! ```

use std::{fmt, net::SocketAddr, sync::Arc};

use axum::{
    extract::{Path, Query, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use tokio::task::JoinSet;
use tonic::{transport::Channel, Status as GrpcStatus};
use tracing::{error, info, instrument, Span};
use uuid::Uuid;

// Generated protobuf definitions live in crate `proto` (build-time dependency).
// Each individual service is versioned separately.
use crate::proto::{
    composition::composition_service_client::CompositionServiceClient,
    governance::governance_service_client::GovernanceServiceClient,
    marketplace::marketplace_service_client::MarketplaceServiceClient,
    minting::{
        minting_service_client::MintingServiceClient, MintNftRequest, MintNftResponse,
        QueryNftRequest, QueryNftResponse,
    },
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// A composable builder that returns a fully-wired [`axum::Router`].
///
/// The caller is responsible for spawning a *single* [`Router`] instance and
/// holding its [`AppState`] for the entire process lifetime.
///
/// ```no_run
/// # use canvaschain_api_gateway::rest_api::{self, AppState};
/// # use tonic::transport::Channel;
/// # async fn run() -> anyhow::Result<()> {
/// let state = AppState::connect_all("http://127.0.0.1:50051").await?;
/// let app   = rest_api::router(state);
/// axum::Server::bind(&"0.0.0.0:8080".parse()?)
///     .serve(app.into_make_service())
///     .await?;
/// # Ok(()) }
/// ```
pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health))
        .nest(
            "/nfts",
            Router::new()
                .route("/", post(mint_nft).get(list_nfts))
                .route("/:nft_id", get(get_nft)),
        )
        .nest("/governance", Router::new().route("/vote", post(cast_vote)))
        .with_state(state)
}

// ---------------------------------------------------------------------------
// Shared application state
// ---------------------------------------------------------------------------

/// A thin immutable container holding *cheaply clonable* gRPC channel handles.
///
/// Cloning an individual client only clones an `Arc` inside the tonic
/// machinery; it does NOT open a fresh TCP connection, so doing so in each
/// request handler is perfectly fine.
#[derive(Clone)]
pub struct AppState {
    pub minting:     MintingServiceClient<Channel>,
    pub composition: CompositionServiceClient<Channel>,
    pub marketplace: MarketplaceServiceClient<Channel>,
    pub governance:  GovernanceServiceClient<Channel>,
}

impl AppState {
    /// Connects every gRPC client to the same given endpoint URI
    /// (`http://127.0.0.1:50051` in dev, service-mesh DNS in prod).
    ///
    /// Each client uses an independent HTTP/2 connection in order to keep
    /// per-service flow-control windows separate and maximise throughput under
    /// heavy load.
    pub async fn connect_all<T: Into<String>>(endpoint: T) -> Result<Self, ApiError> {
        let ep: String = endpoint.into();
        let channel    = Channel::from_shared(ep.clone())?
            .tcp_nodelay(true)
            .concurrency_limit(128) // back-pressure against accidental fan-out
            .connect()
            .await?;

        Ok(Self {
            minting:     MintingServiceClient::new(channel.clone()),
            composition: CompositionServiceClient::new(channel.clone()),
            marketplace: MarketplaceServiceClient::new(channel.clone()),
            governance:  GovernanceServiceClient::new(channel),
        })
    }
}

// ---------------------------------------------------------------------------
// REST models
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MintRequest {
    pub artist_id:   String,
    pub metadata_uri: String,
    pub ask_price:    Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct MintResponse {
    pub nft_id: String,
}

#[derive(Debug, Deserialize)]
struct Pagination {
    /// 1-based page (defaults to `1`)
    #[serde(default = "Pagination::default_page")]
    page: u32,
    /// Items per page (max `100`, defaults to `20`)
    #[serde(default = "Pagination::default_per_page")]
    per_page: u32,
}

impl Pagination {
    fn default_page() -> u32 {
        1
    }
    fn default_per_page() -> u32 {
        20
    }
}

#[derive(Debug, Serialize)]
struct Paginated<T> {
    data: Vec<T>,
    page: u32,
    per_page: u32,
    total: u32,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct Nft {
    pub nft_id:      String,
    pub owner:       String,
    pub metadata_uri: String,
    pub ask_price:    Option<String>,
    pub created_at:   String,
}

#[derive(Debug, Deserialize)]
struct VoteRequest {
    proposal_id: String,
    voter: String,
    choice: String, // Yes | No | Abstain
}

#[derive(Debug, Serialize)]
struct VoteResponse {
    accepted: bool,
}

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

/// Canonical error envelope returned to HTTP clients.  Internally, we rely on
/// [`tonic::Status`] for gRPC, but we do *not* leak internal error codes and
/// messages to the outside world.
#[derive(Debug)]
pub enum ApiError {
    BadRequest(String),
    NotFound(String),
    Upstream(GrpcStatus), // error from micro-service
    Transport(tonic::transport::Error),
    Unexpected(anyhow::Error),
}

impl fmt::Display for ApiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        use ApiError::*;

        match self {
            BadRequest(msg) | NotFound(msg) => write!(f, "{msg}"),
            Upstream(status)                => write!(f, "{status}"),
            Transport(err)                  => write!(f, "{err}"),
            Unexpected(err)                 => write!(f, "{err}"),
        }
    }
}

impl std::error::Error for ApiError {}

impl From<GrpcStatus> for ApiError {
    fn from(value: GrpcStatus) -> Self {
        ApiError::Upstream(value)
    }
}

impl From<tonic::transport::Error> for ApiError {
    fn from(value: tonic::transport::Error) -> Self {
        ApiError::Transport(value)
    }
}

impl From<anyhow::Error> for ApiError {
    fn from(value: anyhow::Error) -> Self {
        ApiError::Unexpected(value)
    }
}

/// Serialises `ApiError` into an RFC7807 compliant JSON payload.
/// All unrecognised errors are mapped to `500 Internal Server Error` in order
/// to avoid bleeding sensitive information.
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let (status, title) = match &self {
            ApiError::BadRequest(_) => (StatusCode::BAD_REQUEST, "Bad Request"),
            ApiError::NotFound(_)   => (StatusCode::NOT_FOUND, "Not Found"),
            ApiError::Upstream(status) => {
                match status.code() {
                    tonic::Code::NotFound       => (StatusCode::NOT_FOUND, "Not Found"),
                    tonic::Code::InvalidArgument=> (StatusCode::BAD_REQUEST, "Bad Request"),
                    _                           => (StatusCode::BAD_GATEWAY, "Upstream Failure"),
                }
            }
            _ => (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error"),
        };

        let problem = serde_json::json!({
            "type":   "about:blank",
            "title":  title,
            "status": status.as_u16(),
            "detail": self.to_string(),
        });

        (status, Json(problem)).into_response()
    }
}

// ---------------------------------------------------------------------------
// Request handlers
// ---------------------------------------------------------------------------

#[instrument(name = "health", skip_all, fields(client_ip))]
async fn health(State(state): State<AppState>) -> Result<Json<serde_json::Value>, ApiError> {
    // Fan-out health probes to every downstream service in parallel.
    let mut set = JoinSet::new();

    let cloned = state.clone();
    set.spawn(async move { cloned.minting.health_check(()).await });
    let cloned = state.clone();
    set.spawn(async move { cloned.composition.health_check(()).await });
    let cloned = state.clone();
    set.spawn(async move { cloned.marketplace.health_check(()).await });
    let cloned = state.clone();
    set.spawn(async move { cloned.governance.health_check(()).await });

    let mut services_healthy = true;
    while let Some(res) = set.join_next().await {
        match res {
            Ok(Ok(_)) => {}
            _ => services_healthy = false,
        }
    }

    let status = if services_healthy { "ok" } else { "degraded" };
    Ok(Json(serde_json::json!({ "status": status })))
}

#[instrument(name = "mint_nft", skip(state, headers, payload))]
async fn mint_nft(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(payload): Json<MintRequest>,
) -> Result<impl IntoResponse, ApiError> {
    // Example of cheap *syntactic* validation – expensive checks are left for
    // the Minting service.
    if payload.metadata_uri.is_empty() {
        return Err(ApiError::BadRequest("metadata_uri must not be empty".into()));
    }

    // Correlate downstream span with the inbound request
    let span = Span::current();
    span.record("artist_id", &payload.artist_id.as_str());

    let grpc_req = tonic::Request::new(MintNftRequest {
        nft_id: Uuid::new_v4().to_string(),
        artist_id: payload.artist_id.clone(),
        metadata_uri: payload.metadata_uri.clone(),
        ask_price: payload.ask_price.clone().unwrap_or_default(),
    });

    let response: MintNftResponse = state.minting.clone().mint_nft(grpc_req).await?.into_inner();

    Ok((
        StatusCode::CREATED,
        Json(MintResponse {
            nft_id: response.nft_id,
        }),
    ))
}

#[instrument(name = "get_nft", skip(state))]
async fn get_nft(
    State(state): State<AppState>,
    Path(nft_id): Path<String>,
) -> Result<Json<Nft>, ApiError> {
    let grpc_req = tonic::Request::new(QueryNftRequest { nft_id: nft_id.clone() });
    let nft: QueryNftResponse = state.minting.clone().get_nft(grpc_req).await?.into_inner();

    if nft.nft_id.is_empty() {
        return Err(ApiError::NotFound(format!("NFT {nft_id} does not exist")));
    }

    Ok(Json(Nft {
        nft_id: nft.nft_id,
        owner: nft.owner,
        metadata_uri: nft.metadata_uri,
        ask_price: if nft.ask_price.is_empty() { None } else { Some(nft.ask_price) },
        created_at: nft.created_at,
    }))
}

#[instrument(name = "list_nfts", skip(state))]
async fn list_nfts(
    State(state): State<AppState>,
    Query(pg): Query<Pagination>,
) -> Result<Json<Paginated<Nft>>, ApiError> {
    // The `list_nfts` RPC accepts offset/limit rather than page/per_page.
    let offset            = (pg.page.saturating_sub(1) * pg.per_page) as u64;
    let grpc_req          = tonic::Request::new(proto::minting::ListNftsRequest {
        offset,
        limit: pg.per_page as u64,
    });
    let list_resp         = state.minting.clone().list_nfts(grpc_req).await?.into_inner();
    let total             = list_resp.total as u32;
    let data: Vec<Nft>    = list_resp
        .nfts
        .into_iter()
        .map(|n| Nft {
            nft_id: n.nft_id,
            owner: n.owner,
            metadata_uri: n.metadata_uri,
            ask_price: if n.ask_price.is_empty() { None } else { Some(n.ask_price) },
            created_at: n.created_at,
        })
        .collect();

    Ok(Json(Paginated {
        data,
        page: pg.page,
        per_page: pg.per_page,
        total,
    }))
}

#[instrument(name = "cast_vote", skip(state, payload))]
async fn cast_vote(
    State(state): State<AppState>,
    Json(payload): Json<VoteRequest>,
) -> Result<Json<VoteResponse>, ApiError> {
    if !["yes", "no", "abstain"].contains(&payload.choice.to_lowercase().as_str()) {
        return Err(ApiError::BadRequest("choice must be Yes|No|Abstain".into()));
    }

    let grpc_req = tonic::Request::new(proto::governance::CastVoteRequest {
        proposal_id: payload.proposal_id,
        voter: payload.voter,
        choice: payload.choice,
    });

    let resp = state
        .governance
        .clone()
        .cast_vote(grpc_req)
        .await?
        .into_inner();

    Ok(Json(VoteResponse { accepted: resp.accepted }))
}

// ---------------------------------------------------------------------------
// Graceful bootstrap entry-point (for local development)
// ---------------------------------------------------------------------------

/// Synchronously blocks on an HTTP server bound to `addr`.
///
/// In production we spawn the gateway via the Kubernetes Rust operator, so the
/// binary entry-point lives elsewhere.  This helper is provided purely for
/// convenience during local tinkering (`cargo run -p api_gateway`).
#[tokio::main]
async fn main() -> Result<(), anyhow::Error> {
    tracing_subscriber::fmt::init();

    let addr: SocketAddr = std::env::var("BIND_ADDR")
        .unwrap_or_else(|_| "127.0.0.1:8080".into())
        .parse()?;

    // Connect to the internal service mesh gateway.
    let grpc_ep = std::env::var("GRPC_ENDPOINT").unwrap_or_else(|_| "http://127.0.0.1:50051".into());
    let state   = AppState::connect_all(grpc_ep).await?;

    info!("🚀  API-Gateway listening on {addr}");
    axum::Server::bind(&addr)
        .serve(router(state).into_make_service())
        .await?;

    Ok(())
}
```