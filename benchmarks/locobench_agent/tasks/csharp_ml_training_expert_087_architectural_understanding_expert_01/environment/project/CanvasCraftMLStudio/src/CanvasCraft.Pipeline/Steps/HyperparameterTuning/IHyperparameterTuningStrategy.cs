using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

using CanvasCraft.Core.Models;
using CanvasCraft.Core.Training;

namespace CanvasCraft.Pipeline.Steps.HyperparameterTuning
{
    /// <summary>
    /// Contract for any hyper-parameter tuning strategy used inside the CanvasCraft
    /// MLOps pipeline.  Implementations are expected to generate candidate
    /// hyper-parameter configurations, dispatch training jobs, evaluate metrics,
    /// and return the best configuration discovered.
    /// </summary>
    public interface IHyperparameterTuningStrategy : IDisposable
    {
        /// <summary>
        /// Observable stream that emits an event every time a single trial
        /// completes.  Down-stream components (dashboards, early-stoppers,
        /// alerting mechanisms) subscribe to this stream to react in real-time.
        /// </summary>
        IObservable<TrialCompletedEventArgs> TrialCompletedStream { get; }

        /// <summary>
        /// Runs the optimization routine over a given <paramref name="searchSpace"/>.
        /// </summary>
        /// <param name="context">
        ///     Describes the data set, feature store, and delegate used to build
        ///     and train a model given a hyper-parameter set.
        /// </param>
        /// <param name="searchSpace">
        ///     The hyper-parameter search space to explore.
        /// </param>
        /// <param name="maxTrials">
        ///     An optional hard cap on the total number of trials to execute.
        ///     When <c>null</c>, the strategy decides internally.
        /// </param>
        /// <param name="cancellationToken">
        ///     Token used to cancel the optimization routine part-way through.
        /// </param>
        /// <returns>
        ///     A <see cref="HyperparameterTuningResult"/> containing the best
        ///     hyper-parameter configuration and metrics, as well as a complete
        ///     history of every trial run.
        /// </returns>
        Task<HyperparameterTuningResult> OptimizeAsync(
            ModelTrainingContext            context,
            HyperparameterSearchSpace       searchSpace,
            int?                            maxTrials          = null,
            CancellationToken               cancellationToken  = default);

        /// <summary>
        /// Validates that the supplied search space is compatible with the tuning strategy.
        /// </summary>
        /// <exception cref="ArgumentException">
        /// Thrown when the search space violates constraints of the strategy.
        /// </exception>
        void ValidateSearchSpace(HyperparameterSearchSpace searchSpace);
    }

    #region Support DTOs & Domain Types

    /// <summary>
    /// Event payload published when a hyper-parameter trial finishes.
    /// </summary>
    public sealed class TrialCompletedEventArgs : EventArgs
    {
        internal TrialCompletedEventArgs(
            IReadOnlyDictionary<string, object> hyperparameters,
            MetricSet                          metrics,
            int                                trialNumber,
            TimeSpan                           duration)
        {
            Hyperparameters = hyperparameters 
                              ?? throw new ArgumentNullException(nameof(hyperparameters));
            Metrics         = metrics ?? throw new ArgumentNullException(nameof(metrics));
            TrialNumber     = trialNumber;
            Duration        = duration;
        }

        public IReadOnlyDictionary<string, object> Hyperparameters { get; }
        public MetricSet                           Metrics         { get; }
        public int                                TrialNumber     { get; }
        public TimeSpan                           Duration        { get; }
    }

    /// <summary>
    /// The aggregated result of an optimization run.
    /// </summary>
    public sealed class HyperparameterTuningResult
    {
        public HyperparameterTuningResult(
            IReadOnlyDictionary<string, object> bestHyperparameters,
            MetricSet                          bestMetric,
            IReadOnlyList<TrialCompletedEventArgs> allTrials)
        {
            BestHyperparameters = bestHyperparameters 
                                  ?? throw new ArgumentNullException(nameof(bestHyperparameters));
            BestMetric = bestMetric ?? throw new ArgumentNullException(nameof(bestMetric));
            AllTrials = allTrials ?? throw new ArgumentNullException(nameof(allTrials));

            CompletedAt = DateTimeOffset.UtcNow;
        }

        public IReadOnlyDictionary<string, object>   BestHyperparameters { get; }
        public MetricSet                             BestMetric         { get; }
        public IReadOnlyList<TrialCompletedEventArgs> AllTrials         { get; }
        public DateTimeOffset                        CompletedAt        { get; }

        /// <summary>
        /// Convenience method that serializes the result to JSON for experiment tracking.
        /// </summary>
        public string ToJson() =>
            System.Text.Json.JsonSerializer.Serialize(
                this,
                new System.Text.Json.JsonSerializerOptions
                {
                    WriteIndented = false,
                    Converters    = { new System.Text.Json.Serialization.JsonStringEnumConverter() }
                });
    }

