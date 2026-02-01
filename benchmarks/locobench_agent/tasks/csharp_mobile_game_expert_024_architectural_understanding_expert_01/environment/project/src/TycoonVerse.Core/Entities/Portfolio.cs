```csharp
// File: TycoonVerse/src/TycoonVerse.Core/Entities/Portfolio.cs

using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading;

namespace TycoonVerse.Core.Entities
{
    /// <summary>
    /// Represents a player’s portfolio of cash and equity holdings.
    /// Thread-safe for public mutation APIs.
    /// </summary>
    public sealed class Portfolio : IEquatable<Portfolio>
    {
        private readonly object _syncRoot = new();

        private readonly Dictionary<Guid, Holding> _holdings = new();

        /// <summary>Optimistic concurrency token (incremented per mutation).</summary>
        public long Version { get; private set; }

        /// <summary>Currency-agnostic cash balance (denominated in game credits).</summary>
        public decimal CashBalance { get; private set; }

        /// <summary>Identifier of the owning player.</summary>
        public Guid PlayerId { get; }

        /// <summary>Unique portfolio identifier.</summary>
        public Guid PortfolioId { get; } = Guid.NewGuid();

        /// <summary>Read-only view of the equity holdings.</summary>
        public IReadOnlyCollection<Holding> Holdings
        {
            get
            {
                lock (_syncRoot)
                {
                    // Return a defensive, read-only copy to protect invariants.
                    return new ReadOnlyCollection<Holding>(_holdings.Values
                                                                  .Select(h => h.Clone())
                                                                  .ToList());
                }
            }
        }

        #region ctor
        public Portfolio(Guid playerId, decimal initialCash = 0m)
        {
            if (playerId == Guid.Empty) throw new ArgumentException("PlayerId cannot be empty.", nameof(playerId));
            if (initialCash < 0)       throw new ArgumentOutOfRangeException(nameof(initialCash));

            PlayerId    = playerId;
            CashBalance = initialCash;
            Version     = 0;
        }
        #endregion

        #region Cash Operations
        public void DepositCash(decimal amount)
        {
            if (amount <= 0) throw new ArgumentOutOfRangeException(nameof(amount));

            lock (_syncRoot)
            {
                CashBalance += amount;
                BumpVersion();
            }
        }

        public void WithdrawCash(decimal amount)
        {
            if (amount <= 0) throw new ArgumentOutOfRangeException(nameof(amount));

            lock (_syncRoot)
            {
                if (CashBalance < amount)
                    throw new InvalidOperationException("Insufficient cash.");

                CashBalance -= amount;
                BumpVersion();
            }
        }
        #endregion

        #region Equity Operations
        /// <summary>
        /// Executes a purchase order. Throws when funds are insufficient.
        /// </summary>
        public void Buy(Guid companyId, Industry industry, int quantity, decimal unitPrice)
        {
            ValidateTradeArguments(companyId, quantity, unitPrice);

            var totalCost = quantity * unitPrice;

            lock (_syncRoot)
            {
                if (CashBalance < totalCost)
                    throw new InvalidOperationException("Insufficient cash to execute purchase.");

                CashBalance -= totalCost;

                if (!_holdings.TryGetValue(companyId, out var holding))
                {
                    holding = new Holding(companyId, industry, 0, 0m);
                    _holdings.Add(companyId, holding);
                }

                holding.AddUnits(quantity, unitPrice);
                BumpVersion();
            }
        }

        /// <summary>
        /// Executes a sell order. Throws when the requested shares exceed position size.
        /// </summary>
        public void Sell(Guid companyId, int quantity, decimal unitPrice)
        {
            ValidateTradeArguments(companyId, quantity, unitPrice);

            lock (_syncRoot)
            {
                if (!_holdings.TryGetValue(companyId, out var holding))
                    throw new InvalidOperationException("No existing position in target company.");

                var proceeds = holding.RemoveUnits(quantity, unitPrice);

                if (holding.Quantity == 0)
                    _holdings.Remove(companyId);

                CashBalance += proceeds;
                BumpVersion();
            }
        }
        #endregion

        #region Analytics
        /// <summary>
        /// Snapshot of total portfolio market value.
        /// </summary>
        /// <param name="priceProvider">
        /// Delegate returning current market price for a company’s share.
        /// Must be non-blocking and thread-safe.
        /// </param>
        public decimal ComputeNetWorth(Func<Guid, decimal> priceProvider)
        {
            if (priceProvider == null) throw new ArgumentNullException(nameof(priceProvider));

            lock (_syncRoot)
            {
                var equityValue = _holdings.Values.Sum(h =>
                {
                    var price = priceProvider(h.CompanyId);
                    return h.GetMarketValue(price);
                });

                return CashBalance + equityValue;
            }
        }
        #endregion

        #region Helpers
        private void BumpVersion() => Interlocked.Increment(ref Version);

        private static void ValidateTradeArguments(Guid companyId, int quantity, decimal unitPrice)
        {
            if (companyId == Guid.Empty) throw new ArgumentException("CompanyId cannot be empty.", nameof(companyId));
            if (quantity    <= 0)        throw new ArgumentOutOfRangeException(nameof(quantity));
            if (unitPrice   <= 0)        throw new ArgumentOutOfRangeException(nameof(unitPrice));
        }
        #endregion

        #region Equality
        public bool Equals(Portfolio? other)
            => other is not null && PortfolioId == other.PortfolioId;

        public override bool Equals(object? obj)
            => obj is Portfolio p && Equals(p);

        public override int GetHashCode() => PortfolioId.GetHashCode();
        #endregion

        #region Nested Holding Class
        /// <summary>
        /// Mutable internal representation of an equity position.
        /// Consumers receive clones to preserve encapsulation.
        /// </summary>
        public sealed class Holding
        {
            public Guid CompanyId { get; }
            public Industry Industry { get; }

            /// <summary>Total shares held.</summary>
            public int Quantity { get; private set; }

            /// <summary>Cumulative acquisition cost.</summary>
            public decimal TotalCost { get; private set; }

            public decimal AverageCostPerUnit => Quantity == 0 ? 0m : TotalCost / Quantity;

            internal Holding(Guid companyId, Industry industry, int quantity, decimal totalCost)
            {
                CompanyId = companyId;
                Industry  = industry;
                Quantity  = quantity;
                TotalCost = totalCost;
            }

            internal void AddUnits(int quantity, decimal unitPrice)
            {
                checked
                {
                    Quantity  += quantity;
                    TotalCost += quantity * unitPrice;
                }
            }

            /// <summary>
            /// Removes shares from the position. Returns cash proceeds of the sale.
            /// </summary>
            internal decimal RemoveUnits(int quantity, decimal unitPrice)
            {
                if (quantity > Quantity)
                    throw new InvalidOperationException("Attempted to sell more shares than held.");

                var saleProceeds = quantity * unitPrice;
                var proportion   = (decimal)quantity / Quantity;

                // Reduce average cost proportionally
                TotalCost -= TotalCost * proportion;
                Quantity  -= quantity;

                return saleProceeds;
            }

            internal decimal GetMarketValue(decimal currentPrice) => currentPrice * Quantity;

            internal Holding Clone() => new(CompanyId, Industry, Quantity, TotalCost);
        }
        #endregion
    }

    /// <summary>
    /// Simplified enumeration of industries used by in-game companies.
    /// </summary>
    public enum Industry
    {
        Unknown = 0,
        Technology,
        Manufacturing,
        Energy,
        Finance,
        Healthcare,
        Logistics,
        Retail
    }
}
```