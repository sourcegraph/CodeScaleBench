```csharp
using System;
using System.Collections.Generic;
using System.Data;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using Hangfire;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Orchestrator.Application.Jobs
{
    /// <summary>
    /// Orchestrates a full ETL pipeline execution.
    /// Designed to be triggered by Hangfire, but can also be invoked directly (e.g., integration tests).
    /// </summary>
    /// <remarks>
    /// 1. Retrieves pipeline metadata & configuration.
    /// 2. Iteratively executes each configured transformation strategy.
    /// 3. Performs data-quality checks after every stage.
    /// 4. Writes the final data-frame to the Data Lake zone specified by the pipeline definition.
    /// 5. Publishes monitoring events and handles failure recovery.
    /// </remarks>
    public sealed class PipelineJob
    {
        private readonly IServiceProvider _serviceProvider;
        private readonly ILogger<PipelineJob> _logger;

        public PipelineJob(IServiceProvider serviceProvider, ILogger<PipelineJob> logger)
        {
            _serviceProvider = serviceProvider ?? throw new ArgumentNullException(nameof(serviceProvider));
            _logger         = logger            ?? throw new ArgumentNullException(nameof(logger));
        }

        // -----------------------------------------------------------------------------------------------------------------
        // Hangfire entry point (the only public surface of this class)
        // -----------------------------------------------------------------------------------------------------------------
        [AutomaticRetry(
            Attempts           = 3,
            DelaysInSeconds    = new[] { 30, 60, 300 },  // exponential-ish back-off
            LogEvents          = true,
            OnAttemptsExceeded = AttemptsExceededAction.Fail)]
        public async Task RunAsync(Guid pipelineId, CancellationToken cancellationToken = default)
        {
            var correlationId = Activity.Current?.Id ?? ActivityTraceId.CreateRandom().ToString();
            using (_logger.BeginScope(new Dictionary<string, object> { ["CorrelationId"] = correlationId }))
            {
                _logger.LogInformation("PipelineJob started for PipelineId={PipelineId}", pipelineId);

                await using var scope     = _serviceProvider.CreateAsyncScope();
                var repository            = scope.ServiceProvider.GetRequiredService<IPipelineRepository>();
                var strategyFactory       = scope.ServiceProvider.GetRequiredService<ITransformationStrategyFactory>();
                var qualityService        = scope.ServiceProvider.GetRequiredService<IDataQualityService>();
                var dataLakeWriter        = scope.ServiceProvider.GetRequiredService<IDataLakeWriter>();
                var monitoringClient      = scope.ServiceProvider.GetRequiredService<IMonitoringClient>();

                var definition = await repository.GetAsync(pipelineId, cancellationToken);
                if (definition is null)
                {
                    _logger.LogWarning("Pipeline definition not found (PipelineId={PipelineId}). Job aborted.", pipelineId);
                    return;
                }

                try
                {
                    await repository.UpdateStatusAsync(pipelineId, PipelineStatus.Running, cancellationToken);
                    await monitoringClient.PublishAsync(
                        MonitoringEvent.Started(definition, correlationId), cancellationToken);

                    var currentFrame = definition.InitialFrame ?? DataFrame.Empty;

                    foreach (var stage in definition.Stages)
                    {
                        cancellationToken.ThrowIfCancellationRequested();

                        _logger.LogInformation("Executing stage '{StageName}' using strategy '{StrategyKey}' …",
                                               stage.Name, stage.StrategyKey);

                        var strategy = strategyFactory.Create(stage.StrategyKey)
                                      ?? throw new InvalidOperationException(
                                          $"Transformation strategy '{stage.StrategyKey}' could not be resolved.");

                        currentFrame = await strategy.TransformAsync(currentFrame, cancellationToken);

                        // ────────────────────────────────────────────────────────────────────────────────
                        // Data-quality checks
                        // ────────────────────────────────────────────────────────────────────────────────
                        var report = await qualityService.CheckAsync(currentFrame, cancellationToken);
                        if (!report.Passed)
                        {
                            throw new DataQualityException(
                                $"Data-quality checks failed at stage '{stage.Name}'. " +
                                $"Blocking issue(s): {string.Join("; ", report.BlockingIssues)}");
                        }

                        await monitoringClient.PublishAsync(
                            MonitoringEvent.StageCompleted(definition, stage, report, correlationId), cancellationToken);
                    }

                    // ────────────────────────────────────────────────────────────────────────────────
                    // Persist the final frame
                    // ────────────────────────────────────────────────────────────────────────────────
                    await dataLakeWriter.WriteAsync(
                        currentFrame,
                        definition.TargetDataLakePath,
                        cancellationToken);

                    await repository.UpdateStatusAsync(pipelineId, PipelineStatus.Completed, cancellationToken);
                    await monitoringClient.PublishAsync(
                        MonitoringEvent.Completed(definition, correlationId), cancellationToken);

                    _logger.LogInformation("PipelineId={PipelineId} completed successfully.", pipelineId);
                }
                catch (Exception ex) when (!ex.IsFatal())
                {
                    _logger.LogError(ex, "PipelineId={PipelineId} failed. Attempting recovery …", pipelineId);

                    try
                    {
                        await repository.UpdateStatusAsync(pipelineId, PipelineStatus.Failed, cancellationToken);
                        await monitoringClient.PublishAsync(
                            MonitoringEvent.Failed(definition, ex, correlationId), cancellationToken);
                    }
                    catch (Exception updateEx)
                    {
                        _logger.LogError(updateEx,
                            "Failed to update status/monitoring for PipelineId={PipelineId}.", pipelineId);
                    }

                    // swallows Hangfire retry logic; re-throw to mark job as failed for this attempt
                    throw;
                }
            }
        }
    }

    #region ────────────────────────────────────── Helper Interfaces & Models ──────────────────────────────────────

    // NOTE: In a full solution these abstractions live in dedicated files/projects.
    // They are included here to keep the example self-contained & compilable.

    public enum PipelineStatus { Pending, Running, Completed, Failed }

    public record PipelineDefinition(
        Guid PipelineId,
        string Name,
        DataFrame? InitialFrame,
        IReadOnlyList<PipelineStage> Stages,
        string TargetDataLakePath);

    public record PipelineStage(
        string Name,
        string StrategyKey);

    public interface IPipelineRepository
    {
        Task<PipelineDefinition?> GetAsync(Guid pipelineId, CancellationToken token);
        Task UpdateStatusAsync(Guid pipelineId, PipelineStatus status, CancellationToken token);
    }

    public interface ITransformationStrategy
    {
        string Name { get; }

        /// <summary>Transforms <paramref name="source"/> into a new <see cref="DataFrame"/> instance.</summary>
        Task<DataFrame> TransformAsync(DataFrame source, CancellationToken token);
    }

    public interface ITransformationStrategyFactory
    {
        ITransformationStrategy? Create(string strategyKey);
    }

    public interface IDataQualityService
    {
        Task<DataQualityReport> CheckAsync(DataFrame frame, CancellationToken token);
    }

    public interface IDataLakeWriter
    {
        Task WriteAsync(DataFrame frame, string targetPath, CancellationToken token);
    }

    public interface IMonitoringClient
    {
        Task PublishAsync(MonitoringEvent evt, CancellationToken token);
    }

    public record DataQualityReport(bool Passed, IReadOnlyList<string> BlockingIssues);

    public sealed class DataQualityException : Exception
    {
        public DataQualityException(string message) : base(message) { }
    }

    /// <summary>
    /// Very small, lightweight data-frame abstraction (placeholder for Apache Arrow, DataTable, etc.).
    /// </summary>
    public sealed class DataFrame
    {
        private DataFrame() { }

        public static DataFrame Empty { get; } = new();

        // In real life: columns, schema, record batches, etc.
    }

    /// <summary>
    /// Monitoring events pushed to observability/alerting backends.
    /// </summary>
    public record MonitoringEvent
    {
        private MonitoringEvent(string type, string correlationId, object payload)
            => (Type, CorrelationId, Payload) = (type, correlationId, payload);

        public string  Type          { get; }
        public string  CorrelationId { get; }
        public object  Payload       { get; }

        public static MonitoringEvent Started(PipelineDefinition def, string correlationId)
            => new("pipeline.started", correlationId, new { def.PipelineId, def.Name });

        public static MonitoringEvent StageCompleted(PipelineDefinition def, PipelineStage stage,
                                                     DataQualityReport report, string correlationId)
            => new("pipeline.stage_completed", correlationId,
                  new { def.PipelineId, Stage = stage.Name, report.Passed });

        public static MonitoringEvent Completed(PipelineDefinition def, string correlationId)
            => new("pipeline.completed", correlationId, new { def.PipelineId });

        public static MonitoringEvent Failed(PipelineDefinition def, Exception ex, string correlationId)
            => new("pipeline.failed", correlationId, new { def.PipelineId, ex.Message });
    }

    internal static class ExceptionExtensions
    {
        /// <summary>
        /// Determines whether the exception is considered fatal (i.e., should not be swallowed or retried).
        /// </summary>
        public static bool IsFatal(this Exception ex) =>
            ex is OutOfMemoryException or StackOverflowException or ThreadAbortException;
    }

    #endregion
}
```