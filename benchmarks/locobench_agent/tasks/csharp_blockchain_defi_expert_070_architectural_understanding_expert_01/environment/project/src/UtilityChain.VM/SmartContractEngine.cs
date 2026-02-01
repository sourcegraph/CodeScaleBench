```csharp
// -----------------------------------------------------------------------------
//  UtilityChain Core Suite (blockchain_defi) – SmartContractEngine
// -----------------------------------------------------------------------------
//  File:      UtilityChainCoreSuite/src/UtilityChain.VM/SmartContractEngine.cs
//  Project:   UtilityChain Core Suite
//  Language:  C# 12 / .NET 8
//
//  Description:
//      Event-driven smart-contract engine that validates, loads, and executes
//      contract code via pluggable execution strategies (CLR, WASM, etc.).
//      It exposes lifecycle events, gas metering, and an observer pipeline
//      that downstream modules (consensus, governance, wallet UI) can plug into.
// -----------------------------------------------------------------------------

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.Loader;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.CodeAnalysis.CSharp.Scripting;
using Microsoft.CodeAnalysis.Scripting;

namespace UtilityChain.VM
{
    #region Public Engine API

    /// <summary>
    /// Primary façade responsible for validating and executing smart-contracts.
    /// Internally delegates to strategy implementations that encapsulate
    /// environment-specific execution (e.g., CLR, WASM, EVM).
    /// </summary>
    public sealed class SmartContractEngine
    {
        private readonly ExecutionStrategyFactory _strategyFactory;
        private readonly ConcurrentBag<IContractExecutionObserver> _observers = new();

        public event EventHandler<ContractEventArgs>? ContractLoaded;
        public event EventHandler<ContractEventArgs>? ExecutionStarted;
        public event EventHandler<ExecutionCompletedEventArgs>? ExecutionCompleted;
        public event EventHandler<ExecutionFailedEventArgs>? ExecutionFailed;

        public SmartContractEngine(ExecutionStrategyFactory? strategyFactory = null)
        {
            _strategyFactory = strategyFactory ?? new ExecutionStrategyFactory();
        }

        /// <summary>
        /// Registers an observer that will receive callback notifications for the
        /// lifetime of the engine instance.
        /// </summary>
        public void RegisterObserver(IContractExecutionObserver observer)
        {
            ArgumentNullException.ThrowIfNull(observer);
            _observers.Add(observer);
        }

        /// <summary>
        /// Executes a method on a contract with the provided execution context.
        /// </summary>
        public async Task<ExecutionResult> ExecuteAsync(
            ContractDefinition contract,
            string methodName,
            object?[]? parameters,
            ExecutionContext context,
            CancellationToken cancellationToken = default)
        {
            ArgumentNullException.ThrowIfNull(contract);
            ArgumentException.ThrowIfNullOrEmpty(methodName);

            // 1) Validate contract (throws on failure)
            ValidateContract(contract);

            // 2) Notify observers
            DispatchEvent(_observers, o => o.OnContractLoaded(contract));
            ContractLoaded?.Invoke(this, new ContractEventArgs(contract));

            // 3) Instantiate strategy & wrap with gas-meter proxy
            var innerStrategy = _strategyFactory.Create(contract);
            var gasProxy      = new GasMeterProxy(innerStrategy, context.GasBudget);

            // 4) Execution started
            DispatchEvent(_observers, o => o.OnExecutionStarted(contract, methodName, parameters, context));
            ExecutionStarted?.Invoke(this, new ContractEventArgs(contract, methodName));

            try
            {
                var result = await gasProxy.ExecuteAsync(methodName, parameters, context, cancellationToken)
                                           .ConfigureAwait(false);

                var execResult = new ExecutionResult(
                    result.ReturnValue,
                    gasProxy.GasUsed,
                    result.Logs);

                // 5) Success notifications
                DispatchEvent(_observers, o => o.OnExecutionCompleted(contract, execResult));
                ExecutionCompleted?.Invoke(this, new ExecutionCompletedEventArgs(contract, execResult));

                return execResult;
            }
            catch (Exception ex)
            {
                var fault = new ContractExecutionException(contract, methodName, ex);

                // 6) Failure notifications
                DispatchEvent(_observers, o => o.OnExecutionFailed(contract, fault));
                ExecutionFailed?.Invoke(this, new ExecutionFailedEventArgs(contract, fault));

                throw fault;
            }
        }

        #endregion

        #region Private Helpers

        private static void ValidateContract(ContractDefinition contract)
        {
            if (contract.Code.Length == 0)
            {
                throw new ContractValidationException("Empty contract code.");
            }

            // Basic safety checks – can be extended with signature verification,
            // policy compliance, bytecode inspection, etc.
            if (contract.Code.Length > ContractConstants.MaxContractSizeBytes)
            {
                throw new ContractValidationException(
                    $"Contract size exceeds maximum of {ContractConstants.MaxContractSizeBytes} bytes.");
            }
        }

        private static void DispatchEvent<TObserver>(IEnumerable<TObserver> observers, Action<TObserver> action)
        {
            foreach (var observer in observers)
            {
                try { action(observer); }
                catch
                {
                    // Observers should never impact engine stability – swallow and move on.
                }
            }
        }

        #endregion
    }

    #endregion

    #region Execution Strategies (Strategy Pattern)

    /// <summary>
    /// Factory responsible for providing an <see cref="IExecutionStrategy" />
    /// suitable for the given contract metadata.
    /// </summary>
    public sealed class ExecutionStrategyFactory
    {
        public IExecutionStrategy Create(ContractDefinition contract)
        {
            return contract.ExecutionType switch
            {
                ContractExecutionType.CLR  => new ClrScriptExecutionStrategy(contract),
                ContractExecutionType.Wasm => new WasmExecutionStrategy(contract),
                _                          => throw new NotSupportedException(
                    $"Execution type '{contract.ExecutionType}' is not supported.")
            };
        }
    }

    /// <summary>Common contract execution strategy abstraction.</summary>
    public interface IExecutionStrategy
    {
        Task<InternalExecutionResult> ExecuteAsync(
            string method,
            object?[]? args,
            ExecutionContext ctx,
            CancellationToken ct);
    }

    /// <summary>
    /// Execution strategy for plain C# scripts compiled at runtime using
    /// Roslyn scripting APIs.
    /// </summary>
    internal sealed class ClrScriptExecutionStrategy : IExecutionStrategy
    {
        private readonly Script<object>? _compiledScript;
        private readonly ContractDefinition _contract;

        public ClrScriptExecutionStrategy(ContractDefinition contract)
        {
            _contract = contract;
            _compiledScript = Compile(contract);
        }

        public async Task<InternalExecutionResult> ExecuteAsync(
            string method,
            object?[]? args,
            ExecutionContext ctx,
            CancellationToken ct)
        {
            if (_compiledScript is null)
                throw new InvalidOperationException("Contract has not been compiled.");

            var globals = new ScriptGlobals(ctx.BlockHeight, ctx.Caller, args ?? Array.Empty<object?>());
            var scriptState = await _compiledScript.RunAsync(globals, cancellationToken: ct);

            // The contract code must define a method with the requested name.
            if (scriptState.ReturnValue is not IDictionary<string, Delegate> exports ||
                !exports.TryGetValue(method, out var target))
            {
                throw new MissingMethodException($"Contract does not contain method '{method}'.");
            }

            var returnValue = target.DynamicInvoke(args ?? Array.Empty<object?>());

            var logs = scriptState.Variables; // Simplified: treat variables as logs

            return new InternalExecutionResult(returnValue, logs);
        }

        private static Script<object> Compile(ContractDefinition contract)
        {
            var options = ScriptOptions.Default
                                       .WithImports("System", "System.Linq", "System.Collections.Generic")
                                       .WithReferences(typeof(object).Assembly);

            // Compile contract code to a delegate map: return a dictionary where
            // keys are exported method names and values are delegates.
            var wrappedCode =
$$"""
using System;
using System.Collections.Generic;

public static class ContractExports
{
    public static IDictionary<string, Delegate> Create()
    {
        var exports = new Dictionary<string, Delegate>(StringComparer.OrdinalIgnoreCase);

{{contract.Code}}

        return exports;
    }
}

return ContractExports.Create();
""";

            return CSharpScript.Create(wrappedCode, options);
        }

        private sealed record ScriptGlobals(long BlockHeight, string Caller, object?[] Parameters);
    }

    /// <summary>
    /// Execution strategy for WASM contracts – in this stub implementation we
    /// simply pretend to execute and return a deterministic result. A real
    /// implementation would delegate to Wasmtime or Wasm3.
    /// </summary>
    internal sealed class WasmExecutionStrategy : IExecutionStrategy
    {
        private readonly ContractDefinition _contract;

        public WasmExecutionStrategy(ContractDefinition contract) => _contract = contract;

        public Task<InternalExecutionResult> ExecuteAsync(
            string method,
            object?[]? args,
            ExecutionContext ctx,
            CancellationToken ct)
        {
            // TODO: Replace stub with real WASM runtime invocation.
            object? result =
                $"{method} executed (WASM stub) for caller {ctx.Caller} on block {ctx.BlockHeight}.";

            return Task.FromResult(new InternalExecutionResult(result, Array.Empty<object>()));
        }
    }

    #endregion

    #region Gas Metering (Proxy Pattern)

    /// <summary>
    /// Wraps an execution strategy and tracks gas consumption during invocation.
    /// </summary>
    internal sealed class GasMeterProxy : IExecutionStrategy
    {
        private readonly IExecutionStrategy _inner;
        private readonly GasMeter _meter;

        public GasMeterProxy(IExecutionStrategy inner, long gasBudget)
        {
            _inner = inner;
            _meter = new GasMeter(gasBudget);
        }

        public long GasUsed => _meter.Used;

        public async Task<InternalExecutionResult> ExecuteAsync(
            string method,
            object?[]? args,
            ExecutionContext ctx,
            CancellationToken ct)
        {
            var start = _meter.ElapsedNano;
            var result = await _inner.ExecuteAsync(method, args, ctx, ct).ConfigureAwait(false);
            _meter.Consume(_meter.ElapsedNano - start); // simplistic
            return result;
        }
    }

    internal sealed class GasMeter
    {
        private readonly long _budget;
        private long _used;

        public GasMeter(long budget) => _budget = budget;

        public long Used => Interlocked.Read(ref _used);

        public long ElapsedNano => (long)(DateTime.UtcNow.Ticks * 100); // ≈ ns

        public void Consume(long gas)
        {
            var total = Interlocked.Add(ref _used, gas);
            if (total > _budget)
            {
                throw new GasExceededException($"Gas budget exceeded. Budget: {_budget}, Used: {total}");
            }
        }
    }

    #endregion

    #region Domain Models & Context

    public sealed record ExecutionContext(
        long BlockHeight,
        string Caller,
        long GasBudget)
    {
        // Additional blockchain-state accessors can be injected here (UTXO set,
        // Merkle Trie, etc.) without leaking mutable state to contracts.
    }

    public sealed record ContractDefinition(
        byte[] Code,
        ContractExecutionType ExecutionType,
        string Name,
        string Version);

    public enum ContractExecutionType
    {
        CLR,
        Wasm
    }

    public sealed record ExecutionResult(object? ReturnValue, long GasUsed, object? Logs);

    internal sealed record InternalExecutionResult(object? ReturnValue, object? Logs);

    public static class ContractConstants
    {
        public const int MaxContractSizeBytes = 1024 * 512; // 512 KiB
    }

    #endregion

    #region Observers & Events (Observer Pattern)

    public interface IContractExecutionObserver
    {
        void OnContractLoaded(ContractDefinition contract)    { }
        void OnExecutionStarted(
            ContractDefinition contract,
            string method,
            object?[]? parameters,
            ExecutionContext context)                          { }
        void OnExecutionCompleted(ContractDefinition contract, ExecutionResult result) { }
        void OnExecutionFailed(ContractDefinition contract, Exception ex)              { }
    }

    public sealed class ContractEventArgs : EventArgs
    {
        public ContractDefinition Contract { get; }
        public string? Method { get; }

        public ContractEventArgs(ContractDefinition contract, string? method = null)
        {
            Contract = contract;
            Method   = method;
        }
    }

    public sealed class ExecutionCompletedEventArgs : EventArgs
    {
        public ContractDefinition Contract { get; }
        public ExecutionResult Result { get; }

        public ExecutionCompletedEventArgs(
            ContractDefinition contract,
            ExecutionResult result)
        {
            Contract = contract;
            Result   = result;
        }
    }

    public sealed class ExecutionFailedEventArgs : EventArgs
    {
        public ContractDefinition Contract { get; }
        public Exception Exception { get; }

        public ExecutionFailedEventArgs(
            ContractDefinition contract,
            Exception ex)
        {
            Contract   = contract;
            Exception  = ex;
        }
    }

    #endregion

    #region Exceptions

    public sealed class ContractValidationException : Exception
    {
        public ContractValidationException(string message) : base(message) { }
        public ContractValidationException(string message, Exception inner) : base(message, inner) { }
    }

    public sealed class ContractExecutionException : Exception
    {
        public ContractDefinition Contract { get; }
        public string Method { get; }

        public ContractExecutionException(
            ContractDefinition contract,
            string method,
            Exception inner)
            : base($"Error executing contract '{contract.Name}' (method '{method}').", inner)
        {
            Contract = contract;
            Method   = method;
        }
    }

    public sealed class GasExceededException : Exception
    {
        public GasExceededException(string message) : base(message) { }
    }

    #endregion
}
```