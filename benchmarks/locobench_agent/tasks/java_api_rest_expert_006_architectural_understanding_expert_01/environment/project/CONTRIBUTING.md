# Contributing to OpsForge Utility Nexus (api_rest)

> Welcome! We’re excited that you want to contribute to OpsForge Utility Nexus.  
> This document describes the standards, workflows and quality bars that every pull-request must meet before being merged into `main`.

---

## 1. Ground Rules

* **Create an Issue First** – Whether you intend to fix a bug or propose a new feature, open an issue so we can discuss scope, ownership and architectural fit.
* **Small, Focused PRs** – One pull-request should solve one problem. Avoid “kitchen-sink” changes.
* **Follow the Hexagonal Architecture** – All new code _must_ respect the existing ports-and-adapters boundaries. See `docs/architecture.md` for details.
* **100 % CI Green** – A PR is not eligible for review until all GitHub Actions workflows pass.
* **Respect Versioning** – Any change that breaks the public REST/GraphQL contract must bump the appropriate semantic version part _and_ update changelogs.

---

## 2. Branch & Workflow

1. Fork the repository and clone your fork locally.
2. Create a branch off `main` using the naming convention:

   ```
   <type>/<github-issue-id>-short-description
   # e.g. feature/42-brotli-compression
   # Types: feature | fix | docs | chore | refactor | test
   ```

3. Keep your branch in sync with upstream `main`:

   ```shell
   git fetch upstream
   git rebase upstream/main
   ```

4. Open a Draft PR early to trigger CI and receive async feedback.
5. Mark the PR “Ready for review” once all checklist items are complete (see § 9).

---

## 3. Code Style

We strictly adhere to **Google Java Style** with additional project-specific rules enforced by:

* [`spotless`](https://github.com/diffplug/spotless) – auto-formats code on build  
  `./gradlew spotlessApply`
* [`error-prone`](https://errorprone.info/) – catches common mistakes at compile-time
* [`NullAway`](https://github.com/uber/NullAway) – enforces null-safety

Running `./gradlew check` locally before pushing will save you many CI round-trips.

---

## 4. Architectural Principles

* **Domain ≠ Infrastructure** – Domain entities **never** reference Spring, JPA, Jackson, etc.  
* **Application Services Are Thin** – They orchestrate domain objects and delegate to ports.  
* **Adapters Only Depend Inward** – Outbound adapters (`*-adapter-*` modules) implement ports; inbound adapters (`*-controller-*`) expose them.  
* **CQRS** – Keep commands side-effect free and queries read-only.  
* **Resilience** – All outbound calls must have timeouts, retries and circuit-breakers (see `resilience4j` config).

---

## 5. Test Strategy

| Layer             | Framework                         | Goal                       | Minimum Coverage |
|-------------------|-----------------------------------|----------------------------|------------------|
| Domain            | JUnit 5, AssertJ                  | Business rules             | 90 %             |
| Application       | JUnit 5, Mockito                  | Use-case flow              | 80 %             |
| Inbound Adapter   | Spring MockMvc, graphql-tester    | Contract & validation      | 70 %             |
| Outbound Adapter  | Testcontainers, WireMock, ToxiProxy| Integration w/ deps        | 70 %             |

Run `./gradlew jacocoTestReport` and check the `build/reports/jacoco` HTML output before submission.

---

## 6. Commit Messages

Follow the **Conventional Commits** spec:

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

Example:

```
fix(anonymizer): preserve UUID format in masked output

The previous implementation generated invalid UUIDs
when the original value contained uppercase letters.

Closes #123
```

---

## 7. Documentation

* Public API changes require updates to:
  * `api/openapi/**/*.yaml`
  * `api/graphql/**/*.graphqls`
  * `CHANGELOG.md`
* Significant internal changes should be reflected in `docs/architecture.md`
  and, when relevant, ADRs under `docs/adr-*`.

---

## 8. Sample Skeleton for New Utilities

Below is a **minimal yet production-ready** implementation skeleton that complies with all project conventions. Use it as a starting point for new utilities.

```java
package com.opsforge.utilitynexus.checksum.adapter.in.rest;

import com.opsforge.utilitynexus.checksum.application.port.in.GenerateChecksumCommand;
import com.opsforge.utilitynexus.checksum.application.port.in.GenerateChecksumUseCase;
import com.opsforge.utilitynexus.shared.web.ApiError;
import com.opsforge.utilitynexus.shared.web.validation.EnumNamePattern;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@RestController
@Validated
@RequestMapping(
    path = "/v1/checksums",
    produces = MediaType.APPLICATION_JSON_VALUE,
    consumes = MediaType.APPLICATION_JSON_VALUE
)
@RequiredArgsConstructor
public class ChecksumController {

    private final GenerateChecksumUseCase useCase;

    @PostMapping
    public ChecksumResponse generate(@RequestBody @Validated ChecksumRequest request) {
        try {
            var command = new GenerateChecksumCommand(
                request.algorithm(),
                request.payload()
            );
            var checksum = useCase.handle(command);
            return new ChecksumResponse(checksum);
        } catch (IllegalArgumentException ex) {
            throw ApiError.invalidInput(ex.getMessage());
        }
    }

    // -----------------------------------------------------------------------
    // DTOs (Inbound only – never leak domain objects!)
    // -----------------------------------------------------------------------

    public record ChecksumRequest(
        @EnumNamePattern(regexp = "MD5|SHA1|SHA256|SHA512")
        String algorithm,

        @NotBlank
        @Size(max = 2_000_000) // max 2 MB
        String payload
    ) {}

    public record ChecksumResponse(String value) {}
}
```

Key Takeaways:

1. The controller depends **only** on the inbound port (`GenerateChecksumUseCase`), not on any domain or outbound adapter classes.
2. Validation is declarative (`jakarta.validation`) and fails fast before reaching business logic.
3. Errors are mapped to a centralized `ApiError` hierarchy for consistent responses.

---

## 9. Pull-Request Checklist

Before switching your PR from _Draft_ to _Ready for review_:

- [ ] All unit & integration tests pass locally (`./gradlew clean build`)
- [ ] Code is formatted (`./gradlew spotlessApply`)
- [ ] Jacoco coverage ≥ thresholds in § 5
- [ ] No new warnings from `error-prone` or `NullAway`
- [ ] OpenAPI/GraphQL schemas updated (if applicable)
- [ ] Added/updated documentation
- [ ] Squash commits into logical units (`fix:` / `feat:` / etc.)
- [ ] Linked the relevant issue (`Fixes #<id>`, `Closes #<id>`)

---

## 10. Code of Conduct

We expect everyone to adhere to the [Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). Be kind, be respectful, and help us build a welcoming community.

---

## 11. Getting Help

If you’re stuck:

1. Re-read this document – most answers live here.
2. Search existing [issues](../../issues) and [discussions](../../discussions).
3. Ask in the `#contrib` channel on Slack (invite link in the repo description).
4. If everything fails, open a new issue with as much context as possible.

Happy hacking! 🎉