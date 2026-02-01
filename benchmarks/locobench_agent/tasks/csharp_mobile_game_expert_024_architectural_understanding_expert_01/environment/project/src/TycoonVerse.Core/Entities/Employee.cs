using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.Linq;
using TycoonVerse.Core.SharedKernel;

namespace TycoonVerse.Core.Entities
{
    /// <summary>
    ///     Represents a single employee in the player-owned enterprise.
    ///     The entity is designed following DDD best-practices and is
    ///     storage-agnostic (it does not expose persistence concerns).
    /// </summary>
    public sealed class Employee : IEquatable<Employee>, IComparable<Employee>, IAggregateRoot
    {
        #region Nested types

        /// <summary>
        ///     Employment status used by HR and payroll systems.
        /// </summary>
        public enum EmploymentStatus
        {
            Active,
            OnLeave,
            Terminated
        }

        /// <summary>
        ///     Role classification determines pay-grade, authority, and
        ///     contribution to the player’s company rating.
        /// </summary>
        public enum EmployeeRole
        {
            Intern = 0,
            JuniorAssociate = 1,
            Associate = 2,
            SeniorAssociate = 3,
            Manager = 4,
            SeniorManager = 5,
            Director = 6,
            VicePresident = 7,
            SeniorVicePresident = 8,
            CLevel = 9
        }

        /// <summary>
        ///     Historical performance record.  Immutable value-object.
        /// </summary>
        public readonly struct PerformanceReview
        {
            public PerformanceReview(DateTime occurredAtUtc, byte score0To100, string reviewer, string notes)
            {
                if (score0To100 is < 0 or > 100)
                    throw new ArgumentOutOfRangeException(nameof(score0To100), "Score must be between 0 and 100.");
                OccurredAtUtc = occurredAtUtc.ToUniversalTime();
                Score = score0To100;
                Reviewer = reviewer ?? throw new ArgumentNullException(nameof(reviewer));
                Notes = notes ?? string.Empty;
            }

            public DateTime OccurredAtUtc { get; }
            public byte Score { get; }
            public string Reviewer { get; }
            public string Notes { get; }

            public override string ToString() =>
                $"{OccurredAtUtc:u} | Score: {Score} | Reviewer: {Reviewer} | {Notes}";
        }

        #endregion

        #region State & backing fields

        private readonly ConcurrentDictionary<string, byte> _skills;
        private readonly List<PerformanceReview> _performanceHistory;
        private readonly object _promotionLock = new();

        #endregion

        #region Constructors

        public Employee(Guid id,
                        string fullName,
                        EmployeeRole role,
                        decimal annualSalary,
                        DateTime hiredAtUtc,
                        IDictionary<string, byte>? initialSkills = null)
        {
            if (id == Guid.Empty) throw new ArgumentException("Id must be non-empty.", nameof(id));

            FullName = string.IsNullOrWhiteSpace(fullName)
                ? throw new ArgumentException("Name cannot be empty.", nameof(fullName))
                : fullName.Trim();

            Role = role;
            AnnualSalary = annualSalary >= 0
                ? annualSalary
                : throw new ArgumentOutOfRangeException(nameof(annualSalary));

            HiredAtUtc = hiredAtUtc.ToUniversalTime();
            Id = id;

            Status = EmploymentStatus.Active;

            _skills = new ConcurrentDictionary<string, byte>(
                (initialSkills ?? new Dictionary<string, byte>()).ToDictionary(
                    kvp => NormalizeSkillKey(kvp.Key),
                    kvp => ClampSkillScore(kvp.Value)));

            _performanceHistory = new List<PerformanceReview>(capacity: 4);
        }

        #endregion

        #region Public properties

        /// <summary>Primary key used throughout the domain.</summary>
        public Guid Id { get; }

        /// <summary>Display name.</summary>
        public string FullName { get; }

        /// <summary>Current role / title.</summary>
        public EmployeeRole Role { get; private set; }

        /// <summary>Gross salary quoted on an annual basis (in game currency).</summary>
        public decimal AnnualSalary { get; private set; }

        /// <summary>The date the employee was hired (UTC).</summary>
        public DateTime HiredAtUtc { get; }

        /// <summary>Current employment status.</summary>
        public EmploymentStatus Status { get; private set; }

        /// <summary>
        ///     Returns an immutable snapshot of skills (case-insensitive keys,
        ///     0-100 proficiency values).
        /// </summary>
        public IReadOnlyDictionary<string, byte> Skills =>
            new ReadOnlyDictionary<string, byte>(_skills);

        /// <summary>All historical reviews from first hire.</summary>
        public IReadOnlyList<PerformanceReview> PerformanceHistory =>
            _performanceHistory.AsReadOnly();

        #endregion

        #region Domain logic

        /// <summary>
        ///     Calculates the cost to the company for a single in-game day.
        ///     Includes employer expenses such as benefits and taxes.
        ///     Benefit multiplier can be tuned by designers through config.
        /// </summary>
        public decimal CalculateDailyCost(GameEconomyConfig economy)
        {
            if (economy == null) throw new ArgumentNullException(nameof(economy));

            const int DaysInYear = 365;
            var baseCost = AnnualSalary / DaysInYear;
            var benefits = baseCost * economy.BenefitsMultiplier;
            var payrollTax = baseCost * economy.PayrollTaxRate;

            return Decimal.Round(baseCost + benefits + payrollTax, economy.CurrencyPrecision);
        }

