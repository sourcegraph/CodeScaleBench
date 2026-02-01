```csharp
#nullable enable

using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace CanvasCraft.Core.Interfaces.Services
{
    /// <summary>
    /// Abstraction over the binary-storage layer that backs CanvasCraft ML Studio.
    /// Responsible for persisting and retrieving <see cref="ArtifactType"/>s such as
    /// datasets, engineered feature sets, model checkpoints and visual assets.
    ///
    /// The interface purposefully exposes a minimal, provider-agnostic contract
    /// while remaining expressive enough to support advanced use-cases such as
    /// artifact versioning, signed URL generation and reactive eventing.
    /// </summary>
    public interface IStorageService
    {
        #region ─── Artifact CRUD ───────────────────────────────────────────────────

        /// <summary>
        /// Uploads a new artifact or a new version of an existing artifact.
        /// Implementations SHOULD emit a <see cref="StorageEventType.Uploaded"/> event.
        /// </summary>
        /// <param name="content">Raw binary stream of the artifact.</param>
        /// <param name="options">Upload configuration details.</param>
        /// <param name="cancellationToken">Token to observe cancellation requests.</param>
        /// <returns>Descriptor of the stored artifact.</returns>
        Task<ArtifactDescriptor> UploadArtifactAsync(
            Stream content,
            ArtifactUploadOptions options,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Downloads the artifact stream for the requested version.
        /// </summary>
        /// <param name="artifactId">Stable identifier of the artifact.</param>
        /// <param name="version">
        /// Optional version selector; when <c>null</c> the latest version is returned.
        /// </param>
        /// <param name="cancellationToken">Token to observe cancellation requests.</param>
        Task<Stream> DownloadArtifactAsync(
            Guid artifactId,
            ArtifactVersion? version = null,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Generates a provider-specific, time-limited download URL
        /// (e.g., AWS pre-signed S3 URL, Azure Blob SAS token).
        /// </summary>
        Task<Uri> GetDownloadUriAsync(
            Guid artifactId,
            ArtifactVersion? version = null,
            TimeSpan? expiresIn = null,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Removes the specified artifact (or version thereof) from storage.
        /// Implementations SHOULD emit a <see cref="StorageEventType.Deleted"/> event.
        /// </summary>
        Task<bool> DeleteArtifactAsync(
            Guid artifactId,
            ArtifactVersion? version = null,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Checks whether an artifact (or specific version) exists.
        /// </summary>
        Task<bool> ArtifactExistsAsync(
            Guid artifactId,
            ArtifactVersion? version = null,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Retrieves metadata about an artifact without downloading its content.
        /// </summary>
        Task<ArtifactMetadata> GetArtifactMetadataAsync(
            Guid artifactId,
            ArtifactVersion? version = null,
            CancellationToken cancellationToken = default);

        #endregion

        #region ─── Listing & Search ───────────────────────────────────────────────

        /// <summary>
        /// Asynchronously enumerates artifacts that match the provided query.
        /// </summary>
        IAsyncEnumerable<ArtifactDescriptor> ListArtifactsAsync(
            ArtifactQueryParameters query,
            CancellationToken cancellationToken = default);

        #endregion

        #region ─── Reactive Eventing ──────────────────────────────────────────────

        /// <summary>
        /// Cold observable that streams storage events (upload/update/delete).
        /// Consumers can subscribe to power reactive pipelines and dashboards.
        /// </summary>
        IObservable<StorageEvent> Events { get; }

        #endregion
    }

    // ────────────────────────────────────────────────────────────────────────────────
    // Supporting Contracts
    // ────────────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Canonical artifact categories recognised by the CanvasCraft ecosystem.
    /// </summary>
    public enum ArtifactType
    {
        Dataset,
        FeatureSet,
        ModelCheckpoint,
        MetricsReport,
        VisualizationAsset,
        Generic
    }

    /// <summary>
    /// Semantic version wrapper. Implementations MAY map to underlying storage
    /// versioning primitives (e.g., S3 object version ID, Blob snapshot time).
    /// </summary>
    /// <param name="Label">Human-readable version label (e.g., "v1.2").</param>
    /// <param name="Revision">
    /// Monotonically increasing counter used for ordering and conflict detection.
    /// </param>
    public record ArtifactVersion(string Label, int Revision);

    /// <summary>
    /// Lightweight artifact descriptor returned by queries and uploads.
    /// </summary>
    public record ArtifactDescriptor(
        Guid ArtifactId,
        ArtifactType Type,
        string Name,
        DateTimeOffset CreatedAt,
        ArtifactVersion Version,
        long? SizeInBytes,
        IReadOnlyDictionary<string, string>? Tags);

    /// <summary>
    /// Rich artifact metadata, typically backed by blob properties or custom
    /// metadata dictionaries in the storage provider.
    /// </summary>
    public record ArtifactMetadata(
        Guid ArtifactId,
        ArtifactVersion Version,
        DateTimeOffset CreatedAt,
        DateTimeOffset? LastModified,
        string? Checksum,
        IReadOnlyDictionary<string, string>? AdditionalMetadata);

    /// <summary>
    /// Configuration options for an upload operation.
    /// </summary>
    public sealed class ArtifactUploadOptions
    {
        public ArtifactUploadOptions(ArtifactType type, string name)
        {
            Type = type;
            Name = name ?? throw new ArgumentNullException(nameof(name));
        }

        /// <summary>Logical type/category of the artifact.</summary>
        public ArtifactType Type { get; }

        /// <summary>Friendly display name (file-like).</summary>
        public string Name { get; }

        /// <summary>
        /// When provided, instructs the storage to create the specified version;
        /// otherwise a new revision is auto-generated.
        /// </summary>
        public ArtifactVersion? Version { get; init; }

        /// <summary>Optional tag collection for filtering and categorisation.</summary>
        public IReadOnlyDictionary<string, string>? Tags { get; init; }

        /// <summary>Arbitrary key/value pairs persisted alongside the blob.</summary>
        public IReadOnlyDictionary<string, string>? Metadata { get; init; }

        /// <summary>
        /// If <c>true</c> and the artifact already exists, its content will be replaced.
        /// Versioning rules apply depending on provider capabilities.
        /// </summary>
        public bool OverwriteIfExists { get; init; } = false;
    }

    /// <summary>
    /// Parameters used to search and paginate artifacts.
    /// </summary>
    public sealed class ArtifactQueryParameters
    {
        /// <summary>Optional artifact type filter.</summary>
        public ArtifactType? Type { get; init; }

        /// <summary>Optional tag-based AND search.</summary>
        public IReadOnlyDictionary<string, string>? Tags { get; init; }

        /// <summary>Free-text search against the artifact <c>Name</c>.</summary>
        public string? SearchTerm { get; init; }

        /// <summary>Date range lower bound on <c>CreatedAt</c>.</summary>
        public DateTimeOffset? CreatedAfter { get; init; }

        /// <summary>Date range upper bound on <c>CreatedAt</c>.</summary>
        public DateTimeOffset? CreatedBefore { get; init; }

        /// <summary>Maximum number of results; null for provider default.</summary>
        public int? Limit { get; init; }

        /// <summary>Continuation token for result paging.</summary>
        public string? ContinuationToken { get; init; }
    }

    /// <summary>
    /// Event envelope emitted by <see cref="IStorageService.Events"/>.
    /// </summary>
    public readonly record struct StorageEvent(
        Guid ArtifactId,
        StorageEventType EventType,
        ArtifactVersion? Version,
        DateTimeOffset Timestamp);

    /// <summary>
    /// Event taxonomy for storage operations.
    /// </summary>
    public enum StorageEventType
    {
        Uploaded,
        Updated,
        Deleted
    }
}
```