```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright file="VisualizationService.cs">
//   CanvasCraft ML Studio – Turning Machine-Learning into Digital Art
//   © 2024–present Cold-Start Creations LLC. All rights reserved.
// </copyright>
// --------------------------------------------------------------------------------------------------------------------

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Reactive.Linq;
using System.Reactive.Subjects;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Core.Domain.Experiments;
using CanvasCraft.Core.Domain.Metrics;
using CanvasCraft.Core.Domain.Models;
using CanvasCraft.Core.Exceptions;
using CanvasCraft.Core.Extensions;
using CanvasCraft.Core.Logging;
using CanvasCraft.WebApp.DTO;
using CanvasCraft.WebApp.Infrastructure.Caching;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.WebApp.Services
{
    /// <summary>
    /// Transforms raw experiment / model artefacts into lightweight DTOs that the
    /// front-end rendering engine (e.g., D3.js, three.js) can consume. Combines data
    /// aggregation, smoothing and real-time streaming to power the gallery dashboards.
    /// </summary>
    public sealed class VisualizationService : IVisualizationService, IDisposable
    {
        private readonly IExperimentRepository _experimentRepository;
        private readonly IMetricRepository _metricRepository;
        private readonly IModelRegistry _modelRegistry;
        private readonly ILogger<VisualizationService> _logger;
        private readonly IMemoryCache _cache;

        // Local hot observable streams keyed by experimentId|metricName
        private readonly ConcurrentDictionary<string, ISubject<LiveMetricUpdateDto>> _streamMap =
            new ConcurrentDictionary<string, ISubject<LiveMetricUpdateDto>>();

        private bool _disposed;

        public VisualizationService(
            IExperimentRepository experimentRepository,
            IMetricRepository metricRepository,
            IModelRegistry modelRegistry,
            IMemoryCache cache,
            ILogger<VisualizationService> logger)
        {
            _experimentRepository = experimentRepository ?? throw new ArgumentNullException(nameof(experimentRepository));
            _metricRepository    = metricRepository    ?? throw new ArgumentNullException(nameof(metricRepository));
            _modelRegistry       = modelRegistry       ?? throw new ArgumentNullException(nameof(modelRegistry));
            _cache               = cache              ?? throw new ArgumentNullException(nameof(cache));
            _logger              = logger             ?? throw new ArgumentNullException(nameof(logger));
        }

        #region Public API --------------------------------------------------------------------

        /// <inheritdoc />
        public async Task<ExperimentVisualizationDto> GetExperimentVisualizationAsync(
            Guid experimentId,
            VisualizationOptions options,
            CancellationToken cancellationToken = default)
        {
            if (experimentId == Guid.Empty)
                throw new ArgumentException("Experiment id must be non-empty.", nameof(experimentId));

            var cacheKey = CacheKeys.ExperimentVisualization(experimentId, options);
            if (_cache.TryGetValue(cacheKey, out ExperimentVisualizationDto cached))
            {
                _logger.LogDebug("Cache hit for experiment visualization {ExperimentId}.", experimentId);
                return cached;
            }

            var experiment = await _experimentRepository
                .GetAsync(experimentId, cancellationToken)
                .ConfigureAwait(false);

            if (experiment == null)
                throw new EntityNotFoundException($"Experiment {experimentId} not found.");

            // Gather associated metrics in parallel
            var metricNames = options?.MetricNames?.ToArray()
                              ?? Array.Empty<string>();

            var metricTasks = metricNames.Select(
                name => BuildMetricSeriesAsync(experimentId, name, options, cancellationToken));

            var metrics = await Task.WhenAll(metricTasks).ConfigureAwait(false);

            var dto = new ExperimentVisualizationDto
            {
                ExperimentId   = experiment.Id,
                DisplayName    = experiment.DisplayName,
                CreatedAtUtc   = experiment.CreatedAtUtc,
                Owner          = experiment.Owner,
                MetricSeries   = metrics.Where(m => m != null).ToList()
            };

            // Cache for 30s – fast enough for near-real-time while avoiding cold queries
            _cache.Set(cacheKey, dto, CacheDurations.Short);

            return dto;
        }

        /// <inheritdoc />
        public async Task<HeatmapDto> GetConfusionMatrixHeatmapAsync(
            Guid modelVersionId,
            CancellationToken cancellationToken = default)
        {
            if (modelVersionId == Guid.Empty)
                throw new ArgumentException("ModelVersionId must be non-empty.", nameof(modelVersionId));

            var cacheKey = CacheKeys.ConfusionMatrix(modelVersionId);

            if (_cache.TryGetValue(cacheKey, out HeatmapDto dto))
            {
                return dto;
            }

            var version = await _modelRegistry
                .GetVersionAsync(modelVersionId, cancellationToken)
                .ConfigureAwait(false);

            if (version == null)
                throw new EntityNotFoundException($"Model version {modelVersionId} not found.");

            var matrix = await _metricRepository
                .GetConfusionMatrixAsync(modelVersionId, cancellationToken)
                .ConfigureAwait(false);

            if (matrix == null)
                throw new DomainInvariantViolationException(
                    $"Model version {modelVersionId} lacks a confusion matrix metric.");

            dto = ToHeatmapDto(matrix);

            // Confusion matrix seldom changes; cache for 12 hours
            _cache.Set(cacheKey, dto, CacheDurations.Long);

            return dto;
        }

        /// <inheritdoc />
        public IObservable<LiveMetricUpdateDto> SubscribeToLiveMetrics(
            Guid experimentId,
            string metricName,
            CancellationToken cancellationToken = default)
        {
            if (experimentId == Guid.Empty)
                throw new ArgumentException("Experiment id must be non-empty.", nameof(experimentId));
            if (string.IsNullOrWhiteSpace(metricName))
                throw new ArgumentException("Metric name must be supplied.", nameof(metricName));

            var key = BuildStreamKey(experimentId, metricName);

            // Return existing stream or create a new one lazily
            var stream = _streamMap.GetOrAdd(key, _ =>
            {
                var subject = new ReplaySubject<LiveMetricUpdateDto>(bufferSize: 128);

                // Fire-and-forget background task that polls new metric points
                _ = Task.Run(async () =>
                {
                    _logger.LogInformation(
                        "Live metric stream created for experiment {ExperimentId}, metric {MetricName}.",
                        experimentId, metricName);

                    var cursor = DateTimeOffset.MinValue;

                    while (!cancellationToken.IsCancellationRequested && !_disposed)
                    {
                        try
                        {
                            var newPoints = await _metricRepository
                                .GetNewPointsAsync(experimentId, metricName, cursor, cancellationToken)
                                .ConfigureAwait(false);

                            foreach (var p in newPoints)
                            {
                                var liveUpdate = new LiveMetricUpdateDto(
                                    experimentId,
                                    metricName,
                                    p.TimestampUtc,
                                    p.Value);

                                subject.OnNext(liveUpdate);
                                cursor = p.TimestampUtc;
                            }

                            await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken)
                                .ConfigureAwait(false);
                        }
                        catch (OperationCanceledException)
                        {
                            // expected during shutdown; break gracefully
                            break;
                        }
                        catch (Exception ex)
                        {
                            _logger.LogError(ex,
                                "Error while polling live metrics for experiment {ExperimentId} / {MetricName}.",
                                experimentId, metricName);
                            // brief back-off on transient failure
                            await Task.Delay(TimeSpan.FromSeconds(5), cancellationToken)
                                .ConfigureAwait(false);
                        }
                    }

                    subject.OnCompleted();
                    _streamMap.TryRemove(key, out _);

                    _logger.LogInformation(
                        "Live metric stream disposed for experiment {ExperimentId}, metric {MetricName}.",
                        experimentId, metricName);
                }, cancellationToken);

                return subject;
            });

            return stream.AsObservable();
        }

        #endregion

        #region Internal Implementation --------------------------------------------------------

        private async Task<MetricTimeSeriesDto?> BuildMetricSeriesAsync(
            Guid experimentId,
            string metricName,
            VisualizationOptions options,
            CancellationToken cancellationToken)
        {
            var rawPoints = await _metricRepository
                .GetSeriesAsync(experimentId, metricName, cancellationToken)
                .ConfigureAwait(false);

            if (rawPoints == null || !rawPoints.Any())
            {
                _logger.LogWarning("No data points for experiment {ExperimentId}, metric {MetricName}.",
                    experimentId, metricName);
                return null;
            }

            var series = ToDataPoints(rawPoints);

            if (options.SmoothingWindow > 1)
            {
                series = SmoothSeries(series, options.SmoothingWindow);
            }

            return new MetricTimeSeriesDto
            {
                Name   = metricName,
                Points = series.ToList()
            };
        }

        private static IEnumerable<DataPointDto> SmoothSeries(
            IEnumerable<DataPointDto> source,
            int window)
        {
            var queue  = new Queue<double>(window);
            var buffer = new List<DataPointDto>();

            foreach (var p in source.OrderBy(s => s.TimestampUtc))
            {
                queue.Enqueue(p.Value);

                if (queue.Count > window)
                    queue.Dequeue();

                var avg = queue.Average();
                buffer.Add(new DataPointDto(p.TimestampUtc, avg));
            }

            return buffer;
        }

        private static HeatmapDto ToHeatmapDto(ConfusionMatrix matrix)
        {
            var labels = matrix.Labels.ToArray();
            var values = new double[labels.Length, labels.Length];

            for (var i = 0; i < labels.Length; i++)
            {
                for (var j = 0; j < labels.Length; j++)
                {
                    values[i, j] = matrix[labels[i], labels[j]];
                }
            }

            return new HeatmapDto
            {
                AxisLabels  = labels,
                Matrix      = values,
                Title       = "Confusion Matrix",
                Palette     = "artist-lab-blue-scale"
            };
        }

        private static IEnumerable<DataPointDto> ToDataPoints(IEnumerable<MetricPoint> points) =>
            points.Select(p => new DataPointDto(p.TimestampUtc, p.Value));

        #endregion

        #region Helpers & Disposal -------------------------------------------------------------

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private static string BuildStreamKey(Guid experimentId, string metricName) =>
            $"{experimentId:N}|{metricName}";

        public void Dispose()
        {
            if (_disposed) return;

            _disposed = true;

            foreach (var kvp in _streamMap)
            {
                kvp.Value.OnCompleted();
                kvp.Value.Dispose();
            }

            _streamMap.Clear();

            _logger.LogDebug("VisualizationService disposed.");
        }

        #endregion
    }
}
```

