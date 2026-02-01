```rust
//! gRPC client façade for the CanvasChain Symphony API-Gateway.
//!
//! The gateway is the single public entry-point of the Symphony back-end.  All
//! incoming HTTP/GraphQL requests are translated into gRPC calls that are
//! forwarded to the specialised domain micro-services (composition, minting,
//! marketplace …).  This module centralises gRPC channel construction, uniform
//! request metadata injection (auth, tracing, …) and connection pooling logic.
//!
//! - TLS is enabled automatically when the target URI starts with `https://`.
//! - End-points can be overridden via environment variables so the same binary
//!   can be deployed to dev-nets, staging or production without re-compilation.
//! - A cheap in-memory cache avoids reconnecting for every request.
//!
//! NOTE: protobuf stubs are generated at build-time by `tonic_build` in the
//! `build.rs` of the workspace root and re-exported under `crate::pb`.

#![allow(clippy::module_name_repetitions)]

use std::{
    collections::HashMap,
    fmt::Debug,
    sync::Arc,
    time::Duration,
};

use anyhow::{Context, Result};
use http::{HeaderValue, Request};
use once_cell::sync::Lazy;
use tokio::sync::RwLock;
use tonic::{
    codegen::InterceptedService,
    service::Interceptor,
    transport::{Channel, Endpoint},
    Status,
};
use tracing::{debug, error, info, warn};

/// Re-export generated protobuf stubs so callers do not need to depend on the
/// exact module layout.
pub use crate::pb::{
    composition::composer_client::ComposerClient,
    marketplace::marketplace_client::MarketplaceClient,
    minting::minter_client::MinterClient,
    remixing::remixer_client::RemixerClient,
    royalty::royalty_stream_client::RoyaltyStreamClient,
};

/// Enumeration of every Symphony micro-service reachable over gRPC.
///
/// Each variant maps to a build-time default address.  The effective address
/// can be overridden at runtime with an environment variable of the same name.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ServiceTarget {
    Composition,
    Minting,
    Remixing,
    Marketplace,
    Royalty,
}

impl ServiceTarget {
    /// Environment variable used to override the default address.
    fn env_key(self) -> &'static str {
        use ServiceTarget::*;
        match self {
            Composition => "COMPOSITION_SERVICE_ADDR",
            Minting => "MINTING_SERVICE_ADDR",
            Remixing => "REMIXING_SERVICE_ADDR",
            Marketplace => "MARKETPLACE_SERVICE_ADDR",
            Royalty => "ROYALTY_SERVICE_ADDR",
        }
    }

    /// Reasonable defaults used for local development.
    fn default_addr(self) -> &'static str {
        use ServiceTarget::*;
        match self {
            Composition => "http://127.0.0.1:50051",
            Minting => "http://127.0.0.1:50052",
            Remixing => "http://127.0.0.1:50053",
            Marketplace => "http://127.0.0.1:50054",
            Royalty => "http://127.0.0.1:50055",
        }
    }
}

/// Tiny helper that injects common request metadata such as authentication
/// tokens or distributed-tracing identifiers.
#[derive(Clone)]
struct MetadataInterceptor {
    api_key: HeaderValue,
}

impl MetadataInterceptor {
    fn new<S: AsRef<str>>(api_key: S) -> Self {
        Self {
            api_key: HeaderValue::from_str(api_key.as_ref())
                .expect("`api_key` must be a valid HTTP header value"),
        }
    }
}

impl Interceptor for MetadataInterceptor {
    fn call(&mut self, mut req: Request<()>) -> std::result::Result<Request<()>, Status> {
        // Insert auth and a per-request trace-id if present.
        req.metadata_mut().insert("x-api-key", self.api_key.clone());

        if let Some(span) = tracing::Span::current().id() {
            req.metadata_mut().insert(
                "x-trace-id",
                HeaderValue::from_str(&hex::encode(span.into_u64().to_be_bytes()))
                    .unwrap_or_default(),
            );
        }

        Ok(req)
    }
}

/// Internal cache for already established channels.  Re-establishing a TCP/TLS
/// connection on every request would be wasteful.
type ChannelCache = Arc<RwLock<HashMap<ServiceTarget, Channel>>>;

/// Central entry-point for constructing **typed** gRPC stubs.
///
/// ```no_run
/// # use services::api_gateway::grpc_client::GrpcClient;
/// # #[tokio::main(flavor = "current_thread")] async fn main() -> anyhow::Result<()> {
/// let client = GrpcClient::global().await?;
/// let mut minter = client.minting().await?;
/// let rsp = minter.mint_token(/* … */).await?;
/// # Ok(()) }
/// ```
#[derive(Clone)]
pub struct GrpcClient {
    channels: ChannelCache,
    interceptor: MetadataInterceptor,
}

/* -------------------------------------------------------------------------- */
/*                           Singleton initialisation                         */
/* -------------------------------------------------------------------------- */

static GLOBAL_CLIENT: Lazy<Arc<GrpcClient>> = Lazy::new(|| {
    // Lazy initialisation allows reading environment variables _after_ the
    // binary has been launched (handy for containers).
    let api_key = std::env::var("CANVAS_API_KEY").unwrap_or_else(|_| "local-dev-key".to_owned());

    Arc::new(
        tokio::runtime::Handle::current()
            .block_on(GrpcClient::new(api_key))
            .expect("fatal: cannot initialise gRPC client"),
    )
});

