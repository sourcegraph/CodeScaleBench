```markdown
# Architecture Decision Record 003  
## Title: Standardise on gRPC over mTLS inside an Envoy-based Service Mesh

* Status: **Accepted**  
* Date: 2024-06-11  
* Supersedes / Amends: None  
* Authors: Platform & Runtime Chapter  

---

### 1. Context  
FortiLedger360 consists of ~40 micro-services distributed across five bounded-context
layers.  The initial prototype relied on *REST/JSON* for inter-service communication and
used a bespoke DNS+Consul mechanism for discovery.  As we approach General Availability
and a target throughput of 35 K cross-service calls per second, the following pain-points
have become critical:

* High per-call latency caused by HTTP/1.1 + JSON (≈ 1.7 ms serialisation cost alone).  
* No first-class streaming semantics — mandatory for continuous vulnerability scans.  
* Ad-hoc security: hand-rolled JWTs, static API keys, no mutual-TLS.  
* Operational blind-spots: we cannot uniformly enforce retries, circuit-breakers, or
  trace context propagation.  

### 2. Decision  
We will:

1. Adopt **gRPC (HTTP/2)** as the canonical RPC protocol between internal services.  
2. Mandate **mutual-TLS** using the platform’s Certificate-Authority for every gRPC call.  
3. Deploy all workloads **behind Envoy sidecars** (managed by Istio¹) to realise a
   zero-trust **Service Mesh** featuring:  
   * mTLS termination & rotation  
   * out-of-the-box retries, circuit-breaking, deadline and back-off policies  
   * distributed tracing via OpenTelemetry → Jaeger  
   * L7 metrics and rate-limiting  
4. Generate C++ stubs via `protoc --cpp_out` for low-latency services written in C++17
   (Scanner, Metrics, BackupNode).  Java/Kotlin, Go and Rust services will continue to
   use language-appropriate gRPC bindings.  

¹ Istio can be swapped with Consul Connect or Kuma if future requirements dictate.

### 3. Consequences  

* (+) 4–6× faster intra-cluster calls (binary Protobuf, header compression, multiplexed
  streams).  
* (+) Uniform security posture: every hop is authenticated & encrypted.  
* (+) Mesh provides traffic-shaping without code changes.  
* (±) Incremental learning curve: teams must master Protobuf, gRPC error-model, Envoy.  
* (–) Additional sidecar footprint (~80 MiB RAM / pod) and control-plane overhead.  

---

## 4. Reference Implementation (C++ 17)

Below is a distilled yet functional excerpt taken from the *Scanner* bounded context.  
The code compiles with **grpc 1.61+**, **OpenSSL 3** and enables *sanitizers* in `CMakeLists.txt`.

### 4.1 `scanner.proto`

```proto
syntax = "proto3";

package fortiledger360.scanner.v1;

option java_package = "com.fortiledger360.scanner.v1";
option go_package   = "fortiledger360/scanner/v1;scannerpb";

// Command Pattern — invokes an asynchronous scan.
message InitiateSecurityScanRequest {
  string tenant_id   = 1;
  string resource_id = 2; // VM, container, or k8s-namespace
  enum Depth {
    DEPTH_UNSPECIFIED = 0;
    QUICK             = 1;
    DEEP              = 2;
  }
  Depth depth = 3;
}

message InitiateSecurityScanResponse {
  string scan_id = 1;
}

// Observer/Strategy Pattern — stream incremental findings.
message ScanFinding {
  string vulnerability_id = 1;
  string severity         = 2;
  string description      = 3;
  int64  detected_at_ms   = 4;
}

service SecurityScanner {
  rpc InitiateSecurityScan (InitiateSecurityScanRequest)
        returns (InitiateSecurityScanResponse);

  // Server-side streaming for real-time dashboards.
  rpc StreamFindings (google.protobuf.StringValue) // scan_id
        returns (stream ScanFinding);
}
```

### 4.2 `security_scanner_server.cpp`

```cpp
/**
 * @file security_scanner_server.cpp
 * @brief gRPC server for the SecurityScanner bounded context.
 *
 * Build:
 *   $ cmake -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo
 *   $ cmake --build build -j
 */

