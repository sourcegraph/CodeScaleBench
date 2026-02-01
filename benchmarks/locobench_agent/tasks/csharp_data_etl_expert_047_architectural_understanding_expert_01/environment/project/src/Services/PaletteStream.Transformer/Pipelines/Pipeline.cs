```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using PaletteStream.Transformer.Monitoring;
using PaletteStream.Transformer.Pipelines.Contracts;

namespace PaletteStream.Transformer.Pipelines;

/// <summary>
///     A composable, asynchronous ETL pipeline that supports
///     1. Dynamic step injection/removal
///     2. Parallel fan-out / fan-in execution
///     3. Step-level observability (latency, error rate, throughput)
///     4. Cancellation & graceful shutdown semantics
/// </summary>
/// <typeparam name="TIn">Input message shape (raw pigment)</typeparam>
/// <typeparam name="TOut">Output message shape (curated pigment)</typeparam>
public sealed class Pipeline<TIn, TOut> : IPipeline<TIn, TOut>, IDisposable
{
    private readonly IReadOnlyList<IPipelineStep> _steps;
    private readonly ILogger<Pipeline<TIn, TOut>> _logger;
    private readonly ITransformationObserver _observer;
    private bool _disposed;

    internal Pipeline(
        IEnumerable<IPipelineStep> steps,
        ILogger<Pipeline<TIn, TOut>> logger,
        ITransformationObserver? observer = null)
    {
        _steps   = steps.ToList().AsReadOnly();
        _logger  = logger;
        _observer = observer ?? NullTransformationObserver.Instance;
    }

    #region IPipeline

    /// <inheritdoc />
    public async Task<TOut> ExecuteAsync(TIn input, CancellationToken ct = default)
    {
        EnsureNotDisposed();

        object? current = input;

        foreach (var step in _steps)
        {
            if (ct.IsCancellationRequested)
            {
                _logger.LogWarning("Pipeline execution cancelled before step {StepName}", step.Name);
                ct.ThrowIfCancellationRequested();
            }

            current = await ExecuteStepAsync(step, current!, ct).ConfigureAwait(false);
        }

        return (TOut)current!;
    }

    /// <inheritdoc />
    public async IAsyncEnumerable<TOut> ExecuteBatchAsync(
        IAsyncEnumerable<TIn> inputs,
        int degreeOfParallelism = 4,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
    {
        EnsureNotDisposed();

        if (degreeOfParallelism <= 0)
            throw new ArgumentOutOfRangeException(nameof(degreeOfParallelism));

        await foreach (var batchItem in ExecuteWithParallelismAsync(inputs, degreeOfParallelism, ct).ConfigureAwait(false))
            yield return batchItem;
    }

    #endregion

    #region Private helpers

    private async Task<object> ExecuteStepAsync(IPipelineStep step, object input, CancellationToken ct)
    {
        var sw = Stopwatch.StartNew();
        try
        {
            _observer.OnStepStart(step.Name, input);
            var output = await step.InvokeAsync(input, ct).ConfigureAwait(false);
            sw.Stop();

            _observer.OnStepSuccess(step.Name, sw.Elapsed);
            return output;
        }
        catch (Exception ex)
        {
            sw.Stop();
            _observer.OnStepError(step.Name, ex, sw.Elapsed);
            _logger.LogError(ex, "Step {StepName} failed after {Elapsed}", step.Name, sw.Elapsed);
            throw;
        }
    }

    private async IAsyncEnumerable<TOut> ExecuteWithParallelismAsync(
        IAsyncEnumerable<TIn> source,
        int dop,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken ct = default)
    {
        var throttler = new SemaphoreSlim(dop, dop);
        var channel   = new ConcurrentQueue<Task<TOut>>();

        await foreach (var item in source.WithCancellation(ct).ConfigureAwait(false))
        {
            await throttler.WaitAsync(ct).ConfigureAwait(false);

            var task = ExecuteAsync(item, ct)
                .ContinueWith(t =>
                {
                    throttler.Release();
                    return t.Result;
                }, ct);

            channel.Enqueue(task);

            // Drain completed tasks
            while (channel.TryPeek(out var peek) && peek.IsCompleted)
            {
                channel.TryDequeue(out var completed);
                yield return await completed.ConfigureAwait(false);
            }
        }

        // Drain the remaining
        while (channel.TryDequeue(out var remaining))
        {
            yield return await remaining.ConfigureAwait(false);
        }
    }

    private void EnsureNotDisposed()
    {
        if (_disposed) throw new ObjectDisposedException(nameof(Pipeline<TIn, TOut>));
    }

    #endregion

    #region IDisposable

    public void Dispose()
    {
        if (_disposed) return;

        foreach (var step in _steps.OfType<IDisposable>())
            step.Dispose();

        _disposed = true;
        GC.SuppressFinalize(this);
    }

    #endregion
}

/// <summary>
///     Pipeline builder that wires up dependencies (steps, logging, observers)
/// </summary>
/// <typeparam name="TIn"></typeparam>
/// <typeparam name="TOut"></typeparam>
public sealed class PipelineBuilder<TIn, TOut>
{
    private readonly IList<IPipelineStep> _steps = new List<IPipelineStep>();
    private ILogger<Pipeline<TIn, TOut>>? _logger;
    private ITransformationObserver? _observer;

    public PipelineBuilder<TIn, TOut> UseStep(IPipelineStep step)
    {
        _steps.Add(step ?? throw new ArgumentNullException(nameof(step)));
        return this;
    }

    public PipelineBuilder<TIn, TOut> UseObserver(ITransformationObserver observer)
    {
        _observer = observer ?? throw new ArgumentNullException(nameof(observer));
        return this;
    }

    public PipelineBuilder<TIn, TOut> UseLogger(ILogger<Pipeline<TIn, TOut>> logger)
    {
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        return this;
    }

    public IPipeline<TIn, TOut> Build()
    {
        if (!_steps.Any())
            throw new InvalidOperationException("Pipeline must have at least one step.");

        var logger = _logger ?? NullLoggerFactory.Instance.CreateLogger<Pipeline<TIn, TOut>>();
        var builtSteps = _steps.Select(s => s).ToArray(); // clone

        return new Pipeline<TIn, TOut>(builtSteps, logger, _observer);
    }
}

/* Contracts & Infrastructure */

namespace PaletteStream.Transformer.Pipelines.Contracts
{
    /// <summary>
    ///     Represents a unit of work in the ETL pipeline.
    ///     Steps are intentionally untyped on input/output to enable
    ///     covariance across heterogeneous transformations.
    /// </summary>
    public interface IPipelineStep : IDisposable
    {
        string Name { get; }

        Task<object> InvokeAsync(object input, CancellationToken ct = default);
    }

    public interface IPipeline<in TIn, TOut>
    {
        /// <summary>
        ///     Execute the pipeline for a single item.
        /// </summary>
        Task<TOut> ExecuteAsync(TIn input, CancellationToken ct = default);

        /// <summary>
        ///     Execute the pipeline for a stream of items.
        ///     Results are streamed back as soon as they become available.
        /// </summary>
        IAsyncEnumerable<TOut> ExecuteBatchAsync(IAsyncEnumerable<TIn> inputs,
                                                int degreeOfParallelism = 4,
                                                CancellationToken ct = default);
    }
}

/* Monitoring */

namespace PaletteStream.Transformer.Monitoring
{
    public interface ITransformationObserver
    {
        void OnStepStart(string stepName, object payload);
        void OnStepSuccess(string stepName, TimeSpan latency);
        void OnStepError(string stepName, Exception ex, TimeSpan latency);
    }

    /// <summary>
    ///     Silent observer (used when no explicit observer was configured)
    /// </summary>
    internal sealed class NullTransformationObserver : ITransformationObserver
    {
        public static readonly NullTransformationObserver Instance = new();

        public void OnStepStart(string stepName, object payload) { }
        public void OnStepSuccess(string stepName, TimeSpan latency) { }
        public void OnStepError(string stepName, Exception ex, TimeSpan latency) { }
    }
}

/* Null logger fallback */

internal sealed class NullLoggerFactory : ILoggerFactory
{
    public static readonly NullLoggerFactory Instance = new();

    public void Dispose() { }

    public ILogger CreateLogger(string categoryName) => new NullLogger();

    public void AddProvider(ILoggerProvider provider) { }

    private class NullLogger : ILogger
    {
        public IDisposable BeginScope<TState>(TState state) => NullDisposable.Instance;
        public bool IsEnabled(LogLevel logLevel) => false;
        public void Log<TState>(LogLevel logLevel, EventId eventId,
            TState state, Exception exception, Func<TState, Exception, string> formatter) { }

        private sealed class NullDisposable : IDisposable
        {
            public static readonly NullDisposable Instance = new();
            public void Dispose() { }
        }
    }
}
```