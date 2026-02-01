```csharp
using System;
using System.Threading;
using System.Threading.Tasks;
using TycoonVerse.Domain.Primitives;
using TycoonVerse.Domain.ValueObjects;
using TycoonVerse.Application.Models.Authentication;

namespace TycoonVerse.Application.Interfaces.Services
{
    /// <summary>
    ///     Contract for every authentication-related workflow used by the game client.
    ///     The service is implemented in the Infrastructure layer (e.g., Firebase, Azure B2C, or a mock
    ///     offline provider) and consumed exclusively through this abstraction from the
    ///     Application / View-Model layer.
    ///     
    ///     Responsibilities
    ///     1. Online sign-in/out and token refresh
    ///     2. Deterministic offline session restoration
    ///     3. Biometric credential enrollment & verification
    ///     4. Secure persistence of authentication artifacts (key-chain / keystore)
    ///     5. Session change notifications for reactive UI updates
    /// </summary>
    public interface IAuthenticationService : IScopedDependency
    {
        #region Online Credentials Based Login

        /// <summary>
        /// Performs an online sign-in with traditional credentials.
        /// </summary>
        /// <param name="email">User’s primary account e-mail.</param>
        /// <param name="password">The plaintext password (will be transmitted through TLS).</param>
        /// <param name="cancellationToken">Optional cancellation token.</param>
        /// <returns>An authenticated <see cref="UserSession"/> or throws <see cref="AuthenticationException"/>.</returns>
        Task<UserSession> SignInAsync(
            string email,
            string password,
            CancellationToken cancellationToken = default);

        #endregion

        #region Biometric Authentication Flows

        /// <summary>
        /// Indicates whether the device supports biometric sensors configured by the player
        /// (Face-ID, Touch-ID, Windows Hello, etc.).
        /// </summary>
        /// <returns>True when available and enrolled.</returns>
        Task<bool> IsBiometricsAvailableAsync(CancellationToken cancellationToken = default);

        /// <summary>
        /// Enrolls-or-updates a new biometric credential set that maps to the user’s identity.
        /// </summary>
        /// <param name="localDeviceUserId">An opaque identifier unique to the device profile.</param>
        Task RegisterBiometricCredentialsAsync(
            string localDeviceUserId,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Attempts to unlock a session using only biometric validation.
        /// Falls back to offline session cache when network is unreachable.
        /// </summary>
        /// <param name="localDeviceUserId">Device-local user identifier used during enrollment.</param>
        /// <returns>An unlocked <see cref="UserSession"/> instance.</returns>
        Task<UserSession> SignInWithBiometricsAsync(
            string localDeviceUserId,
            CancellationToken cancellationToken = default);

        #endregion

        #region Session Persistence & Lifecycle

        /// <summary>
        /// Restores the most recent cached session. If no valid session can be found, returns null.
        /// Used for silent logins on app cold-start or connectivity resumes.
        /// </summary>
        Task<UserSession?> TryRestoreSessionAsync(CancellationToken cancellationToken = default);

        /// <summary>
        /// Explicitly signs the player out, removing any cached tokens and revoking server-side refresh tokens.
        /// </summary>
        Task SignOutAsync(CancellationToken cancellationToken = default);

        /// <summary>
        /// Requests a new tokens set using a valid refresh token. Throws <see cref="AuthenticationException"/>
        /// if the refresh token has been revoked or expired.
        /// </summary>
        Task<TokenPair> RefreshTokenAsync(
            RefreshToken refreshToken,
            CancellationToken cancellationToken = default);

        #endregion

        #region Events

        /// <summary>
        /// Raised whenever the active session changes (sign-in / sign-out / token refresh).
        /// The <see cref="SessionChangedEventArgs"/> payload carries the old and new state.
        /// </summary>
        event EventHandler<SessionChangedEventArgs> SessionChanged;

        #endregion
    }
}
```