```markdown
<!--
  CommerceSphere Enterprise Suite
  Architectural Decision Record (ADR)
  ADR-002: Package-by-Feature vs. Package-by-Layer
  Status: ACCEPTED
  Date: 2024-05-27
-->

# ADR-002: Adopt “Package-by-Feature” as the Primary Modularization Strategy

## 1. Status
ACCEPTED – This decision has been implemented starting with version **7.4.0** of CommerceSphere Enterprise Suite.

## 2. Context

Historically, CommerceSphere has been organized using the traditional **package-by-layer** convention:

```
com.commercesphere
  └── catalog
      ├── controller
      ├── service
      ├── repository
      └── model
```

While this structure is intuitive for newcomers, we have observed several pain points over the last three release cycles:

* **Poor Feature Cohesion** – The code for a single functional slice (e.g., *Quote Management*) is scattered across many packages.
* **High Cognitive Load** – Engineers must open multiple folders to debug or extend a single feature.
* **Bloated Merge Conflicts** – Trivial changes in one layer often collide with unrelated commits in the same layer.
* **Opaque Ownership** – It is hard to determine which squad owns which classes when the same package layer hosts multiple features.

Given the accelerating pace of delivery (now shipping **bi-weekly**), we require a more cohesive, maintainable structure.

## 3. Decision

We will adopt a **Package-by-Feature** organization as the default for all new code and progressively migrate existing packages.

```
com.commercesphere
  └── features
      ├── catalog            # Product catalogs & facets
      │   ├── CatalogController.java
      │   ├── CatalogService.java
      │   ├── CatalogRepository.java
      │   └── CatalogMapper.java
      │
      ├── payments           # Payment orchestration
      │   ├── PaymentsController.java
      │   ├── PaymentsService.java
      │   ├── PaymentsFacade.java
      │   └── PaymentsRepository.java
      │
      └── quote              # Quote-to-cash workflows
          ├── QuoteController.java
          ├── QuoteService.java
          ├── QuoteRepository.java
          └── QuotePolicyValidator.java
```

### 3.1 Enforcement

1. Code reviews will reject new classes that are added directly under the top-level `controller`, `service`, or `repository` packages.
2. A Gradle task (`enforcePackageByFeature`) has been introduced to fail the build when violations are detected by static analysis (`ArchUnit` rules).
3. Each feature must include a private, `package-private` factory to prevent cross-feature leakage of internal abstractions.

## 4. Consequences

### Positive

* **High Cohesion & Low Coupling** – All classes that contribute to a feature reside in one folder.
* **Streamlined Git Diffs** – Most changes touch only a small surface area.
* **Feature-level CI Validation** – Tests, QA data, and mocks are co-located with code, enabling targeted test runs (`gradle :features:payments:test`).
* **Clear Ownership** – Squads can “own” a package without affecting others.

### Negative

* **Potential Classpath Confusion** – Import statements become longer (`com.commercesphere.features.catalog.*`).
* **Migration Overhead** – Moving existing classes may break binary compatibility for integrators using reflection.
* **IDE Index Impact** – Large IDEs (e.g., IntelliJ) may take longer to re-index if package names are heavily mutated.

## 5. Alternatives Considered

| Alternative | Outcome |
|-------------|---------|
| Continue with Package-by-Layer | Rejected – Does not address identified pain points. |
| Split into Micro-Services | Rejected – Violates monolithic cohesion requirement & increases operational overhead. |
| Adopt Java 17 Modules | Rejected for now – Adds complexity and would require major refactoring in build pipelines. |

## 6. Example Implementation

Below is a minimal yet functional **Quote** feature demonstrating the new structure.

### 6.1 `QuoteController.java`
```java
package com.commercesphere.features.quote;

import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import java.util.UUID;

/**
 * Public REST endpoint for Quote operations.
 */
@RestController
@RequestMapping("/api/v1/quotes")
class QuoteController {

