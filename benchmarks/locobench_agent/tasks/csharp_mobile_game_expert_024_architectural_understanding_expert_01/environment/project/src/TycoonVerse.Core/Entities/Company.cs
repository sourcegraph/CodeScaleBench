```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;

namespace TycoonVerse.Core.Entities
{
    #region Supporting abstractions ---------------------------------------------------------------

    /// <summary>
    /// Marker interface for Domain-Driven Design aggregate roots.
    /// </summary>
    public interface IAggregateRoot { }

    /// <summary>
    /// Simple value object representing an amount of money in a specific currency.
    /// </summary>
    public readonly struct Money : IEquatable<Money>, IComparable<Money>
    {
        public decimal Amount { get; }
        public string Currency { get; }

        public static readonly Money Zero = new Money(0m, "USD");

        public Money(decimal amount, string currency)
        {
            if (string.IsNullOrWhiteSpace(currency))
                throw new ArgumentException("Currency must be provided.", nameof(currency));

            Amount   = decimal.Round(amount, 2, MidpointRounding.AwayFromZero);
            Currency = currency.ToUpperInvariant();
        }

        public Money Add(Money other)
        {
            EnsureSameCurrency(other);
            return new Money(Amount + other.Amount, Currency);
        }

        public Money Subtract(Money other)
        {
            EnsureSameCurrency(other);
            return new Money(Amount - other.Amount, Currency);
        }

        private void EnsureSameCurrency(Money other)
        {
            if (Currency != other.Currency)
                throw new InvalidOperationException("Currency mismatch.");
        }

        #region Equality & Comparison

        public bool Equals(Money other) => Amount == other.Amount && Currency == other.Currency;
        public override bool Equals(object? obj) => obj is Money other && Equals(other);
        public override int GetHashCode() => HashCode.Combine(Amount, Currency);
        public int CompareTo(Money other)
        {
            EnsureSameCurrency(other);
            return Amount.CompareTo(other.Amount);
        }

        public static Money operator +(Money a, Money b) => a.Add(b);
        public static Money operator -(Money a, Money b) => a.Subtract(b);
        public static bool operator >(Money a, Money b) => a.CompareTo(b) > 0;
        public static bool operator <(Money a, Money b) => a.CompareTo(b) < 0;
        public static bool operator >=(Money a, Money b) => a.CompareTo(b) >= 0;
        public static bool operator <=(Money a, Money b) => a.CompareTo(b) <= 0;
        public override string ToString() => $"{Amount:n2} {Currency}";
        #endregion
    }

    /// <summary>
    /// Generic domain event contract for the observer pattern.
    /// </summary>
    public interface IDomainEvent { }

    /// <summary>
    /// Observer contract for company events.
    /// </summary>
    public interface ICompanyObserver
    {
        void OnEvent(IDomainEvent @event);
    }

    #endregion Supporting abstractions ------------------------------------------------------------

    /// <summary>
    ///     Core aggregate root representing a company within the TycoonVerse world.
    /// </summary>
    /// <remarks>
    ///     Because companies are mutated frequently (financial ticks, acquisitions, taxes, etc.)
    ///     internal state is guarded by a <see cref="ReaderWriterLockSlim"/> to avoid race
    ///     conditions when running simulations on background threads.
    /// </remarks>
    public sealed class Company : IAggregateRoot, IDisposable
    {
        private readonly ReaderWriterLockSlim _lock          = new(LockRecursionPolicy.NoRecursion);
        private readonly List<Company>        _subsidiaries  = new();
        private readonly ConcurrentQueue<IDomainEvent> _uncommittedEvents = new();
        private readonly HashSet<ICompanyObserver>    _observers         = new();

        #region Construction ----------------------------------------------------------------------

        public Company(string legalName,
                       Industry sector,
                       DateTime foundedOn,
                       string countryCode,
                       Guid? id                   = null,
                       CompanyStatus initialState = CompanyStatus.Private)
        {
            if (string.IsNullOrWhiteSpace(legalName))
                throw new ArgumentException("Legal name must be provided.", nameof(legalName));

            Id            = id ?? Guid.NewGuid();
            LegalName     = legalName;
            Sector        = sector;
            FoundedOn     = foundedOn.Date;
            CountryCode   = countryCode.ToUpperInvariant();
            Status        = initialState;

            CashOnHand    = Money.Zero;
            TotalDebt     = Money.Zero;
            TotalEquity   = Money.Zero;
        }

        #endregion

        #region Public properties -----------------------------------------------------------------

        public Guid           Id            { get; }
        public string         LegalName     { get; private set; }
        public Industry       Sector        { get; private set; }
        public string         CountryCode   { get; private set; }
        public CompanyStatus  Status        { get; private set; }
        public DateTime       FoundedOn     { get; private set; }

        public Money          CashOnHand    { get; private set; }
        public Money          TotalDebt     { get; private set; }
        public Money          TotalEquity   { get; private set; }

        public IReadOnlyCollection<Company> Subsidiaries
        {
            get
            {
                _lock.EnterReadLock();
                try { return _subsidiaries.ToList().AsReadOnly(); }
                finally { _lock.ExitReadLock(); }
            }
        }

        /// <summary>
        /// Domain events generated since the last commit.
        /// </summary>
        public IReadOnlyCollection<IDomainEvent> UncommittedEvents => _uncommittedEvents.ToList().AsReadOnly();

        #endregion

        #region Financial operations ---------------------------------------------------------------

        /// <summary>
        /// Deposits cash into the company (e.g., revenue, capital raise).
        /// </summary>
        public void Deposit(Money amount, string memo = "Deposit")
        {
            if (amount.Amount <= 0) throw new ArgumentOutOfRangeException(nameof(amount));

            ExecuteWrite(() =>
            {
                CashOnHand = CashOnHand + amount;
                RecordEvent(new CashDepositedEvent(Id, amount, memo, DateTime.UtcNow));
            });
        }

        /// <summary>
        /// Withdraws cash from the company (e.g., expense, asset purchase).
        /// </summary>
        public void Withdraw(Money amount, string memo = "Withdrawal")
        {
            if (amount.Amount <= 0) throw new ArgumentOutOfRangeException(nameof(amount));

            ExecuteWrite(() =>
            {
                if (CashOnHand < amount)
                    throw new InvalidOperationException("Insufficient funds.");

                CashOnHand = CashOnHand - amount;
                RecordEvent(new CashWithdrawnEvent(Id, amount, memo, DateTime.UtcNow));
            });
        }

        /// <summary>
        /// Adds debt to the balance sheet.
        /// </summary>
        public void IncurDebt(Money principal, string lender)
        {
            if (principal.Amount <= 0) throw new ArgumentOutOfRangeException(nameof(principal));

            ExecuteWrite(() =>
            {
                TotalDebt  = TotalDebt + principal;
                CashOnHand = CashOnHand + principal;
                RecordEvent(new DebtIncurredEvent(Id, principal, lender, DateTime.UtcNow));
            });
        }

        /// <summary>
        /// Pays down existing debt from cash reserves.
        /// </summary>
        public void RepayDebt(Money amount, string lender)
        {
            if (amount.Amount <= 0) throw new ArgumentOutOfRangeException(nameof(amount));

            ExecuteWrite(() =>
            {
                if (CashOnHand < amount)          throw new InvalidOperationException("Insufficient funds.");
                if (TotalDebt < amount)           throw new InvalidOperationException("Amount exceeds outstanding debt.");

                CashOnHand = CashOnHand - amount;
                TotalDebt  = TotalDebt  - amount;
                RecordEvent(new DebtRepaidEvent(Id, amount, lender, DateTime.UtcNow));
            });
        }

        /// <summary>
        /// Issues equity to raise capital.  Debt-to-equity ratios in the simulation will react accordingly.
        /// </summary>
        public void IssueEquity(Money raiseAmount, string series = "Series-A")
        {
            if (raiseAmount.Amount <= 0) throw new ArgumentOutOfRangeException(nameof(raiseAmount));

            ExecuteWrite(() =>
            {
                CashOnHand  = CashOnHand  + raiseAmount;
                TotalEquity = TotalEquity + raiseAmount;
                RecordEvent(new EquityIssuedEvent(Id, raiseAmount, series, DateTime.UtcNow));
            });
        }

        #endregion Financial operations ------------------------------------------------------------

        #region Structural operations --------------------------------------------------------------

        /// <summary>
        /// Acquires a target company and adds it as a subsidiary while settling the transaction from cash reserves.
        /// </summary>
        public void Acquire(Company target, Money purchasePrice)
        {
            if (target == null)                 throw new ArgumentNullException(nameof(target));
            if (ReferenceEquals(this, target))  throw new InvalidOperationException("A company cannot acquire itself.");
            if (purchasePrice.Amount <= 0)      throw new ArgumentOutOfRangeException(nameof(purchasePrice));

            ExecuteWrite(() =>
            {
                if (CashOnHand < purchasePrice)
                    throw new InvalidOperationException($"Insufficient funds to acquire {target.LegalName}.");

                // 1. Transfer cash to seller (simplified).
                CashOnHand = CashOnHand - purchasePrice;

                // 2. Integrate subsidiary.
                _lock.EnterWriteLock();
                try { _subsidiaries.Add(target); }
                finally { _lock.ExitWriteLock(); }

                // 3. Emit event for simulation engine.
                RecordEvent(new CompanyAcquiredEvent(Id, target.Id, purchasePrice, DateTime.UtcNow));
            });
        }

        /// <summary>
        /// Files for an IPO, converting the company's status to <see cref="CompanyStatus.Public"/>.
        /// </summary>
        public void FileInitialPublicOffering(DateTime filingDate, Money expectedRaise)
        {
            if (Status == CompanyStatus.Public)
                throw new InvalidOperationException("Company is already public.");

            if (expectedRaise.Amount <= 0)
                throw new ArgumentOutOfRangeException(nameof(expectedRaise));

            ExecuteWrite(() =>
            {
                Status      = CompanyStatus.PendingIPO;
                RecordEvent(new IpoFiledEvent(Id, filingDate, expectedRaise));
            });
        }

        /// <summary>
        /// Completes the IPO, injecting capital and updating status.
        /// </summary>
        public void ListOnExchange(DateTime listingDate, Money actualRaise)
        {
            if (Status != CompanyStatus.PendingIPO)
                throw new InvalidOperationException("Company is not in IPO process.");

            ExecuteWrite(() =>
            {
                Status      = CompanyStatus.Public;
                CashOnHand  = CashOnHand  + actualRaise;
                TotalEquity = TotalEquity + actualRaise;

                RecordEvent(new IpoListedEvent(Id, listingDate, actualRaise));
            });
        }

        #endregion Structural operations -----------------------------------------------------------

        #region Observer pattern -------------------------------------------------------------------

        public void Subscribe(ICompanyObserver observer)
        {
            if (observer == null) throw new ArgumentNullException(nameof(observer));
            _observers.Add(observer);
        }

        public void Unsubscribe(ICompanyObserver observer) => _observers.Remove(observer);

        private void RecordEvent(IDomainEvent @event)
        {
            _uncommittedEvents.Enqueue(@event);

            // Fire-and-forget notifications; exceptions should not bubble to domain logic.
            foreach (var observer in _observers)
            {
                try { observer.OnEvent(@event); }
                catch (Exception ex)
                {
                    // In production, forward to crash-reporting layer or logger.
                    System.Diagnostics.Debug.WriteLine($"[Company] Observer failed: {ex}");
                }
            }
        }

        /// <summary>
        /// Clears uncommitted events after a repository has persisted them.
        /// </summary>
        internal void CommitEvents()
        {
            while (_uncommittedEvents.TryDequeue(out _)) { /* discard */ }
        }

        #endregion Observer pattern ----------------------------------------------------------------

        #region Private helpers --------------------------------------------------------------------

        private void ExecuteWrite(Action action)
        {
            _lock.EnterWriteLock();
            try { action(); }
            finally { _lock.ExitWriteLock(); }
        }

        #endregion

        #region IDisposable ------------------------------------------------------------------------

        public void Dispose()
        {
            _lock?.Dispose();
            GC.SuppressFinalize(this);
        }

        #endregion
    }

    #region Enumerations --------------------------------------------------------------------------

    public enum CompanyStatus
    {
        Private,
        PendingIPO,
        Public,
        Liquidated
    }

    public enum Industry
    {
        ConsumerGoods,
        Technology,
        Healthcare,
        Energy,
        Financial,
        Industrial,
        RealEstate,
        Transportation,
        Hospitality,
        Retail
    }

    #endregion Enumerations -----------------------------------------------------------------------

    #region Domain event implementations ----------------------------------------------------------

    public record CashDepositedEvent(Guid CompanyId, Money Amount, string Memo, DateTime Timestamp) : IDomainEvent;
    public record CashWithdrawnEvent(Guid CompanyId, Money Amount, string Memo, DateTime Timestamp) : IDomainEvent;
    public record DebtIncurredEvent(Guid CompanyId, Money Principal, string Lender, DateTime Timestamp) : IDomainEvent;
    public record DebtRepaidEvent(Guid CompanyId, Money Amount, string Lender, DateTime Timestamp) : IDomainEvent;
    public record EquityIssuedEvent(Guid CompanyId, Money RaiseAmount, string Series, DateTime Timestamp) : IDomainEvent;

    public record CompanyAcquiredEvent(Guid BuyerId, Guid TargetId, Money PurchasePrice, DateTime Timestamp) : IDomainEvent;

    public record IpoFiledEvent(Guid CompanyId, DateTime FilingDate, Money ExpectedRaise) : IDomainEvent;
    public record IpoListedEvent(Guid CompanyId, DateTime ListingDate, Money ActualRaise) : IDomainEvent;

    #endregion Domain event implementations -------------------------------------------------------
}
```