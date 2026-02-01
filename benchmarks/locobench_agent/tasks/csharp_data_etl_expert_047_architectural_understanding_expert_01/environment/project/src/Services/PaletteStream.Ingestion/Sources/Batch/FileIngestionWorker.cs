using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Polly;
using Polly.Retry;

namespace PaletteStream.Ingestion.Sources.Batch
{
    /// <summary>
    /// Background worker that scans a configured folder and ingests new files into
    /// the Data Lake in micro-batches.  
    /// 
    /// – Resilient: uses Polly for retries on transient I/O failures.  
    /// – Idempotent: moves processed files to a separate folder & persists checkpoints.  
    /// – Observable: records Prometheus-style metrics and structured logs.  
    /// </summary>
    public sealed class FileIngestionWorker : BackgroundService
    {
        private readonly ILogger<FileIngestionWorker> _logger;
        private readonly IDataLakeWriter _dataLakeWriter;
        private readonly IMetricsRecorder _metrics;
        private readonly ICheckpointStore _checkpointStore;
        private readonly BatchFileIngestionOptions _options;
        private readonly AsyncRetryPolicy _retryPolicy;

        private readonly string _sourceFolder;
        private readonly string _processedFolder;
        private readonly HashSet<string> _allowedExtensions;

        public FileIngestionWorker(
            ILogger<FileIngestionWorker> logger,
            IDataLakeWriter dataLakeWriter,
            IMetricsRecorder metrics,
            ICheckpointStore checkpointStore,
            IOptions<BatchFileIngestionOptions> optionsAccessor)
        {
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _dataLakeWriter = dataLakeWriter ?? throw new ArgumentNullException(nameof(dataLakeWriter));
            _metrics = metrics ?? throw new ArgumentNullException(nameof(metrics));
            _checkpointStore = checkpointStore ?? throw new ArgumentNullException(nameof(checkpointStore));

            _options = optionsAccessor?.Value ?? throw new ArgumentNullException(nameof(optionsAccessor));

            _sourceFolder     = Path.GetFullPath(_options.SourceFolder     ?? throw new ArgumentNullException(nameof(_options.SourceFolder)));
            _processedFolder  = Path.GetFullPath(_options.ProcessedFolder  ?? Path.Combine(_sourceFolder, "_processed"));

            Directory.CreateDirectory(_sourceFolder);
            Directory.CreateDirectory(_processedFolder);

            _allowedExtensions = _options.AllowedExtensions?.Count > 0
                ? new HashSet<string>(_options.AllowedExtensions.Select(e => e.StartsWith('.') ? e : "." + e),
                                      StringComparer.OrdinalIgnoreCase)
                : new HashSet<string>(StringComparer.OrdinalIgnoreCase) { ".csv", ".json", ".parquet" };

            _retryPolicy = Policy
                .Handle<IOException>()
                .OrAnyResult<bool>(r => r == false)
                .WaitAndRetryAsync(
                    _options.RetryCount,
                    attempt => TimeSpan.FromSeconds(Math.Pow(2, attempt)),
                    (outcome, delay, attempt, ctx) =>
                    {
                        _metrics.Counter("ingestion_retry_total").Inc();
                        _logger.LogWarning(outcome.Exception,
                            "Retry {Attempt} after {Delay} for failed file ingestion.",
                            attempt, delay);
                    });
        }

