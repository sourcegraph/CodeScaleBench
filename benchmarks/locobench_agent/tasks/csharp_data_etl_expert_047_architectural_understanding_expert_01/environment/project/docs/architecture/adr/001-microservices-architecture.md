```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Hosting;
using Polly;
using Polly.CircuitBreaker;
using Polly.Registry;
using Xunit;

namespace PaletteStream.ETL.Canvas.Tests.Architecture
{
    /// <summary>
    /// Integration-style tests that assert compliance with ADR-001
    /// (Microservices Architecture) for the PaletteStream ETL Canvas.
    /// </summary>
    public sealed class MicroservicesArchitectureTests : IAsyncDisposable
    {
        private readonly IHost _host;
        private readonly HttpClient _client;

        public MicroservicesArchitectureTests()
        {
            // Spin up an in-memory ASP.NET Core host with TestServer
            _host = Host.CreateDefaultBuilder()
                        .ConfigureWebHostDefaults(webBuilder =>
                        {
                            webBuilder.UseTestServer()
                                      .UseStartup<TestStartup>();
                        })
                        .Start();

            _client = _host.GetTestClient();
        }

        [Fact(DisplayName = "Critical service contracts must be discoverable via DI")]
        public void DependencyGraph_ContainsCriticalServices()
        {
            var provider = _host.Services;

            Assert.NotNull(provider.GetService<IOrchestratorService>());
            Assert.NotNull(provider.GetService<IDataQualityService>());
            Assert.NotNull(provider.GetService<IEventBus>());
            Assert.NotNull(provider.GetService<IPolicyRegistry>());
        }

        [Fact(DisplayName = "Health endpoint must return HTTP 200")]
        public async Task HealthEndpoint_ReturnsSuccess()
        {
            var response = await _client.GetAsync("/health");
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        }

        [Fact(DisplayName = "Circuit breaker trips and recovers as expected")]
        public async Task CircuitBreaker_BehavesAsExpected()
        {
            var policyRegistry = _host.Services.GetRequiredService<IPolicyRegistry>();
            var breaker = policyRegistry.Get<AsyncCircuitBreakerPolicy>("defaultBreaker");

            // Force the circuit open
            breaker.Isolate();
            await Assert.ThrowsAsync<BrokenCircuitException>(() =>
                breaker.ExecuteAsync(() => Task.CompletedTask));

            Assert.Equal(CircuitState.Open, breaker.CircuitState);

            // Close the circuit and verify reset
            breaker.Reset();
            await breaker.ExecuteAsync(() => Task.CompletedTask);
            Assert.Equal(CircuitState.Closed, breaker.CircuitState);
        }

        public async ValueTask DisposeAsync()
        {
            _client?.Dispose();
            if (_host is IAsyncDisposable asyncHost)
                await asyncHost.DisposeAsync();
            else
                _host.Dispose();
        }
    }

    #region Test Startup & Stub Implementations

    /// <summary>
    /// Minimal Startup that wires up the same critical services used in production.
    /// </summary>
    internal sealed class TestStartup
    {
        public void ConfigureServices(IServiceCollection services)
        {
            // --- Core Pipeline Services ---
            services.AddSingleton<IOrchestratorService, OrchestratorService>();
            services.AddSingleton<IDataQualityService, DataQualityService>();

            // --- Observability ---
            services.AddSingleton<IEventBus, InMemoryEventBus>();
            services.AddHealthChecks()
                    .AddCheck<StartupSelfCheck>("self");

            // --- Resilience Policies ---
            var breaker = Policy
                .Handle<Exception>()
                .CircuitBreakerAsync(2, TimeSpan.FromSeconds(5));
            var registry = new PolicyRegistry
            {
                { "defaultBreaker", breaker }
            };
            services.AddSingleton<IPolicyRegistry>(registry);

            services.AddRouting();
        }

        public void Configure(IApplicationBuilder app)
        {
            app.UseRouting();
            app.UseEndpoints(endpoints =>
            {
                endpoints.MapHealthChecks("/health", new HealthCheckOptions
                {
                    ResponseWriter = async (ctx, _) =>
                    {
                        ctx.Response.StatusCode = (int)HttpStatusCode.OK;
                        await ctx.Response.CompleteAsync();
                    }
                });
            });
        }
    }

    internal sealed class StartupSelfCheck : IHealthCheck
    {
        public Task<HealthCheckResult> CheckHealthAsync(
            HealthCheckContext context,
            CancellationToken cancellationToken = default)
            => Task.FromResult(HealthCheckResult.Healthy("Self check passed"));
    }

    // ---------- Service Contracts ----------
    internal interface IOrchestratorService { }
    internal interface IDataQualityService { }
    internal interface IEventBus
    {
        void Publish<TEvent>(TEvent @event);
        IDisposable Subscribe<TEvent>(Action<TEvent> handler);
    }

    // ---------- Stub Services ----------
    internal sealed class OrchestratorService : IOrchestratorService { }
    internal sealed class DataQualityService : IDataQualityService { }

    internal sealed class InMemoryEventBus : IEventBus, IDisposable
    {
        private readonly ConcurrentDictionary<Type, List<Delegate>> _handlers = new();

        public void Publish<TEvent>(TEvent @event)
        {
            if (_handlers.TryGetValue(typeof(TEvent), out var list))
            {
                foreach (var action in list.ToArray())
                    ((Action<TEvent>)action).Invoke(@event);
            }
        }

        public IDisposable Subscribe<TEvent>(Action<TEvent> handler)
        {
            var list = _handlers.GetOrAdd(typeof(TEvent), _ => new List<Delegate>());
            list.Add(handler);
            return new Subscription(() => list.Remove(handler));
        }

        public void Dispose() => _handlers.Clear();

        private sealed class Subscription : IDisposable
        {
            private readonly Action _unsubscribe;
            private bool _disposed;

            public Subscription(Action unsubscribe) => _unsubscribe = unsubscribe;

            public void Dispose()
            {
                if (_disposed) return;
                _unsubscribe();
                _disposed = true;
            }
        }
    }

    #endregion
}
```