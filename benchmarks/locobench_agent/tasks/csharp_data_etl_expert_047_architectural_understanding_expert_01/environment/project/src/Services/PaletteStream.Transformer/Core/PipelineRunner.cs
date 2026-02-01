```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Transformer.Core
{
    /// <summary>
    ///   Runs a transformation pipeline in either batch or streaming mode.
    ///   The runner pulls data from an <see cref="IDataStreamReader"/>, executes a chain of
    ///   <see cref="ITransformerStep"/> components, pushes the result to an <see cref="IDataStreamWriter"/>,
    ///   and publishes pipeline events to an <see cref="IEventBus"/> for monitoring & alerting.
    /// </summary>
    public sealed class PipelineRunner : IPipelineRunner, IAsyncDisposable
    {
        private readonly IDataStreamReader        _reader;
        private readonly IReadOnlyList<ITransformerStep> _steps;
        private readonly IDataStreamWriter        _writer;
        private readonly IDeadLetterSink          _deadLetterSink;
        private readonly IEventBus                _eventBus;
        private readonly ILogger<PipelineRunner>  _logger;
        private          long                     _successCount;
        private          long                     _failureCount;
        private          bool                     _disposed;

        public PipelineRunner(
            IDataStreamReader               reader,
            IEnumerable<ITransformerStep>   steps,
            IDataStreamWriter               writer,
            IDeadLetterSink                 deadLetterSink,
            IEventBus                       eventBus,
            ILogger<PipelineRunner>         logger)
        {
            _reader         = reader  ?? throw new ArgumentNullException(nameof(reader));
            _writer         = writer  ?? throw new ArgumentNullException(nameof(writer));
            _deadLetterSink = deadLetterSink ?? throw new ArgumentNullException(nameof(deadLetterSink));
            _eventBus       = eventBus ?? throw new ArgumentNullException(nameof(eventBus));
            _logger         = logger ?? throw new ArgumentNullException(nameof(logger));

            if (steps is null) throw new ArgumentNullException(nameof(steps));
            _steps = steps.ToList().AsReadOnly();

            if (!_steps.Any())
                throw new ArgumentException("Pipeline cannot be empty.", nameof(steps));
        }

        /// <inheritdoc/>
        public async Task<PipelineResult> ExecuteAsync(CancellationToken cancellationToken = default)
        {
            var sw = Stopwatch.StartNew();
            _logger.LogInformation("Pipeline starting with {StepCount} step(s).", _steps.Count);
            await _eventBus.PublishAsync(new PipelineStarted(DateTimeOffset.UtcNow, _steps.Count), cancellationToken)
                            .ConfigureAwait(false);

            await foreach (var record in _reader.ReadAsync(cancellationToken).ConfigureAwait(false))
            {
                cancellationToken.ThrowIfCancellationRequested();
                await ProcessRecordAsync(record, cancellationToken).ConfigureAwait(false);
            }

            await _writer.FlushAsync(cancellationToken).ConfigureAwait(false);

            var elapsed = sw.Elapsed;
            var result  = new PipelineResult(_successCount, _failureCount, elapsed);

            await _eventBus.PublishAsync(
                new PipelineCompleted(DateTimeOffset.UtcNow, result), cancellationToken).ConfigureAwait(false);

            _logger.LogInformation("Pipeline completed in {Elapsed}. Success={Success}, Fail={Fail}",
                                   elapsed, _successCount, _failureCount);
            return result;
        }

        /// <summary>
        ///   Processes a single record through the pipeline chain.
        /// </summary>
        private async ValueTask ProcessRecordAsync(DataRecord record, CancellationToken ct)
        {
            try
            {
                var current = record;

                foreach (var step in _steps)
                {
                    ct.ThrowIfCancellationRequested();
                    current = await step.TransformAsync(current, ct).ConfigureAwait(false);

                    if (current is { IsDeleted: true })
                    {
                        // Short-circuit if a step marks the record as deleted (soft-delete behaviour)
                        _logger.LogDebug("Record {RecordId} marked as deleted. Skipping remaining steps.",
                                         record.Id);
                        break;
                    }
                }

                await _writer.WriteAsync(current, ct).ConfigureAwait(false);
                Interlocked.Increment(ref _successCount);
            }
            catch (Exception ex)
            {
                Interlocked.Increment(ref _failureCount);
                await HandleErrorAsync(record, ex, ct).ConfigureAwait(false);
            }
        }

        private async ValueTask HandleErrorAsync(DataRecord record, Exception ex, CancellationToken ct)
        {
            _logger.LogError(ex, "Failed processing record {RecordId}; routing to dead letter queue.", record?.Id);
            await _deadLetterSink.WriteAsync(new DeadLetterItem(record, ex), ct).ConfigureAwait(false);
            await _eventBus.PublishAsync(new TransformationFailed(record, ex), ct).ConfigureAwait(false);
        }

        #region IAsyncDisposable

        public async ValueTask DisposeAsync()
        {
            if (_disposed) return;
            _disposed = true;

            try
            {
                await _reader.DisposeAsync().ConfigureAwait(false);
                await _writer.DisposeAsync().ConfigureAwait(false);
                await _deadLetterSink.DisposeAsync().ConfigureAwait(false);
                // _eventBus usually has a longer life cycle, so we intentionally don't dispose it here
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Error while disposing pipeline resources.");
            }
        }

        #endregion
    }

    #region Interfaces and models (simplified stub versions)

    // NOTE: The following abstractions would normally reside in separate files / packages, but are embedded
    //       here to keep this code file self-contained and compilable for demonstration purposes.

    public interface IPipelineRunner
    {
        Task<PipelineResult> ExecuteAsync(CancellationToken cancellationToken = default);
    }

    public interface IDataStreamReader : IAsyncDisposable
    {
        IAsyncEnumerable<DataRecord> ReadAsync(CancellationToken cancellationToken = default);
    }

    public interface IDataStreamWriter : IAsyncDisposable
    {
        Task WriteAsync(DataRecord record, CancellationToken cancellationToken = default);
        Task FlushAsync(CancellationToken cancellationToken = default);
    }

    public interface IDeadLetterSink : IAsyncDisposable
    {
        Task WriteAsync(DeadLetterItem item, CancellationToken cancellationToken = default);
    }

    public interface ITransformerStep
    {
        /// <summary>
        ///   Executes the step transform.
        /// </summary>
        Task<DataRecord> TransformAsync(DataRecord input, CancellationToken cancellationToken = default);
    }

    public interface IEventBus
    {
        Task PublishAsync<TEvent>(TEvent @event, CancellationToken cancellationToken = default);
    }

    #endregion

    #region Supporting DTOs

    public sealed record PipelineResult(long SuccessCount, long FailureCount, TimeSpan Elapsed);

    public sealed record DataRecord(Guid Id, IReadOnlyDictionary<string, object?> Fields, bool IsDeleted = false)
    {
        public static DataRecord Create(IReadOnlyDictionary<string, object?> fields)
            => new(Guid.NewGuid(), fields);
    }

    public sealed record DeadLetterItem(DataRecord Record, Exception Exception);

    // Events
    public sealed record PipelineStarted(DateTimeOffset Timestamp, int StepCount);
    public sealed record PipelineCompleted(DateTimeOffset Timestamp, PipelineResult Result);
    public sealed record TransformationFailed(DataRecord Record, Exception Exception);

    #endregion
}
```