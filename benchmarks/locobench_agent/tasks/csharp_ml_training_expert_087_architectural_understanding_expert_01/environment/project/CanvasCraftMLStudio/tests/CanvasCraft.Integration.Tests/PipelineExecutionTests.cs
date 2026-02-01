```csharp
// File: CanvasCraftMLStudio/tests/CanvasCraft.Integration.Tests/PipelineExecutionTests.cs

using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Xunit;

namespace CanvasCraft.Integration.Tests
{
    /// <summary>
    /// End-to-end integration tests for the configurable MLOps pipeline executor.
    /// </summary>
    public sealed class PipelineExecutionTests
    {
        private readonly ServiceProvider _serviceProvider;

        public PipelineExecutionTests()
        {
            // Because this is an integration test we bootstrap the same DI tree
            // that production uses—only replacing/wrapping the infrastructure
            // (feature store, experiment tracker, etc.) with in-memory test doubles.
            var services = new ServiceCollection();

            // Logging
            services.AddLogging(b => b.AddDebug().SetMinimumLevel(LogLevel.Debug));

            // Core pipeline infrastructure
            services.AddSingleton<IExperimentTracker, InMemoryExperimentTracker>();
            services.AddSingleton<IPipelineStageFactory, PipelineStageFactory>();
            services.AddSingleton<IPipelineExecutor, PipelineExecutor>();

            _serviceProvider = services.BuildServiceProvider(validateScopes: true);
        }

        [Fact(DisplayName = "ExecutePipeline_EndToEnd_SucceedsAndPersistsArtifacts")]
        public async Task ExecutePipeline_EndToEnd_SucceedsAndPersistsArtifacts()
        {
            // Arrange
            var executor  = _serviceProvider.GetRequiredService<IPipelineExecutor>();
            var tracker   = _serviceProvider.GetRequiredService<IExperimentTracker>();
            var pipeline  = BuildDefaultDefinition();

            // Act
            var result = await executor.ExecuteAsync(pipeline, CancellationToken.None);

            // Assert
            result.Success.Should().BeTrue();
            result.Artifacts.Should().ContainKey("model.checkpoint");
            tracker.Runs.Should().ContainSingle()
                   .Which.Status.Should().Be(RunStatus.Succeeded);
        }

        [Fact(DisplayName = "ExecutePipeline_CancelMidExecution_ThrowsOperationCanceledException")]
        public async Task ExecutePipeline_CancelMidExecution_ThrowsOperationCanceledException()
        {
            // Arrange
            var executor = _serviceProvider.GetRequiredService<IPipelineExecutor>();
            using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(150)); // cancel shortly

            // Act
            Func<Task> act = async () =>
            {
                await executor.ExecuteAsync(BuildDefaultDefinition(), cts.Token);
            };

            // Assert
            await act.Should().ThrowAsync<OperationCanceledException>();
        }

        [Fact(DisplayName = "ExecutePipeline_FailureInPreprocessing_LogsAndRegistersFailedRun")]
        public async Task ExecutePipeline_FailureInPreprocessing_LogsAndRegistersFailedRun()
        {
            // Arrange
            var executor = _serviceProvider.GetRequiredService<IPipelineExecutor>();
            var tracker  = _serviceProvider.GetRequiredService<IExperimentTracker>();
            var definition = BuildDefaultDefinition(injectPreprocessFailure: true);

            // Act
            Func<Task> act = async () => await executor.ExecuteAsync(definition, CancellationToken.None);

            // Assert
            await act.Should().ThrowAsync<PipelineRunFailedException>()
                     .Where(e => e.StageName == "preprocess");

            tracker.Runs.Should().ContainSingle()
                   .Which.Status.Should().Be(RunStatus.Failed);
        }

        private static PipelineDefinition BuildDefaultDefinition(bool injectPreprocessFailure = false)
        {
            return new PipelineDefinition(new[]
            {
                new IngestStage(),
                injectPreprocessFailure
                    ? new PreprocessStage(shouldThrow: true)
                    : new PreprocessStage(),
                new TrainingStage(),
                new RegistryStage()
            });
        }
    }

    #region === Production Contracts (mirrors domain objects) =======================================

    public record PipelineDefinition(IReadOnlyCollection<IPipelineStage> Stages);

    public interface IPipelineStage
    {
        string Name { get; }
        Task ExecuteAsync(PipelineContext context, CancellationToken token);
    }

    public interface IPipelineExecutor
    {
        Task<PipelineRunResult> ExecuteAsync(PipelineDefinition definition, CancellationToken token);
    }

    public interface IPipelineStageFactory
    {
        IPipelineStage Instantiate(string name);
    }

    public interface IExperimentTracker
    {
        void RecordRun(PipelineRunRecord record);
        IReadOnlyCollection<PipelineRunRecord> Runs { get; }
    }

    #endregion

    #region === In-memory/Test implementations ======================================================

    /// <summary>
    /// Simple factory that returns the stage instance verbatim (used to mimic production DI).
    /// </summary>
    internal sealed class PipelineStageFactory : IPipelineStageFactory
    {
        public IPipelineStage Instantiate(string name) =>
            name switch
            {
                "ingest"     => new IngestStage(),
                "preprocess" => new PreprocessStage(),
                "train"      => new TrainingStage(),
                "register"   => new RegistryStage(),
                _            => throw new ArgumentException($"Unknown stage '{name}'.", nameof(name))
            };
    }

    /// <summary>
    /// Executes each stage sequentially, handling cancellation and error propagation.
    /// </summary>
    internal sealed class PipelineExecutor : IPipelineExecutor
    {
        private readonly ILogger<PipelineExecutor> _logger;
        private readonly IExperimentTracker _tracker;

        public PipelineExecutor(ILogger<PipelineExecutor> logger, IExperimentTracker tracker)
        {
            _logger   = logger  ?? throw new ArgumentNullException(nameof(logger));
            _tracker  = tracker ?? throw new ArgumentNullException(nameof(tracker));
        }

        public async Task<PipelineRunResult> ExecuteAsync(
            PipelineDefinition definition,
            CancellationToken token)
        {
            if (definition == null) throw new ArgumentNullException(nameof(definition));

            var context = new PipelineContext();
            try
            {
                foreach (var stage in definition.Stages)
                {
                    token.ThrowIfCancellationRequested();
                    _logger.LogInformation("⏩ Starting stage: {Stage}", stage.Name);

                    var start = DateTimeOffset.UtcNow;
                    await stage.ExecuteAsync(context, token);
                    var elapsed = DateTimeOffset.UtcNow - start;

                    _logger.LogInformation("✅ Finished stage: {Stage} in {Elapsed}", stage.Name, elapsed);
                }

                var result = new PipelineRunResult(true, context.Artifacts);

                _tracker.RecordRun(new PipelineRunRecord
                {
                    RunId   = Guid.NewGuid(),
                    Status  = RunStatus.Succeeded,
                    Started = context.Started,
                    Ended   = DateTimeOffset.UtcNow
                });

                return result;
            }
            catch (OperationCanceledException)
            {
                _logger.LogWarning("✋ Pipeline execution canceled.");
                _tracker.RecordRun(new PipelineRunRecord
                {
                    RunId   = Guid.NewGuid(),
                    Status  = RunStatus.Canceled,
                    Started = context.Started,
                    Ended   = DateTimeOffset.UtcNow
                });
                throw;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "❌ Pipeline failed at stage '{Stage}'.", ex.Data["Stage"] ?? "?");

                _tracker.RecordRun(new PipelineRunRecord
                {
                    RunId   = Guid.NewGuid(),
                    Status  = RunStatus.Failed,
                    Started = context.Started,
                    Ended   = DateTimeOffset.UtcNow,
                    Reason  = ex.Message
                });

                throw new PipelineRunFailedException(
                    stageName: (string?) ex.Data["Stage"] ?? "unknown",
                    message:   ex.Message,
                    inner:     ex);
            }
        }
    }

    internal sealed class InMemoryExperimentTracker : IExperimentTracker
    {
        private readonly List<PipelineRunRecord> _runs = new();

        public IReadOnlyCollection<PipelineRunRecord> Runs => _runs;

        public void RecordRun(PipelineRunRecord record)
        {
            _runs.Add(record);
        }
    }

    #endregion

    #region === Stages ==============================================================================

    internal abstract class BaseStage : IPipelineStage
    {
        protected BaseStage(string name) => Name = name;

        public string Name { get; }

        public async Task ExecuteAsync(PipelineContext context, CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            try
            {
                await RunAsync(context, token).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                // add stage name to exception metadata for richer diagnostics
                ex.Data["Stage"] = Name;
                throw;
            }
        }

        protected abstract Task RunAsync(PipelineContext context, CancellationToken token);
    }

    internal sealed class IngestStage : BaseStage
    {
        public IngestStage() : base("ingest") { }

        protected override async Task RunAsync(PipelineContext context, CancellationToken token)
        {
            await Task.Delay(50, token); // simulate IO-bound ingestion
            context.Metadata["rowsIngested"] = 10_000;
        }
    }

    internal sealed class PreprocessStage : BaseStage
    {
        private readonly bool _shouldThrow;

        public PreprocessStage(bool shouldThrow = false) : base("preprocess") =>
            _shouldThrow = shouldThrow;

        protected override async Task RunAsync(PipelineContext context, CancellationToken token)
        {
            await Task.Delay(100, token); // pretend work

            if (_shouldThrow)
            {
                throw new InvalidOperationException("Synthetic failure while cleaning data.");
            }

            context.Metadata["cleanRows"] = 9_800;
        }
    }

    internal sealed class TrainingStage : BaseStage
    {
        public TrainingStage() : base("train") { }

        protected override async Task RunAsync(PipelineContext context, CancellationToken token)
        {
            await Task.Delay(150, token); // pretend compute

            context.Artifacts["model.checkpoint"] = new Artifact
            {
                Name = "model.checkpoint",
                Payload = new byte[] { 0x1, 0x2, 0x3 } // just a stub
            };

            context.Metadata["accuracy"] = 0.91;
        }
    }

    internal sealed class RegistryStage : BaseStage
    {
        public RegistryStage() : base("register") { }

        protected override async Task RunAsync(PipelineContext context, CancellationToken token)
        {
            await Task.Delay(50, token);

            context.Metadata["registryVersion"] = "v123";
        }
    }

    #endregion

    #region === Domain models / DTOs ================================================================

    public sealed class Artifact
    {
        public string Name { get; init; } = string.Empty;
        public byte[] Payload { get; init; } = Array.Empty<byte>();
    }

    public sealed class PipelineRunResult
    {
        public PipelineRunResult(bool success, IReadOnlyDictionary<string, Artifact> artifacts)
        {
            Success   = success;
            Artifacts = artifacts;
        }

        public bool Success { get; }
        public IReadOnlyDictionary<string, Artifact> Artifacts { get; }
    }

    public sealed class PipelineContext
    {
        public DateTimeOffset Started { get; } = DateTimeOffset.UtcNow;
        public IDictionary<string, object?> Metadata  { get; } = new Dictionary<string, object?>();
        public IDictionary<string, Artifact> Artifacts { get; } = new Dictionary<string, Artifact>();
    }

    public enum RunStatus
    {
        Succeeded,
        Failed,
        Canceled
    }

    public sealed class PipelineRunRecord
    {
        public Guid RunId { get; init; }
        public RunStatus Status { get; init; }
        public DateTimeOffset Started { get; init; }
        public DateTimeOffset Ended { get; init; }
        public string? Reason { get; init; }
    }

    public sealed class PipelineRunFailedException : Exception
    {
        public PipelineRunFailedException(string stageName, string message, Exception inner)
            : base(message, inner)
        {
            StageName = stageName;
        }

        public string StageName { get; }
    }

    #endregion
}
```