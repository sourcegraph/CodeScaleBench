```markdown
# Contributing to **TycoonVerse**

> Welcome, entrepreneur!  
> Thank you for taking the time to help shape the TycoonVerse platform.  
> This document describes everything you need to build, test, and submit changes  
> that meet the project’s production-grade standards.

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Prerequisites](#prerequisites)
3. [Branching & Workflow](#branching--workflow)
4. [Commit Message Convention](#commit-message-convention)
5. [Coding Standards](#coding-standards)
6. [Architecture Guidelines](#architecture-guidelines)
7. [Testing Strategy](#testing-strategy)
8. [Pull Request Checklist](#pull-request-checklist)
9. [Issue Triage](#issue-triage)
10. [Tooling & Automation](#tooling--automation)
11. [Security & Sensitive Data](#security--sensitive-data)
12. [Code of Conduct](#code-of-conduct)
13. [License](#license)

---

## Project Overview
TycoonVerse is a **mobile business-simulation** game built entirely in C#.  
Its layered architecture separates:

| Layer           | Responsibility                                 |
|-----------------|-------------------------------------------------|
| Domain          | Core business rules (unit-test only)           |
| Infrastructure  | Persistence, network, push, analytics, etc.    |
| Presentation    | Unity 3-D dashboards & mini-games              |
| Application     | Use-case orchestration (MVVM ‑ ViewModel)      |

All contributions **must** respect this layering to avoid unwanted coupling.

---

## Prerequisites
| Tool | Version | Notes |
|------|---------|-------|
| Unity | ≥ 2022 LTS | Use the Hub to install with Android/iOS modules |
| .NET  | 7.0 SDK | `dotnet --version` should return 7.x               |
| Git   | ≥ 2.40  | LFS enabled (`git lfs install`)                    |
| IDE   | Rider / VS 2022 | `.editorconfig` enforced on save          |

Install dependencies:

```bash
git clone https://github.com/TycoonVerse/TycoonVerse.git
cd TycoonVerse
git submodule update --init --recursive
dotnet tool restore     # installs dotnet-format, reportgenerator, etc.
```

---

## Branching & Workflow
We follow **GitHub Flow** with a protected `main` branch:

```
main ←─ hotfix/*
        ↑
  release/*
        ↑
   develop ←─ feature/<ticket-id>-short-desc
```

1. **Create an Issue** if one does not already exist.  
2. **Branch** off `develop`:  
   `git checkout -b feature/TP-142-digital-wallet-redesign`.
3. **Commit** early & often (see convention below).  
4. **Push** and open a **Draft PR** to start CI and gather feedback.  
5. **Rebase** frequently to keep changes minimal.  
6. **Squash merge** once approvals & checks pass.

---

## Commit Message Convention
We enforce **Conventional Commits v1.0**.

Example:
```
feat(auth): add biometric fallback for devices without FaceID

Fallbacks to secure PIN after three failed attempts.
Closes TP-217.
```

| Type     | Scope (optional) | Description                               |
|----------|------------------|-------------------------------------------|
| feat     | inventory        | New feature                               |
| fix      | analytics        | Bug fix                                   |
| refactor | domain           | Internal code change (non-API)           |
| docs     | guides           | Documentation only                       |
| test     | supply-chain     | Adding or correcting tests               |
| chore    | ci               | Build process, tooling, dependencies     |

---

## Coding Standards
The project ships with `.editorconfig` & StyleCop rules.  
Run `dotnet format --verify-no-changes` before pushing.

General C# guidelines:

* **Nullable Reference Types** must be enabled (`<Nullable>enable</Nullable>`).
* Prefer `internal` over `public` unless required by another assembly.
* Use `async/await`; **never block** on async code (`.Result` / `.Wait()`).
* **Dependency Injection** via the built-in DI container (`ServiceCollection`).
* **SOLID** first; design to interfaces, not implementations.
* All public members require **XML doc comments**.

Example:

```csharp
namespace TycoonVerse.Domain.Inventory;

/// <summary>
/// Calculates landed cost of goods after shipping and tariffs.
/// Thread-safe, stateless.
/// </summary>
public interface ILandedCostCalculator
{
    Money Calculate(Money itemCost, Shipment shipment, Currency targetCurrency);
}

internal sealed class LandedCostCalculator : ILandedCostCalculator
{
    public Money Calculate(Money itemCost, Shipment shipment, Currency targetCurrency)
    {
        ArgumentNullException.ThrowIfNull(shipment);
        var freight = shipment.Weight * shipment.Shipper.RatePerKg;
        var duties  = TariffResolver.Resolve(itemCost, shipment);
        var total   = itemCost + freight + duties;

        return Exchange.Convert(total, targetCurrency);
    }
}
```

### Forbidden Patterns
🚫 Static mutable state  
🚫 Catch-all `try/catch` without logging  
🚫 `Debug.Log` in production code (use `ILogger`)  
🚫 Business logic in Unity MonoBehaviours

---

## Architecture Guidelines
The following patterns are used extensively and must be preserved:

* **Singleton**: Only for global adapters (e.g., `AnalyticsTracker.Instance`).
* **Repository Pattern**: Encapsulate data access; return domain entities, not DTOs.
* **Observer Pattern**: Decouple gameplay events from UI updates.
* **Adapter Pattern**: Wrap 3rd-party SDKs (IAP, biometrics, crash reporting).
* **Factory Pattern**: Instantiate domain aggregates; hide complex set-up.
* **MVVM**: All UI panels use ViewModel bindings (see `Assets/UI/ViewModels/`).

When adding new features, identify which layer & pattern fits best.
If unsure, open a design discussion in the issue first.

---

## Testing Strategy
We practice **TDD** where feasible.

* Test framework: **NUnit 3**  
* Coverage threshold: **80 %** (fail on CI below)  
* Use the **AAA pattern** (`Arrange-Act-Assert`)  
* Mocks/Stubs: **NSubstitute**  
* For randomness, inject an `IRandom` interface to ensure determinism.

Example test:

```csharp
[Test]
public void Calculate_NegativeCashFlow_ShouldTriggerBankruptcy()
{
    // Arrange
    var ledger = new Ledger();
    ledger.Record(new CashFlow(-1_000_000M));
    var observer = Substitute.For<IBankruptcyObserver>();

    var evaluator = new FinancialHealthEvaluator(observer);

    // Act
    evaluator.Evaluate(ledger);

    // Assert
    observer.Received(1).OnBankruptcy(Arg.Any<Company>());
}
```

Run the full test suite:

```bash
dotnet test --collect:"XPlat Code Coverage"
reportgenerator -reports:"**/coverage.cobertura.xml" -targetdir:coveragereport
open coveragereport/index.html
```

---

## Pull Request Checklist
Before requesting review, ensure:

- [ ] CI passes (`build`, `test`, `code-quality`)
- [ ] Code is self-documented; public APIs have XML docs
- [ ] New/changed APIs added to **Changelog**
- [ ] Unit & integration tests added/updated
- [ ] No debug logs or commented code
- [ ] No secrets or hard-coded API keys
- [ ] Screenshots/gifs for UI changes attached to PR
- [ ] Issue reference (`Closes #123`) included

