```csharp
// -------------------------------------------------------------------------------------------------
//  PaletteStream ETL Canvas
//  File:        IPipelineRepository.cs
//  Project:     PaletteStream.Orchestrator (Domain Layer)
//  Description: Contract for pipeline persistence & query operations used by the Orchestrator
//               micro-service.  The repository acts as the abstraction between the domain model
//               (Pipeline Aggregate) and the underlying data store (PostgreSQL, CosmosDB, etc.).
//               NOTE: Implementations must remain side-effect free and transactional – the
//               Orchestrator relies on this component for idempotent scheduling and replay.
// -------------------------------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using PaletteStream.Orchestrator.Domain.Models;
using PaletteStream.Orchestrator.Domain.Primitives;

namespace PaletteStream.Orchestrator.Domain.Repositories;

/// <summary>
/// Primary repository contract for <see cref="Pipeline"/> aggregates.  Implementations MUST honor
/// optimistic concurrency by validating the <see cref="Entity.Version"/> property on every update
/// call.  All methods are designed for asynchronous, non-blocking IO.
/// </summary>
public interface IPipelineRepository
{
    #region Aggregate CRUD

    /// <summary>
    /// Persists a new <see cref="Pipeline"/> aggregate.
    /// </summary>
    /// <remarks>
    /// Implementations SHOULD persist the aggregate atomically together with its initial
    /// <see cref="PipelineVersion"/> child entities in a single transaction.
    /// </remarks>
    /// <param name="pipeline">Pipeline aggregate to add.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>Fully hydrated aggregate with DB-generated identity values.</returns>
    Task<Pipeline> AddAsync(
        Pipeline pipeline,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Retrieves a pipeline by identifier.
    /// </summary>
    /// <param name="pipelineId">Unique pipeline identifier.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The pipeline or <c>null</c>.</returns>
    Task<Pipeline?> GetAsync(
        Guid pipelineId,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Updates an existing pipeline aggregate.
    /// </summary>
    /// <remarks>
    /// Optimistic concurrency must be enforced by comparing <see cref="Entity.Version"/>.
    /// An <see cref="ConcurrencyException"/> SHOULD be thrown on version mismatch.
    /// </remarks>
    /// <param name="pipeline">Aggregate with updated state.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    Task UpdateAsync(
        Pipeline pipeline,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Permanently deletes a pipeline and all child entities.
    /// </summary>
    /// <param name="pipelineId">Identifier of the pipeline to delete.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    Task DeleteAsync(
        Guid pipelineId,
        CancellationToken cancellationToken = default);

    #endregion

    #region Query helpers

    /// <summary>
    /// Checks if a pipeline exists.
    /// </summary>
    /// <param name="pipelineId">Pipeline identity.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    Task<bool> ExistsAsync(
        Guid pipelineId,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Streams all pipelines lazily.  Ideal for large datasets.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    IAsyncEnumerable<Pipeline> StreamAllAsync(
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Retrieves a paginated collection of pipelines filtered by status, ordered by creation date
    /// descending.
    /// </summary>
    /// <param name="status">Desired pipeline status to filter.</param>
    /// <param name="pageSize">Maximum items per page.</param>
    /// <param name="page">Page index (1-based).</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    Task<PaginatedResult<Pipeline>> GetByStatusAsync(
        PipelineStatus status,
        int pageSize             = 50,
        int page                 = 1,
        CancellationToken cancellationToken = default);

    #endregion

    #region Versioning

    /// <summary>
    /// Adds a new version to an existing pipeline, marking it as the active version by default.
    /// </summary>
    /// <param name="pipelineId">Pipeline identifier.</param>
    /// <param name="version">Version entity to add.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    Task<PipelineVersion> AddVersionAsync(
        Guid pipelineId,
        PipelineVersion version,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Retrieves a specific version of a pipeline.
    /// </summary>
    /// <param name="pipelineId">Pipeline identifier.</param>
    /// <param name="versionNumber">Version number.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    Task<PipelineVersion?> GetVersionAsync(
        Guid pipelineId,
        int versionNumber,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Activates a given version, making it the default for future executions.
    /// </summary>
    /// <param name="pipelineId">Pipeline identifier.</param>
    /// <param name="versionNumber">Version to activate.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    Task ActivateVersionAsync(
        Guid pipelineId,
        int versionNumber,
        CancellationToken cancellationToken = default);

    #endregion

    #region Scheduling

    /// <summary>
    /// Retrieves all pipelines that are due to run at or before the provided timestamp.  Used by
    /// the <c>SchedulerService</c> to dispatch runnable jobs.
    /// </summary>
    /// <param name="utcNow">Current UTC timestamp.</param>
    /// <param name="limit">Maximum number of pipelines to return.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    Task<IReadOnlyCollection<Pipeline>> GetDuePipelinesAsync(
        DateTime utcNow,
        int limit = 100,
        CancellationToken cancellationToken = default);

    #endregion
}

// -------------------------------------------------------------------------------------------------
// Below are slim domain primitives required only for compilation of this file. In the real project
// they live in dedicated files and contain rich domain logic.  They are included here to make the
// file self-contained for code-generation purposes.
// -------------------------------------------------------------------------------------------------

namespace PaletteStream.Orchestrator.Domain.Primitives;

/// <summary>
/// Base entity with an identity <c>Id</c> and an optimistic concurrency <c>Version</c>.
/// </summary>
public abstract record Entity
{
    public Guid Id { get; init; } = Guid.NewGuid();
    public long Version { get; set; }
}

/// <summary>
/// Paginated result wrapper.
/// </summary>
public record PaginatedResult<T>(IReadOnlyCollection<T> Items, int TotalCount, int Page, int PageSize);

/// <summary>
/// Thrown when optimistic locking detects an obsolete version during update.
/// </summary>
public sealed class ConcurrencyException : Exception
{
    public ConcurrencyException(string message) : base(message) { }
}

// -------------------------------------------------------------------------------------------------

namespace PaletteStream.Orchestrator.Domain.Models;

/// <summary>
/// Represents the aggregate root for an ETL pipeline.
/// </summary>
public sealed record Pipeline : PaletteStream.Orchestrator.Domain.Primitives.Entity
{
    public string Name { get; init; } = default!;
    public PipelineStatus Status { get; set; }
    public DateTime CreatedUtc { get; init; } = DateTime.UtcNow;
    public DateTime? NextRunUtc { get; set; }
    public IReadOnlyCollection<PipelineVersion> Versions { get; init; } = Array.Empty<PipelineVersion>();
}

/// <summary>
/// Immutable value object encapsulating a specific pipeline definition (set of transformation
/// steps & parameters).
/// </summary>
public sealed record PipelineVersion
{
    public int VersionNumber { get; init; }
    public string DefinitionJson { get; init; } = default!;
    public DateTime CreatedUtc { get; init; } = DateTime.UtcNow;
}

public enum PipelineStatus
{
    Draft       = 0,
    Active      = 1,
    Paused      = 2,
    Deprecated  = 3
}
```