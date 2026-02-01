```csharp
// File: PaletteStream-ETL-Canvas/src/Shared/PaletteStream.Shared.Models/PipelineStatus.cs

using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;
using System.Threading;

namespace PaletteStream.Shared.Models
{
    /// <summary>
    /// Represents the finite states through which an ETL pipeline moves while processing data.
    /// </summary>
    [JsonConverter(typeof(JsonStringEnumConverter))]
    public enum PipelineState
    {
        Unknown            = 0,
        NotStarted         = 1,
        Queued             = 2,
        Running            = 3,
        Succeeded          = 4,
        Failed             = 5,
        Cancelled          = 6,
        PartiallySucceeded = 7,
    }

    /// <summary>
    /// Immutable snapshot that describes the current status of a pipeline execution.
    /// </summary>
    /// <remarks>
    /// The <see cref="PipelineStatus"/> record is designed to be passed across service boundaries
    /// (e.g. gRPC, REST, message queues) and therefore focuses on serialization–friendly types.
    /// </remarks>
    public sealed record PipelineStatus
    {
        /// <summary>
        /// Represents the ID of the pipeline instance. 
        /// Correlates to an execution/RunId—not a definition template.
        /// </summary>
        public Guid PipelineId { get; init; }

        /// <summary>
        /// The current lifecycle state of the pipeline.
        /// </summary>
        public PipelineState State { get; init; }

        /// <summary>
        /// Optional diagnostics or human–readable context for the current state.
        /// Typically populated on failures or cancellations.
        /// </summary>
        public string? Message { get; init; }

        /// <summary>
        /// When the pipeline was created / first enqueued.
        /// </summary>
        public DateTimeOffset CreatedAt { get; init; }

        /// <summary>
        /// When the pipeline last transitioned state.
        /// </summary>
        public DateTimeOffset UpdatedAt { get; init; }

        /// <summary>
        /// Arbitrary metadata emitted by strategy–specific processors.
        /// </summary>
        public IDictionary<string, string>? Metadata { get; init; }

        /// <summary>
        /// A monotonically–increasing number that increments with every state transition.
        /// Enables optimistic concurrency control across distributed services (e.g. CAS in Cosmos DB).
        /// </summary>
        public long Version { get; init; }

        private static readonly IReadOnlyDictionary<PipelineState, PipelineState[]> VALID_TRANSITIONS =
            new Dictionary<PipelineState, PipelineState[]>
            {
                { PipelineState.Unknown,            new[] { PipelineState.NotStarted } },
                { PipelineState.NotStarted,         new[] { PipelineState.Queued } },
                { PipelineState.Queued,             new[] { PipelineState.Running, PipelineState.Cancelled } },
                { PipelineState.Running,            new[] { PipelineState.Succeeded, PipelineState.Failed, PipelineState.PartiallySucceeded, PipelineState.Cancelled } },
                { PipelineState.PartiallySucceeded, new[] { PipelineState.Running, PipelineState.Succeeded, PipelineState.Failed, PipelineState.Cancelled } },
                { PipelineState.Succeeded,          Array.Empty<PipelineState>() },
                { PipelineState.Failed,             Array.Empty<PipelineState>() },
                { PipelineState.Cancelled,          Array.Empty<PipelineState>() },
            };

        #region Factory helpers

        /// <summary>
        /// Factory for a brand–new pipeline status.
        /// </summary>
        public static PipelineStatus Create(Guid pipelineId) => new()
        {
            PipelineId = pipelineId,
            State      = PipelineState.NotStarted,
            CreatedAt  = DateTimeOffset.UtcNow,
            UpdatedAt  = DateTimeOffset.UtcNow,
            Version    = 0
        };

        #endregion

        #region Transition helpers

        /// <summary>
        /// Returns a new <see cref="PipelineStatus"/> with its <see cref="State"/> field mutated—if valid.
        /// </summary>
        /// <exception cref="InvalidPipelineStateTransitionException"/>
        public PipelineStatus WithState(PipelineState newState, string? message = null,
                                        IDictionary<string, string>? metadata = null)
        {
            if (State == newState) return this; // No-op.

            if (!IsValidTransition(State, newState))
                throw new InvalidPipelineStateTransitionException(PipelineId, State, newState);

            return this with
            {
                State     = newState,
                Message   = message,
                Metadata  = metadata ?? Metadata,
                UpdatedAt = DateTimeOffset.UtcNow,
                Version   = checked(Version + 1)
            };
        }

        /// <summary>
        /// Computes whether <paramref name="to"/> is a valid successsor of <paramref name="from"/>.
        /// </summary>
        public static bool IsValidTransition(PipelineState from, PipelineState to)
            => VALID_TRANSITIONS.TryGetValue(from, out var allowed) && Array.Exists(allowed, s => s == to);

        #endregion

        public override string ToString() =>
            $"PipelineStatus(Id={PipelineId}, State={State}, Version={Version}, UpdatedAt={UpdatedAt:O})";
    }

    /// <summary>
    /// Thrown when attempting to execute an invalid state transition on a <see cref="PipelineStatus"/>.
    /// </summary>
    public sealed class InvalidPipelineStateTransitionException : Exception
    {
        /// <inheritdoc/>
        public InvalidPipelineStateTransitionException(Guid pipelineId, PipelineState from, PipelineState to)
            : base($"Invalid pipeline state transition for PipelineId: {pipelineId}. {from} ➜ {to}.")
        {
            PipelineId = pipelineId;
            From       = from;
            To         = to;
        }

        public Guid PipelineId { get; }
        public PipelineState From { get; }
        public PipelineState To   { get; }
    }

    /// <summary>
    /// Provides thread–safe state transition utilities for <see cref="PipelineStatus"/>.
    /// </summary>
    public static class PipelineStatusExtensions
    {
        /// <summary>
        /// Atomically applies a state transition with optimistic concurrency guarantees.
        /// </summary>
        /// <param name="current">The current <see cref="PipelineStatus"/> snapshot.</param>
        /// <param name="desired">A delegate that produces a mutated copy of <paramref name="current"/>.</param>
        /// <param name="compareExchange">
        /// Delegate that returns the original value before the exchange, mirroring
        /// <see cref="Interlocked.CompareExchange{T}(ref T, T, T)"/>.
        /// </param>
        /// <returns>The updated <see cref="PipelineStatus"/>.</returns>
        /// <exception cref="InvalidOperationException">If concurrency violated.</exception>
        public static PipelineStatus UpdateAtomically(
            this PipelineStatus current,
            Func<PipelineStatus, PipelineStatus> desired,
            Func<PipelineStatus, PipelineStatus, PipelineStatus> compareExchange)
        {
            PipelineStatus snapshot = current;
            while (true)
            {
                var updated = desired(snapshot);

                // Attempt compare–exchange (CAS).
                var original = compareExchange(updated, snapshot);
                if (ReferenceEquals(original, snapshot))
                    return updated; // Successfully swapped.

                // Someone else modified; retry.
                snapshot = original;
            }
        }
    }
}
```