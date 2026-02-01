```markdown
# Architecture Decision Record: ADR 003  
## Title: .NET Stack Selection for CanvasCraft ML Studio  
**Status:** Accepted  
**Date:** 2024-06-11  
**Authors:** CanvasCraft ML Studio Core Engineering Team  

---

## 1. Context  

CanvasCraft ML Studio is an MVC-driven machine-learning authoring suite focused on creative experimentation, rapid iteration, and high-fidelity visualization of generative models.  
Key non-functional requirements drive the choice of runtime and libraries:

| Requirement                         | Rationale                                                                                  |
|------------------------------------|--------------------------------------------------------------------------------------------|
| Cross-platform desktop & server    | Artists may run local experiments on macOS/Windows while the MLOps backend runs in Linux. |
| High-performance numerical compute | Large tensor operations and real-time 3-D rendering require native-level performance.      |
| First-class GUI tooling            | Designers expect polished UI/UX; WPF/WinUI/MAUI are desirable options.                     |
| Mature web API & micro-services    | The experiment-tracking backend must expose secure REST/gRPC endpoints.                    |
| Dependency Injection & Modularity  | Pipeline, Strategy, and Factory patterns must plug-and-play at runtime.                    |
| Long-term ecosystem stability      | OSS packages, cloud support, and LTS versioning are mandatory for production.              |

We evaluated four candidate stacks:

| # | Stack                                          | Pros                                                                                         | Cons                                                                            |
|---|------------------------------------------------|----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| 1 | Python + FastAPI + PyTorch                      | ML ecosystem dominance; great community                                                      | GUI story weak; sluggish for large UI; packaging headaches on Windows/macOS     |
| 2 | Node.js + Electron + TensorFlow.js              | Web-native, quick prototyping                                                                | Heavy memory footprint; poor native hardware acceleration                       |
| 3 | Rust + Tauri + candle/ndarray                   | Near-bare-metal performance; small binaries                                                  | Immature ML ecosystem; steep learning curve; limited Windows GUI maturity       |
| 4 | **.NET 7/8 + ASP.NET Core + ONNX Runtime + MAUI** | Cross-platform, high-perf JIT + AOT; robust DI; hot-reload; strong IDE tooling; C# 12 modern | Slightly smaller ML OSS community; new MAUI UI stack is still evolving          |

## 2. Decision  

We will adopt **Stack #4 (.NET 7/8)** as the official runtime for both the desktop composer and the cloud-native backend services.

Key elements:

1. Runtime & Language  
   • .NET 8 LTS (C# 12, F# 8)  
2. Model Training & Inference  
   • ONNX Runtime with GPU/EPU acceleration  
   • Tensor primitives via `System.Numerics.Tensors` and `Microsoft.ML` for classic tasks  
3. Application Layers  
   • MVC pattern using ASP.NET Core MVC (server) and MAUI (desktop/mobile)  
4. Dependency Injection & Hosting  
   • `Microsoft.Extensions.Hosting` Generic Host for unified lifecycle (worker, web, CLI)  
5. Plugin Architecture  
   • `System.Composition` (MEF) + Reflection.Emit for runtime-loaded “brushes” (Strategies)  
6. Observability  
   • OpenTelemetry instrumentation via `OpenTelemetry.Extensions.Hosting`  

## 3. Detailed Solution Sketch  

Below is a trimmed production-grade sample demonstrating how CanvasCraft registers Pipeline “brushes” (pre-processing strategies) using `IHost`, DI scopes, and reflection-based discovery.

```csharp
using System.Composition.Hosting;
using System.Reflection;
using CanvasCraft.Pipeline;
using CanvasCraft.Pipeline.Brushes;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Bootstrap;