    /// <summary>
    /// Encapsulates the hyper-parameter dimensions that comprise a search space.
    /// </summary>
    public sealed class HyperparameterSearchSpace
    {
        public HyperparameterSearchSpace(IDictionary<string, SearchDimension> dimensions)
        {
            if (dimensions == null)
                throw new ArgumentNullException(nameof(dimensions));
            if (dimensions.Count == 0)
                throw new ArgumentException("A search space must contain at least one dimension.",
                                            nameof(dimensions));

            Dimensions = new Dictionary<string, SearchDimension>(dimensions,
                                                                 StringComparer.OrdinalIgnoreCase);
        }

        /// <summary>
        /// Gets the search-space dimensions keyed by hyper-parameter name.
        /// </summary>
        public IReadOnlyDictionary<string, SearchDimension> Dimensions { get; }

        /// <summary>
        /// Computes a deterministic SHA-256 hash of the search-space definition so that
        /// experiment tracking can identify unique spaces even across processes.
        /// </summary>
        public string ComputeHash()
        {
            var buffer = new System.Text.StringBuilder();
            foreach (var kvp in Dimensions.OrderBy(k => k.Key, StringComparer.OrdinalIgnoreCase))
            {
                buffer.Append(kvp.Key)
                      .Append(':')
                      .Append(kvp.Value)
                      .Append('|');
            }

            using var sha = System.Security.Cryptography.SHA256.Create();
            return Convert.ToHexString(
                sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(buffer.ToString())));
        }
    }

    /// <summary>
    /// Base class for any dimension that can be used in <see cref="HyperparameterSearchSpace"/>.
    /// </summary>
    public abstract class SearchDimension
    {
        /// <summary>
        /// Samples a single value from the dimension using the provided RNG.
        /// </summary>
        public abstract object Sample(Random random);

        /// <summary>
        /// Determines whether the candidate value belongs to the dimension.
        /// </summary>
        public abstract bool Contains(object candidate);
    }

    /// <summary>
    /// Represents a continuous or discrete numeric range.
    /// </summary>
    public sealed class RangeDimension<T> : SearchDimension where T : IComparable<T>
    {
        public RangeDimension(T min, T max, bool inclusive = true)
        {
            if (min.CompareTo(max) > 0)
                throw new ArgumentException("Min must be less than or equal to Max.");

            Min       = min;
            Max       = max;
            Inclusive = inclusive;
        }

        public T     Min       { get; }
        public T     Max       { get; }
        public bool  Inclusive { get; }

        public override object Sample(Random random)
        {
            if (typeof(T) == typeof(int))
            {
                int min = Convert.ToInt32(Min);
                int max = Convert.ToInt32(Max);

                int value = random.Next(min, Inclusive ? max + 1 : max);
                return (T)(object)value;
            }

            if (typeof(T) == typeof(double))
            {
                double min = Convert.ToDouble(Min);
                double max = Convert.ToDouble(Max);
                double val = random.NextDouble() * (max - min) + min;

                // If we sampled the exclusive upper bound, adjust slightly
                if (!Inclusive && Math.Abs(val - max) < double.Epsilon)
                    val = Math.BitIncrement(val);

                return (T)(object)val;
            }

            throw new NotSupportedException($"Sampling not supported for type {typeof(T)}.");
        }

        public override bool Contains(object candidate)
        {
            if (candidate is not T value)
                return false;

            int lower = value.CompareTo(Min);
            int upper = value.CompareTo(Max);

            return Inclusive
                ? lower >= 0 && upper <= 0
                : lower >= 0 && upper < 0;
        }

        public override string ToString() => $"[{Min}, {Max}]{(Inclusive ? "" : ")")}";
    }

    /// <summary>
    /// Represents a finite set of categorical options.
    /// </summary>
    public sealed class CategoricalDimension : SearchDimension
    {
        private readonly IReadOnlyList<object> _choices;

        public CategoricalDimension(IEnumerable<object> choices)
        {
            if (choices == null)
                throw new ArgumentNullException(nameof(choices));

            _choices = choices.Distinct().ToArray();

            if (_choices.Count == 0)
                throw new ArgumentException("At least one choice must be specified.", nameof(choices));
        }

        public IReadOnlyList<object> Choices => _choices;

        public override object Sample(Random random)
        {
            int idx = random.Next(0, _choices.Count);
            return _choices[idx];
        }

        public override bool Contains(object candidate) => _choices.Contains(candidate);

        public override string ToString() => $"{{{string.Join(", ", _choices)}}}";
    }

    #endregion
}