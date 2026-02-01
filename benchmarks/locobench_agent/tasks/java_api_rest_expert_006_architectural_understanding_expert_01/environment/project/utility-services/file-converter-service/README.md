```markdown
# 🗄️ File Converter Service
Part of **OpsForge Utility Nexus**, the File Converter Service offers high-performance, lossless conversion between a curated set of enterprise-grade file formats (CSV ↔ XLSX, DOCX → PDF, PNG ↔ JPG, etc.).  
The service is _API-first_, fully stateless, and designed around **hexagonal architecture** so that the core domain never depends on delivery or infrastructure concerns.

![CI](https://github.com/opsforge/utility-nexus/actions/workflows/ci.yml/badge.svg)
![Coverage](https://img.shields.io/badge/coverage-92%25-brightgreen)
![License](https://img.shields.io/github/license/opsforge/utility-nexus)

---

## ✨ Key Capabilities
| Feature                     | Description                                                                                          |
|-----------------------------|------------------------------------------------------------------------------------------------------|
| Multi-format conversion     | Convert between 18 common office, raster, and vector formats with streaming I/O.                    |
| Secure-by-default           | All temp artifacts are encrypted at rest (AES-256) and shredded on completion.                      |
| Reactive & Non-blocking     | Built with Spring WebFlux and Project Reactor for massive concurrency.                              |
| Pluggable engines           | Swap out LibreOffice, Apache POI, or ImageMagick without touching domain logic.                     |
| Idempotent, traceable calls | Deterministic checksums, correlation IDs, and OpenTelemetry spans for every request.                |
| API Gateway integration     | Exposed via REST (v1/ v2) and GraphQL while enforcing tenant-aware rate limiting & caching.         |

---

## 🏗️ Project Structure (Hexagonal View)

```
file-converter-service
├─ src
│  ├─ main
│  │  ├─ java
│  │  │  └─ com.opsforge.utility.converter
│  │  │     ├─ domain          ← Pure business objects & policies
│  │  │     ├─ application     ← Use-cases / orchestrations
│  │  │     ├─ inbound         ← REST + GraphQL adapters
│  │  │     └─ outbound        ← Engine ports, persistence, cache
│  │  └─ resources
│  │     └─ graphql            ← *.graphqls schema definitions
│  └─ test                     ← Unit, slice & contract tests
└─ README.md
```

---

## 🖥️ Quick Start

### Prerequisites
* Java 17+
* Maven 3.9.x
* Docker 24.x (for local LibreOffice/ ImageMagick containers)

### Build & Run (Local)

```bash
# Clone mono-repo (shallow)
git clone --filter=blob:none --sparse https://github.com/opsforge/utility-nexus.git
cd utility-nexus
git sparse-checkout set utility-services/file-converter-service

# Build with unit + integration tests
mvn -pl utility-services/file-converter-service clean verify

# Start external engines
docker compose -f compose/engines.yml up -d

# Launch Spring Boot app
mvn -pl utility-services/file-converter-service spring-boot:run
```

### REST Usage

```bash
curl -X POST http://localhost:8082/api/v2/files/convert \
     -H "Content-Type: multipart/form-data" \
     -F "file=@annual_report.xlsx" \
     -F "targetFormat=PDF" \
     -H "X-Correlation-Id: $(uuidgen)" \
     --output annual_report.pdf
```

Response headers include:

```
X-OpsForge-Checksum-SHA256: 3b17c7…
X-OpsForge-Cache-Status: MISS
```

### GraphQL Query

```graphql
mutation convertDoc($input: ConvertFileInput!) {
  convertFile(input: $input) {
    downloadUrl
    checksum
    durationMillis
  }
}

# Variables
{
  "input": {
    "fileName": "budget.xlsx",
    "targetFormat": "CSV"
  }
}
```

---

## 🛠️ Selected Code Snippets

Below are excerpts to illustrate the production code-quality and separation of concerns.  
_See full sources under `src/main/java`._

```java
/* Domain Model — ConversionRequest */
package com.opsforge.utility.converter.domain;

