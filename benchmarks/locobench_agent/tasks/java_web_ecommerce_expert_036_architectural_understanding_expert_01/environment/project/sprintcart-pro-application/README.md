```markdown
# SprintCart Pro – Hyper-Productive E-Commerce Workbench

![Build](https://img.shields.io/github/actions/workflow/status/acme-inc/sprintcart-pro/ci.yml)
![License](https://img.shields.io/github/license/acme-inc/sprintcart-pro)
![Java](https://img.shields.io/badge/java-17%2B-blue.svg)

SprintCart Pro is an enterprise-grade e-commerce platform designed for merchants who treat selling
as a high-performance workflow rather than a mere storefront.  
Every user touchpoint—from catalog curation to fulfillment—is modeled as an optimizable work cycle,
complete with real-time analytics and KPI-driven nudges that help operators shorten decision loops
and increase revenue per minute.

The core follows a strict **Hexagonal Architecture** so that inbound/outbound channels can be swapped
without touching business logic.

---

## ⚡️ Quick Start

```bash
# 1. Clone & build
git clone https://github.com/acme-inc/sprintcart-pro
cd sprintcart-pro
./mvnw clean verify

# 2. Run the application (requires JDK 17+ and Docker)
docker compose up -d postgres redis maildev
./mvnw -pl sprintcart-pro-application spring-boot:run
```

Then open <http://localhost:8080> for the Vue 3 SPA  
API docs are available at <http://localhost:8080/swagger-ui.html>.

Login with the bootstrap admin account:

* **User:** `admin@sprintcart.local`
* **Pass:** `admin123!`

---

## 🏗 Project Modules

| Module | Description |
|--------|-------------|
| `sprintcart-pro-domain` | Pure business logic (Orders, Products, WorkQueues, …) |
| `sprintcart-pro-application` | Spring Boot wiring, REST/GraphQL controllers, security |
| `sprintcart-pro-adapters` | External integrations: payment, email/SMS, ERP |
| `sprintcart-pro-spa` | Vue 3 frontend (PNPM) |
| `sprintcart-pro-tooling` | Load testing, code-gen utilities |

---

## 🛠 Architecture Primer

1. **Domain Layer (POJOs + Domain Services)**  
   Completely framework-agnostic, validated via pure JUnit 5 tests.

2. **Application Layer (Spring Boot)**  
   Orchestrates use-cases, transactions, and security via ports.

3. **Inbound Adapters**  
   * REST controllers (`/api/**`)
   * GraphQL endpoint (`/graphql`)
   * WebSocket channels (order events)

4. **Outbound Adapters**  
   * PaymentGateway (Stripe, Adyen)  
   * NotificationService (Mailgun, Twilio)  
   * InventoryConnector (SAP, NetSuite)

![Hexagonal diagram](docs/hexagonal.png)

---

## 🧩 Code Snippets

### 1. Domain Aggregate – Order

```java
package pro.sprintcart.domain.order;

import java.time.OffsetDateTime;
import java.util.*;

public final class Order {

    private final UUID id;
    private final List<LineItem> items;
    private final Money total;
    private final OffsetDateTime createdAt;
    private Status status;

    public enum Status { PENDING, PAID, FULFILLED, CANCELED }

    public Order(UUID id, List<LineItem> items, OffsetDateTime createdAt) {
        this.id = Objects.requireNonNull(id);
        this.items = List.copyOf(items);
        this.total = items.stream()
                          .map(LineItem::subtotal)
                          .reduce(Money.ZERO, Money::add);
        this.createdAt = Objects.requireNonNull(createdAt);
        this.status = Status.PENDING;
    }

    public void markPaid() {
        if (status != Status.PENDING) {
            throw new IllegalStateException("Order not payable: " + status);
        }
        status = Status.PAID;
    }

    // getters…
}
```

### 2. Port / Use-Case – Checkout

```java
package pro.sprintcart.application.port.in;

import java.util.UUID;

public interface CheckoutUseCase {

    /**
     * Places an order and initiates payment.
     *
     * @param cartId the shopping cart to be checked out
     * @return the created order id
     */
    UUID checkout(UUID cartId);
}
```

```java
package pro.sprintcart.application.service;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import pro.sprintcart.application.port.in.CheckoutUseCase;
import pro.sprintcart.application.port.out.PaymentPort;
import pro.sprintcart.domain.cart.Cart;
import pro.sprintcart.domain.order.OrderRepository;

