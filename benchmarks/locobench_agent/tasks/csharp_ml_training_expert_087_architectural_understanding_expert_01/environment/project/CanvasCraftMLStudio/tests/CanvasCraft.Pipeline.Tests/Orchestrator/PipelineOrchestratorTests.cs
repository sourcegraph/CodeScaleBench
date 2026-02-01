```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Pipeline.Core;
using CanvasCraft.Pipeline.Core.Events;
using CanvasCraft.Pipeline.Core.Orchestration;
using CanvasCraft.Pipeline.Core.Stages;
using FluentAssertions;
using Moq;
using Xunit;

namespace CanvasCraft.Pipeline.Tests.Orchestrator
{
    /// <summary>
    /// Unit-tests for <see cref="PipelineOrchestrator"/>.
    /// The orchestrator is expected to co-ordinate pipeline stages, publish domain events,
    /// honour cancellation tokens, and gracefully handle exceptions.
    /// </summary>
    public sealed class PipelineOrchestratorTests
    {
        private static readonly PipelineContext DefaultContext = new("unit-test-run");

        #region Happy-Path

        [Fact(DisplayName = "Executes all pipeline stages in the configured order")]
        public async Task ExecuteAsync_WhenAllStagesSucceed_RunsSequentiallyInOrder()
        {
            // Arrange
            var executed = new List<string>();

            var stage1 = CreateStageMock("Ingest", executed);
            var stage2 = CreateStageMock("Preprocess", executed);
            var stage3 = CreateStageMock("Train", executed);

            var bus = new Mock<IPipelineEventBus>();

            var orchestrator = new PipelineOrchestrator(
                new[] { stage1.Object, stage2.Object, stage3.Object },
                bus.Object);

            // Act
            await orchestrator.ExecuteAsync(DefaultContext, CancellationToken.None);

            // Assert – executed in order
            executed.Should().ContainInOrder("Ingest", "Preprocess", "Train");
            stage1.Verify(s => s.ExecuteAsync(DefaultContext, It.IsAny<CancellationToken>()), Times.Once);
            stage2.Verify(s => s.ExecuteAsync(DefaultContext, It.IsAny<CancellationToken>()), Times.Once);
            stage3.Verify(s => s.ExecuteAsync(DefaultContext, It.IsAny<CancellationToken>()), Times.Once);
        }

        [Fact(DisplayName = "Publishes StageCompletedEvent after each successful stage")]
        public async Task ExecuteAsync_WhenStageCompletes_PublishesStageCompletedEvent()
        {
            // Arrange
            var stage1 = new Mock<IPipelineStage>();
            stage1.SetupGet(s => s.Name).Returns("Feature-Engineering");
            stage1.Setup(s => s.ExecuteAsync(It.IsAny<PipelineContext>(), It.IsAny<CancellationToken>()))
                  .Returns(Task.CompletedTask);

            var bus = new Mock<IPipelineEventBus>();

            var orchestrator = new PipelineOrchestrator(
                new[] { stage1.Object },
                bus.Object);

            // Act
            await orchestrator.ExecuteAsync(DefaultContext, CancellationToken.None);

            // Assert
            bus.Verify(b => b.PublishAsync(
                It.Is<StageCompletedEvent>(e =>
                    e.PipelineRunId == DefaultContext.RunId &&
                    e.StageName == "Feature-Engineering"),
                It.IsAny<CancellationToken>()),
                Times.Once);
        }

        #endregion

        #region Failure-Cases

        [Fact(DisplayName = "Halts execution and publishes StageFailedEvent when a stage throws")]
        public async Task ExecuteAsync_WhenStageFails_PublishesFailureAndStops()
        {
            // Arrange
            var expectedException = new InvalidOperationException("Synthetic failure");

            var stage1 = new Mock<IPipelineStage>();
            stage1.SetupGet(s => s.Name).Returns("Transform");
            stage1.Setup(s => s.ExecuteAsync(It.IsAny<PipelineContext>(), It.IsAny<CancellationToken>()))
                  .ThrowsAsync(expectedException);

            var stage2 = new Mock<IPipelineStage>();
            stage2.SetupGet(s => s.Name).Returns("Train");

            var bus = new Mock<IPipelineEventBus>();

            var orchestrator = new PipelineOrchestrator(
                new[] { stage1.Object, stage2.Object },
                bus.Object);

            // Act
            Func<Task> act = () => orchestrator.ExecuteAsync(DefaultContext, CancellationToken.None);

            // Assert
            (await Assert.ThrowsAsync<PipelineStageException>(act))
                .InnerException.Should().Be(expectedException);

            bus.Verify(b => b.PublishAsync(
                It.Is<StageFailedEvent>(e =>
                    e.PipelineRunId == DefaultContext.RunId &&
                    e.StageName == "Transform" &&
                    e.Error.Contains(expectedException.Message)),
                It.IsAny<CancellationToken>()),
                Times.Once);

            // Stage2 must never run
            stage2.Verify(s => s.ExecuteAsync(It.IsAny<PipelineContext>(), It.IsAny<CancellationToken>()), Times.Never);
        }

        #endregion

        #region Cancellation

        [Fact(DisplayName = "Propagates cancellation token to pipeline stages")]
        public async Task ExecuteAsync_WhenCancelled_StopsEarlyAndThrows()
        {
            // Arrange
            using var cts = new CancellationTokenSource();
            var tcs = new TaskCompletionSource();

            var stage1 = new Mock<IPipelineStage>();
            stage1.SetupGet(s => s.Name).Returns("Long-Running");
            stage1.Setup(s => s.ExecuteAsync(It.IsAny<PipelineContext>(), It.IsAny<CancellationToken>()))
                  .Returns(async (_, token) =>
                  {
                      tcs.SetResult();
                      await Task.Delay(TimeSpan.FromMinutes(5), token); // never completes until cancelled
                  });

            var bus = new Mock<IPipelineEventBus>();

            var orchestrator = new PipelineOrchestrator(
                new[] { stage1.Object },
                bus.Object);

            // Act – start execution, wait until we enter stage1, then cancel
            var runTask = orchestrator.ExecuteAsync(DefaultContext, cts.Token);
            await tcs.Task; // ensure stage has started
            cts.Cancel();

            // Assert
            await Assert.ThrowsAsync<TaskCanceledException>(() => runTask);
            stage1.Verify(s => s.ExecuteAsync(It.IsAny<PipelineContext>(), It.IsAny<CancellationToken>()), Times.Once);
        }

        #endregion

        #region Helpers

        private static Mock<IPipelineStage> CreateStageMock(string name, ICollection<string> auditTrail)
        {
            var mock = new Mock<IPipelineStage>();
            mock.SetupGet(s => s.Name).Returns(name);
            mock.Setup(s => s.ExecuteAsync(It.IsAny<PipelineContext>(), It.IsAny<CancellationToken>()))
                .Returns((PipelineContext ctx, CancellationToken _) =>
                {
                    auditTrail.Add(name);
                    return Task.CompletedTask;
                });
            return mock;
        }

        #endregion
    }
}
```