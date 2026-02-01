# VisuTility Orchestrator `ml_computer_vision`

A production-grade, Rust-centric platform that turns raw camera streams into continuously improving, versioned computer-vision services—deployable from edge devices to cloud clusters.

![VisuTility Orchestrator Banner](docs/assets/banner.png)

---

## Key Capabilities

| Layer | Highlights |
|-------|------------|
| **Ingress**      | Multi-protocol stream capture (RTSP, WebRTC, ONVIF) with automatic fail-over and back-pressure handling |
| **Data Ops**     | Lossless video chunking, delta-encoding, GDPR-aware redaction, time-series alignment |
| **Feature Ops**  | Factory-generated feature pipelines (RGB, depth, thermal) with pluggable encoders |
| **Model Ops**    | Strategy-based hyper-parameter tuner, internal model registry, experiment tracking |
| **Serving Ops**  | gRPC + REST endpoints, multi-tenant model routers, traffic-shadowing canary support |
| **Utility Ops**  | Structured logging (OpenTelemetry), distributed tracing, policy-driven secret management |

---

## Quick Start

Prerequisites  
```bash
rustup toolchain install stable             # 1.70+ recommended
cargo install cargo-make cargo-edit
sudo apt install ffmpeg pkg-config libssl-dev
```

Build & run locally  
```bash
git clone https://github.com/<org>/visutility-orchestrator.git
cd visutility-orchestrator
cargo make start-dev
```

Live demo (pulls a sample RGB stream)  
```bash
curl --silent --location \
  "http://localhost:8080/api/v1/infer?stream=rtsp://my.cam/primary" \
  | jq
```

---

## Core Concepts

### 1. Pipeline Pattern

```rust
pub trait Pipeline<Input, Output> {
    fn ingest(&self, input: Input)            -> Result<IngestHandle>;
    fn transform(&self, handle: IngestHandle) -> Result<TransformHandle>;
    fn detect(&self, handle: TransformHandle) -> Result<DetectionHandle>;
    fn serve(&self, handle: DetectionHandle)  -> Result<Output>;
}
```
The orchestrator wires a concrete `VisionPipeline` at runtime based on the **Factory Pattern**, selecting the correct `Preprocessor`, `FeatureExtractor`, and `Model` implementations by inspecting the incoming stream’s modality.

### 2. Factory Pattern

```rust
let extractor = FeatureFactory::new()
    .with_modality(Modality::Rgb)
    .with_strategy(Encoding::Hog)
    .instantiate()?;
```
Factories enable hot-swapping algorithms without recompiling the binary.

### 3. Strategy & Observer Patterns

Strategies fine-tune hyper-parameters on the fly, while observers watch for data-drift and trigger automated retraining:

```rust
let mut tuner = HyperParamTuner::default()
    .with_strategy(Box::new(BayesianOpt::new()));

tuner.register_observer(Box::new(RetrainingTrigger::new(
    drift_threshold = 0.12
)));
```

### 4. Internal Model Registry

All artifacts are versioned and immutable. The registry records:
- semantic version (`semver`)
- data lineage hash (Git-style SHA-256)
- training metadata (GPU count, epoch, dataset snapshot)
- signed compliance manifest (Open Policy Agent)

---

## Folder Structure

```
.
├── Cargo.toml
├── README.md
├── crates
│   ├── ingress            # RTSP/WebRTC adapters
│   ├── data_ops           # Video IO & storage connectors
│   ├── feature_ops        # Feature engineering
│   ├── model_ops          # Training, registry
│   ├── serving_ops        # HTTP/gRPC gateways
│   └── utility_ops        # Logging, metrics, tracing
└── examples
    └── rgb_object_detect.rs
```

---

## Usage Examples

1. **Embed as a Library**

```rust
use visutility_orchestrator::prelude::*;

fn main() -> Result<()> {
    let ctx = AppContext::default();
    let pipeline = VisionPipeline::for_modality(Modality::Rgb, &ctx)?;

    pipeline
        .ingest("rtsp://10.0.0.12/stream")?
        .transform()?
        .detect()?
        .serve()?;

    Ok(())
}
```

2. **gRPC Service Call (Python)**  
```python
import visutility_pb2, visutility_pb2_grpc, grpc

chan  = grpc.insecure_channel("orch.example.com:443")
stub  = visutility_pb2_grpc.OrchestratorStub(chan)
reply = stub.Detect(visutility_pb2.DetectRequest(stream_id="cam-42"))
print(reply.json())
```

3. **Automated Retraining Job**

```bash
cargo run -p model_ops --bin retrain \
  -- --model rgb_det_v1.2.0 --epochs 20 --notify-slack
```

---

## Configuration

All runtime knobs are surfaced as environment variables with `serde` + `figment` support.

```bash
export VTO__INGRESS__MAX_FPS=30
export VTO__MODEL_OPS__GPU_POOL=4
export VTO__SERVING__HTTP_PORT=8080
```

---

## Production Deployment

Kubernetes Helm chart:  
```bash
helm repo add visutility https://charts.visutility.ai
helm install vto visutility/orchestrator \
  --set ingress.rtsp.enabled=true \
  --set modelOps.gpuPool=8
```

Edge device (NVIDIA Jetson):  
```bash
docker run --gpus all -p 8080:8080 \
  ghcr.io/<org>/visutility-orchestrator:latest \
  --config /etc/vto/edge.toml
```

---

## Observability Stack

| Component | Port | UI |
|-----------|------|----|
| Prometheus | 9090 | `/metrics` |
| Grafana    | 3000 | `/dashboard/db/vto` |
| Jaeger     | 16686| `/traces` |

---

## Security & Compliance

- mTLS (Rustls) across all internal services  
- AES-256-GCM encrypted artifact store  
- Supply-chain signed by [Sigstore](https://sigstore.dev)  
- GDPR & CCPA redaction presets included

---

## Contributing

1. Fork the repo and create a feature branch
2. Run `cargo make ci` (clippy + fmt + tests + coverage)
3. Submit a PR with a descriptive title

We use Conventional Commits and enforce `cargo deny` for dependency audits.

---

## License

Licensed under **Apache 2.0**. See [`LICENSE`](LICENSE) for details.

---

© 2023-2024 VisuTility Contributors. All rights reserved.