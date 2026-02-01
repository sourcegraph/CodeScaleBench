```csharp
// File: TycoonVerse/src/TycoonVerse.Unity/Assets/Scripts/Views/CompanyDetailsView.cs

#nullable enable
using System;
using System.Threading;
using System.Threading.Tasks;
using TMPro;
using UniRx;
using UnityEngine;
using UnityEngine.UI;
using TycoonVerse.Unity.Infrastructure.Analytics;
using TycoonVerse.Unity.Infrastructure.Dialogs;
using TycoonVerse.Unity.Infrastructure.Toast;
using TycoonVerse.Unity.ViewModels;

namespace TycoonVerse.Unity.Views
{
    /// <summary>
    ///     A Unity UI view that displays the real-time financial status of a single company
    ///     and exposes actions such as “Invest” or “Rename”.
    ///
    ///     The class relies on MVVM bindings powered by UniRx.  All commands and data come
    ///     from <see cref="ICompanyDetailsViewModel" /> so that the view never manipulates
    ///     domain objects directly.
    /// </summary>
    [RequireComponent(typeof(CanvasGroup))]
    public sealed class CompanyDetailsView : MonoBehaviour
    {
        #region Inspector Bindings ------------------------------------------------------------

        [Header("Text Fields")]
        [SerializeField] private TMP_Text _companyNameTxt = default!;
        [SerializeField] private TMP_Text _valuationTxt    = default!;
        [SerializeField] private TMP_Text _revenueTxt      = default!;
        [SerializeField] private TMP_Text _ebitdaTxt       = default!;
        [SerializeField] private TMP_Text _deRatioTxt      = default!;

        [Header("Buttons")]
        [SerializeField] private Button _renameBtn  = default!;
        [SerializeField] private Button _investBtn  = default!;
        [SerializeField] private Button _reportsBtn = default!;

        [Header("UX Helpers")]
        [SerializeField] private GameObject _loadingSpinner = default!;
        [SerializeField] private GameObject _offlineBanner  = default!;

        #endregion ---------------------------------------------------------------------------

        private readonly CompositeDisposable _disposables = new();

        private ICompanyDetailsViewModel? _viewModel;

        // For async operations that live as long as this view.
        private readonly CancellationTokenSource _cts = new();

        /// <summary>
        ///     Injects the view-model and kicks off subscriptions.  Must be called by
        ///     whichever controller / flow coordinator instantiates the prefab.
        /// </summary>
        public void Initialize(ICompanyDetailsViewModel viewModel)
        {
            _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));

            BindUi();
            BindViewModel();

            // Initial load, executed after bindings so the spinner reacts immediately.
            _ = SafeExecuteAsync(_viewModel.LoadInitialAsync, _cts.Token);
        }

        #region UI -> ViewModel Bindings -------------------------------------------------------

        private void BindUi()
        {
            _renameBtn.onClick.AsObservable()
                     .ThrottleFirst(TimeSpan.FromMilliseconds(300))
                     .Subscribe(_ => HandleRenameClicked())
                     .AddTo(_disposables);

            _investBtn.onClick.AsObservable()
                     .ThrottleFirst(TimeSpan.FromMilliseconds(300))
                     .Subscribe(_ => HandleInvestClicked())
                     .AddTo(_disposables);

            _reportsBtn.onClick.AsObservable()
                      .ThrottleFirst(TimeSpan.FromMilliseconds(300))
                      .Subscribe(_ => HandleReportsClicked())
                      .AddTo(_disposables);
        }

        #endregion ---------------------------------------------------------------------------

        #region ViewModel -> UI Bindings -------------------------------------------------------

        private void BindViewModel()
        {
            if (_viewModel == null) return;

            _viewModel.CompanyName
                      .ObserveOnMainThread()
                      .Subscribe(name => _companyNameTxt.text = name)
                      .AddTo(_disposables);

            _viewModel.Valuation
                      .ObserveOnMainThread()
                      .Subscribe(v => _valuationTxt.text = v.ToString("C0"))
                      .AddTo(_disposables);

            _viewModel.Revenue
                      .ObserveOnMainThread()
                      .Subscribe(r => _revenueTxt.text = r.ToString("C0"))
                      .AddTo(_disposables);

            _viewModel.Ebitda
                      .ObserveOnMainThread()
                      .Subscribe(e => _ebitdaTxt.text = e.ToString("C0"))
                      .AddTo(_disposables);

            _viewModel.DebtToEquity
                      .ObserveOnMainThread()
                      .Subscribe(d => _deRatioTxt.text = $"{d:P1}")
                      .AddTo(_disposables);

            _viewModel.IsBusy
                      .ObserveOnMainThread()
                      .Subscribe(isBusy => _loadingSpinner.SetActive(isBusy))
                      .AddTo(_disposables);

            _viewModel.IsOffline
                      .ObserveOnMainThread()
                      .Subscribe(isOffline => _offlineBanner.SetActive(isOffline))
                      .AddTo(_disposables);

            _viewModel.Errors
                      .ObserveOnMainThread()
                      .Subscribe(ShowErrorToast)
                      .AddTo(_disposables);
        }

        #endregion ---------------------------------------------------------------------------

        #region Button Handlers ---------------------------------------------------------------

        private void HandleRenameClicked()
        {
            if (_viewModel == null) return;

            DialogFactory
                .ShowRenameCompanyDialog(_viewModel.CompanyName.Value)
                .Subscribe(newName =>
                {
                    if (!string.IsNullOrWhiteSpace(newName))
                    {
                        _ = SafeExecuteAsync(
                            ct => _viewModel.RenameAsync(newName, ct),
                            _cts.Token);
                    }
                })
                .AddTo(_disposables);

            AnalyticsService.LogEvent(AnalyticsEvent.UiButtonClicked,
                                      ("context", "CompanyDetailsView"),
                                      ("button",  "Rename"));
        }

        private void HandleInvestClicked()
        {
            if (_viewModel == null) return;

            DialogFactory
                .ShowInvestDialog(_viewModel.AvailableFunds)
                .Subscribe(amount =>
                {
                    if (amount > 0)
                    {
                        _ = SafeExecuteAsync(
                            ct => _viewModel.InvestAsync(amount, ct),
                            _cts.Token);
                    }
                })
                .AddTo(_disposables);

            AnalyticsService.LogEvent(AnalyticsEvent.UiButtonClicked,
                                      ("context", "CompanyDetailsView"),
                                      ("button",  "Invest"));
        }

        private void HandleReportsClicked()
        {
            if (_viewModel == null) return;

            _viewModel.OpenReportsCommand.Execute();
            AnalyticsService.LogEvent(AnalyticsEvent.UiButtonClicked,
                                      ("context", "CompanyDetailsView"),
                                      ("button",  "Reports"));
        }

        #endregion ---------------------------------------------------------------------------

        #region Helpers -----------------------------------------------------------------------

        /// <summary>
        ///     Runs an async action while toggling _viewModel.IsBusy and propagating
        ///     exceptions to the shared error stream.
        /// </summary>
        private async Task SafeExecuteAsync(
            Func<CancellationToken, Task> asyncAction,
            CancellationToken ct)
        {
            if (_viewModel == null) return;

            try
            {
                _viewModel.IsBusy.OnNext(true);
                await asyncAction(ct);
            }
            catch (OperationCanceledException)
            {
                // ignore — expected during view destruction.
            }
            catch (Exception ex)
            {
                _viewModel.Errors.OnNext(ex);
            }
            finally
            {
                _viewModel.IsBusy.OnNext(false);
            }
        }

        private void ShowErrorToast(Exception ex)
        {
            ToastService.Show($"⚠️ {ex.Message}");
            Debug.LogException(ex);
        }

        #endregion ---------------------------------------------------------------------------

        private void OnDestroy()
        {
            _cts.Cancel();
            _cts.Dispose();
            _disposables.Dispose();
        }
    }
}

#region Interfaces & Supporting Types  (kept in same file for convenience)

// NOTE: In the production codebase these belong to dedicated files/namespaces.
// They are declared here so that this single file is self-contained and
// compilable when copied into an empty Unity project.

namespace TycoonVerse.Unity.ViewModels
{
    using UniRx;
    using System.Threading;
    using System.Threading.Tasks;

    public interface ICompanyDetailsViewModel
    {
        // Reactive state ------------------------------------------------------
        IReadOnlyReactiveProperty<string> CompanyName  { get; }
        IReadOnlyReactiveProperty<decimal> Valuation    { get; }
        IReadOnlyReactiveProperty<decimal> Revenue      { get; }
        IReadOnlyReactiveProperty<decimal> Ebitda       { get; }
        IReadOnlyReactiveProperty<double>  DebtToEquity { get; }
        IReadOnlyReactiveProperty<bool>    IsBusy       { get; }
        IReadOnlyReactiveProperty<bool>    IsOffline    { get; }
        ReactiveCommand<Unit>              OpenReportsCommand { get; }
        ReactiveProperty<Exception>        Errors       { get; }

        // Non-reactive properties -------------------------------------------
        decimal AvailableFunds { get; }

        // Actions ------------------------------------------------------------
        Task LoadInitialAsync(CancellationToken ct);
        Task RenameAsync(string newName, CancellationToken ct);
        Task InvestAsync(decimal amount, CancellationToken ct);
    }
}

namespace TycoonVerse.Unity.Infrastructure.Dialogs
{
    using System;
    using UniRx;

    public static class DialogFactory
    {
        public static IObservable<string> ShowRenameCompanyDialog(string currentName)
        {
            // Production implementation would instantiate a prefab, wire events etc.
            // For this stub, return an observable that never fires.
            return Observable.Never<string>();
        }

        public static IObservable<decimal> ShowInvestDialog(decimal maxAmount)
        {
            return Observable.Never<decimal>();
        }
    }
}

namespace TycoonVerse.Unity.Infrastructure.Toast
{
    using UnityEngine;

    public static class ToastService
    {
        public static void Show(string message) =>
            Debug.Log($"[Toast] {message}");

        public static void ShowError(string message) =>
            Show($"Error: {message}");
    }
}

namespace TycoonVerse.Unity.Infrastructure.Analytics
{
    using System;
    using UnityEngine;

    public static class AnalyticsService
    {
        public static void LogEvent(string eventName, params (string key, object value)[] parameters)
        {
            var paramStr = string.Join(", ",
                Array.ConvertAll(parameters, p => $"{p.key}={p.value}"));
            Debug.Log($"[Analytics] {eventName}: {paramStr}");
        }
    }

    public static class AnalyticsEvent
    {
        public const string UiButtonClicked = "ui_button_clicked";
    }
}

#endregion
```