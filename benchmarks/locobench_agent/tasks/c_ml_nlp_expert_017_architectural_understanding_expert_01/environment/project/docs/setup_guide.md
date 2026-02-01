# LexiLearn MVC Orchestrator  
*Setup & Deployment Guide*  
*Last updated: 2024-06-02*

---

## Table of Contents
1. Introduction  
2. Supported Platforms  
3. Quick Start (TL;DR)  
4. Detailed Installation  
   1. Prerequisites  
   2. Building from Source (CMake)  
   3. Docker Workflow  
5. Configuration  
6. Running the Pipelines  
7. Continuous Integration / Continuous Deployment  
8. Troubleshooting  
9. FAQ  

---

## 1. Introduction
LexiLearn MVC Orchestrator (`ml_nlp`) is a high-performance, C-based MLOps/NLP engine that powers adaptive language-learning applications in production.  
This document walks you through:

* Compiling the Orchestrator **from source** or **via Docker**  
* Installing all mandatory and optional dependencies  
* Configuring model registries, feature-stores, and data ingress endpoints  
* Executing end-to-end pipelines (training, evaluation, monitoring, auto-retraining)  

---

## 2. Supported Platforms
| OS           | Compiler            | Notes                                         |
|--------------|---------------------|-----------------------------------------------|
| Ubuntu 20.04 | GCC ≥ 11, Clang ≥ 13| Officially QA’d, used in CI/CD                |
| Ubuntu 22.04 | GCC ≥ 12            | Preferred                                     |
| macOS 13+    | AppleClang ≥ 14     | Minor perf penalty (vec-ops)                  |
| RHEL 8/9     | GCC ≥ 11            | Requires `libstdc++-static` for static build  |
| Windows 11   | MSVC ≥ 19.36, LLVM  | Experimental; limited CUDA support            |

---

## 3. Quick Start (TL;DR)

```bash
# 1. Clone
git clone --recurse-submodules https://github.com/lexilearn/ml_nlp.git
cd ml_nlp

# 2. Build & test (Release profile)
./scripts/bootstrap.sh         # installs system deps
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
ctest --test-dir build         # run unit & integration suites

# 3. Launch orchestrator (local mode)
./build/bin/lexilearnd --config ./configs/local.yaml
```

Prefer Docker? One-liner:

```bash
docker compose -f deploy/docker-compose.yaml up -d
```

---

## 4. Detailed Installation

### 4.1 Prerequisites

| Dependency            | Minimum Version | Install Hint                                  |
|-----------------------|-----------------|-----------------------------------------------|
| CMake                 | 3.25            | `sudo apt install cmake`                      |
| GNU Make / Ninja      | any             | Ninja is default in CI                        |
| OpenBLAS / MKL        | 0.3.20          | `sudo apt install libopenblas-dev`            |
| OpenSSL (TLS)         | 1.1+            | For secure LMS API ingestion                  |
| libcurl               | 7.88            | LMS REST/GraphQL                              |
| protobuf-c            | 1.4             | On-disk model registry (binary manifest)      |
| PostgreSQL            | 14              | Feature store + experiment metadata           |
| Redis                 | 6               | Low-latency cache for feature vectors         |
| CUDA (optional)       | 11.8            | Transformer acceleration                      |
| Python 3.10           | —               | CLI helpers, evaluation notebooks             |

Ensure `$PATH`, `$LD_LIBRARY_PATH`, and `$PKG_CONFIG_PATH` contain the above.

### 4.2 Building from Source (CMake)

```bash
# recommended out-of-tree build
mkdir -p build && cd build

cmake .. \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DENABLE_CUDA=ON \
  -DENABLE_PY_BINDINGS=ON \
  -DENABLE_SANITIZERS=OFF \
  -DPOSTGRES_HOST=localhost

cmake --build . --target all -j$(nproc)
```

#### Common CMake Flags
* `-DENABLE_MKL=ON` — prefer Intel MKL over OpenBLAS  
* `-DENABLE_TEST_COVERAGE=ON` — generates gcov/lcov reports  
* `-DENABLE_STATIC_LINKING=ON` — produce a single self-contained binary  

