```markdown
<!--
  OpsForge Utility Nexus – ADR 003
  Title: API Façade Strategy
  Status: Accepted
  Date: 2024-04-27
  Deciders: @arch-lead, @api-lead, @infra-lead
-->

# 003 – API Façade Strategy

## Status
Accepted – supersedes ADR-001 “Experimental Gateway PoC”.  
This decision is **binding** for all utility verticals (conversion, anonymization, scheduling, checksums, text-ops) starting with platform version **v1.2.0**.

---

## Context

OpsForge Utility Nexus aspires to expose a single, coherent contract while allowing each utility to remain an independent, hexagonally-structured microservice.  
A façade layer (a.k.a. “API Gateway”) must therefore:

* Expose **stable, consumer-centric endpoints** that abstract internal topology changes.  
* Support **REST _and_ GraphQL** entry points without duplicating business logic.  
* Enforce **cross-cutting concerns** (rate limiting, authN/Z, tenant routing, observability, caching).  
* Provide **versioning guarantees** that enable non-breaking evolution.  
* Remain **agnostic** of the utilities’ programming language, transport protocol or data store.

Early prototypes evaluated three approaches:

| # | Approach | Pros | Cons |
|---|----------|------|------|
| A | Pass-through API Gateway (e.g. NGINX + Lua) | Low latency; infra-centric | Lacks domain validation; brittle error handling; Lua skillset scarcity |
| B | “Thin” GraphQL BFF per client | Flexible composition; schema-driven | Code duplication across BFFs; N+1 requests; operational overhead |
| C | Unified **Java** façade running in the same tech stack as utilities | Reuse common libs; type safety; Spring/WebFlux maturity | Increases JVM footprint; may appear monolithic |

Empirical load-tests and maintainability reviews highlighted option **C** as the most sustainable: it maximises code reuse (error model, pagination, DTO mappers) and minimises operational sprawl.

---

## Decision

We will implement a **unified Java-based façade service** that:

1. Uses **Spring Boot 3.2** with **WebFlux** for non-blocking HTTP and **Netflix DGS** for GraphQL.
2. Implements **API-First** workflow via **OpenAPI 3.1** and **GraphQL SDL** living in `contracts/`.
3. Delegates all business logic to downstream utilities through **dedicated outbound ports** (Feign Client interfaces for REST, gRPC stubs, or JMS templates).
4. Applies **API versioning** through
   * URI segment (`/v{n}/…`) for REST  
   * Namespaced GraphQL schema (`schema @tag(name:"v{n}")`) for GraphQL
5. Encapsulates **cross-cutting filters** (auth, rate-limit, metrics, cache) using Spring `WebFilter` / `HandlerInterceptor` and DGS `DataFetcherInterceptor`.
6. Emits **structured problem details** (`application/problem+json`) conforming to [RFC 9457] for error handling.
7. Offers **partial responses & pagination** (RFC 7240 / Cursor-based) out of the box.

---

## Consequences

### Positive
* **Consistency** – All clients (CLI, SDKs, UI) leverage the same semantics, reducing cognitive load.
* **Evolutionary** – Internals can migrate (REST → gRPC; Caffeine → Redis) without public contract churn.
* **Observability** – Central façade surfaces unified logs, tracing, and metrics, expediting SRE workflows.
* **Security** – Single choke-point to enforce JWT scopes, multi-tenancy guards, and threat mitigations.

### Negative / Mitigations
* **Increased Blast Radius** – A defect in the façade could affect all utilities.  
  → Mitigation: Blue/Green deploys, exhaustive test pyramid, layered health-checks.
* **Throughput Bottleneck** – Additional hop may introduce latency.  
  → Mitigation: WebFlux back-pressure, response caching, and gRPC multiplexing for chatty paths.
* **Perceived Monolith** – May obscure microservice boundaries.  
  → Mitigation: Maintain clear ownership docs, contract tests, and align domain events per utility.

---

## Alternatives Considered

* **GraphQL Federation** – Rejected due to premature complexity and lack of per-utility SDL maturity.
* **Service Mesh Sidecars** (Istio, Linkerd) – Suitable for transport-level concerns but insufficient for domain validation and versioning semantics.
* **Serverless Edge Functions** – Would optimise global latency but complicate stateful retries and bulk payload handling (>10 MB).

---

## Compliance & Reference Implementation

All new endpoints **MUST**:

1. Conform to the published OpenAPI/GraphQL contract before merge.  
2. Return a `problem+json` body for 4xx/5xx categories.  
3. Include `X-Request-Id`, `X-Correlation-Id` in all egress calls.  
4. Register with the façade’s central `UtilityRegistry` during application bootstrap.

Reference code lives in `opsforge-facade/src/main/java/.../facade`.  
Sample usage:

```java
@GetMapping(path = "/v1/checksums/sha256", produces = APPLICATION_JSON_VALUE)
public Mono<ChecksumResponse> calculateSha256(@Valid ChecksumRequest req) {
    return checksumPort.calculate(req)
                       .map(mapper::toResponse)
                       .timeout(Duration.ofSeconds(5))
                       .onErrorMap(TimeoutException.class, ProblemDetails::fromTimeout);
}
```

---

## Next Steps

1. Finalise façade v1 contract freeze (2024-05-15).
2. Migrate existing CLI to new endpoints.
3. Deprecate NGINX Lua scripts by Q3.

---

### Changelog
* 2024-04-27 – Initial decision recorded.
```