public static class Program
{
    public static async Task Main(string[] args)
    {
        using IHost host = Host.CreateDefaultBuilder(args)
            .ConfigureLogging(logging =>
            {
                logging.ClearProviders()
                       .AddConsole()
                       .AddDebug();
            })
            .ConfigureServices((ctx, services) =>
            {
                // Core services
                services.AddPipelineCore();
                services.AddFeatureStore(ctx.Configuration);
                services.AddOpenTelemetryTracing();

                // Dynamically compose brushes via MEF
                var configuration = new ContainerConfiguration()
                    .WithAssembly(typeof(AbstractBrush).Assembly)
                    .WithAssemblies(DiscoverBrushAssemblies());

                using var container = configuration.CreateContainer();
                foreach (var brush in container.GetExports<IBrush>())
                    services.AddSingleton(typeof(IBrush), brush);

                // Hosted worker for retraining loop
                services.AddHostedService<ModelRetrainWorker>();
            })
            .Build();

        try
        {
            await host.RunAsync();
        }
        catch (Exception ex)
        {
            host.Services.GetRequiredService<ILoggerFactory>()
                .CreateLogger("Bootstrap")
                .LogCritical(ex, "Fatal error—host terminated unexpectedly.");
        }
    }

    // Discover plugin assemblies in ./plugins directory
    private static IEnumerable<Assembly> DiscoverBrushAssemblies()
    {
        var pluginPath = Path.Combine(AppContext.BaseDirectory, "plugins");
        if (!Directory.Exists(pluginPath))
        {
            yield break;
        }

        foreach (var dll in Directory.EnumerateFiles(pluginPath, "*.Brush.dll", SearchOption.AllDirectories))
        {
            Assembly? assembly = null;
            try
            {
                assembly = Assembly.LoadFrom(dll);
            }
            catch (Exception e)
            {
                Console.Error.WriteLine($"Failed to load plugin {dll}: {e.Message}");
            }

            if (assembly != null)
                yield return assembly;
        }
    }
}
```

The corresponding `IBrush` contract and a sample implementation that normalizes pixel data:

```csharp
namespace CanvasCraft.Pipeline.Brushes;

/// <summary>
/// Represents a modular pre-processing strategy (“brush”) that can be swapped at runtime.
/// </summary>
public interface IBrush
{
    string Name { get; }

    /// <summary>
    /// Applies the transformation on the provided input tensor.
    /// </summary>
    Tensor<float> Stroke(Tensor<float> input, BrushContext context);
}

public sealed class PixelNormalizeBrush : AbstractBrush
{
    public override string Name => "PixelNormalize";

    public override Tensor<float> Stroke(Tensor<float> input, BrushContext context)
    {
        // Min-Max normalisation [0,1]
        return (input - context.Min) / (context.Max - context.Min + 1e-8f);
    }
}
```

This sample highlights production practices:

• Generic Host for consistent startup path (CLI, worker, web).  
• Async `Main` with `await` to avoid sync-over-async deadlocks.  
• Structured logging with fallback error handling.  
• MEF-based discovery enabling zero-downtime brush hot-swap.  

## 4. Consequences  

• **Pros**  
  – Single language across backend, desktop, mobile, and web (Blazor).  
  – First-class tooling (Rider, VS Code, Visual Studio) accelerates onboarding.  
  – AOT compilation yields native binaries for lightweight edge deployments.  
  – Managed memory, but span-based APIs allow near-C performance for heavy tensor ops.  

• **Cons**  
  – Some cutting-edge academic libraries are Python-only; we will expose a gRPC bridge for interoperability.  
  – Developers unfamiliar with .NET may require ramp-up.  

• **Mitigations**  
  – Provide Docker images that encapsulate full toolchain to ease adoption.  
  – Maintain polyglot micro-services to leverage Python/Rust for exotic research spikes.  

## 5. References  

1. Microsoft Learn: [.NET 8 Performance Improvements](https://learn.microsoft.com/dotnet/whats-new/dotnet-8)  
2. ONNX Runtime: [High-Performance Scoring on GPU](https://onnxruntime.ai/)  
3. ADR methodology: [Michael Nygard, “Documenting Architecture Decisions”](http://thinkrelevance.com/blog/2011/11/15/documenting-architecture-decisions)  

---
© 2024 CanvasCraft ML Studio – All rights reserved
```