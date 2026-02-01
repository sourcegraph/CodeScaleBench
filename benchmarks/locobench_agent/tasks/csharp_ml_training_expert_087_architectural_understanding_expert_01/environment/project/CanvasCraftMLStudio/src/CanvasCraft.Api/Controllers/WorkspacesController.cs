```csharp
using System;
using System.Collections.Generic;
using System.Net.Mime;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Api.Contracts;
using CanvasCraft.Application.Abstractions;
using CanvasCraft.Domain.Exceptions;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Api.Controllers
{
    /// <summary>
    ///     REST controller responsible for CRUD operations and
    ///     higher-level workflow orchestration for <see cref="WorkspaceDto"/> resources.
    ///     
    ///     A “workspace” in CanvasCraft represents an isolated sandbox for
    ///     creative ML experimentation. Each workspace contains its own dataset
    ///     lineage, feature-engineering graphs, model checkpoints, experiment
    ///     logs, and visualization artifacts.
    /// </summary>
    [ApiController]
    [ApiVersion("1.0")]
    [Consumes(MediaTypeNames.Application.Json)]
    [Produces(MediaTypeNames.Application.Json)]
    [Route("api/v{version:apiVersion}/[controller]")]
    public sealed class WorkspacesController : ControllerBase
    {
        private readonly IWorkspaceService _workspaceService;
        private readonly ILogger<WorkspacesController> _logger;

        public WorkspacesController(
            IWorkspaceService workspaceService,
            ILogger<WorkspacesController> logger)
        {
            _workspaceService = workspaceService ?? throw new ArgumentNullException(nameof(workspaceService));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        #region GET

        /// <summary>
        ///     Returns a paginated list of workspaces that the current user
        ///     has permission to access.
        /// </summary>
        [HttpGet]
        [ProducesResponseType(typeof(PagedResult<WorkspaceDto>), StatusCodes.Status200OK)]
        public async Task<ActionResult<PagedResult<WorkspaceDto>>> GetAsync(
            [FromQuery] WorkspaceFilter filter,
            [FromQuery] PagingOptions paging,
            CancellationToken cancellationToken = default)
        {
            var result = await _workspaceService
               .GetAsync(filter, paging, cancellationToken)
               .ConfigureAwait(false);

            return Ok(result);
        }

        /// <summary>
        ///     Retrieves metadata for a single workspace.
        /// </summary>
        [HttpGet("{workspaceId:guid}", Name = nameof(GetByIdAsync))]
        [ProducesResponseType(typeof(WorkspaceDto), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<ActionResult<WorkspaceDto>> GetByIdAsync(
            Guid workspaceId,
            CancellationToken cancellationToken = default)
        {
            try
            {
                var workspace = await _workspaceService
                   .GetByIdAsync(workspaceId, cancellationToken)
                   .ConfigureAwait(false);

                return Ok(workspace);
            }
            catch (EntityNotFoundException ex)
            {
                _logger.LogWarning(ex, "Workspace {WorkspaceId} not found", workspaceId);
                return NotFound();
            }
        }

        #endregion

        #region POST

        /// <summary>
        ///     Creates a new workspace.
        /// </summary>
        [HttpPost]
        [ProducesResponseType(typeof(WorkspaceDto), StatusCodes.Status201Created)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public async Task<ActionResult<WorkspaceDto>> CreateAsync(
            [FromBody] CreateWorkspaceRequest request,
            CancellationToken cancellationToken = default)
        {
            if (!ModelState.IsValid)
                return BadRequest(ModelState);

            var workspace = await _workspaceService
               .CreateAsync(request, cancellationToken)
               .ConfigureAwait(false);

            return CreatedAtRoute(nameof(GetByIdAsync),
                new { workspaceId = workspace.Id, version = HttpContext.GetRequestedApiVersion() },
                workspace);
        }

        /// <summary>
        ///     Clones an existing workspace, including its artifacts, into
        ///     a new branch.
        /// </summary>
        [HttpPost("{workspaceId:guid}/clone")]
        [ProducesResponseType(typeof(WorkspaceDto), StatusCodes.Status201Created)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<ActionResult<WorkspaceDto>> CloneAsync(
            Guid workspaceId,
            [FromBody] CloneWorkspaceRequest request,
            CancellationToken cancellationToken = default)
        {
            try
            {
                var clone = await _workspaceService
                   .CloneAsync(workspaceId, request, cancellationToken)
                   .ConfigureAwait(false);

                return CreatedAtRoute(nameof(GetByIdAsync),
                    new { workspaceId = clone.Id, version = HttpContext.GetRequestedApiVersion() },
                    clone);
            }
            catch (EntityNotFoundException)
            {
                return NotFound();
            }
        }

        #endregion

        #region PUT

        /// <summary>
        ///     Updates mutable metadata for a workspace. Immutable artifacts such
        ///     as experiment history remain untouched.
        /// </summary>
        [HttpPut("{workspaceId:guid}")]
        [ProducesResponseType(StatusCodes.Status204NoContent)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> UpdateAsync(
            Guid workspaceId,
            [FromBody] UpdateWorkspaceRequest request,
            CancellationToken cancellationToken = default)
        {
            try
            {
                await _workspaceService
                   .UpdateAsync(workspaceId, request, cancellationToken)
                   .ConfigureAwait(false);

                return NoContent();
            }
            catch (EntityNotFoundException)
            {
                return NotFound();
            }
        }

        #endregion

        #region DELETE

        /// <summary>
        ///     Permanently deletes a workspace along with its artifacts.
        ///     This operation is destructive and cannot be undone.
        /// </summary>
        [HttpDelete("{workspaceId:guid}")]
        [ProducesResponseType(StatusCodes.Status204NoContent)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> DeleteAsync(
            Guid workspaceId,
            CancellationToken cancellationToken = default)
        {
            try
            {
                await _workspaceService
                   .DeleteAsync(workspaceId, cancellationToken)
                   .ConfigureAwait(false);

                return NoContent();
            }
            catch (EntityNotFoundException)
            {
                return NotFound();
            }
        }

        #endregion

        #region Domain-specific actions

        /// <summary>
        ///     Schedules a training job for all models inside the workspace using
        ///     the currently configured pipeline brushes, palettes, and tuning wheels.
        /// </summary>
        [HttpPost("{workspaceId:guid}/train")]
        [ProducesResponseType(typeof(TrainingJobDto), StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<ActionResult<TrainingJobDto>> TrainAsync(
            Guid workspaceId,
            [FromBody] LaunchTrainingRequest request,
            CancellationToken cancellationToken = default)
        {
            try
            {
                var job = await _workspaceService
                   .TrainAsync(workspaceId, request, cancellationToken)
                   .ConfigureAwait(false);

                return AcceptedAtRoute(
                    routeName: "GetTrainingJobById",
                    routeValues: new { jobId = job.Id, version = HttpContext.GetRequestedApiVersion() },
                    job);
            }
            catch (EntityNotFoundException)
            {
                return NotFound();
            }
        }

        #endregion
    }
}

/* -----------------------------------------------------------
 * Below are lightweight DTO/contract classes used exclusively
 * by this controller. In the production codebase they would be
 * placed in distinct files under CanvasCraft.Api.Contracts
 * ----------------------------------------------------------*/

namespace CanvasCraft.Api.Contracts
{
    using System;
    using System.ComponentModel.DataAnnotations;

    public sealed class WorkspaceDto
    {
        public Guid Id { get; init; }
        public string Name { get; init; } = default!;
        public string Description { get; init; } = default!;
        public DateTimeOffset CreatedAtUtc { get; init; }
        public DateTimeOffset? UpdatedAtUtc { get; init; }
    }

    public sealed class CreateWorkspaceRequest
    {
        [Required, MinLength(3), MaxLength(100)]
        public string Name { get; set; } = default!;

        [MaxLength(1024)]
        public string? Description { get; set; }
    }

    public sealed class UpdateWorkspaceRequest
    {
        [Required, MinLength(3), MaxLength(100)]
        public string Name { get; set; } = default!;

        [MaxLength(1024)]
        public string? Description { get; set; }
    }

    public sealed class CloneWorkspaceRequest
    {
        [Required, MinLength(3), MaxLength(100)]
        public string Name { get; set; } = default!;

        [MaxLength(1024)]
        public string? Description { get; set; }

        /// <summary>
        ///     Optional flag that dictates whether associated feature-store
        ///     artifacts should be deep-copied or referenced.
        /// </summary>
        public bool DeepCopyFeatureStore { get; set; } = true;
    }

    public sealed class LaunchTrainingRequest
    {
        /// <summary>
        ///     Optional human-readable label for the training run.
        /// </summary>
        [MaxLength(256)]
        public string? RunName { get; set; }

        /// <summary>
        ///     If true, experimental hyper-parameter tuning wheels are activated.
        /// </summary>
        public bool EnableHyperparameterTuning { get; set; }
    }

    public sealed class TrainingJobDto
    {
        public Guid Id { get; init; }
        public Guid WorkspaceId { get; init; }
        public string Status { get; init; } = default!;
        public DateTimeOffset CreatedAtUtc { get; init; }
    }

    public sealed class WorkspaceFilter
    {
        public string? Search { get; init; }
    }

    public sealed class PagingOptions
    {
        private const int MaxPageSize = 100;

        public int Offset { get; init; } = 0;

        private int _limit = 20;
        public int Limit
        {
            get => _limit;
            init => _limit = value > MaxPageSize ? MaxPageSize : value;
        }
    }

    public sealed class PagedResult<T>
    {
        public IReadOnlyCollection<T> Items { get; init; } = Array.Empty<T>();
        public int Offset { get; init; }
        public int Limit { get; init; }
        public long Total { get; init; }
    }
}

/* -----------------------------------------------------------
 * Domain exceptions referenced by the controller.
 * In the real solution these live under CanvasCraft.Domain.
 * ----------------------------------------------------------*/

namespace CanvasCraft.Domain.Exceptions
{
    using System;

    /// <summary>
    ///     Thrown when a requested entity is not found in the persistence layer.
    /// </summary>
    public sealed class EntityNotFoundException : Exception
    {
        public EntityNotFoundException() : base() { }
        public EntityNotFoundException(string message) : base(message) { }
        public EntityNotFoundException(string message, Exception innerException) : base(message, innerException) { }
    }
}

/* -----------------------------------------------------------
 * Service abstraction injected into the controller.
 * Typically implemented in Application layer.
 * ----------------------------------------------------------*/

namespace CanvasCraft.Application.Abstractions
{
    using System;
    using System.Threading;
    using System.Threading.Tasks;
    using CanvasCraft.Api.Contracts;

    public interface IWorkspaceService
    {
        Task<PagedResult<WorkspaceDto>> GetAsync(
            WorkspaceFilter filter,
            PagingOptions paging,
            CancellationToken cancellationToken = default);

        Task<WorkspaceDto> GetByIdAsync(
            Guid workspaceId,
            CancellationToken cancellationToken = default);

        Task<WorkspaceDto> CreateAsync(
            CreateWorkspaceRequest request,
            CancellationToken cancellationToken = default);

        Task UpdateAsync(
            Guid workspaceId,
            UpdateWorkspaceRequest request,
            CancellationToken cancellationToken = default);

        Task DeleteAsync(
            Guid workspaceId,
            CancellationToken cancellationToken = default);

        Task<WorkspaceDto> CloneAsync(
            Guid workspaceId,
            CloneWorkspaceRequest request,
            CancellationToken cancellationToken = default);

        Task<TrainingJobDto> TrainAsync(
            Guid workspaceId,
            LaunchTrainingRequest request,
            CancellationToken cancellationToken = default);
    }
}
```