```csharp
using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Xunit;
using CanvasCraft.Domain.Observability;

namespace CanvasCraft.Integration.Tests
{
    /// <summary>
    /// Integration-level tests that spin-up the full CanvasCraft API pipeline and exercise the public
    /// model-serving surface.  These tests verify that:
    ///     1. The inference endpoint returns a well-formed prediction response.
    ///     2. The Model Registry surfaces the most-recent production version.
    ///     3. Observer hooks are executed when the serving layer detects model drift.
    /// </summary>
    public sealed class ModelServingTests : IClassFixture<ModelServingTests.CanvasCraftFactory>
    {
        private readonly HttpClient _client;
        private readonly CanvasCraftFactory _factory;
        private readonly JsonSerializerOptions _jsonOptions = new()
        {
            PropertyNameCaseInsensitive = true,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase
        };

        public ModelServingTests(CanvasCraftFactory factory)
        {
            _factory = factory;
            _client  = factory.CreateClient();
        }

        #region Test Factory
        /// <summary>
        /// Bootstraps the entire CanvasCraft web host in an *in-memory* test environment.
        /// We can freely override any infrastructure plumbing required for deterministic
        /// integration tests (e.g. switch the persistent store to an in-memory DB, replace
        /// the message bus, short-circuit external dependencies, etc.).
        /// </summary>
        public sealed class CanvasCraftFactory : WebApplicationFactory<Program>
        {
            protected override void ConfigureWebHost(IWebHostBuilder builder)
            {
                builder.UseEnvironment("Test");
                builder.ConfigureServices(services =>
                {
                    //
                    // Hook a test-specific implementation for the drift observer so that
                    // we can assert on side-effects without talking to external systems.
                    //
                    services.AddSingleton<TestDriftObserver>();
                    services.AddSingleton<IModelDriftObserver>(
                        sp => sp.GetRequiredService<TestDriftObserver>());
                });
            }
        }
        #endregion

        #region Tests

        [Fact]
        public async Task PredictEndpoint_ShouldReturn200AndPredictionPayload()
        {
            // Arrange
            const string modelId = "stylegan-v2";
            var requestBody = new
            {
                inputs = new[] { "seed:42", "style:impressionist" }
            };

            var content = new StringContent(
                JsonSerializer.Serialize(requestBody, _jsonOptions),
                Encoding.UTF8,
                "application/json");

            // Act
            var response = await _client.PostAsync($"/api/v1/serving/{modelId}/predict", content);

            // Assert
            response.EnsureSuccessStatusCode();
            var json = await response.Content.ReadAsStringAsync();
            var payload = JsonSerializer.Deserialize<DTOs.PredictionResponse>(json, _jsonOptions);

            payload.Should().NotBeNull();
            payload!.Outputs.Should().NotBeEmpty();
            payload!.Metadata.ModelId.Should().Be(modelId);
            payload!.Metadata.Version.Should().NotBeNullOrEmpty();
            payload!.Metadata.InferenceTimeMs.Should().BeGreaterThan(0);
        }

        [Fact]
        public async Task RegistryEndpoint_ShouldReturnLatestModelVersion()
        {
            // Arrange
            const string modelId = "stylegan-v2";

            // Act
            var response = await _client.GetAsync($"/api/v1/registry/{modelId}/versions/latest");

            // Assert
            response.EnsureSuccessStatusCode();
            var json = await response.Content.ReadAsStringAsync();
            var versionInfo = JsonSerializer.Deserialize<DTOs.ModelVersionResponse>(json, _jsonOptions);

            versionInfo.Should().NotBeNull();
            versionInfo!.ModelId.Should().Be(modelId);
            versionInfo.Version.Should().NotBeNullOrWhiteSpace();
            versionInfo.IsProduction.Should().BeTrue();
            versionInfo.CreatedAt.Should().BeOnOrBefore(DateTimeOffset.UtcNow);
        }

        [Fact]
        public async Task ModelDrift_ShouldNotifyObserver_OnOutOfDistributionInput()
        {
            // Arrange
            var driftObserver = _factory.Services.GetRequiredService<TestDriftObserver>();
            var requestBody   = new { inputs = new[] { "noise:random" } };
            var content       = new StringContent(
                JsonSerializer.Serialize(requestBody, _jsonOptions),
                Encoding.UTF8,
                "application/json");

            // Act: Fire a prediction that is expected to trigger drift
            _ = await _client.PostAsync($"/api/v1/serving/stylegan-v2/predict", content);

            // Assert: Wait (bounded) for the observer to be signalled
            var completedTask = await Task.WhenAny(
                driftObserver.DriftDetected.Task,
                Task.Delay(TimeSpan.FromSeconds(5)));

            completedTask.Should().Be(driftObserver.DriftDetected.Task,
                "model drift should be detected and propagated to registered observers");

            var driftEvent = await driftObserver.DriftDetected.Task;
            driftEvent.DriftScore.Should().BeGreaterThan(0.5);
            driftEvent.ModelId.Should().Be("stylegan-v2");
        }

        #endregion

        #region Helpers / Test Doubles

        /// <summary>
        /// Captures model drift notifications so that tests can assert on them
        /// without leaking implementation details.  Registered inside the test
        /// DI container as the concrete implementation of IModelDriftObserver.
        /// </summary>
        private sealed class TestDriftObserver : IModelDriftObserver
        {
            public TaskCompletionSource<ModelDriftEvent> DriftDetected { get; } =
                new(TaskCreationOptions.RunContinuationsAsynchronously);

            public Task OnDriftAsync(ModelDriftEvent driftEvent, CancellationToken cancellationToken = default)
            {
                DriftDetected.TrySetResult(driftEvent);
                return Task.CompletedTask;
            }
        }

        #endregion
    }

    #region DTOs (test-local projections)

    // NOTE: These are *test-only* projections used for deserialisation.
    // The production API is versioned and may superset the properties defined here.

    namespace DTOs
    {
        public sealed record PredictionResponse(string[] Outputs, PredictionMeta Metadata);

        public sealed record PredictionMeta(string ModelId,
                                           string Version,
                                           double InferenceTimeMs);

        public sealed record ModelVersionResponse(string ModelId,
                                                  string Version,
                                                  bool   IsProduction,
                                                  DateTimeOffset CreatedAt);
    }

    #endregion
}
```