```csharp
using System;
using System.Collections.Generic;
using System.Net.Mime;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Domain.Exceptions;
using CanvasCraft.Domain.Inferencing;
using CanvasCraft.Domain.ModelRegistry;
using CanvasCraft.Domain.Tracking;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Api.Controllers
{
    /// <summary>
    ///     ReST controller responsible for runtime model serving.  
    ///     Provides prediction, metadata lookup and live-reload endpoints.
    /// </summary>
    [ApiController]
    [Route("api/serve")]
    [Produces(MediaTypeNames.Application.Json)]
    public sealed class ServingController : ControllerBase
    {
        private readonly IInferenceService _inferenceService;
        private readonly ILogger<ServingController> _logger;
        private readonly IModelRegistryService _modelRegistry;
        private readonly IExperimentTrackingService _trackingService;

        public ServingController(
            IModelRegistryService modelRegistry,
            IInferenceService inferenceService,
            IExperimentTrackingService trackingService,
            ILogger<ServingController> logger)
        {
            _modelRegistry = modelRegistry ?? throw new ArgumentNullException(nameof(modelRegistry));
            _inferenceService = inferenceService ?? throw new ArgumentNullException(nameof(inferenceService));
            _trackingService = trackingService ?? throw new ArgumentNullException(nameof(trackingService));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        #region ---------- Prediction ---------------------------------------------------------------------------

        /// <summary>
        ///     Executes a prediction against the specified model version.
        /// </summary>
        /// <remarks>
        ///     The request body must be a JSON dictionary whose keys map exactly to the model’s feature names.
        /// </remarks>
        /// <param name="modelName">Registered model name or alias.</param>
        /// <param name="request">Input feature vector.</param>
        /// <param name="ct">Cancellation token.</param>
        /// <returns>Prediction result along with contextual metadata.</returns>
        [HttpPost("{modelName}/predict")]
        [Consumes(MediaTypeNames.Application.Json)]
        [ProducesResponseType(typeof(PredictionResponseDto), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        [ProducesResponseType(StatusCodes.Status500InternalServerError)]
        public async Task<IActionResult> PredictAsync(
            [FromRoute] string modelName,
            [FromBody] PredictionRequestDto request,
            CancellationToken ct)
        {
            if (string.IsNullOrWhiteSpace(modelName))
            {
                return BadRequest("Model name must be provided.");
            }

            if (request?.Features is null || request.Features.Count == 0)
            {
                return BadRequest("Request payload must contain at least one feature.");
            }

            try
            {
                // 1) Obtain model manifest (metadata & location).
                var manifest = await _modelRegistry.GetLatestModelAsync(modelName, ct);
                if (manifest is null)
                {
                    return NotFound($"Model '{modelName}' does not exist in registry.");
                }

                // 2) Run inference.
                var output = await _inferenceService.PredictAsync(
                    manifest,
                    request.Features,
                    ct);

                // 3) Persist prediction event for audit / feedback loop.
                var predictionId = Guid.NewGuid().ToString("N");
                await _trackingService.TrackPredictionAsync(
                    new PredictionEvent
                    {
                        Id = predictionId,
                        ModelId = manifest.Id,
                        ModelVersion = manifest.Version,
                        TimestampUtc = DateTime.UtcNow,
                        Input = request.Features,
                        Output = output
                    }, ct);

                // 4) Build response.
                var response = new PredictionResponseDto
                {
                    PredictionId = predictionId,
                    ModelName = manifest.Name,
                    ModelVersion = manifest.Version,
                    Timestamp = DateTime.UtcNow,
                    Output = output
                };

                return Ok(response);
            }
            catch (ModelRegistryException ex)
            {
                _logger.LogWarning(ex, "Model registry failure for model {ModelName}.", modelName);
                return NotFound(ex.Message);
            }
            catch (InferenceException ex)
            {
                _logger.LogError(ex, "Inference failure for model {ModelName}.", modelName);
                return StatusCode(StatusCodes.Status500InternalServerError, "Inference engine error.");
            }
            catch (Exception ex)
            {
                _logger.LogCritical(ex, "Unhandled error during prediction for model {ModelName}.", modelName);
                return StatusCode(StatusCodes.Status500InternalServerError, "Unhandled server error.");
            }
        }

        #endregion

        #region ---------- Metadata -----------------------------------------------------------------------------

        /// <summary>
        ///     Returns the metadata (manifest) for the latest version of a model.
        /// </summary>
        /// <param name="modelName">Registered model name.</param>
        /// <param name="ct">Cancellation token.</param>
        [HttpGet("{modelName}/metadata")]
        [ProducesResponseType(typeof(ModelManifest), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> GetMetadataAsync(
            [FromRoute] string modelName,
            CancellationToken ct)
        {
            try
            {
                var manifest = await _modelRegistry.GetLatestModelAsync(modelName, ct);
                if (manifest is null) return NotFound();

                return Ok(manifest);
            }
            catch (ModelRegistryException ex)
            {
                _logger.LogWarning(ex, "Model registry failure for model {ModelName}.", modelName);
                return NotFound(ex.Message);
            }
        }

        #endregion

        #region ---------- Hot Reload ---------------------------------------------------------------------------

        /// <summary>
        ///     Reloads the model into memory.  Useful when a new version has been promoted in the registry
        ///     and low-latency serving is required without recycling the process.
        /// </summary>
        /// <param name="modelName">Registered model name.</param>
        /// <param name="ct">Cancellation token.</param>
        [HttpPost("{modelName}/reload")]
        [ProducesResponseType(StatusCodes.Status202Accepted)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<IActionResult> ReloadModelAsync(
            [FromRoute] string modelName,
            CancellationToken ct)
        {
            try
            {
                var manifest = await _modelRegistry.GetLatestModelAsync(modelName, ct);
                if (manifest is null) return NotFound();

                await _inferenceService.ReloadModelAsync(manifest, ct);
                return Accepted($"Model '{modelName}' successfully reloaded.");
            }
            catch (ModelRegistryException ex)
            {
                _logger.LogWarning(ex, "Model registry failure for model {ModelName}.", modelName);
                return NotFound(ex.Message);
            }
            catch (InferenceException ex)
            {
                _logger.LogError(ex, "Failed to reload model {ModelName}.", modelName);
                return StatusCode(StatusCodes.Status500InternalServerError, "Reload failed.");
            }
        }

        #endregion

        #region ---------- Health Check -------------------------------------------------------------------------

        /// <summary>
        ///     Simple liveness probe used by container orchestrators.
        /// </summary>
        [HttpGet("health")]
        [ProducesResponseType(StatusCodes.Status200OK)]
        public IActionResult Health() => Ok("Alive");

        #endregion
    }

    #region ---------- DTOs ------------------------------------------------------------------------------------

    /// <summary>
    ///     Incoming prediction request.  Accepts arbitrary feature key/values.
    /// </summary>
    public sealed class PredictionRequestDto
    {
        [JsonPropertyName("features")]
        public IDictionary<string, JsonElement> Features { get; init; } =
            new Dictionary<string, JsonElement>(StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>
    ///     Outgoing prediction payload.
    /// </summary>
    public sealed class PredictionResponseDto
    {
        [JsonPropertyName("prediction_id")]
        public string PredictionId { get; init; } = default!;

        [JsonPropertyName("model_name")]
        public string ModelName { get; init; } = default!;

        [JsonPropertyName("model_version")]
        public string ModelVersion { get; init; } = default!;

        [JsonPropertyName("timestamp_utc")]
        public DateTime Timestamp { get; init; }

        [JsonPropertyName("output")]
        public object Output { get; init; } = default!;
    }

    #endregion
}
```