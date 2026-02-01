```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright>
//   © PaletteStream ETL Canvas. All rights reserved.
// </copyright>
// --------------------------------------------------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Net.Mime;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using PaletteStream.Orchestrator.Abstractions;
using PaletteStream.Orchestrator.Domain;
using PaletteStream.Orchestrator.Domain.Exceptions;
using PaletteStream.Orchestrator.Domain.Models;
using PaletteStream.Orchestrator.Domain.Requests;

namespace PaletteStream.Orchestrator.Api
{
    /// <summary>
    /// Exposes CRUD and control operations for ETL pipelines.
    /// </summary>
    /// <remarks>
    /// The controller is intentionally thin; all heavy-lifting is delegated to the injected
    /// <see cref="IPipelineOrchestratorService"/> which coordinates with Hangfire (batch),
    /// Kafka (stream), and GPU compute services under the hood.
    /// </remarks>
    [ApiController]
    [ApiVersion("1.0")]
    [Route("api/v{version:apiVersion}/[controller]")]
    [Produces(MediaTypeNames.Application.Json)]
    public sealed class PipelinesController : ControllerBase
    {
        private readonly IPipelineOrchestratorService _orchestratorService;
        private readonly ILogger<PipelinesController>  _logger;

        public PipelinesController(
            IPipelineOrchestratorService orchestratorService,
            ILogger<PipelinesController> logger)
        {
            _orchestratorService = orchestratorService ?? throw new ArgumentNullException(nameof(orchestratorService));
            _logger              = logger               ?? throw new ArgumentNullException(nameof(logger));
        }

        #region CRUD

        /// <summary>
        ///     Returns a paged collection of pipelines.
        /// </summary>
        [HttpGet]
        [ProducesResponseType(StatusCodes.Status200OK)]
        public async Task<ActionResult<IEnumerable<PipelineDto>>> GetAsync(
            [FromQuery] int page      = 1,
            [FromQuery] int pageSize  = 50,
            CancellationToken ct      = default)
        {
            var result = await _orchestratorService.ListAsync(page, pageSize, ct);
            return Ok(result);
        }

        /// <summary>
        ///     Retrieves a pipeline by id.
        /// </summary>
        [HttpGet("{pipelineId:guid}")]
        [ProducesResponseType(StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<ActionResult<PipelineDto>> GetByIdAsync(
            Guid pipelineId,
            CancellationToken ct = default)
        {
            var pipeline = await _orchestratorService.GetAsync(pipelineId, ct);
            if (pipeline is null)
            {
                return NotFound();
            }

            return Ok(pipeline);
        }

        /// <summary>
        ///     Creates a new pipeline definition but does not start it.
        /// </summary>
        [HttpPost]
        [ProducesResponseType(StatusCodes.Status201Created)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public async Task<ActionResult<PipelineDto>> CreateAsync(
            [FromBody] PipelineCreateRequest request,
            CancellationToken ct = default)
        {
            if (!ModelState.IsValid)
            {
                return ValidationProblem(ModelState);
            }

            try
            {
                var pipeline = await _orchestratorService.CreateAsync(request, ct);

                return CreatedAtAction(
                    nameof(GetByIdAsync),
                    new { pipelineId = pipeline.Id, version = HttpContext.GetRequestedApiVersion()?.ToString() ?? "1.0" },
                    pipeline);
            }
            catch (PipelineValidationException ex)
            {
                _logger.LogWarning(ex, "Pipeline validation failed. {Message}", ex.Message);
                return BadRequest(new ProblemDetails
                {
                    Title  = "Invalid pipeline definition",
                    Detail = ex.Message,
                    Status = StatusCodes.Status400BadRequest
                });
            }
        }

        /// <summary>
        ///     Removes an existing pipeline. If the pipeline is still running, the operation is rejected.
        /// </summary>
        [HttpDelete("{pipelineId:guid}")]
        [ProducesResponseType(StatusCodes.Status204NoContent)]
        [ProducesResponseType(StatusCodes.Status409Conflict)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> DeleteAsync(
            Guid pipelineId,
            CancellationToken ct = default)
        {
            try
            {
                await _orchestratorService.DeleteAsync(pipelineId, ct);
                return NoContent();
            }
            catch (PipelineNotFoundException)
            {
                return NotFound();
            }
            catch (PipelineStateException ex)
            {
                _logger.LogWarning(ex, "Pipeline deletion rejected due to invalid state.");
                return Conflict(new ProblemDetails
                {
                    Title  = "Cannot delete pipeline",
                    Detail = ex.Message,
                    Status = StatusCodes.Status409Conflict
                });
            }
        }

        #endregion

        #region Commands

        /// <summary>
        ///     Schedules a pipeline for execution.
        /// </summary>
        [HttpPost("{pipelineId:guid}/start")]
        [ProducesResponseType(StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status409Conflict)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> StartAsync(
            Guid pipelineId,
            CancellationToken ct = default)
        {
            try
            {
                await _orchestratorService.StartAsync(pipelineId, ct);
                return Accepted();
            }
            catch (PipelineNotFoundException)
            {
                return NotFound();
            }
            catch (PipelineStateException ex)
            {
                return Conflict(new ProblemDetails
                {
                    Title  = "Cannot start pipeline",
                    Detail = ex.Message,
                    Status = StatusCodes.Status409Conflict
                });
            }
        }

        /// <summary>
        ///     Pauses the pipeline. If streaming, this will commit offsets and halt consumption.
        /// </summary>
        [HttpPost("{pipelineId:guid}/pause")]
        [ProducesResponseType(StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status409Conflict)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> PauseAsync(
            Guid pipelineId,
            CancellationToken ct = default)
        {
            try
            {
                await _orchestratorService.PauseAsync(pipelineId, ct);
                return Accepted();
            }
            catch (PipelineNotFoundException)
            {
                return NotFound();
            }
            catch (PipelineStateException ex)
            {
                return Conflict(new ProblemDetails
                {
                    Title  = "Cannot pause pipeline",
                    Detail = ex.Message,
                    Status = StatusCodes.Status409Conflict
                });
            }
        }

        /// <summary>
        ///     Resumes a paused pipeline.
        /// </summary>
        [HttpPost("{pipelineId:guid}/resume")]
        [ProducesResponseType(StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status409Conflict)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> ResumeAsync(
            Guid pipelineId,
            CancellationToken ct = default)
        {
            try
            {
                await _orchestratorService.ResumeAsync(pipelineId, ct);
                return Accepted();
            }
            catch (PipelineNotFoundException)
            {
                return NotFound();
            }
            catch (PipelineStateException ex)
            {
                return Conflict(new ProblemDetails
                {
                    Title  = "Cannot resume pipeline",
                    Detail = ex.Message,
                    Status = StatusCodes.Status409Conflict
                });
            }
        }

        /// <summary>
        ///     Gracefully stops the pipeline, finalizing in-flight operations.
        /// </summary>
        [HttpPost("{pipelineId:guid}/stop")]
        [ProducesResponseType(StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status409Conflict)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> StopAsync(
            Guid pipelineId,
            CancellationToken ct = default)
        {
            try
            {
                await _orchestratorService.StopAsync(pipelineId, ct);
                return Accepted();
            }
            catch (PipelineNotFoundException)
            {
                return NotFound();
            }
            catch (PipelineStateException ex)
            {
                return Conflict(new ProblemDetails
                {
                    Title  = "Cannot stop pipeline",
                    Detail = ex.Message,
                    Status = StatusCodes.Status409Conflict
                });
            }
        }

        #endregion
    }
}
```