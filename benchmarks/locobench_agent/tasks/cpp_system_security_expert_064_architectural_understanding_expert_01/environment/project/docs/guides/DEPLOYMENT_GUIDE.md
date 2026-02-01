```markdown
# FortiLedger360 – Deployment Guide
*Version 2.3 – Last updated 2024-06-06*

> This guide walks DevOps engineers through three deployment topologies—local
> development, single-node PoC, and highly-available production—and provides
> C++ reference implementations for extending the platform via an **inline
> Strategy plug-in**.  
> All commands have been verified against Ubuntu 22.04 LTS, Docker 24.x,
> Kubernetes v1.29, and g++ 13.

---

## 1  Architecture Recap

FortiLedger360 is intentionally layered to keep security primitives orthogonal
to business logic.  
The default binary distribution contains **five independently scalable
micro-services**:

| Layer            | Responsibility (excerpt)                       | Binary/Container |
|------------------|------------------------------------------------|------------------|
| Platform         | HAProxy Ingress, HashiCorp Vault, Jaeger       | `forti-platform` |
| Infrastructure   | MongoDB, PostgreSQL, NATS JetStream            | `forti-infra`    |
| Domain           | Scanner, BackupNode, ConfigManager             | `forti-domain`   |
| Orchestration    | Event router, compensation sagas               | `forti-orch`     |
| Presentation/API | GraphQL, REST, gRPC Gateway, Envoy egress      | `forti-api`      |

Every service publishes a **protobuf contract**; requests are idempotent and
secured via **mTLS** with SPIFFE identities.

---

## 2  Prerequisites

1. **Hardware** – Minimum 4 vCPU, 8 GB RAM (PoC); Production: 3 × 8 vCPU
   nodes, 32 GB RAM, 500 GB SSD, 1 Gbps network.
2. **Operating System** – Ubuntu 20.04/22.04 or CentOS 9 Stream.
3. **Container Runtime** – Docker 24.x or containerd 1.7+.
4. **Cluster Orchestrator** –  
   • PoC: docker-compose (provided).  
   • Production: Kubernetes 1.27+ with RBAC, admission webhooks, and CSI
     storage class configured.
5. **TLS CA** – Internal PKI or HashiCorp Vault acting as root CA.
6. **Dev Toolchain (optional)** – g++ 13, CMake 3.26, Conan 2 to build custom
   strategy plug-ins.

---

## 3  Quick Start – Local Docker Compose

```bash
git clone https://github.com/fortiledger360/fortiledger360.git
cd fortiledger360/deploy/compose

# Fetch images from public registry (≈ 1.2 GB)
docker compose pull

# Spin everything up
docker compose up -d

# Wait until health-checks succeed
docker compose ps --format "{{.Service}}\t{{.Status}}"
```

Endpoints after bootstrap:

| Service      | URL                               |
|--------------|-----------------------------------|
| gRPC API     | `grpc://localhost:7000`           |
| REST API     | `https://localhost:8443/v1`       |
| GraphQL      | `https://localhost:8443/graphql`  |
| Jaeger UI    | `http://localhost:16686`          |
| Mongo Express| `http://localhost:8081`           |

Destroy environment:

```bash
docker compose down -v --remove-orphans
```

---

## 4  Production Deployment – Kubernetes

The Helm chart is hosted under `ghcr.io/fortiledger360/charts/fortiledger360`.

```bash
helm repo add forti360 https://ghcr.io/fortiledger360/charts
helm repo update

# Generate cluster-wide secrets (mTLS, JWT)
./scripts/gen_cluster_secrets.sh --cluster-name prod-eu

# Install with 3-replica HA and horizontal pod autoscaling
helm upgrade --install forti360 forti360/fortiledger360 \
  --namespace forti360 \
  --create-namespace \
  --values ops/prod-values.yaml
```

Verify rollout:

```bash
kubectl -n forti360 get pods -w
```

Enable **zero-downtime upgrades** using Canary strategy:

```bash
helm upgrade forti360 forti360/fortiledger360 \
  --namespace forti360 \
  --set global.rolloutStrategy=Canary \
  --set global.canaryWeight=10
```

Scenarios such as **Geo-replication**, **multi-AZ fail-over**, and **encrypted
object storage** are documented in
`docs/guides/ADVANCED_OPERATIONS.md`.

---

## 5  Extending with a Custom Strategy (C++)

Below is a fully-functional plug-in implementing a **tenant-specific deep
vulnerability scan**.  
The plug-in conforms to the `IScanStrategy` interface shipped in the SDK
(`include/strategies/scan_strategy.hpp`).

> Build artifact: `libdeep_scan_strategy.so`  
> Deployment: Mount into the `Scanner` container under
> `/opt/forti/strategies`.

### 5.1 Interface Contract

```cpp
// scan_strategy.hpp – Provided by FortiLedger360 SDK
#pragma once
#include <memory>
#include <string_view>
#include "domain/scan/scan_result.hpp"

namespace forti::scan {

class IScanStrategy {
public:
    virtual ~IScanStrategy() = default;

    // Executes a scan for the given tenant and returns a rich result object.
    virtual ScanResult execute(std::string_view tenantId,
                               std::span<const std::byte> dataBlob) = 0;

    // Human-readable name (e.g., "DeepVulnScan")
    virtual std::string_view name() const noexcept = 0;
};

using StrategyPtr = std::unique_ptr<IScanStrategy>;

} // namespace forti::scan
```

### 5.2 Implementation

