```md
# 002 — Hexagonal Architecture for Services
> Status: **Accepted**  
> Date: 2024-06-16  
> Decision Makers: Platform Architecture Guild  
> Supersedes: N/A  
> Tags: architecture, hexagonal, ports-and-adapters

## 1. Context
OpsForge Utility Nexus exposes a suite of *utility micro-services* ranging from file conversions to bulk text transformations.  
We need each service to be:

* Technology-agnostic at its core  
* Swappable in-/out-bound infrastructure without touching business logic  
* Meticulously testable (pure unit tests at the core, integration tests at the edges)  
* Compatible with both HTTP/JSON and GraphQL façades  

These goals naturally align with **Hexagonal Architecture (aka Ports & Adapters)**.

## 2. Decision
Every utility is implemented as a self-contained hexagon:

1. **Domain/Core**  
   * Pure POJOs and value objects  
   * Use-case orchestrators (Application Services)  
   * Port interfaces (inbound & outbound)

2. **Adapters**  
   * **Inbound**: REST controllers / GraphQL resolvers / message listeners  
   * **Outbound**: Repository drivers, SaaS connectors, cache providers  

3. **Configuration**  
   * Wiring of ports to adapters via dependency injection (Spring Boot)  
   * Uniform, versioned contracts exposed by the API Gateway layer  

All cross-cutting concerns (rate limiting, caching, tracing, etc.) are expressed as *decorators* or *framework interceptors*, never leaking into domain code.

## 3. Consequences
✔ Fast unit tests against core logic  
✔ Easy to swap technologies (e.g., Caffeine → Redis)  
✔ Clear test boundaries (mock ports instead of mocks everywhere)  
✘ Slightly higher initial boilerplate (worth the ROI)

---

## 4. Reference Implementation

Below is a trimmed, yet **runnable** example of the File-Conversion utility adopting the hexagonal style.

```java
// -------- 1️⃣ Domain Layer (Core) -------------------------------------------
package com.opsforge.utility.fileconversion.domain;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * Value object that represents a single file-conversion request.
 */
public record ConversionRequest(
        UUID requestId,
        String sourceFormat,
        String targetFormat,
        byte[] payload,
        OffsetDateTime requestedAt
) {}

/**
 * Port that expresses the *purpose* of persisting conversion artefacts.
 */
public interface ArtefactStoragePort {
    void save(UUID requestId, byte[] convertedPayload);
}

/**
 * Primary use-case orchestrator (Application Service).
 */
public class ConvertFileUseCase {

    private final ArtefactStoragePort storagePort;
    private final FileFormatConverter converter; // pure domain service

    public ConvertFileUseCase(ArtefactStoragePort storagePort,
                              FileFormatConverter converter) {
        this.storagePort = storagePort;
        this.converter   = converter;
    }

    /**
     * Executes the conversion and persists the output using the outbound port.
     */
    public ConversionResponse execute(ConversionRequest request) {
        byte[] output = converter.convert(
                request.sourceFormat(),
                request.targetFormat(),
                request.payload()
        );
        storagePort.save(request.requestId(), output);
        return new ConversionResponse(request.requestId(), output.length);
    }
}

/**
 * Domain service that performs format conversion.
 * Decoupled from any IO concerns.
 */
public interface FileFormatConverter {
    byte[] convert(String from, String to, byte[] input);
}

/**
 * Minimal response DTO emitted by the use-case.
 */
public record ConversionResponse(UUID requestId, int sizeInBytes) {}
```

```java
// -------- 2️⃣ Inbound Adapter (REST Controller) -----------------------------
package com.opsforge.utility.fileconversion.inbound.rest;

import com.opsforge.utility.fileconversion.domain.*;
import jakarta.validation.constraints.NotNull;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * REST façade that delegates to the core use-case.
 */
@RestController
@RequestMapping("/v1/conversions")
@Validated
public class FileConversionController {

    private final ConvertFileUseCase useCase;

    public FileConversionController(ConvertFileUseCase useCase) {
        this.useCase = useCase;
    }

