```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Globalization;
using System.Text;
using TycoonVerse.Core.Exceptions;

namespace TycoonVerse.Core.ValueObjects
{
    /// <summary>
    /// Immutable value-object that represents a monetary amount in a specific currency,
    /// following Domain-Driven-Design best-practices.
    ///
    /// All arithmetic operations require matching currencies to avoid implicit conversion
    /// errors.  Conversion must be done explicitly through an <see cref="IExchangeRateProvider"/>.
    /// </summary>
    public sealed class Money : IEquatable<Money>, IComparable<Money>, IComparable
    {
        #region Static factory helpers -------------------------------------------------------

        public static readonly Money ZeroUsd = new Money(0m, Currency.USD);

        /// <summary>
        /// Factory method that validates input and enforces precision based on the
        /// currency’s minor unit (typically 2 decimal places for FIAT currencies).
        /// </summary>
        public static Money From(decimal amount, Currency currency)
        {
            ValidateCurrency(currency);
            decimal rounded = Round(amount, currency);
            return new Money(rounded, currency);
        }

        /// <summary>
        /// Parses a string representation like "USD 10.35" or "€10,35" depending on the
        /// provided <see cref="CultureInfo"/>.
        /// </summary>
        /// <exception cref="MoneyParseException">Thrown when the format cannot be parsed.</exception>
        public static Money Parse(
            string input,
            Currency expectedCurrency,
            IFormatProvider? formatProvider = null,
            NumberStyles numberStyles           = NumberStyles.Currency)
        {
            if (string.IsNullOrWhiteSpace(input))
                throw new MoneyParseException("Input cannot be empty.");

            formatProvider ??= CultureInfo.InvariantCulture;

            string numericPart = ExtractNumericPart(input, expectedCurrency);
            if (!decimal.TryParse(numericPart, numberStyles, formatProvider, out var amount))
                throw new MoneyParseException($"Unable to parse amount '{numericPart}'.");

            return From(amount, expectedCurrency);
        }

        private static string ExtractNumericPart(string input, Currency expectedCurrency)
        {
            // Remove currency symbol/code and whitespace
            var cleaned = input.Replace(expectedCurrency.Symbol, string.Empty, StringComparison.OrdinalIgnoreCase)
                               .Replace(expectedCurrency.Code, string.Empty, StringComparison.OrdinalIgnoreCase)
                               .Trim();
            return cleaned;
        }

        #endregion

        #region Private fields ---------------------------------------------------------------

        private readonly decimal _amount;

        #endregion

        #region Constructors -----------------------------------------------------------------

        private Money(decimal amount, Currency currency)
        {
            _amount   = amount;
            Currency = currency;
        }

        #endregion

        #region Public properties ------------------------------------------------------------

        public decimal Amount  => _amount;
        public Currency Currency { get; }

        public bool IsZero => _amount == 0m;
        public bool IsPositive => _amount > 0m;
        public bool IsNegative => _amount < 0m;

        #endregion

        #region Arithmetic -------------------------------------------------------------------

        public Money Add(Money other) => this + other;
        public Money Subtract(Money other) => this - other;
        public Money Multiply(decimal factor) => this * factor;
        public Money Divide(decimal divisor) => this / divisor;

        public static Money operator +(Money a, Money b)
        {
            EnsureSameCurrency(a, b);
            return From(a._amount + b._amount, a.Currency);
        }

        public static Money operator -(Money a, Money b)
        {
            EnsureSameCurrency(a, b);
            return From(a._amount - b._amount, a.Currency);
        }

        public static Money operator *(Money a, decimal factor)
            => From(a._amount * factor, a.Currency);

        public static Money operator /(Money a, decimal divisor)
        {
            if (divisor == 0m)
                throw new DivideByZeroException("Cannot divide Money by zero.");
            return From(a._amount / divisor, a.Currency);
        }

        public Money Abs() => _amount >= 0 ? this : From(Math.Abs(_amount), Currency);

        #endregion

        #region Currency Conversion -----------------------------------------------------------

        /// <summary>
        /// Converts this money to <paramref name="targetCurrency"/> using the provided
        /// <see cref="IExchangeRateProvider"/>.
        /// </summary>
        public Money ConvertTo(
            Currency              targetCurrency,
            IExchangeRateProvider rateProvider,
            DateTimeOffset?       onDate = null)
        {
            if (targetCurrency == Currency)
                return this;

            decimal rate = rateProvider.GetRate(Currency, targetCurrency, onDate ?? DateTimeOffset.UtcNow);
            return From(_amount * rate, targetCurrency);
        }

        #endregion

        #region Equality & Comparison ---------------------------------------------------------

        public bool Equals(Money? other)
            => other is not null && Currency == other.Currency && _amount == other._amount;

        public override bool Equals(object? obj) => Equals(obj as Money);

        public override int GetHashCode() => HashCode.Combine(_amount, Currency);

        public static bool operator ==(Money a, Money b) => a.Equals(b);
        public static bool operator !=(Money a, Money b) => !a.Equals(b);

        public int CompareTo(Money? other)
        {
            if (other is null) return 1;
            EnsureSameCurrency(this, other);
            return _amount.CompareTo(other._amount);
        }

        int IComparable.CompareTo(object? obj)
            => obj is Money money ? CompareTo(money) : throw new ArgumentException("Object is not a Money.");

        #endregion

        #region Formatting --------------------------------------------------------------------

        /// <summary>
        /// Returns a localized string representation (e.g., "$10.00").
        /// </summary>
        public string ToString(IFormatProvider? formatProvider = null)
        {
            formatProvider ??= CultureInfo.CurrentCulture;
            return string.Format(formatProvider, "{0}{1:N" + Currency.DecimalPlaces + "}", Currency.Symbol, _amount);
        }

        public override string ToString() => ToString(CultureInfo.CurrentCulture);

        #endregion

        #region Helpers -----------------------------------------------------------------------

        private static void ValidateCurrency(Currency currency)
        {
            if (currency == default)
                throw new ArgumentException("Currency must be specified.", nameof(currency));
        }

        private static decimal Round(decimal amount, Currency currency)
            => Math.Round(amount, currency.DecimalPlaces, MidpointRounding.AwayFromZero);

        private static void EnsureSameCurrency(Money a, Money b)
        {
            if (a.Currency != b.Currency)
                throw new CurrencyMismatchException(a.Currency, b.Currency);
        }

        #endregion
    }

    /// <summary>
    /// Lightweight immutable value-object that wraps an ISO-4217 currency code,
    /// symbol, and decimal precision.
    /// </summary>
    public readonly struct Currency : IEquatable<Currency>
    {
        private static readonly ConcurrentDictionary<string, Currency> _cache = new();

        public string Code { get; }
        public string Symbol { get; }
        public byte   DecimalPlaces { get; }

        private Currency(string code, string symbol, byte decimalPlaces)
        {
            Code          = code;
            Symbol        = symbol;
            DecimalPlaces = decimalPlaces;
        }

        public static Currency Of(string code, string symbol, byte decimalPlaces = 2)
        {
            if (string.IsNullOrWhiteSpace(code))
                throw new ArgumentException("Currency code cannot be null or whitespace.", nameof(code));

            code = code.ToUpperInvariant();
            return _cache.GetOrAdd(code, _ => new Currency(code, symbol, decimalPlaces));
        }

        public static readonly Currency USD = Of("USD", "$", 2);
        public static readonly Currency EUR = Of("EUR", "€", 2);
        public static readonly Currency GBP = Of("GBP", "£", 2);
        public static readonly Currency JPY = Of("JPY", "¥", 0);

        public bool Equals(Currency other) => Code == other.Code;

        public override bool Equals(object? obj) => obj is Currency other && Equals(other);

        public override int GetHashCode() => Code.GetHashCode(StringComparison.Ordinal);

        public static bool operator ==(Currency left, Currency right) => left.Equals(right);
        public static bool operator !=(Currency left, Currency right) => !(left == right);

        public override string ToString() => Code;
    }

    #region Support types --------------------------------------------------------------------

    /// <summary>
    /// Abstraction used by <see cref="Money"/> when converting between currencies.
    /// Implementations are expected to provide thread-safe access to historical
    /// exchange rates (cached or otherwise).
    /// </summary>
    public interface IExchangeRateProvider
    {
        /// <summary>
        /// Returns the rate used to convert 1 unit of <paramref name="from"/> to
        /// <paramref name="to"/> at <paramref name="onDate"/>.
        /// </summary>
        decimal GetRate(Currency from, Currency to, DateTimeOffset onDate);
    }

    [Serializable]
    public class CurrencyMismatchException : InvalidOperationException
    {
        public CurrencyMismatchException(Currency expected, Currency actual)
            : base($"Currency mismatch: expected {expected.Code}, got {actual.Code}.")
        {
        }
    }

    [Serializable]
    public class MoneyParseException : FormatException
    {
        public MoneyParseException(string message) : base(message) { }
    }

    #endregion
}
```
