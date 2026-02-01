# 001 – Architectural Style: Microservices

Status: **Accepted**  
Date: 2023-08-29  
ADR-Owner: Architecture Guild  

---

## 1. Context

OpsForge Utility Nexus aims to provide a *single, versioned façade* that aggregates a wide variety of utilities—file-format conversion, data anonymisation, checksum generation, time-zone-aware scheduling, etc. Each utility has a distinct lifecycle, scalability profile, and set of external dependencies.

Historically, similar platforms have been built as:

* a **monolith**, offering a single deployment artefact, or  
* a **modular monolith**, separating code at compile-time while sharing the same runtime and database schema.

Early spike implementations revealed several pain-points:

* **Resource Contention** – CPU-intensive converters starved IO-bound schedulers.  
* **Release Cadence Mismatch** – checksum algorithms evolve slowly; anonymisation libraries update weekly.  
* **Polyglot Dependencies** – some utilities require native binaries; others depend on JDBC drivers.  
* **Regulatory Isolation** – GDPR mandates data-anonymisation modules to undergo specific audits, blocking the entire delivery pipeline.

Given these concerns—and the fact that customers frequently request *only one or two* utilities—we need an architectural style that supports:

* Independent release and deployment cadences  
* Autonomous horizontal scaling  
* Technology heterogeneity per utility  
* Fine-grained security boundaries  
* Evolutionary replacement of utilities without cross-cutting regression risk  

## 2. Decision

We will architect OpsForge Utility Nexus as a **Microservice-oriented System**, in which *each utility function is implemented as its own microservice* that:

1. Exposes its capabilities via a lightweight REST and (optionally) GraphQL API.  
2. Owns its **hexagonal architecture** internals—domain, application services, inbound/outbound adapters.  
3. Communicates with other services only through well-defined, versioned contracts (HTTP/JSON and/or gRPC where streaming is required).  
4. Publishes domain events on an event bus for eventual consistency and observability.  
5. Is deployed, scaled, and monitored independently, yet discovered and composed by the **API Gateway** to present a cohesive façade to consumers.

### Illustrative Directory Layout

```text
opsforge-utility-nexus/
├── gateway/               # Spring Cloud Gateway + GraphQL Federation
├── utilities/
│   ├── checksum/
│   ├── converter/
│   ├── anonymizer/
│   └── scheduler/
└── shared-kernel/         # Value objects, error codes, cross-service contracts
```

### Minimal Service Contract Example (Checksum Utility)

```java
// inbound adapter
@RestController
@RequestMapping("/v1/checksum")
@RequiredArgsConstructor
class ChecksumController {

    private final ChecksumUseCase checksumUseCase;

    @PostMapping
    ResponseEntity<ChecksumResponse> calculate(@Valid @RequestBody ChecksumRequest request) {
        ChecksumResult result = checksumUseCase.calculate(request.toDomain());
        return ResponseEntity.ok(ChecksumResponse.from(result));
    }
}
```

## 3. Rationale

* **Decoupled Deployment** – Teams push features without synchronising global release trains.  
* **Scalability Alignment** – CPU-bound converters can autoscale independently of latency-sensitive schedulers.  
* **Failure Containment** – Circuit-breaking a malfunctioning anonymisation service leaves other utilities unaffected.  
* **Technology Freedom** – Teams may select optimal persistence (e.g., PostgreSQL vs MongoDB) or caching layers (e.g., Caffeine vs Redis) without impacting peers.  
* **Regulatory Compliance** – Security reviews and audits can scope to the service that touches sensitive data.

## 4. Consequences

Pros:

* Faster, risk-isolated releases  
* Resilience via bulkheads, retries, timeouts  
* Fine-grained autoscaling, leading to cost optimisation  
* Facilitates domain-driven design and bounded contexts  

Cons / Trade-offs:

* **Operational Overhead** – More CI pipelines, Docker images, Helm charts, dashboards, alerts.  
* **Distributed Complexity** – Requires centralised logging, tracing, service discovery, and advanced DevSecOps maturity.  
* **Data Consistency** – Cross-service transactions demand eventual consistency or Saga patterns.  
* **Cross-Cutting Concerns Duplication** – Rate-limiting, auth, and caching must be standardised via libraries or sidecars.

Mitigations:

* Provide a **Golden Path** with base images, Terraform modules, Helm templates, and shared Gradle plugins.  
* Adopt **OpenTelemetry** for unified traces, metrics, and logs.  
* Leverage **GraphQL Federation** to stitch service schemas and reduce REST round-trips.  
* Enforce **Semantic Versioning** and **Consumer-Driven Contract Tests** (Pact) to detect breaking changes early.

## 5. Alternatives Considered

| Candidate                      | Why Rejected                                                                 |
|--------------------------------|------------------------------------------------------------------------------|
| Monolith                       | Single blast radius; divergent scalability needs cause over-provisioning     |
| Modular Monolith               | Better boundaries than classic monolith, but still shares runtime & DB       |
| Functions-as-a-Service (FaaS)  | Cold-start latency unacceptable for bulk conversions; complex orchestration  |
| Self-contained Systems (SCS)   | Similar benefits but less tooling support compared to mainstream microservices |

## 6. Related Decisions

* 002 – **Hexagonal Architecture Enforcement**  
* 003 – **API Gateway & GraphQL Federation Strategy**  
* 004 – **Event Streaming Backbone (Kafka)**  
* 005 – **Observability Stack Selection**  

---

> *This ADR is irrevocable only as long as its motivation remains valid. Should empirical evidence prove otherwise, it may be superseded following established governance procedures.*