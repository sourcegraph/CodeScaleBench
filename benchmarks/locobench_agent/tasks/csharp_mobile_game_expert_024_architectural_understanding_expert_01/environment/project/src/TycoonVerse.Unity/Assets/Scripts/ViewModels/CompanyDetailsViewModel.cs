```csharp
// File: TycoonVerse/src/TycoonVerse.Unity/Assets/Scripts/ViewModels/CompanyDetailsViewModel.cs

using System;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using TMPro; // Example usage in the view layer – safe to keep here for intellisense.
using TycoonVerse.Domain.Companies;
using TycoonVerse.Domain.Finance;
using TycoonVerse.Infrastructure.Logging;
using TycoonVerse.Services.Analytics;
using TycoonVerse.Services.Localization;
using TycoonVerse.Services.Networking;
using TycoonVerse.Services.Repositories;
using TycoonVerse.Unity.Common.UI.Commands;
using TycoonVerse.Unity.Common.UI.Dispatcher;
using UnityEngine;

namespace TycoonVerse.Unity.ViewModels
{
    /// <summary>
    /// View-model for the “Company Details” screen (MVVM).
    /// Encapsulates all presentation-ready data and user commands.
    /// </summary>
    public sealed class CompanyDetailsViewModel : INotifyPropertyChanged, IDisposable
    {
        #region Fields

        private readonly ICompanyRepository           _companyRepository;
        private readonly IFinancialProjectionService  _projectionService;
        private readonly IAnalyticsService            _analytics;
        private readonly ILocalizationService         _localization;
        private readonly IConnectivityService         _connectivity;
        private readonly ILog                         _log;
        private readonly IMainThreadDispatcher        _dispatcher;

        private CancellationTokenSource               _cancellationSource;

        private Company?                              _company;

        private bool                                  _isBusy;
        private string                                _statusMessage = string.Empty;

        #endregion

        #region Ctor / Lifecycle

        public CompanyDetailsViewModel(
            ICompanyRepository           companyRepository,
            IFinancialProjectionService  projectionService,
            IAnalyticsService            analytics,
            ILocalizationService         localization,
            IConnectivityService         connectivity,
            ILog                         log,
            IMainThreadDispatcher        dispatcher
        )
        {
            _companyRepository = companyRepository ?? throw new ArgumentNullException(nameof(companyRepository));
            _projectionService = projectionService ?? throw new ArgumentNullException(nameof(projectionService));
            _analytics         = analytics          ?? throw new ArgumentNullException(nameof(analytics));
            _localization      = localization       ?? throw new ArgumentNullException(nameof(localization));
            _connectivity      = connectivity       ?? throw new ArgumentNullException(nameof(connectivity));
            _log               = log                ?? throw new ArgumentNullException(nameof(log));
            _dispatcher        = dispatcher         ?? throw new ArgumentNullException(nameof(dispatcher));

            RefreshCommand     = new AsyncDelegateCommand(RefreshAsync, CanExecuteWhenNotBusy);
            AcquireCommand     = new AsyncDelegateCommand(AcquireAsync, CanExecuteWhenNotBusy);
            IssueBondCommand   = new AsyncDelegateCommand(IssueBondAsync,   CanExecuteWhenNotBusy);
            IPOCommand         = new AsyncDelegateCommand(StartIpoAsync,    CanExecuteWhenNotBusy);
        }

        #endregion

        #region Public Bindable Properties

        public string CompanyName
        {
            get => _company?.Name ?? string.Empty;
            private set => SetField(value);
        }

        public Sprite? LogoSprite
        {
            get => _company?.LogoSprite;
            private set => SetField(value);
        }

        public decimal Revenue
        {
            get => _company?.Financials.Revenue ?? 0m;
            private set => SetField(value);
        }

        public decimal Ebitda
        {
            get => _company?.Financials.Ebitda ?? 0m;
            private set => SetField(value);
        }

        public float DebtToEquity
        {
            get => _company?.Financials.DebtToEquity ?? 0f;
            private set => SetField(value);
        }

        public string StatusMessage
        {
            get => _statusMessage;
            private set => SetField(ref _statusMessage, value);
        }

        public bool IsBusy
        {
            get => _isBusy;
            private set
            {
                if (SetField(ref _isBusy, value))
                {
                    // Refresh CanExecute
                    RefreshCommand.RaiseCanExecuteChanged();
                    AcquireCommand.RaiseCanExecuteChanged();
                    IssueBondCommand.RaiseCanExecuteChanged();
                    IPOCommand.RaiseCanExecuteChanged();
                }
            }
        }

        #endregion

        #region Commands

        public AsyncDelegateCommand RefreshCommand   { get; }
        public AsyncDelegateCommand AcquireCommand   { get; }
        public AsyncDelegateCommand IssueBondCommand { get; }
        public AsyncDelegateCommand IPOCommand       { get; }

        #endregion

        #region Public API

        /// <summary>
        /// Must be called by the owner (monobehaviour) when the view is shown.
        /// </summary>
        public async Task InitializeAsync(Guid companyId)
        {
            _cancellationSource?.Cancel();
            _cancellationSource = new CancellationTokenSource();

            await LoadCompanyAsync(companyId, _cancellationSource.Token).ConfigureAwait(false);
        }

        #endregion

        #region Command Handlers

        private async Task RefreshAsync()
        {
            if (_company is null) return;

            await LoadCompanyAsync(_company.Id, CancellationToken.None).ConfigureAwait(false);
            _analytics.TrackEvent("company_details_refresh");
        }

        private async Task AcquireAsync()
        {
            if (_company is null) return;

            try
            {
                IsBusy = true;
                StatusMessage = _localization["company.acquire.progress"];

                await _companyRepository.AcquireAsync(_company.Id).ConfigureAwait(false);

                StatusMessage = _localization["company.acquire.success"];
                _analytics.TrackEvent("company_acquired", ("company_id", _company.Id));
            }
            catch (Exception ex)
            {
                _log.Error(ex, "AcquireAsync failed");
                StatusMessage = _localization["company.acquire.failed"];
            }
            finally
            {
                IsBusy = false;
            }
        }

        private async Task IssueBondAsync()
        {
            if (_company is null) return;

            try
            {
                IsBusy = true;
                StatusMessage = _localization["company.issue_bond.progress"];

                await _companyRepository.IssueBondAsync(_company.Id).ConfigureAwait(false);

                StatusMessage = _localization["company.issue_bond.success"];
                _analytics.TrackEvent("bond_issued", ("company_id", _company.Id));
            }
            catch (Exception ex)
            {
                _log.Error(ex, "IssueBondAsync failed");
                StatusMessage = _localization["company.issue_bond.failed"];
            }
            finally
            {
                IsBusy = false;
            }
        }

        private async Task StartIpoAsync()
        {
            if (_company is null) return;

            try
            {
                IsBusy = true;
                StatusMessage = _localization["company.ipo.progress"];

                await _companyRepository.StartIpoProcessAsync(_company.Id).ConfigureAwait(false);

                StatusMessage = _localization["company.ipo.success"];
                _analytics.TrackEvent("ipo_started", ("company_id", _company.Id));
            }
            catch (Exception ex)
            {
                _log.Error(ex, "StartIpoAsync failed");
                StatusMessage = _localization["company.ipo.failed"];
            }
            finally
            {
                IsBusy = false;
            }
        }

        #endregion

        #region Private Helpers

        private bool CanExecuteWhenNotBusy() => !IsBusy;

        private async Task LoadCompanyAsync(Guid companyId, CancellationToken ct)
        {
            if (!_connectivity.HasInternet && !_companyRepository.HasLocalCache(companyId))
            {
                StatusMessage = _localization["generic.no_internet"];
                return;
            }

            try
            {
                IsBusy = true;
                StatusMessage = _localization["generic.loading"];

                var company = await _companyRepository.GetByIdAsync(companyId, ct).ConfigureAwait(false);
                ct.ThrowIfCancellationRequested();

                _company = company;

                // Calculation is CPU-bound, keep it off the main thread, then marshal back
                var projection = await Task.Run(() => _projectionService.Calculate(company), ct).ConfigureAwait(false);

                await _dispatcher.RunAsync(() =>
                {
                    CompanyName   = company.Name;
                    LogoSprite    = company.LogoSprite;
                    Revenue       = projection.Revenue;
                    Ebitda        = projection.Ebitda;
                    DebtToEquity  = projection.DebtToEquity;

                    StatusMessage = string.Empty;
                });
            }
            catch (OperationCanceledException) { /* ignore */ }
            catch (Exception ex)
            {
                _log.Error(ex, "LoadCompanyAsync failed");
                StatusMessage = _localization["generic.error"];
            }
            finally
            {
                IsBusy = false;
            }
        }

        #endregion

        #region INotifyPropertyChanged

        public event PropertyChangedEventHandler? PropertyChanged;

        private void SetField<T>(T value, [CallerMemberName] string? propertyName = null)
        {
            typeof(CompanyDetailsViewModel).GetField($"<{propertyName}>k__BackingField",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!
                .SetValue(this, value);
            OnPropertyChanged(propertyName);
        }

        private bool SetField<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
        {
            if (EqualityComparer<T>.Default.Equals(field, value)) return false;
            field = value;
            OnPropertyChanged(propertyName);
            return true;
        }

        private void OnPropertyChanged(string? propertyName)
            => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

        #endregion

        #region IDisposable

        public void Dispose()
        {
            _cancellationSource?.Cancel();
            _cancellationSource?.Dispose();
        }

        #endregion
    }
}
```