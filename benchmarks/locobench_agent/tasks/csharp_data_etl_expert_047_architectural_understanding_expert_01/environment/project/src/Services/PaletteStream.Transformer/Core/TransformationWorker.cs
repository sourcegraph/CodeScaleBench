```csharp
// File: PaletteStream-ETL-Canvas/src/Services/PaletteStream.Transformer/Core/TransformationWorker.cs
//
// NOTE: This file is part of the “PaletteStream ETL Canvas” project.
//
// The TransformationWorker is a long-running background service that pulls raw data
// “pigments” from an async source, applies a Strategy-pattern driven transformation,
// performs data-quality checks, and then writes the curated result to the downstream
// sink.  Throughout the process it broadcasts lifecycle events to any registered
// observers, enabling real-time monitoring, alerting, and metrics collection.
//
// The worker is designed for high-throughput scenarios and can be hosted inside
// Kestrel, a Worker Service container, or executed as a Hangfire recurring job.
//
// -----------------------------------------------------------------------------
// External NuGet packages assumed:
//   - Microsoft.Extensions.Hosting
//   - Microsoft.Extensions.Logging
//   - System.Threading.Channels
//   - Microsoft.Data.Analysis (optional; only referenced in models)
// -----------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using System.Threading.Channels;

namespace PaletteStream.Transformer.Core
{
    /// <summary>
    /// Represents the background service responsible for orchestrating the
    /// end-to-end data transformation lifecycle.
    /// </summary>
    public sealed class TransformationWorker : BackgroundService
    {
        private readonly ILogger<TransformationWorker> _logger;
        private readonly ITransformationSource _source;
        private readonly ITransformationSink _sink;
        private readonly ITransformationStrategyFactory _strategyFactory;
        private readonly IReadOnlyCollection<ITransformationObserver> _observers;
        private readonly IDataQualityService _dataQualityService;

        public TransformationWorker(
            ILogger<TransformationWorker> logger,
            ITransformationSource source,
            ITransformationSink sink,
            ITransformationStrategyFactory strategyFactory,
            IEnumerable<ITransformationObserver> observers,
            IDataQualityService dataQualityService)
        {
            _logger             = logger ?? throw new ArgumentNullException(nameof(logger));
            _source             = source ?? throw new ArgumentNullException(nameof(source));
            _sink               = sink ?? throw new ArgumentNullException(nameof(sink));
            _strategyFactory    = strategyFactory ?? throw new ArgumentNullException(nameof(strategyFactory));
            _dataQualityService = dataQualityService ?? throw new ArgumentNullException(nameof(dataQualityService));
            _observers          = observers is IReadOnlyCollection<ITransformationObserver> list 
                                      ? list
                                      : new List<ITransformationObserver>(observers ?? Array.Empty<ITransformationObserver>());
        }

        /// <inheritdoc/>
        protected override async Task ExecuteAsync(CancellationToken stoppingToken)
        {
            _logger.LogInformation("TransformationWorker started");

            await foreach (var envelope in _source.ReadAsync(stoppingToken))
            {
                if (stoppingToken.IsCancellationRequested) break;

                var stopwatch = Stopwatch.StartNew();

                try
                {
                    await BroadcastAsync(o => o.OnTransformationStartedAsync(envelope, stoppingToken), stoppingToken);

                    // Resolve and execute strategy
                    var strat = _strategyFactory.Resolve(envelope.Metadata.TransformationType);
                    var transformed = await strat.TransformAsync(envelope.Payload, stoppingToken);

                    // Validate data-quality checkpoints
                    var dqResult = _dataQualityService.Validate(transformed);

                    if (!dqResult.IsSuccess)
                    {
                        await HandleDataQualityFailureAsync(envelope, dqResult, stoppingToken);
                        continue; // skip normal output
                    }

                    await _sink.WriteAsync(transformed, envelope.Metadata, stoppingToken);

                    stopwatch.Stop();
                    _logger.LogInformation(
                        "Successfully transformed envelope {EnvelopeId} in {ElapsedMs} ms",
                        envelope.Metadata.EnvelopeId,
                        stopwatch.ElapsedMilliseconds);

                    await BroadcastAsync(o =>
                        o.OnTransformationCompletedAsync(envelope, transformed, stoppingToken),
                        stoppingToken);
                }
                catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
                {
                    // Graceful shutdown
                    _logger.LogInformation("Cancellation requested. Shutting transformation loop down.");
                    break;
                }
                catch (Exception ex)
                {
                    await HandleUnhandledExceptionAsync(envelope, ex, stoppingToken);
                }
            }

            _logger.LogInformation("TransformationWorker stopped");
        }

        #region Helper / Error Handling

        private async Task HandleDataQualityFailureAsync(
            TransformationEnvelope envelope,
            DataQualityResult dqResult,
            CancellationToken token)
        {
            _logger.LogWarning(
                "DataQuality validation failed for envelope {EnvelopeId}: {Issues}",
                envelope.Metadata.EnvelopeId,
                string.Join(" | ", dqResult.Issues));

            await _sink.PublishDeadLetterAsync(envelope, dqResult, token);

            await BroadcastAsync(o =>
                o.OnTransformationFailedAsync(
                    envelope,
                    new DataQualityException(dqResult.Issues),
                    token),
                token);
        }

        private async Task HandleUnhandledExceptionAsync(
            TransformationEnvelope envelope,
            Exception ex,
            CancellationToken token)
        {
            _logger.LogError(ex,
                "Unhandled exception while processing envelope {EnvelopeId}",
                envelope.Metadata.EnvelopeId);

            await _sink.PublishDeadLetterAsync(envelope, ex, token);

            await BroadcastAsync(o => o.OnTransformationFailedAsync(envelope, ex, token), token);
        }

        private async Task BroadcastAsync(
            Func<ITransformationObserver, Task> notify,
            CancellationToken token)
        {
            foreach (var observer in _observers)
            {
                try
                {
                    if (token.IsCancellationRequested) return;
                    await notify(observer);
                }
                catch (Exception ex)
                {
                    // Observers should never bring down the worker
                    _logger.LogWarning(ex,
                        "Observer {Observer} threw during notification. Continuing...",
                        observer.GetType().Name);
                }
            }
        }

        #endregion
    }

    #region Contracts / Supporting Models

    /// <summary>
    /// Represents a source capable of streaming raw data envelopes.
    /// </summary>
    public interface ITransformationSource
    {
        IAsyncEnumerable<TransformationEnvelope> ReadAsync(CancellationToken token);
    }

    /// <summary>
    /// Represents the downstream sink that stores curated data or dead-letter items.
    /// </summary>
    public interface ITransformationSink
    {
        Task WriteAsync(TransformedData data, TransformationMetadata metadata, CancellationToken token);

        Task PublishDeadLetterAsync(
            TransformationEnvelope envelope,
            object error,
            CancellationToken token);
    }

    /// <summary>
    /// Factory responsible for resolving the correct transformation strategy.
    /// </summary>
    public interface ITransformationStrategyFactory
    {
        ITransformationStrategy Resolve(string transformationType);
    }

    /// <summary>
    /// Strategy-pattern abstraction for performing a data transformation.
    /// </summary>
    public interface ITransformationStrategy
    {
        Task<TransformedData> TransformAsync(RawData data, CancellationToken token);
    }

    /// <summary>
    /// Hook for observing lifecycle events emitted by <see cref="TransformationWorker"/>.
    /// </summary>
    public interface ITransformationObserver
    {
        Task OnTransformationStartedAsync(TransformationEnvelope envelope, CancellationToken token);

        Task OnTransformationCompletedAsync(
            TransformationEnvelope envelope,
            TransformedData result,
            CancellationToken token);

        Task OnTransformationFailedAsync(
            TransformationEnvelope envelope,
            Exception ex,
            CancellationToken token);
    }

    /// <summary>
    /// Validates transformed data against data-quality rules.
    /// </summary>
    public interface IDataQualityService
    {
        DataQualityResult Validate(TransformedData data);
    }

    /// <summary>
    /// Raw un-curated data (“pigment”) flowing in from an upstream source.
    /// </summary>
    public sealed record RawData
    {
        // In a real system this would wrap a DataFrame or a strongly-typed POCO collection.
        public byte[] Buffer { get; init; } = Array.Empty<byte>();
    }

    /// <summary>
    /// Curated, validated data ready for downstream zones.
    /// </summary>
    public sealed record TransformedData
    {
        // Again, this could be a Microsoft.Data.Analysis.DataFrame
        public byte[] Buffer { get; init; } = Array.Empty<byte>();
        public DateTime TransformedUtc { get; init; } = DateTime.UtcNow;
    }

    public sealed record TransformationMetadata
    {
        public Guid   EnvelopeId         { get; init; } = Guid.NewGuid();
        public string TransformationType { get; init; } = string.Empty;
        public DateTime ReceivedUtc      { get; init; } = DateTime.UtcNow;
    }

    /// <summary>
    /// Combines raw data with the metadata required to perform a transformation.
    /// </summary>
    public sealed record TransformationEnvelope
    {
        public RawData               Payload  { get; init; } = new();
        public TransformationMetadata Metadata { get; init; } = new();
    }

    /// <summary>
    /// Result of a data-quality check pass/fail.
    /// </summary>
    public sealed record DataQualityResult
    {
        public bool                IsSuccess { get; init; } = true;
        public IReadOnlyList<string> Issues   { get; init; } = Array.Empty<string>();

        public static DataQualityResult Success() => new() { IsSuccess = true };
        public static DataQualityResult Failure(IEnumerable<string> issues) =>
            new()
            {
                IsSuccess = false,
                Issues    = new List<string>(issues)
            };
    }

    /// <summary>
    /// Exception type used to surface data-quality errors.
    /// </summary>
    public sealed class DataQualityException : Exception
    {
        public IReadOnlyList<string> Issues { get; }

        public DataQualityException(IEnumerable<string> issues)
            : base($"Data quality validation failed: {string.Join(" | ", issues)}")
        {
            Issues = new List<string>(issues);
        }
    }

    #endregion
}
```