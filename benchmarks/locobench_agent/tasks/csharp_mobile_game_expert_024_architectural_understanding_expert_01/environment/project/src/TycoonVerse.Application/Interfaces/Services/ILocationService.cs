```csharp
// File: TycoonVerse/src/TycoonVerse.Application/Interfaces/Services/ILocationService.cs
// Project: TycoonVerse – Enterprise Empire Simulator (Mobile Game)
// Copyright © 2024 TycoonVerse
//
// NOTE: This file lives in the Application layer.  It exposes contracts that are
// consumed by View-Models, Use-Cases, and other application services while being
// completely agnostic of concrete platform APIs (Android/iOS/Editor).

#nullable enable

using System;
using System.Threading;
using System.Threading.Tasks;

namespace TycoonVerse.Application.Interfaces.Services
{
    /// <summary>
    /// Provides a domain-focused abstraction over platform-specific location/GPS services.
    /// The service is expected to:
    ///   • Operate offline and reconcile when connectivity resumes.
    ///   • Emit real-time geo-coordinates for in-game pricing events.
    ///   • Handle permission lifecycles gracefully to avoid soft-crashes.
    /// </summary>
    public interface ILocationService : IDisposable
    {
        /// <summary>
        /// Current operational state of the service.
        /// </summary>
        LocationStatus Status { get; }

        /// <summary>
        /// Reactive push stream that publishes location updates
        /// whenever <see cref="LocationSnapshot.Coordinate"/> changes by
        /// the specified <paramref name="desiredAccuracy"/> or when
        /// <paramref name="minInterval"/> elapses—whichever comes first.
        /// </summary>
        /// <param name="desiredAccuracy">
        ///     The accuracy threshold in meters that must be met before
        ///     emitting a new coordinate.
        /// </param>
        /// <param name="minInterval">
        ///     Minimum time interval between two consecutive updates.
        /// </param>
        /// <param name="token">Cancellation token.</param>
        /// <returns>An observable stream of <see cref="LocationSnapshot"/>.</returns>
        IObservable<LocationSnapshot> StartTracking(
            GeoAccuracy desiredAccuracy,
            TimeSpan minInterval,
            CancellationToken token = default);

        /// <summary>
        /// Stops the active tracking session (if any). Subscribers to the observable
        /// returned by <see cref="StartTracking"/> will receive <c>OnCompleted</c>.
        /// </summary>
        Task StopTrackingAsync(CancellationToken token = default);

        /// <summary>
        /// Retrieves the most recently cached location snapshot if available.
        /// </summary>
        /// <remarks>
        ///     The implementation MUST NOT perform a fresh GPS lookup to keep
        ///     the method lightweight and side-effect free.
        /// </remarks>
        /// <returns>
        ///     The last known <see cref="LocationSnapshot"/>, or <c>null</c> if unknown.
        /// </returns>
        Task<LocationSnapshot?> GetLastKnownLocationAsync(CancellationToken token = default);

        /// <summary>
        /// Resolves the user's current geo-region (country, state, currency, etc.)
        /// without starting continuous tracking.
        /// </summary>
        Task<GeoRegion?> ResolveCurrentRegionAsync(CancellationToken token = default);

        /// <summary>
        /// Calculates a price modifier (surge/discount) for the given commodity
        /// based on the specified <paramref name="region"/>.
        /// </summary>
        /// <remarks>
        ///     The algorithm may factor in local taxes, climate events, or
        ///     supply-chain disruptions simulated by the game.
        /// </remarks>
        /// <param name="commodityId">Canonical identifier of the commodity.</param>
        /// <param name="region">Geo-region previously obtained from <see cref="ResolveCurrentRegionAsync"/>.</param>
        /// <returns>A multiplier (e.g., 1.25m for +25% surge).</returns>
        decimal GetRegionalPriceModifier(string commodityId, GeoRegion region);

        /// <summary>
        /// Requests fine-grained location permission from the user.
        /// The call is idempotent; repeated invocations return the cached result.
        /// </summary>
        /// <returns>
        ///     The resolved <see cref="LocationStatus"/> post-permission request.
        /// </returns>
        Task<LocationStatus> RequestPermissionAsync(CancellationToken token = default);

        /// <summary>
        /// Event raised whenever a new <see cref="LocationSnapshot"/> is published
        /// on the <see cref="StartTracking"/> stream.
        /// </summary>
        event EventHandler<LocationChangedEventArgs>? LocationChanged;
    }

    #region Domain-centric Supporting Types

    /// <summary>
    /// Snapshot containing a geo-coordinate, its accuracy, and a UTC timestamp.
    /// </summary>
    /// <param name="Coordinate">Latitude/Longitude (and optional altitude).</param>
    /// <param name="Accuracy">Expected accuracy in meters.</param>
    /// <param name="TimestampUtc">UTC time of measurement.</param>
    public sealed record LocationSnapshot(
        GeoCoordinate Coordinate,
        double Accuracy,
        DateTimeOffset TimestampUtc);

    /// <summary>
    /// Lightweight value object representing global coordinates.
    /// </summary>
    /// <param name="Latitude">Degrees latitude (-90 .. 90).</param>
    /// <param name="Longitude">Degrees longitude (-180 .. 180).</param>
    /// <param name="AltitudeMeters">Optional altitude above sea level.</param>
    public sealed record GeoCoordinate(
        double Latitude,
        double Longitude,
        double AltitudeMeters = 0);

    /// <summary>
    /// Human-readable geo-region used for price localization.
    /// </summary>
    /// <param name="CountryCode">ISO-3166 alpha-2.</param>
    /// <param name="RegionCode">State / province / prefecture code.</param>
    /// <param name="City">City or locality.</param>
    /// <param name="IsoCurrencyCode">ISO-4217 currency for local transactions.</param>
    public sealed record GeoRegion(
        string CountryCode,
        string RegionCode,
        string City,
        string IsoCurrencyCode);

    /// <summary>
    /// Status codes for the life-cycle of the location service.
    /// </summary>
    public enum LocationStatus
    {
        /// <summary>Location functionality is unavailable on the device.</summary>
        Unavailable = 0,

        /// <summary>User denied permission or system policy blocks usage.</summary>
        PermissionDenied,

        /// <summary>Service initializing or awaiting first location fix.</summary>
        Initializing,

        /// <summary>Actively tracking and emitting positions.</summary>
        Running,

        /// <summary>An unrecoverable error occurred; see logs.</summary>
        Faulted
    }

    /// <summary>
    /// Desired accuracy levels recognized by the application.  Implementations
    /// map these to platform-specific numeric values (e.g., Android FusedLocation
    /// or CoreLocation on iOS).
    /// </summary>
    public enum GeoAccuracy
    {
        Low = 0,
        Medium = 1,
        High = 2,
        Best = 3
    }

    /// <summary>
    /// Event data delivered with <see cref="ILocationService.LocationChanged"/>.
    /// </summary>
    public sealed class LocationChangedEventArgs : EventArgs
    {
        public LocationChangedEventArgs(LocationSnapshot snapshot) =>
            Snapshot = snapshot ?? throw new ArgumentNullException(nameof(snapshot));

        public LocationSnapshot Snapshot { get; }
    }

    #endregion
}
```