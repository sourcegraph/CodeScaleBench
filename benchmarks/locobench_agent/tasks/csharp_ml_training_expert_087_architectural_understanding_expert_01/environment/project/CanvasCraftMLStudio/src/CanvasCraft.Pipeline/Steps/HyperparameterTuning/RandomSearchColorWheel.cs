```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Core.Tracking;
using CanvasCraft.Core.Logging;
using CanvasCraft.Pipeline.Events;

namespace CanvasCraft.Pipeline.Steps.HyperparameterTuning
{
    /// <summary>
    /// A “color wheel” implementation that performs random search over the provided hyper-parameter
    /// search space.  Each sampled configuration is interpreted as a unique color hue in the
    /// creative ML workflow metaphor.
    /// </summary>
    /// <remarks>
    /// The tuner is thread-safe and can run evaluation trials in parallel.  
    /// Results are streamed to the configured <see cref="IExperimentTracker"/> and published
    /// to the pipeline event bus so that downstream observers (dashboards, alerts, etc.) can
    /// react to intermediate findings in near real-time.
    /// </remarks>
    public sealed class RandomSearchColorWheel : IHyperparameterTuner, IDisposable
    {
        private readonly IExperimentTracker _tracker;
        private readonly ILogger _logger;
        private readonly IEventBus _eventBus;
        private readonly Random _random;
        private readonly CancellationTokenSource _internalCts = new();
        private readonly ConcurrentDictionary<int, HyperparameterTrialResult> _results = new();

        public RandomSearchColorWheel(
            IExperimentTracker tracker,
            ILogger logger,
            IEventBus eventBus,
            int? seed = null)
        {
            _tracker   = tracker  ?? throw new ArgumentNullException(nameof(tracker));
            _logger    = logger   ?? throw new ArgumentNullException(nameof(logger));
            _eventBus  = eventBus ?? throw new ArgumentNullException(nameof(eventBus));
            _random    = new Random(seed ?? Environment.TickCount);
        }

        /// <inheritdoc/>
        public async Task<HyperparameterTuningSummary> ExecuteAsync(
            HyperparameterSearchSpace searchSpace,
            Func<IReadOnlyDictionary<string, object>, Task<TrialMetric>> evaluateAsync,
            HyperparameterTuningOptions options,
            CancellationToken externalToken = default)
        {
            ArgumentNullException.ThrowIfNull(searchSpace);
            ArgumentNullException.ThrowIfNull(evaluateAsync);
            ArgumentNullException.ThrowIfNull(options);

            using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(
                externalToken, _internalCts.Token);
            var token = linkedCts.Token;

            _logger.Info($"🎨 Starting random search color wheel with {options.MaxTrials} trials.");

            var semaphore = new SemaphoreSlim(options.MaxDegreeOfParallelism);
            var tasks     = new List<Task>();

            for (var trialIndex = 0; trialIndex < options.MaxTrials && !token.IsCancellationRequested; trialIndex++)
            {
                await semaphore.WaitAsync(token).ConfigureAwait(false);

                tasks.Add(Task.Run(async () =>
                {
                    try
                    {
                        var sampledParams = Sample(searchSpace);
                        _logger.Debug($"Trial {trialIndex} ▶ Parameters: {FormatParams(sampledParams)}");

                        var metric = await evaluateAsync(sampledParams).ConfigureAwait(false);

                        var result = new HyperparameterTrialResult(
                            trialIndex,
                            sampledParams,
                            metric);

                        _results[trialIndex] = result;

                        await _tracker.LogTrialAsync(result, token).ConfigureAwait(false);
                        await _eventBus.PublishAsync(new TrialCompletedEvent(result), token).ConfigureAwait(false);

                        _logger.Info($"Trial {trialIndex} ✔ Metric={metric.Score:n4}");
                    }
                    catch (OperationCanceledException) { /* bubbling handled below */ }
                    catch (Exception ex)
                    {
                        _logger.Error($"Trial {trialIndex} ✖ {ex}");
                        await _tracker.LogErrorAsync(trialIndex, ex, token).ConfigureAwait(false);
                    }
                    finally
                    {
                        semaphore.Release();
                    }
                }, token));
            }

            await Task.WhenAll(tasks).ConfigureAwait(false);

            var best = _results.Values
                               .OrderByDescending(r => r.Metric.Score) // Higher is better by default
                               .FirstOrDefault();

            var summary = new HyperparameterTuningSummary(
                trials: _results.Count,
                bestTrialResult: best);

            await _tracker.LogSummaryAsync(summary, token).ConfigureAwait(false);

            _logger.Info($"🎨 Random search completed. Best trial={best?.TrialIndex}, Score={best?.Metric.Score:n4}");
            return summary;
        }

        public void Cancel() => _internalCts.Cancel();

        /// <inheritdoc/>
        public void Dispose() => _internalCts.Cancel();

        #region Helpers

        private IReadOnlyDictionary<string, object> Sample(HyperparameterSearchSpace space)
        {
            var dict = new Dictionary<string, object>(space.Count);

            foreach (var (name, descriptor) in space)
            {
                dict[name] = descriptor switch
                {
                    IntRange i      => _random.Next(i.Min, i.Max + 1),
                    DoubleRange d   => _random.NextDouble() * (d.Max - d.Min) + d.Min,
                    CategoricalSet c=> c.Values[_random.Next(c.Values.Count)],
                    _               => throw new NotSupportedException($"Unknown descriptor type {descriptor.GetType().Name}")
                };
            }

            return dict;
        }

        private static string FormatParams(IReadOnlyDictionary<string, object> p) =>
            string.Join(", ", p.Select(kv => $"{kv.Key}={kv.Value}"));

        #endregion
    }

    #region DTOs & Interfaces (minimal stubs)

    // These are intentionally lightweight so the file remains self-contained.
    // In a real solution they would live in dedicated assemblies.

    public interface IHyperparameterTuner
    {
        Task<HyperparameterTuningSummary> ExecuteAsync(
            HyperparameterSearchSpace searchSpace,
            Func<IReadOnlyDictionary<string, object>, Task<TrialMetric>> evaluateAsync,
            HyperparameterTuningOptions options,
            CancellationToken cancellationToken = default);
        void Cancel();
    }

    public record HyperparameterTuningOptions(
        int MaxTrials,
        int MaxDegreeOfParallelism = 1);

    public record TrialMetric(
        double Score,
        IDictionary<string, double>? AdditionalMetrics = null);

    public record HyperparameterTrialResult(
        int TrialIndex,
        IReadOnlyDictionary<string, object> Parameters,
        TrialMetric Metric);

    public record HyperparameterTuningSummary(
        int Trials,
        HyperparameterTrialResult? BestTrialResult);

    public interface IExperimentTracker
    {
        Task LogTrialAsync(HyperparameterTrialResult result, CancellationToken token);
        Task LogErrorAsync(int trialIndex, Exception exception, CancellationToken token);
        Task LogSummaryAsync(HyperparameterTuningSummary summary, CancellationToken token);
    }

    public interface ILogger
    {
        void Info(string message);
        void Debug(string message);
        void Error(string message);
    }

    public interface IEventBus
    {
        Task PublishAsync<TEvent>(TEvent @event, CancellationToken token);
    }

    /// <summary>Base type for hyper-parameter descriptors.</summary>
    public abstract record HyperparameterDescriptor;

    public record IntRange(int Min, int Max)                       : HyperparameterDescriptor;
    public record DoubleRange(double Min, double Max)              : HyperparameterDescriptor;
    public record CategoricalSet(IReadOnlyList<object> Values)     : HyperparameterDescriptor;

    public class HyperparameterSearchSpace : Dictionary<string, HyperparameterDescriptor> { }

    public record TrialCompletedEvent(HyperparameterTrialResult Result);

    #endregion
}
```