    @PostMapping
    public ResponseEntity<ConversionResponse> convert(
            @RequestParam @NotNull String sourceFormat,
            @RequestParam @NotNull String targetFormat,
            @RequestBody byte[] payload
    ) {
        ConversionRequest request = new ConversionRequest(
                UUID.randomUUID(),
                sourceFormat,
                targetFormat,
                payload,
                OffsetDateTime.now()
        );
        return ResponseEntity.ok(useCase.execute(request));
    }
}
```

```java
// -------- 3️⃣ Outbound Adapter (S3 Artefact Storage) ------------------------
package com.opsforge.utility.fileconversion.outbound.s3;

import com.opsforge.utility.fileconversion.domain.ArtefactStoragePort;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;

import java.util.UUID;

/**
 * Concrete adapter that stores conversion outputs in an S3 bucket.
 */
public class S3ArtefactStorageAdapter implements ArtefactStoragePort {

    private static final Logger LOG = LoggerFactory.getLogger(S3ArtefactStorageAdapter.class);

    private final S3Client s3;
    private final String   bucketName;

    public S3ArtefactStorageAdapter(S3Client s3, String bucketName) {
        this.s3 = s3;
        this.bucketName = bucketName;
    }

    @Override
    public void save(UUID requestId, byte[] convertedPayload) {
        try {
            PutObjectRequest req = PutObjectRequest.builder()
                    .bucket(bucketName)
                    .key(requestId + ".bin")
                    .build();
            s3.putObject(req, RequestBody.fromBytes(convertedPayload));
        } catch (Exception e) {
            LOG.error("Failed to store artefact for request {}", requestId, e);
            throw new ArtefactStorageException(requestId, e);
        }
    }
}
```

```java
// -------- 4️⃣ Configuration (Spring) ---------------------------------------
package com.opsforge.utility.fileconversion.config;

import com.opsforge.utility.fileconversion.domain.*;
import com.opsforge.utility.fileconversion.outbound.s3.S3ArtefactStorageAdapter;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import software.amazon.awssdk.services.s3.S3Client;

/**
 * Wires ports to adapters using Spring’s DI container.
 */
@Configuration
public class FileConversionModule {

    @Bean
    ConvertFileUseCase convertFileUseCase(
            ArtefactStoragePort storagePort,
            FileFormatConverter converter) {
        return new ConvertFileUseCase(storagePort, converter);
    }

    @Bean
    @ConditionalOnProperty(name = "storage.provider", havingValue = "s3")
    ArtefactStoragePort s3StoragePort(S3Client s3,
                                      FileConversionProperties props) {
        return new S3ArtefactStorageAdapter(s3, props.bucket());
    }
}
```

```java
// -------- 5️⃣ Cross-Cutting Concern (Caching Decorator) --------------------
package com.opsforge.utility.fileconversion.outbound.cache;

import com.github.benmanes.caffeine.cache.Cache;
import com.opsforge.utility.fileconversion.domain.ArtefactStoragePort;

import java.util.UUID;

/**
 * Transparently caches artefacts before delegating to the "real" port.
 */
public class CachingStorageDecorator implements ArtefactStoragePort {

    private final Cache<UUID, byte[]> cache;
    private final ArtefactStoragePort delegate;

    public CachingStorageDecorator(Cache<UUID, byte[]> cache,
                                   ArtefactStoragePort delegate) {
        this.cache = cache;
        this.delegate = delegate;
    }

    @Override
    public void save(UUID requestId, byte[] convertedPayload) {
        cache.put(requestId, convertedPayload);
        delegate.save(requestId, convertedPayload);
    }
}
```

## 5. Testing Strategy
* **Core tests**: Pure JUnit tests verifying `ConvertFileUseCase` with mocked ports  
* **Adapter tests**: Web-layer tests for controller, TestContainers for S3 emulation  
* **Contract tests**: Swagger / GraphQL SDL snapshots per version

---

## 6. Rejected Alternatives
1. Layered (n-tier) architecture — tight coupling across layers, harder to swap tech.  
2. Anemic-model approach — domain logic scattered in services, violates DDD principles.  

---

## 7. Links
* Alistair Cockburn, *Hexagonal Architecture* (2005)  
* Fowler, *Ports and Adapters* article  
```
