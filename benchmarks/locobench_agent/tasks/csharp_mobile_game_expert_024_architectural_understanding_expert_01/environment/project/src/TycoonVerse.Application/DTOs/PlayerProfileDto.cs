```csharp
// File: TycoonVerse/src/TycoonVerse.Application/DTOs/PlayerProfileDto.cs

using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel.DataAnnotations;
using System.Diagnostics.CodeAnalysis;
using Newtonsoft.Json;
using TycoonVerse.Domain.Enums; // Imaginary domain namespace

namespace TycoonVerse.Application.DTOs
{
    /// <summary>
    /// Data-transfer object that represents the immutable snapshot of a player’s profile.
    /// This DTO is used by the application layer when communicating with:
    /// • Local SQLite repositories (offline cache)
    /// • Remote REST endpoints (cloud save, analytics)
    /// • In-memory view models (UI binding inside Unity)
    /// </summary>
    /// <remarks>
    /// The object is intentionally serialization-friendly—only auto-properties
    /// (with get/init) and read-only collections are exposed.
    /// </remarks>
    public sealed class PlayerProfileDto : IValidatableObject, IEquatable<PlayerProfileDto>
    {
        private const int MaxUserNameLength = 32;
        private const int MaxAvatarUrlLength = 2048;

        #region Core Identity

        /// <summary>Technical identifier (stable, globally unique).</summary>
        [Required]
        public Guid PlayerId { get; init; } = Guid.Empty;

        /// <summary>Vanity user name displayed in leader boards.</summary>
        [Required, StringLength(MaxUserNameLength, MinimumLength = 3)]
        public string UserName { get; init; } = string.Empty;

        /// <summary>UTC timestamp of the very first registration.</summary>
        [Required]
        public DateTime CreatedUtc { get; init; } = DateTime.MinValue;

        /// <summary>UTC timestamp of the last successful login (device or cloud).</summary>
        [Required]
        public DateTime LastLoginUtc { get; init; } = DateTime.MinValue;

        /// <summary>Base-64 row version used for optimistic concurrency in the cloud.</summary>
        /// <remarks>Ignored during JSON serialization since it is transport-layer specific.</remarks>
        [JsonIgnore]
        public byte[]? RowVersion { get; init; }

        #endregion

        #region Game Progress

        /// <summary>Current level reflecting accumulated XP.</summary>
        [Range(1, 10_000)]
        public int ExperienceLevel { get; init; }

        /// <summary>Liquid cash available to the player.</summary>
        [Range(0, double.MaxValue)]
        [JsonProperty("cash")]
        public decimal CashOnHand { get; init; }

        /// <summary>Total net worth including company valuations, securities, and cash.</summary>
        [Range(0, double.MaxValue)]
        public decimal NetWorth { get; init; }

        /// <summary>Reputation affects negotiations and special events (0–100).</summary>
        [Range(0, 100)]
        public int ReputationScore { get; init; }

        /// <summary>True when the user opted-in to biometric sign-in.</summary>
        public bool IsBiometricAuthEnabled { get; init; }

        /// <summary>Remote-first token required for deterministic sync once connectivity returns.</summary>
        public string? LastSyncToken { get; init; }

        #endregion

        #region Cosmetic

        /// <summary>Absolute URL of the user’s avatar stored in S3 or CDN.</summary>
        [StringLength(MaxAvatarUrlLength)]
        public string? AvatarUrl { get; init; }

        #endregion

        #region Navigation Properties

        /// <summary>Lightweight summary of each company controlled by the player.</summary>
        [JsonProperty(Order = 100)] // Send large collections last to optimize payload streaming.
        public IReadOnlyCollection<CompanySummaryDto> Companies { get; init; } =
            ReadOnlyCollection<CompanySummaryDto>.Empty;

        /// <summary>Unlocked achievements (used by UI badges & social sharing).</summary>
        [JsonProperty(Order = 101)]
        public IReadOnlyCollection<AchievementDto> Achievements { get; init; } =
            ReadOnlyCollection<AchievementDto>.Empty;

        #endregion

        #region Computed Members

        /// <summary>Elapsed account age in whole days.</summary>
        [JsonIgnore]
        public int AccountAgeInDays =>
            (int)Math.Max(0, (DateTime.UtcNow - CreatedUtc).TotalDays);

        #endregion

        #region Validation

        /// <inheritdoc />
        public IEnumerable<ValidationResult> Validate(ValidationContext validationContext)
        {
            if (CreatedUtc > DateTime.UtcNow)
            {
                yield return new ValidationResult(
                    $"{nameof(CreatedUtc)} cannot be in the future.",
                    new[] { nameof(CreatedUtc) });
            }

            if (LastLoginUtc < CreatedUtc)
            {
                yield return new ValidationResult(
                    $"{nameof(LastLoginUtc)} cannot be earlier than {nameof(CreatedUtc)}.",
                    new[] { nameof(LastLoginUtc) });
            }

            if (NetWorth < CashOnHand)
            {
                yield return new ValidationResult(
                    $"{nameof(NetWorth)} cannot be less than {nameof(CashOnHand)}.",
                    new[] { nameof(NetWorth), nameof(CashOnHand) });
            }
        }

        #endregion

        #region Equality members

        public bool Equals(PlayerProfileDto? other)
        {
            if (other is null) return false;
            if (ReferenceEquals(this, other)) return true;

            return PlayerId.Equals(other.PlayerId)
                   && ExperienceLevel == other.ExperienceLevel
                   && NetWorth == other.NetWorth
                   && CashOnHand == other.CashOnHand
                   && ReputationScore == other.ReputationScore
                   && LastLoginUtc.Equals(other.LastLoginUtc);
        }

        public override bool Equals(object? obj) => Equals(obj as PlayerProfileDto);

        public override int GetHashCode() => HashCode.Combine(PlayerId, ExperienceLevel, NetWorth, CashOnHand);

        #endregion

        #region Factory Helpers

        /// <summary>
        /// Convenience method for constructing an instance from domain aggregate.
        /// Keeps the DTO free of domain references while avoiding unnecessary reflection.
        /// </summary>
        public static PlayerProfileDto FromDomain(PlayerAggregate source)
        {
            if (source is null) throw new ArgumentNullException(nameof(source));

            return new PlayerProfileDto
            {
                PlayerId               = source.Id,
                UserName               = source.UserName,
                CreatedUtc             = source.CreatedUtc,
                LastLoginUtc           = source.LastLoginUtc,
                ExperienceLevel        = source.Level,
                CashOnHand             = source.Wallet.Cash,
                NetWorth               = source.Wallet.NetWorth,
                ReputationScore        = source.Reputation,
                IsBiometricAuthEnabled = source.Security.IsBiometricEnabled,
                LastSyncToken          = source.SyncToken,
                AvatarUrl              = source.Avatar?.Url,
                RowVersion             = source.RowVersion,
                Companies              = MapCompanies(source.Companies),
                Achievements           = MapAchievements(source.Achievements)
            };

            static IReadOnlyCollection<CompanySummaryDto> MapCompanies(IReadOnlyCollection<CompanyAggregate> companies)
            {
                var list = new List<CompanySummaryDto>(capacity: companies.Count);
                foreach (var c in companies)
                {
                    list.Add(new CompanySummaryDto
                    {
                        CompanyId   = c.Id,
                        Name        = c.Name,
                        Industry    = c.Industry,
                        MarketCap   = c.Valuation,
                        Employees   = c.Headcount
                    });
                }

                return new ReadOnlyCollection<CompanySummaryDto>(list);
            }

            static IReadOnlyCollection<AchievementDto> MapAchievements(IReadOnlyCollection<Achievement> achievements)
            {
                var list = new List<AchievementDto>(achievements.Count);
                foreach (var a in achievements)
                {
                    list.Add(new AchievementDto
                    {
                        AchievementId = a.Id,
                        Title         = a.Title,
                        Description   = a.Description,
                        DateUnlocked  = a.UnlockedUtc
                    });
                }

                return new ReadOnlyCollection<AchievementDto>(list);
            }
        }

        #endregion
    }

    #region Supporting DTOs

    /// <summary>Compact view of a company, optimized for profile screen rendering.</summary>
    public sealed class CompanySummaryDto
    {
        [Required]
        public Guid CompanyId { get; init; }

        [Required, StringLength(64)]
        public string Name { get; init; } = string.Empty;

        public IndustryType Industry { get; init; }

        [Range(0, double.MaxValue)]
        public decimal MarketCap { get; init; }

        [Range(0, int.MaxValue)]
        public int Employees { get; init; }
    }

    /// <summary>Achievement badge unlocked by completing milestones.</summary>
    public sealed class AchievementDto
    {
        [Required]
        public Guid AchievementId { get; init; }

        [Required, StringLength(64)]
        public string Title { get; init; } = string.Empty;

        [StringLength(256)]
        public string? Description { get; init; }

        public DateTime DateUnlocked { get; init; }
    }

    #endregion
}

// Because the DTO layer exists in a separate assembly, 
// lightweight domain duplicates are provided below to satisfy compilation.
// In the production solution these would reside in the Domain project.
namespace TycoonVerse.Domain.Enums
{
    [SuppressMessage("ReSharper", "InconsistentNaming")]
    public enum IndustryType
    {
        Unknown = 0,
        Manufacturing = 1,
        Technology = 2,
        Retail = 3,
        Logistics = 4,
        Energy = 5,
        HealthCare = 6
    }
}

// Dummy aggregates to make FromDomain compile without full domain layer.
// These will be excluded in the real build via conditional compilation.
#if DEBUG
namespace TycoonVerse.Domain
{
    using System.Collections.Generic;
    using TycoonVerse.Domain.Enums;

    internal sealed class PlayerAggregate
    {
        public Guid Id { get; init; }
        public string UserName { get; init; } = default!;
        public DateTime CreatedUtc { get; init; }
        public DateTime LastLoginUtc { get; init; }
        public int Level { get; init; }
        public Wallet Wallet { get; init; } = default!;
        public int Reputation { get; init; }
        public SecuritySettings Security { get; init; } = default!;
        public string? SyncToken { get; init; }
        public Avatar? Avatar { get; init; }
        public byte[]? RowVersion { get; init; }
        public IReadOnlyCollection<CompanyAggregate> Companies { get; init; } = default!;
        public IReadOnlyCollection<Achievement> Achievements { get; init; } = default!;
    }

    internal sealed class Wallet
    {
        public decimal Cash { get; init; }
        public decimal NetWorth { get; init; }
    }

    internal sealed class SecuritySettings
    {
        public bool IsBiometricEnabled { get; init; }
    }

    internal sealed class Avatar
    {
        public string Url { get; init; } = default!;
    }

    internal sealed class CompanyAggregate
    {
        public Guid Id { get; init; }
        public string Name { get; init; } = default!;
        public IndustryType Industry { get; init; }
        public decimal Valuation { get; init; }
        public int Headcount { get; init; }
    }

    internal sealed class Achievement
    {
        public Guid Id { get; init; }
        public string Title { get; init; } = default!;
        public string? Description { get; init; }
        public DateTime UnlockedUtc { get; init; }
    }
}
#endif
```