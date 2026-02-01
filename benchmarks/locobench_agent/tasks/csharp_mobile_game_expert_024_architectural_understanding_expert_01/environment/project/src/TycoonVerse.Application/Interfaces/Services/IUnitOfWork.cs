```csharp
using System;
using System.Threading;
using System.Threading.Tasks;
using TycoonVerse.Domain.Abstractions.Events;
using TycoonVerse.Domain.Abstractions.Repositories;

namespace TycoonVerse.Application.Interfaces.Services
{
    /// <summary>
    ///     A Unit-of-Work contract that encapsulates the game’s transactional
    ///     boundaries. Implementations must guarantee atomic persistence across
    ///     all repositories and publish domain events only after a successful
    ///     commit.  Because TycoonVerse supports both on-device (offline) and
    ///     cloud-sync storage back-ends, the concrete implementation can choose
    ///     the appropriate data store at runtime.
    /// </summary>
    public interface IUnitOfWork : IDisposable, IAsyncDisposable
    {
        #region Repositories exposed as bounded contexts

        /// <summary> Repository for company aggregate roots. </summary>
        ICompanyRepository Companies { get; }

        /// <summary> Repository for player profiles and authentication snapshots. </summary>
        IPlayerRepository Players { get; }

        /// <summary> Repository for inventory items manufactured or traded by companies. </summary>
        IInventoryItemRepository InventoryItems { get; }

        /// <summary> Repository for finance-related aggregates such as ledgers,
        ///           journal entries, and transactional statements. </summary>
        IFinanceRepository Finances { get; }

        /// <summary> Repository for in-app purchases and wallet transactions. </summary>
        IInAppPurchaseRepository InAppPurchases { get; }

        /// <summary> Repository for global or regional market events
        ///           (e.g., hurricanes, tariffs, inflation spikes). </summary>
        IMarketEventRepository MarketEvents { get; }

        /// <summary> Repository for push/notification scheduling. </summary>
        INotificationRepository Notifications { get; }

        #endregion

        #region Domain Event Infrastructure

        /// <summary>
        ///     An event bus through which domain events are dispatched after the
        ///     persistence layer confirms that the transaction has been committed.
        /// </summary>
        IEventBus EventBus { get; }

        #endregion

        #region Transactional API

        /// <summary>
        ///     Returns <c>true</c> if any tracked entity has been added, modified,
        ///     or deleted since the last commit.
        /// </summary>
        bool HasPendingChanges { get; }

        /// <summary>
        ///     Saves current changes to the underlying data store without
        ///     dispatching domain events.  Use this for background jobs or
        ///     migrations where side-effects are undesirable.
        ///     
        ///     Returns the number of state entries written to the store.
        /// </summary>
        Task<int> SaveChangesAsync(CancellationToken cancellationToken = default);

        /// <summary>
        ///     Atomically persists all changes and, upon success, dispatches the
        ///     accumulated domain events through the <see cref="EventBus"/>.
        ///     
        ///     The method throws if either the persistence or the event dispatch
        ///     fails, ensuring the caller can retry via idempotent commands.
        ///     
        ///     Returns the number of state entries written to the store.
        /// </summary>
        Task<int> CommitAndDispatchAsync(CancellationToken cancellationToken = default);

        /// <summary>
        ///     Executes an arbitrary async action inside a database transaction.
        ///     Any exception thrown by <paramref name="operation"/> triggers a
        ///     rollback.  This helper simplifies application-layer workflows
        ///     where multiple service calls must be executed atomically.
        ///     
        ///     Example:
        ///     <code>
        ///     await _unitOfWork.ExecuteInTransactionAsync(async ct =>
        ///     {
        ///         await _inventoryService.TransferAsync(itemId, warehouseA, warehouseB, ct);
        ///         await _financeService.ReserveCostAsync(itemId, transferFee, ct);
        ///     }, cancellationToken);
        ///     </code>
        /// </summary>
        Task ExecuteInTransactionAsync(
            Func<CancellationToken, Task> operation,
            CancellationToken cancellationToken = default);

        #endregion
    }
}
```