    private final QuoteService quoteService;
    private final QuoteAssembler assembler;

    QuoteController(QuoteService quoteService, QuoteAssembler assembler) {
        this.quoteService = quoteService;
        this.assembler = assembler;
    }

    @PostMapping
    ResponseEntity<QuoteView> createQuote(@Valid @RequestBody QuoteRequest request) {
        Quote quote = quoteService.createQuote(request);
        return ResponseEntity
                .status(HttpStatus.CREATED)
                .body(assembler.toView(quote));
    }

    @GetMapping("/{id}")
    ResponseEntity<QuoteView> getQuote(@PathVariable UUID id) {
        return quoteService.getQuote(id)
                .map(assembler::toView)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }
}
```

### 6.2 `QuoteService.java`
```java
package com.commercesphere.features.quote;

import java.util.Optional;
import java.util.UUID;

/**
 * Domain service containing Quote business logic.
 */
interface QuoteService {

    Quote createQuote(QuoteRequest request);

    Optional<Quote> getQuote(UUID id);
}
```

### 6.3 `DefaultQuoteService.java`
```java
package com.commercesphere.features.quote;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.Optional;
import java.util.UUID;

@Service
class DefaultQuoteService implements QuoteService {

    private final QuoteRepository repository;
    private final QuotePolicyValidator policyValidator;

    DefaultQuoteService(QuoteRepository repository,
                        QuotePolicyValidator policyValidator) {
        this.repository = repository;
        this.policyValidator = policyValidator;
    }

    @Override
    @Transactional
    public Quote createQuote(QuoteRequest request) {
        policyValidator.validate(request);
        Quote quote = Quote.of(request);
        return repository.save(quote);
    }

    @Override
    @Transactional(readOnly = true)
    public Optional<Quote> getQuote(UUID id) {
        return repository.findById(id);
    }
}
```

### 6.4 `QuoteRepository.java`
```java
package com.commercesphere.features.quote;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.UUID;

/**
 * Spring Data repository for Quote entities.
 */
interface QuoteRepository extends JpaRepository<Quote, UUID> {
}
```

### 6.5 `QuotePolicyValidator.java`
```java
package com.commercesphere.features.quote;

import org.springframework.stereotype.Component;

/**
 * Validates quote creation policies such as tiered pricing
 * and customer approval workflow.
 */
@Component
class QuotePolicyValidator {

    void validate(QuoteRequest request) {
        // Business rule: Minimum order amount must exceed contract threshold
        if (request.totalValue().compareTo(request.contractThreshold()) < 0) {
            throw new IllegalStateException(
                "Quote does not satisfy minimum contract threshold");
        }
    }
}
```

### 6.6 `QuoteAssembler.java`
```java
package com.commercesphere.features.quote;

import org.springframework.stereotype.Component;

/**
 * Converts between domain objects and DTOs.
 */
@Component
class QuoteAssembler {

    QuoteView toView(Quote quote) {
        return new QuoteView(
                quote.id(),
                quote.status(),
                quote.totalValue()
        );
    }
}
```

> NOTE: Unit tests for each class reside in the same package (`src/test/java/com/commercesphere/features/quote`) to leverage package-private methods.

## 7. Migration Plan

1. **Sprint 62** – Migrate features `catalog`, `payments`, and `quote`.
2. **Sprint 63** – Auto-refactor layer packages (`controller`, `service`, etc.) using IntelliJ structural search.
3. **Sprint 64** – Remove deprecated packages and enable `enforcePackageByFeature` build rule in **fail-fast** mode.
4. Document the new structure in the developer playbook & host a lunch-and-learn.

## 8. References

* “Package by Feature, not Layer” by Robert C. Martin – NDC Conference 2017.
* ArchUnit Rule Examples – https://www.archunit.org
* Shopify Engineering – *Organizing Rails Controllers by Feature* (analogous concept)

---
This ADR will be revisited after two major releases (approx. 6 months) to assess its efficacy.
```