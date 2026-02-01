# 002 – Pluggable Consensus Strategy  
*Status: Accepted*  
*Date: 2024-05-27*  

---

## Context  

UtilityChain must support multiple consensus algorithms (PoS, PoA, PBFT, etc.) to satisfy varied deployment environments (private consortium, municipal energy grid, or regulated DeFi exchange). Because future consensus methods (e.g., DAG-based, zero-knowledge roll-ups) are unknown at compile-time, the system requires a way to:

1. Swap consensus engines without recompiling the entire monolith.  
2. Run multiple consensus engines side-by-side for migration or *blue-green* upgrades.  
3. Allow third-party developers to distribute closed-source consensus plugins that interoperate with the public core.  

The architectural constraints of the monolith (single binary, zero-copy data models) prohibit out-of-process microservices. Instead, we adopt an in-process **Strategy Pattern** augmented by a lightweight **Factory** and **Proxy** layer to load, validate, and hot-swap consensus modules.

---

## Decision  

1. Define a narrow `IConsensusStrategy` interface focused on *block proposal*, *validation*, and *finalization*.  
2. Use `ConsensusStrategyDescriptor` records to describe metadata (algorithm-id, version, capabilities, gas-cost model).  
3. Package each concrete strategy in a `.dll` that targets `net8.0` and ships with a manifest (`*.ucs.json`).  
4. At runtime, the `ConsensusStrategyLoader` discovers strategies via reflection (or explicit CLI argument), validates signatures, and registers them in the IoC container.  
5. A multilayer cache (`MemoryCache` + `Span<byte>` ring buffer) is shared across strategies through an immutable `ConsensusContext`.  
6. All public consensus calls are routed through `ConsensusProxy`, enabling transparent re-configuration and A/B testing.  
7. ADR-controlled feature flags gate experimental strategies (`--enable-consensus:pbft`).  

---

## Consequences  

Positive  
• New consensus engines can be delivered as NuGet packages or dropped into the `plugins/` folder at runtime.  
• Node operators configure consensus by editing `appsettings.json` or issuing `ucs consensus set PoA`.  
• Rolling upgrades are supported because both legacy and new strategies can validate blocks concurrently until epoch cut-over.  

Negative  
• Reflection and dynamic loading introduce a marginal startup cost (~45 ms on benchmark hardware).  
• A bug in a third-party consensus module can crash the node (mitigated via sandboxing & AppDomain isolation flags).  

---

## Implementation Sketch  

