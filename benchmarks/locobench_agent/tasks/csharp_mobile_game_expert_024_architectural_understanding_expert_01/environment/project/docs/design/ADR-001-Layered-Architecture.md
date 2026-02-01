```markdown
# ADR-001: Layered Architecture

*Status*          | **Accepted**
------------------|---------------
*Date*            | 2024-06-01
*Decision Makers* | @core-arch, @lead-gameplay, @infra-ops
*Tech Stack*      | C# 11, Unity 2023 LTS, SQLite, Azure App Services
*Review Cycle*    | Evaluate every major version (v1.0, v2.0, …)

---

## 1. Context & Problem Statement  

TycoonVerse is both a **mobile game** and a **financial simulation platform**.  
We must:

1. Evolve rules (tax, IPO, ESG) without recompiling UI.
2. Support **offline-first** and later sync to cloud.
3. Integrate regulated features (biometric wallet, IAP) while staying compliant.
4. Enable **A/B experimentation** at feature level (analytics, monetization).

A monolithic code-base couples Unity views to business rules, making changes brittle and increasing risk for exploits/cheats. We need a structure that enforces **separation of concerns, testability, and mod-ability**.

---

## 2. Decision

Adopt a **4-Layered, Hexagon-inspired** architecture:

```
┌─────────────────────────────┐
│        Presentation         │ ← Unity, UI Toolkit
├─────────┬─────────┬─────────┤
│Application|Domain |Scripting│ ← Use-cases, Domain Model, Lua modding
├─────────┴─────────┴─────────┤
│       Infrastructure        │ ← SQLite, REST, Push, Telemetry
└─────────────────────────────┘
```

Key rules:

1. Lower layers **never reference** upper ones (Dependency Inversion).
2. Cross-layer comms via **contracts** (interfaces, DTOs, events).
3. **Unity** hosts only Presentation; gameplay data never touches `MonoBehaviour`.
4. **Domain layer is pure C#** (no UnityEngine), enabling deterministic tests.
5. **Infrastructure** implements ports (repositories, gateways) and is swapped for mocks in tests.

---

## 3. Drivers

* Deterministic offline simulation (seedable RNG, rollback).
* App-store compliance: update binary rarely, deliver content via data.
* Hot-patch economy parameters from back-end without breaking saves.
* Reduce start-up time by lazy-loading Infrastructure.

---

## 4. Considered Options

Option                             | Description                                   | Notes
----------------------------------|-----------------------------------------------|------
1. Tight Unity MVC                | Everything in scenes                          | Fast prototype, poor scaling
2. ECS-only (DOTS)                | High perf, learning curve                     | Not stable on iOS/Android yet
3. **Layered / Hexagonal** (✔)    | Ports-and-Adapters, DTOs, Domain events       | Best balance

---

## 5. Decision Outcome

We select **Option 3**.  
All new packages follow this folder/asmdef layout:

```
TycoonVerse
 ├─ Presentation/        (Unity asmdef: TycoonVerse.Presentation)
 ├─ Application/         (TycoonVerse.Application)
 ├─ Domain/              (TycoonVerse.Domain)
 └─ Infrastructure/
     ├─ Local/           (TycoonVerse.Infrastructure.Local)
     ├─ Remote/          (TycoonVerse.Infrastructure.Remote)
     └─ … 
```

Cross-package dependencies:

```
Presentation → Application → Domain
Infrastructure → Domain
```

---

## 6. Example Code Contracts

### 6.1 Domain

```csharp
namespace TycoonVerse.Domain.Finance
{
    public sealed record Money(decimal Amount, string Currency);

    public interface IClock
    {
        DateTime UtcNow { get; }
    }

    public class CashLedger
    {
        private readonly IClock _clock;
        private readonly List<LedgerEntry> _entries = new();

        public CashLedger(IClock clock) => _clock = clock;

