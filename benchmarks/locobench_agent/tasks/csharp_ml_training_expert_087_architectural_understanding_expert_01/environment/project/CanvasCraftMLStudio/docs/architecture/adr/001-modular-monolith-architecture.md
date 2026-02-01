# 001 – Adopt a Modular-Monolith Architecture  
Status: Accepted  
Date: 2024-06-08  
Deciders: Core Architecture Working Group (CAWG)  
Supersedes: *n/a*  
Tags: [`architecture`](#), [`modular-monolith`](#), [`csharp`](#), [`mlops`](#)

---

## 1. Context  

CanvasCraft ML Studio is an end-to-end **MVC-driven MLOps platform** that targets creative professionals iterating on generative media.  
While the business road-map forecasts multiple deployment targets (desktop, on-prem, cloud, edge), the immediate product goals are:

* Rapid iteration on **feature-engineering palettes** and **hyper-parameter color-wheels**.  
* Tight coupling between **experiment-tracking**, **feature store**, and **model registry** to guarantee lineage.  
* A **reactive model-monitoring** feedback loop that must not fall out of sync with training pipelines.  
* A single deployable artifact that remains **operationally simple** yet **modular enough** to allow multiple teams (Data Science, UX, DevOps) to collaborate in parallel.

The team evaluated the following architectural styles:

| Candidate | Pros | Cons |
|-----------|------|------|
| Pure Micro-services | Independent deployability; granular scaling | YAGNI for current size; high operational overhead; transaction boundaries complicate ACID model registry |
| **Modular Monolith (Internal Hexagons)** | Clear module boundaries; performant in-process calls; single deployment unit | Requires discipline to avoid “big ball of mud”; limited horizontal scaling |
| Packaged Plugins (OSGi style) | Hot-swappable “brush” plugins; strict contracts | Added complexity to load/unload modules; less tooling in .NET ecosystem |
| Serverless Functions | Zero-management infra; pay-per-use for burst training jobs | Cold-start latency for interactive “gallery” UI; cross-function state management painful |

Given current **team size**, the **need for synchronous cross-module transactions** (e.g., dataset ↔ feature store ↔ model registry), and the **desire to postpone DevOps overhead** until usage patterns stabilize, we choose the **Modular Monolith**.

---

## 2. Decision  

We will build CanvasCraft ML Studio as a **C# 8/9, .NET 8** modular monolith with the following rules:

1. **Single Deployment Unit**  
   A single Docker container / process hosts all modules (Train, Serve, Monitor, UX, etc.).
2. **Explicit Module Boundaries**  
   Modules are organized under `/src/{BoundedContext}.{Module}` namespaces, compiled into **separate class libraries** referenced by a thin *Composition Root* (Web / gRPC Host).
3. **Internal Hexagonal Architecture** per module  
   Each module exposes its own:
   * `Application` layer (Use-Cases, CQRS commands/queries)  
   * `Domain` layer (Aggregates, Value Objects, Domain Events)  
   * `Infrastructure` layer (EF Core, Redis, Kafka, TensorRT, etc.)
4. **Public Contracts** *(C# interfaces + OpenAPI)*  
   Modules interact only via their `*.Contracts` assemblies to prevent direct reference leaks.
5. **Shared Kernel** kept minimal  
   Only cross-cutting primitives (e.g., `Result<T>`, `IEvent`, `IDomainNotification`) live here.
6. **Dependency Inversion through Internal DI Container**  
   All external dependencies are injected via `IServiceCollection` extensions located in each module’s `Infrastructure` layer.

---

## 3. Consequences  

### Positive  

* 🚀 **Velocity** – Teams commit to their modules without touching others; compile-time boundaries give rapid feedback.  
* 🔬 **Observability** – Since calls are in-process, **OpenTelemetry** tracing is cheap; back-pressure can be simulated with Polly policies.  
* 🗃️ **Transactional Integrity** – The feature store and model registry execute in the same ACID transaction when needed (e.g., using EF Core `IDbContextTransaction`).  
* 🛠️ **Gradual Extraction Path** – If a module’s load pattern grows, we can extract it into a micro-service by lifting its contract and infrastructure *without* rewriting domain code.

### Negative / Risks  

* 🏗️ **Discipline Required** – Nothing (besides CI linting) prevents developers from taking a rogue reference into another module’s `Infrastructure` assembly.  
* 📈 **Limited Horizontal Scaling** – The entire monolith scales as one unit. Mitigation: run multiple container replicas behind a load balancer.  
* 💼 **Deployment Blast Radius** – A change in any module triggers a full redeploy. Our blue-green pipeline must be robust.

---

## 4. Implementation Sketch  

### 4.1. Directory / Namespace Layout  

```
CanvasCraftMLStudio/
│
├── src/
│   ├── SharedKernel/
│   │   └── CanvasCraft.SharedKernel.csproj
│   ├── ExperimentTracking/
│   │   ├── Contracts/
│   │   ├── Domain/
│   │   ├── Application/
│   │   └── Infrastructure/
│   ├── FeatureEngineering/
│   │   └── ...
│   ├── ModelRegistry/
│   │   └── ...
│   ├── ServingGallery/
│   │   └── ...
│   └── WebHost/
│       └── CanvasCraft.WebHost.csproj
└── docs/
    └── architecture/
        └── adr/
            └── ...
```

### 4.2. Composition Root (simplified)

```csharp
// CanvasCraft.WebHost/Program.cs
using CanvasCraft.SharedKernel;
using CanvasCraft.ExperimentTracking.Infrastructure;
using CanvasCraft.FeatureEngineering.Infrastructure;
using CanvasCraft.ModelRegistry.Infrastructure;
using CanvasCraft.ServingGallery.Infrastructure;

var builder = WebApplication.CreateBuilder(args);
builder.Services
    .AddSharedKernel()
    .AddExperimentTrackingModule(builder.Configuration)
    .AddFeatureEngineeringModule(builder.Configuration)
    .AddModelRegistryModule(builder.Configuration)
    .AddServingGalleryModule(builder.Configuration);

builder.Services.AddControllers().AddNewtonsoftJson();

var app = builder.Build();
app.MapControllers();
app.Run();
```

### 4.3. Enforcing Boundaries via Roslyn Analyzer

A custom Roslyn analyzer (loaded in `Directory.Build.props`) blocks forbidden references:

```csharp
[DiagnosticAnalyzer(LanguageNames.CSharp)]
public sealed class NoInfrastructureLeakAnalyzer : DiagnosticAnalyzer
{
    private static readonly DiagnosticDescriptor Rule = new(
        id: "CCMS001",
        title: "No cross-module Infrastructure references",
        messageFormat: "Project '{0}' should not reference '{1}.Infrastructure'",
        category: "Architecture",
        defaultSeverity: DiagnosticSeverity.Error,
        isEnabledByDefault: true);

    public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics => ImmutableArray.Create(Rule);

    public override void Initialize(AnalysisContext context) =>
        context.RegisterCompilationStartAction(start =>
        {
            var infraProjects = start.Compilation.ReferencedAssemblyNames
                .Where(a => a.Name.EndsWith(".Infrastructure", StringComparison.Ordinal))
                .ToHashSet(StringComparer.Ordinal);

            start.RegisterSymbolAction(symbolContext =>
            {
                var assembly = symbolContext.Symbol.ContainingAssembly?.Name;
                if (assembly is null || !assembly.EndsWith(".Infrastructure"))
                {
                    foreach (var infra in infraProjects)
                    {
                        if (symbolContext.Compilation.AssemblyName == infra.ToString())
                            continue;

                        symbolContext.ReportDiagnostic(
                            Diagnostic.Create(Rule, Location.None, assembly, infra));
                    }
                }
            }, SymbolKind.NamedType);
        });
}
```

---

## 5. Alternatives Considered  

1. **Full Micro-Services** with gRPC & Kafka  
   *Rejected* – Over-engineering at current scale; slows feature velocity.  
2. **Serverless-First** using Azure Functions & Durable Orchestration  
   *Rejected* – Real-time “gallery” UI would suffer cold starts; local dev experience poor.  
3. **Plugin-Oriented (MEF) Desktop App**  
   *Rejected* – Conflicts with requirement for cloud-native CI/CD and containerization.

---

## 6. Validation Plan  

* Implement two pilot modules (**ExperimentTracking** and **FeatureEngineering**) under this architecture.  
* Run performance benchmark: ingest → transform → model fit; target < 250 ms overhead vs. baseline script.  
* Conduct *“design spike”* to extract ExperimentTracking into a micro-service after initial release and measure required refactor effort (< 8 story points target).  
* Audit module boundaries via the Roslyn analyzer in every PR.

---

## 7. References  

* “Monolith First” – Martin Fowler, 2015  
* “A Modular Monolith Architecture in .NET” – Khorikov, 2023  
* OpenTelemetry .NET Instrumentation Guidelines, v1.7  
* Domain-Driven Design Tackling Complexity in the Heart of Software – Evans, 2004  

---

*This document is living; amendments require a new ADR.*