using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Mime;
using System.Threading;
using System.Threading.Tasks;
using AutoMapper;
using CanvasCraft.Domain.ModelRegistry;
using CanvasCraft.Domain.ModelRegistry.DTOs;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Api.Controllers
{
    /// <summary>
    /// REST-ful controller that exposes the CanvasCraft Model Registry.
    /// All creative ML artifacts – checkpoints, feature bundles, evaluation reports – are treated as first-class citizens.
    /// </summary>
    [ApiController]
    [Route("api/[controller]")]
    [Produces("application/json")]
    public sealed class ModelRegistryController : ControllerBase
    {
        private readonly IModelRegistryService _registry;
        private readonly IMapper _mapper;
        private readonly ILogger<ModelRegistryController> _logger;

        public ModelRegistryController(
            IModelRegistryService registry,
            IMapper mapper,
            ILogger<ModelRegistryController> logger)
        {
            _registry = registry ?? throw new ArgumentNullException(nameof(registry));
            _mapper   = mapper    ?? throw new ArgumentNullException(nameof(mapper));
            _logger   = logger    ?? throw new ArgumentNullException(nameof(logger));
        }

        // ---------------------------------------------------------------------
        // Queries
        // ---------------------------------------------------------------------

        /// <summary>
        /// Retrieves a paged list of models in the registry.
        /// Supports tag, owner and search filters to keep the UX snappy for creative collaborators.
        /// </summary>
        [HttpGet("models")]
        [ProducesResponseType(typeof(PagedResult<ModelSummaryDto>), StatusCodes.Status200OK)]
        public async Task<IActionResult> ListModelsAsync(
            [FromQuery] string?   owner,
            [FromQuery] string?   tag,
            [FromQuery] string?   search,
            [FromQuery] int       page       = 1,
            [FromQuery] int       pageSize   = 20,
            CancellationToken     ct         = default)
        {
            var request = new ModelListRequest(owner, tag, search, page, pageSize);
            var result  = await _registry.ListModelsAsync(request, ct).ConfigureAwait(false);

            return Ok(result);
        }

        /// <summary>
        /// Retrieves all versions for a particular model.
        /// </summary>
        [HttpGet("models/{modelId:guid}/versions")]
        [ProducesResponseType(typeof(IReadOnlyCollection<ModelVersionDto>), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> ListVersionsAsync(
            Guid            modelId,
            CancellationToken ct = default)
        {
            if (!await _registry.ModelExistsAsync(modelId, ct))
            {
                return NotFound();
            }

            var versions = await _registry.ListVersionsAsync(modelId, ct).ConfigureAwait(false);
            return Ok(versions);
        }

        /// <summary>
        /// Shows the manifest (metadata) for a specific model version.
        /// </summary>
        [HttpGet("models/{modelId:guid}/versions/{version:int}/manifest")]
        [ProducesResponseType(typeof(ModelManifestDto), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> GetManifestAsync(
            Guid            modelId,
            int             version,
            CancellationToken ct = default)
        {
            var manifest = await _registry.GetManifestAsync(modelId, version, ct).ConfigureAwait(false);
            return manifest is null
                ? NotFound()
                : Ok(manifest);
        }

        /// <summary>
        /// Downloads the serialized model artifact (binary) for a specific version.
        /// Streaming is used to avoid buffering large files in memory.
        /// </summary>
        [HttpGet("models/{modelId:guid}/versions/{version:int}/artifact")]
        [ProducesResponseType(StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> DownloadArtifactAsync(
            Guid            modelId,
            int             version,
            CancellationToken ct = default)
        {
            var stream = await _registry.OpenArtifactStreamAsync(modelId, version, ct)
                                        .ConfigureAwait(false);

            if (stream is null)
            {
                return NotFound();
            }

            return File(stream, MediaTypeNames.Application.Octet, 
                        $"model-{modelId}-v{version}.ccraft");
        }

        // ---------------------------------------------------------------------
        // Commands
        // ---------------------------------------------------------------------

        /// <summary>
        /// Registers a new model or a new version of an existing model.
        /// Accepts multipart/form-data containing the artifact file and JSON metadata.
        /// </summary>
        [HttpPost("models")]
        [Consumes("multipart/form-data")]
        [ProducesResponseType(typeof(ModelVersionDto), StatusCodes.Status201Created)]
        [ProducesResponseType(StatusCodes.Status409Conflict)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public async Task<IActionResult> RegisterModelAsync(
            [FromForm] RegisterModelRequest request,
            CancellationToken ct = default)
        {
            if (!ModelState.IsValid)
            {
                return BadRequest(ModelState);
            }

            try
            {
                var command = _mapper.Map<RegisterModelCommand>(request);
                var result  = await _registry.RegisterModelAsync(command, ct)
                                             .ConfigureAwait(false);

                var routeValues = new { modelId = result.ModelId, version = result.Version };

                return CreatedAtAction(nameof(GetManifestAsync), routeValues, result);
            }
            catch (ModelAlreadyExistsException ex)
            {
                _logger.LogWarning(ex, "Attempted to register a duplicate model {Name}", request.ModelName);
                return Conflict(new { message = ex.Message });
            }
        }

        /// <summary>
        /// Promotes a specific model version to a lifecycle stage (e.g. Staging, Production).
        /// </summary>
        [HttpPost("models/{modelId:guid}/versions/{version:int}/stage")]
        [ProducesResponseType(StatusCodes.Status204NoContent)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public async Task<IActionResult> PromoteVersionAsync(
            Guid            modelId,
            int             version,
            [FromBody]      PromoteVersionRequest request,
            CancellationToken ct = default)
        {
            if (!Enum.IsDefined(typeof(ModelStage), request.Stage))
            {
                return BadRequest("Unknown stage.");
            }

            await _registry.PromoteVersionAsync(modelId, version, request.Stage, ct)
                           .ConfigureAwait(false);

            return NoContent();
        }

        /// <summary>
        /// Soft-deletes (archives) a model version – useful when an experiment branch is abandoned.
        /// </summary>
        [HttpDelete("models/{modelId:guid}/versions/{version:int}")]
        [ProducesResponseType(StatusCodes.Status204NoContent)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> ArchiveVersionAsync(
            Guid            modelId,
            int             version,
            CancellationToken ct = default)
        {
            var deleted = await _registry.ArchiveVersionAsync(modelId, version, ct)
                                         .ConfigureAwait(false);

            return deleted ? NoContent() : NotFound();
        }

        // ---------------------------------------------------------------------
        // DTOs (kept in-file for brevity; in production they live in their own folders)
        // ---------------------------------------------------------------------

        /// <summary>
        /// Multipart/form-data payload for registering a model.
        /// </summary>
        public sealed class RegisterModelRequest
        {
            /// <summary>
            /// Human-readable model name (unique across the workspace).
            /// </summary>
            [FromForm(Name = "modelName")] 
            public string ModelName { get; init; } = default!;

            /// <summary>
            /// A sentence or two describing the creative intent behind the model.
            /// </summary>
            [FromForm(Name = "description")]
            public string? Description { get; init; }

            /// <summary>
            /// Comma-separated tags (genre, style, inspiration).
            /// </summary>
            [FromForm(Name = "tags")]
            public string? TagsCsv { get; init; }

            /// <summary>
            /// Binary artifact (e.g. .pt, .ckpt, .onnx).
            /// </summary>
            [FromForm(Name = "artifact")]
            public IFormFile Artifact { get; init; } = default!;
        }

        /// <summary>
        /// Body for promoting a version to a stage.
        /// </summary>
        public sealed class PromoteVersionRequest
        {
            public ModelStage Stage { get; init; }
        }
    }
}