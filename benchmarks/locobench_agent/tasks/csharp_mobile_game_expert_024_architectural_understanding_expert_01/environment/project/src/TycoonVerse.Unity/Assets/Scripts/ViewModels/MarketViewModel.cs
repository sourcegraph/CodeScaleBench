```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright file="MarketViewModel.cs" company="TycoonVerse">
//   Copyright (c) TycoonVerse. 
//   Licensed under the Unity Companion License. See LICENSE in the project root for license information.
// </copyright>
// <summary>
//   View-model for the in-game global marketplace dashboard.
//   Exposes live market listings, wallet state, and trading commands to Unity UI layers.
// </summary>
// --------------------------------------------------------------------------------------------------------------------

#nullable enable

using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using TycoonVerse.Domain.Market;
using TycoonVerse.Domain.Market.Models;
using TycoonVerse.Domain.Player;
using TycoonVerse.Infrastructure.Connectivity;
using TycoonVerse.Infrastructure.Logging;
using TycoonVerse.Shared;
using UnityEngine;

namespace TycoonVerse.Unity.ViewModels
{
    /// <summary>
    ///     MVVM view-model that orchestrates interactions between the Unity presentation layer and the domain-level
    ///     market services. Handles offline buffering, connectivity changes, and error propagation.
    /// </summary>
    public sealed class MarketViewModel : INotifyPropertyChanged, IDisposable
    {
        // Dependencies injected via constructor (Zenject or another DI container)
        private readonly IMarketService _marketService;
        private readonly IWalletService _walletService;
        private readonly IConnectivityService _connectivityService;
        private readonly ICrashLogger _crashLogger;
        private readonly CancellationTokenSource _disposeCts = new();

        // Backing fields
        private bool _isBusy;
        private string? _errorMessage;
        private decimal _walletBalance;

        /// <summary>
        ///     Creates a new instance of the market view-model.
        /// </summary>
        public MarketViewModel(
            IMarketService marketService,
            IWalletService walletService,
            IConnectivityService connectivityService,
            ICrashLogger crashLogger)
        {
            _marketService = marketService ?? throw new ArgumentNullException(nameof(marketService));
            _walletService = walletService ?? throw new ArgumentNullException(nameof(walletService));
            _connectivityService = connectivityService ?? throw new ArgumentNullException(nameof(connectivityService));
            _crashLogger = crashLogger ?? throw new ArgumentNullException(nameof(crashLogger));

            Listings = new ObservableCollection<MarketListingViewModel>();

            BuyCommand = new AsyncRelayCommand<MarketListingViewModel>(ExecuteBuyAsync, CanExecuteTrade);
            SellCommand = new AsyncRelayCommand<MarketListingViewModel>(ExecuteSellAsync, CanExecuteTrade);
            RefreshCommand = new AsyncRelayCommand(LoadMarketAsync);

            // Subscribe to connectivity changes for automatic sync.
            _connectivityService.ConnectivityChanged += OnConnectivityChanged;
        }

        #region Public API ---------------------------------------------------------------------

        /// <summary>
        ///     Observable collection bound to the UI list-view that shows current market listings.
        /// </summary>
        public ObservableCollection<MarketListingViewModel> Listings { get; }

        /// <summary>
        ///     Indicates whether a background operation is running (e.g., network fetch, purchase execution).
        /// </summary>
        public bool IsBusy
        {
            get => _isBusy;
            private set => SetProperty(ref _isBusy, value);
        }

        /// <summary>
        ///     Human-readable error message to be displayed in the UI. Null or empty when there is no error.
        /// </summary>
        public string? ErrorMessage
        {
            get => _errorMessage;
            private set => SetProperty(ref _errorMessage, value);
        }

        /// <summary>
        ///     Player's current wallet balance in in-game currency.
        /// </summary>
        public decimal WalletBalance
        {
            get => _walletBalance;
            private set
            {
                if (SetProperty(ref _walletBalance, value))
                {
                    // Update CanExecute state for trading commands when balance changes.
                    BuyCommand.RaiseCanExecuteChanged();
                    SellCommand.RaiseCanExecuteChanged();
                }
            }
        }

        /// <summary>
        ///     Command that refreshes the market listings.
        /// </summary>
        public AsyncRelayCommand RefreshCommand { get; }

        /// <summary>
        ///     Command that executes a BUY order for the selected <see cref="MarketListingViewModel"/>.
        /// </summary>
        public AsyncRelayCommand<MarketListingViewModel> BuyCommand { get; }

        /// <summary>
        ///     Command that executes a SELL order for the selected <see cref="MarketListingViewModel"/>.
        /// </summary>
        public AsyncRelayCommand<MarketListingViewModel> SellCommand { get; }

        /// <summary>
        ///     Initializes the view-model by loading wallet state and market listings.
        ///     Should be awaited once by the view (e.g., from a MonoBehaviour Awake/Start).
        /// </summary>
        public async Task InitializeAsync(CancellationToken externalToken = default)
        {
            using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(_disposeCts.Token, externalToken);
            await LoadWalletAsync(linkedCts.Token).ConfigureAwait(false);
            await LoadMarketAsync(linkedCts.Token).ConfigureAwait(false);
        }

        #endregion --------------------------------------------------------------------------------

        #region Private helpers -----------------------------------------------------------------

        private async Task LoadMarketAsync(CancellationToken token = default)
        {
            if (IsBusy) return;

            try
            {
                IsBusy = true;
                ErrorMessage = null;

                IEnumerable<MarketListing> listings =
                    await _marketService.GetGlobalListingsAsync(token).ConfigureAwait(false);

                // Marshal to Unity main thread if necessary
                UnityMainThread.Post(() =>
                {
                    Listings.Clear();
                    foreach (MarketListing listing in listings)
                    {
                        Listings.Add(new MarketListingViewModel(listing));
                    }
                });
            }
            catch (OperationCanceledException)
            {
                // Ignore expected cancellation
            }
            catch (Exception ex)
            {
                HandleError("Failed to load market listings.", ex);
            }
            finally
            {
                IsBusy = false;
            }
        }

        private async Task LoadWalletAsync(CancellationToken token = default)
        {
            try
            {
                WalletBalance = await _walletService.GetCurrentBalanceAsync(token).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                HandleError("Failed to load wallet balance.", ex);
            }
        }

        private bool CanExecuteTrade(MarketListingViewModel? listing)
        {
            if (listing is null) return false;
            if (IsBusy) return false;

            // For BUY, ensure balance is sufficient; for SELL we assume player owns inventory.
            return true;
        }

        private async Task ExecuteBuyAsync(MarketListingViewModel? listing, CancellationToken token)
        {
            if (listing is null) return;

            try
            {
                IsBusy = true;
                ErrorMessage = null;

                await _marketService.BuyAsync(listing.ListingId, token).ConfigureAwait(false);

                // Update local wallet balance immediately for responsiveness.
                WalletBalance -= listing.Price;

                // Notify UI that the listing may have changed (quantity, price).
                await LoadMarketAsync(token).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                HandleError("Purchase failed.", ex);
            }
            finally
            {
                IsBusy = false;
            }
        }

        private async Task ExecuteSellAsync(MarketListingViewModel? listing, CancellationToken token)
        {
            if (listing is null) return;

            try
            {
                IsBusy = true;
                ErrorMessage = null;

                await _marketService.SellAsync(listing.ListingId, token).ConfigureAwait(false);

                WalletBalance += listing.Price;

                await LoadMarketAsync(token).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                HandleError("Sale failed.", ex);
            }
            finally
            {
                IsBusy = false;
            }
        }

        private void OnConnectivityChanged(object? sender, ConnectivityChangedEventArgs e)
        {
            if (!e.IsConnected) return;

            // Fire and forget, rely on internal exception handling.
            _ = SyncPendingOrdersAsync(_disposeCts.Token);
        }

        private async Task SyncPendingOrdersAsync(CancellationToken token)
        {
            try
            {
                IsBusy = true;
                await _marketService.SyncPendingOrdersAsync(token).ConfigureAwait(false);
                await LoadWalletAsync(token).ConfigureAwait(false);
                await LoadMarketAsync(token).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                HandleError("Failed to synchronize offline trades.", ex);
            }
            finally
            {
                IsBusy = false;
            }
        }

        private void HandleError(string userFriendlyMessage, Exception ex)
        {
            ErrorMessage = userFriendlyMessage;
            _crashLogger.LogException(ex);

#if UNITY_EDITOR
            Debug.LogException(ex);
#endif
        }

        #endregion --------------------------------------------------------------------------------

        #region IDisposable / INotifyPropertyChanged ---------------------------------------------

        public event PropertyChangedEventHandler? PropertyChanged;

        private void SetProperty<T>(ref T storage, T value, [CallerMemberName] string? propertyName = null)
        {
            if (EqualityComparer<T>.Default.Equals(storage, value)) return;
            storage = value;
            OnPropertyChanged(propertyName);
        }

        private void OnPropertyChanged(string? propertyName)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }

        public void Dispose()
        {
            _disposeCts.Cancel();
            _disposeCts.Dispose();
            _connectivityService.ConnectivityChanged -= OnConnectivityChanged;
            RefreshCommand.Dispose();
            BuyCommand.Dispose();
            SellCommand.Dispose();
        }

        #endregion --------------------------------------------------------------------------------
    }

    #region Nested helper classes ---------------------------------------------------------------

    /// <summary>
    ///     Lightweight view-model representing a single market listing for binding in UI cells.
    /// </summary>
    public sealed class MarketListingViewModel
    {
        public MarketListingViewModel(MarketListing listing)
        {
            ListingId = listing.Id;
            ProductName = listing.ProductName;
            Price = listing.Price;
            AvailableQuantity = listing.AvailableQuantity;
            Industry = listing.Industry;
        }

        public Guid ListingId { get; }
        public string ProductName { get; }
        public decimal Price { get; }
        public int AvailableQuantity { get; }
        public string Industry { get; }
    }

    /// <summary>
    ///     A simple async command implementation suitable for Unity.
    /// </summary>
    public sealed class AsyncRelayCommand : AsyncRelayCommand<object>
    {
        public AsyncRelayCommand(Func<CancellationToken, Task> execute,
            Func<bool>? canExecute = null)
            : base(_ => execute(default), _ => canExecute?.Invoke() ?? true)
        {
        }

        public AsyncRelayCommand(Func<CancellationToken, Task> execute,
            Func<object?, bool>? canExecute = null)
            : base(_ => execute(default), canExecute ?? (_ => true))
        {
        }
    }

    public sealed class AsyncRelayCommand<T> : IDisposable
    {
        private readonly Func<T?, CancellationToken, Task> _execute;
        private readonly Func<T?, bool> _canExecute;
        private readonly CancellationTokenSource _cts = new();

        private bool _isExecuting;

        public AsyncRelayCommand(Func<T?, CancellationToken, Task> execute,
            Func<T?, bool> canExecute)
        {
            _execute = execute ?? throw new ArgumentNullException(nameof(execute));
            _canExecute = canExecute ?? throw new ArgumentNullException(nameof(canExecute));
        }

        public bool CanExecute(T? parameter)
        {
            return !_isExecuting && _canExecute(parameter);
        }

        public async void Execute(T? parameter)
        {
            if (!CanExecute(parameter)) return;

            try
            {
                _isExecuting = true;
                RaiseCanExecuteChanged();

                await _execute(parameter, _cts.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // No-op
            }
            catch (Exception ex)
            {
#if UNITY_EDITOR
                Debug.LogException(ex);
#endif
            }
            finally
            {
                _isExecuting = false;
                RaiseCanExecuteChanged();
            }
        }

        public event EventHandler? CanExecuteChanged;

        public void RaiseCanExecuteChanged() => CanExecuteChanged?.Invoke(this, EventArgs.Empty);

        public void Dispose() => _cts.Cancel();
    }

    #endregion ----------------------------------------------------------------------------------
}
```