using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Net.Mime;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using PaletteStream.Orchestrator.Application.Abstractions;
using PaletteStream.Orchestrator.Application.Contracts;
using PaletteStream.Orchestrator.Domain.Exceptions;

namespace PaletteStream.Orchestrator.Api
{
    /// <summary>
    /// Exposes HTTP endpoints for orchestrating ETL jobs.
    /// The controller delegates all business logic to <see cref="IJobOrchestratorService"/> keeping
    /// the layer thin and focused on transport-agnostic concerns (validation, HTTP status codes, etc.).
    /// </summary>
    [ApiController]
    [Route("api/[controller]")]
    [Produces(MediaTypeNames.Application.Json)]
    public sealed class JobsController : ControllerBase
    {
        private readonly IJobOrchestratorService _orchestrator;
        private readonly ILogger<JobsController> _logger;

        public JobsController(
            IJobOrchestratorService orchestrator,
            ILogger<JobsController> logger)
        {
            _orchestrator = orchestrator ?? throw new ArgumentNullException(nameof(orchestrator));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        /// <summary>
        /// Enqueues a new ETL job.  The job will be processed asynchronously by the orchestrator.
        /// </summary>
        /// <param name="request">Payload describing the job and its execution parameters.</param>
        /// <param name="ct">Cancellation token.</param>
        /// <returns>HTTP 202 with the newly created Job Id in the Location header.</returns>
        [HttpPost]
        [ProducesResponseType(StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public async Task<IActionResult> EnqueueJobAsync(
            [FromBody, Required] CreateJobRequest request,
            CancellationToken ct)
        {
            if (!ModelState.IsValid)
            {
                return ValidationProblem(ModelState);
            }

            try
            {
                var jobId = await _orchestrator.EnqueueAsync(request, ct).ConfigureAwait(false);

                // e.g. Location: /api/jobs/{jobId}
                Response.Headers.Location = Url.Action(nameof(GetJobAsync), new { jobId });

                return Accepted(new { id = jobId });
            }
            catch (InvalidJobDefinitionException ex)
            {
                _logger.LogWarning(ex, "Invalid job definition");
                return BadRequest(new ProblemDetails
                {
                    Detail = ex.Message,
                    Status = StatusCodes.Status400BadRequest,
                    Title = "Invalid job definition"
                });
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Unexpected error when enqueuing job");
                return StatusCode(StatusCodes.Status500InternalServerError,
                    new ProblemDetails
                    {
                        Status = StatusCodes.Status500InternalServerError,
                        Title = "Unexpected server error"
                    });
            }
        }

        /// <summary>
        /// Gets a summary for the given job id.
        /// </summary>
        /// <param name="jobId">The job identifier.</param>
        /// <param name="ct">Cancellation token.</param>
        /// <returns>Job summary details.</returns>
        [HttpGet("{jobId}")]
        [ProducesResponseType(typeof(JobStatusDto), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> GetJobAsync(
            [FromRoute, Required] string jobId,
            CancellationToken ct)
        {
            try
            {
                var job = await _orchestrator.GetStatusAsync(jobId, ct).ConfigureAwait(false);
                return Ok(job);
            }
            catch (JobNotFoundException)
            {
                return NotFound(new ProblemDetails
                {
                    Title = "Job not found",
                    Status = StatusCodes.Status404NotFound,
                    Detail = $"No job found with id '{jobId}'"
                });
            }
        }

        /// <summary>
        /// Lists a window of jobs ordered by creation date descending.
        /// This endpoint is optimized for infinite scrolling/virtualized lists in the UI.
        /// </summary>
        /// <param name="from">Optional cursor indicating the starting point (excluded).</param>
        /// <param name="limit">Number of jobs to return.</param>
        /// <param name="ct">Cancellation token.</param>
        /// <returns>A list of jobs.</returns>
        [HttpGet]
        [ProducesResponseType(typeof(IReadOnlyCollection<JobSummaryDto>), StatusCodes.Status200OK)]
        public async Task<IActionResult> ListJobsAsync(
            [FromQuery] DateTimeOffset? from,
            [FromQuery][Range(1, 250)] int limit = 50,
            CancellationToken ct = default)
        {
            var jobs = await _orchestrator
                .ListAsync(from, limit, ct)
                .ConfigureAwait(false);

            return Ok(jobs);
        }

        /// <summary>
        /// Cancels a running job or removes a scheduled one.  If the job has already completed,
        /// the operation is a no-op but still returns 200 OK for idempotency.
        /// </summary>
        /// <param name="jobId">The job identifier.</param>
        /// <returns>HTTP result code describing the action outcome.</returns>
        [HttpDelete("{jobId}")]
        [ProducesResponseType(StatusCodes.Status204NoContent)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> CancelJobAsync(
            [FromRoute, Required] string jobId,
            CancellationToken ct)
        {
            try
            {
                await _orchestrator.CancelAsync(jobId, ct).ConfigureAwait(false);
                return NoContent();
            }
            catch (JobNotFoundException)
            {
                return NotFound(new ProblemDetails
                {
                    Title = "Job not found",
                    Detail = $"No job found with id '{jobId}'",
                    Status = StatusCodes.Status404NotFound
                });
            }
            catch (InvalidJobStateException ex)
            {
                // Cannot cancel job in this state (e.g., completed or already canceled)
                _logger.LogInformation(ex, "Invalid job state when cancelling job {JobId}", jobId);
                return Conflict(new ProblemDetails
                {
                    Title = "Cannot cancel job",
                    Detail = ex.Message,
                    Status = StatusCodes.Status409Conflict
                });
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Unexpected error when cancelling job {JobId}", jobId);
                return StatusCode(StatusCodes.Status500InternalServerError,
                    new ProblemDetails
                    {
                        Title = "Unexpected server error",
                        Status = StatusCodes.Status500InternalServerError
                    });
            }
        }

        /// <summary>
        /// Replays (re-executes) a completed job using its original definition.
        /// Creates a new JobId and returns it. Replay operations are audited internally.
        /// </summary>
        [HttpPost("{jobId}/replay")]
        [ProducesResponseType(StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> ReplayJobAsync(
            [FromRoute, Required] string jobId,
            CancellationToken ct)
        {
            try
            {
                var newJobId = await _orchestrator.ReplayAsync(jobId, ct).ConfigureAwait(false);

                Response.Headers.Location = Url.Action(nameof(GetJobAsync), new { jobId = newJobId });
                return Accepted(new { id = newJobId });
            }
            catch (JobNotFoundException)
            {
                return NotFound(new ProblemDetails
                {
                    Title = "Job not found",
                    Status = StatusCodes.Status404NotFound,
                    Detail = $"No job found with id '{jobId}'"
                });
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Unexpected error when replaying job {JobId}", jobId);
                return StatusCode(StatusCodes.Status500InternalServerError,
                    new ProblemDetails
                    {
                        Title = "Unexpected server error",
                        Status = StatusCodes.Status500InternalServerError
                    });
            }
        }
    }
}