import java.util.UUID;

@Service
@RequiredArgsConstructor
class CheckoutService implements CheckoutUseCase {

    private final CartService cartService;
    private final OrderFactory orderFactory;
    private final OrderRepository orderRepository;
    private final PaymentPort paymentPort;

    @Override
    @Transactional
    public UUID checkout(UUID cartId) {
        Cart cart = cartService.load(cartId);
        var order = orderFactory.fromCart(cart);
        orderRepository.save(order);
        paymentPort.requestPayment(order.getId(), order.getTotal());
        cartService.clear(cartId);
        return order.getId();
    }
}
```

### 3. Spring Boot REST Controller

```java
package pro.sprintcart.adapter.in.rest;

import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import pro.sprintcart.application.port.in.CheckoutUseCase;

import java.util.UUID;

@RestController
@RequestMapping("/api/v1/checkout")
@RequiredArgsConstructor
class CheckoutController {

    private final CheckoutUseCase checkoutUseCase;

    @PostMapping("{cartId}")
    public ResponseEntity<UUID> checkout(@PathVariable UUID cartId) {
        UUID orderId = checkoutUseCase.checkout(cartId);
        return ResponseEntity.ok(orderId);
    }
}
```

---

## 🧪 Running Tests

```bash
./mvnw test        # Unit tests
./mvnw verify -Pit # Integration tests (requires Docker)
```

JUnit 5 + Testcontainers ensure deterministic, production-like environments.

---

## 🐳 Docker Compose (Dev Stack)

```yaml
# docker-compose.yml (excerpt)
services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: sprintcart
      POSTGRES_USER: sprintcart
      POSTGRES_PASSWORD: sprintcart
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  maildev:
    image: maildev/maildev
    ports:
      - "1080:1080"  # Web UI
      - "1025:1025"  # SMTP
```

---

## 🔐 Security

* Spring Security 6 with JWT (access) & opaque tokens (refresh)
* Bcrypt password hashing (12 rounds)
* Role-based authorization (`SCOPE_catalog:write`, `SCOPE_orders:read`)

---

## 📈 Productivity Boosters

* Bulk product editor with spreadsheet-like UX (`/catalog/bulk`)
* Automation Studio – drag-and-drop rules engine
* Keyboard-first command palette (⌘K)

---

## 📦 Packaging & Deployment

1. `./mvnw -Pprod -pl sprintcart-pro-application -am package`  
   Generates a single, optimized `sprintcart-pro.jar` (≈ 45 MB).

2. Deploy to:
   * Kubernetes (`k8s/chart`)  
   * AWS Elastic Beanstalk (`.ebextensions/`)  
   * Heroku (Procfile)

---

## ➕ Extending SprintCart Pro

Creating a new outbound integration (e.g., custom CRM):

```java
@Component
@RequiredArgsConstructor
class AcmeCrmAdapter implements CrmPort {

    private final WebClient crmClient;
    private final CrmMapper mapper;

    @Override
    public void pushCustomer(Customer customer) {
        crmClient.post()
                 .uri("/customers")
                 .bodyValue(mapper.toExternal(customer))
                 .retrieve()
                 .bodyToMono(Void.class)
                 .block();
    }
}
```

Then bind your adapter in `application.yaml`:

```yaml
crm:
  provider: acme
  base-url: https://api.acme-crm.io
  api-key: ${ACME_CRM_API_KEY}
```

No domain classes are touched 🚀

---

## 🤝 Contributing

1. Fork & create a feature branch (`git checkout -b feat/awesome`)
2. Follow the [commit convention](docs/commit-style.md)
3. Run `./mvnw spotless:apply` before pushing
4. Open a PR and our CI will run the full test suite

---

## 📝 License

SprintCart Pro is distributed under the Apache License 2.0.  
See [`LICENSE`](LICENSE) for full text.
```