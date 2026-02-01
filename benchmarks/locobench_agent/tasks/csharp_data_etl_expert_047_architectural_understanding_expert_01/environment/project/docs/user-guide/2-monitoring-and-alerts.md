```csharp
// File: PaletteStream-ETL-Canvas/docs/user-guide/2-monitoring-and-alerts.md
// NOTE: Although this file physically lives under /docs,
// it is compiled as part of the test project for integration
// regression coverage of the Monitoring & Alerts subsystem.

using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using Moq;
using Xunit;

namespace PaletteStream.DataEtl.Tests.Monitoring
{
    #region Domain Contracts (extracted from production code base)

    /// <summary>
    /// Represents a domain event that is raised by the ETL pipeline.
    /// </summary>
    public interface IEtlEvent
    {
        DateTimeOffset OccurredAt { get; }
        string EventName         { get; }
        IReadOnlyDictionary<string, object?> Metadata { get; }
    }

    /// <summary>
    /// A monitoring service consumes ETL domain events for observability purposes.
    /// </summary>
    public interface IMonitoringSink
    {
        ValueTask TrackAsync(IEtlEvent etlEvent, CancellationToken token = default);
    }

    /// <summary>
    /// Defines the contract for an alert dispatcher (PagerDuty, Slack, e-mail, etc.).
    /// </summary>
    public interface IAlertDispatcher
    {
        ValueTask DispatchAsync(AlertDescriptor alert, CancellationToken token = default);
    }

    /// <summary>
    /// Simple POCO that represents a triggered alert.
    /// </summary>
    public sealed record AlertDescriptor(
        string AlertKey,
        AlertSeverity Severity,
        string Message,
        IReadOnlyDictionary<string, object?> Context);

    public enum AlertSeverity { Info, Warning, Error, Critical }

    /// <summary>
    /// An ETL pipeline raises events through this mediator.
    /// </summary>
    public interface IEtlEventBus
    {
        ValueTask PublishAsync(IEtlEvent etlEvent, CancellationToken token = default);
    }

    #endregion

    #region Production Implementation Stub (simplified for test harness)

    /// <summary>
    /// Orchestrates the monitoring & alert hooks in the real system.
    /// For the purpose of testing we re-implement a minimal version here.
    /// </summary>
    public sealed class MonitoringAndAlertHook : IEtlEventBus, IAsyncDisposable
    {
        private readonly ILogger<MonitoringAndAlertHook> _logger;
        private readonly IMonitoringSink _sink;
        private readonly IAlertDispatcher _dispatcher;

        public MonitoringAndAlertHook(
            ILogger<MonitoringAndAlertHook> logger,
            IMonitoringSink sink,
            IAlertDispatcher dispatcher)
        {
            _logger     = logger     ?? throw new ArgumentNullException(nameof(logger));
            _sink       = sink       ?? throw new ArgumentNullException(nameof(sink));
            _dispatcher = dispatcher ?? throw new ArgumentNullException(nameof(dispatcher));
        }

        public async ValueTask PublishAsync(IEtlEvent etlEvent, CancellationToken token = default)
        {
            if (etlEvent == null) throw new ArgumentNullException(nameof(etlEvent));

            // 1. Forward event to monitoring sink
            await _sink.TrackAsync(etlEvent, token).ConfigureAwait(false);

            // 2. Resolve alerting rules (hard-coded for test simplicity)
            //    † If the event name ends with ".Failure" we escalate
            if (etlEvent.EventName.EndsWith(".Failure", StringComparison.Ordinal))
            {
                var alert = new AlertDescriptor(
                    AlertKey : $"etl.{etlEvent.EventName}",
                    Severity : AlertSeverity.Error,
                    Message  : $"ETL failure captured: {etlEvent.EventName}",
                    Context  : etlEvent.Metadata);

                await _dispatcher.DispatchAsync(alert, token).ConfigureAwait(false);
            }

            _logger.LogDebug("ETL event processed by MonitoringAndAlertHook: {Event}",
                             etlEvent.EventName);
        }

        public ValueTask DisposeAsync()
        {
            // In the real implementation we would flush/dispose resources here.
            // For test purposes we keep it simple.
            _logger.LogInformation("MonitoringAndAlertHook disposed.");
            return ValueTask.CompletedTask;
        }
    }

    #endregion

    #region Tests

    /// <summary>
    /// Regression tests that validate the monitoring & alert flow.
    /// </summary>
    public class MonitoringAndAlertsTests
    {
        private static IEtlEvent CreateEvent(
            string name,
            IReadOnlyDictionary<string, object?>? metadata = null)
        {
            metadata ??= new Dictionary<string, object?>();

            return new EtlEventImpl(
                EventName: name,
                OccurredAt: DateTimeOffset.UtcNow,
                Metadata: metadata);
        }

        [Fact(DisplayName = "Monitoring sink should receive every ETL event")]
        public async Task Sink_Should_Receive_All_Events()
        {
            // Arrange
            var sinkMock       = new Mock<IMonitoringSink>(MockBehavior.Strict);
            var dispatcherMock = new Mock<IAlertDispatcher>(MockBehavior.Loose);
            var loggerStub     = new LoggerFactory().CreateLogger<MonitoringAndAlertHook>();

            var hook = new MonitoringAndAlertHook(loggerStub, sinkMock.Object, dispatcherMock.Object);
            var testEvt = CreateEvent("Load.Succeeded");

            sinkMock.Setup(s => s.TrackAsync(testEvt, It.IsAny<CancellationToken>()))
                    .Returns(ValueTask.CompletedTask)
                    .Verifiable();

            // Act
            await hook.PublishAsync(testEvt);

            // Assert
            sinkMock.Verify();
            dispatcherMock.Verify(d => d.DispatchAsync(It.IsAny<AlertDescriptor>(),
                                    It.IsAny<CancellationToken>()), Times.Never,
                                    "No alert should be dispatched for success events.");
        }

        [Fact(DisplayName = "Alert dispatcher should be invoked on failure events")]
        public async Task Alert_Dispatched_On_Failure()
        {
            // Arrange
            var sinkMock       = new Mock<IMonitoringSink>(MockBehavior.Loose);
            var dispatcherMock = new Mock<IAlertDispatcher>(MockBehavior.Strict);
            var loggerStub     = new LoggerFactory().CreateLogger<MonitoringAndAlertHook>();

            var hook = new MonitoringAndAlertHook(loggerStub, sinkMock.Object, dispatcherMock.Object);
            var failureEvt = CreateEvent(
                "Transform.Failure",
                new Dictionary<string, object?>
                {
                    ["JobId"]   = Guid.NewGuid(),
                    ["BatchId"] = 42
                });

            dispatcherMock.Setup(d => d.DispatchAsync(
                                        It.Is<AlertDescriptor>(a =>
                                            a.AlertKey == $"etl.{failureEvt.EventName}" &&
                                            a.Severity == AlertSeverity.Error),
                                        It.IsAny<CancellationToken>()))
                          .Returns(ValueTask.CompletedTask)
                          .Verifiable();

            // Act
            await hook.PublishAsync(failureEvt);

            // Assert
            dispatcherMock.Verify();
        }

        [Fact(DisplayName = "Publishing null events should throw ArgumentNullException")]
        public async Task Publish_Should_Throw_On_Null_Event()
        {
            // Arrange
            var hook = new MonitoringAndAlertHook(
                new LoggerFactory().CreateLogger<MonitoringAndAlertHook>(),
                new Mock<IMonitoringSink>().Object,
                new Mock<IAlertDispatcher>().Object);

            // Act & Assert
            await Assert.ThrowsAsync<ArgumentNullException>(() => hook.PublishAsync(null!));
        }

        [Fact(DisplayName = "Hook can be disposed safely multiple times")]
        public async Task Dispose_Should_Be_Idempotent()
        {
            // Arrange
            await using var hook = new MonitoringAndAlertHook(
                new LoggerFactory().CreateLogger<MonitoringAndAlertHook>(),
                new Mock<IMonitoringSink>().Object,
                new Mock<IAlertDispatcher>().Object);

            // Act & Assert
            await hook.DisposeAsync();
            await hook.DisposeAsync(); // second call should not throw
        }
    }

    #endregion

    #region Private helpers

    private sealed record EtlEventImpl(
        string EventName,
        DateTimeOffset OccurredAt,
        IReadOnlyDictionary<string, object?> Metadata) : IEtlEvent;

    #endregion
}
```