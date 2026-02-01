```markdown
# TycoonVerse: Enterprise Empire Simulator (Mobile Game)
_A deep‐dive, enterprise-grade business simulator built entirely in C# and Unity_

![TycoonVerse Banner](./.assets/banner.png)

---

## Table of Contents
1. [Executive Summary](#executive-summary)  
2. [Quick Start](#quick-start)  
3. [Architecture](#architecture)  
   1. [High-Level Diagram](#high-level-diagram)  
   2. [Layered Breakdown](#layered-breakdown)  
4. [Project Layout](#project-layout)  
5. [Core Patterns](#core-design-patterns)  
6. [Local Development](#local-development)  
7. [Domain Code Snippets](#domain-code-snippets)  
8. [Offline Sync](#offline-sync)  
9. [Telemetry & Analytics](#telemetry--analytics)  
10. [Security Practices](#security-practices)  
11. [Contribution Guide](#contribution-guide)  
12. [Troubleshooting](#troubleshooting)  
13. [License](#license)  

---

## Executive Summary
TycoonVerse is a high-fidelity business simulation that treats gameplay as a live enterprise SaaS.  
Players establish and scale companies across multiple industries, reacting to real-world events (logistics, weather, and macro-economics) in real time.

Key highlights:
- **Deterministic Offline Play** – full gameplay is available without network; a CRDT-inspired sync engine reconciles state once connectivity returns.  
- **Enterprise-Grade Security** – biometric sign-in, encrypted wallets, and GDPR/CCPA compliance baked in.  
- **Flexible Monetization** – remote-configurable in-app purchase catalog with A/B analytics.  
- **Extensible Architecture** – MVVM + DDD core with adapters for Unity, SQLite, and external telemetry.

---

## Quick Start
1. Clone the repository:
   ```bash
   git clone https://github.com/TycoonVerse/TycoonVerse.git
   cd TycoonVerse
   ```

2. Unity (2022 LTS) will auto-import the project.  
   Make sure you have:
   - .NET SDK 7.0  
   - Unity Hub with Android/iOS build support  

3. Build & run unit tests:
   ```bash
   dotnet test
   ```

4. Launch the game in Unity (`File → Build & Run`) or via CLI:
   ```bash
   unity -projectPath . -executeMethod BuildCLI.RunAndroidDebug
   ```

---

## Architecture

### High-Level Diagram
```mermaid
graph TD
  subgraph Presentation (Unity)
      UI[MVVM Views] --> VM[View Models]
  end
  subgraph Domain
      VM -->|Commands| AppSvc[Application Services]
      AppSvc --> Aggregate[Aggregates & ValueObjects]
      Aggregate --> Rules[Domain Rules]
  end
  subgraph Infrastructure
      AppSvc --> Repo[Repositories]
      Repo --> DB[(SQLite)]
      Repo --> Sync[SyncEngine]
      AppSvc --> Telemetry[AnalyticsAdapter]
      AppSvc --> Auth[BiometricAuthAdapter]
  end
  subgraph External
      Cloud[(Cloud Store)]
      TeleTelemetry[Telemetry API]
  end
  Sync -->|Push/Pull| Cloud
  Telemetry --> TeleTelemetry
```

### Layered Breakdown
- **Presentation** – Unity Scene hierarchy, MVVM binding to ScriptableObjects.
- **Domain** – Pure C# (no Unity types) with DDD aggregates: `Company`, `Market`, `Product`, etc.
- **Infrastructure** – Data persistence (SQLite), platform services (biometrics, notifications), and network sync.
- **Cross-Cutting** – Logging, configuration, exception handling, and crash reporting.

---

## Project Layout
```text
TycoonVerse/
 ├─ Assets/
 │  ├─ Scripts/
 │  │  ├─ Presentation/
 │  │  ├─ Domain/
 │  │  ├─ Infrastructure/
 │  │  └─ CrossCutting/
 │  └─ Addressables/
 ├─ Build/
 ├─ Docs/
 │  ├─ Architecture.md
 │  └─ README.md   ← you are here
 ├─ Tests/
 └─ TycoonVerse.sln
```

---

## Core Design Patterns
- **Singleton** – `GameContext` provides service location during bootstrap.
- **Observer Pattern** – Reactive event bus (`DomainEventDispatcher`) connects sub-systems.
- **Repository Pattern** – Abstracts data storage (`ICompanyRepository`, `ISyncRepository`).
- **Adapter Pattern** – Bridges Unity/Android/iOS platform APIs (e.g., `IBiometricAdapter`).
- **Factory Pattern** – Runtime creation of domain aggregates from persisted DTOs.
- **MVVM** – Decouples Unity UI from game logic using `UniRx`.

---

## Local Development

### Coding Conventions
- C# 10, nullable reference types enabled (`<Nullable>enable</Nullable>`).
- Async APIs follow `Try`/`Ensure` guard clauses and return `Task`.
- Domain objects are **immutable**; state changes via `Apply(Event)`.

### Environment Variables
| Variable               | Purpose                    | Default              |
|------------------------|----------------------------|----------------------|
| `TV_ENV`               | `dev`, `staging`, `prod`   | `dev`                |
| `TV_ANALYTICS_KEY`     | Analytics ingestion token  | (local stub)         |
| `TV_CRASH_KEY`         | Crash reporting DSN        | (local stub)         |

---

## Domain Code Snippets

### `Company` Aggregate Root
```csharp
namespace TycoonVerse.Domain.Aggregates.CompanyAggregate;

/// <summary>
/// Aggregate root representing a player's company portfolio.
/// </summary>
public sealed class Company : AggregateRoot<Guid>
{
    private readonly List<Subsidiary> _subsidiaries = new();

