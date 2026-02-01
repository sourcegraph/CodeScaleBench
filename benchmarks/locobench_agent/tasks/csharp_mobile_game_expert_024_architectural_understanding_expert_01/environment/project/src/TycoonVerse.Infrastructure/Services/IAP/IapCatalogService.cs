```csharp
// File: TycoonVerse/src/TycoonVerse.Infrastructure/Services/IAP/IapCatalogService.cs

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace TycoonVerse.Infrastructure.Services.IAP
{
    #region Public Contracts

    /// <summary>
    /// Abstraction that exposes the immutable list of IAP products
    /// configured for the current build/tenant/region combination.
    /// The catalog is automatically refreshed from the backend and
    /// persisted locally so that the game can work fully offline.
    /// </summary>
    public interface IIapCatalogService : IAsyncDisposable
    {
        /// <summary>
        /// Raised every time a new catalog is loaded (either from
        /// remote backend or local storage).
        /// </summary>
        event EventHandler<CatalogUpdatedEventArgs>? CatalogUpdated;

        /// <summary>Loads catalog from storage or backend.</summary>
        Task InitializeAsync(CancellationToken ct = default);

        /// <summary>Returns all products currently cached.</summary>
        ValueTask<IReadOnlyCollection<IapProduct>> GetProductsAsync(CancellationToken ct = default);

        /// <summary>Returns a single product by its ID, or <c>null</c> if it does not exist.</summary>
        ValueTask<IapProduct?> GetProductAsync(string productId, CancellationToken ct = default);

        /// <summary>Forces a re-download from backend and persists the new catalog.</summary>
        Task RefreshAsync(bool force = false, CancellationToken ct = default);
    }

    /// <summary>
    /// Immutable representation of an in-app product configured on the platform store.
    /// </summary>
    /// <param name="Id">Unique identifier used by the platform store (SKU).</param>
    /// <param name="Title">Localized title.</param>
    /// <param name="Description">Localized description.</param>
    /// <param name="Price">Numeric price in the store’s minor units.</param>
    /// <param name="Currency">ISO-4217 currency code.</param>
    /// <param name="IsConsumable">Flag indicating if the item can be purchased multiple times.</param>
    public sealed record IapProduct(
        string Id,
        string Title,
        string Description,
        long Price,
        string Currency,
        bool IsConsumable);

    /// <summary>Event payload for <see cref="IIapCatalogService.CatalogUpdated"/>.</summary>
    public sealed class CatalogUpdatedEventArgs : EventArgs
    {
        internal CatalogUpdatedEventArgs(IReadOnlyCollection<IapProduct> catalog) => Catalog = catalog;
        public IReadOnlyCollection<IapProduct> Catalog { get; }
    }

    #endregion

    #region Concrete Service

    /// <summary>
    /// Production-grade implementation that performs the following:
    ///  • Attempts to load the last known catalog from local storage.
    ///  • Transparently re-downloads from the backend when a configured
    ///    refresh interval has elapsed (or when explicitly forced).
    ///  • Keeps an in-memory cache for fast look-ups.
    ///  • Notifies the rest of the app whenever a new catalog is available.
    ///  • Designed with full offline resiliency in mind.
    /// </summary>
    public sealed class IapCatalogService : IIapCatalogService
    {
        private const string LocalFileName = "iap_catalog.json";
        private static readonly JsonSerializerOptions _jsonOptions = new() { WriteIndented = false };

        private readonly HttpClient _httpClient;
        private readonly ILogger<IapCatalogService> _logger;
        private readonly SemaphoreSlim _gate = new(1, 1);
        private readonly Uri _remoteEndpoint;
        private readonly TimeSpan _refreshInterval;
        private readonly string _persistencePath;

        private IReadOnlyDictionary<string, IapProduct>? _catalog;
        private DateTimeOffset _lastDownloadedAt;

        public event EventHandler<CatalogUpdatedEventArgs>? CatalogUpdated;

        public IapCatalogService(
            Uri remoteEndpoint,
            TimeSpan refreshInterval,
            HttpClient httpClient,
            ILogger<IapCatalogService> logger)
        {
            _remoteEndpoint   = remoteEndpoint    ?? throw new ArgumentNullException(nameof(remoteEndpoint));
            _refreshInterval  = refreshInterval   != default ? refreshInterval : TimeSpan.FromHours(12);
            _httpClient       = httpClient        ?? throw new ArgumentNullException(nameof(httpClient));
            _logger           = logger            ?? throw new ArgumentNullException(nameof(logger));

            // Respect Unity’s persistent path if available, otherwise revert to local app-data folder.
#if UNITY_2022_1_OR_NEWER
            _persistencePath = Path.Combine(UnityEngine.Application.persistentDataPath, LocalFileName);
#else
            _persistencePath = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "TycoonVerse",
                LocalFileName);
            Directory.CreateDirectory(Path.GetDirectoryName(_persistencePath)!);
#endif
        }

        #region IIapCatalogService

        public async Task InitializeAsync(CancellationToken ct = default)
        {
            _logger.LogInformation("Initializing IAP catalog service …");

            // 1) Load from disk (if present). We do it first to enable offline play.
            await LoadFromDiskAsync(ct).ConfigureAwait(false);

            // 2) Immediately try a background refresh (non-blocking).
            _ = Task.Run(() => RefreshAsync(force: false, ct), ct);
        }

        public async ValueTask<IReadOnlyCollection<IapProduct>> GetProductsAsync(CancellationToken ct = default)
        {
            await EnsureInitializedAsync(ct).ConfigureAwait(false);
            return _catalog!.Values; // Safe due to EnsureInitializedAsync
        }

        public async ValueTask<IapProduct?> GetProductAsync(string productId, CancellationToken ct = default)
        {
            if (string.IsNullOrWhiteSpace(productId))
                throw new ArgumentException("Value cannot be null or whitespace.", nameof(productId));

            await EnsureInitializedAsync(ct).ConfigureAwait(false);

            _catalog!.TryGetValue(productId, out var product);
            return product;
        }

        public async Task RefreshAsync(bool force = false, CancellationToken ct = default)
        {
            var mustRefresh = force || (DateTimeOffset.UtcNow - _lastDownloadedAt) >= _refreshInterval;
            if (!mustRefresh) return;

            await _gate.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                // Re-check condition after acquiring lock.
                mustRefresh = force || (DateTimeOffset.UtcNow - _lastDownloadedAt) >= _refreshInterval;
                if (!mustRefresh) return;

                _logger.LogInformation("Fetching latest IAP catalog from {Endpoint}", _remoteEndpoint);

                using var response = await _httpClient.GetAsync(_remoteEndpoint, ct).ConfigureAwait(false);
                response.EnsureSuccessStatusCode();

                var json = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
                var freshCatalog = JsonSerializer.Deserialize<List<IapProduct>>(json, _jsonOptions)
                                   ?? throw new InvalidDataException("Received empty IAP catalog.");

                UpdateCache(freshCatalog);
                await SaveToDiskAsync(ct).ConfigureAwait(false);

                CatalogUpdated?.Invoke(this, new CatalogUpdatedEventArgs(freshCatalog));
            }
            catch (OperationCanceledException)
            {
                throw; // Let caller decide what to do.
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Unable to download IAP catalog.");
                // Intentionally swallow exception so that game keeps running with stale catalog.
            }
            finally
            {
                _gate.Release();
            }
        }

        public async ValueTask DisposeAsync()
        {
            _gate.Dispose();
            _httpClient.Dispose();
            await Task.CompletedTask;
        }

        #endregion

        #region Internal Helpers

        /// <summary>
        /// Guarantees that the catalog has been hydrated either from disk
        /// or remote backend before serving any read operation.
        /// </summary>
        private async Task EnsureInitializedAsync(CancellationToken ct)
        {
            if (_catalog is not null) return;

            await _gate.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                if (_catalog is null) // Double-check under lock
                    await LoadFromDiskAsync(ct).ConfigureAwait(false);
            }
            finally
            {
                _gate.Release();
            }
        }

        private void UpdateCache(IEnumerable<IapProduct> freshCatalog)
        {
            _catalog = new ConcurrentDictionary<string, IapProduct>(
                freshCatalog is List<IapProduct> list
                    ? list.ToDictionary(p => p.Id, p => p, StringComparer.Ordinal)
                    : new Dictionary<string, IapProduct>(StringComparer.Ordinal));

            _lastDownloadedAt = DateTimeOffset.UtcNow;
            _logger.LogInformation("IAP catalog updated with {Count} products.", _catalog!.Count);
        }

        #endregion

        #region Persistence

        private async Task LoadFromDiskAsync(CancellationToken ct)
        {
            if (!File.Exists(_persistencePath))
            {
                _logger.LogDebug("No local IAP catalog found at {Path}.", _persistencePath);
                return;
            }

            try
            {
                await using var fs = File.OpenRead(_persistencePath);
                var storedCatalog = await JsonSerializer
                    .DeserializeAsync<List<IapProduct>>(fs, _jsonOptions, ct)
                    .ConfigureAwait(false);

                if (storedCatalog is { Count: > 0 })
                {
                    UpdateCache(storedCatalog);
                    _logger.LogInformation("Loaded IAP catalog from disk (last saved {Timestamp}).",
                        File.GetLastWriteTimeUtc(_persistencePath));
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to load IAP catalog from local storage. Will re-download.");
            }
        }

        private async Task SaveToDiskAsync(CancellationToken ct)
        {
            try
            {
                await using var fs = File.Create(_persistencePath);
                await JsonSerializer.SerializeAsync(fs, _catalog!.Values, _jsonOptions, ct).ConfigureAwait(false);

                _logger.LogDebug("Persisted IAP catalog to {Path}.", _persistencePath);
            }
            catch (Exception ex)
            {
                // Non-critical: keep application running even if we can't save.
                _logger.LogWarning(ex, "Failed to persist IAP catalog to disk.");
            }
        }

        #endregion
    }

    #endregion
}
```