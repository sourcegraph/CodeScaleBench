```markdown
# SprintCart Pro – Hyper-Productive E-Commerce Workbench

![SprintCart Pro banner](docs/assets/banner.png)

SprintCart Pro is an enterprise-grade e-commerce platform designed for merchants who treat selling as a **high-performance workflow** rather than a mere storefront. Each user touch-point—from catalog curation to fulfillment—is modeled as an *optimizable work cycle*, complete with real-time analytics and KPI-driven nudges that shorten decision loops and increase **revenue per minute**.

* **Productivity-First UI** – bulk product editor, keyboard-centric navigation, and lightning-fast search  
* **Hexagonal Architecture** – strict separation between business logic, inbound, and outbound adapters  
* **Automation Studio** – chain actions visually without writing code (e.g. “when stock &lt; 3 → reorder & pause ads”)  
* **Omnichannel Ready** – expose the same domain via REST, GraphQL, WebSockets, and soon voice assistants  
* **Cloud Native** – container-first, horizontal scaling, GitOps-friendly  

---

## 1  Tech Stack

| Tier                 | Technology                                 |
|----------------------|---------------------------------------------|
| Language             | Java 21 / Kotlin (for DSL extensions)       |
| Runtime              | Spring Boot 3.x (virtual threads enabled)   |
| Build                | Maven + Modular JDK                         |
| Database             | PostgreSQL 15 (read replicas supported)     |
| Async / Messaging    | Apache Kafka, Spring Cloud Stream           |
| Front-End            | Vue 3, TypeScript, Vite + Tailwind CSS      |
| Observability        | OpenTelemetry, Loki, Grafana, Prometheus    |
| CI/CD                | GitHub Actions + Argo CD                    |

---

## 2  Architecture at 30 000 ft

```
┌──────────────────────────────────┐
│        Inbound Adapters          │
│  REST • GraphQL • Web • CLI      │
└┬─────────────────────────────────┘
 │  Ports (Interfaces)             <- Clean boundary
┌▼─────────────────────────────────┐
│            Domain                │
│  Order, Catalogue, WorkQueue     │
│  Services, Policies, Events      │
└┬─────────────────────────────────┘
 │  Ports                          <- Clean boundary
┌▼─────────────────────────────────┐
│        Outbound Adapters         │
│  Stripe, FedEx, ERP, Email, DB   │
└───────────────────────────────────┘
```

*The domain is pure Java with zero framework dependencies.*

---

## 3  Repository Layout

```
├── .github/            ← CI/CD pipelines
├── docs/               ← ADRs, diagrams, API contracts
├── infrastructure/     ← Terraform, Helm charts
├── sprintcart-pro-api/ ← REST & GraphQL controllers (inbound)
├── sprintcart-pro-core/
│   ├── catalog/        ← Domain: products, categories
│   ├── ordering/       ← Domain: orders, payments
│   └── productity/     ← Domain: work queues, metrics
└── sprintcart-pro-adapters/
    ├── stripe/         ← Outbound: payment gateway
    ├── postgres/       ← Outbound: persistence
    └── sendgrid/       ← Outbound: email notifications
```

---

## 4  Getting Started

### 4.1 Prerequisites

* JDK 21+
* Docker 20.10+
* `make`, `docker-compose`, `kubectl` (optional)

### 4.2 Clone & Run

```bash
git clone https://github.com/sprintcart/sprintcart-pro.git
cd sprintcart-pro
make dev-up       # spins up DB, Kafka, MailHog
make api-run      # runs Spring Boot on :8080
make ui-run       # runs Vue 3 SPA on :5173
```

Navigate to `http://localhost:5173`. The SPA will proxy API calls to `:8080`.

---

## 5  Configuration

Configuration is externalized via the standard *Spring Config* hierarchy (`application.yml`, env-vars, etc.).

