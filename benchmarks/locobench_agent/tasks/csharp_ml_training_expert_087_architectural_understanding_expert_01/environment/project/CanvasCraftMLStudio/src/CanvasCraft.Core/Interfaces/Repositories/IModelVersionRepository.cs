```csharp
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Core.Models;
using CanvasCraft.Core.Specifications;
using CanvasCraft.Core.ValueObjects;

namespace CanvasCraft.Core.Interfaces.Repositories
{
    /// <summary>
    ///     Repository abstraction for working with <see cref="ModelVersion" /> aggregates in the Model Registry.
    ///     All write operations MUST be executed in an application-level transactional boundary
    ///     (see <see cref="IUnitOfWork" />) to ensure consistency between metadata storage,
    ///     the artifact store (Blob / S3 / GCS), and the feature store catalog.
    ///
    ///     Implementations are expected to:
    ///     • Persist model metadata to a durable store (e.g. SQL, NoSQL)
    ///     • Manage artifact-level blobs and checksum invariants
    ///     • Employ optimistic concurrency via <see cref="ModelVersion.RowVersion" />
    ///     • Publish relevant domain events to the message bus for downstream observers
    /// </summary>
    public interface IModelVersionRepository
    {
        #region Queries

        /// <summary>
        ///     Retrieves a single <see cref="ModelVersion" /> by its identity.
        /// </summary>
        /// <param name="versionId">Unique identifier of the model version.</param>
        /// <param name="token">Cancellation token.</param>
        /// <returns>The matching <see cref="ModelVersion" />, or <c>null</c> if not found.</returns>
        Task<ModelVersion?> GetAsync(Guid versionId, CancellationToken token = default);

        /// <summary>
        ///     Checks if a model version with the provided (ModelName, SemanticVersion) pair already exists.
        ///     Primarily used to guard against duplicate uploads.
        /// </summary>
        /// <param name="modelName">The name of the model.</param>
        /// <param name="semanticVersion">SemVer-compatible version tag.</param>
        /// <param name="token">Cancellation token.</param>
        Task<bool> ExistsAsync(string modelName, string semanticVersion, CancellationToken token = default);

        /// <summary>
        ///     Returns a paged, read-only list of model versions that satisfy the specified query specification.
        /// </summary>
        /// <param name="specification">Filtering criteria (status, tags, created date, etc.).</param>
        /// <param name="pageRequest">Pagination and ordering parameters.</param>
        /// <param name="token">Cancellation token.</param>
        Task<PagedResult<ModelVersionSummary>> ListAsync(
            ModelVersionSpecification specification,
            PageRequest pageRequest,
            CancellationToken token = default);

        #endregion

        #region Commands

        /// <summary>
        ///     Persists a new model version to the backing store.
        ///     Implementations SHOULD throw <see cref="DuplicateResourceException" /> if the resource already exists.
        /// </summary>
        /// <param name="modelVersion">Aggregate to persist.</param>
        /// <param name="token">Cancellation token.</param>
        Task<ModelVersion> AddAsync(ModelVersion modelVersion, CancellationToken token = default);

        /// <summary>
        ///     Updates an existing model version. Concurrency is controlled via <see cref="ModelVersion.RowVersion" />.
        ///     Implementations SHOULD throw <see cref="ConcurrencyViolationException" /> if the supplied rowVersion
        ///     does not match the persisted value.
        /// </summary>
        /// <param name="modelVersion">Aggregate with mutated state.</param>
        /// <param name="token">Cancellation token.</param>
        Task UpdateAsync(ModelVersion modelVersion, CancellationToken token = default);

        /// <summary>
        ///     Soft-deletes (archives) a model version, retaining its artifact lineage for reproducibility.
        ///     The record remains queryable when inclusion flags (e.g. IncludeArchived=true) are set.
        /// </summary>
        /// <param name="versionId">Identifier of the model version to archive.</param>
        /// <param name="archivedBy">User or service that initiated the archive.</param>
        /// <param name="token">Cancellation token.</param>
        Task ArchiveAsync(Guid versionId, string archivedBy, CancellationToken token = default);

        /// <summary>
        ///     Permanently removes a model version and its artifacts from the system.
        ///     Use with extreme caution—preferred flow is <see cref="ArchiveAsync"/>.
        /// </summary>
        /// <param name="versionId">Identifier of the model version to delete.</param>
        /// <param name="token">Cancellation token.</param>
        Task DeleteAsync(Guid versionId, CancellationToken token = default);

        #endregion
    }
}
```