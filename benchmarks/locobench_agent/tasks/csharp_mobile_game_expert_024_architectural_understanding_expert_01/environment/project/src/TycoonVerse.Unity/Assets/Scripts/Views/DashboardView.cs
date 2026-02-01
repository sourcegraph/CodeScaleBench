```csharp
using System;
using System.Collections;
using System.Globalization;
using System.Threading;
using System.Threading.Tasks;
using TycoonVerse.Application.Analytics;
using TycoonVerse.Application.GameState;
using TycoonVerse.Domain.Models;
using TycoonVerse.Infrastructure.ServiceLocator;
using TMPro;
using UnityEngine;
using UnityEngine.Assertions;
using UnityEngine.UI;

#nullable enable

namespace TycoonVerse.Unity.Views
{
    /// <summary>
    /// DashboardView is responsible for presenting high-level financial metrics to the
    /// player and routing UI interactions to the View-Model layer.
    ///
    /// It subscribes to the <see cref="IGameStateReader"/> in order to react to real-time
    /// changes of the player’s company.  All UI updates are performed on the main thread
    /// and animated using lightweight coroutines.
    ///
    /// The class purposely avoids direct domain-logic manipulation and delegates all
    /// commands through the <see cref="IDashboardController"/> façade.  This keeps the
    /// view as dumb as possible—an essential property for unit-testing and separation
    /// of concerns in MVVM.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class DashboardView : MonoBehaviour
    {
        #region Inspector

        [Header("Header / Company Info")]
        [SerializeField] private TextMeshProUGUI _companyNameText = default!;
        [SerializeField] private Image _companyLogoImage       = default!;

        [Header("Financials")]
        [SerializeField] private TextMeshProUGUI _cashText           = default!;
        [SerializeField] private TextMeshProUGUI _ebitdaText         = default!;
        [SerializeField] private TextMeshProUGUI _debtEquityText     = default!;

        [Header("Connectivity")]
        [SerializeField] private Image _connectivityIcon             = default!;
        [SerializeField] private Sprite _onlineSprite                = default!;
        [SerializeField] private Sprite _offlineSprite               = default!;

        [Header("Navigation Buttons")]
        [SerializeField] private Button _inventoryButton             = default!;
        [SerializeField] private Button _reportsButton               = default!;
        [SerializeField] private Button _marketButton                = default!;
        [SerializeField] private Button _settingsButton              = default!;

        [Header("Misc")]
        [Tooltip("Duration in seconds to animate numerical value updates.")]
        [Range(0.01f, 3f)]
        [SerializeField] private float _valueAnimationDuration = .4f;

        #endregion

        #region Private state

        private IDashboardController? _controller;
        private IGameStateReader?     _gameState;
        private IAnalyticsService?    _analytics;

        private readonly CultureInfo _currencyCulture =
#if UNITY_IOS
            new CultureInfo("en-US"); // iOS forces en-US for currency formatting to match App Store conventions
#else
            CultureInfo.CurrentCulture;
#endif

        private CancellationTokenSource? _valueAnimationToken;

        #endregion

        #region Unity lifecycle

        private void Awake()
        {
            ValidateInspectorBindings();
            ResolveDependencies();
            HookButtonEvents();
        }

        private void OnEnable()
        {
            SubscribeToGameState();
            PublishAnalyticsOpened();

            // Force a UI refresh to match the latest state immediately
            if (_gameState != null)
            {
                UpdateUI(_gameState.CurrentSnapshot);
            }
        }

        private void OnDisable()
        {
            UnsubscribeFromGameState();
            _valueAnimationToken?.Cancel();
        }

        #endregion

        #region Dependency resolution

        private void ResolveDependencies()
        {
            // All services are fetched via the project's lightweight service locator.
            _controller = ServiceLocator.Resolve<IDashboardController>();
            _gameState  = ServiceLocator.Resolve<IGameStateReader>();
            _analytics  = ServiceLocator.Resolve<IAnalyticsService>();

            if (_controller == null || _gameState == null || _analytics == null)
            {
                const string msg = "Missing critical service dependency. " +
                                   "Ensure ServiceLocator is configured in bootstrap.";
                Debug.LogError(msg, this);
                enabled = false;
            }
        }

        #endregion

        #region Event wiring

        private void HookButtonEvents()
        {
            _inventoryButton.onClick.AddListener(() => _controller?.OpenInventory());
            _reportsButton.onClick.AddListener(() => _controller?.OpenReports());
            _marketButton.onClick.AddListener(()  => _controller?.OpenMarketplace());
            _settingsButton.onClick.AddListener(() => _controller?.OpenSettings());
        }

        private void SubscribeToGameState()
        {
            if (_gameState == null) { return; }
            _gameState.OnFinancialsChanged           += HandleFinancialChanged;
            _gameState.OnCompanyIdentityChanged      += HandleCompanyIdentityChanged;
            _gameState.OnConnectivityStatusChanged   += HandleConnectivityChanged;
        }

        private void UnsubscribeFromGameState()
        {
            if (_gameState == null) { return; }
            _gameState.OnFinancialsChanged           -= HandleFinancialChanged;
            _gameState.OnCompanyIdentityChanged      -= HandleCompanyIdentityChanged;
            _gameState.OnConnectivityStatusChanged   -= HandleConnectivityChanged;
        }

        private void PublishAnalyticsOpened() => 
            _analytics?.TrackScreenOpened("dashboard");

        #endregion

        #region Game-state handlers

        private void HandleFinancialChanged(FinancialSnapshot snapshot) =>
            UpdateUI(snapshot);

        private void HandleCompanyIdentityChanged(CompanyIdentity identity)
        {
            _companyNameText.text = identity.CompanyName;

            // Kick off async logo download if needed
            _ = LoadCompanyLogoAsync(identity.LogoUri);
        }

        private void HandleConnectivityChanged(bool isOnline)
        {
            _connectivityIcon.sprite = isOnline ? _onlineSprite : _offlineSprite;
            _connectivityIcon.color  = isOnline ? Color.white   : new Color(1f, .5f, .5f);
        }

        #endregion

        #region UI updates

        private void UpdateUI(FinancialSnapshot snapshot)
        {
            AnimateText(_cashText,    snapshot.Cash);
            AnimateText(_ebitdaText,  snapshot.Ebitda);
            AnimateText(_debtEquityText, snapshot.DebtToEquityRatio, percentage: true);
        }

        private void AnimateText(TextMeshProUGUI target, decimal value, bool percentage = false)
        {
            _valueAnimationToken?.Cancel();
            _valueAnimationToken = new CancellationTokenSource();

            var token = _valueAnimationToken.Token;

            if (!gameObject.activeInHierarchy) // skip animation when not visible
            {
                target.text = FormatValue(value, percentage);
                return;
            }

            // Use coroutine wrapper to ensure work happens on main thread
            StartCoroutine(Animate());

            IEnumerator Animate()
            {
                decimal startValue = ParseCurrent(target.text, percentage);
                float elapsed = 0f;

                while (elapsed < _valueAnimationDuration)
                {
                    elapsed += Time.deltaTime;
                    float t  = Mathf.Clamp01(elapsed / _valueAnimationDuration);
                    decimal interpolated = Decimal.Lerp(startValue, value, t);
                    target.text = FormatValue(interpolated, percentage);

                    if (token.IsCancellationRequested) yield break;
                    yield return null;
                }

                target.text = FormatValue(value, percentage);
            }
        }

        private string FormatValue(decimal value, bool percentage)
        {
            if (percentage)
            {
                return $"{value:P1}";
            }

            // Negative values are formatted in red for instant visual feedback
            string formattedNumber = value.ToString("C0", _currencyCulture);
            return value < 0
                ? $"<color=#ff4d4d>{formattedNumber}</color>"
                : formattedNumber;
        }

        private static decimal ParseCurrent(string raw, bool percentage)
        {
            try
            {
                if (percentage)
                {
                    raw = raw.Replace("%", string.Empty);
                    if (Decimal.TryParse(raw, NumberStyles.Any, CultureInfo.InvariantCulture, out var pct))
                        return pct / 100m;
                }
                else
                {
                    // Remove rich-text tags if any
                    raw = TMPro.TMProUtility.StripRichText(raw);

                    // Remove currency symbols/commas
                    raw = raw.Replace(CultureInfo.CurrentCulture.NumberFormat.CurrencySymbol, string.Empty);
                    raw = raw.Replace(",", string.Empty);
                    if (Decimal.TryParse(raw, out var num))
                        return num;
                }
            }
            catch
            {
                // ignore parsing errors & fall through
            }

            return 0m;
        }

        #endregion

        #region Async logo handling

        private async Task LoadCompanyLogoAsync(Uri? logoUri)
        {
            if (logoUri == null) return;

            try
            {
                var texture = await RemoteTextureLoader.LoadAsync(logoUri);
                if (texture == null) return;

                _companyLogoImage.sprite = Sprite.Create(
                    texture,
                    new Rect(0, 0, texture.width, texture.height),
                    new Vector2(.5f, .5f),
                    100f);

                _companyLogoImage.SetNativeSize();
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"Failed to load company logo from {logoUri}: {ex.Message}", this);
            }
        }

        #endregion

        #region Validation

        private void ValidateInspectorBindings()
        {
#if UNITY_EDITOR
            Assert.IsNotNull(_companyNameText,  $"{nameof(_companyNameText)} not bound.",  this);
            Assert.IsNotNull(_companyLogoImage, $"{nameof(_companyLogoImage)} not bound.", this);
            Assert.IsNotNull(_cashText,         $"{nameof(_cashText)} not bound.",         this);
            Assert.IsNotNull(_ebitdaText,       $"{nameof(_ebitdaText)} not bound.",       this);
            Assert.IsNotNull(_debtEquityText,   $"{nameof(_debtEquityText)} not bound.",   this);
            Assert.IsNotNull(_connectivityIcon, $"{nameof(_connectivityIcon)} not bound.", this);
            Assert.IsNotNull(_inventoryButton,  $"{nameof(_inventoryButton)} not bound.",  this);
            Assert.IsNotNull(_reportsButton,    $"{nameof(_reportsButton)} not bound.",    this);
            Assert.IsNotNull(_marketButton,     $"{nameof(_marketButton)} not bound.",     this);
            Assert.IsNotNull(_settingsButton,   $"{nameof(_settingsButton)} not bound.",   this);
#endif
        }

        #endregion
    }

    // ---- Helper extensions ----------------------------------------------------

    internal static class DecimalExtensions
    {
        /// <summary>
        /// Linearly interpolates between two <see cref="decimal"/> values.
        /// </summary>
        internal static decimal Lerp(this decimal a, decimal b, float t) =>
            a + (b - a) * (decimal)Mathf.Clamp01(t);
    }

    internal static class TMProUtility
    {
        // Cheap utility to strip rich-text tags so we can parse numerical value out of a string
        internal static string StripRichText(string input)
        {
            int idx;
            while ((idx = input.IndexOf('<')) != -1)
            {
                int end = input.IndexOf('>', idx + 1);
                if (end == -1) break;
                input = input.Remove(idx, end - idx + 1);
            }
            return input;
        }
    }

    // ---- Mocked Infrastructure (used only for compilation) --------------------

    /// <summary>
    /// Optional remote loader abstracted behind a facade, implemented elsewhere.
    /// </summary>
    internal static class RemoteTextureLoader
    {
        public static Task<Texture2D?> LoadAsync(Uri uri)
        {
            // In production this hits CDN & caches result locally.
            var tcs = new TaskCompletionSource<Texture2D?>();
            tcs.SetResult(null);
            return tcs.Task;
        }
    }
}
```