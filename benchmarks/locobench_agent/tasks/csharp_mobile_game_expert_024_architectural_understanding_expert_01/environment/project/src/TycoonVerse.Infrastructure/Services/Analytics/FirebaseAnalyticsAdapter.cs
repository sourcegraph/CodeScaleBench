```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Firebase;
using Firebase.Analytics;
using Microsoft.Extensions.Logging;
using TycoonVerse.Application.Abstractions.Analytics;
using TycoonVerse.Application.Abstractions.Infrastructure;
using TycoonVerse.Domain.Analytics;

#if UNITY_IOS || UNITY_ANDROID
using UnityEngine;
#endif

namespace TycoonVerse.Infrastructure.Services.Analytics
{
    /// <summary>
    /// Bridges TycoonVerse's domain-driven analytics API to Firebase Analytics.
    /// Handles offline queuing, persistence, and retry logic to guarantee
    /// deterministic event delivery once connectivity returns.
    /// </summary>
    public sealed class FirebaseAnalyticsAdapter : IAnalyticsAdapter, IDisposable
    {
        private readonly IConnectivityService _connectivityService;
        private readonly IOfflineEventStore _offlineStore;
        private readonly ILogger<FirebaseAnalyticsAdapter> _logger;

        // Thread-safe in-memory buffer for events generated while offline.
        private readonly ConcurrentQueue<AnalyticsEvent> _pendingEvents = new();

        // Semaphore to avoid concurrent flushes.
        private readonly SemaphoreSlim _flushLock = new(1, 1);

        private bool _disposed;
        private bool _firebaseReady;

        public FirebaseAnalyticsAdapter(
            IConnectivityService connectivityService,
            IOfflineEventStore offlineStore,
            ILogger<FirebaseAnalyticsAdapter> logger)
        {
            _connectivityService = connectivityService ?? throw new ArgumentNullException(nameof(connectivityService));
            _offlineStore        = offlineStore        ?? throw new ArgumentNullException(nameof(offlineStore));
            _logger              = logger              ?? throw new ArgumentNullException(nameof(logger));

            _connectivityService.ConnectivityChanged += OnConnectivityChanged;

            // Fire-and-forget initialization
            _ = InitializeFirebaseAsync();
        }

        #region IAnalyticsAdapter

        /// <inheritdoc />
        public async Task LogEventAsync(AnalyticsEvent analyticsEvent, CancellationToken ct = default)
        {
            ThrowIfDisposed();

            if (analyticsEvent == null)
                throw new ArgumentNullException(nameof(analyticsEvent));

            if (!_firebaseReady || !_connectivityService.IsConnected)
            {
                await EnqueueOfflineAsync(analyticsEvent, ct).ConfigureAwait(false);
                return;
            }

            await SendToFirebaseAsync(analyticsEvent, ct).ConfigureAwait(false);
        }

        /// <inheritdoc />
        public async Task SetUserIdAsync(string userId, CancellationToken ct = default)
        {
            ThrowIfDisposed();

            if (string.IsNullOrWhiteSpace(userId))
                throw new ArgumentException("UserId must not be null or whitespace.", nameof(userId));

            await WaitForFirebaseAsync(ct).ConfigureAwait(false);

            FirebaseAnalytics.SetUserId(userId);
            _logger.LogDebug("Firebase userId set to '{UserId}'", userId);
        }

        /// <inheritdoc />
        public async Task SetUserPropertyAsync(string name, string value, CancellationToken ct = default)
        {
            ThrowIfDisposed();

            if (string.IsNullOrWhiteSpace(name))
                throw new ArgumentException("Property name must not be null or whitespace.", nameof(name));

            await WaitForFirebaseAsync(ct).ConfigureAwait(false);

            FirebaseAnalytics.SetUserProperty(name, value);
            _logger.LogDebug("Firebase user property set '{Property}' = '{Value}'", name, value);
        }

        /// <inheritdoc />
        public async Task FlushAsync(CancellationToken ct = default)
        {
            ThrowIfDisposed();

            if (!_pendingEvents.IsEmpty)
            {
                await _flushLock.WaitAsync(ct).ConfigureAwait(false);
                try
                {
                    if (!_connectivityService.IsConnected || !_firebaseReady)
                        return;

                    while (_pendingEvents.TryDequeue(out var ev))
                    {
                        ct.ThrowIfCancellationRequested();
                        await SendToFirebaseAsync(ev, ct).ConfigureAwait(false);
                        await _offlineStore.RemoveAsync(ev, ct).ConfigureAwait(false);
                    }
                }
                finally
                {
                    _flushLock.Release();
                }
            }
        }

        #endregion

        #region Private Helpers

        private async Task InitializeFirebaseAsync()
        {
            try
            {
                var dependencyStatus = await FirebaseApp.CheckAndFixDependenciesAsync();
                if (dependencyStatus == DependencyStatus.Available)
                {
                    // Ensures that the default app is created.
                    _ = FirebaseApp.DefaultInstance;
                    _firebaseReady = true;

                    // Load persisted events (if any) into in-memory queue.
                    await RestorePendingEventsAsync().ConfigureAwait(false);

                    // Attempt initial flush.
                    _ = FlushAsync();
                    _logger.LogInformation("Firebase Analytics initialized successfully.");
                }
                else
                {
                    _logger.LogError("Could not resolve all Firebase dependencies: {Status}", dependencyStatus);
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to initialize Firebase Analytics.");
            }
        }

        private async Task EnqueueOfflineAsync(AnalyticsEvent analyticsEvent, CancellationToken ct)
        {
            _pendingEvents.Enqueue(analyticsEvent);
            await _offlineStore.PersistAsync(analyticsEvent, ct).ConfigureAwait(false);
            _logger.LogDebug("Event '{EventName}' queued for later delivery.", analyticsEvent.Name);
        }

        private async Task SendToFirebaseAsync(AnalyticsEvent analyticsEvent, CancellationToken ct)
        {
            try
            {
                var parameters = ConvertParameters(analyticsEvent.Parameters);
                FirebaseAnalytics.LogEvent(analyticsEvent.Name, parameters);
                _logger.LogDebug("Event '{EventName}' sent to Firebase.", analyticsEvent.Name);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to send event '{EventName}', queuing for retry.", analyticsEvent.Name);
                await EnqueueOfflineAsync(analyticsEvent, ct).ConfigureAwait(false);
            }
        }

        private static Parameter[] ConvertParameters(IReadOnlyDictionary<string, object>? source)
        {
            if (source == null || source.Count == 0)
                return Array.Empty<Parameter>();

            var list = new List<Parameter>(source.Count);
            foreach (var kv in source)
            {
                switch (kv.Value)
                {
                    case null:
                        continue;

                    case long l:
                        list.Add(new Parameter(kv.Key, l));
                        break;

                    case int i:
                        list.Add(new Parameter(kv.Key, i));
                        break;

                    case double d:
                        list.Add(new Parameter(kv.Key, d));
                        break;

                    case float f:
                        list.Add(new Parameter(kv.Key, f));
                        break;

                    default:
                        list.Add(new Parameter(kv.Key, kv.Value.ToString()));
                        break;
                }
            }
            return list.ToArray();
        }

        private async Task RestorePendingEventsAsync()
        {
            var restored = await _offlineStore.ReadAllAsync().ConfigureAwait(false);
            foreach (var ev in restored)
            {
                _pendingEvents.Enqueue(ev);
            }

            if (restored.Count > 0)
                _logger.LogInformation("Restored {Count} offline analytics events from persistent store.", restored.Count);
        }

        private void OnConnectivityChanged(object? sender, ConnectivityChangedEventArgs e)
        {
            if (e.IsConnected)
            {
                // Fire-and-forget flush, no awaiting inside event handler.
                _ = FlushAsync();
            }
        }

        private async Task WaitForFirebaseAsync(CancellationToken ct)
        {
            while (!_firebaseReady)
            {
                ct.ThrowIfCancellationRequested();
                await Task.Delay(250, ct).ConfigureAwait(false);
            }
        }

        private void ThrowIfDisposed()
        {
            if (_disposed) throw new ObjectDisposedException(nameof(FirebaseAnalyticsAdapter));
        }

        #endregion

        #region IDisposable

        public void Dispose()
        {
            if (_disposed) return;

            _connectivityService.ConnectivityChanged -= OnConnectivityChanged;
            _flushLock.Dispose();
            _disposed = true;
            _logger.LogDebug("FirebaseAnalyticsAdapter disposed.");
        }

        #endregion
    }
}
```