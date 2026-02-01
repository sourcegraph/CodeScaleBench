```csharp
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading;
using MediatR;

namespace PaletteStream.Orchestrator.Domain.Entities
{
    /// <summary>
    /// Aggregate root representing a logical ETL pipeline definition.
    /// </summary>
    public sealed class Pipeline : IAggregateRoot
    {
        private readonly IList<PipelineStep> _steps = new List<PipelineStep>();
        private readonly IList<PipelineExecution> _executions = new List<PipelineExecution>();
        private readonly IList<INotification> _domainEvents = new List<INotification>();

        /// <summary>
        /// For ORM tools. Use <see cref="Create"/> instead.
        /// </summary>
        private Pipeline() { }

        private Pipeline(Guid id,
                         string name,
                         string? description,
                         PipelineStatus status)
        {
            Id          = id;
            Name        = name;
            Description = description;
            Status      = status;
            CreatedAt   = DateTimeOffset.UtcNow;
            UpdatedAt   = CreatedAt;
        }

        public Guid               Id          { get; }
        public string             Name        { get; private set; }
        public string?            Description { get; private set; }
        public PipelineStatus     Status      { get; private set; }
        public DateTimeOffset     CreatedAt   { get; }
        public DateTimeOffset     UpdatedAt   { get; private set; }
        public IReadOnlyList<PipelineStep>    Steps       => new ReadOnlyCollection<PipelineStep>(_steps);
        public IReadOnlyList<PipelineExecution> Executions => new ReadOnlyCollection<PipelineExecution>(_executions);
        public IReadOnlyCollection<INotification> DomainEvents => _domainEvents.ToArray();

        #region Factory

        public static Pipeline Create(string name, string? description = null)
        {
            if (string.IsNullOrWhiteSpace(name))
                throw new ArgumentException("Pipeline name must not be empty.", nameof(name));

            return new Pipeline(Guid.NewGuid(), name.Trim(), description, PipelineStatus.Draft);
        }

        #endregion

        #region Behavior

        public void AddStep(PipelineStep step)
        {
            ArgumentNullException.ThrowIfNull(step);

            if (_steps.Any(s => s.Order == step.Order))
                throw new InvalidOperationException($"A step with order {step.Order} already exists.");

            _steps.Add(step);
            SortSteps();
            Touch();
        }

        public void RemoveStep(Guid stepId)
        {
            var removed = _steps.RemoveAll(s => s.Id == stepId);
            if (removed == 0)
                throw new InvalidOperationException($"Step with id '{stepId}' not found.");

            SortSteps();
            Touch();
        }

        public void ReorderStep(Guid stepId, int newOrder)
        {
            var step = _steps.FirstOrDefault(s => s.Id == stepId)
                       ?? throw new InvalidOperationException($"Step with id '{stepId}' not found.");

            if (_steps.Any(s => s.Order == newOrder))
                throw new InvalidOperationException($"A step with order {newOrder} already exists.");

            step.UpdateOrder(newOrder);
            SortSteps();
            Touch();
        }

        public void Activate()
        {
            if (Status != PipelineStatus.Draft && Status != PipelineStatus.Paused)
                throw new InvalidOperationException(
                    $"Pipeline must be in Draft or Paused state to activate. Current state: {Status}");

            if (!_steps.Any())
                throw new InvalidOperationException("Pipeline must contain at least one step before activation.");

            Status = PipelineStatus.Ready;
            Touch();
        }

        public PipelineExecution StartExecution(string? trigger = null)
        {
            if (Status != PipelineStatus.Ready)
                throw new InvalidOperationException(
                    $"Pipeline status must be Ready to start execution. Current state: {Status}");

            Status = PipelineStatus.Running;
            var execution = PipelineExecution.Create(this, trigger);
            _executions.Add(execution);

            Touch();
            RaiseDomainEvent(new PipelineStartedDomainEvent(Id, execution.Id, trigger));

            return execution;
        }

        public void CompleteExecution(Guid executionId)
        {
            var execution = RequireExecution(executionId);

            execution.MarkCompleted();
            Status = PipelineStatus.Completed;
            Touch();
            RaiseDomainEvent(new PipelineCompletedDomainEvent(Id, execution.Id));
        }

        public void FailExecution(Guid executionId, Exception ex)
        {
            var execution = RequireExecution(executionId);

            execution.MarkFailed(ex);
            Status = PipelineStatus.Failed;
            Touch();
            RaiseDomainEvent(new PipelineFailedDomainEvent(Id, execution.Id, ex));
        }

        #endregion

        #region Helpers

        private PipelineExecution RequireExecution(Guid executionId) =>
            _executions.FirstOrDefault(e => e.Id == executionId)
             ?? throw new InvalidOperationException($"Execution with id '{executionId}' not found.");

        private void SortSteps() =>
            _steps.OrderBy(s => s.Order)
                  .ToList()
                  .ForEach((s, i) => s.UpdateOrder(i + 1));

        private void Touch() => UpdatedAt = DateTimeOffset.UtcNow;

        private void RaiseDomainEvent(INotification @event)
        {
            _domainEvents.Add(@event);
        }

        #endregion
    }

    #region Supporting Types

    public enum PipelineStatus
    {
        Draft      = 0,
        Ready      = 1,
        Running    = 2,
        Completed  = 3,
        Failed     = 4,
        Paused     = 5
    }

    /// <summary>
    /// Immutable representation of a pipeline step.
    /// </summary>
    public sealed class PipelineStep
    {
        /// <summary>For ORM.</summary>
        private PipelineStep() { }

        private PipelineStep(Guid id,
                             int order,
                             string name,
                             string transformerType,
                             IDictionary<string, string>? settings)
        {
            Id             = id;
            Order          = order;
            Name           = name;
            TransformerType = transformerType;
            Settings       = settings is null
                                ? new ReadOnlyDictionary<string, string>(new Dictionary<string, string>())
                                : new ReadOnlyDictionary<string, string>(settings);
            IsEnabled      = true;
        }

        public Guid                   Id              { get; }
        public int                    Order           { get; private set; }
        public string                 Name            { get; private set; }
        public string                 TransformerType { get; private set; }
        public IReadOnlyDictionary<string, string> Settings { get; }
        public bool                   IsEnabled       { get; private set; }

        public static PipelineStep Create(int order,
                                          string name,
                                          string transformerType,
                                          IDictionary<string, string>? settings = null)
        {
            if (string.IsNullOrWhiteSpace(name))
                throw new ArgumentException("Step name must not be empty.", nameof(name));
            if (string.IsNullOrWhiteSpace(transformerType))
                throw new ArgumentException("Transformer type must not be empty.", nameof(transformerType));

            return new PipelineStep(Guid.NewGuid(), order, name.Trim(), transformerType.Trim(), settings);
        }

        internal void UpdateOrder(int order) => Order = order;

        public void Disable() => IsEnabled = false;
        public void Enable()  => IsEnabled = true;
    }

    /// <summary>
    /// Represents a single execution/run of a pipeline.
    /// </summary>
    public sealed class PipelineExecution
    {
        /// <summary>For ORM.</summary>
        private PipelineExecution() { }

        private PipelineExecution(Guid id,
                                  Guid pipelineId,
                                  string? trigger)
        {
            Id         = id;
            PipelineId = pipelineId;
            Trigger    = trigger;
            Status     = ExecutionStatus.Running;
            StartedAt  = DateTimeOffset.UtcNow;
        }

        public Guid           Id          { get; }
        public Guid           PipelineId  { get; }
        public string?        Trigger     { get; }
        public ExecutionStatus Status     { get; private set; }
        public DateTimeOffset StartedAt   { get; }
        public DateTimeOffset? FinishedAt { get; private set; }
        public string?        Error       { get; private set; }

        public static PipelineExecution Create(Pipeline pipeline, string? trigger)
        {
            ArgumentNullException.ThrowIfNull(pipeline);
            return new PipelineExecution(Guid.NewGuid(), pipeline.Id, trigger);
        }

        public void MarkCompleted()
        {
            EnsureRunning();
            Status     = ExecutionStatus.Completed;
            FinishedAt = DateTimeOffset.UtcNow;
        }

        public void MarkFailed(Exception ex)
        {
            EnsureRunning();
            Status     = ExecutionStatus.Failed;
            Error      = ex.ToString();
            FinishedAt = DateTimeOffset.UtcNow;
        }

        private void EnsureRunning()
        {
            if (Status != ExecutionStatus.Running)
                throw new InvalidOperationException($"Execution is not running. Current state: {Status}");
        }
    }

    public enum ExecutionStatus
    {
        Running    = 0,
        Completed  = 1,
        Failed     = 2
    }

    #endregion

    #region Domain Events

    public sealed record PipelineStartedDomainEvent(Guid PipelineId, Guid ExecutionId, string? Trigger)
        : INotification;

    public sealed record PipelineCompletedDomainEvent(Guid PipelineId, Guid ExecutionId)
        : INotification;

    public sealed record PipelineFailedDomainEvent(Guid PipelineId, Guid ExecutionId, Exception Exception)
        : INotification;

    #endregion

    #region Interfaces

    public interface IAggregateRoot
    {
        Guid Id { get; }
        IReadOnlyCollection<INotification> DomainEvents { get; }
    }

    #endregion
}
```