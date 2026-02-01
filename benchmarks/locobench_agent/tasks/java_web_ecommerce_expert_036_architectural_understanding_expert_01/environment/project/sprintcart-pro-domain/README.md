```markdown
# SprintCart Pro – Domain Layer (`sprintcart-pro-domain`)
_Enterprise-grade e-commerce logic modeled using Hexagonal Architecture._

---

## Table of Contents
1. Domain Philosophy  
2. Package Structure  
3. Key Building Blocks  
4. Coding Guidelines & Conventions  
5. Sample Implementation Snippets  
6. Running Unit Tests  

---

## 1. Domain Philosophy
The domain layer is **framework-agnostic** and expresses pure business concepts such as `Order`, `CatalogItem`, `WorkQueue`, and `ProductivityMetric`.  
No HTTP, SQL, or message-broker code lives here; those details are delegated to adapters that depend **on** the domain—not vice-versa.

* Ports (interfaces) define use-cases (`CheckoutPort`, `InventoryAdjustmentPort`).  
* Adapters implement ports for REST controllers, CLI tools, Azure Service Bus listeners, etc.  
* Domain events such as `OrderPaid` and `StockReordered` allow cross-cutting logic (e.g., KPI tracking) without tight coupling.

---

## 2. Package Structure
```text
com.sprintcartpro.domain
├── common             # Generic value objects (Money, EmailAddress)
├── catalog            # Product, Variant, Category aggregates
├── checkout           # Order aggregate, Payment & Shipping policies
├── productivity       # WorkQueue, KPI, AutomationRule models
├── shared             # Domain events, Id generation, Clock abstraction
└── spi                # Ports (Service Provider Interfaces)
```

---

## 3. Key Building Blocks

| Package | Responsibility | Example Classes |
|---------|---------------|-----------------|
| `common` | Reusable primitives & utilities | `Money`, `Percentage`, `EmailAddress` |
| `catalog` | Merchandisable entities | `Product`, `Variant`, `InventoryItem` |
| `checkout` | Order life-cycle & payment orchestration | `Order`, `OrderLineItem`, `PaymentPolicy` |
| `productivity` | Workflow & automation | `WorkQueue`, `AutomationRule`, `ProductivityMetric` |
| `spi` | Hexagonal ports | `PaymentGatewayPort`, `InventoryGatewayPort` |

---

## 4. Coding Guidelines & Conventions
* **Immutability first** – aggregates expose intention-revealing methods and return new instances when mutated.  
* **Fail fast** – all public factory methods validate arguments and throw `IllegalArgumentException` on failure.  
* **Domain events** – emit an event for every state transition.  
* **Package-private constructors** – enforce invariants via static factory methods.  
* **No Lombok** – explicit code is favored for clarity and debugging.

---

## 5. Sample Implementation Snippets

Below are condensed yet production-ready excerpts to illustrate best practices.  
Feel free to copy/paste them as starting points for new features.

### 5.1 `Money` – A Currency-Aware Value Object
```java
package com.sprintcartpro.domain.common;

import java.math.BigDecimal;
import java.util.Currency;
import java.util.Objects;

/**
 * Immutable representation of a monetary amount.
 */
public final class Money {

    private final BigDecimal amount;
    private final Currency currency;

    private Money(BigDecimal amount, Currency currency) {
        this.amount = amount.setScale(currency.getDefaultFractionDigits());
        this.currency = currency;
    }

    public static Money of(BigDecimal amount, Currency currency) {
        Objects.requireNonNull(amount, "amount");
        Objects.requireNonNull(currency, "currency");
        if (amount.scale() > currency.getDefaultFractionDigits()) {
            throw new IllegalArgumentException("Scale exceeds currency fraction digits");
        }
        return new Money(amount, currency);
    }

    public Money add(Money other) {
        assertSameCurrency(other);
        return of(amount.add(other.amount), currency);
    }

    public Money subtract(Money other) {
        assertSameCurrency(other);
        return of(amount.subtract(other.amount), currency);
    }

    public boolean isNegative() {
        return amount.signum() < 0;
    }

