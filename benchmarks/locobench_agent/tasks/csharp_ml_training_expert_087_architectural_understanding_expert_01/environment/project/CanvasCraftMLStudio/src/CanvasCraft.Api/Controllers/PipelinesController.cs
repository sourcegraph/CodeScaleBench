```csharp
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Net.Mime;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Domain.Pipelines;
using CanvasCraft.Domain.Pipelines.Events;
using CanvasCraft.Domain.Pipelines.Models;
using CanvasCraft.Infrastructure.Observers;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Api.Controllers
{
    /// <summary>
    /// Exposes REST-style endpoints that orchestrate the end-to-end
    /// MLOps pipeline life-cycle (create, run, monitor, archive, etc.).
    /// The controller itself is intentionally thin and delegates all
    /// heavy-lifting to the <see cref="IPipelineOrchestrator"/> domain
    /// service, which internally relies on Strategy/Factory patterns so
    /// different data-prep brushes, feature-engineering palettes, or
    /// hyper-parameter color-wheels can be swapped at run-time.
    /// </summary>
    [ApiController]
    [Route("api/[controller]")]
    [Produces(MediaTypeNames.Application.Json)]
    public sealed class PipelinesController : ControllerBase
    {
        private readonly IPipelineOrchestrator _orchestrator;
        private readonly IDomainEventDispatcher _eventDispatcher;
        private readonly ILogger<PipelinesController> _logger;

        public PipelinesController(
            IPipelineOrchestrator orchestrator,
            IDomainEventDispatcher eventDispatcher,
            ILogger<PipelinesController> logger)
        {
            _orchestrator = orchestrator ?? throw new ArgumentNullException(nameof(orchestrator));
            _eventDispatcher = eventDispatcher ?? throw new ArgumentNullException(nameof(eventDispatcher));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        /// <summary>
        /// Returns a paginated list of all pipelines registered in the system.
        /// </summary>
        [HttpGet]
        [ProducesResponseType(typeof(IReadOnlyCollection<PipelineSummaryDto>), StatusCodes.Status200OK)]
        public async Task<IActionResult> ListAsync(
            [FromQuery] int page = 1,
            [FromQuery] int pageSize = 25,
            CancellationToken cancellationToken = default)
        {
            var pipelines = await _orchestrator.GetPipelinesAsync(page, pageSize, cancellationToken)
                                               .ConfigureAwait(false);

            return Ok(pipelines);
        }

        /// <summary>
        /// Retrieves rich details for a single pipeline, including last run &amp; artifact info.
        /// </summary>
        [HttpGet("{pipelineId:guid}", Name = nameof(GetByIdAsync))]
        [ProducesResponseType(typeof(PipelineDetailsDto), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> GetByIdAsync(
            Guid pipelineId,
            CancellationToken cancellationToken = default)
        {
            var details = await _orchestrator.GetPipelineAsync(pipelineId, cancellationToken)
                                             .ConfigureAwait(false);

            return details is null
                ? NotFound()
                : Ok(details);
        }

        /// <summary>
        /// Creates (or versions) a new pipeline definition.
        /// </summary>
        [HttpPost]
        [Consumes(MediaTypeNames.Application.Json)]
        [ProducesResponseType(typeof(PipelineDetailsDto), StatusCodes.Status201Created)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public async Task<IActionResult> CreateAsync(
            [FromBody] PipelineCreateRequest request,
            CancellationToken cancellationToken = default)
        {
            if (!ModelState.IsValid)
                return ValidationProblem(ModelState);

            try
            {
                var pipeline = await _orchestrator.CreatePipelineAsync(request, cancellationToken)
                                                  .ConfigureAwait(false);

                // Notify observers that a new creative pipeline was born.
                await _eventDispatcher.PublishAsync(new PipelineCreatedDomainEvent(pipeline.Id), cancellationToken)
                                      .ConfigureAwait(false);

                return CreatedAtRoute(nameof(GetByIdAsync), new { pipelineId = pipeline.Id }, pipeline);
            }
            catch (PipelineConflictException ex)
            {
                // Name might already be taken for a given version; surface conflict to caller.
                _logger.LogWarning(ex, "Pipeline conflict while creating {Name}", request.Name);
                return Conflict(new { ex.Message });
            }
        }

        /// <summary>
        /// Triggers an asynchronous run for a pipeline. The run is tracked inside
        /// the experiment-tracking subsystem and can be polled via <see cref="GetRunStatusAsync"/>.
        /// </summary>
        [HttpPost("{pipelineId:guid}/runs")]
        [ProducesResponseType(typeof(PipelineRunDetailsDto), StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> RunAsync(
            Guid pipelineId,
            [FromBody] PipelineRunRequest request,
            CancellationToken cancellationToken = default)
        {
            if (!ModelState.IsValid) return ValidationProblem(ModelState);

            var run = await _orchestrator.TriggerRunAsync(pipelineId, request, cancellationToken)
                                         .ConfigureAwait(false);

            if (run is null) return NotFound();

            _ = Task.Run(async () =>
            {
                // Fire-and-forget background monitoring, will push out DomainEvents
                // that external observers (Slack, email, UI signalR hubs) can react to.
                await _eventDispatcher.PublishAsync(new PipelineRunStartedDomainEvent(run.Id), CancellationToken.None);
            }, CancellationToken.None);

            return AcceptedAtRoute(nameof(GetRunStatusAsync), new { pipelineId, runId = run.Id }, run);
        }

        /// <summary>
        /// Returns the current status for a particular run instance.
        /// </summary>
        [HttpGet("{pipelineId:guid}/runs/{runId:guid}", Name = nameof(GetRunStatusAsync))]
        [ProducesResponseType(typeof(PipelineRunStatusDto), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> GetRunStatusAsync(
            Guid pipelineId,
            Guid runId,
            CancellationToken cancellationToken = default)
        {
            var status = await _orchestrator.GetRunStatusAsync(pipelineId, runId, cancellationToken)
                                            .ConfigureAwait(false);

            return status is null ? NotFound() : Ok(status);
        }

        /// <summary>
        /// Soft-deletes (archives) a pipeline, keeping historical runs but preventing new ones.
        /// </summary>
        [HttpDelete("{pipelineId:guid}")]
        [ProducesResponseType(StatusCodes.Status204NoContent)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> ArchiveAsync(
            Guid pipelineId,
            CancellationToken cancellationToken = default)
        {
            var archived = await _orchestrator.ArchiveAsync(pipelineId, cancellationToken)
                                              .ConfigureAwait(false);

            if (!archived) return NotFound();

            await _eventDispatcher.PublishAsync(new PipelineArchivedDomainEvent(pipelineId), cancellationToken)
                                  .ConfigureAwait(false);

            return NoContent();
        }
    }

    #region DTO Contracts

    /// <summary>
    /// Client-side contract for creating a new pipeline.
    /// </summary>
    public sealed class PipelineCreateRequest
    {
        [Required, MaxLength(128)]
        public string Name { get; init; } = default!;

        [MaxLength(1024)]
        public string? Description { get; init; }

        /// <summary>
        /// Optional parent pipeline to create a branched series from.
        /// </summary>
        public Guid? BasePipelineId { get; init; }

        /// <summary>
        /// Initial version tag (e.g. "v1-sketch").
        /// </summary>
        [RegularExpression(@"^[a-zA-Z0-9_\-]+$")]
        public string? InitialVersion { get; init; }
    }

    /// <summary>
    /// Contract for invoking a run on a pipeline.
    /// </summary>
    public sealed class PipelineRunRequest
    {
        /// <summary>
        /// Which trained model (checkpoint) to start from, if any.
        /// </summary>
        public Guid? CheckpointId { get; init; }

        /// <summary>
        /// Arbitrary run-level metadata (e.g. "style=monet", "seed=42").
        /// </summary>
        public IDictionary<string, string>? Tags { get; init; }
    }

    /// <summary>
    /// Lightweight list view object.
    /// </summary>
    public sealed record PipelineSummaryDto(
        Guid Id,
        string Name,
        string Version,
        PipelineLifecycleState State,
        DateTimeOffset? LastRunUtc);

    /// <summary>
    /// Rich details for a single pipeline.
    /// </summary>
    public sealed record PipelineDetailsDto(
        Guid Id,
        string Name,
        string Version,
        string? Description,
        PipelineLifecycleState State,
        DateTimeOffset CreatedUtc,
        DateTimeOffset? LastRunUtc,
        IReadOnlyCollection<PipelineComponentDto> Components);

    /// <summary>
    /// DTO giving immediate feedback once a run is scheduled.
    /// </summary>
    public sealed record PipelineRunDetailsDto(
        Guid Id,
        Guid PipelineId,
        PipelineRunStatus Status,
        DateTimeOffset CreatedUtc);

    /// <summary>
    /// DTO used for polling run status.
    /// </summary>
    public sealed record PipelineRunStatusDto(
        Guid Id,
        PipelineRunStatus Status,
        double Progress,
        string? Message,
        DateTimeOffset LastUpdatedUtc);

    /// <summary>
    /// A single component in the pipeline DAG (e.g. data loader, featurizer, trainer).
    /// </summary>
    public sealed record PipelineComponentDto(
        string Id,
        string Type,
        string Label,
        string? Description);

    #endregion
}
```