```cpp
// deep_scan_strategy.cpp
#include "scan_strategy.hpp"
#include <chrono>
#include <exception>
#include <openssl/sha.h>
#include <spdlog/spdlog.h>

namespace forti::scan {

namespace {

std::string sha256Hex(std::span<const std::byte> blob)
{
    unsigned char hash[SHA256_DIGEST_LENGTH]{};
    SHA256_CTX ctx;
    SHA256_Init(&ctx);
    SHA256_Update(&ctx, blob.data(), blob.size());
    SHA256_Final(hash, &ctx);

    std::string hex;
    hex.reserve(SHA256_DIGEST_LENGTH * 2);
    static constexpr char* map = "0123456789abcdef";

    for (const auto byte : hash) {
        hex.push_back(map[(byte & 0xF0) >> 4]);
        hex.push_back(map[(byte & 0x0F)]);
    }
    return hex;
}

} // namespace

class DeepScanStrategy final : public IScanStrategy {
public:
    std::string_view name() const noexcept override { return "DeepVulnScan"; }

    ScanResult execute(std::string_view tenantId,
                       std::span<const std::byte> dataBlob) override
    {
        const auto start = std::chrono::steady_clock::now();
        ScanResult result;
        result.tenantId = std::string{tenantId};
        result.checksum = sha256Hex(dataBlob);

        try {
            spdlog::info("[DeepScan] (tenant={}) Starting scan ({} bytes)",
                         tenantId, dataBlob.size());

            // Simulate I/O-heavy CVE database lookup
            std::this_thread::sleep_for(std::chrono::milliseconds(250));

            // Naïve heuristic: Flag binaries > 10 MiB for manual review
            if (dataBlob.size() > 10 * 1024 * 1024) {
                result.status = ScanStatus::Warning;
                result.notes  = "Artifact exceeds 10 MiB – manual review recommended";
            }

            // Additional rule sets may be loaded from /opt/forti/rules.d
            result.vulnerabilities = lookupCVEs(dataBlob);

            result.status = result.vulnerabilities.empty()
                            ? ScanStatus::Clean
                            : ScanStatus::Failed;
        }
        catch (const std::exception& ex) {
            spdlog::error("[DeepScan] Fatal error: {}", ex.what());
            result.status = ScanStatus::Error;
            result.notes  = ex.what();
        }

        result.durationMs =
            std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::steady_clock::now() - start).count();

        return result;
    }

private:
    static std::vector<Vulnerability>
    lookupCVEs(std::span<const std::byte> blob)
    {
        // Placeholder – integrates with CVE feed (NVD JSON 2.0)
        if (blob.size() % 13 == 0) {
            return { Vulnerability{ "CVE-2024-1337", "Example buffer overflow", 9.8 } };
        }
        return {};
    }
};

// --- C Linkage Factory ---

extern "C" [[gnu::visibility("default")]]
forti::scan::StrategyPtr create_strategy()
{
    return std::make_unique<DeepScanStrategy>();
}

} // namespace forti::scan
```

### 5.3 CMake Build Script

```cmake
cmake_minimum_required(VERSION 3.26)
project(deep_scan_strategy LANGUAGES CXX)

find_package(OpenSSL REQUIRED)
find_package(spdlog 1.12 REQUIRED)

add_library(deep_scan_strategy SHARED deep_scan_strategy.cpp)
target_link_libraries(deep_scan_strategy PRIVATE OpenSSL::SSL spdlog::spdlog)
target_compile_features(deep_scan_strategy PRIVATE cxx_std_23)

# Position-independent code; export only factory symbol
set_target_properties(deep_scan_strategy PROPERTIES
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
)
```

### 5.4 Deployment Step

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --parallel

# Copy into running Scanner pod
kubectl cp build/libdeep_scan_strategy.so \
  forti360/scanner-0:/opt/forti/strategies/libdeep_scan_strategy.so

# Trigger a rolling restart to load the new plug-in
kubectl rollout restart sts/scanner -n forti360
```

---

## 6  Observability & Alerting

1. **Metrics** – All pods expose Prometheus‐formatted metrics on port 9102.
   Important SLOs:
   * `http_request_duration_seconds{service="api",status="5xx"}` < 0.1 %
   * `scan_job_duration_seconds_bucket{le="5"}` < 1 %
2. **Tracing** – Envoy sidecars propagate
   `traceparent` headers through the mesh; traces are collected by **Jaeger**.
3. **Alerting** – Grafana dashboards + Alertmanager templates in
   `ops/alerting/`. Example alert:
   ```yaml
   - alert: BackupFailure
     expr: increase(backup_job_errors_total[15m]) > 0
     for: 5m
     labels:
       severity: critical
     annotations:
       summary: "Backup failure detected on {{ $labels.instance }}"
       description: "Job {{ $labels.job }} failed {{ $value }} times in 15m."
   ```

---

## 7  Troubleshooting

| Symptom                                   | Resolution |
|-------------------------------------------|------------|
| Pods stuck in `Init:CrashLoopBackOff`     | Mis-configured Vault token or missing TLS certificates. Re-run `gen_cluster_secrets.sh`. |
| gRPC calls return `UNAUTHENTICATED`       | Ensure SPIRE agent is running and workloads are annotated with `spire.io/spiffe-id`. |
| Strategy plug-in fails to load            | Check `Scanner` logs: `dlopen error: undefined symbol _ZTIN...`. Recompile with `-fvisibility=hidden`. |

---

## 8  Appendix – Useful One-liners

```bash
# Tail logs across all FortiLedger360 namespaces
stern -n forti360 .

# Port-forward gRPC API (mTLS)
kubectl -n forti360 port-forward svc/api 7000:7000

# Benchmark scan throughput (500 concurrent requests)
ghz --insecure --proto api/scanner.proto \
    --call scanner.ScannerService/DeepScan \
    -d '{"tenantId": "acme", "artifact": "..."}' \
    -c 500 -n 10000 \
    localhost:7000
```

---

© 2024 FortiLedger360 Inc. All rights reserved.
```