```csharp
// -------------------------------------------------------------------------------------------------
// TycoonVerse/src/TycoonVerse.Unity/Assets/Scripts/Views/IAPStoreView.cs
// -------------------------------------------------------------------------------------------------
//
//  Copyright  © TycoonVerse
//  All rights reserved.
//
//  Description:
//      Unity UI View responsible for rendering the IAP (In-App-Purchase) catalog, handling user
//      interactions (buy, restore, close), and coordinating with the View-Model layer.  The view
//      leverages UniRx for reactive data-binding and follows TycoonVerse’s MVVM guidelines.
//
//  NOTE: This file purposefully contains no `using UnityEditor` directives so it is 100% runtime-
//        safe and can be reused in builds without conditional compilation.
//
// -------------------------------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using TycoonVerse.Common.Analytics;
using TycoonVerse.Common.CrashReporting;
using TycoonVerse.Common.DependencyInjection;
using TycoonVerse.IAP;
using TycoonVerse.IAP.ViewModels;
using UniRx;
using UnityEngine;
using UnityEngine.UI;

namespace TycoonVerse.Views
{
    /// <summary>
    /// Reactive, self-contained view that renders an in-app purchase catalog and forwards events
    /// to the <see cref="IIapStoreViewModel"/>.  Requires UniRx and TycoonVerse’s internal DI.
    /// </summary>
    [RequireComponent(typeof(CanvasGroup))]
    public sealed class IapStoreView : MonoBehaviour
    {
        // ──────────────────────────────────────────────────────────────────────────────
        // Inspector-bound fields
        // ──────────────────────────────────────────────────────────────────────────────

        [Header("Layout / Prefabs")]
        [SerializeField] private IapStoreItemView _itemPrefab = default!;
        [SerializeField] private Transform        _itemContainer = default!;

        [Header("Buttons")]
        [SerializeField] private Button _restoreButton = default!;
        [SerializeField] private Button _closeButton   = default!;

        [Header("Visuals")]
        [SerializeField] private GameObject _loadingSpinner = default!;

        // ──────────────────────────────────────────────────────────────────────────────
        // Private state
        // ──────────────────────────────────────────────────────────────────────────────

        private readonly CompositeDisposable                   _disposables   = new CompositeDisposable();
        private readonly Dictionary<string, IapStoreItemView> _uiByProductId = new Dictionary<string, IapStoreItemView>();

        private CanvasGroup             _canvasGroup  = default!;
        private IIapStoreViewModel      _viewModel    = default!;
        private IAnalyticsService?      _analytics;
        private ICrashReportingService? _crashReporting;

        // ──────────────────────────────────────────────────────────────────────────────
        // Unity ‑ Lifecycle
        // ──────────────────────────────────────────────────────────────────────────────

        private void Awake()
        {
            _canvasGroup    = GetComponent<CanvasGroup>();
            _viewModel      = ServiceLocator.Resolve<IIapStoreViewModel>();
            _analytics      = ServiceLocator.TryResolve<IAnalyticsService>();
            _crashReporting = ServiceLocator.TryResolve<ICrashReportingService>();

            BindViewModel();
        }

        private void OnEnable()
        {
            _analytics?.TrackScreen("IAP_Store");
        }

        private void OnDestroy()
        {
            _disposables.Dispose();
        }

        // ──────────────────────────────────────────────────────────────────────────────
        // MVVM Binding
        // ──────────────────────────────────────────────────────────────────────────────

        private void BindViewModel()
        {
            if (_viewModel == null)
            {
                Debug.LogError("[IapStoreView] ViewModel is null.  Aborting binding.");
                return;
            }

            // Busy indicator
            _viewModel.IsBusy
                      .DistinctUntilChanged()
                      .ObserveOnMainThread()
                      .Subscribe(SetBusyState, LogAndReport)
                      .AddTo(_disposables);

            // Product catalog additions
            _viewModel.Products
                      .ObserveAdd()
                      .Subscribe(e => SpawnOrUpdateItem(e.Value), LogAndReport)
                      .AddTo(_disposables);

            // Product catalog removals
            _viewModel.Products
                      .ObserveRemove()
                      .Subscribe(e => RemoveItem(e.Value.Id), LogAndReport)
                      .AddTo(_disposables);

            // Product updates (e.g., localization, price-change)
            _viewModel.Products
                      .ObserveReplace()
                      .Subscribe(e => SpawnOrUpdateItem(e.NewValue), LogAndReport)
                      .AddTo(_disposables);

            // Restore purchases
            _restoreButton.OnClickAsObservable()
                          .ThrottleFirst(TimeSpan.FromSeconds(1)) // debouncing tap-spamming
                          .Subscribe(_ => _viewModel.RestorePurchases(), LogAndReport)
                          .AddTo(_disposables);

            // Close button
            _closeButton.OnClickAsObservable()
                        .Subscribe(_ => gameObject.SetActive(false), LogAndReport)
                        .AddTo(_disposables);
        }

        // ──────────────────────────────────────────────────────────────────────────────
        // UI Helpers
        // ──────────────────────────────────────────────────────────────────────────────

        private void SpawnOrUpdateItem(IapProductViewModel productVm)
        {
            if (_uiByProductId.TryGetValue(productVm.Id, out var existing))
            {
                existing.Bind(productVm);
                return;
            }

            var instance = Instantiate(_itemPrefab, _itemContainer);
            instance.Bind(productVm);
            _uiByProductId.Add(productVm.Id, instance);
        }

        private void RemoveItem(string id)
        {
            if (!_uiByProductId.TryGetValue(id, out var view))
                return;

            _uiByProductId.Remove(id);
            Destroy(view.gameObject);
        }

        private void SetBusyState(bool busy)
        {
            _canvasGroup.interactable = !busy;
            _canvasGroup.blocksRaycasts = !busy;

            if (_loadingSpinner != null)
                _loadingSpinner.SetActive(busy);
        }

        // ──────────────────────────────────────────────────────────────────────────────
        // Error Handling
        // ──────────────────────────────────────────────────────────────────────────────

        private void LogAndReport(Exception ex)
        {
            Debug.LogError($"[IapStoreView] {ex}");
            _crashReporting?.RecordException(ex);
        }
    }
}
```