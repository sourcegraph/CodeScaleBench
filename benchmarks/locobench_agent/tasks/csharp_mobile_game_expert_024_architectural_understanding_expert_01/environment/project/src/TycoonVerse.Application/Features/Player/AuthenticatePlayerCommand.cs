```csharp
// -----------------------------------------------------------------------------
//  TycoonVerse: Enterprise Empire Simulator
//  File: TycoonVerse.Application/Features/Player/AuthenticatePlayerCommand.cs
// -----------------------------------------------------------------------------

using System;
using System.Threading;
using System.Threading.Tasks;
using MediatR;
using TycoonVerse.Application.Common.Exceptions;
using TycoonVerse.Application.Common.Interfaces;
using TycoonVerse.Application.Common.Models;
using TycoonVerse.Domain.PlayerAggregate;
using TycoonVerse.Domain.Shared;
using TycoonVerse.Infrastructure.Telemetry;

namespace TycoonVerse.Application.Features.Player;

/// <summary>
///     Command used to authenticate a player by password, biometric signature, or
///     cached offline credentials.  Implements the CQRS pattern via MediatR.
/// </summary>
public sealed class AuthenticatePlayerCommand : IRequest<AuthenticatePlayerResponse>
{
    /// <summary>
    ///     Email address uniquely identifying the player.  Required for all
    ///     authentication modes because it acts as the logical partition key.
    /// </summary>
    public string Email { get; }

    /// <summary>
    ///     Raw password entered by the player. Can be <c>null</c> when authenticating
    ///     via biometrics or offline token.
    /// </summary>
    public string? Password { get; }

    /// <summary>
    ///     Platform-specific biometric token (e.g., FaceID hash or Android keystore
    ///     signature).  Can be <c>null</c> if authenticating via password.
    /// </summary>
    public string? BiometricSignature { get; }

    /// <summary>
    ///     When <c>true</c>, the client is explicitly requesting an offline
    ///     authentication attempt using previously cached credentials.
    /// </summary>
    public bool OfflineModeRequested { get; }

    public AuthenticatePlayerCommand(
        string email,
        string? password,
        string? biometricSignature,
        bool offlineModeRequested = false)
    {
        Email = email.Trim().ToLowerInvariant();
        Password = password;
        BiometricSignature = biometricSignature;
        OfflineModeRequested = offlineModeRequested;
    }
}

/// <summary>
///     Response returned to the presentation layer after a successful or failed
///     player authentication attempt.
/// </summary>
public sealed class AuthenticatePlayerResponse
{
    public bool IsAuthenticated { get; init; }
    public bool IsOfflineGrant { get; init; }
    public string? AccessToken { get; init; }
    public DateTimeOffset? AccessTokenExpiresAt { get; init; }
    public PlayerProfileDto? Profile { get; init; }
    public string? FailureReason { get; init; }

    public static AuthenticatePlayerResponse Success(PlayerProfileDto profile, string jwt, DateTimeOffset expiresAt)
        => new()
        {
            IsAuthenticated = true,
            AccessToken = jwt,
            AccessTokenExpiresAt = expiresAt,
            Profile = profile,
            FailureReason = null,
            IsOfflineGrant = false
        };

    public static AuthenticatePlayerResponse Offline(PlayerProfileDto profile)
        => new()
        {
            IsAuthenticated = true,
            IsOfflineGrant = true,
            AccessToken = null,
            AccessTokenExpiresAt = null,
            Profile = profile,
            FailureReason = null
        };

    public static AuthenticatePlayerResponse Fail(string reason)
        => new()
        {
            IsAuthenticated = false,
            FailureReason = reason
        };
}

/// <summary>
///     Handles <see cref="AuthenticatePlayerCommand"/> requests.
/// </summary>
internal sealed class AuthenticatePlayerCommandHandler
    : IRequestHandler<AuthenticatePlayerCommand, AuthenticatePlayerResponse>
{
    private readonly IPlayerRepository _playerRepository;
    private readonly IPasswordService _passwordService;
    private readonly IBiometricAuthService _biometricAuthService;
    private readonly ITokenService _tokenService;
    private readonly IOfflineAuthCache _offlineCache;
    private readonly IAnalyticsService _analytics;
    private readonly IDateTimeProvider _dateTime;

    public AuthenticatePlayerCommandHandler(
        IPlayerRepository playerRepository,
        IPasswordService passwordService,
        IBiometricAuthService biometricAuthService,
        ITokenService tokenService,
        IOfflineAuthCache offlineCache,
        IAnalyticsService analytics,
        IDateTimeProvider dateTime)
    {
        _playerRepository = playerRepository;
        _passwordService = passwordService;
        _biometricAuthService = biometricAuthService;
        _tokenService = tokenService;
        _offlineCache = offlineCache;
        _analytics = analytics;
        _dateTime = dateTime;
    }

    public async Task<AuthenticatePlayerResponse> Handle(
        AuthenticatePlayerCommand command,
        CancellationToken cancellationToken)
    {
        // 1. Sanity validation -------------------------------------------------------------------
        if (string.IsNullOrWhiteSpace(command.Email))
            return AuthenticatePlayerResponse.Fail("Email must be provided.");

        // 2. Attempt offline authentication if requested ----------------------------------------
        if (command.OfflineModeRequested)
        {
            var cached = _offlineCache.TryGet(command.Email);
            if (cached != null)
            {
                _analytics.TrackEvent(AnalyticsEvent.OfflineAuthGranted, command.Email);
                return AuthenticatePlayerResponse.Offline(cached);
            }

            // If offline login was explicitly requested and no cache found, we *fail fast*
            return AuthenticatePlayerResponse.Fail("Offline credentials not found.");
        }

        // 3. Fetch player aggregate from repository ---------------------------------------------
        var player = await _playerRepository.GetByEmailAsync(command.Email, cancellationToken);
        if (player is null)
            return AuthenticatePlayerResponse.Fail("Player not found.");

        // 4. Validate credentials ----------------------------------------------------------------
        bool isCredentialValid = false;

        // 4a. Password flow
        if (!string.IsNullOrWhiteSpace(command.Password))
        {
            isCredentialValid = _passwordService.VerifyHashedPassword(
                player.PasswordHash,
                command.Password);
        }

        // 4b. Biometric flow (if password failed / not provided)
        if (!isCredentialValid && !string.IsNullOrWhiteSpace(command.BiometricSignature))
        {
            isCredentialValid = await _biometricAuthService.ValidateAsync(
                player.Id,
                command.BiometricSignature,
                cancellationToken);
        }

        if (!isCredentialValid)
        {
            _analytics.TrackEvent(AnalyticsEvent.AuthFailed, command.Email);
            return AuthenticatePlayerResponse.Fail("Invalid credentials.");
        }

        // 5. Build JWT and persist refresh token -------------------------------------------------
        var (jwt, expiresAt) = _tokenService.GenerateAccessToken(player);
        player.RefreshToken = _tokenService.GenerateRefreshToken();
        player.RefreshTokenExpiry = expiresAt.AddDays(7);

        await _playerRepository.UpdateAsync(player, cancellationToken);

        // 6. Cache profile for possible offline authentication -----------------------------------
        var profileDto = PlayerProfileDto.From(player);
        _offlineCache.Set(command.Email, profileDto);

        // 7. Track analytics ---------------------------------------------------------------------
        _analytics.TrackEvent(AnalyticsEvent.AuthSucceeded, command.Email);

        // 8. Return success ----------------------------------------------------------------------
        return AuthenticatePlayerResponse.Success(profileDto, jwt, expiresAt);
    }
}

// -----------------------------------------------------------------------------
//  Interfaces required by this feature.  They are implemented in other layers.
// -----------------------------------------------------------------------------

namespace TycoonVerse.Application.Common.Interfaces
{
    /// <summary>
    ///     Repository abstraction for <see cref="Player"/> aggregates.
    /// </summary>
    public interface IPlayerRepository
    {
        Task<Player?> GetByEmailAsync(string email, CancellationToken ct);
        Task UpdateAsync(Player player, CancellationToken ct);
    }

    /// <summary>Responsible for hashing and verifying player passwords.</summary>
    public interface IPasswordService
    {
        bool VerifyHashedPassword(string hashedPassword, string providedPassword);
    }

    /// <summary>Service that delegates biometric verification to platform APIs.</summary>
    public interface IBiometricAuthService
    {
        Task<bool> ValidateAsync(PlayerId playerId, string biometricSignature, CancellationToken ct);
    }

    /// <summary>Generates access & refresh tokens following the OAuth 2.0 spec.</summary>
    public interface ITokenService
    {
        (string Jwt, DateTimeOffset ExpiresAt) GenerateAccessToken(Player player);
        string GenerateRefreshToken();
    }

    /// <summary>
    ///     Local cache holding last-known good credentials to unlock offline play.
    /// </summary>
    public interface IOfflineAuthCache
    {
        PlayerProfileDto? TryGet(string email);
        void Set(string email, PlayerProfileDto profile);
    }

    /// <summary>Thin wrapper around analytics SDK for feature-level events.</summary>
    public interface IAnalyticsService
    {
        void TrackEvent(string @event, string playerIdentifier);
    }

    /// <summary>
    ///     Provides <see cref="DateTimeOffset.UtcNow"/> access for testability.
    /// </summary>
    public interface IDateTimeProvider
    {
        DateTimeOffset UtcNow { get; }
    }
}

// -----------------------------------------------------------------------------
//  DTOs & shared constants
// -----------------------------------------------------------------------------

namespace TycoonVerse.Application.Common.Models
{
    /// <summary>Lightweight representation of a player's public profile.</summary>
    public sealed class PlayerProfileDto
    {
        public string Id { get; init; } = default!;
        public string Email { get; init; } = default!;
        public string DisplayName { get; init; } = default!;
        public long CashOnHand { get; init; }

        public static PlayerProfileDto From(Player player) => new()
        {
            Id = player.Id.Value,
            Email = player.Email,
            DisplayName = player.DisplayName,
            CashOnHand = player.CashOnHand
        };
    }
}

namespace TycoonVerse.Infrastructure.Telemetry
{
    public static class AnalyticsEvent
    {
        public const string AuthSucceeded = "auth_success";
        public const string AuthFailed = "auth_failure";
        public const string OfflineAuthGranted = "auth_offline_grant";
    }
}
```