    private void assertSameCurrency(Money other) {
        if (!currency.equals(other.currency)) {
            throw new IllegalArgumentException("Currency mismatch");
        }
    }

    // getters, equals, hashCode, toString omitted for brevity
}
```

### 5.2 `Order` Aggregate Root (Simplified)
```java
package com.sprintcartpro.domain.checkout;

import com.sprintcartpro.domain.common.Money;
import com.sprintcartpro.domain.shared.DomainEvent;
import com.sprintcartpro.domain.shared.EventRecorder;
import java.time.OffsetDateTime;
import java.util.*;

/**
 * Order aggregate root capturing the entire checkout flow.
 */
public final class Order extends EventRecorder {

    public enum Status { DRAFT, PLACED, PAID, FULFILLED, CANCELED }

    private final UUID id;
    private final OffsetDateTime createdAt;
    private Status status;
    private final List<LineItem> items;
    private final Money subtotal;

    private Order(UUID id, OffsetDateTime createdAt, Status status,
                  List<LineItem> items, Money subtotal) {
        this.id = id;
        this.createdAt = createdAt;
        this.status = status;
        this.items = Collections.unmodifiableList(items);
        this.subtotal = subtotal;
    }

    public static Order draft(List<LineItem> items) {
        Objects.requireNonNull(items, "items");
        if (items.isEmpty()) throw new IllegalArgumentException("Items cannot be empty");

        Money subtotal = items.stream()
                              .map(LineItem::lineTotal)
                              .reduce(Money::add)
                              .orElseThrow();

        Order order = new Order(UUID.randomUUID(),
                                OffsetDateTime.now(),
                                Status.DRAFT,
                                new ArrayList<>(items),
                                subtotal);

        order.recordEvent(new DomainEvent.OrderCreated(order.id));
        return order;
    }

    public Order place() {
        ensureStatus(Status.DRAFT);
        this.status = Status.PLACED;
        recordEvent(new DomainEvent.OrderPlaced(id));
        return this;
    }

    public Order markAsPaid() {
        ensureStatus(Status.PLACED);
        this.status = Status.PAID;
        recordEvent(new DomainEvent.OrderPaid(id));
        return this;
    }

    public Order cancel(String reason) {
        ensureStatus(Status.DRAFT, Status.PLACED);
        this.status = Status.CANCELED;
        recordEvent(new DomainEvent.OrderCanceled(id, reason));
        return this;
    }

    private void ensureStatus(Status... allowed) {
        if (Arrays.stream(allowed).noneMatch(s -> s == this.status)) {
            throw new IllegalStateException("Operation not allowed in status " + status);
        }
    }

    // getters omitted for brevity

    /* --- Nested Entity --- */
    public record LineItem(UUID productId, int quantity, Money unitPrice) {

        public LineItem {
            Objects.requireNonNull(productId, "productId");
            Objects.requireNonNull(unitPrice, "unitPrice");
            if (quantity <= 0) throw new IllegalArgumentException("quantity must be > 0");
        }

        public Money lineTotal() {
            return unitPrice.multiply(quantity);
        }
    }
}
```

### 5.3 Domain Event Recorder (Infrastructure-Independent)
```java
package com.sprintcartpro.domain.shared;

import java.util.ArrayDeque;
import java.util.Collections;
import java.util.Deque;
import java.util.List;

/**
 * Base class for aggregates that emit domain events.
 */
public abstract class EventRecorder {

    private final Deque<DomainEvent> events = new ArrayDeque<>();

    protected void recordEvent(DomainEvent event) {
        events.add(event);
    }

    public List<DomainEvent> domainEvents() {
        return Collections.unmodifiableList(events.stream().toList());
    }

    public void clearEvents() {
        events.clear();
    }
}
```

---

## 6. Running Unit Tests
The domain module is 100 % covered by JUnit 5.  
Execute the following command from the project root:

```bash
./gradlew :sprintcart-pro-domain:test
```

All tests **must** pass before opening a pull-request.

---

> “Make it work, make it right, make it fast.” – Kent Beck
```