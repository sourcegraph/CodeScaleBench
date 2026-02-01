```csharp
// ---------------------------------------------------------------------------------------------------------------------
//  TycoonVerse – Enterprise Empire Simulator
//  File:        Assets/Scripts/Views/MarketView.cs
//  Author:      TycoonVerse Dev Team
//  Description: Unity‐side Presentation Layer for the real-time market screen.
//               Implements MVVM bindings, analytics hooks, and offline-aware UI behavior.
// ---------------------------------------------------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using TycoonVerse.Domain.Markets;
using TycoonVerse.Infrastructure.Analytics;
using TycoonVerse.Infrastructure.Localization;
using TycoonVerse.Unity.Common;
using TycoonVerse.Unity.Extensions;
using TycoonVerse.Unity.IoC;
using UniRx;
using UnityEngine;
using UnityEngine.UI;

#nullable enable

namespace TycoonVerse.Unity.Views
{
    /// <summary>
    /// Presents real-time commodity prices, company shares, and actionable buy/sell buttons.
    /// Binds to <see cref="IMarketViewModel"/> via UniRx streams, allowing reactive UI updates
    /// without manual polling.
    /// </summary>
    [RequireComponent(typeof(CanvasGroup))]
    public sealed class MarketView : MonoBehaviour
    {
        // --------------------------------------------------
        // Inspector bindings
        // --------------------------------------------------

        [Header("UI – Price Tickers")]
        [SerializeField] private Text _commodityPriceTxt      = default!;
        [SerializeField] private Text _sharePriceTxt          = default!;
        [SerializeField] private Image _commodityTrendArrow   = default!;
        [SerializeField] private Image _shareTrendArrow       = default!;

        [Header("UI – Actionables")]
        [SerializeField] private Button _buyButton            = default!;
        [SerializeField] private Button _sellButton           = default!;

        [Header("UI – Offline Banner")]
        [SerializeField] private GameObject _offlineBanner    = default!;

        // --------------------------------------------------
        // Private fields
        // --------------------------------------------------

        private readonly CompositeDisposable _viewDisposables = new CompositeDisposable();
        private IMarketViewModel? _viewModel;

        // IoC-resolved services
        private IAnalyticsAdapter?          _analytics;
        private ILocalizationService?       _localization;
        private IConnectivityService?       _connectivity;
        private CancellationTokenSource?    _cancellation;

        // --------------------------------------------------
        // Unity lifecycle
        // --------------------------------------------------

        private async void Awake()
        {
            // Resolve dependencies via the project’s service locator.
            _analytics      = ServiceLocator.Resolve<IAnalyticsAdapter>();
            _localization   = ServiceLocator.Resolve<ILocalizationService>();
            _connectivity   = ServiceLocator.Resolve<IConnectivityService>();
            _viewModel      = ServiceLocator.Resolve<IMarketViewModel>();

            GuardAgainst.Null(_analytics,      nameof(_analytics));
            GuardAgainst.Null(_localization,   nameof(_localization));
            GuardAgainst.Null(_connectivity,   nameof(_connectivity));
            GuardAgainst.Null(_viewModel,      nameof(_viewModel));

            // Localize static UI.
            _buyButton .GetComponentInChildren<Text>().text  = _localization!.Get("MARKET_BUY");
            _sellButton.GetComponentInChildren<Text>().text  = _localization!.Get("MARKET_SELL");

            // Button bindings
            _buyButton .onClick.AddListener(OnBuyClicked);
            _sellButton.onClick.AddListener(OnSellClicked);

            // Begin binding reactive ViewModel streams.
            BindViewModel();

            // Kick off periodic refresh (server sync every n seconds).
            _cancellation = new CancellationTokenSource();
            try
            {
                await StartPeriodicRefreshAsync(_cancellation.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // Expected when view is destroyed.
            }
        }

        private void OnEnable()
        {
            _analytics?.TrackScreenView("MarketScreen");
        }

        private void OnDisable()
        {
            _viewDisposables.Clear();
            _cancellation?.Cancel();
        }

        // --------------------------------------------------
        // ViewModel binding
        // --------------------------------------------------

        private void BindViewModel()
        {
            if (_viewModel == null)
                return;

            // Commodity price binding
            _viewModel.CommodityPrice
                .ObserveOnMainThread()
                .Subscribe(UpdateCommodityPrice)
                .AddTo(_viewDisposables);

            // Share price binding
            _viewModel.CompanySharePrice
                .ObserveOnMainThread()
                .Subscribe(UpdateSharePrice)
                .AddTo(_viewDisposables);

            // Connectivity binding
            _connectivity!.IsOnlineStream
                .DistinctUntilChanged()
                .ObserveOnMainThread()
                .Subscribe(SetConnectivityState)
                .AddTo(_viewDisposables);
        }

        // --------------------------------------------------
        // UI update helpers
        // --------------------------------------------------

        private void UpdateCommodityPrice(PriceSnapshot snapshot)
        {
            _commodityPriceTxt.text = snapshot.Price.ToString("C2");
            _commodityTrendArrow.sprite = snapshot.Direction.ToSprite();
            _commodityTrendArrow.color  = snapshot.Direction.ToColor();
        }

        private void UpdateSharePrice(PriceSnapshot snapshot)
        {
            _sharePriceTxt.text = snapshot.Price.ToString("C2");
            _shareTrendArrow.sprite = snapshot.Direction.ToSprite();
            _shareTrendArrow.color  = snapshot.Direction.ToColor();
        }

        private void SetConnectivityState(bool isOnline)
        {
            _offlineBanner.SetActive(!isOnline);
            _buyButton.interactable  = isOnline;
            _sellButton.interactable = isOnline;
        }

        // --------------------------------------------------
        // Button handlers
        // --------------------------------------------------

        private void OnBuyClicked()
        {
            if (_viewModel == null) return;

            // Prevent spamming
            if (!_buyButton.interactable) return;

            _viewModel.ExecuteBuy()
                .ObserveOnMainThread()
                .Subscribe(
                    _ => _analytics?.TrackEvent("Market_Buy_Success"),
                    ex => HandleViewError("BUY_FAILED", ex))
                .AddTo(_viewDisposables);
        }

        private void OnSellClicked()
        {
            if (_viewModel == null) return;
            if (!_sellButton.interactable) return;

            _viewModel.ExecuteSell()
                .ObserveOnMainThread()
                .Subscribe(
                    _ => _analytics?.TrackEvent("Market_Sell_Success"),
                    ex => HandleViewError("SELL_FAILED", ex))
                .AddTo(_viewDisposables);
        }

        // --------------------------------------------------
        // Periodic server refresh – offline tolerant
        // --------------------------------------------------

        private async Task StartPeriodicRefreshAsync(CancellationToken token)
        {
            const float refreshSeconds = 5f;

            while (!token.IsCancellationRequested)
            {
                try
                {
                    if (_connectivity!.IsOnline)
                    {
                        await _viewModel!.RefreshAsync(token).ConfigureAwait(false);
                    }
                }
                catch (Exception ex)
                {
                    HandleViewError("REFRESH_FAILED", ex);
                }

                await Task.Delay(TimeSpan.FromSeconds(refreshSeconds), token).ConfigureAwait(false);
            }
        }

        // --------------------------------------------------
        // Error handling
        // --------------------------------------------------

        private void HandleViewError(string errorKey, Exception ex)
        {
            Debug.LogError($"MarketView error ({errorKey}): {ex}");

            // Fire-and-forget analytics
            _analytics?.TrackError(errorKey, ex);

            // Localized toast
            Toast.Show(_localization?.Get(errorKey) ?? "Something went wrong");
        }
    }

    // -------------------------------------------------------------------------------------------------
    // Extension helpers (keep inside same file for cohesion but can be moved to separate utility files)
    // -------------------------------------------------------------------------------------------------

    internal static class PriceDirectionExtensions
    {
        private static readonly Dictionary<PriceDirection, Color> s_ColorMap = new()
        {
            { PriceDirection.Up,    new Color(0.14f, 0.80f, 0.32f) }, // Green
            { PriceDirection.Down,  new Color(0.80f, 0.18f, 0.14f) }, // Red
            { PriceDirection.Flat,  new Color(0.75f, 0.75f, 0.75f) }  // Gray
        };

        public static Sprite ToSprite(this PriceDirection direction)
        {
            return Resources.Load<Sprite>($"UI/Icons/Arrow_{direction}");
        }

        public static Color ToColor(this PriceDirection direction)
        {
            return s_ColorMap.TryGetValue(direction, out var c) ? c : Color.white;
        }
    }
}
```