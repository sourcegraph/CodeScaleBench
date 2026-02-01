```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using PaletteStream.Ingestion.Core.Contracts;
using PaletteStream.Ingestion.Core.Events;
using PaletteStream.Ingestion.Core.Exceptions;
using PaletteStream.Ingestion.Core.Models;
using PaletteStream.SharedKernel.Events;

namespace PaletteStream.Ingestion.Core;

/// <summary>
///     The heart of the Ingestion micro-service.  Responsible for orchestrating the flow of data
///     from an <see cref="ISourceAdapter"/> through a transformation <see cref="IPipeline"/>
///     and finally into a <see cref="ISinkAdapter"/> destination.  Both streaming and batch
///     scenarios are supported.
/// </summary>
/// <remarks>
///     The service is intentionally stateless so that multiple instances can run in parallel
///     (e.g. Kubernetes horizontal scaling).
/// </remarks>
public sealed class IngestionService : IIngestionService, IAsyncDisposable
{
    private readonly IReadOnlyDictionary<string, ISourceAdapter> _sources;
    private readonly IReadOnlyDictionary<string, ISinkAdapter>   _sinks;
    private readonly IPipeline                                   _pipeline;
    private readonly IEventBus                                   _eventBus;
    private readonly IngestionOptions                            _options;
    private readonly ILogger<IngestionService>                   _logger;
    private readonly ConcurrentDictionary<Guid, CancellationTokenSource> _streamSessions = new();

    public IngestionService(
        IEnumerable<ISourceAdapter> sources,
        IEnumerable<ISinkAdapter> sinks,
        IPipeline pipeline,
        IEventBus eventBus,
        IOptions<IngestionOptions> options,
        ILogger<IngestionService> logger)
    {
        _sources  = sources?.ToDictionary(s => s.Name, StringComparer.OrdinalIgnoreCase)
                    ?? throw new ArgumentNullException(nameof(sources));
        _sinks    = sinks?.ToDictionary(s => s.Name,  StringComparer.OrdinalIgnoreCase)
                    ?? throw new ArgumentNullException(nameof(sinks));
        _pipeline = pipeline  ?? throw new ArgumentNullException(nameof(pipeline));
        _eventBus = eventBus  ?? throw new ArgumentNullException(nameof(eventBus));
        _options  = options?.Value ?? new IngestionOptions();
        _logger   = logger   ?? throw new ArgumentNullException(nameof(logger));
    }

    #region Batch

    /// <inheritdoc />
    public async Task<IngestionResult> RunBatchAsync(
        string sourceName,
        string sinkName,
        IReadOnlyDictionary<string, object?>? parameters = null,
        CancellationToken cancellationToken             = default)
    {
        _logger.LogInformation("Starting batch ingestion: Source={Source} Sink={Sink}", sourceName, sinkName);

        ISourceAdapter source = ResolveSource(sourceName);
        ISinkAdapter sink    = ResolveSink(sinkName);

        var readContext  = new ReadContext(isStreaming:false, parameters);
        var writeContext = new WriteContext(isStreaming:false, parameters);

        var processed = 0L;
        var failed    = 0L;

        await foreach (var pigment in EnumerateWithCancellation(source.ReadAsync(readContext, cancellationToken), cancellationToken))
        {
            try
            {
                var transformed = await _pipeline.ProcessAsync(pigment, cancellationToken).ConfigureAwait(false);
                await sink.WriteAsync(transformed, writeContext, cancellationToken).ConfigureAwait(false);

                processed++;
                OnProgress(pigment);
            }
            catch (Exception ex)
            {
                failed++;
                _logger.LogError(ex, "Failed to process pigment with Id={PigmentId}", pigment.Id);
                await _eventBus.PublishAsync(new IngestionFailedEvent(pigment.Id, ex), cancellationToken).ConfigureAwait(false);

                if (_options.ThrowOnFirstError)
                    throw;
            }
        }

        var result = new IngestionResult(processed, failed);
        _logger.LogInformation("Batch ingestion completed: {@Result}", result);

        await _eventBus.PublishAsync(new IngestionCompletedEvent(sourceName, sinkName, result), cancellationToken)
                       .ConfigureAwait(false);

        return result;
    }

    #endregion

    #region Streaming

    /// <inheritdoc />
    public async Task<Guid> StartStreamAsync(
        string sourceName,
        string sinkName,
        IReadOnlyDictionary<string, object?>? parameters = null,
        CancellationToken cancellationToken             = default)
    {
        ISourceAdapter source = ResolveSource(sourceName);
        ISinkAdapter sink    = ResolveSink(sinkName);

        var sessionId = Guid.NewGuid();
        var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);

        if (!_streamSessions.TryAdd(sessionId, linkedCts))
            throw new InvalidOperationException("Unable to register stream session.");

        _ = Task.Run(async () =>
        {
            _logger.LogInformation("🟢 Stream session {SessionId} started (Source={Source}, Sink={Sink})",
                                   sessionId, sourceName, sinkName);

            var readContext  = new ReadContext(isStreaming:true, parameters);
            var writeContext = new WriteContext(isStreaming:true, parameters);

            await using var buffer = Channel.CreateBounded<Pigment>(_options.StreamBufferSize);

            var producer = Task.Run(async () =>
            {
                try
                {
                    await foreach (var pigment in source.ReadAsync(readContext, linkedCts.Token)
                                                        .WithCancellation(linkedCts.Token))
                    {
                        await buffer.Writer.WriteAsync(pigment, linkedCts.Token).ConfigureAwait(false);
                    }
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Stream producer error (SessionId={SessionId})", sessionId);
                    linkedCts.Cancel();
                }
                finally
                {
                    buffer.Writer.Complete();
                }
            }, linkedCts.Token);

            var consumerWorkers = Enumerable.Range(0, _options.Parallelism).Select(_ => Task.Run(async () =>
            {
                try
                {
                    while (await buffer.Reader.WaitToReadAsync(linkedCts.Token).ConfigureAwait(false))
                    {
                        while (buffer.Reader.TryRead(out var pigment))
                        {
                            await ProcessAndSinkAsync(pigment, sink, writeContext, linkedCts.Token)
                                .ConfigureAwait(false);
                        }
                    }
                }
                catch (OperationCanceledException)
                {
                    /* graceful shutdown */
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Stream consumer error (SessionId={SessionId})", sessionId);
                    linkedCts.Cancel();
                }
            }, linkedCts.Token)).ToArray();

            await Task.WhenAll(consumerWorkers.Concat(new[] { producer })).ConfigureAwait(false);

            _logger.LogInformation("🔴 Stream session {SessionId} stopped", sessionId);
        }, linkedCts.Token);

        return sessionId;
    }

    /// <inheritdoc />
    public void StopStream(Guid sessionId)
    {
        if (_streamSessions.TryRemove(sessionId, out var cts))
        {
            _logger.LogInformation("Cancellation requested for stream session {SessionId}", sessionId);
            cts.Cancel();
        }
    }

    #endregion

    #region Helpers

    private ISourceAdapter ResolveSource(string sourceName)
        => _sources.TryGetValue(sourceName, out var source)
           ? source
           : throw new AdapterNotFoundException(sourceName, AdapterType.Source);

    private ISinkAdapter ResolveSink(string sinkName)
        => _sinks.TryGetValue(sinkName, out var sink)
           ? sink
           : throw new AdapterNotFoundException(sinkName, AdapterType.Sink);

    private async Task ProcessAndSinkAsync(
        Pigment pigment,
        ISinkAdapter sink,
        WriteContext writeContext,
        CancellationToken cancellationToken)
    {
        try
        {
            var transformed = await _pipeline.ProcessAsync(pigment, cancellationToken).ConfigureAwait(false);
            await sink.WriteAsync(transformed, writeContext, cancellationToken).ConfigureAwait(false);

            OnProgress(pigment);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to process pigment with Id={PigmentId}", pigment.Id);
            await _eventBus.PublishAsync(new IngestionFailedEvent(pigment.Id, ex), cancellationToken).ConfigureAwait(false);

            if (_options.ThrowOnFirstError)
                throw;
        }
    }

    private void OnProgress(Pigment pigment)
        => _eventBus.PublishAsync(new IngestionProgressEvent(pigment.Id),
                                  CancellationToken.None).Forget();

    /// <summary>
    ///     Ensures async enumeration is cooperatively canceled, while keeping the compiler happy about nullability.
    /// </summary>
    private static async IAsyncEnumerable<T> EnumerateWithCancellation<T>(
        IAsyncEnumerable<T> source,
        [EnumeratorCancellation] CancellationToken ct)
    {
        await foreach (var item in source.WithCancellation(ct).ConfigureAwait(false))
            yield return item;
    }

    #endregion

    #region IDisposable

    public ValueTask DisposeAsync()
    {
        foreach (var cts in _streamSessions.Values)
        {
            try { cts.Cancel(); }
            catch { /* ignore */ }
            cts.Dispose();
        }

        _streamSessions.Clear();
        return ValueTask.CompletedTask;
    }

    #endregion
}

#region Options / Contracts / Shared models (internal for compilation)

public record IngestionOptions
{
    public int  Parallelism       { get; init; } = Environment.ProcessorCount;
    public int  StreamBufferSize  { get; init; } = 4_096;
    public bool ThrowOnFirstError { get; init; }
}

public interface IIngestionService
{
    Task<IngestionResult> RunBatchAsync(
        string sourceName,
        string sinkName,
        IReadOnlyDictionary<string, object?>? parameters = null,
        CancellationToken cancellationToken             = default);

    Task<Guid> StartStreamAsync(
        string sourceName,
        string sinkName,
        IReadOnlyDictionary<string, object?>? parameters = null,
        CancellationToken cancellationToken             = default);

    void StopStream(Guid sessionId);
}

/// <summary>
///     Lightweight wrapper around progress, success & failure counts.
/// </summary>
public readonly record struct IngestionResult(long Processed, long Failed);

#endregion

#region Extension helpers

internal static class TaskExtensions
{
    /// <summary>
    ///     Fire-and-forget while surfacing unobserved exceptions to the thread-pool handler.
    /// </summary>
    public static void Forget(this Task task)
    {
        if (task.IsCompleted)
        {
            if (task.IsFaulted)
                _ = task.Exception;           // observe exception to prevent Unobserved
            return;
        }

        _ = ForgetAwaited(task);

        static async Task ForgetAwaited(Task t)
        {
            try       { await t.ConfigureAwait(false); }
            // ReSharper disable once EmptyGeneralCatchClause
            catch     { /* swallowed */ }
        }
    }
}

#endregion
```