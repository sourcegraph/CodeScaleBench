```csharp
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Net.Mime;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Core.Domain.Experiments;
using CanvasCraft.Core.Exceptions;
using CanvasCraft.Core.Services;
using CanvasCraft.Core.Services.Monitoring;
using CanvasCraft.Core.Services.Registry;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Api.Controllers
{
    /// <summary>
    /// REST-ful endpoints that expose core functionality for Experiment
    /// lifecycle management and experiment-level interactions with the
    /// Feature Store, Experiment Tracker and Model Registry.
    /// </summary>
    [ApiController]
    [Route("api/[controller]")]
    [Produces(MediaTypeNames.Application.Json)]
    public sealed class ExperimentsController : ControllerBase
    {
        private readonly IExperimentService _experimentService;
        private readonly IModelRegistryService _modelRegistry;
        private readonly IMetricStreamingService _metricStream;
        private readonly ILogger<ExperimentsController> _logger;

        public ExperimentsController(
            IExperimentService experimentService,
            IModelRegistryService modelRegistry,
            IMetricStreamingService metricStream,
            ILogger<ExperimentsController> logger)
        {
            _experimentService = experimentService;
            _modelRegistry = modelRegistry;
            _metricStream = metricStream;
            _logger = logger;
        }

        #region ––––––––––––––– CRUD –––––––––––––––

        /// <summary>
        /// Fetch paged list of Experiments.
        /// </summary>
        /// <remarks>
        /// Queryable by name, tag or status.
        /// </remarks>
        [HttpGet]
        [ProducesResponseType(typeof(PagedResult<ExperimentDto>), StatusCodes.Status200OK)]
        public async Task<IActionResult> GetAllAsync(
            [FromQuery] string? tag,
            [FromQuery] string? search,
            [FromQuery, Range(1, 250)] int pageSize = 50,
            [FromQuery, Range(1, int.MaxValue)] int page = 1,
            CancellationToken ct = default)
        {
            var result = await _experimentService
                .GetAsync(tag, search, pageSize, page, ct)
                .ConfigureAwait(false);

            return Ok(result.Select(MapToDto));
        }

        /// <summary>
        /// Fetch single Experiment detail.
        /// </summary>
        [HttpGet("{experimentId:guid}", Name = nameof(GetByIdAsync))]
        [ProducesResponseType(typeof(ExperimentDto), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> GetByIdAsync(Guid experimentId, CancellationToken ct = default)
        {
            try
            {
                var experiment = await _experimentService.FindAsync(experimentId, ct);
                return Ok(MapToDto(experiment));
            }
            catch (EntityNotFoundException e)
            {
                _logger.LogWarning(e, "Experiment {ExperimentId} not found.", experimentId);
                return NotFound();
            }
        }

        /// <summary>
        /// Create a new Experiment (does not run training yet).
        /// </summary>
        [HttpPost]
        [ProducesResponseType(typeof(ExperimentDto), StatusCodes.Status201Created)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public async Task<IActionResult> CreateAsync(
            [FromBody] CreateExperimentRequest request,
            CancellationToken ct = default)
        {
            if (!ModelState.IsValid) return BadRequest(ModelState);

            var experiment = await _experimentService
                .CreateAsync(request.Name, request.Description, request.Tags, ct)
                .ConfigureAwait(false);

            return CreatedAtRoute(
                nameof(GetByIdAsync),
                new { experimentId = experiment.Id },
                MapToDto(experiment));
        }

        /// <summary>
        /// Update metadata for an Experiment.
        /// </summary>
        [HttpPut("{experimentId:guid}")]
        [ProducesResponseType(StatusCodes.Status204NoContent)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> UpdateMetadataAsync(
            Guid experimentId,
            [FromBody] UpdateExperimentRequest request,
            CancellationToken ct = default)
        {
            if (!ModelState.IsValid) return BadRequest(ModelState);

            try
            {
                await _experimentService.UpdateMetadataAsync(
                    experimentId,
                    request.Description,
                    request.Tags,
                    ct);
                return NoContent();
            }
            catch (EntityNotFoundException e)
            {
                _logger.LogWarning(e, "Experiment {ExperimentId} not found.", experimentId);
                return NotFound();
            }
        }

        /// <summary>
        /// Archive an Experiment (soft delete).
        /// </summary>
        [HttpDelete("{experimentId:guid}")]
        [ProducesResponseType(StatusCodes.Status204NoContent)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> ArchiveAsync(Guid experimentId, CancellationToken ct = default)
        {
            try
            {
                await _experimentService.ArchiveAsync(experimentId, ct);
                return NoContent();
            }
            catch (EntityNotFoundException e)
            {
                _logger.LogWarning(e, "Attempted to archive missing Experiment {ExperimentId}.", experimentId);
                return NotFound();
            }
        }

        #endregion

        #region ––––––––––––––– Lifecycle Hooks –––––––––––––––

        /// <summary>
        /// Trigger an Experiment run (model training / tuning).
        /// </summary>
        [HttpPost("{experimentId:guid}/run")]
        [ProducesResponseType(typeof(RunStartedResponse), StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> RunAsync(Guid experimentId, CancellationToken ct = default)
        {
            try
            {
                var runId = await _experimentService.StartRunAsync(experimentId, ct);
                _logger.LogInformation("Started run {RunId} for Experiment {ExperimentId}.", runId, experimentId);

                return AcceptedAtRoute(
                    nameof(GetRunMetricsAsync),
                    new { experimentId, runId },
                    new RunStartedResponse(runId));
            }
            catch (EntityNotFoundException e)
            {
                _logger.LogWarning(e, "Experiment {ExperimentId} not found.", experimentId);
                return NotFound();
            }
            catch (ExperimentAlreadyRunningException e)
            {
                // 409 Conflict when a run is already in progress
                return Conflict(new { e.Message });
            }
        }

        /// <summary>
        /// Roll back an Experiment to a specified checkpoint and
        /// register the reverted model in the Model Registry.
        /// </summary>
        [HttpPost("{experimentId:guid}/rollback/{checkpointId:guid}")]
        [ProducesResponseType(typeof(CheckpointRollbackResponse), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> RollbackAsync(
            Guid experimentId,
            Guid checkpointId,
            CancellationToken ct = default)
        {
            try
            {
                var modelArtifact = await _experimentService.RollbackAsync(
                    experimentId,
                    checkpointId,
                    ct);

                var registryRef = await _modelRegistry.RegisterAsync(modelArtifact, ct);

                return Ok(new CheckpointRollbackResponse(
                    registryRef.ModelVersionId,
                    registryRef.Uri));
            }
            catch (EntityNotFoundException e)
            {
                _logger.LogWarning(e, "Rollback target not found. Experiment: {ExperimentId}, Checkpoint: {CheckpointId}", experimentId, checkpointId);
                return NotFound();
            }
            catch (InvalidOperationException e)
            {
                return BadRequest(new { e.Message });
            }
        }

        #endregion

        #region ––––––––––––––– Metrics & Streaming –––––––––––––––

        /// <summary>
        /// Get aggregate metrics for a specific run.
        /// </summary>
        [HttpGet("{experimentId:guid}/runs/{runId:guid}/metrics", Name = nameof(GetRunMetricsAsync))]
        [ProducesResponseType(typeof(IEnumerable<MetricDto>), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> GetRunMetricsAsync(
            Guid experimentId,
            Guid runId,
            CancellationToken ct = default)
        {
            try
            {
                var metrics = await _experimentService.GetMetricsAsync(experimentId, runId, ct);
                return Ok(metrics.Select(m => new MetricDto(m.Key, m.Value, m.Timestamp)));
            }
            catch (EntityNotFoundException)
            {
                return NotFound();
            }
        }

        /// <summary>
        /// Server-Sent Event (SSE) stream of live metric updates.
        /// </summary>
        [HttpGet("{experimentId:guid}/runs/{runId:guid}/metrics/stream")]
        public async Task StreamMetricsAsync(
            Guid experimentId,
            Guid runId,
            CancellationToken ct = default)
        {
            Response.Headers.Add("Content-Type", "text/event-stream");

            await foreach (var metric in _metricStream.StreamAsync(experimentId, runId, ct))
            {
                await Response
                    .WriteAsync($"data: {System.Text.Json.JsonSerializer.Serialize(metric)}\n\n", ct)
                    .ConfigureAwait(false);

                await Response.Body.FlushAsync(ct).ConfigureAwait(false);

                if (ct.IsCancellationRequested)
                {
                    break;
                }
            }
        }

        #endregion

        #region ––––––––––––––– Mappers / DTOs –––––––––––––––

        private static ExperimentDto MapToDto(Experiment exp) => new(
            exp.Id,
            exp.Name,
            exp.Description,
            exp.Status.ToString(),
            exp.CreatedUtc,
            exp.UpdatedUtc,
            exp.Tags);

        public record ExperimentDto(
            Guid Id,
            string Name,
            string? Description,
            string Status,
            DateTime CreatedUtc,
            DateTime UpdatedUtc,
            IReadOnlyCollection<string> Tags);

        public record MetricDto(
            string Name,
            double Value,
            DateTime TimestampUtc);

        public record PagedResult<T>(IEnumerable<T> Items, int Page, int PageSize, long Total);

        public sealed class CreateExperimentRequest
        {
            [Required]
            [StringLength(128, MinimumLength = 3)]
            public string Name { get; init; } = default!;

            [StringLength(2048)]
            public string? Description { get; init; }

            public IReadOnlyCollection<string>? Tags { get; init; }
        }

        public sealed class UpdateExperimentRequest
        {
            [StringLength(2048)]
            public string? Description { get; init; }

            public IReadOnlyCollection<string>? Tags { get; init; }
        }

        public record RunStartedResponse(Guid RunId);

        public record CheckpointRollbackResponse(Guid ModelVersionId, string RegisteredUri);

        #endregion
    }
}
```
