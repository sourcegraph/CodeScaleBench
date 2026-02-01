```csharp
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace TycoonVerse.Application.Interfaces.Services
{
    /// <summary>
    /// Describes how a crash, unhandled exception, or soft failure should be classified when sent to
    /// the crash-reporting back-end (e.g., AppCenter, Sentry, Firebase).
    /// </summary>
    public enum CrashSeverity
    {
        /// <summary>
        /// Diagnostic information that is useful only while developing locally.
        /// </summary>
        Debug = 0,

        /// <summary>
        /// Informational messages that represent expected but notable runtime events.
        /// </summary>
        Info = 1,

        /// <summary>
        /// Minor issues that do not prevent normal gameplay but may degrade the experience.
        /// </summary>
        Warning = 2,

        /// <summary>
        /// Recoverable errors such as handled exceptions or API timeouts.
        /// </summary>
        Error = 3,

        /// <summary>
        /// Unrecoverable failures or unhandled exceptions that bring the application
        /// to an inconsistent state and usually terminate the process.
        /// </summary>
        Fatal = 4
    }

    /// <summary>
    /// Represents a short-lived in-memory breadcrumb used to trace user actions
    /// and system events leading up to a crash.
    /// </summary>
    public sealed class Breadcrumb
    {
        public Breadcrumb(string message,
                          IDictionary<string, object>? metadata = null,
                          DateTimeOffset? timestamp = null)
        {
            Message   = message  ?? throw new ArgumentNullException(nameof(message));
            Metadata  = metadata ?? new Dictionary<string, object>();
            Timestamp = timestamp ?? DateTimeOffset.UtcNow;
        }

        public string                       Message   { get; }
        public IDictionary<string, object>  Metadata  { get; }
        public DateTimeOffset               Timestamp { get; }

        public override string ToString() => $"{Timestamp:u} | {Message}";
    }

    /// <summary>
    /// Provides an abstraction over the game’s crash-reporting infrastructure,
    /// allowing the domain and presentation layers to record crashes without
    /// referencing concrete analytics SDKs.
    ///
    /// Implementations must be thread-safe and performant—they will be called
    /// from hot paths such as Update() and network callbacks.
    /// </summary>
    public interface ICrashReportingService
    {
        /// <summary>
        /// Initializes the crash-reporting pipeline for a given player session.
        /// This MUST be called once during the boot-strap phase before any other method.
        /// </summary>
        /// <param name="playerId">Unique, stable identifier for the current user.</param>
        /// <param name="additionalContext">
        /// Arbitrary key/value pairs (e.g., app version, locale) appended to every event.
        /// </param>
        /// <param name="cancellationToken">Propagates cancellation.</param>
        Task InitializeAsync(
            string playerId,
            IDictionary<string, string>? additionalContext = null,
            CancellationToken cancellationToken            = default);

        /// <summary>
        /// Records an exception and forwards it to the back-end service.
        /// </summary>
        /// <param name="exception">The captured exception.</param>
        /// <param name="severity">Indicates how critical the exception is.</param>
        /// <param name="context">Optional contextual data appended as tags.</param>
        /// <param name="cancellationToken">Propagates cancellation.</param>
        Task CaptureExceptionAsync(
            Exception exception,
            CrashSeverity severity                       = CrashSeverity.Error,
            IDictionary<string, object>? context         = null,
            CancellationToken cancellationToken          = default);

        /// <summary>
        /// Records a non-exception message to the crash-reporting back-end.
        /// Ideal for soft-failures and explicit Log("assert failed") equivalents.
        /// </summary>
        Task CaptureMessageAsync(
            string message,
            CrashSeverity severity                       = CrashSeverity.Info,
            IDictionary<string, object>? context         = null,
            CancellationToken cancellationToken          = default);

        /// <summary>
        /// Adds a breadcrumb to the in-memory trail. Breadcrumbs are sent together with
        /// the next captured exception so that engineers can replicate the failure path.
        /// </summary>
        /// <param name="message">Human-readable description of the action.</param>
        /// <param name="metadata">Key/value data providing additional context.</param>
        void AddBreadcrumb(string message, IDictionary<string, object>? metadata = null);

        /// <summary>
        /// Flushes all buffered events to the back-end. Useful when the app moves to background.
        /// </summary>
        /// <param name="timeout">Maximum time to wait for the flush to complete.</param>
        /// <param name="cancellationToken">Propagates cancellation.</param>
        Task FlushAsync(
            TimeSpan timeout,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Gracefully shuts down the crash-reporting pipeline, flushing any pending data and
        /// releasing native resources. Once shut down, the service MUST NOT be used again.
        /// </summary>
        Task ShutdownAsync(CancellationToken cancellationToken = default);

        /// <summary>
        /// Creates an isolated scope for contextual data (e.g., "MiniGame:Scanner").
        /// Any context set via <see cref="SetContextValue"/> or call to
        /// <see cref="AddBreadcrumb"/> will be disposed together with the scope.
        ///
        /// Typical usage:
        /// <code>
        /// using (crashService.BeginScope(new Dictionary&lt;string, object&gt; { ["Level"] = 12 }))
        /// {
        ///     // Gameplay code
        /// }
        /// // Scope is automatically flushed and removed
        /// </code>
        /// </summary>
        /// <param name="context">Initial set of scope-local context values.</param>
        /// <returns>An <see cref="IDisposable"/> handle that controls scope lifetime.</returns>
        IDisposable BeginScope(IDictionary<string, object>? context = null);

        /// <summary>
        /// Programmatically injects or overwrites a context value that will be attached
        /// to all subsequent crash events within the current scope.
        /// </summary>
        void SetContextValue(string key, object value);
    }
}
```