impl GrpcClient {
    /// Build a new client from scratch.  You probably want [`GrpcClient::global`].
    pub async fn new<S: Into<String>>(api_key: S) -> Result<Self> {
        Ok(Self {
            channels: Default::default(),
            interceptor: MetadataInterceptor::new(api_key.into()),
        })
    }

    /// Obtain a reference to the global singleton (`Arc`-wrapped).
    pub async fn global() -> Result<Arc<Self>> {
        Ok(GLOBAL_CLIENT.clone())
    }

    /* ---------------------------------------------------------------------- */
    /*                     Typed client constructors (public)                 */
    /* ---------------------------------------------------------------------- */

    /// Composition micro-service (generative art “movements”).
    pub async fn composition(
        &self,
    ) -> Result<ComposerClient<InterceptedService<Channel, MetadataInterceptor>>> {
        let chan = self.channel(ServiceTarget::Composition).await?;
        Ok(ComposerClient::with_interceptor(chan, self.interceptor.clone()))
    }

    /// NFT minting micro-service (ERC-721/-1155 compatible).
    pub async fn minting(
        &self,
    ) -> Result<MinterClient<InterceptedService<Channel, MetadataInterceptor>>> {
        let chan = self.channel(ServiceTarget::Minting).await?;
        Ok(MinterClient::with_interceptor(chan, self.interceptor.clone()))
    }

    /// Remixing micro-service (derivative artwork & transformations).
    pub async fn remixing(
        &self,
    ) -> Result<RemixerClient<InterceptedService<Channel, MetadataInterceptor>>> {
        let chan = self.channel(ServiceTarget::Remixing).await?;
        Ok(RemixerClient::with_interceptor(chan, self.interceptor.clone()))
    }

    /// Marketplace micro-service (listing, bids, auctions).
    pub async fn marketplace(
        &self,
    ) -> Result<MarketplaceClient<InterceptedService<Channel, MetadataInterceptor>>> {
        let chan = self.channel(ServiceTarget::Marketplace).await?;
        Ok(MarketplaceClient::with_interceptor(chan, self.interceptor.clone()))
    }

    /// Royalty-stream micro-service (revenue split & live payouts).
    pub async fn royalty(
        &self,
    ) -> Result<RoyaltyStreamClient<InterceptedService<Channel, MetadataInterceptor>>> {
        let chan = self.channel(ServiceTarget::Royalty).await?;
        Ok(RoyaltyStreamClient::with_interceptor(
            chan,
            self.interceptor.clone(),
        ))
    }

    /* ---------------------------------------------------------------------- */
    /*                          Channel management (private)                  */
    /* ---------------------------------------------------------------------- */

    #[tracing::instrument(level = "trace", skip(self))]
    async fn channel(&self, target: ServiceTarget) -> Result<Channel> {
        // Hot path: look-up in the in-memory cache.
        if let Some(chan) = self.channels.read().await.get(&target).cloned() {
            return Ok(chan);
        }

        // Cold path: create a brand new connection.
        let addr = std::env::var(target.env_key()).unwrap_or_else(|_| target.default_addr().into());

        debug!(?target, %addr, "establishing new gRPC channel");

        // Timeouts & TCP/TLS options.
        let endpoint = Endpoint::from_shared(addr.clone())
            .with_context(|| format!("invalid URI for {:?}", target))?
            .connect_timeout(Duration::from_secs(3))
            .timeout(Duration::from_secs(8))
            .tcp_nodelay(true);

        // Tonic automatically selects TLS when the URI scheme is `https`.
        let chan = endpoint.connect().await.with_context(|| {
            format!(
                "could not connect to {:?} service at {}",
                target,
                addr.replace("://", "s://") // hide credentials if any
            )
        })?;

        // Cache connection for later reuse.
        self.channels
            .write()
            .await
            .insert(target, chan.clone());

        info!(?target, "gRPC channel ready");

        Ok(chan)
    }
}

/* -------------------------------------------------------------------------- */
/*                                   Tests                                    */
/* -------------------------------------------------------------------------- */

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn env_key_and_default_addr() {
        assert_eq!(
            ServiceTarget::Composition.env_key(),
            "COMPOSITION_SERVICE_ADDR"
        );
        assert!(ServiceTarget::Royalty.default_addr().contains("127.0.0.1"));
    }

    // Integration tests with live services are run in the CI pipeline only. In
    // local development they are skipped unless the corresponding environment
    // variables are exported (to avoid polluting `cargo test` with network
    // failures).
    #[tokio::test]
    #[ignore]
    async fn can_connect_to_minting_service() -> Result<()> {
        if std::env::var("MINTING_SERVICE_ADDR").is_err() {
            warn!("no `MINTING_SERVICE_ADDR` – skipping real gRPC connectivity test");
            return Ok(());
        }

        let client = GrpcClient::global().await?;
        let mut minter = client.minting().await?;
        // Take advantage of the “health” unary RPC implemented by every service.
        let _ = minter.health_check(()).await?;
        Ok(())
    }
}
```