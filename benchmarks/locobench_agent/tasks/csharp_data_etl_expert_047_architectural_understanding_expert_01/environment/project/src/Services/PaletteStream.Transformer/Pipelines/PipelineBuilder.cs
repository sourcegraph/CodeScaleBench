```csharp
// File: PaletteStream-ETL-Canvas/src/Services/PaletteStream.Transformer/Pipelines/PipelineBuilder.cs
//
// Copyright (c) PaletteStream.
// Licensed under the MIT license.

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Transformer.Pipelines
{
    #region Core Abstractions

    /// <summary>
    /// A single unit of work inside a transformation pipeline.
    /// </summary>
    public interface IPipelineStage
    {
        /// <summary>
        /// Human-friendly name of the stage for logging/monitoring.
        /// </summary>
        string Name { get; }

        /// <summary>
        /// Executes the stage logic.
        /// </summary>
        /// <param name="input">Up-stream data as async stream.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        /// <returns>Down-stream data as async stream.</returns>
        ValueTask<IAsyncEnumerable<PigmentFrame>> ProcessAsync(
            IAsyncEnumerable<PigmentFrame> input,
            CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Observer pattern hook to monitor stage lifecycle events.
    /// </summary>
    public interface ITransformationObserver
    {
        Task OnStageStartedAsync(string stageName, CancellationToken token);
        Task OnStageCompletedAsync(string stageName, CancellationToken token);
        Task OnStageErrorAsync(string stageName, Exception ex, CancellationToken token);
    }

    /// <summary>
    /// A single “pixel” in the ETL canvas – a minimal data unit.
    /// </summary>
    public sealed record PigmentFrame
    {
        public PigmentFrame(IDictionary<string, object?> columns)
        {
            if (columns is null)
                throw new ArgumentNullException(nameof(columns));

            Columns = new ReadOnlyDictionary<string, object?>(columns);
            Timestamp = DateTimeOffset.UtcNow;
        }

        public Guid Id { get; init; } = Guid.NewGuid();

        public DateTimeOffset Timestamp { get; }

        public IReadOnlyDictionary<string, object?> Columns { get; }
    }

    /// <summary>
    /// Public contract for a pipeline that can be executed.
    /// </summary>
    public interface IPipeline
    {
        /// <summary>
        /// Runs the pipeline.
        /// </summary>
        /// <param name="source">Initial input stream.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        /// <returns>Transformed output stream.</returns>
        Task<IAsyncEnumerable<PigmentFrame>> ExecuteAsync(
            IAsyncEnumerable<PigmentFrame> source,
            CancellationToken cancellationToken = default);
    }

    #endregion

    /// <summary>
    /// Implements builder pattern for composing complex transformation pipelines.
    /// </summary>
    public sealed class PipelineBuilder
    {
        private readonly List<Func<IServiceProvider, IPipelineStage>> _factoryDelegates = new();
        private readonly List<ITransformationObserver> _observers = new();
        private readonly IServiceProvider _services;
        private readonly ILogger<PipelineBuilder> _logger;
        private bool _built;

        public PipelineBuilder(IServiceProvider services)
        {
            _services = services ?? throw new ArgumentNullException(nameof(services));
            _logger = _services.GetRequiredService<ILogger<PipelineBuilder>>();
        }

        /// <summary>
        /// Adds a new stage to the pipeline. The stage is resolved from the container.
        /// </summary>
        public PipelineBuilder AddStage<TStage>() where TStage : class, IPipelineStage
        {
            EnsureNotBuilt();
            _factoryDelegates.Add(sp => sp.GetRequiredService<TStage>());
            _logger.LogDebug("Queued stage {StageType}", typeof(TStage).Name);
            return this;
        }

        /// <summary>
        /// Adds a stage using a custom factory delegate.
        /// </summary>
        public PipelineBuilder AddStage<TStage>(Func<IServiceProvider, TStage> factory)
            where TStage : class, IPipelineStage
        {
            if (factory is null)
                throw new ArgumentNullException(nameof(factory));

            EnsureNotBuilt();
            _factoryDelegates.Add(sp => factory(sp));
            _logger.LogDebug("Queued stage via factory {StageType}", typeof(TStage).Name);
            return this;
        }

        /// <summary>
        /// Registers an observer which receives lifecycle callbacks.
        /// </summary>
        public PipelineBuilder AddObserver(ITransformationObserver observer)
        {
            if (observer is null)
                throw new ArgumentNullException(nameof(observer));

            EnsureNotBuilt();
            _observers.Add(observer);
            return this;
        }

        /// <summary>
        /// Builds an immutable pipeline instance. This method is idempotent,
        /// subsequent calls return the same instance.
        /// </summary>
        public IPipeline Build()
        {
            if (_built)
                throw new InvalidOperationException("Pipeline has already been built.");

            _built = true;

            // Materialise stages at build-time.
            var stages = _factoryDelegates.Select(f => f(_services)).ToArray();

            if (stages.Length == 0)
                throw new InvalidOperationException("Cannot build an empty pipeline.");

            return new BuiltPipeline(
                stages,
                _observers.ToArray(),
                _services.GetRequiredService<ILogger<BuiltPipeline>>());
        }

        #region Private Helpers
        private void EnsureNotBuilt()
        {
            if (_built)
                throw new InvalidOperationException("Pipeline has already been built and cannot be modified.");
        }
        #endregion

        #region Inner Classes

        /// <summary>
        /// Concrete pipeline produced by the <see cref="PipelineBuilder"/>.
        /// </summary>
        private sealed class BuiltPipeline : IPipeline
        {
            private readonly IReadOnlyList<IPipelineStage> _stages;
            private readonly IReadOnlyList<ITransformationObserver> _observers;
            private readonly ILogger<BuiltPipeline> _logger;

            public BuiltPipeline(
                IReadOnlyList<IPipelineStage> stages,
                IReadOnlyList<ITransformationObserver> observers,
                ILogger<BuiltPipeline> logger)
            {
                _stages = stages;
                _observers = observers;
                _logger = logger;
            }

            public Task<IAsyncEnumerable<PigmentFrame>> ExecuteAsync(
                IAsyncEnumerable<PigmentFrame> source,
                CancellationToken cancellationToken = default)
            {
                if (source == null)
                    throw new ArgumentNullException(nameof(source));

                return Task.FromResult(RunInternalAsync(source, cancellationToken));
            }

            private async IAsyncEnumerable<PigmentFrame> RunInternalAsync(
                IAsyncEnumerable<PigmentFrame> upstream,
                [EnumeratorCancellation] CancellationToken cancellationToken)
            {
                IAsyncEnumerable<PigmentFrame> current = upstream;

                foreach (var stage in _stages)
                {
                    cancellationToken.ThrowIfCancellationRequested();

                    await NotifyStartedAsync(stage, cancellationToken).ConfigureAwait(false);

                    try
                    {
                        current = await stage.ProcessAsync(current, cancellationToken)
                                             .ConfigureAwait(false);

                        await NotifyCompletedAsync(stage, cancellationToken).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        _logger.LogError(ex, "Stage {StageName} threw an exception.", stage.Name);
                        await NotifyErrorAsync(stage, ex, cancellationToken).ConfigureAwait(false);
                        throw; // Bubble up so compensating transactions can kick in upstream.
                    }
                }

                await foreach (var frame in current.WithCancellation(cancellationToken)
                                                   .ConfigureAwait(false))
                {
                    yield return frame;
                }
            }

            #region Observer Helpers

            private Task NotifyStartedAsync(IPipelineStage stage, CancellationToken token)
                => BroadcastAsync(o => o.OnStageStartedAsync(stage.Name, token));

            private Task NotifyCompletedAsync(IPipelineStage stage, CancellationToken token)
                => BroadcastAsync(o => o.OnStageCompletedAsync(stage.Name, token));

            private Task NotifyErrorAsync(IPipelineStage stage, Exception ex, CancellationToken token)
                => BroadcastAsync(o => o.OnStageErrorAsync(stage.Name, ex, token));

            private Task BroadcastAsync(Func<ITransformationObserver, Task> action)
            {
                if (_observers.Count == 0)
                    return Task.CompletedTask;

                var tasks = new List<Task>(_observers.Count);

                foreach (var observer in _observers)
                {
                    try
                    {
                        tasks.Add(action(observer));
                    }
                    catch (Exception ex)
                    {
                        // Ensure an observer failure does not take down the pipeline.
                        _logger.LogWarning(ex, "Observer {ObserverType} threw an exception.", observer.GetType().Name);
                    }
                }

                return Task.WhenAll(tasks);
            }

            #endregion
        }

        #endregion
    }

    #region Example Built-In Stages (For illustration / testability)

    /// <summary>
    /// Sample stage that enriches frames by injecting a new column.
    /// </summary>
    public sealed class EnrichmentStage : IPipelineStage
    {
        private readonly ILogger<EnrichmentStage> _logger;

        public EnrichmentStage(ILogger<EnrichmentStage> logger)
        {
            _logger = logger;
        }

        public string Name => nameof(EnrichmentStage);

        public ValueTask<IAsyncEnumerable<PigmentFrame>> ProcessAsync(IAsyncEnumerable<PigmentFrame> input,
            CancellationToken cancellationToken = default)
        {
            async IAsyncEnumerable<PigmentFrame> Impl(
                IAsyncEnumerable<PigmentFrame> src,
                [EnumeratorCancellation] CancellationToken token)
            {
                await foreach (var frame in src.WithCancellation(token).ConfigureAwait(false))
                {
                    var cols = new Dictionary<string, object?>(frame.Columns)
                    {
                        ["enriched_at"] = DateTimeOffset.UtcNow
                    };

                    _logger.LogTrace("Frame {FrameId} enriched.", frame.Id);

                    yield return frame with { Columns = new ReadOnlyDictionary<string, object?>(cols) };
                }
            }

            return new ValueTask<IAsyncEnumerable<PigmentFrame>>(Impl(input, cancellationToken));
        }
    }

    /// <summary>
    /// Sample quality check stage that validates data rows. Invalid rows are dropped
    /// and surfaced to monitoring via observer notifications.
    /// </summary>
    public sealed class QualityCheckStage : IPipelineStage
    {
        private readonly ILogger<QualityCheckStage> _logger;

        public QualityCheckStage(ILogger<QualityCheckStage> logger)
        {
            _logger = logger;
        }

        public string Name => nameof(QualityCheckStage);

        public ValueTask<IAsyncEnumerable<PigmentFrame>> ProcessAsync(
            IAsyncEnumerable<PigmentFrame> input,
            CancellationToken cancellationToken = default)
        {
            async IAsyncEnumerable<PigmentFrame> Impl(
                IAsyncEnumerable<PigmentFrame> src,
                [EnumeratorCancellation] CancellationToken token)
            {
                await foreach (var frame in src.WithCancellation(token).ConfigureAwait(false))
                {
                    if (!frame.Columns.Any())
                    {
                        _logger.LogWarning("Frame {FrameId} dropped due to empty schema.", frame.Id);
                        continue; // drop
                    }

                    yield return frame;
                }
            }

            return new ValueTask<IAsyncEnumerable<PigmentFrame>>(Impl(input, cancellationToken));
        }
    }

    #endregion
}
```