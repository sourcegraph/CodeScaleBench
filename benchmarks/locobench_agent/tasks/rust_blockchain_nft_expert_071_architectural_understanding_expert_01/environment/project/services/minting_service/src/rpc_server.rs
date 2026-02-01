```rust
//! src/rpc_server.rs
//!
//! gRPC façade for the `minting_service` micro–service. The server exposes a
//! handful of RPCs that allow external actors (CLI, Front-End, other
//! micro-services) to trigger NFT minting, query status and subscribe to
//! real-time minting events.
//!
//! Generation of the protobuf stubs happens in build-time (see
//! `build.rs`). The relevant proto lives in
//! `proto/minting/minting_service.proto` and defines the following RPCs:
//!   * `MintNft`              – Mints a new NFT instrument
//!   * `GetMintingStatus`     – Returns the status of a previously submitted job
//!   * `StreamMintingEvents`  – Server-side stream with minting pipeline events
//!
//! This file wires those RPCs to the internal domain logic (the `pipeline`
//! module) and hides transport-specific details from the rest of the system.

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::{broadcast, oneshot, RwLock};
use tokio_stream::{wrappers::BroadcastStream, StreamExt};
use tonic::{transport::Server, Request, Response, Status, Streaming};
use tracing::{debug, error, info, instrument, warn};

/// Generated protobuf stubs (see build.rs)
pub mod proto {
    pub use crate::minting_proto::*;
}

use proto::minting::{
    minting_service_server::{MintingService, MintingServiceServer},
    GetMintingStatusRequest, GetMintingStatusResponse, MintNftRequest, MintNftResponse,
    MintingEvent,
};

/// Maximum amount of events kept in the broadcast channel.…large enough for a
/// bursty workload but small enough to avoid unbounded memory growth.
const EVENT_CHANNEL_CAPACITY: usize = 1_024;

/// Defaults for graceful shutdown timeouts.
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(10);

/// Type alias for internal event bus sender.
pub type EventSender = broadcast::Sender<MintingEvent>;

/// Trait object to decouple core minting pipeline from transport.  
/// (`dyn` + `Send + Sync` so we can share it across async tasks)
pub type PipelineHandle = Arc<dyn crate::pipeline::MintingPipeline + Send + Sync>;

/// gRPC server instance.
#[derive(Clone)]
pub struct MintingRpcServer {
    pipeline: PipelineHandle,
    event_sender: EventSender,
}

impl MintingRpcServer {
    /// Construct a new `MintingRpcServer`.
    pub fn new(pipeline: PipelineHandle, event_sender: EventSender) -> Self {
        Self {
            pipeline,
            event_sender,
        }
    }

    /// Runs the gRPC server on the given address until a shutdown signal is received.
    ///
    /// # Arguments
    /// * `addr` – Socket address to bind on, usually configured from `Settings`.
    /// * `shutdown` – Trigger for graceful shutdown (e.g. ctrl-c handler or
    ///                systemd stop).
    pub async fn serve(self, addr: SocketAddr, mut shutdown: oneshot::Receiver<()>) -> anyhow::Result<()> {
        info!(?addr, "Starting Minting RPC server");

        let svc = MintingServiceServer::new(self)
            // Send compression saves bandwidth when streaming large events.
            .send_compressed(tonic::codec::CompressionEncoding::Gzip)
            .accept_compressed(tonic::codec::CompressionEncoding::Gzip);

        // Run the tonic server with a graceful shutdown trigger.
        Server::builder()
            .tcp_nodelay(true)
            .add_service(svc)
            .serve_with_shutdown(addr, async move {
                // Wait for the caller to notify for shutdown.
                let _ = shutdown.await;
                info!("Shutdown signal received for RPC server");
            })
            .await
            .map_err(|e| anyhow::anyhow!(e))
    }
}

#[tonic::async_trait]
impl MintingService for MintingRpcServer {
    /// Submits a new NFT minting job to the pipeline.
    #[instrument(skip(self, request))]
    async fn mint_nft(
        &self,
        request: Request<MintNftRequest>,
    ) -> Result<Response<MintNftResponse>, Status> {
        let req = request.into_inner();
        let caller = req
            .caller
            .clone()
            .unwrap_or_else(|| "anonymous".to_string());

        debug!(%caller, "Received MintNft request");

        // Delegates to domain pipeline; handle business errors accordingly.
        match self.pipeline.submit_job(req).await {
            Ok(job_id) => {
                // Emit an event for reactive components (e.g. metrics, UI).
                let event = MintingEvent {
                    timestamp: chrono::Utc::now().timestamp_millis(),
                    job_id: job_id.clone(),
                    stage: "QUEUED".into(),
                    detail: "Minting job accepted".into(),
                };
                let _ = self.event_sender.send(event);

                let resp = MintNftResponse { job_id };
                Ok(Response::new(resp))
            }
            Err(e) => {
                error!(error = %e, "Failed to submit minting job");
                Err(Status::internal(format!(
                    "Unable to submit minting job: {e}"
                )))
            }
        }
    }

    /// Returns the status of a submitted minting job.
    #[instrument(skip(self, request))]
    async fn get_minting_status(
        &self,
        request: Request<GetMintingStatusRequest>,
    ) -> Result<Response<GetMintingStatusResponse>, Status> {
        let req = request.into_inner();

        let status = self
            .pipeline
            .get_status(&req.job_id)
            .await
            .map_err(|e| Status::not_found(format!("Job not found: {e}")))?;

        let resp = GetMintingStatusResponse {
            job_id: req.job_id,
            status: status.to_string(),
            // A human-readable explanation provided by the pipeline.
            description: status.description().into(),
        };

        Ok(Response::new(resp))
    }

    /// Bidirectional stream is unnecessary here; a simple server-side stream
    /// suffices to push events to the caller.
    #[instrument(skip(self, request))]
    type StreamMintingEventsStream = BroadcastStream<Result<MintingEvent, Status>>;

    async fn stream_minting_events(
        &self,
        request: Request<tonic::Streaming<proto::minting::Filter>>,
    ) -> Result<Response<Self::StreamMintingEventsStream>, Status> {
        // We currently ignore the filter but we keep the stream alive to drain
        // frames so gRPC doesn't enforce flow-control starvation.
        let mut _filter_stream: Streaming<proto::minting::Filter> = request.into_inner();

        // Every subscriber gets its own receiver side of the broadcast channel.
        let rx = self.event_sender.subscribe();
        let stream = BroadcastStream::new(rx).map(|event| match event {
            Ok(ev) => Ok(ev),
            Err(broadcast::error::RecvError::Lagged(skipped)) => {
                warn!(%skipped, "Event stream lagged behind");
                Err(Status::resource_exhausted(format!(
                    "Skipped {skipped} events due to lag"
                )))
            }
            Err(e) => {
                error!(error = %e, "Event channel closed unexpectedly");
                Err(Status::internal("Event channel closed"))
            }
        });

        Ok(Response::new(Box::pin(stream) as Self::StreamMintingEventsStream))
    }
}

/// Bootstrap helper that wires together the event bus and the core pipeline.
///
/// Most callers will simply use `start_server` from `main.rs` instead of
/// calling this directly.
pub async fn build_server() -> anyhow::Result<(MintingRpcServer, broadcast::Receiver<MintingEvent>)>
{
    // Core pipeline is created elsewhere but we still own it here.
    let pipeline = crate::pipeline::create_pipeline().await?;

    let (event_sender, event_receiver) = broadcast::channel(EVENT_CHANNEL_CAPACITY);

    // Notify the pipeline so it can publish its own events.
    pipeline.set_event_sender(event_sender.clone()).await;

    let server = MintingRpcServer::new(Arc::new(pipeline), event_sender);

    Ok((server, event_receiver))
}

/// Initiates the RPC server with default settings and waits for Ctrl-C.
///
/// This helper is mainly used by integration tests and binaries created with
/// `bin/`.
pub async fn serve_forever(addr: SocketAddr) -> anyhow::Result<()> {
    let (server, _event_rx) = build_server().await?;
    let (shutdown_tx, shutdown_rx) = oneshot::channel();

    // Handle SIGINT/SIGTERM for graceful shutdown.
    tokio::spawn(async move {
        if let Err(e) = tokio::signal::ctrl_c().await {
            error!(error = %e, "Unable to listen for shutdown signal");
            return;
        }
        let _ = shutdown_tx.send(());
    });

    server.serve(addr, shutdown_rx).await?;

    // Give some time for in-flight responses to finish.
    tokio::time::timeout(SHUTDOWN_TIMEOUT, async {}).await.ok();

    Ok(())
}
```