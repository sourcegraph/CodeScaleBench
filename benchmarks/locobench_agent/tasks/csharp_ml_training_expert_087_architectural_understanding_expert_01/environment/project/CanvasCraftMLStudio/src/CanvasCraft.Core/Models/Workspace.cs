```csharp
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics.CodeAnalysis;
using System.Linq;
using System.Threading;

namespace CanvasCraft.Core.Models
{
    /// <summary>
    ///     Represents an end-to-end creative workspace that groups together datasets, experiments,
    ///     feature engineering pipelines, model checkpoints, and the surrounding MLOps context.
    ///     A workspace is the top-level aggregate root in the CanvasCraft domain model.
    ///     All state-changing operations raise <see cref="WorkspaceChanged" /> events so that
    ///     UI dashboards and background services (e.g., model monitoring, automated retraining)
    ///     can react in real time via the Observer pattern.
    /// </summary>
    public sealed class Workspace : IEquatable<Workspace>, IDisposable
    {
        #region Private fields

        private readonly ReaderWriterLockSlim _lock = new(LockRecursionPolicy.NoRecursion);

        // Internal collections are protected by _lock
        private readonly Dictionary<Guid, Dataset>      _datasets   = new();
        private readonly Dictionary<Guid, Experiment>   _experiments = new();
        private readonly Dictionary<Guid, ModelVersion> _models      = new();

        private bool _disposed;

        #endregion

        #region Constructors

        /// <summary>
        ///     Initializes a new workspace.
        /// </summary>
        /// <param name="name">Friendly name of the workspace.</param>
        /// <param name="owner">Unique identifier of the workspace owner (e.g., user id, service principal).</param>
        /// <param name="description">Optional description.</param>
        public Workspace(string name, string owner, string? description = null)
        {
            Id          = Guid.NewGuid();
            Name        = name  ?? throw new ArgumentNullException(nameof(name));
            Owner       = owner ?? throw new ArgumentNullException(nameof(owner));
            Description = description;

            CreatedAtUtc      = DateTimeOffset.UtcNow;
            LastModifiedAtUtc = CreatedAtUtc;
        }

        #endregion

        #region Public events

        /// <summary>
        ///     Raised after every state change to the workspace.  Consumers may observe the <see cref="Action"/>
        ///     that occurred to implement reactive flows (e.g., refresh dashboards, trigger pipelines).
        /// </summary>
        public event EventHandler<WorkspaceChangedEventArgs>? WorkspaceChanged;

        #endregion

        #region Public properties

        public Guid            Id                { get; }
        public string          Name              { get; private set; }
        public string?         Description       { get; private set; }
        public string          Owner             { get; }
        public DateTimeOffset  CreatedAtUtc      { get; }
        public DateTimeOffset  LastModifiedAtUtc { get; private set; }
        public bool            IsArchived        { get; private set; }

        public IReadOnlyCollection<Dataset>      Datasets    => AsReadOnly(_datasets);
        public IReadOnlyCollection<Experiment>   Experiments => AsReadOnly(_experiments);
        public IReadOnlyCollection<ModelVersion> Models      => AsReadOnly(_models);

        #endregion

        #region Public API ‑ Dataset management

        public void AddDataset(Dataset dataset)
        {
            EnsureNotArchived();
            ArgumentNullException.ThrowIfNull(dataset);

            WriteScoped(() =>
            {
                if (_datasets.ContainsKey(dataset.Id))
                    throw new DuplicateEntityException($"Dataset {dataset.Id} already exists in workspace '{Name}'.");

                _datasets.Add(dataset.Id, dataset);
                Touch();
                OnWorkspaceChanged(WorkspaceAction.DatasetAdded, dataset.Id);
            });
        }

        public void RemoveDataset(Guid datasetId)
        {
            EnsureNotArchived();

            WriteScoped(() =>
            {
                if (!_datasets.Remove(datasetId))
                    throw new EntityNotFoundException($"Dataset {datasetId} was not found in workspace '{Name}'.");

                Touch();
                OnWorkspaceChanged(WorkspaceAction.DatasetRemoved, datasetId);
            });
        }

        #endregion

        #region Public API ‑ Experiment management

        public void AddExperiment(Experiment experiment)
        {
            EnsureNotArchived();
            ArgumentNullException.ThrowIfNull(experiment);

            WriteScoped(() =>
            {
                if (_experiments.ContainsKey(experiment.Id))
                    throw new DuplicateEntityException($"Experiment {experiment.Id} already exists.");

                _experiments.Add(experiment.Id, experiment);
                Touch();
                OnWorkspaceChanged(WorkspaceAction.ExperimentAdded, experiment.Id);
            });
        }

        public void UpdateExperiment(Experiment experiment)
        {
            EnsureNotArchived();
            ArgumentNullException.ThrowIfNull(experiment);

            WriteScoped(() =>
            {
                if (!_experiments.ContainsKey(experiment.Id))
                    throw new EntityNotFoundException($"Experiment {experiment.Id} was not found.");

                _experiments[experiment.Id] = experiment;
                Touch();
                OnWorkspaceChanged(WorkspaceAction.ExperimentUpdated, experiment.Id);
            });
        }

        #endregion

        #region Public API ‑ Model versioning

        public void RegisterModelVersion(ModelVersion model)
        {
            EnsureNotArchived();
            ArgumentNullException.ThrowIfNull(model);

            WriteScoped(() =>
            {
                if (_models.ContainsKey(model.Id))
                    throw new DuplicateEntityException($"Model version {model.Id} already registered.");

                _models.Add(model.Id, model);
                Touch();
                OnWorkspaceChanged(WorkspaceAction.ModelRegistered, model.Id);
            });
        }

        #endregion

        #region Public API ‑ Workspace lifecycle

        /// <summary>
        ///     Updates high-level metadata such as <see cref="Name"/> or <see cref="Description"/>.
        /// </summary>
        public void UpdateMetadata(string name, string? description = null)
        {
            EnsureNotArchived();

            WriteScoped(() =>
            {
                Name        = name        ?? throw new ArgumentNullException(nameof(name));
                Description = description;
                Touch();
                OnWorkspaceChanged(WorkspaceAction.MetadataUpdated, Id);
            });
        }

        /// <summary>
        ///     Soft-archives the workspace; no further state-changing operations are allowed.
        /// </summary>
        public void Archive()
        {
            WriteScoped(() =>
            {
                if (IsArchived)
                    return;

                IsArchived = true;
                Touch();
                OnWorkspaceChanged(WorkspaceAction.Archived, Id);
            });
        }

        #endregion

        #region Equality members

        public bool Equals(Workspace? other) => other is not null && other.Id == Id;

        public override bool Equals(object? obj) => Equals(obj as Workspace);

        public override int GetHashCode() => Id.GetHashCode();

        #endregion

        #region IDisposable

        public void Dispose()
        {
            if (_disposed) return;

            _lock.Dispose();
            _disposed = true;
            GC.SuppressFinalize(this);
        }

        #endregion

        #region Private helpers

        private void Touch() => LastModifiedAtUtc = DateTimeOffset.UtcNow;

        private void EnsureNotArchived()
        {
            if (IsArchived)
                throw new InvalidOperationException($"Workspace '{Name}' is archived and can no longer be modified.");
        }

        private void WriteScoped(Action action)
        {
            _lock.EnterWriteLock();
            try
            {
                action();
            }
            finally
            {
                _lock.ExitWriteLock();
            }
        }

        private IReadOnlyCollection<T> AsReadOnly<T>(IDictionary<Guid, T> source)
        {
            _lock.EnterReadLock();
            try
            {
                // Snapshot the current values to avoid holding locks during enumeration.
                return new ReadOnlyCollection<T>(source.Values.ToList());
            }
            finally
            {
                _lock.ExitReadLock();
            }
        }

        [SuppressMessage("ReSharper", "ExplicitCallerInfoArgument")]
        private void OnWorkspaceChanged(WorkspaceAction action, Guid affectedEntityId) =>
            WorkspaceChanged?.Invoke(this, new WorkspaceChangedEventArgs(action, affectedEntityId));

        #endregion
    }

    #region Supporting domain classes / enums / exceptions

    /// <summary>
    ///     Simple POCO placeholders for domain objects; real implementations live elsewhere in the project.
    /// </summary>
    public sealed record Dataset(Guid Id, string Name);

    public sealed record Experiment(Guid Id, string Name);

    public sealed record ModelVersion(Guid Id, string Name, string CheckpointPath);

    public enum WorkspaceAction
    {
        DatasetAdded,
        DatasetRemoved,
        ExperimentAdded,
        ExperimentUpdated,
        ModelRegistered,
        MetadataUpdated,
        Archived
    }

    public sealed class WorkspaceChangedEventArgs : EventArgs
    {
        public WorkspaceChangedEventArgs(WorkspaceAction action, Guid affectedEntityId)
        {
            Action           = action;
            AffectedEntityId = affectedEntityId;
            OccurredAtUtc    = DateTimeOffset.UtcNow;
        }

        public WorkspaceAction Action           { get; }
        public Guid            AffectedEntityId { get; }
        public DateTimeOffset  OccurredAtUtc    { get; }
    }

    public sealed class DuplicateEntityException : Exception
    {
        public DuplicateEntityException(string message) : base(message) { }
    }

    public sealed class EntityNotFoundException : Exception
    {
        public EntityNotFoundException(string message) : base(message) { }
    }

    #endregion
}
```