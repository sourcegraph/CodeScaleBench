```csharp
// File: TycoonVerse/src/TycoonVerse.Unity/Assets/Scripts/ViewModels/IAPStoreViewModel.cs

using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using TycoonVerse.Domain.InAppPurchase;
using TycoonVerse.Domain.Telemetry;
using TycoonVerse.Infrastructure.CrashReporting;
using TycoonVerse.Unity.Extensions;
using UniRx;
using UnityEngine;

/// <summary>
/// View-Model responsible for exposing Unity-side bindings for the In-App-Purchase store.
/// Encapsulates product catalog state, purchase pipeline, analytics hooks and error handling.
/// </summary>
namespace TycoonVerse.Unity.ViewModels
{
    public sealed class IAPStoreViewModel : IDisposable
    {
        private const string LogCategory = "[IAP-Store-VM]";

        private readonly IInAppPurchaseService      _iapService;
        private readonly IAnalyticsService          _analyticsService;
        private readonly ICrashReporter             _crashReporter;
        private readonly IDispatcher                _dispatcher;           // Guarantees UI-thread marshalling
        private readonly CompositeDisposable        _disposables = new();

        private readonly ReactiveProperty<bool>     _isBusy        = new(false);
        private readonly ReactiveProperty<bool>     _isInitialized = new(false);
        private readonly ReactiveCollection<StoreProductViewModel> _products = new();

        public IReadOnlyReactiveProperty<bool>                 IsBusy        => _isBusy;
        public IReadOnlyReactiveProperty<bool>                 IsInitialized => _isInitialized;
        public IReadOnlyReactiveCollection<StoreProductViewModel> Products   => _products;

        #region Construction & Lifetime

        public IAPStoreViewModel(
            IInAppPurchaseService iapService,
            IAnalyticsService analyticsService,
            ICrashReporter crashReporter,
            IDispatcher dispatcher)
        {
            _iapService        = iapService  ?? throw new ArgumentNullException(nameof(iapService));
            _analyticsService  = analyticsService ?? throw new ArgumentNullException(nameof(analyticsService));
            _crashReporter     = crashReporter ?? throw new ArgumentNullException(nameof(crashReporter));
            _dispatcher        = dispatcher ?? throw new ArgumentNullException(nameof(dispatcher));

            // Wire up analytics for successful purchases
            _iapService.OnPurchaseSucceeded
                       .ObserveOnMainThread()
                       .Subscribe(OnPurchaseSucceeded)
                       .AddTo(_disposables);

            // Wire up error stream
            _iapService.OnPurchaseFailed
                       .ObserveOnMainThread()
                       .Subscribe(OnPurchaseFailed)
                       .AddTo(_disposables);
        }

        public void Dispose()
        {
            _disposables.Dispose();
        }

        #endregion

        #region Public API

        /// <summary>
        /// Initializes the IAP service and populates the product catalog.
        /// Safe to call multiple times; redundant calls are ignored.
        /// </summary>
        public async Task InitializeAsync(CancellationToken ct = default)
        {
            if (_isInitialized.Value || _isBusy.Value) return;

            _isBusy.Value = true;
            try
            {
                await _iapService.InitializeAsync(ct).ConfigureAwait(false);
                await FetchCatalogAsync(ct).ConfigureAwait(false);

                _isInitialized.Value = true;
                _analyticsService.TrackEvent(AnalyticsEvent.IapStoreInitialized);
            }
            catch (OperationCanceledException)
            {
                // ignore – shutdown or user-cancelled
            }
            catch (Exception ex)
            {
                Debug.LogError($"{LogCategory} initialization failed: {ex}");
                _crashReporter.ReportNonFatal(ex);
                _analyticsService.TrackEvent(AnalyticsEvent.IapStoreInitFailed,
                    new Dictionary<string, object> { { "exception", ex.GetType().Name } });
            }
            finally
            {
                _isBusy.Value = false;
            }
        }

        /// <summary>
        /// Begins a purchase flow for the supplied product id.
        /// </summary>
        public async Task PurchaseAsync(string productId, CancellationToken ct = default)
        {
            if (string.IsNullOrEmpty(productId))
                throw new ArgumentException("Invalid product id.", nameof(productId));

            if (_isBusy.Value)
                return;

            var productVm = _products.FirstOrDefault(p => p.Id == productId);
            if (productVm == null)
            {
                Debug.LogWarning($"{LogCategory} Attempted to purchase unknown product: {productId}");
                return;
            }

            _isBusy.Value = true;
            try
            {
                _analyticsService.TrackEvent(AnalyticsEvent.IapPurchaseStarted, 
                    new Dictionary<string, object> { { "product_id", productId } });

                await _iapService.PurchaseAsync(productId, ct).ConfigureAwait(false);
                // On success, IAP service will trigger OnPurchaseSucceeded handler.
            }
            catch (OperationCanceledException)
            {
                _analyticsService.TrackEvent(AnalyticsEvent.IapPurchaseCancelled, 
                    new Dictionary<string, object> { { "product_id", productId } });
            }
            catch (Exception ex)
            {
                _analyticsService.TrackEvent(AnalyticsEvent.IapPurchaseFailed, 
                    new Dictionary<string, object> 
                    { 
                        { "product_id", productId },
                        { "exception", ex.GetType().Name }
                    });
                _crashReporter.ReportNonFatal(ex);
            }
            finally
            {
                _isBusy.Value = false;
            }
        }

        #endregion

        #region Private helpers

        private async Task FetchCatalogAsync(CancellationToken ct)
        {
            var catalog = await _iapService.FetchAvailableProductsAsync(ct).ConfigureAwait(false);

            await _dispatcher.SwitchToMainThread(ct); // Ensure we touch reactive collection on main-thread
            _products.Clear();

            foreach (var p in catalog.OrderBy(c => c.SortOrder))
            {
                var vm = new StoreProductViewModel(p);
                _products.Add(vm);
            }
        }

        private void OnPurchaseSucceeded(PurchaseReceipt receipt)
        {
            var productVm = _products.FirstOrDefault(p => p.Id == receipt.ProductId);
            if (productVm != null)
                productVm.MarkAsPurchased(receipt);

            // Track analytics
            _analyticsService.TrackRevenue(
                revenue: receipt.LocalizedPrice, 
                currencyIso: receipt.IsoCurrencyCode, 
                productId: receipt.ProductId,
                transactionId: receipt.TransactionId);

            Debug.Log($"{LogCategory} Purchase successful for {receipt.ProductId}");
        }

        private void OnPurchaseFailed(PurchaseError error)
        {
            Debug.LogWarning($"{LogCategory} Purchase failed: {error.ErrorCode} – {error.Message}");
            _analyticsService.TrackEvent(AnalyticsEvent.IapPurchaseFailed,
                new Dictionary<string, object>
                {
                    { "product_id", error.ProductId },
                    { "error_code", error.ErrorCode.ToString() }
                });
        }

        #endregion
    }

    #region Nested VM

    /// <summary>
    /// Lightweight VM representing a purchasable catalog item.
    /// </summary>
    public sealed class StoreProductViewModel : IDisposable
    {
        private readonly ReactiveProperty<bool> _isPurchased = new(false);

        public string Id                { get; }
        public string Title             { get; }
        public string Description       { get; }
        public string Price             { get; }
        public bool   Consumable        { get; }
        public IReadOnlyReactiveProperty<bool> IsPurchased => _isPurchased;

        internal StoreProductViewModel(IAPProduct product)
        {
            Id          = product.Id;
            Title       = product.Title;
            Description = product.Description;
            Price       = product.Price;
            Consumable  = product.Consumable;
        }

        internal void MarkAsPurchased(PurchaseReceipt _)
        {
            if (!Consumable) _isPurchased.Value = true;
        }

        public void Dispose() { /* Nothing yet */ }
    }

    #endregion
}
```