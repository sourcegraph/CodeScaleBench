using System;
using System.Diagnostics;
using Hangfire;
using Hangfire.Server;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Orchestrator.Application.Jobs
{
    /// <summary>
    /// Custom Hangfire <see cref="JobActivator"/> that delegates job activation to the
    /// application's <see cref="IServiceProvider"/>.  This allows Hangfire jobs to fully
    /// participate in ASP .NET Core dependency-injection, logging, telemetry, and configuration
    /// pipelines.
    /// </summary>
    public sealed class HangfireJobActivator : JobActivator
    {
        private readonly IServiceProvider _serviceProvider;
        private readonly ILogger<HangfireJobActivator> _logger;

        private static readonly ActivitySource ActivitySource =
            new("PaletteStream.Orchestrator.HangfireJob");

        public HangfireJobActivator(IServiceProvider serviceProvider)
        {
            _serviceProvider = serviceProvider ?? throw new ArgumentNullException(nameof(serviceProvider));
            _logger          = _serviceProvider.GetRequiredService<ILogger<HangfireJobActivator>>();
        }

        /// <summary>
        /// Starts a new scoped container for each Hangfire background job.
        /// </summary>
        public override JobActivatorScope BeginScope(JobActivatorContext context)
        {
            if (context == null) throw new ArgumentNullException(nameof(context));

            // This log entry helps correlate enqueue-time diagnostics with run-time diagnostics.
            _logger.LogDebug("Beginning Hangfire job scope for JobId={JobId}, Type={JobType}.",
                context.BackgroundJob?.Id,
                context.BackgroundJob?.Job?.Type?.FullName);

            // Create a DI scope so that scoped services are disposed after job completion.
            var serviceScope = _serviceProvider.CreateScope();

            // Set up OpenTelemetry / System.Diagnostics tracing for end-to-end correlation.
            Activity? activity = ActivitySource.StartActivity(
                $"{context.BackgroundJob?.Job?.Type?.Name}.{context.BackgroundJob?.Job?.Method?.Name}",
                ActivityKind.Internal);

            // Enrich the activity with Hangfire metadata for observability dashboards.
            activity?.SetTag("hangfire.job.id", context.BackgroundJob?.Id);
            activity?.SetTag("hangfire.job.queue", context.BackgroundJob?.Queue);

            return new ScopedActivatorScope(serviceScope, _logger, activity, context);
        }

        #region Nested Scope

        /// <summary>
        /// A wrapper around <see cref="IServiceScope"/> that implements Hangfire's
        /// <see cref="JobActivatorScope"/> abstraction.
        /// </summary>
        private sealed class ScopedActivatorScope : JobActivatorScope
        {
            private readonly IServiceScope      _scope;
            private readonly ILogger            _logger;
            private readonly Activity?          _activity;
            private readonly JobActivatorContext _context;
            private readonly Guid               _scopeId = Guid.NewGuid();
            private          bool               _disposed;

            public ScopedActivatorScope(
                IServiceScope scope,
                ILogger logger,
                Activity? activity,
                JobActivatorContext context)
            {
                _scope    = scope    ?? throw new ArgumentNullException(nameof(scope));
                _logger   = logger   ?? throw new ArgumentNullException(nameof(logger));
                _activity = activity;
                _context  = context  ?? throw new ArgumentNullException(nameof(context));

                _logger.LogTrace("Hangfire DI scope {ScopeId} created for JobId={JobId}.",
                    _scopeId,
                    _context.BackgroundJob?.Id);
            }

            /// <inheritdoc />
            public override object Resolve(Type type)
            {
                if (_disposed)
                {
                    throw new ObjectDisposedException(nameof(ScopedActivatorScope),
                        "Attempted to resolve a service from a disposed Hangfire scope.");
                }

                try
                {
                    _logger.LogTrace("Resolving service {ServiceType} in Hangfire scope {ScopeId} for JobId={JobId}.",
                        type.FullName,
                        _scopeId,
                        _context.BackgroundJob?.Id);

                    return _scope.ServiceProvider.GetRequiredService(type);
                }
                catch (Exception ex)
                {
                    // Capture dependency-resolution failures for troubleshooting.
                    _logger.LogError(ex,
                        "Failed to resolve service {ServiceType} in Hangfire scope {ScopeId} for JobId={JobId}.",
                        type.FullName,
                        _scopeId,
                        _context.BackgroundJob?.Id);

                    throw;
                }
            }

            /// <inheritdoc />
            public override void DisposeScope()
            {
                if (_disposed) return;

                try
                {
                    _scope.Dispose();
                    _activity?.Dispose();
                }
                catch (Exception ex)
                {
                    // Swallowing exceptions during disposal can mask resource-leak bugs,
                    // so we log and re-throw as a best-practice.
                    _logger.LogError(ex,
                        "Error occurred while disposing Hangfire scope {ScopeId} for JobId={JobId}.",
                        _scopeId,
                        _context.BackgroundJob?.Id);

                    throw;
                }
                finally
                {
                    _disposed = true;

                    _logger.LogDebug("Disposed Hangfire scope {ScopeId} for JobId={JobId}.",
                        _scopeId,
                        _context.BackgroundJob?.Id);
                }
            }
        }

        #endregion
    }
}