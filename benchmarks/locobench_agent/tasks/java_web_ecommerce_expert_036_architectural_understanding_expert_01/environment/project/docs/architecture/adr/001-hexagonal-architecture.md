```markdown
# Architectural Decision Record: 001 — Adopt Hexagonal Architecture (Ports & Adapters)

| Status | Date | Deciders |  
| ------ | ---- | -------- |  
| Accepted | 2024-06-11 | Core Architecture Team (A. Dev, B. Lead, C. Ops) |

## 1. Context  

SprintCart Pro is positioned as an _operator-first_ e-commerce platform where every back-office interaction is a measurable, optimizable work cycle.  
Key business drivers:

* Rapid feature velocity — new sales channels (live-shopping, voice assistants, AI chat) must be added without re-writing the business core.  
* On-prem & SaaS deployments — domain logic must remain agnostic to external infrastructure (RDBMS vs. document store, single-tenant vs. multi-tenant).  
* High-performance back office — productivity tooling (e.g., bulk editors, automation studio) must call the same domain use-cases as the public storefront to guarantee consistency.  

After evaluating several architectural styles (Layered, Clean Architecture, Event-Sourced, Micro-Kernels), we need an approach that:

1. Keeps domain code pure and testable.  
2. Decouples inbound adapters (REST, GraphQL, SPA, CLI, batch) from outbound integrations (Stripe, SendGrid, ERP) through explicit, technology-agnostic contracts.  
3. Minimizes cross-cutting concerns bleeding into business logic (e.g., tracing, auth, validation).  

## 2. Decision  

We will structure SprintCart Pro following _Hexagonal Architecture_ (Ports & Adapters) as described by Alistair Cockburn:

* **Domain Layer (Inside)** — Aggregates, Entities, Value Objects, and Domain Services with no dependencies on frameworks.  
* **Application Layer** — Use-cases (Service Layer) orchestrating domain objects via _inbound ports_ (commands/queries).  
* **Inbound Adapters** — REST/GraphQL controllers, WebSocket handlers, scheduled jobs.  
* **Outbound Adapters** — Payment gateways, messaging, notification services, external ERPs.  
* **Ports** — Java interfaces owned by the core that define required/expected behavior, enabling adapters to plug in without touching the domain.  

### Folder Blueprint (Gradle multi-module)

```
sprintcart-pro/
 ├─ sprintcart-domain/          // pure Java/Kotlin, no Spring
 ├─ sprintcart-application/     // use-cases, ports
 ├─ sprintcart-adapter-in/      // web-rest, graphql, scheduler
 ├─ sprintcart-adapter-out/     // stripe, sendgrid, kafka
 └─ sprintcart-boot/            // Spring Boot composition root
```

## 3. Consequences  

### Positive
* Domain logic is testable with plain JUnit; adapters are mocked via ports.  
* New channels (voice POS, headless kiosk) add an inbound adapter without touching core.  
* Payment gateways can be swapped (Stripe → Adyen) by implementing the same `PaymentPort`.  
* Clear ownership boundaries reduce merge conflicts across teams (Core vs. Integration).  

### Negative
* Boilerplate overhead for simple CRUD scenarios.  
* Developers unfamiliar with Ports & Adapters need onboarding.  
* Extra indirection can complicate debugging if logging/tracing is not standardized.  

## 4. Sample Reference Implementation  

```java
// sprintcart-application/src/main/java/pro/sprintcart/checkout/port/in/PlaceOrderCommand.java
package pro.sprintcart.checkout.port.in;

import java.util.UUID;

/**
 * Inbound Port exposed by the Application layer.
 * Technology-agnostic contract for placing an order.
 */
public interface PlaceOrderCommand {
    UUID place(OrderDraft draft);
}
```

```java
// sprintcart-application/src/main/java/pro/sprintcart/checkout/port/out/PaymentPort.java
package pro.sprintcart.checkout.port.out;

import pro.sprintcart.checkout.domain.Payment;
import pro.sprintcart.checkout.domain.PaymentMethod;

/**
 * Outbound Port required by the core.
 * Implemented by StripeAdapter, AdyenAdapter, etc.
 */
public interface PaymentPort {
    Payment charge(PaymentMethod method, Money amount);
}
```

```java
// sprintcart-adapter-out/stripe/StripePaymentAdapter.java
package pro.sprintcart.adapter.out.stripe;

import com.stripe.exception.StripeException;
import com.stripe.model.Charge;
import pro.sprintcart.checkout.domain.*;
import pro.sprintcart.checkout.port.out.PaymentPort;
import pro.sprintcart.shared.Money;
import org.springframework.stereotype.Component;

@Component
public class StripePaymentAdapter implements PaymentPort {

    @Override
    public Payment charge(PaymentMethod method, Money amount) {
        try {
            Charge charge = Charge.create(Map.of(
                "amount", amount.inMinorUnits(),
                "currency", amount.getCurrency().getCurrencyCode(),
                "source", method.token()
            ));
            return Payment.approved(charge.getId());
        } catch (StripeException ex) {
            throw new PaymentGatewayException("Stripe charge failed", ex);
        }
    }
}
```

```java
// sprintcart-adapter-in/rest/CheckoutController.java
package pro.sprintcart.adapter.in.rest;

import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import pro.sprintcart.checkout.port.in.PlaceOrderCommand;
import pro.sprintcart.checkout.application.dto.OrderDraftDTO;

@RestController
@RequestMapping("/api/v1/checkout")
public class CheckoutController {

    private final PlaceOrderCommand placeOrder;

    public CheckoutController(PlaceOrderCommand placeOrder) {
        this.placeOrder = placeOrder;
    }

    @PostMapping("/orders")
    public ResponseEntity<?> place(@Valid @RequestBody OrderDraftDTO dto) {
        var orderId = placeOrder.place(dto.toDomain());
        return ResponseEntity.accepted().body(Map.of("orderId", orderId));
    }
}
```

The domain, application, and adapter layers compile independently, are wired by Spring Boot in the `sprintcart-boot` module, and can be sliced for serverless or on-prem deployments.

## 5. References  

* Alistair Cockburn — _Hexagonal Architecture_.  
* “Ports and Adapters Architecture” — Fowler, M. Patterns of Enterprise Application Architecture.  
* Team ADR 000 — Directory structure and ADR decision-making policy.  
```