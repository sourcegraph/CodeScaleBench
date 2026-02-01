```csharp
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel.DataAnnotations;
using System.Linq;

namespace CanvasCraft.Core.Models
{
    /// <summary>
    ///     Represents a single, immutable checkpoint of a machine-learning model.
    ///     Instances are created through the static <see cref="Create"/> factory
    ///     and transition between states via explicit domain methods that emit
    ///     <see cref="ModelVersionChanged"/> notifications.
    /// </summary>
    public sealed class ModelVersion : IEquatable<ModelVersion>, IObservable<ModelVersionChanged>
    {
        #region Factory

        /// <summary>
        ///     Factory method responsible for fully-populating and validating a new instance.
        ///     This enforces invariants such as non-empty modelId and a non-null
        ///     semantic version.
        /// </summary>
        /// <exception cref="ArgumentException">
        ///     Thrown when supplied arguments are invalid.
        /// </exception>
        public static ModelVersion Create(
            string modelId,
            SemanticVersion version,
            Uri artifactUri,
            IDictionary<string, string>? hyperParameters = null,
            string? commitHash               = null,
            IEnumerable<string>? initialTags = null)
        {
            if (string.IsNullOrWhiteSpace(modelId))
                throw new ArgumentException("Model Id must be supplied.", nameof(modelId));

            if (version == SemanticVersion.Empty)
                throw new ArgumentException("Semantic version must be supplied.", nameof(version));

            if (artifactUri is null)
                throw new ArgumentNullException(nameof(artifactUri));

            return new ModelVersion(
                Guid.NewGuid(),
                modelId.Trim(),
                version,
                artifactUri,
                hyperParameters ?? new Dictionary<string, string>(),
                commitHash,
                initialTags ?? Enumerable.Empty<string>());
        }

        #endregion

        #region Constructors

        // Constructor is private to enforce usage of factory.
        private ModelVersion(
            Guid id,
            string modelId,
            SemanticVersion version,
            Uri artifactUri,
            IDictionary<string, string> hyperParameters,
            string? commitHash,
            IEnumerable<string> tags)
        {
            Id             = id;
            ModelId        = modelId;
            Version        = version;
            ArtifactUri    = artifactUri.ToString();
            CommitHash     = commitHash;

            _hyperParameters = new Dictionary<string, string>(hyperParameters, StringComparer.OrdinalIgnoreCase);
            _metrics         = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);
            _tags            = new HashSet<string>(tags, StringComparer.OrdinalIgnoreCase);

            Status        = ModelVersionStatus.Draft;
            CreatedAtUtc  = DateTime.UtcNow;
            LastUpdatedAt = CreatedAtUtc;
        }

        #endregion

        #region State & Identity

        /// <summary>Primary key for persistence.</summary>
        [Key]
        public Guid Id { get; }

        /// <summary>Identifier of the parent model this version belongs to.</summary>
        [Required]
        public string ModelId { get; }

        /// <summary>Semantic version label.</summary>
        [Required]
        public SemanticVersion Version { get; }

        /// <summary>Where the serialized model artifact is stored (blob, S3, etc.).</summary>
        [Required]
        public string ArtifactUri { get; private set; }

        /// <summary>Git/SVN commit of the dataset + code used to build this version.</summary>
        public string? CommitHash { get; }

        /// <summary>Current lifecycle state.</summary>
        public ModelVersionStatus Status { get; private set; }

        /// <summary>UTC timestamp at creation.</summary>
        public DateTime CreatedAtUtc { get; }

        /// <summary>Last time any property changed.</summary>
        public DateTime LastUpdatedAt { get; private set; }

        /// <summary>UTC timestamp when training started, if applicable.</summary>
        public DateTime? TrainingStartedAtUtc { get; private set; }

        /// <summary>UTC timestamp when training completed.</summary>
        public DateTime? TrainedAtUtc { get; private set; }

        /// <summary>UTC timestamp when the model was promoted to production.</summary>
        public DateTime? DeployedAtUtc { get; private set; }

        /// <summary>
        ///     Concurrency token. Should be configured as rowversion/timestamp in the
        ///     data store to prevent accidental overwrites.
        /// </summary>
        [Timestamp]
        // ReSharper disable once MemberCanBePrivate.Global
        public byte[]? RowVersion { get; set; }

        #endregion

        #region Collections (Hyper-parameters, Metrics & Tags)

        private readonly Dictionary<string, string> _hyperParameters;
        private readonly Dictionary<string, double> _metrics;
        private readonly HashSet<string>           _tags;

        /// <summary>Read-only view of original hyperparameters.</summary>
        public IReadOnlyDictionary<string, string> HyperParameters =>
            new ReadOnlyDictionary<string, string>(_hyperParameters);

        /// <summary>Immutable snapshot of training/evaluation metrics.</summary>
        public IReadOnlyDictionary<string, double> Metrics =>
            new ReadOnlyDictionary<string, double>(_metrics);

        /// <summary>Arbitrary tags that support search & filtering.</summary>
        public IReadOnlyCollection<string> Tags =>
            new ReadOnlyCollection<string>(_tags.ToList());

        #endregion

        #region Domain Behavior

        /// <summary>Transition model to <see cref="ModelVersionStatus.QueuedForTraining"/>.</summary>
        public void QueueForTraining()
        {
            EnsureState(ModelVersionStatus.Draft);

            Status              = ModelVersionStatus.QueuedForTraining;
            TrainingStartedAtUtc = null;
            Touch();

            NotifyObservers(new ModelVersionChanged(this, ModelVersionChangeType.QueuedForTraining));
        }

        /// <summary>Mark that the training job has commenced.</summary>
        public void MarkTrainingStarted()
        {
            EnsureState(ModelVersionStatus.QueuedForTraining);

            Status              = ModelVersionStatus.Training;
            TrainingStartedAtUtc = DateTime.UtcNow;

            Touch();
            NotifyObservers(new ModelVersionChanged(this, ModelVersionChangeType.TrainingStarted));
        }

        /// <summary>Complete training and record metrics.</summary>
        public void CompleteTraining(IDictionary<string, double> metrics)
        {
            EnsureState(ModelVersionStatus.Training);

            if (metrics == null || metrics.Count == 0)
                throw new ArgumentException("At least one metric must be supplied.", nameof(metrics));

            foreach (var (key, value) in metrics)
                _metrics[key] = value;

            Status     = ModelVersionStatus.Trained;
            TrainedAtUtc = DateTime.UtcNow;

            Touch();
            NotifyObservers(new ModelVersionChanged(this, ModelVersionChangeType.TrainingCompleted));
        }

        /// <summary>Training failed; captures optional diagnostic reason.</summary>
        public void FailTraining(string? reason = null)
        {
            EnsureState(ModelVersionStatus.Training, ModelVersionStatus.QueuedForTraining);

            Status = ModelVersionStatus.FailedTraining;

            if (!string.IsNullOrWhiteSpace(reason))
                _metrics["failure_reason"] = 0; // Value is meaningless; key presence is enough.

            Touch();
            NotifyObservers(new ModelVersionChanged(this, ModelVersionChangeType.TrainingFailed));
        }

        /// <summary>
        ///     Promote this model version to production. Idempotent—calling more than once
        ///     when already deployed will be ignored.
        /// </summary>
        public void PromoteToProduction()
        {
            if (Status == ModelVersionStatus.Production)
                return;

            EnsureState(ModelVersionStatus.Trained, ModelVersionStatus.Staged);

            Status        = ModelVersionStatus.Production;
            DeployedAtUtc = DateTime.UtcNow;

            Touch();
            NotifyObservers(new ModelVersionChanged(this, ModelVersionChangeType.PromotedToProduction));
        }

        /// <summary>Adds a free-form tag.</summary>
        /// <exception cref="ArgumentException">If the tag is null/empty or whitespace.</exception>
        public void AddTag(string tag)
        {
            if (string.IsNullOrWhiteSpace(tag))
                throw new ArgumentException("Tag cannot be empty.", nameof(tag));

            if (_tags.Add(tag.Trim()))
            {
                Touch();
                NotifyObservers(new ModelVersionChanged(this, ModelVersionChangeType.TagAdded));
            }
        }

        /// <summary>Removes a tag if present.</summary>
        public void RemoveTag(string tag)
        {
            if (_tags.Remove(tag))
            {
                Touch();
                NotifyObservers(new ModelVersionChanged(this, ModelVersionChangeType.TagRemoved));
            }
        }

        private void Touch() => LastUpdatedAt = DateTime.UtcNow;

        private void EnsureState(params ModelVersionStatus[] expectedStates)
        {
            if (!expectedStates.Contains(Status))
            {
                throw new InvalidOperationException(
                    $"Operation invalid when status is {Status}; expected: {string.Join(", ", expectedStates)}.");
            }
        }

        #endregion

        #region Equality

        public bool Equals(ModelVersion? other) =>
            other is not null &&
            other.ModelId.Equals(ModelId, StringComparison.Ordinal) &&
            other.Version.Equals(Version);

        public override bool Equals(object? obj) => Equals(obj as ModelVersion);

        public override int GetHashCode() => HashCode.Combine(ModelId, Version);

        #endregion

        #region Observer Pattern

        private readonly List<IObserver<ModelVersionChanged>> _observers = new();

        public IDisposable Subscribe(IObserver<ModelVersionChanged> observer)
        {
            if (observer == null) throw new ArgumentNullException(nameof(observer));

            _observers.Add(observer);
            return new Unsubscriber(_observers, observer);
        }

        private void NotifyObservers(ModelVersionChanged changeEvent)
        {
            foreach (var observer in _observers.ToArray())
                observer.OnNext(changeEvent);
        }

        private sealed class Unsubscriber : IDisposable
        {
            private readonly List<IObserver<ModelVersionChanged>> _subs;
            private readonly IObserver<ModelVersionChanged>        _observer;

            public Unsubscriber(List<IObserver<ModelVersionChanged>> subs, IObserver<ModelVersionChanged> observer)
            {
                _subs     = subs;
                _observer = observer;
            }

            public void Dispose()
            {
                if (_observer != null && _subs.Contains(_observer))
                    _subs.Remove(_observer);
            }
        }

        #endregion
    }

    #region Supporting Types

    /// <summary>Mutable event describing a change in <see cref="ModelVersion"/>.</summary>
    public sealed class ModelVersionChanged
    {
        public ModelVersionChanged(ModelVersion version, ModelVersionChangeType changeType)
        {
            Version    = version;
            ChangeType = changeType;
            AtUtc      = DateTime.UtcNow;
        }

        public ModelVersion           Version    { get; }
        public ModelVersionChangeType ChangeType { get; }
        public DateTime               AtUtc      { get; }
    }

    public enum ModelVersionChangeType
    {
        QueuedForTraining,
        TrainingStarted,
        TrainingCompleted,
        TrainingFailed,
        PromotedToProduction,
        TagAdded,
        TagRemoved
    }

    /// <summary>Lifecycle state of a <see cref="ModelVersion"/>.</summary>
    public enum ModelVersionStatus
    {
        Draft,
        QueuedForTraining,
        Training,
        FailedTraining,
        Trained,
        Staged,
        Production,
        Archived
    }

    /// <summary>
    ///     Lightweight semantic-version implementation that supports equality,
    ///     ordering, and string parsing. This avoids taking an external NuGet
    ///     dependency for a single struct.
    /// </summary>
    public readonly struct SemanticVersion : IComparable<SemanticVersion>, IEquatable<SemanticVersion>
    {
        public static readonly SemanticVersion Empty = default;

        public SemanticVersion(int major, int minor, int patch, string? preRelease = null, string? buildMetadata = null)
        {
            if (major < 0) throw new ArgumentOutOfRangeException(nameof(major));
            if (minor < 0) throw new ArgumentOutOfRangeException(nameof(minor));
            if (patch < 0) throw new ArgumentOutOfRangeException(nameof(patch));

            Major         = major;
            Minor         = minor;
            Patch         = patch;
            PreRelease    = preRelease;
            BuildMetadata = buildMetadata;
        }

        public int    Major         { get; }
        public int    Minor         { get; }
        public int    Patch         { get; }
        public string? PreRelease    { get; }
        public string? BuildMetadata { get; }

        public static bool TryParse(string source, out SemanticVersion version)
        {
            version = Empty;

            if (string.IsNullOrWhiteSpace(source))
                return false;

            var mainAndMeta = source.Split('+');
            var preAndMain  = mainAndMeta[0].Split('-');

            var mainParts = preAndMain[0].Split('.');
            if (mainParts.Length != 3 ||
                !int.TryParse(mainParts[0], out var major) ||
                !int.TryParse(mainParts[1], out var minor) ||
                !int.TryParse(mainParts[2], out var patch))
                return false;

            var preRelease    = preAndMain.Length > 1 ? preAndMain[1] : null;
            var buildMetadata = mainAndMeta.Length > 1 ? mainAndMeta[1] : null;

            version = new SemanticVersion(major, minor, patch, preRelease, buildMetadata);
            return true;
        }

        public int CompareTo(SemanticVersion other)
        {
            var majorCmp = Major.CompareTo(other.Major);
            if (majorCmp != 0) return majorCmp;

            var minorCmp = Minor.CompareTo(other.Minor);
            if (minorCmp != 0) return minorCmp;

            var patchCmp = Patch.CompareTo(other.Patch);
            if (patchCmp != 0) return patchCmp;

            // Pre-release versions have lower precedence.
            if (PreRelease == null && other.PreRelease != null) return 1;
            if (PreRelease != null && other.PreRelease == null) return -1;

            return string.Compare(PreRelease, other.PreRelease, StringComparison.Ordinal);
        }

        public bool Equals(SemanticVersion other) =>
            Major == other.Major &&
            Minor == other.Minor &&
            Patch == other.Patch &&
            string.Equals(PreRelease, other.PreRelease, StringComparison.Ordinal) &&
            string.Equals(BuildMetadata, other.BuildMetadata, StringComparison.Ordinal);

        public override bool Equals(object? obj) => obj is SemanticVersion v && Equals(v);

        public override int GetHashCode() =>
            HashCode.Combine(Major, Minor, Patch, PreRelease ?? string.Empty, BuildMetadata ?? string.Empty);

        public static bool operator ==(SemanticVersion left, SemanticVersion right) => left.Equals(right);

        public static bool operator !=(SemanticVersion left, SemanticVersion right) => !left.Equals(right);

        public static bool operator >(SemanticVersion left, SemanticVersion right) => left.CompareTo(right) > 0;

        public static bool operator <(SemanticVersion left, SemanticVersion right) => left.CompareTo(right) < 0;

        public override string ToString()
        {
            var core = $"{Major}.{Minor}.{Patch}";
            var pre  = PreRelease != null ? $"-{PreRelease}" : string.Empty;
            var meta = BuildMetadata != null ? $"+{BuildMetadata}" : string.Empty;
            return $"{core}{pre}{meta}";
        }
    }

    #endregion
}
```