        public void Debit(Money amount, string reason)
        {
            if (amount.Amount <= 0) throw new ArgumentOutOfRangeException(nameof(amount));
            _entries.Add(new LedgerEntry(-amount.Amount, reason, _clock.UtcNow));
        }

        // …
    }

    internal record LedgerEntry(decimal Delta, string Reason, DateTime Timestamp);
}
```

### 6.2 Application (Use-Case)

```csharp
namespace TycoonVerse.Application.Finance.Commands
{
    public record PurchaseInventory(Guid CompanyId, Money Amount, string Description);

    public class PurchaseInventoryHandler
    {
        private readonly ICompanyRepository _repo;
        private readonly IClock _clock;
        private readonly IEventBus _bus;

        public PurchaseInventoryHandler(ICompanyRepository repo, IClock clock, IEventBus bus)
            => (_repo, _clock, _bus) = (repo, clock, bus);

        public async Task HandleAsync(PurchaseInventory cmd, CancellationToken token)
        {
            var company = await _repo.LoadAsync(cmd.CompanyId, token);
            company.Ledger.Debit(cmd.Amount, cmd.Description);

            await _repo.SaveAsync(company, token);
            await _bus.PublishAsync(new InventoryPurchased(cmd.CompanyId, cmd.Amount, _clock.UtcNow), token);
        }
    }
}
```

### 6.3 Infrastructure (SQLite Adapter)

```csharp
namespace TycoonVerse.Infrastructure.Local.Repositories
{
    internal sealed class SqliteCompanyRepository : ICompanyRepository
    {
        private readonly SqliteConnection _conn;
        private readonly JsonSerializerOptions _jsonOptions = new() { WriteIndented = false };

        public SqliteCompanyRepository(string dbPath)
        {
            _conn = new SqliteConnection($"Data Source={dbPath}");
            _conn.Open();
        }

        public async Task<Company> LoadAsync(Guid id, CancellationToken ct)
        {
            const string sql = "SELECT payload FROM companies WHERE id = @id";
            await using var cmd = _conn.CreateCommand();
            cmd.CommandText = sql;
            cmd.Parameters.AddWithValue("@id", id.ToString());

            var payload = (string?)await cmd.ExecuteScalarAsync(ct);
            if (payload is null)
                throw new DataException($"Company {id} not found.");

            return JsonSerializer.Deserialize<Company>(payload, _jsonOptions)
                   ?? throw new DataException("Deserialization failed.");
        }

        public async Task SaveAsync(Company company, CancellationToken ct)
        {
            const string upsert = """
            INSERT INTO companies (id, payload) VALUES (@id, @payload)
            ON CONFLICT(id) DO UPDATE SET payload = @payload;
            """;

            var json = JsonSerializer.Serialize(company, _jsonOptions);
            await using var cmd = _conn.CreateCommand();
            cmd.CommandText = upsert;
            cmd.Parameters.AddWithValue("@id", company.Id.ToString());
            cmd.Parameters.AddWithValue("@payload", json);
            await cmd.ExecuteNonQueryAsync(ct);
        }
    }
}
```

---

## 7. Consequences

Positive:
* Unit tests run without Unity runtime (headless CI).
* Mod-ders can script against Domain DTOs safely.
* Hot-swap Infrastructure (e.g., switch from SQLite to Mongo) with minimal code change.

Negative:
* More boilerplate (DTOs, mappers).
* Steeper onboarding for typical game devs.

---

## 8. Future Work

1. Introduce **Mediator** for decoupled command routing.
2. Evaluate IL weaving to auto-generate mapping code.
3. Package Domain as *NuGet* to enable external simulation servers.

---

## 9. References

* [Alistair Cockburn, Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/)
* [Unity Assembly Definition Guidelines](https://docs.unity3d.com/Manual/ScriptCompilationAssemblyDefinitionFiles.html)
* ADR format inspired by [Michael Nygard](http://thinkrelevance.com/blog/2011/11/15/documenting-architecture-decisions)
```