#include <csignal>
#include <filesystem>
#include <fstream>
#include <grpcpp/ext/proto_server_reflection_plugin.h>
#include <grpcpp/grpcpp.h>

#include "scanner.grpc.pb.h"

using fortiledger360::scanner::v1::SecurityScanner;
using fortiledger360::scanner::v1::InitiateSecurityScanRequest;
using fortiledger360::scanner::v1::InitiateSecurityScanResponse;
using fortiledger360::scanner::v1::ScanFinding;

namespace fs = std::filesystem;

static std::atomic_bool g_terminate{false};

class SecurityScannerServiceImpl final : public SecurityScanner::Service
{
public:
    grpc::Status InitiateSecurityScan(grpc::ServerContext* context,
                                      const InitiateSecurityScanRequest* request,
                                      InitiateSecurityScanResponse* response) override
    {
        if (request->tenant_id().empty() || request->resource_id().empty())
        {
            return grpc::Status(grpc::StatusCode::INVALID_ARGUMENT,
                                "tenant_id and resource_id must be set");
        }

        // Naïve UUID — replace with a robust generator in prod.
        const std::string scan_id = "scan-" + std::to_string(++scan_counter_);
        response->set_scan_id(scan_id);

        // Off-load heavy scan to a dedicated thread-pool.
        std::thread{&SecurityScannerServiceImpl::performScan, this,
                    scan_id, *request}.detach();

        return grpc::Status::OK;
    }

    grpc::Status StreamFindings(grpc::ServerContext* context,
                                const google::protobuf::StringValue* scan_id_val,
                                grpc::ServerWriter<ScanFinding>* writer) override
    {
        const std::string scan_id = scan_id_val->value();
        absl::ReaderMutexLock lk(&findings_mu_);
        auto it = findings_.find(scan_id);
        if (it == findings_.end())
        {
            return grpc::Status(grpc::StatusCode::NOT_FOUND, "Unknown scan_id");
        }

        for (const auto& finding : it->second)
        {
            if (!writer->Write(finding))
            {
                // Client aborted.
                break;
            }
        }
        return grpc::Status::OK;
    }

private:
    void performScan(std::string scan_id, InitiateSecurityScanRequest request)
    {
        // Simulate scan workflow. In reality this would call ClamAV, Trivy, etc.
        std::this_thread::sleep_for(std::chrono::milliseconds(250));

        ScanFinding f;
        f.set_vulnerability_id("CVE-2023-1234");
        f.set_severity("HIGH");
        f.set_description("Sample buffer-overflow vuln");
        f.set_detected_at_ms(
            std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count());

        {
            absl::WriterMutexLock lk(&findings_mu_);
            findings_[scan_id].push_back(std::move(f));
        }

        // Persist to event-bus for further processing (omitted).
    }

    std::atomic_uint64_t scan_counter_{0};
    absl::Mutex findings_mu_;
    std::unordered_map<std::string, std::vector<ScanFinding>> findings_ ABSL_GUARDED_BY(findings_mu_);
};

static void handleSignal(int)
{
    g_terminate.store(true);
}

static std::string readFile(const fs::path& p)
{
    std::ifstream ifs(p, std::ios::binary);
    if (!ifs)
        throw std::runtime_error("Unable to open " + p.string());
    return {std::istreambuf_iterator<char>(ifs), {}};
}

