```csharp
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace CanvasCraft.Pipeline.Steps
{
    /// <summary>
    /// Indicates the current life-cycle state of a pipeline step.
    /// </summary>
    public enum PipelineStepStatus
    {
        /// <summary>The step has been constructed but not yet executed.</summary>
        Created = 0,

        /// <summary>The step is waiting for its turn in the execution queue.</summary>
        Pending = 1,

        /// <summary>The step is currently executing.</summary>
        Running = 2,

        /// <summary>The step finished successfully.</summary>
        Succeeded = 3,

        /// <summary>The step finished but produced a warning (e.g. degraded performance).</summary>
        CompletedWithWarning = 4,

        /// <summary>The step was cancelled by the user or upstream failure.</summary>
        Cancelled = 5,

        /// <summary>The step failed with an unrecoverable exception.</summary>
        Failed = 6
    }

    /// <summary>
    /// Payload emitted when the status of the step changes.
    /// </summary>
    public sealed class PipelineStepStatusChangedEventArgs : EventArgs
    {
        public PipelineStepStatusChangedEventArgs(PipelineStepStatus previous, PipelineStepStatus current, Exception? error)
        {
            PreviousStatus = previous;
            CurrentStatus  = current;
            Error          = error;
        }

        public PipelineStepStatus PreviousStatus { get; }
        public PipelineStepStatus CurrentStatus  { get; }
        public Exception?         Error          { get; }
    }

    /// <summary>
    /// Payload emitted when a step wishes to report progress.
    /// </summary>
    public sealed class PipelineStepProgressChangedEventArgs : EventArgs
    {
        public PipelineStepProgressChangedEventArgs(double progress, string? message = null)
        {
            Progress = Math.Min(Math.Max(progress, 0.0), 1.0); // Clamp 0..1
            Message  = message;
        }

        /// <summary>A value between 0 and 1.</summary>
        public double  Progress { get; }

        /// <summary>Optional message describing the current sub-task.</summary>
        public string? Message  { get; }
    }

    /// <summary>
    /// A lightweight object that represents the execution context for a pipeline run.
    /// The implementation is intentionally minimal so that downstream projects can
    /// extend it through the <see cref="IDictionary{TKey,TValue}"/> <see cref="Items"/> bag.
    /// </summary>
    public sealed class PipelineContext
    {
        public PipelineContext(Guid runId, IDictionary<string, object>? items = null)
        {
            RunId = runId;
            Items = items ?? new Dictionary<string, object>();
        }

        /// <summary>The unique identifier that groups all steps belonging to the same run.</summary>
        public Guid RunId { get; }

        /// <summary>Free-form bag for sharing objects across steps (e.g. dependency injection scopes).</summary>
        public IDictionary<string, object> Items { get; }
    }

    /// <summary>
    /// A wrapper that captures success/failure metadata and a strongly-typed output
    /// produced by a pipeline step.
    /// </summary>
    public sealed class PipelineStepResult
    {
        private PipelineStepResult(PipelineStepStatus status, object? output, Exception? error, IReadOnlyDictionary<string, object>? metrics)
        {
            Status  = status;
            Output  = output;
            Error   = error;
            Metrics = metrics ?? new Dictionary<string, object>();
        }

        public static PipelineStepResult Success(object? output, IReadOnlyDictionary<string, object>? metrics = null)
            => new(PipelineStepStatus.Succeeded, output, null, metrics);

        public static PipelineStepResult Warning(object? output, IReadOnlyDictionary<string, object>? metrics = null)
            => new(PipelineStepStatus.CompletedWithWarning, output, null, metrics);

        public static PipelineStepResult Failure(Exception error, IReadOnlyDictionary<string, object>? metrics = null)
            => new(PipelineStepStatus.Failed, null, error, metrics);

        /// <summary>Indicates the final status of the step.</summary>
        public PipelineStepStatus Status { get; }

        /// <summary>The typed or untyped payload produced by the step. Can be <c>null</c>.</summary>
        public object? Output { get; }

        /// <summary>Exception thrown by the step if <see cref="Status"/> equals <see cref="PipelineStepStatus.Failed"/>.</summary>
        public Exception? Error { get; }

        /// <summary>
        /// Additional key-value pairs—often metrics—that the step wishes to publish for
        /// experiment-tracking or user dashboards.
        /// </summary>
        public IReadOnlyDictionary<string, object> Metrics { get; }
    }

    /// <summary>
    /// Contract implemented by every unit of work that can be orchestrated by the
    /// CanvasCraft Pipeline runtime. Steps should be stateless and disposable.
    /// </summary>
    public interface IPipelineStep : IAsyncDisposable
    {
        /// <summary>Human-readable name that appears on dashboards.</summary>
        string Name { get; }

        /// <summary>Longer description that may include Markdown links and examples.</summary>
        string? Description { get; }

        /// <summary>
        /// Arbitrary metadata attached to this step (e.g. author, version). Immutable after construction.
        /// </summary>
        IReadOnlyDictionary<string, string> Metadata { get; }

        /// <summary>
        /// Current status of the step. Implementations must update this value atomically
        /// and raise <see cref="StatusChanged"/> on transition.
        /// </summary>
        PipelineStepStatus Status { get; }

        /// <summary>
        /// Raised whenever <see cref="Status"/> changes. Will fire on the calling thread of the
        /// state change, therefore subscribers should not perform heavy work.
        /// </summary>
        event EventHandler<PipelineStepStatusChangedEventArgs>? StatusChanged;

        /// <summary>
        /// Raised periodically while the step is executing. Progress is optional but recommended
        /// when a step is expected to take longer than a few seconds.
        /// </summary>
        event EventHandler<PipelineStepProgressChangedEventArgs>? ProgressChanged;

        /// <summary>
        /// Executes the step. Implementations should be idempotent and safe to rerun if the process
        /// is resumed from a checkpoint.
        /// </summary>
        /// <param name="context">Shared context among all pipeline steps in the same run.</param>
        /// <param name="cancellationToken">Signal to cancel work and perform fast cleanup.</param>
        /// <returns>A <see cref="PipelineStepResult"/> that includes success/error information.</returns>
        Task<PipelineStepResult> ExecuteAsync(PipelineContext context,
                                             CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Generic version of <see cref="IPipelineStep"/> with strongly typed input/output contracts.
    /// </summary>
    /// <typeparam name="TInput">Type of the object that this step expects as input.</typeparam>
    /// <typeparam name="TOutput">Type of the object produced by this step.</typeparam>
    public interface IPipelineStep<in TInput, TOutput> : IPipelineStep
    {
        /// <summary>
        /// Executes the step using a strongly typed <paramref name="input"/>.
        /// Implementations should call the non-generic <see cref="IPipelineStep.ExecuteAsync"/>
        /// internally to guarantee consistent event flow.
        /// </summary>
        Task<PipelineStepResult> ExecuteAsync(TInput? input,
                                             PipelineContext context,
                                             CancellationToken cancellationToken = default);
    }
}
```