---

## Issue Triage
Labels:

| Label        | Meaning                               |
|--------------|---------------------------------------|
| `bug`        | Unexpected malfunction                |
| `enhancement`| Improvement to existing feature       |
| `feature`    | Net-new functionality                 |
| `good first` | Suitable for newcomers                |
| `blocked`    | Waiting on external dependency        |
| `security`   | Vulnerability or sensitive topic      |

Triagers assign severity (`P0-P3`) and milestone (`v1.7`, `Backlog`).  
Security issues are **NEVER** discussed in public threads—email  
`security@tycoonverse.com`.

---

## Tooling & Automation
We use **GitHub Actions**. Key workflows:

* `ci.yml` – builds, tests, analyzes (SonarCloud + Coverlet)  
* `release.yml` – tags, creates GitHub Release, pushes to Unity Cloud Build  
* `dependabot.yml` – monthly NuGet & Unity-package updates  

Enable client-side hooks:

```bash
git config core.hooksPath .githooks
./.githooks/install.sh
```
Hooks run `dotnet format` and static analysis before each commit.

---

## Security & Sensitive Data
1. Never commit credentials; use **Unity Cloud Environment Variables** or
   `.env.local` (ignored by Git).
2. Report vulnerabilities privately:  
   `security@tycoonverse.com`, GPG key `0xA1B2C3D4`.
3. All cryptographic work must use **`System.Security.Cryptography`**
   or audited 3rd-party libs—no home-grown algorithms.

---

## Code of Conduct
We adhere to the **Contributor Covenant v2.1**.  
See [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md).

---

## License
By contributing, you agree that your code will be licensed under the
**MIT License** and that you have the right to license it.

Happy entrepreneuring! 🚀
```