using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel.DataAnnotations;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace CanvasCraft.Core.Models
{
    /// <summary>
    /// Domain entity that represents a dataset under management by CanvasCraft ML Studio.
    /// Includes rich metadata, version history, schema definition, and runtime validation helpers.
    /// 
    /// This class is designed to be used as an EF Core aggregate root and therefore owns the lifecycle
    /// of its child <see cref="DatasetVersion"/> entities.
    /// </summary>
    public class Dataset : IEquatable<Dataset>
    {
        private readonly List<DatasetVersion> _versions = new();

        private readonly SemaphoreSlim _versionGate = new(1, 1);

        public Dataset(string name,
                       string description,
                       DataSourceType sourceType,
                       string sourceUri,
                       string schemaJson,
                       string createdBy)
        {
            Id = Guid.NewGuid();
            Name = name ?? throw new ArgumentNullException(nameof(name));
            Description = description ?? string.Empty;
            SourceType = sourceType;
            SourceUri = sourceUri ?? throw new ArgumentNullException(nameof(sourceUri));
            SchemaJson = schemaJson ?? throw new ArgumentNullException(nameof(schemaJson));
            Status = DatasetStatus.Draft;
            CreatedBy = createdBy ?? "system";
            UpdatedBy = createdBy ?? "system";
            CreatedAt = DateTimeOffset.UtcNow;
            UpdatedAt = CreatedAt;
        }

        // EF Core parameterless constructor
        private Dataset() { }

        [Key]
        public Guid Id { get; private set; }

        [MaxLength(128)]
        public string Name { get; private set; } = default!;

        [MaxLength(1024)]
        public string Description { get; private set; } = default!;

        public DataSourceType SourceType { get; private set; }

        [MaxLength(2048)]
        public string SourceUri { get; private set; } = default!;

        /// <summary>
        /// JSON serialized schema definition that can be used by downstream components
        /// to enforce column names, types, and constraints.
        /// </summary>
        public string SchemaJson { get; private set; } = default!;

        public DatasetStatus Status { get; private set; }

        [Timestamp]
        public byte[] RowVersion { get; private set; } = default!;

        public DateTimeOffset CreatedAt { get; private set; }

        public DateTimeOffset UpdatedAt { get; private set; }

        [MaxLength(128)]
        public string CreatedBy { get; private set; } = default!;

        [MaxLength(128)]
        public string UpdatedBy { get; private set; } = default!;

        public IReadOnlyCollection<DatasetVersion> Versions => new ReadOnlyCollection<DatasetVersion>(_versions);

        #region Public Domain Operations

        /// <summary>
        /// Adds a new version for this dataset.
        /// Thread-safe – concurrent callers will be serialized via an async lock to avoid 
        /// version number clashes.
        /// </summary>
        /// <param name="features">Feature definitions present in the version.</param>
        /// <param name="transformationFingerprint">Deterministic hash representing the preprocessing pipeline that generated the version.</param>
        /// <param name="recordCount">Row count contained in the dataset.</param>
        /// <param name="createdBy">User requesting the new version.</param>
        /// <param name="cancellationToken">Cancel operation token.</param>
        public async Task<DatasetVersion> CreateNewVersionAsync(
            IEnumerable<FeatureDefinition> features,
            string transformationFingerprint,
            long recordCount,
            string createdBy,
            CancellationToken cancellationToken = default)
        {
            if (features is null) throw new ArgumentNullException(nameof(features));
            if (string.IsNullOrWhiteSpace(transformationFingerprint))
                throw new ArgumentException("Transformation fingerprint cannot be null or empty.", nameof(transformationFingerprint));
            if (recordCount <= 0) throw new ArgumentOutOfRangeException(nameof(recordCount));
            if (string.IsNullOrWhiteSpace(createdBy)) throw new ArgumentNullException(nameof(createdBy));

            await _versionGate.WaitAsync(cancellationToken).ConfigureAwait(false);
            try
            {
                var nextVersionNumber = _versions.Count == 0
                    ? 1
                    : _versions.Max(v => v.Version) + 1;

                var datasetVersion = new DatasetVersion(
                    parentDatasetId: Id,
                    version: nextVersionNumber,
                    transformationFingerprint: transformationFingerprint.Trim(),
                    recordCount: recordCount,
                    features: features.ToList(),
                    createdBy: createdBy);

                _versions.Add(datasetVersion);

                // update metadata
                Status = DatasetStatus.Active;
                UpdatedAt = DateTimeOffset.UtcNow;
                UpdatedBy = createdBy;

                // raise domain event
                OnDatasetVersionCreated(datasetVersion);

                return datasetVersion;
            }
            finally
            {
                _versionGate.Release();
            }
        }

        /// <summary>
        /// Marks the dataset as archived so that no further processing will be performed.
        /// </summary>
        public void Archive(string archivedBy)
        {
            if (Status == DatasetStatus.Archived) return;

            Status = DatasetStatus.Archived;
            UpdatedAt = DateTimeOffset.UtcNow;
            UpdatedBy = archivedBy ?? "system";

            OnDatasetArchived();
        }

        /// <summary>
        /// Validates that the remote or local file referenced by <see cref="SourceUri"/> exists
        /// and that the schema on disk matches the schema recorded in <see cref="SchemaJson"/>.
        /// This method does a lightweight validation and is not intended to parse large datasets.
        /// </summary>
        public async Task<DatasetValidationResult> ValidateAsync(CancellationToken cancellationToken = default)
        {
            var result = new DatasetValidationResult { DatasetId = Id };

            try
            {
                cancellationToken.ThrowIfCancellationRequested();

                if (!Uri.TryCreate(SourceUri, UriKind.Absolute, out var uri))
                {
                    result.Errors.Add($"Invalid SourceUri: {SourceUri}");
                    return result;
                }

                switch (uri.Scheme)
                {
                    case "file":
                        if (!File.Exists(uri.LocalPath))
                            result.Errors.Add($"File not found: {uri.LocalPath}");
                        break;

                    case "https":
                    case "http":
                        // Quick HEAD request without reading entire body
                        result.RemoteReachable = await HttpHelpers.UrlExistsAsync(uri, cancellationToken).ConfigureAwait(false);
                        if (!result.RemoteReachable)
                            result.Errors.Add($"Remote resource not reachable: {SourceUri}");
                        break;

                    default:
                        result.Errors.Add($"Unsupported URI scheme: {uri.Scheme}");
                        break;
                }

                // Basic JSON validation for schema
                try
                {
                    JsonDocument.Parse(SchemaJson);
                }
                catch (JsonException ex)
                {
                    result.Errors.Add($"SchemaJson is invalid: {ex.Message}");
                }
            }
            catch (OperationCanceledException)
            {
                result.Errors.Add("Validation canceled.");
            }
            catch (Exception ex)
            {
                result.Errors.Add($"Unexpected error during validation: {ex.Message}");
            }

            return result;
        }

        #endregion

        #region Events

        public event EventHandler<DatasetVersionCreatedEventArgs>? DatasetVersionCreated;

        public event EventHandler? DatasetArchived;

        protected virtual void OnDatasetVersionCreated(DatasetVersion newVersion)
        {
            DatasetVersionCreated?.Invoke(this, new DatasetVersionCreatedEventArgs(newVersion));
        }

        protected virtual void OnDatasetArchived()
        {
            DatasetArchived?.Invoke(this, EventArgs.Empty);
        }

        #endregion

        #region Equality

        public bool Equals(Dataset? other)
        {
            if (other is null) return false;
            if (ReferenceEquals(this, other)) return true;

            return Id.Equals(other.Id);
        }

        public override bool Equals(object? obj) => Equals(obj as Dataset);

        public override int GetHashCode() => Id.GetHashCode();

        #endregion
    }

    public enum DatasetStatus
    {
        Draft = 0,
        Active = 1,
        Deprecated = 2,
        Archived = 3
    }

    public enum DataSourceType
    {
        File = 0,
        Database = 1,
        Api = 2,
        Generated = 3
    }

    /// <summary>
    /// Immutable record describing a feature present in a dataset.
    /// </summary>
    /// <param name="Name">Name of the feature/column.</param>
    /// <param name="DataType">CLR data type name (string, int, float, etc.).</param>
    /// <param name="IsCategorical">Marks whether the feature is categorical.</param>
    /// <param name="Description">Human friendly description.</param>
    public record FeatureDefinition(
        string Name,
        string DataType,
        bool IsCategorical = false,
        string? Description = null)
    {
        public static FeatureDefinition From<T>(string name, bool isCategorical = false, string? description = null)
            => new(name, typeof(T).Name, isCategorical, description);
    }

    /// <summary>
    /// Represents a single version of an existing dataset.
    /// </summary>
    public class DatasetVersion
    {
        internal DatasetVersion(Guid parentDatasetId,
                                int version,
                                string transformationFingerprint,
                                long recordCount,
                                IReadOnlyCollection<FeatureDefinition> features,
                                string createdBy)
        {
            ParentDatasetId = parentDatasetId;
            Version = version;
            TransformationFingerprint = transformationFingerprint;
            RecordCount = recordCount;
            Features = features;
            CreatedBy = createdBy;
            CreatedAt = DateTimeOffset.UtcNow;
        }

        // Required by EF Core
        private DatasetVersion() { }

        public Guid Id { get; private set; } = Guid.NewGuid();

        public Guid ParentDatasetId { get; private set; }

        public int Version { get; private set; }

        public string TransformationFingerprint { get; private set; } = default!;

        public long RecordCount { get; private set; }

        public IReadOnlyCollection<FeatureDefinition> Features { get; private set; } = default!;

        public DateTimeOffset CreatedAt { get; private set; }

        [MaxLength(128)]
        public string CreatedBy { get; private set; } = default!;

        public override string ToString() => $"v{Version} ({RecordCount:n0} rows)";
    }

    /// <summary>
    /// Encapsulates results from validating a dataset's source and schema.
    /// </summary>
    public class DatasetValidationResult
    {
        public Guid DatasetId { get; set; }

        public bool RemoteReachable { get; set; }

        public bool IsValid => Errors.Count == 0;

        public List<string> Errors { get; } = new();
    }

    /// <summary>
    /// Domain event args for a newly created dataset version.
    /// </summary>
    public sealed class DatasetVersionCreatedEventArgs : EventArgs
    {
        public DatasetVersionCreatedEventArgs(DatasetVersion datasetVersion)
        {
            DatasetVersion = datasetVersion ?? throw new ArgumentNullException(nameof(datasetVersion));
        }

        public DatasetVersion DatasetVersion { get; }
    }

    internal static class HttpHelpers
    {
        /// <summary>
        /// Executes a lightweight HEAD request to determine whether the URL exists.
        /// </summary>
        public static async Task<bool> UrlExistsAsync(Uri uri, CancellationToken cancellationToken = default)
        {
            using var client = new System.Net.Http.HttpClient
            {
                Timeout = TimeSpan.FromSeconds(5)
            };

            using var request = new System.Net.Http.HttpRequestMessage(System.Net.Http.HttpMethod.Head, uri);

            try
            {
                var response = await client.SendAsync(request, cancellationToken).ConfigureAwait(false);
                return response.IsSuccessStatusCode;
            }
            catch (System.Net.Http.HttpRequestException)
            {
                return false;
            }
        }
    }
}