int main(int argc, char* argv[])
{
    const fs::path kCertDir   = "/etc/fortiledger360/certs/";
    const fs::path kCertFile  = kCertDir / "server.crt";
    const fs::path kKeyFile   = kCertDir / "server.key";
    const fs::path kCaFile    = kCertDir / "ca.crt";

    grpc::SslServerCredentialsOptions::PemKeyCertPair pkcp{
        readFile(kKeyFile), readFile(kCertFile)};
    grpc::SslServerCredentialsOptions ssl_opts;
    ssl_opts.pem_key_cert_pairs.push_back(pkcp);
    ssl_opts.pem_root_certs = readFile(kCaFile);
    ssl_opts.client_certificate_request =
        GRPC_SSL_REQUEST_AND_REQUIRE_CLIENT_CERTIFICATE_AND_VERIFY;

    std::shared_ptr<grpc::ServerCredentials> creds =
        grpc::SslServerCredentials(ssl_opts);

    SecurityScannerServiceImpl service;

    grpc::EnableDefaultHealthCheckService(true);
    grpc::reflection::InitProtoReflectionServerBuilderPlugin();

    grpc::ServerBuilder builder;
    builder.AddListeningPort("0.0.0.0:50051", creds);
    builder.RegisterService(&service);
    std::unique_ptr<grpc::Server> server(builder.BuildAndStart());

    std::signal(SIGINT, handleSignal);
    std::signal(SIGTERM, handleSignal);

    std::cout << "SecurityScanner gRPC server started on :50051 (mTLS enabled)\n";
    while (!g_terminate.load())
        std::this_thread::sleep_for(std::chrono::seconds(1));

    server->Shutdown();
    server->Wait();
    std::cout << "SecurityScanner gracefully terminated.\n";
    return 0;
}
```

### 4.3 `security_scanner_client.cpp`

```cpp
/**
 * @file security_scanner_client.cpp
 * @brief Example envoy-injected client that calls the scanner via mTLS.
 */

#include <grpcpp/grpcpp.h>
#include "scanner.grpc.pb.h"

using fortiledger360::scanner::v1::SecurityScanner;
using fortiledger360::scanner::v1::InitiateSecurityScanRequest;
using fortiledger360::scanner::v1::InitiateSecurityScanResponse;

static std::shared_ptr<grpc::Channel> makeSecureChannel()
{
    grpc::SslCredentialsOptions ssl_opts;
    ssl_opts.pem_root_certs = ""; // Envoy sidecar performs TLS => plaintext loopback
    return grpc::CreateChannel("127.0.0.1:15001", grpc::InsecureChannelCredentials());
}

int main()
{
    auto channel = makeSecureChannel();
    std::unique_ptr<SecurityScanner::Stub> stub = SecurityScanner::NewStub(channel);

    InitiateSecurityScanRequest req;
    req.set_tenant_id("tenant-42");
    req.set_resource_id("k8s-namespace-prod");
    req.set_depth(InitiateSecurityScanRequest::DEPTH::InitiateSecurityScanRequest_Depth_DEEP);

    grpc::ClientContext ctx;
    InitiateSecurityScanResponse resp;
    grpc::Status status = stub->InitiateSecurityScan(&ctx, req, &resp);

    if (!status.ok())
    {
        std::cerr << "RPC failed: " << status.error_message() << '\n';
        return EXIT_FAILURE;
    }
    std::cout << "Scan ID: " << resp.scan_id() << '\n';
    return EXIT_SUCCESS;
}
```

---

### 5. Operational Topology

```mermaid
flowchart TD
    subgraph Service Mesh (Istio)
        SC[SecurityScanner] <-- gRPC/mTLS --> MN[MetricsNode]
        SC <-- gRPC/mTLS --> BN[BackupNode]
        SC <-- gRPC/mTLS --> AB[AlertBroker]
    end
    classDef svc fill:#0f5e9c,stroke:#fff,stroke-width:2px,color:#fff;
    class SC,MN,BN,AB svc;
```

Envoy sidecars transparently enforce per-method time-outs, automatic retries (`retryOn:
5xx,connect-failure,refused-stream`) and distributed traces exported to the
OpenTelemetry Collector.

---

### 6. Risk Mitigation & Future Work  

* Blue-green roll-outs validated in a staging mesh before prod promotion.  
* Pen-tests scheduled to validate certificate rotation and downgrade attack resilience.  
* Evaluate HTTP/3 + gQUIC once officially supported by gRPC-C++.  

---

### 7. Rejected Alternatives

| Alternative | Rationale for Rejection |
|-------------|-------------------------|
| Continue with REST/JSON + Custom TLS | Latency & missing streaming semantics outweighed familiarity benefits. |
| Apache Thrift | We already depend on gRPC in the Java pipeline; doubling infra was unjustified. |
| ZeroMQ | Lack of built-in authN/Z, difficult to operate at scale in Kubernetes. |

---

This ADR is **accepted** and effective immediately.  All new internal service
interfaces **must** be defined in Protobuf and exposed via gRPC; legacy endpoints
are slated for migration over the next two quarters.
```