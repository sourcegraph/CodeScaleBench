```csharp
using System;
using System.Collections.Generic;
using System.Net.Mime;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Api.Contracts;
using CanvasCraft.Api.Contracts.Dtos;
using CanvasCraft.Api.Services;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Api.Controllers
{
    /// <summary>
    /// Provides endpoints that surface real-time health, metric, and alerting information for
    /// models managed by CanvasCraft ML Studio.
    /// </summary>
    [ApiController]
    [Route("api/[controller]")]
    public sealed class MonitoringController : ControllerBase
    {
        private readonly IMonitoringService _monitoringService;
        private readonly IMetricService _metricService;
        private readonly IAlertService _alertService;
        private readonly ILogger<MonitoringController> _logger;

        public MonitoringController(
            IMonitoringService monitoringService,
            IMetricService metricService,
            IAlertService alertService,
            ILogger<MonitoringController> logger)
        {
            _monitoringService = monitoringService ?? throw new ArgumentNullException(nameof(monitoringService));
            _metricService     = metricService     ?? throw new ArgumentNullException(nameof(metricService));
            _alertService      = alertService      ?? throw new ArgumentNullException(nameof(alertService));
            _logger            = logger           ?? throw new ArgumentNullException(nameof(logger));
        }

        #region Health
        
        /// <summary>
        /// Returns the overall health status of the CanvasCraft platform and its critical sub-systems.
        /// </summary>
        [HttpGet("health")]
        [Produces(MediaTypeNames.Application.Json)]
        [ProducesResponseType(StatusCodes.Status200OK)]
        public async Task<ActionResult<HealthStatusDto>> GetHealthAsync(CancellationToken ct)
        {
            var status = await _monitoringService.GetHealthStatusAsync(ct);
            return Ok(status);
        }

        #endregion

        #region Metrics
        
        /// <summary>
        /// Gets time-series metrics for a specific model run or deployed model.
        /// Query string supports interval &amp; range selections: ?from=2023-01-01T00:00:00Z&amp;to=2023-01-02T00:00:00Z&amp;granularity=1h
        /// </summary>
        [HttpGet("models/{modelId:guid}/metrics")]
        [Produces(MediaTypeNames.Application.Json)]
        [ProducesResponseType(StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<ActionResult<IEnumerable<ModelMetricDto>>> GetModelMetricsAsync(
            Guid modelId,
            [FromQuery] MetricQueryDto query,
            CancellationToken ct)
        {
            if (!await _monitoringService.ModelExistsAsync(modelId, ct))
            {
                _logger.LogWarning("Metrics requested for unknown model {ModelId}", modelId);
                return NotFound();
            }

            var metrics = await _metricService.QueryMetricsAsync(modelId, query, ct);
            return Ok(metrics);
        }
        
        #endregion

        #region Drift / Quality Checks
        
        /// <summary>
        /// Runs an ad-hoc drift detection job for the specified model and returns the result.
        /// </summary>
        [HttpPost("models/{modelId:guid}/drift-check")]
        [Produces(MediaTypeNames.Application.Json)]
        [ProducesResponseType(StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public async Task<ActionResult<DriftCheckResultDto>> RunDriftCheckAsync(
            Guid modelId,
            CancellationToken ct)
        {
            if (!await _monitoringService.ModelExistsAsync(modelId, ct))
            {
                _logger.LogWarning("Drift check requested for unknown model {ModelId}", modelId);
                return NotFound();
            }

            var result = await _monitoringService.RunDriftCheckAsync(modelId, ct);
            return Ok(result);
        }

        #endregion

        #region Alert Streaming
        
        /// <summary>
        /// Streams alert events as server-sent events (SSE). The client will receive each alert as a JSON blob.
        /// </summary>
        /// <remarks>
        /// Example JavaScript client:
        /// <code>
        /// const evtSrc = new EventSource("/api/monitoring/alerts/stream");
        /// evtSrc.onmessage = e =&gt; console.log(JSON.parse(e.data));
        /// </code>
        /// </remarks>
        [HttpGet("alerts/stream")]
        public async Task StreamAlertsAsync(CancellationToken ct)
        {
            Response.Headers.Add("Content-Type", "text/event-stream");
            
            await foreach (var alert in _alertService.StreamAlertsAsync(ct))
            {
                var json = JsonSerializer.Serialize(alert);
                await Response.WriteAsync($"data: {json}\n\n", ct);
                await Response.Body.FlushAsync(ct);
            }
        }

        #endregion
    }
}

/* -------------------------------------------------------------------------- */
/*                          Internal contracts / DTOs                         */
/*        In real production code these would live in their own files.        */
/* -------------------------------------------------------------------------- */

namespace CanvasCraft.Api.Contracts
{
    public interface IMonitoringService
    {
        Task<HealthStatusDto> GetHealthStatusAsync(CancellationToken ct);
        Task<bool>           ModelExistsAsync(Guid modelId, CancellationToken ct);
        Task<DriftCheckResultDto> RunDriftCheckAsync(Guid modelId, CancellationToken ct);
    }

    public interface IMetricService
    {
        Task<IEnumerable<ModelMetricDto>> QueryMetricsAsync(Guid modelId, MetricQueryDto query, CancellationToken ct);
    }

    public interface IAlertService
    {
        IAsyncEnumerable<AlertDto> StreamAlertsAsync(CancellationToken ct);
    }
}

namespace CanvasCraft.Api.Contracts.Dtos
{
    public record HealthStatusDto(ServiceHealthStatus Status, DateTimeOffset Timestamp, string? Message);

    public enum ServiceHealthStatus
    {
        Healthy,
        Degraded,
        Unhealthy
    }

    public record MetricQueryDto(DateTimeOffset? From, DateTimeOffset? To, string? Granularity);

    public record ModelMetricDto(string MetricName, double Value, DateTimeOffset Timestamp);

    public record DriftCheckResultDto(
        Guid ModelId,
        bool IsDrifting,
        double DriftScore,
        string DriftAlgorithm,
        DateTimeOffset CheckedAt);

    public record AlertDto(
        Guid Id,
        string Severity,
        string Category,
        string Message,
        DateTimeOffset CreatedAt);
}

/* -------------------------------------------------------------------------- */
/*                          Example Service Implementations                   */
/*      Stubbed out to make the controller compile; replace in prod.          */
/* -------------------------------------------------------------------------- */
namespace CanvasCraft.Api.Services
{
    using System.Linq;

    internal sealed class MonitoringService : IMonitoringService
    {
        public Task<HealthStatusDto> GetHealthStatusAsync(CancellationToken ct)
        {
            var dto = new HealthStatusDto(ServiceHealthStatus.Healthy, DateTimeOffset.UtcNow, "All systems operational");
            return Task.FromResult(dto);
        }

        public Task<bool> ModelExistsAsync(Guid modelId, CancellationToken ct)
        {
            // Simulated lookup
            return Task.FromResult(true);
        }

        public Task<DriftCheckResultDto> RunDriftCheckAsync(Guid modelId, CancellationToken ct)
        {
            var dto = new DriftCheckResultDto(
                modelId,
                IsDrifting: false,
                DriftScore: 0.02,
                DriftAlgorithm: "KS-Test",
                CheckedAt: DateTimeOffset.UtcNow);

            return Task.FromResult(dto);
        }
    }

    internal sealed class MetricService : IMetricService
    {
        public Task<IEnumerable<ModelMetricDto>> QueryMetricsAsync(Guid modelId, MetricQueryDto query, CancellationToken ct)
        {
            var now = DateTimeOffset.UtcNow;
            var metrics = Enumerable.Range(0, 10)
                                    .Select(i => new ModelMetricDto("accuracy", 0.8 + i * 0.001, now.AddMinutes(-i)));
            return Task.FromResult(metrics);
        }
    }

    internal sealed class AlertService : IAlertService
    {
        public async IAsyncEnumerable<AlertDto> StreamAlertsAsync([EnumeratorCancellation] CancellationToken ct)
        {
            // Simulated alert stream
            while (!ct.IsCancellationRequested)
            {
                await Task.Delay(TimeSpan.FromSeconds(5), ct);
                yield return new AlertDto(
                    Guid.NewGuid(),
                    Severity: "warning",
                    Category: "drift",
                    Message: "Model drift approaching threshold",
                    CreatedAt: DateTimeOffset.UtcNow);
            }
        }
    }
}
```