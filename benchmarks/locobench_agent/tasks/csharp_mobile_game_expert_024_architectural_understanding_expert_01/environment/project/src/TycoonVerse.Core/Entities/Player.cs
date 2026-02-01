```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright file="Player.cs" company="TycoonVerse">
//   © TycoonVerse. All rights reserved.
// </copyright>
// --------------------------------------------------------------------------------------------------------------------

#nullable enable

using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Linq;
using System.Threading;

namespace TycoonVerse.Core.Entities
{
    /// <summary>
    /// Aggregate-root that represents a player profile inside TycoonVerse.
    /// Handles core domain behavior such as wallet mutations, level progression,
    /// and biometric verification. Exposes an <see cref="IObservable{T}"/> stream
    /// of <see cref="PlayerDomainEvent"/>s so that upper layers (analytics, UI) may
    /// react without leaking business rules.
    /// </summary>
    public sealed class Player : IObservable<PlayerDomainEvent>
    {
        #region Static Members

        private const decimal MaxDailyDebit = 250_000m; // Anti-fraud guard.

        #endregion

        #region Private Fields

        private readonly List<IObserver<PlayerDomainEvent>> _observers = new();
        private readonly List<Company> _ownedCompanies = new();
        private readonly List<Achievement> _achievements = new();
        private readonly object _sync = new();

        // Wallet balance is protected via Interlocked for atomicity.
        private decimal _walletBalance;

        #endregion

        #region Constructors

        // Required for ORM / serialization.
        private Player()
        {
            Id = PlayerId.NewId();
            _walletBalance = 0m;
            Currency = CurrencyCode.Usd;
            LastLoginUtc = DateTime.UtcNow;
        }

        private Player(string username, IClock clock)
            : this()
        {
            Username = username;
            Level = 1;
            CreatedUtc = clock.UtcNow;
            LastLoginUtc = clock.UtcNow;
        }

        #endregion

        #region Factory Methods

        /// <summary>
        /// Creates and returns a brand-new player instance.
        /// </summary>
        /// <exception cref="ArgumentException">Thrown when username is null/empty.</exception>
        public static Player Register(string username, IClock clock)
        {
            if (string.IsNullOrWhiteSpace(username))
                throw new ArgumentException("Username must not be empty.", nameof(username));

            var player = new Player(username.Trim(), clock);
            player.Publish(new PlayerRegisteredEvent(player.Id, clock.UtcNow));

            return player;
        }

        #endregion

        #region Public Properties

        public PlayerId Id { get; }
        public string Username { get; private set; } = string.Empty;
        public int Level { get; private set; }
        public bool IsBiometricallyVerified { get; private set; }
        public CurrencyCode Currency { get; private set; }

        /// <summary>
        /// UTC timestamp when the account was first created.
        /// </summary>
        public DateTime CreatedUtc { get; private set; }

        /// <summary>
        /// UTC timestamp when the player last signed in successfully.
        /// Updated on every <see cref="SignIn"/>.
        /// </summary>
        public DateTime LastLoginUtc { get; private set; }

        /// <summary>
        /// Exposes the wallet balance in a thread-safe fashion.
        /// </summary>
        public decimal WalletBalance => Interlocked.CompareExchange(ref _walletBalance, 0, 0);

        /// <summary>
        /// Read-only view of companies currently owned by the player.
        /// </summary>
        public IReadOnlyList<Company> OwnedCompanies => new ReadOnlyCollection<Company>(_ownedCompanies);

        /// <summary>
        /// Read-only view of achievements that have been unlocked.
        /// </summary>
        public IReadOnlyList<Achievement> Achievements => new ReadOnlyCollection<Achievement>(_achievements);

        #endregion

        #region Domain Behavior

        /// <summary>
        /// Signs a player in, updating <see cref="LastLoginUtc"/> and emitting a domain event.
        /// </summary>
        public void SignIn(IClock clock)
        {
            LastLoginUtc = clock.UtcNow;
            Publish(new PlayerSignedInEvent(Id, LastLoginUtc));
        }

        /// <summary>
        /// Adds funds to the player wallet.
        /// </summary>
        /// <param name="amount">Positive monetary amount.</param>
        /// <param name="source">Descriptive source (e.g., “IPO proceeds”, “IAP”).</param>
        /// <exception cref="ArgumentOutOfRangeException">When amount is not positive.</exception>
        public void CreditWallet(decimal amount, string source)
        {
            if (amount <= 0)
                throw new ArgumentOutOfRangeException(nameof(amount), amount, "Amount must be positive.");

            var newBalance = Interlocked.Add(ref _walletBalance, amount);
            Publish(new WalletCreditedEvent(Id, amount, newBalance, source));
        }

        /// <summary>
        /// Debits funds from the player wallet with daily anti-fraud limit.
        /// </summary>
        /// <exception cref="InvalidOperationException">
        /// Thrown when balance is insufficient or limit exceeded.
        /// </exception>
        public void DebitWallet(decimal amount, string reason, IClock clock)
        {
            if (amount <= 0)
                throw new ArgumentOutOfRangeException(nameof(amount), amount, "Amount must be positive.");

            lock (_sync)
            {
                var today = clock.UtcNow.Date;
                var debitedToday = _dailyDebits.TryGetValue(today, out var total) ? total : 0m;

                if (debitedToday + amount > MaxDailyDebit)
                    throw new InvalidOperationException("Daily debit limit exceeded.");

                var currentBalance = WalletBalance;
                if (currentBalance < amount)
                    throw new InvalidOperationException("Insufficient wallet balance.");

                Interlocked.Add(ref _walletBalance, -amount);
                _dailyDebits[today] = debitedToday + amount;
            }

            Publish(new WalletDebitedEvent(Id, amount, WalletBalance, reason));
        }

        /// <summary>
        /// Levels the player up when XP thresholds are met.
        /// Level-up formula: nextLevelXp = 1,000 + (level * 500)
        /// </summary>
        /// <param name="currentXp">Current XP score.</param>
        public void EvaluateLevelUp(int currentXp)
        {
            var requiredXp = 1_000 + (Level * 500);
            if (currentXp < requiredXp)
                return;

            var oldLevel = Level;
            Level++;
            Publish(new PlayerLevelUpEvent(Id, oldLevel, Level));
        }

        /// <summary>
        /// Registers the provided biometric token and sets <see cref="IsBiometricallyVerified"/>.
        /// </summary>
        /// <exception cref="ArgumentException">When token is invalid.</exception>
        public void VerifyBiometrics(BiometricToken token, IBiometricValidator validator)
        {
            if (!validator.Validate(token))
                throw new ArgumentException("Invalid biometric token.", nameof(token));

            IsBiometricallyVerified = true;
            Publish(new PlayerBiometricallyVerifiedEvent(Id, DateTime.UtcNow));
        }

        /// <summary>
        /// Adds a company to the player's portfolio.
        /// </summary>
        public void AcquireCompany(Company company)
        {
            if (company is null) throw new ArgumentNullException(nameof(company));

            lock (_sync)
            {
                if (_ownedCompanies.Any(c => c.Id == company.Id))
                    throw new InvalidOperationException("Company already owned.");

                _ownedCompanies.Add(company);
            }

            Publish(new CompanyAcquiredEvent(Id, company.Id));
        }

        /// <summary>
        /// Adds a new achievement, ensuring duplicates are not recorded.
        /// </summary>
        public void UnlockAchievement(Achievement achievement)
        {
            if (achievement is null) throw new ArgumentNullException(nameof(achievement));

            lock (_sync)
            {
                if (_achievements.Contains(achievement))
                    return; // Already unlocked.
                _achievements.Add(achievement);
            }

            Publish(new AchievementUnlockedEvent(Id, achievement.Code));
        }

        #endregion

        #region Observer Pattern (IObservable)

        public IDisposable Subscribe(IObserver<PlayerDomainEvent> observer)
        {
            if (_observers.Contains(observer)) return new Unsubscriber(_observers, observer);

            _observers.Add(observer);
            return new Unsubscriber(_observers, observer);
        }

        private void Publish(PlayerDomainEvent @event)
        {
            // Defensive copy avoids concurrency woes.
            var snapshot = _observers.ToArray();
            foreach (var observer in snapshot)
            {
                try
                {
                    observer.OnNext(@event);
                }
                catch (Exception e)
                {
                    // Prevent rogue observers from crashing domain logic.
                    Debug.WriteLine(e);
                }
            }
        }

        private sealed class Unsubscriber : IDisposable
        {
            private readonly IList<IObserver<PlayerDomainEvent>> _list;
            private readonly IObserver<PlayerDomainEvent> _observer;

            public Unsubscriber(IList<IObserver<PlayerDomainEvent>> list, IObserver<PlayerDomainEvent> observer)
            {
                _list = list;
                _observer = observer;
            }

            public void Dispose()
            {
                if (_list.Contains(_observer))
                    _list.Remove(_observer);
            }
        }

        #endregion

        #region Private State

        // Keeps track of the total debits per day for fraud protection.
        private readonly Dictionary<DateTime, decimal> _dailyDebits = new();

        #endregion
    }

    #region Supporting Types

    public readonly record struct PlayerId(Guid Value)
    {
        public static PlayerId NewId() => new(Guid.NewGuid());

        public override string ToString() => Value.ToString();
    }

    public enum CurrencyCode
    {
        Usd,
        Eur,
        Gbp,
        Jpy
    }

    /// <summary>
    /// Represents a domain event emitted by <see cref="Player"/>.
    /// </summary>
    public abstract record PlayerDomainEvent(PlayerId PlayerId, DateTime OccurredUtc);

    public sealed record PlayerRegisteredEvent(PlayerId PlayerId, DateTime OccurredUtc) : PlayerDomainEvent(PlayerId, OccurredUtc);
    public sealed record PlayerSignedInEvent(PlayerId PlayerId, DateTime OccurredUtc) : PlayerDomainEvent(PlayerId, OccurredUtc);
    public sealed record WalletCreditedEvent(PlayerId PlayerId, decimal Amount, decimal NewBalance, string Source) : PlayerDomainEvent(PlayerId, DateTime.UtcNow);
    public sealed record WalletDebitedEvent(PlayerId PlayerId, decimal Amount, decimal NewBalance, string Reason) : PlayerDomainEvent(PlayerId, DateTime.UtcNow);
    public sealed record PlayerLevelUpEvent(PlayerId PlayerId, int OldLevel, int NewLevel) : PlayerDomainEvent(PlayerId, DateTime.UtcNow);
    public sealed record PlayerBiometricallyVerifiedEvent(PlayerId PlayerId, DateTime OccurredUtc) : PlayerDomainEvent(PlayerId, OccurredUtc);
    public sealed record CompanyAcquiredEvent(PlayerId PlayerId, CompanyId CompanyId) : PlayerDomainEvent(PlayerId, DateTime.UtcNow);
    public sealed record AchievementUnlockedEvent(PlayerId PlayerId, string AchievementCode) : PlayerDomainEvent(PlayerId, DateTime.UtcNow);

    /// <summary>
    /// Simplified company aggregate just for demonstration.
    /// </summary>
    public sealed record Company(CompanyId Id, string Name);

    public readonly record struct CompanyId(Guid Value)
    {
        public static CompanyId NewId() => new(Guid.NewGuid());

        public override string ToString() => Value.ToString();
    }

    /// <summary>
    /// Simple achievement representation.
    /// </summary>
    public sealed record Achievement(string Code, string Title);

    /// <summary>
    /// Minimalistic clock abstraction for testability.
    /// </summary>
    public interface IClock
    {
        DateTime UtcNow { get; }
    }

    /// <summary>
    /// Token produced by the biometric SDK.
    /// </summary>
    public sealed record BiometricToken(string Base64Payload);

    /// <summary>
    /// Interface used for validating biometric tokens.
    /// Implemented inside infrastructure layer to hit iOS/Android APIs.
    /// </summary>
    public interface IBiometricValidator
    {
        bool Validate(BiometricToken token);
    }

    #endregion
}
```