```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Runtime.Serialization;
using System.Threading;

namespace CanvasCraft.Core.Models
{
    /// <summary>
    /// Represents an end-to-end experiment run captured by CanvasCraft ML Studio.
    /// The class is designed to be thread-safe and raises change notifications so
    /// that observers (dashboards, monitors, etc.) can react in real time.
    /// </summary>
    [DataContract]
    public sealed class Experiment : INotifyPropertyChanged, IEquatable<Experiment>
    {
        private readonly ConcurrentDictionary<string, Parameter> _parameters = new();
        private readonly ConcurrentDictionary<string, MetricSeries> _metrics  = new();
        private readonly ConcurrentBag<Artifact>                 _artifacts = new();

        private readonly ReaderWriterLockSlim _stateLock = new();
        private          ExperimentStatus     _status    = ExperimentStatus.Created;
        private          DateTimeOffset?      _endedOn;

        #region Constructors

        public Experiment(string name, string? description = null, Guid? experimentId = null)
        {
            if (string.IsNullOrWhiteSpace(name))
                throw new ArgumentException("Experiment name cannot be null or whitespace.", nameof(name));

            ExperimentId = experimentId ?? Guid.NewGuid();
            Name         = name.Trim();
            Description  = description?.Trim();
            CreatedOn    = DateTimeOffset.UtcNow;
        }

        #endregion

        #region Properties

        [DataMember(Order = 0)]
        public Guid ExperimentId { get; }

        [DataMember(Order = 1)]
        public string Name { get; }

        [DataMember(Order = 2)]
        public string? Description { get; private set; }

        [DataMember(Order = 3)]
        public DateTimeOffset CreatedOn { get; }

        [DataMember(Order = 4)]
        public DateTimeOffset? EndedOn
        {
            get => _endedOn;
            private set
            {
                if (_endedOn != value)
                {
                    _endedOn = value;
                    OnPropertyChanged();
                }
            }
        }

        [DataMember(Order = 5)]
        public ExperimentStatus Status
        {
            get => _status;
            private set
            {
                if (_status != value)
                {
                    _status = value;
                    OnPropertyChanged();
                }
            }
        }

        /// <summary>
        /// Gets a read-only, thread-safe view of all logged parameters.
        /// </summary>
        public IReadOnlyDictionary<string, Parameter> Parameters =>
            new ReadOnlyDictionary<string, Parameter>(_parameters);

        /// <summary>
        /// Gets a read-only, thread-safe view of all logged metrics.
        /// </summary>
        public IReadOnlyDictionary<string, MetricSeries> Metrics =>
            new ReadOnlyDictionary<string, MetricSeries>(_metrics);

        /// <summary>
        /// Gets a read-only collection of registered artifacts (datasets,
        /// checkpoints, predictions, etc.).
        /// </summary>
        public IReadOnlyCollection<Artifact> Artifacts => _artifacts.ToArray();

        #endregion

        #region Lifecycle Management

        /// <summary>
        /// Marks the experiment as started. If it is already running, no-op.
        /// </summary>
        public void Start()
        {
            _stateLock.EnterWriteLock();
            try
            {
                if (Status == ExperimentStatus.Created)
                    Status = ExperimentStatus.Running;
            }
            finally
            {
                _stateLock.ExitWriteLock();
            }
        }

        /// <summary>
        /// Marks the experiment as successfully completed.
        /// </summary>
        public void Complete()
        {
            _stateLock.EnterWriteLock();
            try
            {
                EnsureRunningState();
                Status  = ExperimentStatus.Completed;
                EndedOn = DateTimeOffset.UtcNow;
            }
            finally
            {
                _stateLock.ExitWriteLock();
            }
        }

        /// <summary>
        /// Marks the experiment as failed with the supplied exception.
        /// </summary>
        public void Fail(Exception reason)
        {
            if (reason is null) throw new ArgumentNullException(nameof(reason));

            _stateLock.EnterWriteLock();
            try
            {
                EnsureRunningState();
                Status        = ExperimentStatus.Failed;
                EndedOn       = DateTimeOffset.UtcNow;
                FailureReason = reason;
            }
            finally
            {
                _stateLock.ExitWriteLock();
            }
        }

        [DataMember(Order = 6)]
        public Exception? FailureReason { get; private set; }

        private void EnsureRunningState()
        {
            if (Status != ExperimentStatus.Running)
                throw new InvalidOperationException(
                    $"Experiment must be in '{ExperimentStatus.Running}' state. Current state: {Status}");
        }

        #endregion

        #region Parameter & Metric Logging

        public void LogParameter(string key, object? value, string? description = null)
        {
            if (string.IsNullOrWhiteSpace(key))
                throw new ArgumentException("Parameter key cannot be null or whitespace.", nameof(key));

            _parameters.AddOrUpdate(
                key.Trim(),
                k => new Parameter(k, value, description),
                (_, existing) => existing with
                {
                    Value       = value,
                    Description = description
                });

            OnPropertyChanged(nameof(Parameters));
        }

        /// <summary>
        /// Records a numeric metric point at the current time.
        /// Multiple points for a metric create a time-series.
        /// </summary>
        public void LogMetric(string name, double value, DateTimeOffset? timestamp = null)
        {
            if (string.IsNullOrWhiteSpace(name))
                throw new ArgumentException("Metric name cannot be null or whitespace.", nameof(name));

            var ts = timestamp ?? DateTimeOffset.UtcNow;

            _metrics.AddOrUpdate(
                name.Trim(),
                _ => new MetricSeries(name.Trim()) { new MetricPoint(value, ts) },
                (_, series) =>
                {
                    series.Add(new MetricPoint(value, ts));
                    return series;
                });

            OnPropertyChanged(nameof(Metrics));
        }

        #endregion

        #region Artifact Registration

        public void RegisterArtifact(Artifact artifact)
        {
            if (artifact is null) throw new ArgumentNullException(nameof(artifact));

            _artifacts.Add(artifact);
            OnPropertyChanged(nameof(Artifacts));
        }

        #endregion

        #region Snapshots & Serialization

        /// <summary>
        /// Captures an immutable snapshot of the experiment for persistence.
        /// </summary>
        public ExperimentSnapshot Snapshot()
        {
            return new ExperimentSnapshot(
                ExperimentId,
                Name,
                Description,
                CreatedOn,
                EndedOn,
                Status,
                new Dictionary<string, Parameter>(_parameters),
                new Dictionary<string, MetricSeries>(_metrics),
                new List<Artifact>(_artifacts),
                FailureReason?.ToString());
        }

        #endregion

        #region IEquatable / overrides

        public bool Equals(Experiment? other) =>
            other is not null && ExperimentId.Equals(other.ExperimentId);

        public override bool Equals(object? obj) => Equals(obj as Experiment);

        public override int GetHashCode() => ExperimentId.GetHashCode();

        public override string ToString() => $"{Name} ({ExperimentId}) - {Status}";

        #endregion

        #region INotifyPropertyChanged

        public event PropertyChangedEventHandler? PropertyChanged;

        private void OnPropertyChanged([CallerMemberName] string? propertyName = null) =>
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

        #endregion
    }

    #region Supporting Types

    /// <summary>
    /// Status lifecycle for an experiment.
    /// </summary>
    public enum ExperimentStatus
    {
        Created,
        Running,
        Completed,
        Failed
    }

    /// <summary>
    /// Immutable representation of an experiment parameter.
    /// </summary>
    [DataContract]
    public record Parameter(
        [property: DataMember(Order = 0)] string Key,
        [property: DataMember(Order = 1)] object? Value,
        [property: DataMember(Order = 2)] string? Description);

    /// <summary>
    /// Represents a single measurement in a metric time-series.
    /// </summary>
    [DataContract]
    public record MetricPoint(
        [property: DataMember(Order = 0)] double Value,
        [property: DataMember(Order = 1)] DateTimeOffset Timestamp);

    /// <summary>
    /// Represents a collection of metric points for a single metric name.
    /// </summary>
    [CollectionDataContract]
    public sealed class MetricSeries : Collection<MetricPoint>
    {
        public MetricSeries(string name)
        {
            Name = name ?? throw new ArgumentNullException(nameof(name));
        }

        [DataMember(Order = 0)]
        public string Name { get; }
    }

    /// <summary>
    /// Represents a data or model artifact produced/consumed by an experiment.
    /// </summary>
    [DataContract]
    public record Artifact(
        [property: DataMember(Order = 0)] string Name,
        [property: DataMember(Order = 1)] Uri Location,
        [property: DataMember(Order = 2)] ArtifactType Type,
        [property: DataMember(Order = 3)] DateTimeOffset CreatedOn);

    public enum ArtifactType
    {
        Dataset,
        ModelCheckpoint,
        VisualOutput,
        AudioOutput,
        TextOutput,
        Other
    }

    /// <summary>
    /// DTO used for persistent storage of immutable experiment state.
    /// </summary>
    [DataContract]
    public record ExperimentSnapshot(
        [property: DataMember(Order = 0)] Guid ExperimentId,
        [property: DataMember(Order = 1)] string Name,
        [property: DataMember(Order = 2)] string? Description,
        [property: DataMember(Order = 3)] DateTimeOffset CreatedOn,
        [property: DataMember(Order = 4)] DateTimeOffset? EndedOn,
        [property: DataMember(Order = 5)] ExperimentStatus Status,
        [property: DataMember(Order = 6)] IReadOnlyDictionary<string, Parameter> Parameters,
        [property: DataMember(Order = 7)] IReadOnlyDictionary<string, MetricSeries> Metrics,
        [property: DataMember(Order = 8)] IReadOnlyCollection<Artifact> Artifacts,
        [property: DataMember(Order = 9)] string? FailureReason);

    #endregion
}
```