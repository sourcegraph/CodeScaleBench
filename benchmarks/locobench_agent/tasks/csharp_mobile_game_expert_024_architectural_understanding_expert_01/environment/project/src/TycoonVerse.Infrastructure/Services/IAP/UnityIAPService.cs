```csharp
// File: TycoonVerse/src/TycoonVerse.Infrastructure/Services/IAP/UnityIAPService.cs

using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using UnityEngine;
using UnityEngine.Purchasing;
using UnityEngine.Purchasing.Extension;

namespace TycoonVerse.Infrastructure.Services.IAP
{
    /// <summary>
    ///     Immutable information about a purchasable product.
    /// </summary>
    public sealed record IAPProduct(
        string Id,
        ProductType Type,
        decimal LocalizedPrice,
        string LocalizedTitle,
        string LocalizedDescription,
        string IsoCurrencyCode);

    /// <summary>
    ///     Result container for any purchase flow.
    /// </summary>
    public sealed class PurchaseResult
    {
        private PurchaseResult(bool success, string productId, string transactionId, string receipt, IAPError? error)
        {
            Success       = success;
            ProductId     = productId;
            TransactionId = transactionId;
            Receipt       = receipt;
            Error         = error;
        }

        public bool      Success       { get; }
        public string    ProductId     { get; }
        public string    TransactionId { get; }
        public string    Receipt       { get; }
        public IAPError? Error         { get; }

        public static PurchaseResult Succeeded(Product product) =>
            new(true, product.definition.id, product.transactionID, product.receipt, null);

        public static PurchaseResult Failed(string productId, IAPError error) =>
            new(false, productId, string.Empty, string.Empty, error);
    }

    /// <summary>
    ///     User-facing error codes distilled from the underlying store-specific codes.
    /// </summary>
    public enum IAPError
    {
        Unknown               = 0,
        InitializationFailure = 1,
        NetworkError          = 2,
        ProductUnavailable    = 3,
        PaymentDeclined       = 4,
        UserCancelled         = 5,
        AlreadyOwned          = 6
    }

    /// <summary>
    ///     Public contract consumed by game systems that need to initiate or observe purchases.
    /// </summary>
    public interface IIAPService
    {
        bool IsInitialized { get; }
        bool IsPurchaseInProgress { get; }

        Task InitializeAsync(CancellationToken token = default);
        Task<PurchaseResult> PurchaseAsync(string productId, CancellationToken token = default);
        Task RestorePurchasesAsync(CancellationToken token = default);
        IReadOnlyCollection<IAPProduct> GetAvailableProducts();

        event Action<PurchaseResult> OnPurchaseCompleted;
        event Action<IAPError>       OnPurchaseFailed;
    }

    /// <summary>
    ///     Production-grade implementation of <see cref="IIAPService"/> backed by Unity’s
    ///     <see cref="UnityEngine.Purchasing"/> subsystem.  This class is intentionally resilient
    ///     to network blips and double-tap purchases and is thread-safe where required.
    /// </summary>
    public sealed class UnityIAPService : IIAPService, IStoreListener
    {
        private readonly ILogger<UnityIAPService> _logger;
        private readonly IAPCatalogProvider      _catalogProvider;      // Wraps remote/static catalog
        private readonly IAnalyticsService?      _analytics;            // Optional (can be null)

        private IStoreController? _storeController;
        private IExtensionProvider? _extensionProvider;

        private TaskCompletionSource<bool>?        _initializationTcs;
        private TaskCompletionSource<PurchaseResult>? _purchaseTcs;
        private TaskCompletionSource<bool>?        _restoreTcs;

        private volatile bool _isInitializing;
        private readonly object _syncRoot = new();

        #region Ctor / DI

        public UnityIAPService(
            ILogger<UnityIAPService> logger,
            IAPCatalogProvider catalogProvider,
            IAnalyticsService? analytics = null)
        {
            _logger          = logger;
            _catalogProvider = catalogProvider ?? throw new ArgumentNullException(nameof(catalogProvider));
            _analytics       = analytics;
        }

        #endregion

        #region IIAPService

        public bool IsInitialized => _storeController != null && _extensionProvider != null;
        public bool IsPurchaseInProgress => _purchaseTcs is { Task.IsCompleted: false };

        public event Action<PurchaseResult>? OnPurchaseCompleted;
        public event Action<IAPError>?       OnPurchaseFailed;

        /// <summary>
        ///     Initializes the underlying IAP SDK if not already done.  Multiple callers may await
        ///     the same initialization operation without triggering duplicate work.
        /// </summary>
        public async Task InitializeAsync(CancellationToken token = default)
        {
            if (IsInitialized) return;

            lock (_syncRoot)
            {
                if (_isInitializing) goto AwaitInitialization;

                _isInitializing  = true;
                _initializationTcs = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);

                // Build the configuration from the catalog provider
                var builder = ConfigurationBuilder.Instance(StandardPurchasingModule.Instance());
                foreach (var catalogItem in _catalogProvider.GetCatalog())
                {
                    builder.AddProduct(
                        catalogItem.Id,
                        catalogItem.Type,
                        catalogItem.Payouts is { Length: > 0 } ? catalogItem.Payouts : null);
                }

                UnityPurchasing.Initialize(this, builder);
            }

        AwaitInitialization:
            using (token.Register(() => _initializationTcs?.TrySetCanceled()))
            {
                await _initializationTcs!.Task.ConfigureAwait(false);
            }
        }

        /// <summary>
        ///     Starts a purchase flow for the requested product.  The returned task completes when
        ///     the store finishes processing.  Only one purchase may be in-flight at any moment.
        /// </summary>
        public async Task<PurchaseResult> PurchaseAsync(string productId, CancellationToken token = default)
        {
            if (string.IsNullOrWhiteSpace(productId))
                throw new ArgumentException("Product id is required", nameof(productId));

            if (!IsInitialized)
                throw new InvalidOperationException("IAP Service is not initialized.");

            lock (_syncRoot)
            {
                if (IsPurchaseInProgress)
                    throw new InvalidOperationException("Another purchase is currently in progress.");

                _purchaseTcs = new TaskCompletionSource<PurchaseResult>(TaskCreationOptions.RunContinuationsAsynchronously);
            }

            Product? product = _storeController!.products.WithID(productId);
            if (product is null || !product.availableToPurchase)
            {
                var unavailable = PurchaseResult.Failed(productId, IAPError.ProductUnavailable);
                _purchaseTcs.TrySetResult(unavailable);
                return unavailable;
            }

            try
            {
                _logger.LogInformation("Initiating purchase for '{ProductId}'", productId);
                _storeController.InitiatePurchase(product);

                using (token.Register(() => _purchaseTcs!.TrySetCanceled()))
                {
                    return await _purchaseTcs.Task.ConfigureAwait(false);
                }
            }
            finally
            {
                lock (_syncRoot) _purchaseTcs = null;
            }
        }

        /// <summary>
        ///     Platform-specific restore (Apple) or re-fetch of previously purchased non-consumables.
        /// </summary>
        public async Task RestorePurchasesAsync(CancellationToken token = default)
        {
            if (!IsInitialized)
                throw new InvalidOperationException("IAP Service is not initialized.");

            // Google Play automatically restores; only call on Apple.
            var appleExt = _extensionProvider!.GetExtension<IAppleExtensions>();
            if (appleExt is null)
            {
                _logger.LogWarning("RestorePurchases called on a non-Apple platform; ignoring.");
                return;
            }

            lock (_syncRoot)
            {
                _restoreTcs = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            }

            _logger.LogInformation("Requesting transaction restore from Apple.");
            appleExt.RestoreTransactions(success =>
            {
                _logger.LogInformation("Apple restore finished. Success={Success}", success);
                _restoreTcs!.TrySetResult(success);
            });

            using (token.Register(() => _restoreTcs!.TrySetCanceled()))
            {
                await _restoreTcs.Task.ConfigureAwait(false);
            }
        }

        public IReadOnlyCollection<IAPProduct> GetAvailableProducts()
        {
            if (!IsInitialized)
                return Array.Empty<IAPProduct>();

            return _storeController!.products.all
                .Select(p => new IAPProduct(
                    p.definition.id,
                    p.definition.type,
                    Convert.ToDecimal(p.metadata.localizedPrice),
                    p.metadata.localizedTitle,
                    p.metadata.localizedDescription,
                    p.metadata.isoCurrencyCode))
                .ToArray();
        }

        #endregion

        #region IStoreListener

        void IStoreListener.OnInitialized(IStoreController controller, IExtensionProvider extensions)
        {
            _logger.LogInformation("Unity IAP successfully initialized with {ProductCount} products.",
                                   controller.products.all.Length);

            _storeController   = controller;
            _extensionProvider = extensions;

            _initializationTcs!.TrySetResult(true);
        }

        void IStoreListener.OnInitializeFailed(InitializationFailureReason reason)
        {
            _logger.LogError("Unity IAP initialization failed: {Reason}", reason);
            _initializationTcs!.TrySetException(MapInitializationError(reason));
        }

        PurchaseProcessingResult IStoreListener.ProcessPurchase(PurchaseEventArgs e)
        {
            var result = PurchaseResult.Succeeded(e.purchasedProduct);
            _logger.LogInformation("Purchase completed successfully for '{ProductId}' (Txn: {Txn}).",
                                   result.ProductId, result.TransactionId);

            _purchaseTcs?.TrySetResult(result);
            OnPurchaseCompleted?.Invoke(result);

            _analytics?.TrackIapPurchase(result);

            // Return Complete for consumables; Pending for server receipt validation (not implemented yet)
            return PurchaseProcessingResult.Complete;
        }

        void IStoreListener.OnPurchaseFailed(Product product, PurchaseFailureReason failureReason)
        {
            var error = MapPurchaseError(failureReason);
            _logger.LogWarning("Purchase failed. Product={ProductId} Reason={Reason}", product.definition.id, failureReason);

            var result = PurchaseResult.Failed(product.definition.id, error);
            _purchaseTcs?.TrySetResult(result);
            OnPurchaseFailed?.Invoke(error);
        }

        #endregion

        #region Mapping Helpers

        private static Exception MapInitializationError(InitializationFailureReason reason) =>
            reason switch
            {
                InitializationFailureReason.AppNotKnown =>
                    new InvalidOperationException("App is not correctly configured in store dashboard."),
                InitializationFailureReason.PurchasingUnavailable =>
                    new InvalidOperationException("Purchasing is disabled on this platform/device."),
                InitializationFailureReason.NoProductsAvailable =>
                    new InvalidOperationException("No purchasable products were found."),
                InitializationFailureReason.Unknown =>
                    new InvalidOperationException("Unknown initialization error."),
                _ => new InvalidOperationException($"Initialization failed: {reason}.")
            };

        private static IAPError MapPurchaseError(PurchaseFailureReason reason) =>
            reason switch
            {
                PurchaseFailureReason.PurchasingUnavailable => IAPError.NetworkError,
                PurchaseFailureReason.ExistingPurchasePending => IAPError.AlreadyOwned,
                PurchaseFailureReason.ProductUnavailable     => IAPError.ProductUnavailable,
                PurchaseFailureReason.DuplicateTransaction   => IAPError.AlreadyOwned,
                PurchaseFailureReason.PaymentDeclined        => IAPError.PaymentDeclined,
                PurchaseFailureReason.UserCancelled          => IAPError.UserCancelled,
                _                                            => IAPError.Unknown
            };

        #endregion
    }

    #region Infrastructure Support Interfaces / Models

    /// <summary>
    ///     Domain-specific wrapper that provides our remote/static catalog to the IAP service.
    ///     It can be implemented over JSON, ScriptableObjects, or a CMS.
    /// </summary>
    public interface IAPCatalogProvider
    {
        IEnumerable<CatalogItem> GetCatalog();
    }

    /// <summary>
    ///     DTO for catalog items.
    /// </summary>
    public sealed record CatalogItem(
        string Id,
        ProductType Type,
        PayoutDefinition[]? Payouts);

    /// <summary>
    ///     Cross-cutting analytics abstraction used throughout TycoonVerse.
    /// </summary>
    public interface IAnalyticsService
    {
        void TrackIapPurchase(PurchaseResult result);
    }

    #endregion
}
```