import java.time.Instant;
import java.util.UUID;

/**
 * Immutable value object representing a client's conversion intention.
 */
public record ConversionRequest(
        UUID correlationId,
        String originalFileName,
        FileFormat sourceFormat,
        FileFormat targetFormat,
        Instant requestedAtUtc
) {
    public ConversionRequest {
        if (sourceFormat == targetFormat) {
            throw new IllegalArgumentException("Source and target formats must differ");
        }
    }
}
```

```java
/* Application Service — ConvertFileUseCase */
package com.opsforge.utility.converter.application;

import com.opsforge.utility.converter.domain.*;
import reactor.core.publisher.Mono;

public interface ConvertFileUseCase {

    /**
     * Converts a file represented as reactive byte stream.
     *
     * @param request  metadata & policies
     * @param content  raw bytes of the source file
     * @return stream of converted bytes
     */
    Mono<ConversionResult> execute(ConversionRequest request, Mono<byte[]> content);
}
```

```java
/* Inbound Adapter — REST Controller */
package com.opsforge.utility.converter.inbound.rest;

import com.opsforge.utility.converter.application.ConvertFileUseCase;
import com.opsforge.utility.converter.domain.*;
import jakarta.validation.constraints.NotNull;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import reactor.core.publisher.Mono;

@RestController
@RequiredArgsConstructor
@RequestMapping(path = "/api/v2/files", produces = MediaType.APPLICATION_JSON_VALUE)
public class FileConversionController {

    private final ConvertFileUseCase useCase;

    @PostMapping(
        path = "/convert",
        consumes = MediaType.MULTIPART_FORM_DATA_VALUE
    )
    public Mono<ConversionResponse> convert(
            @RequestPart("file") @NotNull MultipartFile file,
            @RequestPart("targetFormat") @NotNull String targetFormat) {

        var request = new ConversionRequest(
                UUID.randomUUID(),
                file.getOriginalFilename(),
                FileFormat.detect(file.getOriginalFilename()),
                FileFormat.valueOf(targetFormat.toUpperCase()),
                Instant.now()
        );

        return useCase.execute(request, Mono.fromCallable(file::getBytes))
                      .map(ConversionResponse::fromResult);
    }
}
```

---

## 📜 Error Catalogue

Code | HTTP | Meaning
---- | ---- | -------
FCS-001 | 400 | Unsupported/unknown file type
FCS-002 | 422 | Conversion engine failed (detail in payload)
FCS-003 | 429 | Rate limit exceeded (per tenant)
FCS-004 | 503 | All engine back-ends currently unavailable

Errors follow [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457).

---

## 🧩 Environment Variables

| Variable                          | Default           | Description                                   |
|----------------------------------|-------------------|-----------------------------------------------|
| `FCS_LIBREOFFICE_URI`            | `http://lo:2002`  | Host:port for LibreOffice UNO bridge          |
| `FCS_IMAGEMAGICK_URI`            | `http://im:9000`  | gRPC address for ImageMagick wrapper          |
| `FCS_STORAGE_BUCKET`             | `files`           | Object-store bucket for temp artifacts        |
| `FCS_MAX_FILE_MB`                | `128`             | Guard rail for request payload size           |

---

## 🧪 Testing Matrix

* **Unit Tests** – Pure JUnit 5 & AssertJ, no Spring context
* **Slice Tests** – `@WebFluxTest` for controller/handler layers
* **Contract Tests** – Generated from OpenAPI via Spring Cloud Contract
* **Load Tests** – Gatling simulations committed under `perf/`

Run everything:

```bash
mvn verify -Pfull-ci
```

---

## 🤝 Contributing
1. Fork & branch from `main`
2. Enable pre-commit hooks (`./scripts/install-commit-hooks.sh`)
3. Follow the Conventional Commits spec
4. Create PR—two approvals & green build required

---

## 📄 License
Distributed under the **Apache License 2.0**. See `LICENSE` for details.
```