    public Company(Guid id, string name, Money seedCapital)
    {
        Id = id;
        Name = name;
        SeedCapital = seedCapital;

        RaiseDomainEvent(new CompanyCreatedDomainEvent(id));
    }

    public string Name { get; }
    public Money SeedCapital { get; }

    public IReadOnlyCollection<Subsidiary> Subsidiaries => _subsidiaries.AsReadOnly();

    public void AddSubsidiary(Subsidiary subsidiary)
    {
        Guard.Against.Null(subsidiary);

        _subsidiaries.Add(subsidiary);
        RaiseDomainEvent(new SubsidiaryAddedDomainEvent(Id, subsidiary.Id));
    }
}
```

### Repository Sample
```csharp
namespace TycoonVerse.Infrastructure.Persistence.Repositories;

internal sealed class CompanyRepository : ICompanyRepository
{
    private readonly IDbConnection _connection;
    private readonly IJsonSerializer _serializer;

    public CompanyRepository(IDbConnection connection, IJsonSerializer serializer)
    {
        _connection = connection;
        _serializer = serializer;
    }

    public async Task<Company?> GetAsync(Guid id, CancellationToken ct = default)
    {
        const string sql = "SELECT Data FROM Company WHERE Id = @Id LIMIT 1;";
        var json = await _connection.QuerySingleOrDefaultAsync<string>(sql, new { Id = id }, cancellationToken: ct);
        return json is null ? null : _serializer.Deserialize<CompanyDto>(json)!.ToDomain();
    }

    public async Task SaveAsync(Company company, CancellationToken ct = default)
    {
        const string sql = "INSERT OR REPLACE INTO Company (Id, Data) VALUES(@Id, @Data);";
        var dto = CompanyDto.FromDomain(company);
        var json = _serializer.Serialize(dto);
        await _connection.ExecuteAsync(sql, new { company.Id, Data = json }, cancellationToken: ct);
    }
}
```

### View-Model Example
```csharp
public sealed class CashFlowViewModel : ReactiveObject
{
    private readonly ICompanyRepository _repo;
    private readonly ObservableAsPropertyHelper<decimal> _ebitda;

    public CashFlowViewModel(ICompanyRepository repo)
    {
        _repo = repo;

        _ebitda = Observable.Timer(TimeSpan.Zero, TimeSpan.FromSeconds(5))
                            .SelectMany(_ => Load())
                            .ToProperty(this, vm => vm.EBITDA);
    }

    public decimal EBITDA => _ebitda.Value;

    private async Task<decimal> Load()
    {
        var company = await _repo.GetAsync(GameContext.CurrentPlayer.CompanyId);
        return company?.CalculateEBITDA() ?? 0m;
    }
}
```

---

## Offline Sync
TycoonVerse employs a deterministic **CRDT-augmented event log** to reconcile offline progress.

Flow:
1. Commands are timestamped and appended to a local `CommandLog.sqlite`.
2. During offline, game state is mutated locally.
3. When connectivity returns, `SyncEngine` pushes the delta log to the server.
4. Server acknowledges order; conflicting events are resolved using vector clocks.
5. Confirmed canonical log is replayed locally to ensure determinism.

### Sync Pseudocode
```csharp
public async Task SyncAsync(CancellationToken ct = default)
{
    var pending = await _log.ReadPendingAsync(ct);

    foreach (var batch in pending.Batch(50))
    {
        var response = await _api.PushAsync(batch, ct);
        if (!response.IsSuccess) throw new SyncException(response.Error);

        await _log.MarkAsSyncedAsync(batch, response.ServerTimestamps, ct);
        await _replayer.ReplayAsync(batch, ct);
    }
}
```

---

## Telemetry & Analytics
All significant domain events pass through `IDomainEventDispatcher` and are mirrored to the telemetry layer via an observer:

```csharp
public sealed class AnalyticsDomainObserver : IDomainEventObserver
{
    private readonly IAnalyticsClient _client;

    public async Task OnDomainEventAsync(DomainEvent evt, CancellationToken ct = default)
    {
        var payload = AnalyticsMapper.Map(evt);
        await _client.TrackAsync(payload, ct);
    }
}
```

Opt-in sampling (`0.05` default) is enforced to manage traffic.

---

## Security Practices

1. **Biometric Gate** – `IBiometricAdapter` wraps `AndroidX.Biometric` & `LocalAuthentication` on iOS.  
2. **Wallet Encryption** – ChaCha20-Poly1305, keys stored in Secure Enclave / Keystore.  
3. **Compliance** – Data retention policies align with GDPR Art. 17 & CCPA §1798.105.

---

## Contribution Guide

1. Fork & create a feature branch (`feat/your-feature`).
2. Respect project structure and naming (`PascalCase`, singular class names).
3. All PRs require:
   - Unit tests `dotnet test`
   - Static analysis `dotnet format`
   - CI green badge (`GitHub Actions → build.yml`)

Check the [CONTRIBUTING.md](./CONTRIBUTING.md) for full details.

---

## Troubleshooting

| Symptom                            | Resolution                                  |
|-----------------------------------|---------------------------------------------|
| `SqliteException: Disk I/O Error` | Verify device storage and re-deploy build.  |
| `SyncException: Vector clock ...` | Clear local cache: _Settings → Reset Data_. |
| High battery usage on Android     | Ensure **Battery Saver Mode** is disabled, and run the latest release build (debug builds are unoptimized). |

---

## License
TycoonVerse is released under the Apache 2.0 License.  
© 2024 Algorithmic Playground Studios. All rights reserved.
```