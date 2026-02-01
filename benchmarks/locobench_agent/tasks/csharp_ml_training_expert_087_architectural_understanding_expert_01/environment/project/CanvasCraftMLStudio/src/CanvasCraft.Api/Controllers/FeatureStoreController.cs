```csharp
using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Mime;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Core.FeatureStore;
using CanvasCraft.Core.FeatureStore.DTOs;
using CanvasCraft.Core.FeatureStore.Exceptions;
using CanvasCraft.Core.Infrastructure.Pagination;
using CanvasCraft.Infrastructure.Telemetry;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Api.Controllers
{
    /// <summary>
    ///     REST-style controller that exposes CRUD operations for Feature Store entities.
    ///     A feature represents a reusable, version-aware data artifact used by
    ///     downstream model-training and inference pipelines.
    /// </summary>
    [ApiController]
    [Route("api/feature-store")]
    [Produces(MediaTypeNames.Application.Json)]
    public sealed class FeatureStoreController : ControllerBase
    {
        private readonly IFeatureStoreService _featureStore;
        private readonly ILogger<FeatureStoreController> _logger;
        private readonly IRequestTelemetry _telemetry;

        public FeatureStoreController(
            IFeatureStoreService featureStore,
            ILogger<FeatureStoreController> logger,
            IRequestTelemetry telemetry)
        {
            _featureStore = featureStore ?? throw new ArgumentNullException(nameof(featureStore));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _telemetry = telemetry ?? throw new ArgumentNullException(nameof(telemetry));
        }

        #region GET

        /// <summary>
        ///     Returns a paginated list of feature metadata.
        /// </summary>
        /// <param name="skip">Number of records to skip.</param>
        /// <param name="take">Number of records to take.  Maximum is 250.</param>
        [HttpGet("features")]
        [Authorize(Policy = "read:feature-store")]
        [ProducesResponseType(typeof(Page<FeatureDto>), StatusCodes.Status200OK)]
        public async Task<IActionResult> ListAsync(
            [FromQuery] int skip = 0,
            [FromQuery] int take = Page.DefaultPageSize,
            CancellationToken ct = default)
        {
            take = Math.Min(take, Page.MaxPageSize);

            var page = await _featureStore.ListAsync(skip, take, ct);
            Response.Headers.Add("X-Total-Count", page.TotalCount.ToString());

            return Ok(page);
        }

        /// <summary>
        ///     Retrieves a single version of a feature.  
        ///     If no version is supplied, the latest version is returned.
        /// </summary>
        [HttpGet("features/{featureName}/versions/{version?}")]
        [Authorize(Policy = "read:feature-store")]
        [ProducesResponseType(typeof(FeatureDto), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> GetAsync(
            string featureName,
            int? version = null,
            CancellationToken ct = default)
        {
            try
            {
                var feature = await _featureStore.GetAsync(featureName, version, ct);
                return Ok(feature);
            }
            catch (FeatureNotFoundException e)
            {
                _logger.LogWarning(e, "Feature {FeatureName} v{Version} not found.", featureName, version);
                return NotFound(new { message = e.Message });
            }
        }

        #endregion

        #region POST

        /// <summary>
        ///     Creates a new feature version from a JSON payload.
        /// </summary>
        [HttpPost("features")]
        [Authorize(Policy = "write:feature-store")]
        [Consumes(MediaTypeNames.Application.Json)]
        [ProducesResponseType(typeof(FeatureDto), StatusCodes.Status201Created)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public async Task<IActionResult> CreateAsync(
            [FromBody] FeatureCreateRequest request,
            CancellationToken ct = default)
        {
            if (!ModelState.IsValid)
                return ValidationProblem(ModelState);

            var created = await _featureStore.CreateAsync(request, ct);
            _telemetry.TrackFeatureCreated(request.Name, created.Version);

            return CreatedAtAction(
                nameof(GetAsync),
                new { featureName = created.Name, version = created.Version },
                created);
        }

        /// <summary>
        ///     Bulk-imports features from a CSV file.  
        ///     The strategy and factory patterns decide how to parse and persist each row.
        /// </summary>
        [HttpPost("features/bulk")]
        [Authorize(Policy = "write:feature-store")]
        [RequestSizeLimit(524_288_000)] // 500 MB
        [Consumes("text/csv")]
        [ProducesResponseType(StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public async Task<IActionResult> BulkUploadAsync(
            IFormFile csvFile,
            CancellationToken ct = default)
        {
            if (csvFile is null || csvFile.Length == 0)
                return BadRequest("Empty CSV payload.");

            // Stream processing avoids loading the entire file into memory.
            await using var stream = csvFile.OpenReadStream();
            var importResult = await _featureStore.BulkImportAsync(stream, ct);

            return Accepted(new
            {
                importResult.TotalRows,
                importResult.SuccessfulRows,
                importResult.FailedRows
            });
        }

        #endregion

        #region PUT

        /// <summary>
        ///     Updates a feature’s metadata and registers a new version if content changes.  
        ///     Uses optimistic concurrency via ETag header.
        /// </summary>
        [HttpPut("features/{featureName}")]
        [Authorize(Policy = "write:feature-store")]
        [Consumes(MediaTypeNames.Application.Json)]
        [ProducesResponseType(typeof(FeatureDto), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        [ProducesResponseType(StatusCodes.Status412PreconditionFailed)]
        public async Task<IActionResult> UpdateAsync(
            string featureName,
            [FromBody] FeatureUpdateRequest request,
            CancellationToken ct = default)
        {
            if (!ModelState.IsValid)
                return ValidationProblem(ModelState);

            if (!Request.Headers.TryGetValue("If-Match", out var etag))
                return BadRequest("Missing If-Match header for optimistic concurrency.");

            try
            {
                var updated = await _featureStore.UpdateAsync(featureName, request, etag!, ct);
                return Ok(updated);
            }
            catch (FeatureConflictException e)
            {
                return StatusCode(StatusCodes.Status412PreconditionFailed, new { message = e.Message });
            }
            catch (FeatureNotFoundException e)
            {
                return NotFound(new { message = e.Message });
            }
        }

        #endregion

        #region DELETE

        /// <summary>
        ///     Soft-deletes a feature.  
        ///     A deleted feature is hidden from discovery but preserved for lineage audits.
        /// </summary>
        [HttpDelete("features/{featureName}")]
        [Authorize(Policy = "delete:feature-store")]
        [ProducesResponseType(StatusCodes.Status204NoContent)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> DeleteAsync(
            string featureName,
            CancellationToken ct = default)
        {
            try
            {
                await _featureStore.SoftDeleteAsync(featureName, ct);
                _telemetry.TrackFeatureDeleted(featureName);
                return NoContent();
            }
            catch (FeatureNotFoundException)
            {
                return NotFound();
            }
        }

        #endregion
    }
}
```