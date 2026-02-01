```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright file="UnityLocationService.cs">
//   TycoonVerse – Enterprise Empire Simulator
//   © 2024 TycoonVerse Studios. All rights reserved.
// </copyright>
// <summary>
//   Unity-specific implementation of the ILocationService contract.  Bridges UnityEngine.LocationService to the
//   TycoonVerse domain, adds caching for offline scenarios, and exposes a reactive event stream so that other layers
//   (e.g., pricing engines, disaster simulations, analytics) can observe real–time location changes.
// </summary>
// --------------------------------------------------------------------------------------------------------------------

using System;
using System.Globalization;
using System.Threading;
using System.Threading.Tasks;
using TycoonVerse.Domain.Abstractions;
using TycoonVerse.Domain.Location;
using TycoonVerse.Domain.Models;
using UnityEngine;
#if UNITY_ANDROID
using UnityEngine.Android;
#endif

namespace TycoonVerse.Infrastructure.Services.Location
{
    /// <summary>
    /// Unity-powered implementation of <see cref="ILocationService"/>.
    /// </summary>
    /// <remarks>
    /// Responsibilities:
    /// • Request and manage platform-level permissions.
    /// • Convert UnityEngine.LocationInfo to the TycoonVerse <see cref="GeoCoordinate"/> domain model.
    /// • Persist the last successful coordinate, guaranteeing deterministic behaviour while offline.
    /// • Raise <see cref="LocationUpdated"/> events on a configurable interval for observers.
    /// • Forward anonymised telemetry to <see cref="IAnalyticsService"/>.
    /// </remarks>
    public sealed class UnityLocationService : ILocationService, IDisposable
    {
        // ----------------------------------------------------------------------------------------------------------------
        // Constants / Keys
        // ----------------------------------------------------------------------------------------------------------------
        private const string LastLatitudeKey  = "tv.location.last.lat";
        private const string LastLongitudeKey = "tv.location.last.lon";
        private const string LastTimestampKey = "tv.location.last.ts";

        // ----------------------------------------------------------------------------------------------------------------
        // Dependencies
        // ----------------------------------------------------------------------------------------------------------------
        private readonly IAnalyticsService             _analytics;
        private readonly IDateTimeProvider             _clock;
        private readonly TimeSpan                      _updateInterval;
        private readonly CancellationTokenSource       _cts          = new();
        private readonly object                        _syncRoot     = new();

        // ----------------------------------------------------------------------------------------------------------------
        // Runtime state
        // ----------------------------------------------------------------------------------------------------------------
        private GeoCoordinate?                         _lastLocation;
        private Task?                                  _pollingLoop;

        // ----------------------------------------------------------------------------------------------------------------
        // Events
        // ----------------------------------------------------------------------------------------------------------------

        /// <inheritdoc/>
        public event EventHandler<GeoCoordinate>? LocationUpdated;

        // ----------------------------------------------------------------------------------------------------------------
        // Construction
        // ----------------------------------------------------------------------------------------------------------------
        public UnityLocationService(IAnalyticsService analytics,
                                    IDateTimeProvider clock,
                                    TimeSpan? updateInterval = null)
        {
            _analytics       = analytics ?? throw new ArgumentNullException(nameof(analytics));
            _clock           = clock     ?? throw new ArgumentNullException(nameof(clock));
            _updateInterval  = updateInterval ?? TimeSpan.FromSeconds(30);
            LoadLastKnownLocation();
        }

        // ----------------------------------------------------------------------------------------------------------------
        // ILocationService
        // ----------------------------------------------------------------------------------------------------------------

        /// <inheritdoc/>
        public async Task<GeoCoordinate?> GetCurrentLocationAsync(CancellationToken externalToken = default)
        {
            // Ensure Unity LocationService is initialised.
            if (!await EnsureServiceStartedAsync(externalToken).ConfigureAwait(false))
                return _lastLocation; // Return stale coordinate (may be null) when permission/startup fails.

            // Unity writes latest info every frame; here we access LocationService directly.
            var info = Input.location.lastData;
            if (!info.timestamp.Equals(0))
            {
                var current = ToDomainModel(info);
                CacheLocation(current);
                return current;
            }

            return _lastLocation;
        }

        /// <inheritdoc/>
        public void StartContinuousUpdates()
        {
            lock (_syncRoot)
            {
                if (_pollingLoop is { IsCompleted: false }) return; // Already running
                _pollingLoop = Task.Run(() => PollingLoopAsync(_cts.Token), _cts.Token);
            }
        }

        /// <inheritdoc/>
        public void StopContinuousUpdates()
        {
            lock (_syncRoot)
            {
                _cts.Cancel();
                _pollingLoop = null;
            }
        }

        // ----------------------------------------------------------------------------------------------------------------
        // Internal logic
        // ----------------------------------------------------------------------------------------------------------------
        private async Task<bool> EnsureServiceStartedAsync(CancellationToken token)
        {
            if (Input.location.status is LocationServiceStatus.Running)
                return true;

            // 1) Ask for permission if needed.
#if UNITY_ANDROID
            if (!Permission.HasUserAuthorizedPermission(Permission.FineLocation))
            {
                Permission.RequestUserPermission(Permission.FineLocation);
                // Wait a brief moment for user response. For production you may show a dedicated UI flow.
                await Task.Delay(TimeSpan.FromSeconds(1), token).ConfigureAwait(false);

                if (!Permission.HasUserAuthorizedPermission(Permission.FineLocation))
                    return false; // Denied.
            }
#elif UNITY_IOS
            // iOS automatically prompts on first use; status will indicate afterwards.
#endif

            // 2) (Re)start the service.  Use low power for economic simulation; we do not need meter-level precision.
            if (Input.location.status is LocationServiceStatus.Stopped or LocationServiceStatus.Failed)
                Input.location.Start(desiredAccuracyInMeters: 500, updateDistanceInMeters: 500);

            // Wait until service has initialised or cancelled.
            var startTime = _clock.UtcNow;
            while (Input.location.status is LocationServiceStatus.Initializing && !token.IsCancellationRequested)
            {
                // Time-out after 10s to preserve player experience.
                if (_clock.UtcNow - startTime > TimeSpan.FromSeconds(10))
                    return false;

                await Task.Delay(250, token).ConfigureAwait(false);
            }

            return Input.location.status is LocationServiceStatus.Running;
        }

        private async Task PollingLoopAsync(CancellationToken token)
        {
            // Note: This code runs on a background thread.  Do NOT call any Unity API other than LocationService.
            // (Unity's LocationService is thread-safe.)
            while (!token.IsCancellationRequested)
            {
                try
                {
                    var coord = await GetCurrentLocationAsync(token).ConfigureAwait(false);
                    if (coord is not null)
                    {
                        // Push event to observers.
                        LocationUpdated?.Invoke(this, coord);

                        // Fire-and-forget analytics.
                        _analytics.TrackEvent("location_update",
                                              new { lat = coord.Latitude, lon = coord.Longitude });
                    }
                }
                catch (OperationCanceledException)
                {
                    // Graceful shutdown.
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[Location] Polling loop error: {ex}");
                    _analytics.TrackException(ex);
                }

                await Task.Delay(_updateInterval, token).ConfigureAwait(false);
            }
        }

        private static GeoCoordinate ToDomainModel(LocationInfo info)
        {
            return new GeoCoordinate
            {
                Latitude   = info.latitude,
                Longitude  = info.longitude,
                Timestamp  = DateTimeOffset.FromUnixTimeSeconds((long)info.timestamp)
            };
        }

        private void CacheLocation(GeoCoordinate coordinate)
        {
            _lastLocation = coordinate;

            // Persist to PlayerPrefs (quick & lightweight for small data).
            PlayerPrefs.SetString(LastLatitudeKey,  coordinate.Latitude.ToString(CultureInfo.InvariantCulture));
            PlayerPrefs.SetString(LastLongitudeKey, coordinate.Longitude.ToString(CultureInfo.InvariantCulture));
            PlayerPrefs.SetString(LastTimestampKey, coordinate.Timestamp.ToUnixTimeSeconds().ToString(CultureInfo.InvariantCulture));
            PlayerPrefs.Save();
        }

        private void LoadLastKnownLocation()
        {
            if (!PlayerPrefs.HasKey(LastLatitudeKey) || !PlayerPrefs.HasKey(LastLongitudeKey))
                return;

            if (!double.TryParse(PlayerPrefs.GetString(LastLatitudeKey),  NumberStyles.Any, CultureInfo.InvariantCulture, out var lat) ||
                !double.TryParse(PlayerPrefs.GetString(LastLongitudeKey), NumberStyles.Any, CultureInfo.InvariantCulture, out var lon))
            {
                return;
            }

            long.TryParse(PlayerPrefs.GetString(LastTimestampKey), NumberStyles.Any, CultureInfo.InvariantCulture, out var ts);

            _lastLocation = new GeoCoordinate
            {
                Latitude   = lat,
                Longitude  = lon,
                Timestamp  = ts == 0
                                ? _clock.UtcNow
                                : DateTimeOffset.FromUnixTimeSeconds(ts)
            };
        }

        // ----------------------------------------------------------------------------------------------------------------
        // IDisposable
        // ----------------------------------------------------------------------------------------------------------------
        public void Dispose()
        {
            StopContinuousUpdates();
            _cts.Dispose();
            if (Input.location.status is LocationServiceStatus.Running)
                Input.location.Stop();
        }
    }
}
```