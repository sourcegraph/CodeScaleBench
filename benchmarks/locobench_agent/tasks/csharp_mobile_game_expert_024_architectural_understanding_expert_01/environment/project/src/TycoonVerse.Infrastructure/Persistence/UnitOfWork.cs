using System;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Microsoft.Extensions.Logging;
using TycoonVerse.Domain.Repositories;
using TycoonVerse.Domain.SeedWork;

namespace TycoonVerse.Infrastructure.Persistence
{
    /// <summary>
    ///     Concrete implementation of the Unit-of-Work pattern.
    ///     Responsible for coordinating database transactions across multiple repositories,
    ///     guaranteeing atomicity and consistency of changes while offering
    ///     concurrency-safe commit / rollback semantics.
    /// </summary>
    public sealed class UnitOfWork : IUnitOfWork, IAsyncDisposable
    {
        private readonly TycoonVerseDbContext _context;
        private readonly ILogger<UnitOfWork> _logger;

        private IDbContextTransaction? _currentTransaction;
        private bool _disposed;

        #region Repository accessors

        public ICompanyRepository Companies { get; }
        public IInventoryRepository Inventories { get; }
        public ITransactionRepository Transactions { get; }
        public IPlayerRepository Players { get; }

        #endregion

        public UnitOfWork(
            TycoonVerseDbContext context,
            ILogger<UnitOfWork> logger,
            ICompanyRepository companyRepository,
            IInventoryRepository inventoryRepository,
            ITransactionRepository transactionRepository,
            IPlayerRepository playerRepository)
        {
            _context             = context  ?? throw new ArgumentNullException(nameof(context));
            _logger              = logger   ?? throw new ArgumentNullException(nameof(logger));
            Companies            = companyRepository   ?? throw new ArgumentNullException(nameof(companyRepository));
            Inventories          = inventoryRepository ?? throw new ArgumentNullException(nameof(inventoryRepository));
            Transactions         = transactionRepository ?? throw new ArgumentNullException(nameof(transactionRepository));
            Players              = playerRepository  ?? throw new ArgumentNullException(nameof(playerRepository));
        }

        #region Transaction management

        /// <inheritdoc />
        public async Task BeginTransactionAsync(CancellationToken cancellationToken = default)
        {
            ThrowIfDisposed();

            if (_currentTransaction is not null)
            {
                _logger.LogWarning(
                    "Transaction requested while another is active. Nested transactions are not supported. Ignoring request.");
                return;
            }

            _currentTransaction = await _context.Database
                                               .BeginTransactionAsync(cancellationToken)
                                               .ConfigureAwait(false);

            _logger.LogDebug("Database transaction started ({TransactionId}).", _currentTransaction.TransactionId);
        }

        /// <inheritdoc />
        public async Task CommitAsync(CancellationToken cancellationToken = default)
        {
            ThrowIfDisposed();

            if (_currentTransaction is null)
            {
                _logger.LogWarning("Commit requested without an active transaction. Operation ignored.");
                return;
            }

            try
            {
                await SaveChangesInternalAsync(cancellationToken).ConfigureAwait(false);

                await _currentTransaction
                    .CommitAsync(cancellationToken)
                    .ConfigureAwait(false);

                _logger.LogDebug("Transaction committed ({TransactionId}).", _currentTransaction.TransactionId);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Commit failed. Rolling back transaction ({TransactionId}).",
                                 _currentTransaction.TransactionId);

                await RollbackAsync(cancellationToken).ConfigureAwait(false);
                throw;
            }
            finally
            {
                await DisposeCurrentTransactionAsync().ConfigureAwait(false);
            }
        }

        /// <inheritdoc />
        public async Task RollbackAsync(CancellationToken cancellationToken = default)
        {
            ThrowIfDisposed();

            if (_currentTransaction is null)
            {
                _logger.LogWarning("Rollback requested without an active transaction. Operation ignored.");
                return;
            }

            try
            {
                await _currentTransaction
                    .RollbackAsync(cancellationToken)
                    .ConfigureAwait(false);

                _logger.LogInformation("Transaction rolled back ({TransactionId}).",
                                       _currentTransaction.TransactionId);
            }
            finally
            {
                await DisposeCurrentTransactionAsync().ConfigureAwait(false);
            }
        }

        #endregion

        #region Persistence

        /// <inheritdoc />
        public async Task<int> SaveChangesAsync(CancellationToken cancellationToken = default)
        {
            ThrowIfDisposed();

            if (_currentTransaction is null)
            {
                // No explicit transaction ongoing; save immediately.
                return await SaveChangesInternalAsync(cancellationToken).ConfigureAwait(false);
            }

            // Inside explicit transaction; defer to Commit.
            return 0;
        }

        private async Task<int> SaveChangesInternalAsync(CancellationToken cancellationToken)
        {
            try
            {
                var rows = await _context
                                 .SaveChangesAsync(cancellationToken)
                                 .ConfigureAwait(false);

                _logger.LogTrace("EF Core saved {RowCount} changes.", rows);

                return rows;
            }
            catch (DbUpdateConcurrencyException ex)
            {
                _logger.LogWarning(ex,
                                   "Concurrency conflict detected during SaveChanges. "
                                   + "Exception will be re-thrown to the caller.");
                throw;
            }
            catch (DbUpdateException ex)
            {
                _logger.LogError(ex, "Database update exception encountered.");
                throw;
            }
        }

        #endregion

        #region IDisposable / IAsyncDisposable

        private async Task DisposeCurrentTransactionAsync()
        {
            if (_currentTransaction is null) return;

            await _currentTransaction.DisposeAsync().ConfigureAwait(false);
            _currentTransaction = null;
        }

        private void ThrowIfDisposed()
        {
            if (_disposed)
                throw new ObjectDisposedException(nameof(UnitOfWork),
                                                  "Attempted to use UnitOfWork after it has been disposed.");
        }

        public async ValueTask DisposeAsync()
        {
            if (_disposed) return;

            _disposed = true;

            try
            {
                await DisposeCurrentTransactionAsync().ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error disposing current transaction.");
            }

            await _context.DisposeAsync().ConfigureAwait(false);

            _logger.LogDebug("UnitOfWork disposed.");
        }

        #endregion
    }
}

