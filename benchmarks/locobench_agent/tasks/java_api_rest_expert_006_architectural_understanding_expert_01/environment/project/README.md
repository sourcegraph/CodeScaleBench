```markdown
# OpsForge Utility Nexus – API REST Edition

> A **production-grade, API-first platform** that aggregates and orchestrates enterprise utility
> functions—file format conversions, data anonymization, time-zone aware scheduling, checksum
> generation, bulk text transformations—behind a single, versioned **REST & GraphQL façade**.

---

## ✨ Why OpsForge Utility Nexus?

* **One Gateway, Many Utilities** – expose a consistent, discoverable contract for dozens of micro-utilities.
* **Strict Hexagonal Architecture** – business logic is **100 % framework-agnostic**, allowing hassle-free technology swaps.
* **First-Class DX** – OpenAPI 3 & GraphQL SDL, self-documenting endpoints, typed client stubs.
* **Batteries Included** – rate limiting, response caching, pagination, observability, and multi-tenant error handling.
* **Cloud-Native** – container-ready (Docker/OCI), stateless, 12-Factor compliant, and trivially deployable to Kubernetes.

---

## 🏗️ Reference Architecture

```
              ┌─────────────────────────────┐
              │      API  Gateway           │
              │ (Spring Web MVC + RSocket)  │
              └────────────┬────────────────┘
                           │ HTTP / WebSocket / RSocket
        ┌──────────────────┴──────────────────┐
        │          Incoming Ports             │
        │  REST Controller | GraphQL Resolver │
        └──────────────────┬──────────────────┘
                           │ Application Service
                ┌──────────┴──────────┐
                │ Use-Case Orchestration │
                └──────────┬──────────┘
                           │ Pure Domain Model
                ┌──────────┴──────────┐
                │    Utility Core     │
                └──────────┬──────────┘
           ┌───────────────┴────────────────┐
           │          Outgoing Ports        │
           │ Repository | SaaS Connector    │
           └───────────────┬────────────────┘
                           │
                 Pluggable Adapters
       (PostgreSQL, MongoDB, Redis, AWS S3, …)
```

*No domain object knows Spring, Jackson, or JPA.*

---

## 🚀 Quick Start

### 1. Clone & Build

```bash
git clone https://github.com/opsforge/utility-nexus.git
cd utility-nexus
./mvnw clean verify
```

### 2. Run Locally

```bash
./mvnw spring-boot:run
# or
docker compose up -d
```

The service starts on **`http://localhost:8080`** and publishes:

* **OpenAPI UI:** `http://localhost:8080/swagger-ui.html`
* **GraphQL Playground:** `http://localhost:8080/graphiql`

---

## 💡 Usage Examples

### REST – Checksum Generation

`POST /v1/checksum`

```http
POST /v1/checksum HTTP/1.1
Content-Type: application/json

{
  "algorithm": "SHA-256",
  "payload"  : "Q29kaW5nIGxpZmUgaXMgYmV0dGVyIQ=="   // Base-64
}
```

Response:

```json
{
  "checksum": "43c5964b37876f25b7c3c5e04e..."
}
```

### GraphQL – Bulk Anonymization

```graphql
mutation {
  anonymize(request: {
      strategy: MASK_MIDDLE,
      texts: [
        "john.doe@example.com",
        "alice.wonderland@foo.bar"
      ]
  }) {
    redactedTexts
    strategy
  }
}
```

---

## 🧬 Maven Coordinates

Add the following dependency to consume the utility-client:

```xml
<dependency>
  <groupId>io.opsforge</groupId>
  <artifactId>utility-nexus-client</artifactId>
  <version>${opsforge.version}</version>
</dependency>
```

---

## 📂 Project Layout (Important Nodes Only)

```
opsforge-utility-nexus
├─ docs/             → ADRs + architecture decision logs
├─ nexus-api-rest/
│  ├─ src/
│  │  ├─ main/java/
│  │  │  ├─ io.opsforge.nexus.adapter.in.rest/
│  │  │  ├─ io.opsforge.nexus.adapter.out.postgres/
│  │  │  ├─ io.opsforge.nexus.application/
│  │  │  └─ io.opsforge.nexus.domain/
│  │  └─ main/resources/
│  └─ pom.xml
├─ docker/
│  ├─ Dockerfile      → multi-stage, GraalVM native optional
│  └─ docker-compose.yaml
└─ README.md          → you are here ✅
```

---

## 🔒 Security Model

* **OAuth 2.1 ACLs** – enforced by **Spring Authorization Server**.
* **CSRF & CORS** – opt-in per utility.
* **Multi-Tenant** – tenant id passed via JWT claim and HTTP header (`X-Tenant-Id`).

---

## 📈 Observability

* **Micrometer** with **Prometheus** + **Grafana** dashboards
* **Zipkin** tracing with B3 propagation
* **Structured Logging** (JSON) via Logback

---

## 🛡️ Robust Error Handling

A single `ApiProblem` envelope (RFC 7807) is propagated through:

```json
{
  "type"   : "https://api.opsforge.io/errors/checksum/invalid-algorithm",
  "title"  : "Unsupported checksum algorithm",
  "status" : 400,
  "detail" : "Algorithm MD5 is disabled due to security compliance.",
  "instance": "/v1/checksum"
}
```

---

## ⚙️ Building for Production

```bash
./mvnw -Pnative -DskipTests package      # GraalVM native image
docker build -t ghcr.io/opsforge/nexus:1.3.0 .
```

*Built images are **< 80 MB** and start in **< 150 ms**.*

---

## 👩‍💻 Contributing

1. Fork & clone the repo
2. Create a branch: `feat/my-awesome-utility`
3. Follow the [Contribution Guidelines](./docs/CONTRIBUTING.md)
4. Submit a PR with green CI

All code is formatted using **Google Java Format**; run `mvn spotless:apply` before committing.

---

## 📝 License

```
Apache License 2.0
Copyright (c) 2024 OpsForge
```

<br/>
<p align="center"><i>Happy util-hacking! ⚒️</i></p>
```