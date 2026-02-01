```csharp
#nullable enable
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Api.Common;
using CanvasCraft.Api.Contracts.Datasets;
using CanvasCraft.Api.Services;
using CanvasCraft.Domain.Exceptions;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Api.Controllers
{
    /// <summary>
    ///     Provides a RESTful surface for managing dataset life-cycles, from raw ingestion
    ///     all the way through preprocessing and versioned persistence in the Feature Store.
    ///     The controller purposefully remains thin, delegating business logic to the
    ///     <see cref="IDatasetService" /> application service to preserve SRP.
    /// </summary>
    [ApiController]
    [Route("api/[controller]")]
    [Produces("application/json")]
    public sealed class DatasetsController : ControllerBase
    {
        private readonly IDatasetService _datasetService;
        private readonly ILogger<DatasetsController> _logger;

        public DatasetsController(IDatasetService datasetService,
                                  ILogger<DatasetsController> logger)
        {
            _datasetService = datasetService ?? throw new ArgumentNullException(nameof(datasetService));
            _logger         = logger         ?? throw new ArgumentNullException(nameof(logger));
        }

        #region Query

        /// <summary>Returns a paged collection of datasets.</summary>
        [HttpGet]
        [ProducesResponseType(typeof(PagedResponse<DatasetDto>), StatusCodes.Status200OK)]
        public async Task<ActionResult<PagedResponse<DatasetDto>>> BrowseAsync(
            [FromQuery] DatasetQueryParameters query,
            CancellationToken                   cancellationToken = default)
        {
            var datasets = await _datasetService.BrowseAsync(query, cancellationToken);
            return Ok(datasets);
        }

        /// <summary>Returns the dataset specified by <paramref name="id" />.</summary>
        [HttpGet("{id:guid}")]
        [ProducesResponseType(typeof(DatasetDto), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<ActionResult<DatasetDto>> GetAsync(Guid id, CancellationToken cancellationToken = default)
        {
            var dataset = await _datasetService.GetByIdAsync(id, cancellationToken);

            if (dataset is null)
                return NotFound();

            Response.Headers.ETag = $"\"{dataset.RowVersion}\"";
            return Ok(dataset);
        }

        #endregion

        #region Command – CRUD

        /// <summary>Creates a new dataset entry and returns the created resource.</summary>
        [HttpPost]
        [ProducesResponseType(typeof(DatasetDto), StatusCodes.Status201Created)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public async Task<ActionResult<DatasetDto>> CreateAsync(
            [FromBody] CreateDatasetRequest        request,
            CancellationToken                      cancellationToken = default)
        {
            if (!ModelState.IsValid)
                return ValidationProblem();

            var created = await _datasetService.CreateAsync(request, cancellationToken);

            return CreatedAtAction(nameof(GetAsync), new { id = created.Id }, created);
        }

        /// <summary>
        ///     Uploads a raw data file for a given dataset.
        ///     The file is streamed directly to durable storage (S3, Azure Blob, …)
        ///     and an ingestion pipeline is kicked off asynchronously.
        /// </summary>
        [HttpPost("{id:guid}/upload")]
        [RequestSizeLimit(2L * 1024 * 1024 * 1024)]                    // 2 GB
        [ProducesResponseType(StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public async Task<IActionResult> UploadAsync(
            Guid                id,
            [FromForm] IFormFile file,
            CancellationToken   cancellationToken = default)
        {
            if (file is null || file.Length == 0)
                return BadRequest("No file supplied.");

            await using var stream = file.OpenReadStream();
            await _datasetService.IngestRawAsync(id, stream, file.FileName, cancellationToken);

            return Accepted();
        }

        /// <summary>
        ///     Starts the preprocessing pipeline on the given dataset by delegating to
        ///     a Strategy chosen via <see cref="PreprocessDatasetRequest.PipelineStrategy" />.
        /// </summary>
        [HttpPost("{id:guid}/preprocess")]
        [ProducesResponseType(typeof(DatasetDto), StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public async Task<ActionResult<DatasetDto>> PreprocessAsync(
            Guid                        id,
            [FromBody] PreprocessDatasetRequest request,
            CancellationToken                   cancellationToken = default)
        {
            if (!ModelState.IsValid)
                return ValidationProblem();

            var scheduled = await _datasetService.SchedulePreprocessingAsync(id, request, cancellationToken);
            return AcceptedAtAction(nameof(GetAsync), new { id }, scheduled);
        }

        /// <summary>Updates dataset metadata. Concurrency controlled via If-Match header.</summary>
        [HttpPut("{id:guid}")]
        [ProducesResponseType(typeof(DatasetDto), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        [ProducesResponseType(StatusCodes.Status412PreconditionFailed)]
        public async Task<ActionResult<DatasetDto>> UpdateAsync(
            Guid                       id,
            [FromBody] UpdateDatasetRequest  request,
            CancellationToken          cancellationToken = default)
        {
            if (!ModelState.IsValid)
                return ValidationProblem();

            var ifMatch = Request.Headers["If-Match"].FirstOrDefault();
            if (string.IsNullOrWhiteSpace(ifMatch))
                return BadRequest("Missing If-Match header.");

            try
            {
                var updated = await _datasetService.UpdateAsync(id, request, ifMatch.Trim('"'), cancellationToken);
                return Ok(updated);
            }
            catch (DomainNotFoundException)
            {
                return NotFound();
            }
            catch (ConcurrencyConflictException)
            {
                return StatusCode(StatusCodes.Status412PreconditionFailed);
            }
        }

        /// <summary>Deletes a dataset and all of its derived artifacts.</summary>
        [HttpDelete("{id:guid}")]
        [ProducesResponseType(StatusCodes.Status204NoContent)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> DeleteAsync(Guid id, CancellationToken cancellationToken = default)
        {
            try
            {
                await _datasetService.DeleteAsync(id, cancellationToken);
                return NoContent();
            }
            catch (DomainNotFoundException)
            {
                return NotFound();
            }
        }

        #endregion
    }

    #region Lightweight DTOs & Query Shapes

    // NOTE: In production code these live in CanvasCraft.Api.Contracts.* packages.
    // They are inlined here only to make the file compile in isolation.

    public sealed record DatasetDto(
        Guid Id,
        string Name,
        string Description,
        long Items,
        string RowVersion,
        DateTimeOffset CreatedAtUtc,
        DateTimeOffset? LastPreprocessedUtc);

    public sealed record CreateDatasetRequest(string Name, string? Description);
    public sealed record UpdateDatasetRequest(string Name, string? Description);
    public sealed record PreprocessDatasetRequest(string PipelineStrategy);

    public sealed record DatasetQueryParameters(int Page = 1, int PageSize = 25, string? Search = null);

    #endregion
}
```