| Variable                         | Description                        | Default |
|---------------------------------|------------------------------------|---------|
| `SPRINTCART_DB_URL`             | JDBC URL for PostgreSQL            | `jdbc:postgresql://localhost:5432/sprintcart` |
| `SPRINTCART_KAFKA_BOOTSTRAP`    | Kafka bootstrap servers            | `localhost:9092` |
| `SPRINTCART_PAYMENT_PROVIDER`   | Payment gateway (stripe, dummy)    | `dummy` |
| `SPRINTCART_JWT_SECRET`         | HS256 signing key for access token | _none_ (required) |

> Pro tip: `make env-example` outputs a sanitized `.env` you can start from.

---

## 6  Code Snippets

### 6.1 Domain Aggregate: `Order`

```java
package io.sprintcart.ordering.domain;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

/**
 * A purchase made by a customer.
 * Domain entity is framework-agnostic: no JPA, Lombok, or Spring annotations.
 */
public final class Order {

    public enum Status { NEW, PAYMENT_PENDING, PAID, SHIPPED, CANCELLED }

    private final UUID id;
    private final List<OrderLine> lines;
    private final Money total;
    private Status status;
    private OffsetDateTime createdAt;

    public Order(UUID id, List<OrderLine> lines, Money total) {
        this.id = id;
        this.lines = List.copyOf(lines);
        this.total = total;
        this.status = Status.NEW;
        this.createdAt = OffsetDateTime.now();
    }

    public void markPaid() {
        if (status != Status.PAYMENT_PENDING) {
            throw new IllegalStateException("Order is not awaiting payment");
        }
        status = Status.PAID;
    }

    // getters …
}
```

### 6.2 Port & Adapter: Payment

```java
/** Domain port (interface) */
public interface PaymentProvider {
    PaymentRef charge(Order order, CardDetails card) throws PaymentException;
}

/** Stripe adapter implementing the port */
@Component
@RequiredArgsConstructor
class StripePaymentProvider implements PaymentProvider {

    private final StripeClient stripeClient;

    @Override
    public PaymentRef charge(Order order, CardDetails card) {
        try {
            var response = stripeClient.charge(
                card.token(),
                order.total().inMinorUnits(),
                order.total().currency().getCurrencyCode()
            );
            return new PaymentRef(response.id());
        } catch (StripeException e) {
            throw new PaymentException("Stripe charge failed", e);
        }
    }
}
```

---

## 7  API Playground

Once the API is running, open:

```
GET http://localhost:8080/api/v1/catalog/products?limit=20
```

Example response:

```json
{
  "data": [
    {
      "sku": "SKU-4321",
      "name": "USB-C Hub Pro",
      "price": { "amount": 7999, "currency": "USD" },
      "stock": 56
    }
  ],
  "meta": { "total": 475 }
}
```

Open GraphQL Playground at `http://localhost:8080/graphiql`.

---

## 8  Tests & Quality Gates

We practice *TDD plus hexagon*. Each slice has its own test type:

| Layer | Test Type | Framework  |
|-------|-----------|------------|
| Domain | Unit     | JUnit 5, AssertJ |
| Adapters | Contract | Testcontainers, WireMock |
| Inbound | API spec | Spring MockMvc, REST-Assured |
| End-to-End | Scenario | Playwright (SPA) |

Run all tests:

```bash
make test
```

Quality gates: code coverage ≥ 90 %, mutation score ≥ 80 % (PITest).

---

## 9  CI/CD Pipeline

1. **Build & Test** – Every push runs the full Maven build and test matrix on GitHub Actions.  
2. **Docker Publish** – On `main`, an OCI image is pushed to GHCR with a SemVer tag.  
3. **Deploy** – Argo CD watches `manifests/` for a new image digest and rolls out gradually (canary).  
4. **Smoke Tests** – Post-deploy tests verify health & KPIs before finalizing rollout.  

---

## 10  Contributing

We love PRs! Please follow the
[contribution guidelines](docs/CONTRIBUTING.md) and run `make prerun`
before committing (auto-format, license headers, spotbugs).

---

## 11  License

```
Apache License 2.0
See LICENSE for full text.
```

---

<p align="center"><sub>© 2024 SprintCart Inc. All rights reserved.</sub></p>
```