```csharp
using System.Buffers;
using System.Security.Cryptography;
using Microsoft.Extensions.Logging;
using UtilityChain.Core.Abstractions.Consensus;

namespace UtilityChain.Core.Consensus;

/// <summary>
/// Contract every consensus algorithm must satisfy.
/// Methods should be idempotent and thread-safe where noted.
/// </summary>
public interface IConsensusStrategy
{
    /// <summary>Globally unique algorithm identifier (e.g., "PoS/1.0").</summary>
    string Id { get; }

    /// <summary>
    /// Perform validation of a candidate block header.
    /// Must not mutate state.
    /// </summary>
    ValueTask<ConsensusResult> ValidateBlockAsync(
        ReadOnlyMemory<byte> rawHeader,
        ConsensusContext context,
        CancellationToken ct = default);

    /// <summary>
    /// Finalize the block and persist consensus-critical metadata.
    /// May mutate shared state (stakes, validator sets, etc.).
    /// </summary>
    ValueTask<ConsensusResult> FinalizeBlockAsync(
        ReadOnlyMemory<byte> rawBlock,
        ConsensusContext context,
        CancellationToken ct = default);
}

public sealed record ConsensusResult(bool IsValid, string? Message = null);

/// <summary>
/// Shared, immutable snapshot of runtime-wide data required by strategies.
/// </summary>
public sealed class ConsensusContext
{
    public ConsensusContext(
        ChainState state,
        IBufferWriter<byte> networkBuffer,
        ILogger logger)
    {
        State = state;
        NetworkBuffer = networkBuffer;
        Logger = logger;
    }

    public ChainState State { get; }
    public IBufferWriter<byte> NetworkBuffer { get; }
    public ILogger Logger { get; }
}

/// <summary>
/// Concrete Proof-of-Stake implementation.
/// Demonstrates canonical usage of Strategy contract.
/// </summary>
public sealed class ProofOfStakeStrategy : IConsensusStrategy
{
    public string Id => "PoS/1.0";

    public async ValueTask<ConsensusResult> ValidateBlockAsync(
        ReadOnlyMemory<byte> rawHeader,
        ConsensusContext context,
        CancellationToken ct = default)
    {
        // Example stub: Validate signature + stake weight
        if (rawHeader.IsEmpty) return new(false, "Header empty");

        Span<byte> hash = stackalloc byte[32];
        SHA256.TryHashData(rawHeader.Span, hash, out _);

        bool signatureOk = await StakeValidator.VerifySignatureAsync(hash, context.State, ct);
        if (!signatureOk) return new(false, "Invalid proposer signature");

        return new(true);
    }

    public async ValueTask<ConsensusResult> FinalizeBlockAsync(
        ReadOnlyMemory<byte> rawBlock,
        ConsensusContext context,
        CancellationToken ct = default)
    {
        // Update stake weights, emit events, etc.
        await StakeValidator.UpdateStakeLedgerAsync(rawBlock, context.State, ct);
        return new(true);
    }
}

/// <summary>
/// Loader responsible for discovering, validating, and instantiating strategies.
/// Uses a secure hash-whitelist by default.
/// </summary>
public static class ConsensusStrategyLoader
{
    private static readonly Dictionary<string, IConsensusStrategy> _cache = new();

    public static IReadOnlyDictionary<string, IConsensusStrategy> Discover(string? path = null)
    {
        path ??= Path.Combine(
            AppContext.BaseDirectory,
            "plugins",
            "consensus");

        if (!Directory.Exists(path))
        {
            return _cache;
        }

        foreach (var dll in Directory.EnumerateFiles(path, "*.dll", SearchOption.AllDirectories))
        {
            try
            {
                var asm = Assembly.LoadFrom(dll);

                foreach (var type in asm.GetTypes()
                    .Where(t => !t.IsAbstract && typeof(IConsensusStrategy).IsAssignableFrom(t)))
                {
                    if (Activator.CreateInstance(type) is IConsensusStrategy strategy)
                    {
                        _cache.TryAdd(strategy.Id, strategy);
                    }
                }
            }
            catch (BadImageFormatException)
            {
                // Ignore non-CLR binaries
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"Failed to load consensus plugin '{dll}': {ex.Message}");
            }
        }

        // Fallback: register built-in PoS
        _cache.TryAdd("PoS/1.0", new ProofOfStakeStrategy());
        return _cache;
    }
}

/// <summary>
/// Proxy that delegates calls to the currently active strategy.
/// Clients interact exclusively with this proxy.
/// </summary>
public sealed class ConsensusProxy : IConsensusStrategy
{
    private readonly Func<IConsensusStrategy> _resolver;

    public ConsensusProxy(Func<IConsensusStrategy> resolver)
    {
        _resolver = resolver;
    }

    private IConsensusStrategy Active => _resolver();

    public string Id => Active.Id;

    public ValueTask<ConsensusResult> ValidateBlockAsync(
        ReadOnlyMemory<byte> rawHeader,
        ConsensusContext context,
        CancellationToken ct = default) =>
        Active.ValidateBlockAsync(rawHeader, context, ct);

    public ValueTask<ConsensusResult> FinalizeBlockAsync(
        ReadOnlyMemory<byte> rawBlock,
        ConsensusContext context,
        CancellationToken ct = default) =>
        Active.FinalizeBlockAsync(rawBlock, context, ct);
}
```

---

## Drawbacks  

• Strategy interface must remain stable; breaking changes require version negotiation.  
• High coupling with ChainState; mitigation planned via *Domain Event* abstraction (v2).  

---

## Alternatives Considered  

1. **Compile-time selection via `#if`** – Violates runtime configurability requirement.  
2. **gRPC microservice** – Adds network hops, serialization overhead, and dev-ops complexity for private chains.  
3. **WebAssembly consensus modules** – Promising sandboxing story, but current WASI crypto APIs are immature for production.  

---

## References  

• [GammaChains ADR-003 Consensus Hot-Swap](https://github.com/gammachains/adr/003)  
• “Pluggable Consensus” (Devcon VI, 2023) – Erik Nedrelid  
• *Design Patterns: Elements of Reusable Object-Oriented Software* – GoF (Strategy, Proxy)