        protected override async Task ExecuteAsync(CancellationToken stoppingToken)
        {
            _logger.LogInformation("FileIngestionWorker started. Watching folder {Folder}", _sourceFolder);

            // Load last checkpoint to avoid re-processing.
            var lastProcessed = await _checkpointStore
                .GetCheckpointAsync(Hash(_sourceFolder), stoppingToken)
                .ConfigureAwait(false);

            while (!stoppingToken.IsCancellationRequested)
            {
                try
                {
                    var candidates = Directory
                        .EnumerateFiles(_sourceFolder, "*.*", SearchOption.TopDirectoryOnly)
                        .Where(f => _allowedExtensions.Contains(Path.GetExtension(f)))
                        .OrderBy(File.GetCreationTimeUtc)
                        .ToList();

                    // Skip already processed files based on checkpoint.
                    candidates = candidates
                        .Where(f => string.CompareOrdinal(Path.GetFileName(f), lastProcessed) > 0)
                        .ToList();

                    if (!candidates.Any())
                    {
                        await Task.Delay(_options.PollingInterval, stoppingToken);
                        continue;
                    }

                    var batch = candidates.Take(_options.BatchSize).ToList();
                    var ingested = await IngestBatchAsync(batch, stoppingToken);
                    _metrics.Counter("files_ingested_total").Inc(ingested);

                    lastProcessed = Path.GetFileName(batch.Last());
                    await _checkpointStore.SaveCheckpointAsync(Hash(_sourceFolder), lastProcessed, stoppingToken);
                }
                catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
                {
                    // graceful shutdown
                }
                catch (Exception ex)
                {
                    _metrics.Counter("ingestion_failure_total").Inc();
                    _logger.LogError(ex, "Unhandled exception in ingestion loop. Sleeping {Backoff}...", _options.FailureBackoff);
                    await Task.Delay(_options.FailureBackoff, stoppingToken);
                }
            }

            _logger.LogInformation("FileIngestionWorker stopping.");
        }

        public override Task StopAsync(CancellationToken cancellationToken)
        {
            _logger.LogInformation("Stop signal received for FileIngestionWorker.");
            return base.StopAsync(cancellationToken);
        }

        #region Internal helpers

        private async Task<int> IngestBatchAsync(IEnumerable<string> batch, CancellationToken ct)
        {
            var total = 0;
            foreach (var file in batch)
            {
                var succeeded = await _retryPolicy.ExecuteAsync(c => IngestFileAsync(file, c), ct);
                if (succeeded) total++;
            }
            return total;
        }

        private async Task<bool> IngestFileAsync(string filePath, CancellationToken ct)
        {
            var fileName = Path.GetFileName(filePath);
            using var scope = _logger.BeginScope("file:{File}", fileName);

            _logger.LogDebug("Starting ingestion for {File}", fileName);

            await using var stream = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.Read);

            if (!await _dataLakeWriter.WriteAsync(fileName, stream, ct))
            {
                _logger.LogWarning("Writer rejected file {File}", fileName);
                return false;
            }

            _logger.LogDebug("Uploaded {File} to Data Lake, moving to processed folder.", fileName);

            var processedPath = Path.Combine(_processedFolder, fileName);
            File.Move(filePath, processedPath, overwrite: true);

            _logger.LogInformation("Ingestion complete for {File}", fileName);
            return true;
        }

        private static string Hash(string value)
        {
            using var sha = System.Security.Cryptography.SHA1.Create();
            return Convert.ToHexString(sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(value)));
        }

        #endregion
    }

    #region Supporting abstractions / options

    /// <summary>Configuration options for <see cref="FileIngestionWorker"/>.</summary>
    public sealed class BatchFileIngestionOptions
    {
        public string? SourceFolder  { get; set; }
        public string? ProcessedFolder { get; set; }
        public IList<string>? AllowedExtensions { get; set; }

        public int      BatchSize        { get; set; } = 50;
        public TimeSpan PollingInterval  { get; set; } = TimeSpan.FromSeconds(10);
        public TimeSpan FailureBackoff   { get; set; } = TimeSpan.FromSeconds(30);
        public int      RetryCount       { get; set; } = 3;
    }

    /// <summary>Writes a data stream into the Data Lake storage zone.</summary>
    public interface IDataLakeWriter
    {
        Task<bool> WriteAsync(string objectName, Stream content, CancellationToken cancellationToken);
    }

    /// <summary>Prometheus/StatsD-style metrics recorder abstraction.</summary>
    public interface IMetricsRecorder
    {
        ICounter Counter(string name);
    }

    public interface ICounter
    {
        void Inc(double increment = 1);
    }

    /// <summary>Persists ingestion checkpoints across restarts.</summary>
    public interface ICheckpointStore
    {
        Task<string?> GetCheckpointAsync(string key, CancellationToken cancellationToken);
        Task SaveCheckpointAsync(string key, string value, CancellationToken cancellationToken);
    }

    #endregion
}