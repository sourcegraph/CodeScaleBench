```md
<!--
FortiLedger360 – Architecture Decision Record (ADR)
File: docs/architecture/adr/001-choice-of-cpp.md
Status: Accepted
Author: Core Platform Team
Created: 2024-05-23
-->

# ADR-001: Choosing Modern C++ (C++20) for Core Services

## 1. Context  

FortiLedger360’s *Scanner*, *ConfigManager*, *BackupNode*, and *AlertBroker* services must:

* Sustain 100 K+ events/sec with single-digit millisecond p99 latency.  
* Run on heterogeneous targets (Ubuntu LTS, RHEL, Amazon Linux, Alpine, and in-house edge appliances) without a VM/JIT.  
* Guarantee end-to-end FIPS-validated crypto and deterministic memory handling (i.e., zero garbage-collection pauses).  
* Expose gRPC, mTLS, and eBPF hooks while co-existing with kernel-level tooling (SELinux, AppArmor, seccomp).  
* Integrate seamlessly with a polyglot control-plane (Python/TypeScript) and still offer a low-friction SDK for partners extending the platform.

## 2. Decision  

Adopt **C++20** (with selective C++23 back-ports where compiler support allows) as the primary implementation language for the *Domain*, *Infrastructure*, and *Platform* layers.

### Highlights  

| Requirement                         | C++20 Capability                                                                                                            |
|------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|
| Hard real-time and low latency      | Deterministic stack allocation, `std::pmr` arenas, lock-free atomics (`std::atomic_ref`, `std::atomic_flag::wait/notify`). |
| Cross-platform portability          | Battle-tested toolchains (GCC/Clang/MSVC), CMake 3.26+, and container images.                                               |
| Concurrency & mesh networking       | Coroutines (`co_await`), executors (`std::jthread`), and third-party senders/receivers (libunifex, cppcoro).               |
| Safety without GC                  | RAII + `[[nodiscard]]`, `span`, `std::optional`, `Contracts` (once standardized).                                           |
| Interop with C & assembly           | Seamless linking to OpenSSL, libbpf, envoy-proxy filters, DPDK, and kernel syscalls.                                        |
| Vendor ecosystem                    | Mature static analyzers (Clang-Tidy, CppCheck), sanitizers (ASan/UBSan/TSan), and coverage (gcov-LCOV, LLVM-profdata).      |

```cpp
// Example: asynchronous event dispatch to the mesh using C++20 coroutines
#include <grpcpp/grpcpp.h>
#include "event_bus.grpc.pb.h"

using fortiledger360::mesh::Envelope;
using fortiledger360::mesh::EventBus;

auto publishEvent(std::shared_ptr<EventBus::Stub> stub, Envelope envelope)
    -> cppcoro::task<void>
{
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds{1});

    EnvelopeAck ack;
    co_await stub->AsyncPublish(&ctx, envelope, &ack);
    if (!ack.ok()) {
        throw std::runtime_error("publishEvent: failed to ACK");
    }
}
```

## 3. Considered Alternatives  

| Option          | Pros                                                          | Cons                                                                                                                      |
|-----------------|---------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|
| Rust            | Strong safety guarantees, good async story                    | Immature ecosystem for FIPS crypto & gRPC bidirectional streaming; significant DX learning curve for domain experts.      |
| Go              | Fast compile times, first-class gRPC tooling                  | Stop-the-world GC unfavorable for 24x7 low-latency workloads; cgo complicates FIPS compliance.                             |
| Java/Kotlin     | Rich libraries, massive talent pool                           | JVM warm-up, GC latency, and native-image builds still experimental for Alpine/musl; larger resource footprint.           |
| C (ISO-C18)     | Minimal runtime, predictable                                  | Lack of type safety, RAII, generics, and modern concurrency severely slows feature delivery.                              |

## 4. Consequences  

1. **Toolchain Standardization** –  
   *CMake* is mandated for builds; Conan handles dependency pinning. Docker images provide GCC 13 and Clang 17 by default.

2. **Coding Guidelines** –  
   We enforce Google CPP + CppCoreGuidelines via clang-format and clang-tidy. Mandatory CI gates: ASan/UBSan/Tsan, Valgrind memcheck, and Coverity scans.

3. **Binary Footprint** –  
   Stateless micro-services remain sub-20 MiB by aggressive LTO/ICF, `-fvisibility=hidden`, and `musl` builds for edge nodes.

4. **Talent & On-boarding** –  
   Internal bootcamp and pair-programming for engineers unfamiliar with modern C++. Mentor rotation ensures guidelines adoption.

5. **Build Performance** –  
   Distributed caching via *Bazel Remote Cache* complements CCache. Average full rebuild stays under 90s on 32-core CI runners.

## 5. Risks & Mitigations  

| Risk                                        | Mitigation                                                                                     |
|---------------------------------------------|------------------------------------------------------------------------------------------------|
| Undefined Behavior pitfalls                 | Static analyzers, sanitizers in CI, mandatory code reviews with UB checklist.                  |
| ABI drift across compilers                  | `-fvisibility=hidden`, PImpl for public SDK, semantic versioning enforced via ABI-Compliance-Checker. |
| Slow compile times for templates            | Pre-compiled headers, module 🚧 adoption once compilers mature, limiting deep template meta-prog. |
| Up-leveling to C++23 features prematurely   | Feature flags + clang `-std=c++2b` only behind a CI job; production builds remain on `-std=c++20`. |

## 6. Technical Debt Considerations  

Moving to C++23 modules will require re-organizing header boundaries and build scripts. A spike is scheduled for Q4-2024 to evaluate migration ROI.

## 7. References  

* C++ Core Guidelines – github.com/isocpp/CppCoreGuidelines  
* gRPC C++ async API – grpc.io/docs/languages/cpp  
* FIPS 140-3 Implementation Guidance – nist.gov  
* FortiLedger360 Threat Model v2.1 – internal link

---

*This ADR is final. Revisit only if compile-time or run-time characteristics change materially, or if Rust stabilizes FIPS-certified TLS 1.3 stacks with equivalent performance.*

```