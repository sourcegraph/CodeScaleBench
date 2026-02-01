```csharp
// -------------------------------------------------------------------------------------------------
//  TycoonVerse.Infrastructure :: FirebasePushNotificationService
//  Purpose : Provides Firebase Cloud Messaging (FCM) functionality for push notifications.
//
//  NOTE    : This file is part of the Infrastructure layer and should contain *no*
//            domain-specific logic.  All business rules must live in the Application / Domain
//            projects and communicate through abstractions defined there.
// -------------------------------------------------------------------------------------------------

#nullable enable

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using FirebaseAdmin;
using FirebaseAdmin.Messaging;
using Google.Apis.Auth.OAuth2;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace TycoonVerse.Infrastructure.Services.Notifications
{
    /// <summary>
    /// Configuration options for <see cref="FirebasePushNotificationService"/>.
    /// </summary>
    public sealed class FirebasePushNotificationOptions
    {
        /// <summary>
        /// Path to the service-account JSON credentials file.
        /// </summary>
        public string ServiceAccountJsonPath { get; init; } = string.Empty;

        /// <summary>
        /// When <c>true</c> disables any outgoing network traffic and simply logs attempts.
        /// Useful for local development and automated test environments.
        /// </summary>
        public bool DryRun { get; init; }
    }

    /// <summary>
    /// Contract that abstracts Firebase push notification capabilities.
    /// </summary>
    public interface IFirebasePushNotificationService
    {
        /// <summary>
        /// Sends a push notification to the requested device tokens.
        /// </summary>
        /// <param name="payload">Data describing the notification.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        /// <returns>Firebase multicast response identifier.</returns>
        Task<string> SendNotificationAsync(
            NotificationPayload payload,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Subscribes the given device tokens to a Firebase topic.
        /// </summary>
        Task SubscribeToTopicAsync(
            IEnumerable<string> deviceTokens,
            string topic,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Unsubscribes the given device tokens from a Firebase topic.
        /// </summary>
        Task UnsubscribeFromTopicAsync(
            IEnumerable<string> deviceTokens,
            string topic,
            CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Value object that represents the data needed for an outbound push notification.
    /// </summary>
    public sealed record NotificationPayload(
        string              Title,
        string              Body,
        IReadOnlyDictionary<string, string>? Data,
        IEnumerable<string> DeviceTokens);

    /// <summary>
    /// Firebase implementation of <see cref="IFirebasePushNotificationService"/>.
    /// </summary>
    internal sealed class FirebasePushNotificationService :
        IFirebasePushNotificationService,
        IDisposable
    {
        private readonly FirebasePushNotificationOptions _options;
        private readonly ILogger<FirebasePushNotificationService> _logger;
        private readonly Lazy<Task<FirebaseApp>> _lazyInitialization;

        private bool _disposed;

        public FirebasePushNotificationService(
            IOptions<FirebasePushNotificationOptions>   options,
            ILogger<FirebasePushNotificationService>    logger)
        {
            _options            = options?.Value
                ?? throw new ArgumentNullException(nameof(options));
            _logger             = logger ?? throw new ArgumentNullException(nameof(logger));

            _lazyInitialization = new Lazy<Task<FirebaseApp>>(InitializeFirebaseAsync);
        }

        // -------------------------------------------------------------
        //  Public API
        // -------------------------------------------------------------

        public async Task<string> SendNotificationAsync(
            NotificationPayload payload,
            CancellationToken   cancellationToken = default)
        {
            ThrowIfDisposed();
            if (payload == null) throw new ArgumentNullException(nameof(payload));

            if (!payload.DeviceTokens?.Any() ?? true)
            {
                _logger.LogWarning("Attempted to send notification without any target device tokens.");
                return string.Empty;
            }

            // Dry-run mode short-circuits early, still allowing unit tests
            // to verify behavior via logs.
            if (_options.DryRun)
            {
                _logger.LogInformation(
                    "[Dry-Run] Would have sent notification '{Title}' to {Count} devices.",
                    payload.Title,
                    payload.DeviceTokens.Count());
                return "dry-run";
            }

            // Ensure Firebase app is configured only once.
            await _lazyInitialization.Value.ConfigureAwait(false);

            var message = new MulticastMessage
            {
                Notification = new Notification
                {
                    Title = payload.Title,
                    Body  = payload.Body
                },
                Tokens      = payload.DeviceTokens.ToList(),
                Data        = payload.Data is null ? null : new Dictionary<string, string>(payload.Data)
            };

            try
            {
                var response = await FirebaseMessaging.DefaultInstance
                    .SendMulticastAsync(message, cancellationToken)
                    .ConfigureAwait(false);

                var sentCount    = response.SuccessCount;
                var failedCount  = response.FailureCount;
                var messageId    = response.Responses
                    .FirstOrDefault(r => r.IsSuccess)?
                    .MessageId;

                if (failedCount > 0)
                {
                    _logger.LogWarning(
                        "Push notification '{Title}' partially failed: {Failures} failures / {Total} total.",
                        payload.Title,
                        failedCount,
                        payload.DeviceTokens.Count());
                }

                return messageId ?? string.Empty;
            }
            catch (Exception ex)
            {
                _logger.LogError(
                    ex,
                    "Failed to send push notification '{Title}' to {Count} devices.",
                    payload.Title,
                    payload.DeviceTokens.Count());

                throw;  // Bubble up so caller can decide to retry / circuit-break.
            }
        }

        public async Task SubscribeToTopicAsync(
            IEnumerable<string> deviceTokens,
            string              topic,
            CancellationToken   cancellationToken = default)
        {
            ThrowIfDisposed();

            if (_options.DryRun || !deviceTokens.Any()) return;

            await _lazyInitialization.Value.ConfigureAwait(false);

            try
            {
                await FirebaseMessaging.DefaultInstance
                    .SubscribeToTopicAsync(deviceTokens, topic, cancellationToken)
                    .ConfigureAwait(false);

                _logger.LogInformation(
                    "Subscribed {Count} devices to topic '{Topic}'.",
                    deviceTokens.Count(),
                    topic);
            }
            catch (Exception ex)
            {
                _logger.LogError(
                    ex,
                    "Failed to subscribe devices to topic '{Topic}'.",
                    topic);
                throw;
            }
        }

        public async Task UnsubscribeFromTopicAsync(
            IEnumerable<string> deviceTokens,
            string              topic,
            CancellationToken   cancellationToken = default)
        {
            ThrowIfDisposed();

            if (_options.DryRun || !deviceTokens.Any()) return;

            await _lazyInitialization.Value.ConfigureAwait(false);

            try
            {
                await FirebaseMessaging.DefaultInstance
                    .UnsubscribeFromTopicAsync(deviceTokens, topic, cancellationToken)
                    .ConfigureAwait(false);

                _logger.LogInformation(
                    "Unsubscribed {Count} devices from topic '{Topic}'.",
                    deviceTokens.Count(),
                    topic);
            }
            catch (Exception ex)
            {
                _logger.LogError(
                    ex,
                    "Failed to unsubscribe devices from topic '{Topic}'.",
                    topic);
                throw;
            }
        }

        // -------------------------------------------------------------
        //  Private helpers
        // -------------------------------------------------------------

        private async Task<FirebaseApp> InitializeFirebaseAsync()
        {
            if (FirebaseApp.DefaultInstance != null)
            {
                // Already initialized elsewhere (integration tests, etc.).
                return FirebaseApp.DefaultInstance;
            }

            if (string.IsNullOrWhiteSpace(_options.ServiceAccountJsonPath) ||
                !File.Exists(_options.ServiceAccountJsonPath))
            {
                const string msg = "Firebase ServiceAccountJsonPath must be supplied and point to an existing file.";
                _logger.LogCritical(msg);
                throw new InvalidOperationException(msg);
            }

            try
            {
                var credential = GoogleCredential.FromFile(_options.ServiceAccountJsonPath);
                var app        = FirebaseApp.Create(new AppOptions { Credential = credential });

                _logger.LogInformation("FirebaseApp successfully initialized for push notifications.");
                return await Task.FromResult(app);
            }
            catch (Exception ex)
            {
                _logger.LogCritical(ex, "Failed to initialize FirebaseApp.");
                throw;
            }
        }

        private void ThrowIfDisposed()
        {
            if (_disposed)
            {
                throw new ObjectDisposedException(nameof(FirebasePushNotificationService));
            }
        }

        // -------------------------------------------------------------
        //  IDisposable
        // -------------------------------------------------------------

        public void Dispose()
        {
            if (_disposed) return;

            if (_lazyInitialization.IsValueCreated &&
                FirebaseApp.DefaultInstance is { } app)
            {
                app.Delete();
            }

            _disposed = true;
            GC.SuppressFinalize(this);
        }
    }
}
```