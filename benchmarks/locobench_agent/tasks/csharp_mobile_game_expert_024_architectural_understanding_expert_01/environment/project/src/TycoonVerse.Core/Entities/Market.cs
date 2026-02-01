```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace TycoonVerse.Core.Entities
{
    #region Infrastructure Contracts (lightweight stubs)

    /// <summary>
    /// Domain–level exception for invalid business operations.
    /// </summary>
    public sealed class DomainValidationException : Exception
    {
        public DomainValidationException(string message) : base(message) { }
    }

    /// <summary>
    /// Simple currency value object.
    /// </summary>
    public readonly struct Money : IComparable<Money>
    {
        public decimal Amount { get; }
        public string CurrencyCode { get; }

        public Money(decimal amount, string currencyCode = "USD")
        {
            if (amount < 0) throw new DomainValidationException("Money amount cannot be negative.");
            Amount = amount;
            CurrencyCode = currencyCode;
        }

        public static Money operator +(Money left, Money right)
        {
            EnsureSameCurrency(left, right);
            return new Money(left.Amount + right.Amount, left.CurrencyCode);
        }

        public static Money operator -(Money left, Money right)
        {
            EnsureSameCurrency(left, right);
            if (left.Amount < right.Amount)
                throw new DomainValidationException("Resulting money cannot be negative.");
            return new Money(left.Amount - right.Amount, left.CurrencyCode);
        }

        public static Money operator *(Money money, decimal multiplier) =>
            new Money(money.Amount * multiplier, money.CurrencyCode);

        public int CompareTo(Money other)
        {
            EnsureSameCurrency(this, other);
            return Amount.CompareTo(other.Amount);
        }

        private static void EnsureSameCurrency(Money a, Money b)
        {
            if (a.CurrencyCode != b.CurrencyCode)
                throw new InvalidOperationException("Currency codes must match for arithmetic.");
        }

        public override string ToString() => $"{CurrencyCode} {Amount:N2}";
    }

    /// <summary>
    /// Minimal representation of an in-game product.
    /// </summary>
    public sealed record Product(Guid ProductId, string Name);

    /// <summary>
    /// Represents the participant executing a trade.
    /// </summary>
    public sealed record Company(Guid CompanyId, string Name);

    #endregion

    /// <summary>
    /// Event published by <see cref="Market"/> whenever a listing changes or a trade is completed.
    /// Consumers (analytics, UI, etc.) subscribe through <see cref="Subscribe"/>.
    /// </summary>
    public sealed record MarketEvent(DateTimeOffset OccurredAtUtc, string EventType, object Payload);

    /// <summary>
    /// A single entry in the market order book.
    /// </summary>
    public sealed class MarketListing
    {
        private readonly ReaderWriterLockSlim _lock = new();
        private int _availableUnits;

        public Product Product { get; }
        public Money UnitPrice { get; private set; }

        public int AvailableUnits
        {
            get
            {
                _lock.EnterReadLock();
                try { return _availableUnits; }
                finally { _lock.ExitReadLock(); }
            }
        }

        public DateTimeOffset LastUpdatedUtc { get; private set; }

        public MarketListing(Product product, Money unitPrice, int initialUnits)
        {
            if (initialUnits < 0) throw new DomainValidationException("Initial units cannot be negative.");
            Product      = product;
            UnitPrice    = unitPrice;
            _availableUnits = initialUnits;
            LastUpdatedUtc  = DateTimeOffset.UtcNow;
        }

        /// <summary>
        /// Removes units from inventory when a purchase occurs.
        /// Returns the total price for the units removed.
        /// </summary>
        public Money ReserveUnits(int unitsRequested)
        {
            if (unitsRequested <= 0)
                throw new DomainValidationException("Units requested must be positive.");

            _lock.EnterUpgradeableReadLock();
            try
            {
                if (_availableUnits < unitsRequested)
                    throw new DomainValidationException("Insufficient units available.");

                _lock.EnterWriteLock();
                try
                {
                    _availableUnits -= unitsRequested;
                    LastUpdatedUtc   = DateTimeOffset.UtcNow;
                    return UnitPrice * unitsRequested;
                }
                finally { _lock.ExitWriteLock(); }
            }
            finally { _lock.ExitUpgradeableReadLock(); }
        }

        /// <summary>
        /// Adds units to inventory when a sale occurs.
        /// Optionally overrides the unit price (for dynamic pricing).
        /// </summary>
        public void AddUnits(int unitsAdded, Money? overridePrice = null)
        {
            if (unitsAdded <= 0)
                throw new DomainValidationException("Units added must be positive.");

            _lock.EnterWriteLock();
            try
            {
                _availableUnits += unitsAdded;
                if (overridePrice is not null) UnitPrice = overridePrice.Value;
                LastUpdatedUtc = DateTimeOffset.UtcNow;
            }
            finally { _lock.ExitWriteLock(); }
        }

        public override string ToString() =>
            $"{Product.Name,-30} | {UnitPrice,-12} | Units: {AvailableUnits,-6}";
    }

    /// <summary>
    /// Centralized marketplace that supports concurrent access, dynamic pricing,
    /// and an observable event stream for game systems (UI, analytics, etc.).
    /// </summary>
    public sealed class Market : IObservable<MarketEvent>
    {
        private readonly ConcurrentDictionary<Guid, MarketListing> _listings = new();
        private readonly List<IObserver<MarketEvent>> _observers = new();
        private readonly ReaderWriterLockSlim _observerLock = new();

        private readonly Random _rng = new();

        #region Public API

        /// <summary>Adds or replaces an entire listing (administrative use only).</summary>
        public void UpsertListing(MarketListing listing)
        {
            _listings.AddOrUpdate(listing.Product.ProductId, listing, (_, _) => listing);
            PublishEvent("listing.upserted", listing);
        }

        /// <summary>
        /// Purchase a quantity of a product on behalf of <paramref name="buyer"/>.
        /// Returns the cost of the transaction.
        /// </summary>
        public Money Buy(Company buyer, Guid productId, int units)
        {
            if (!_listings.TryGetValue(productId, out var listing))
                throw new DomainValidationException("Product not found in market.");

            var totalCost = listing.ReserveUnits(units);
            PublishEvent("trade.executed.buy", new
            {
                Buyer      = buyer,
                Product    = listing.Product,
                Units      = units,
                TotalCost  = totalCost
            });

            return totalCost;
        }

        /// <summary>
        /// Sell a quantity of a product on behalf of <paramref name="seller"/>.
        /// Adds the units back into the listing and potentially reduces the price based on supply.
        /// </summary>
        public void Sell(Company seller, Guid productId, int units, Money unitPrice)
        {
            var listing = _listings.GetOrAdd(
                productId,
                _ => new MarketListing(new Product(productId, $"Product-{productId:N4}"), unitPrice, 0));

            listing.AddUnits(units, unitPrice);
            PublishEvent("trade.executed.sell", new
            {
                Seller     = seller,
                Product    = listing.Product,
                Units      = units,
                UnitPrice  = unitPrice
            });
        }

        /// <summary>
        /// Adjust prices across the market based on a simple supply-demand heuristic.
        /// Call periodically (e.g., via game loop or timer).
        /// </summary>
        public void RebalancePrices()
        {
            foreach (var listing in _listings.Values)
            {
                var modifier = ComputePriceModifier(listing.AvailableUnits);
                var newPrice = listing.UnitPrice * modifier;
                listing.AddUnits(0, newPrice); // zero units, only price update
                PublishEvent("price.rebalanced", new { listing.Product, NewPrice = newPrice });
            }
        }

        /// <summary>
        /// Snapshot to a DTO for persistence/offline sync.
        /// </summary>
        public MarketSnapshot CreateSnapshot() =>
            new(_listings.Values.Select(l => new MarketSnapshot.ListingDto(
                    l.Product.ProductId, l.Product.Name, l.UnitPrice.Amount,
                    l.UnitPrice.CurrencyCode, l.AvailableUnits, l.LastUpdatedUtc)).ToList());

        #endregion

        #region Observer Implementation

        public IDisposable Subscribe(IObserver<MarketEvent> observer)
        {
            _observerLock.EnterWriteLock();
            try
            {
                if (!_observers.Contains(observer))
                    _observers.Add(observer);
            }
            finally { _observerLock.ExitWriteLock(); }

            // Immediately push a snapshot to the new subscriber
            observer.OnNext(new MarketEvent(DateTimeOffset.UtcNow, "market.snapshot", CreateSnapshot()));

            return new Unsubscriber(_observers, observer, _observerLock);
        }

        private void PublishEvent(string eventType, object payload)
        {
            var evt = new MarketEvent(DateTimeOffset.UtcNow, eventType, payload);

            _observerLock.EnterReadLock();
            try
            {
                foreach (var observer in _observers.ToList())
                {
                    try { observer.OnNext(evt); }
                    catch { /* Swallow observer errors to avoid cascade failure */ }
                }
            }
            finally { _observerLock.ExitReadLock(); }
        }

        private sealed class Unsubscriber : IDisposable
        {
            private readonly List<IObserver<MarketEvent>> _observers;
            private readonly IObserver<MarketEvent> _observer;
            private readonly ReaderWriterLockSlim _lock;

            public Unsubscriber(List<IObserver<MarketEvent>> observers,
                                IObserver<MarketEvent> observer,
                                ReaderWriterLockSlim @lock)
            {
                _observers = observers;
                _observer  = observer;
                _lock      = @lock;
            }

            public void Dispose()
            {
                _lock.EnterWriteLock();
                try { _observers.Remove(_observer); }
                finally { _lock.ExitWriteLock(); }
            }
        }

        #endregion

        #region Internal Helpers

        private decimal ComputePriceModifier(int availableUnits)
        {
            // Example heuristic: fewer units => higher price, more units => lower price (bounded between 75% and 125%)
            const decimal floor = 0.75m;
            const decimal ceiling = 1.25m;
            const int    highSupplyThreshold = 1000;
            const int    lowSupplyThreshold  = 50;

            return availableUnits switch
            {
                <= 0                    => ceiling,
                < lowSupplyThreshold    => Lerp(ceiling, 1.1m, availableUnits / (decimal)lowSupplyThreshold),
                > highSupplyThreshold   => Lerp(floor, .9m, (availableUnits - highSupplyThreshold) / 5000m),
                _                       => 1m + (decimal)(_rng.NextDouble() - 0.5) * 0.02m // tiny random walk
            };
        }

        private static decimal Lerp(decimal start, decimal end, decimal t) => start + (end - start) * t;

        #endregion
    }

    /// <summary>
    /// Serializable snapshot for offline persistence & sync.
    /// </summary>
    [Serializable]
    public sealed class MarketSnapshot
    {
        public IReadOnlyList<ListingDto> Listings { get; }

        public MarketSnapshot(IReadOnlyList<ListingDto> listings) => Listings = listings;

        [Serializable]
        public sealed record ListingDto(
            Guid ProductId,
            string Name,
            decimal UnitPrice,
            string CurrencyCode,
            int AvailableUnits,
            DateTimeOffset LastUpdatedUtc);
    }
}
```