Run tests:

```bash
ctest --output-on-failure --parallel 4
```

### 4.3 Docker Workflow
Provided Dockerfiles reproduce the CI environment exactly.

```bash
# Build the orchestration image
docker build . -f deploy/Dockerfile -t ghcr.io/lexilearn/ml_nlp:latest

# Start all services: orchestrator, postgres, redis, mlflow
docker compose -f deploy/docker-compose.yaml up -d
```

To attach an interactive shell:

```bash
docker exec -it lexilearn_orchestrator bash
```

---

## 5. Configuration

All runtime settings live in YAML files (validated against JSON-Schema at startup).

Example: `configs/prod.yaml`

```yaml
logging:
  level: info
  file: "/var/log/lexilearn/orchestrator.log"

lms_ingest:
  providers:
    - type: canvas
      api_url: https://lms.example.edu/api
      token_env: CANVAS_API_TOKEN
    - type: moodle
      api_url: https://moodle.example.edu/webservice/rest
      token_env: MOODLE_API_TOKEN
  polling_interval: 10m
  max_parallel: 8

model_registry:
  backend: "mlflow"
  tracking_uri: "http://mlflow:5000"
  default_stage: "Staging"

retraining:
  drift_threshold: 0.07
  cron: "0 3 * * *"   # every night at 3 AM
```

Generate a fresh skeleton:

```bash
./build/bin/lexilearnd --generate-config > configs/local.yaml
```

---

## 6. Running the Pipelines

```bash
# Launch the controller (pipeline orchestrator)
./build/bin/lexilearnd --config configs/prod.yaml
```

Key CLI flags:

| Flag                   | Description                                  |
|------------------------|----------------------------------------------|
| `--dry-run`            | parse config & exit (no network calls)       |
| `--once`               | run a single training/eval cycle, then exit  |
| `--workers=N`          | override concurrency (default: #CPU cores)   |
| `--profile=CPU`        | enable perf tracing (pprof format)           |

Real-time dashboard is available at `http://localhost:7000`.

---

## 7. CI / CD

* GitHub Actions (`.github/workflows/ci.yml`)  
  * style + static analysis (`clang-format`, `clang-tidy`)  
  * Build matrix (GCC, Clang; Ubuntu, macOS)  
  * Unit & integration tests  
  * Coverage upload to Codecov  

* Release pipeline (`.github/workflows/release.yml`)  
  * Semantic versioning via tags  
  * Artifact signing (`cosign`)  
  * Docker image push to GHCR  
  * Docs auto-deploy to GitHub Pages  

---

## 8. Troubleshooting

| Symptom                              | Possible Cause & Fix                                   |
|--------------------------------------|--------------------------------------------------------|
| `undefined reference to 'cblas_dgemm'` | OpenBLAS not found → `export LD_LIBRARY_PATH`          |
| Segfault on startup                  | Missing config field → run with `--dry-run` for schema |
| High GPU memory usage                | `ENABLE_CUDA=ON` but batch_size too large              |
| LMS 429 errors                       | Hit rate limit → increase `polling_interval`           |

Enable verbose logging:

```bash
./build/bin/lexilearnd --config configs/local.yaml --log-level=debug
```

---

## 9. FAQ

**Q: Can I use an external model registry (SageMaker, Vertex AI)?**  
A: Yes, implement the `ModelRegistryStrategy` interface (see `src/model/registry/strategy_*`) and rebuild.

**Q: How do I add a new NLP algorithm?**  
A: Drop your strategy in `src/model/strategies/`. Register it with the `StrategyFactory`, then reference it in the YAML under `model.strategy: your_strategy_name`.

**Q: Does LexiLearn support on-device inference (iPad carts)?**  
A: Road-mapped for Q4 2024 using ONNX + Core ML.

---

## Appendix A – One-Line Installer (Ubuntu)

```bash
curl -sSL https://raw.githubusercontent.com/lexilearn/ml_nlp/main/scripts/install_ubuntu.sh | sudo bash
```

---

Happy teaching & learning!  
*— LexiLearn Engineering*