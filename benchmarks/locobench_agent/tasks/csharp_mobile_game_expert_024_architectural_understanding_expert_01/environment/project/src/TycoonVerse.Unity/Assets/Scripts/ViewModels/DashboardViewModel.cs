```csharp
using System;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Input;                              // ICommand
using Microsoft.Extensions.Logging;
using TycoonVerse.Domain.Models;
using TycoonVerse.Domain.Services;
using TycoonVerse.Infrastructure;
using TycoonVerse.Infrastructure.Analytics;
using TycoonVerse.Infrastructure.Connectivity;
using TycoonVerse.Infrastructure.IAP;

namespace TycoonVerse.Unity.ViewModels
{
    /// <summary>
    ///     View-model that powers the main player dashboard.  Aggregates live
    ///     KPIs from multiple domain services and exposes them as bindable
    ///     properties for Unity UI presenters.
    /// </summary>
    public sealed class DashboardViewModel : INotifyPropertyChanged, IDisposable
    {
        #region Dependencies ---------------------------------------------------

        private readonly IPlayerRepository       _playerRepository;
        private readonly IFinancialService       _financialService;
        private readonly IConnectivityService    _connectivityService;
        private readonly IAnalyticsService       _analyticsService;
        private readonly IInAppPurchaseService   _iapService;
        private readonly ILogger<DashboardViewModel> _logger;

        #endregion

        #region Fields ---------------------------------------------------------

        private readonly CancellationTokenSource _cts = new CancellationTokenSource();

        private decimal _cashOnHand;
        private decimal _ebitda;
        private decimal _debtToEquity;
        private float   _inventoryTurnover;
        private DateTime _lastSyncUtc;
        private ConnectivityState _connectivityState = ConnectivityState.Unknown;

        #endregion

        #region Constructors ---------------------------------------------------

        public DashboardViewModel(IPlayerRepository playerRepository,
                                  IFinancialService financialService,
                                  IConnectivityService connectivityService,
                                  IAnalyticsService analyticsService,
                                  IInAppPurchaseService iapService,
                                  ILogger<DashboardViewModel> logger)
        {
            _playerRepository    = playerRepository  ?? throw new ArgumentNullException(nameof(playerRepository));
            _financialService    = financialService  ?? throw new ArgumentNullException(nameof(financialService));
            _connectivityService = connectivityService ?? throw new ArgumentNullException(nameof(connectivityService));
            _analyticsService    = analyticsService  ?? throw new ArgumentNullException(nameof(analyticsService));
            _iapService          = iapService        ?? throw new ArgumentNullException(nameof(iapService));
            _logger              = logger            ?? throw new ArgumentNullException(nameof(logger));

            RefreshCommand       = new AsyncRelayCommand(RefreshAsync, CanRefresh);
            PurchaseCoinsCommand = new AsyncRelayCommand(PurchaseCoinsAsync, () => true);
            OpenReportsCommand   = new RelayCommand(OpenReports, () => true);

            _connectivityService.ConnectivityChanged += OnConnectivityChanged;

            // Kick off background polling loop
            _ = RunPollingLoopAsync(_cts.Token);
        }

        #endregion

        #region Bindable Properties -------------------------------------------

        public decimal CashOnHand
        {
            get => _cashOnHand;
            private set => Set(ref _cashOnHand, value);
        }

        public decimal EBITDA
        {
            get => _ebitda;
            private set => Set(ref _ebitda, value);
        }

        public decimal DebtToEquity
        {
            get => _debtToEquity;
            private set => Set(ref _debtToEquity, value);
        }

        public float InventoryTurnover
        {
            get => _inventoryTurnover;
            private set => Set(ref _inventoryTurnover, value);
        }

        public DateTime LastSyncUtc
        {
            get => _lastSyncUtc;
            private set => Set(ref _lastSyncUtc, value);
        }

        public ConnectivityState ConnectivityState
        {
            get => _connectivityState;
            private set => Set(ref _connectivityState, value);
        }

        #endregion

        #region Commands -------------------------------------------------------

        public ICommand RefreshCommand       { get; }
        public ICommand PurchaseCoinsCommand { get; }
        public ICommand OpenReportsCommand   { get; }

        #endregion

        #region Private Polling -----------------------------------------------

        private async Task RunPollingLoopAsync(CancellationToken token)
        {
            _logger.LogInformation("Dashboard polling loop started.");

            while (!token.IsCancellationRequested)
            {
                try
                {
                    await RefreshAsync();

                    // Poll every 5 seconds
                    await Task.Delay(TimeSpan.FromSeconds(5), token);
                }
                catch (OperationCanceledException)
                {
                    // Ignore; shutting down
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Unexpected error in Dashboard polling loop.");
                    await Task.Delay(TimeSpan.FromSeconds(10), token); // back-off
                }
            }

            _logger.LogInformation("Dashboard polling loop terminated.");
        }

        #endregion

        #region Refresh  -------------------------------------------------------

        private bool CanRefresh() => ConnectivityState != ConnectivityState.Offline;

        private async Task RefreshAsync()
        {
            try
            {
                var playerId = _playerRepository.CurrentPlayerId;
                if (playerId == Guid.Empty) return;

                var snapshot = await _financialService.GetSnapshotAsync(playerId, _cts.Token);

                CashOnHand         = snapshot.CashOnHand;
                EBITDA             = snapshot.EBITDA;
                DebtToEquity       = snapshot.DebtToEquityRatio;
                InventoryTurnover  = snapshot.InventoryTurnover;

                LastSyncUtc        = DateTime.UtcNow;

                _analyticsService.RecordEvent("dashboard_refresh");

                (RefreshCommand as AsyncRelayCommand)?.RaiseCanExecuteChanged();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to refresh dashboard data.");
                _analyticsService.RecordException(ex);
            }
        }

        #endregion

        #region IAP ------------------------------------------------------------

        private async Task PurchaseCoinsAsync()
        {
            const string productId = "coins_pack_1000";

            try
            {
                var result = await _iapService.PurchaseAsync(productId, _cts.Token);
                if (result.Success)
                {
                    _logger.LogInformation("Coins purchased successfully.");
                    await RefreshAsync();
                }
                else
                {
                    _logger.LogWarning("Coins purchase failed: {Reason}", result.ErrorMessage);
                }

                _analyticsService.RecordEvent("iap_coins_attempt", ("success", result.Success.ToString()));
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Coins purchase threw exception.");
                _analyticsService.RecordException(ex);
            }
        }

        #endregion

        #region Reports --------------------------------------------------------

        private void OpenReports()
        {
            try
            {
                // The view is resolved via Unity UI navigation layer
                _analyticsService.RecordEvent("open_reports_clicked");
                UnityNavigator.NavigateTo("ReportsView");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "OpenReports failed.");
            }
        }

        #endregion

        #region Connectivity ---------------------------------------------------

        private void OnConnectivityChanged(object? sender, ConnectivityState state)
        {
            ConnectivityState = state;
            (RefreshCommand as AsyncRelayCommand)?.RaiseCanExecuteChanged();

            if (state == ConnectivityState.Online)
            {
                _ = RefreshAsync(); // Fire-and-forget refresh on regain
            }
        }

        #endregion

        #region INotifyPropertyChanged ----------------------------------------

        public event PropertyChangedEventHandler? PropertyChanged;

        private void Set<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
        {
            if (Equals(field, value)) return;
            field = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }

        #endregion

        #region IDisposable ----------------------------------------------------

        public void Dispose()
        {
            _cts.Cancel();
            _cts.Dispose();
            _connectivityService.ConnectivityChanged -= OnConnectivityChanged;
            GC.SuppressFinalize(this);
        }

        #endregion
    }

    #region Supporting Command Helpers ----------------------------------------

    /// <summary>
    ///     ICommand implementation for synchronous actions.
    /// </summary>
    internal sealed class RelayCommand : ICommand
    {
        private readonly Action _execute;
        private readonly Func<bool> _canExecute;

        public RelayCommand(Action execute, Func<bool> canExecute)
        {
            _execute    = execute  ?? throw new ArgumentNullException(nameof(execute));
            _canExecute = canExecute ?? (() => true);
        }

        public bool CanExecute(object? parameter) => _canExecute();

        public void Execute(object? parameter) => _execute();

        public event EventHandler? CanExecuteChanged;

        public void RaiseCanExecuteChanged() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>
    ///     ICommand implementation for asynchronous actions
    ///     that handles error reporting internally.
    /// </summary>
    internal sealed class AsyncRelayCommand : ICommand
    {
        private readonly Func<Task> _executeAsync;
        private readonly Func<bool> _canExecute;
        private bool _isExecuting;

        public AsyncRelayCommand(Func<Task> executeAsync, Func<bool> canExecute)
        {
            _executeAsync = executeAsync ?? throw new ArgumentNullException(nameof(executeAsync));
            _canExecute   = canExecute   ?? (() => true);
        }

        public bool CanExecute(object? parameter) => !_isExecuting && _canExecute();

        public async void Execute(object? parameter)
        {
            if (!CanExecute(parameter)) return;

            _isExecuting = true;
            RaiseCanExecuteChanged();

            try
            {
                await _executeAsync();
            }
            finally
            {
                _isExecuting = false;
                RaiseCanExecuteChanged();
            }
        }

        public event EventHandler? CanExecuteChanged;

        public void RaiseCanExecuteChanged() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);
    }

    #endregion
}
```