        /// <summary>
        ///     Gives a performance review and returns the average score for
        ///     the last N reviews (N defined by config).
        /// </summary>
        public double GivePerformanceReview(PerformanceReview review, GameEconomyConfig economy)
        {
            if (Status != EmploymentStatus.Active)
                throw new InvalidOperationException($"Cannot review employee in status {Status}.");

            lock (_performanceHistory) _performanceHistory.Add(review);

            var recentReviews = _performanceHistory
                .OrderByDescending(r => r.OccurredAtUtc)
                .Take(economy.PerformanceAverageSampleSize)
                .ToArray();

            return recentReviews.Any()
                ? recentReviews.Average(r => r.Score)
                : 0d;
        }

        /// <summary>
        ///     Attempts to promote the employee.  If the new role is lower than
        ///     or equal to the current, an exception is thrown.
        /// </summary>
        public void Promote(EmployeeRole newRole, decimal newAnnualSalary)
        {
            if (Status != EmploymentStatus.Active)
                throw new InvalidOperationException("Only active employees can be promoted.");

            if (newAnnualSalary < AnnualSalary)
                throw new ArgumentException("New salary must be equal or higher than current.", nameof(newAnnualSalary));

            lock (_promotionLock)
            {
                if (newRole <= Role)
                    throw new InvalidOperationException(
                        $"New role {newRole} must be higher than current role {Role}.");

                Role = newRole;
                AnnualSalary = newAnnualSalary;
            }
        }

        /// <summary>
        ///     Marks the employee as terminated and returns their severance
        ///     payout using game economy config.
        /// </summary>
        public decimal Terminate(string reason, GameEconomyConfig economy)
        {
            if (Status == EmploymentStatus.Terminated)
                throw new InvalidOperationException("Employee already terminated.");

            Status = EmploymentStatus.Terminated;

            var payout = AnnualSalary * economy.SeveranceMultiplier;
            DomainEvents.Raise(new EmployeeTerminatedDomainEvent(this, reason, payout));
            return payout;
        }

        /// <summary>Adjusts or adds a skill.</summary>
        public void UpdateSkill(string skill, byte proficiency0To100)
        {
            var key = NormalizeSkillKey(skill);
            _skills.AddOrUpdate(key,
                                _ => ClampSkillScore(proficiency0To100),
                                (_, _) => ClampSkillScore(proficiency0To100));
        }

        #endregion

        #region Equality & ordering

        public bool Equals(Employee? other) => !(other is null) && Id == other.Id;
        public override bool Equals(object? obj) => Equals(obj as Employee);
        public override int GetHashCode() => Id.GetHashCode();
        public int CompareTo(Employee? other) => string.CompareOrdinal(FullName, other?.FullName);

        #endregion

        #region Utilities

        private static byte ClampSkillScore(byte score) => (byte)Math.Min(Math.Max(score, 0), 100);

        private static string NormalizeSkillKey(string skill) =>
            skill?.Trim().ToUpperInvariant() ?? throw new ArgumentNullException(nameof(skill));

        #endregion
    }

    #region Supporting types

    /// <summary>
    ///     Runtime-tunable parameters sourced from remote config.  Changing
    ///     these does not require a client update and will automatically
    ///     rebalance calculations after deserialization.
    /// </summary>
    public sealed class GameEconomyConfig
    {
        public const int DefaultCurrencyPrecision = 2;

        public GameEconomyConfig(decimal benefitsMultiplier = 0.18m,
                                 decimal payrollTaxRate = 0.0675m,
                                 decimal severanceMultiplier = 0.15m,
                                 int performanceAverageSampleSize = 3,
                                 int currencyPrecision = DefaultCurrencyPrecision)
        {
            if (benefitsMultiplier < 0) throw new ArgumentOutOfRangeException(nameof(benefitsMultiplier));
            if (payrollTaxRate < 0) throw new ArgumentOutOfRangeException(nameof(payrollTaxRate));
            if (severanceMultiplier < 0) throw new ArgumentOutOfRangeException(nameof(severanceMultiplier));
            if (performanceAverageSampleSize <= 0) throw new ArgumentOutOfRangeException(nameof(performanceAverageSampleSize));

            BenefitsMultiplier = benefitsMultiplier;
            PayrollTaxRate = payrollTaxRate;
            SeveranceMultiplier = severanceMultiplier;
            PerformanceAverageSampleSize = performanceAverageSampleSize;
            CurrencyPrecision = currencyPrecision;
        }

        public decimal BenefitsMultiplier { get; }
        public decimal PayrollTaxRate { get; }
        public decimal SeveranceMultiplier { get; }
        public int PerformanceAverageSampleSize { get; }
        public int CurrencyPrecision { get; }
    }

    /// <summary>
    ///     Domain event raised when an employee is terminated.  It is picked
    ///     up by HR analytics, UI notifications, and data-sync layers.
    /// </summary>
    public sealed class EmployeeTerminatedDomainEvent : IDomainEvent
    {
        public EmployeeTerminatedDomainEvent(Employee employee, string reason, decimal payout)
        {
            Employee = employee ?? throw new ArgumentNullException(nameof(employee));
            Reason = reason ?? string.Empty;
            Payout = payout;
            OccurredAtUtc = DateTime.UtcNow;
        }

        public Employee Employee { get; }
        public string Reason { get; }
        public decimal Payout { get; }
        public DateTime OccurredAtUtc { get; }
    }

    #endregion
}

