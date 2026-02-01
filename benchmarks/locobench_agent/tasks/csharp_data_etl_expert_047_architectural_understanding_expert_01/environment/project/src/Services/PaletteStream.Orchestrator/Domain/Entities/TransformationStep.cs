```csharp
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Linq;

namespace PaletteStream.Orchestrator.Domain.Entities
{
    /// <summary>
    /// Represents a single, atomic transformation (a “brush-stroke”) within an ETL pipeline.
    /// Immutable state transitions are enforced so that a step can only move
    ///      Pending ➜ Running ➜ Completed/Failed.
    /// </summary>
    [Serializable]
    public sealed class TransformationStep : IEquatable<TransformationStep>, ICloneable
    {
        #region Factory

        /// <summary>
        /// Creates a new <see cref="TransformationStep"/> in <see cref="StepStatus.Pending"/> state.
        /// </summary>
        public static TransformationStep Create(
            string name,
            TransformationStrategyType strategyType,
            int sequenceOrder,
            string? description            = null,
            IEnumerable<string>? tags      = null,
            IDictionary<string, string>? parameters = null)
        {
            if (string.IsNullOrWhiteSpace(name))
                throw new ArgumentException("Step name must be provided.", nameof(name));

            if (sequenceOrder < 0)
                throw new ArgumentOutOfRangeException(nameof(sequenceOrder), "Sequence order must be non-negative.");

            return new TransformationStep(
                id: Guid.NewGuid(),
                name: name,
                description: description,
                sequenceOrder: sequenceOrder,
                strategyType: strategyType,
                tags: tags,
                parameters: parameters);
        }

        #endregion

        #region Ctor / Private Setters

        private TransformationStep(
            Guid id,
            string name,
            string? description,
            int sequenceOrder,
            TransformationStrategyType strategyType,
            IEnumerable<string>? tags,
            IDictionary<string, string>? parameters)
        {
            Id               = id;
            Name             = name;
            Description      = description ?? string.Empty;
            SequenceOrder    = sequenceOrder;
            StrategyType     = strategyType;

            _tags            = tags?.Distinct(StringComparer.OrdinalIgnoreCase).ToList() ??
                               new List<string>();

            _parameters      = parameters != null
                               ? new Dictionary<string, string>(parameters, StringComparer.OrdinalIgnoreCase)
                               : new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

            Status           = StepStatus.Pending;
            CreatedAtUtc     = DateTimeOffset.UtcNow;
        }

        #endregion

        #region Public Properties

        public Guid Id { get; }

        /// <summary>Human-friendly name.</summary>
        public string Name { get; private set; }

        /// <summary>Optional rich description.</summary>
        public string Description { get; private set; }

        /// <summary>Zero-based ordering of the step inside a pipeline.</summary>
        public int SequenceOrder { get; private set; }

        /// <summary>Logical identifier of the strategy that will execute this step.</summary>
        public TransformationStrategyType StrategyType { get; private set; }

        /// <summary>Key/Value parameters supplied to the strategy implementation.</summary>
        public IReadOnlyDictionary<string, string> Parameters =>
            new ReadOnlyDictionary<string, string>(_parameters);

        /// <summary>User-defined labels that can be queried/filterd against.</summary>
        public IReadOnlyCollection<string> Tags => _tags.AsReadOnly();

        /// <summary>Lifecycle status.</summary>
        public StepStatus Status { get; private set; }

        /// <summary>Creation timestamp (UTC).</summary>
        public DateTimeOffset CreatedAtUtc { get; }

        /// <summary>Start of execution (UTC).</summary>
        public DateTimeOffset? StartedAtUtc { get; private set; }

        /// <summary>Completion timestamp (UTC) – populated on success only.</summary>
        public DateTimeOffset? CompletedAtUtc { get; private set; }

        /// <summary>Error timestamp (UTC) – populated on failure only.</summary>
        public DateTimeOffset? FailedAtUtc { get; private set; }

        /// <summary>Error captured if <see cref="Status"/> == <see cref="StepStatus.Failed"/>.</summary>
        public string? ErrorMessage { get; private set; }

        /// <summary>Full stack trace captured if the step failed.</summary>
        public string? StackTrace { get; private set; }

        /// <summary>Concurrency token suitable for optimistic locking.</summary>
        public long RowVersion { get; private set; } = DateTime.UtcNow.Ticks;

        #endregion

        #region State Transitions

        /// <summary>Marks the step as <see cref="StepStatus.Running"/>.</summary>
        public void Start()
        {
            EnsureTransitionAllowed(expectedCurrent: StepStatus.Pending, next: StepStatus.Running);

            StartedAtUtc = DateTimeOffset.UtcNow;
            Status       = StepStatus.Running;
            Touch();
        }

        /// <summary>Marks the step as <see cref="StepStatus.Completed"/>.</summary>
        public void Complete()
        {
            EnsureTransitionAllowed(expectedCurrent: StepStatus.Running, next: StepStatus.Completed);

            CompletedAtUtc = DateTimeOffset.UtcNow;
            Status         = StepStatus.Completed;
            Touch();
        }

        /// <summary>Marks the step as <see cref="StepStatus.Failed"/> and records the error.</summary>
        public void Fail(Exception ex)
        {
            if (ex is null) throw new ArgumentNullException(nameof(ex));

            EnsureTransitionAllowed(expectedCurrent: StepStatus.Running, next: StepStatus.Failed);

            FailedAtUtc  = DateTimeOffset.UtcNow;
            Status       = StepStatus.Failed;
            ErrorMessage = ex.Message;
            StackTrace   = ex.ToString();
            Touch();
        }

        /// <summary>Modifies/creates a parameter – only allowed while Pending.</summary>
        public void SetParameter(string key, string value)
        {
            if (Status != StepStatus.Pending)
                throw new InvalidOperationException("Parameters can only be changed while the step is pending.");

            if (string.IsNullOrWhiteSpace(key))
                throw new ArgumentException("Key must be provided.", nameof(key));

            _parameters[key] = value ?? string.Empty;
            Touch();
        }

        /// <summary>Renames the step – only allowed while Pending.</summary>
        public void Rename(string newName)
        {
            if (Status != StepStatus.Pending)
                throw new InvalidOperationException("Name can only be changed while the step is pending.");

            if (string.IsNullOrWhiteSpace(newName))
                throw new ArgumentException("New name must be provided.", nameof(newName));

            Name = newName;
            Touch();
        }

        #endregion

        #region Equality & Clone

        public bool Equals(TransformationStep? other)
            => other != null && other.Id == Id;

        public override bool Equals(object? obj)
            => Equals(obj as TransformationStep);

        public override int GetHashCode()
            => Id.GetHashCode();

        public object Clone()
            => MemberwiseClone();

        #endregion

        #region Private Helpers

        private void EnsureTransitionAllowed(StepStatus expectedCurrent, StepStatus next)
        {
            if (Status != expectedCurrent)
            {
                throw new InvalidOperationException(
                    $"Invalid state transition. Current: {Status}, Expected: {expectedCurrent}, Requested: {next}");
            }
        }

        private void Touch() => RowVersion = DateTime.UtcNow.Ticks;

        #endregion

        #region Backing Stores

        private readonly List<string> _tags;
        private readonly Dictionary<string, string> _parameters;

        #endregion
    }

    /// <summary>Finite state-machine representing the lifecycle of a step.</summary>
    public enum StepStatus
    {
        Pending   = 0,
        Running   = 1,
        Completed = 2,
        Failed    = 3
    }

    /// <summary>
    /// Enumeration of supported transformation strategy types.
    /// Concrete implementations live in Strategy layer and resolved via IoC/SOA.
    /// </summary>
    public enum TransformationStrategyType
    {
        Aggregation,
        Enrichment,
        Anonymization,
        Filtering,
        Mapping,
        Validation,
        Custom // Catch-all for extensions
    }
}
```