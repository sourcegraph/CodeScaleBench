```csharp
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace TycoonVerse.Application.Interfaces.Services
{
    /// <summary>
    ///     Centralized contract for all In-App Purchase (IAP) workflows in TycoonVerse.
    ///     Implementations target platform-specific stores (Google Play, App Store, etc.) via
    ///     an Adapter layer, hiding SDK peculiarities from the rest of the application.
    ///     
    ///     Design goals:
    ///     • Thread-safe, async/await friendly  
    ///     • Resilient to offline play—transactions are queued until connectivity resumes  
    ///     • Observable streams for real-time UI updates & analytics pipelines  
    ///     • Explicit, strongly-typed result models to avoid magic strings/integers  
    /// </summary>
    public interface IIAPService : IDisposable
    {
        #region Catalog & Initialization

        /// <summary>
        ///     Initializes the IAP catalog returned from the remote configuration service.
        ///     MUST be invoked before any purchase calls, typically during bootstrap.
        /// </summary>
        /// <param name="catalog">List of <see cref="CatalogProduct"/> objects.</param>
        /// <param name="cancellationToken">Token used to cancel the operation.</param>
        Task<InitializationResult> InitializeCatalogAsync(
            IReadOnlyCollection<CatalogProduct> catalog,
            CancellationToken cancellationToken = default);

        /// <summary>
        ///     Retrieves the set of purchasable products that are currently available to the player
        ///     (e.g., parental controls, regional pricing events, or subscription status can filter the list).
        /// </summary>
        Task<IReadOnlyCollection<CatalogProduct>> GetAvailableProductsAsync(
            CancellationToken cancellationToken = default);

        #endregion

        #region Purchasing

        /// <summary>
        ///     Initiates a one-time consumable or non-consumable purchase for the supplied product identifier.
        /// </summary>
        /// <param name="productId">The unique catalog identifier.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        Task<PurchaseResult> PurchaseAsync(
            string productId,
            CancellationToken cancellationToken = default);

        /// <summary>
        ///     Initiates/renews a subscription.
        /// </summary>
        /// <param name="productId">Subscription product identifier.</param>
        Task<SubscriptionResult> SubscribeAsync(
            string productId,
            CancellationToken cancellationToken = default);

        /// <summary>
        ///     Consumes a consumable product (e.g., currency pack) after the game
        ///     has successfully granted the entitlements. This acknowledges the transaction
        ///     for stores that require explicit consumption.
        /// </summary>
        /// <param name="transactionId">The store-issued transaction identifier.</param>
        Task ConsumeAsync(
            string transactionId,
            CancellationToken cancellationToken = default);

        #endregion

        #region Transaction & Queue Management

        /// <summary>
        ///     Attempts to resume or finalize all previously pending transactions.
        ///     Called automatically on app launch and when network connectivity changes.
        /// </summary>
        Task<IReadOnlyCollection<PurchaseResult>> FlushPendingTransactionsAsync(
            CancellationToken cancellationToken = default);

        /// <summary>
        ///     Returns an observable stream publishing real-time purchase lifecycle events.
        ///     Typical consumers: UI toast notifications, analytics trackers, and achievement systems.
        /// </summary>
        IObservable<PurchaseEvent> PurchaseEvents { get; }

        #endregion

        #region Verification & Status

        /// <summary>
        ///     Performs server-side receipt validation whenever feasible.  
        ///     Falls back to local validation if offline, marking the receipt for later revalidation.
        /// </summary>
        Task<ReceiptValidationResult> ValidateReceiptAsync(
            string transactionId,
            CancellationToken cancellationToken = default);

        /// <summary>
        ///     Retrieves the current subscription status for a specific product.
        ///     Useful for gating premium features behind an active subscription.
        /// </summary>
        Task<SubscriptionStatus> GetSubscriptionStatusAsync(
            string productId,
            CancellationToken cancellationToken = default);

        #endregion
    }

    #region Supporting Models

    /// <summary>
    ///     A product entry as configured in remote catalog service & platform store.
    /// </summary>
    /// <param name="Id">Unique identifier used across codebase and platform stores.</param>
    /// <param name="LocalizedTitle">Localized display name.</param>
    /// <param name="LocalizedDescription">Localized description.</param>
    /// <param name="Price">Localized price string (e.g., "$1.99").</param>
    /// <param name="CurrencyCode">ISO-4217 currency code.</param>
    /// <param name="Type">Product kind: consumable, non-consumable, or subscription.</param>
    public sealed record CatalogProduct(
        string Id,
        string LocalizedTitle,
        string LocalizedDescription,
        string Price,
        string CurrencyCode,
        ProductType Type);

    public enum ProductType
    {
        Consumable,
        NonConsumable,
        Subscription
    }

    /// <summary>
    ///     Result of an IAP system initialization call.
    /// </summary>
    public sealed record InitializationResult(
        bool Success,
        string? ErrorMessage = null);

    /// <summary>
    ///     Encapsulates the outcome of a purchase attempt.
    /// </summary>
    public sealed record PurchaseResult(
        PurchaseStatus Status,
        string ProductId,
        string? TransactionId = null,
        string? ErrorMessage = null,
        DateTimeOffset? Timestamp = null);

    public enum PurchaseStatus
    {
        Success,
        AlreadyOwned,
        Pending,
        Deferred,
        CanceledByUser,
        Failed,
        NetworkError,
        InvalidProduct
    }

    /// <summary>
    ///     Encapsulates the outcome of a subscription purchase or renewal.
    /// </summary>
    public sealed record SubscriptionResult(
        PurchaseStatus Status,
        string ProductId,
        DateTimeOffset? ExpirationDate = null,
        string? TransactionId = null,
        string? ErrorMessage = null);

    /// <summary>
    ///     Receipt validation result, abstracting platform specifics.
    /// </summary>
    public sealed record ReceiptValidationResult(
        bool IsValid,
        bool IsSandbox,
        string ProductId,
        string TransactionId,
        DateTimeOffset PurchaseDate,
        string? ErrorMessage = null);

    /// <summary>
    ///     Represents the current status of a subscription.
    /// </summary>
    public sealed record SubscriptionStatus(
        string ProductId,
        bool IsActive,
        DateTimeOffset? ExpirationDate,
        bool WillAutoRenew);

    /// <summary>
    ///     Stream event item for purchase lifecycle monitoring.
    /// </summary>
    /// <param name="Type">Event kind.</param>
    /// <param name="Result">Optional purchase result payload.</param>
    /// <param name="OccurredAt">Event timestamp.</param>
    public sealed record PurchaseEvent(
        PurchaseEventType Type,
        PurchaseResult? Result,
        DateTimeOffset OccurredAt);

    public enum PurchaseEventType
    {
        Pending,
        Completed,
        Failed,
        Deferred,
        Canceled,
        Restored
    }

    #endregion
}
```