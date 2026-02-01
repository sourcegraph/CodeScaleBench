```csharp
// File: TycoonVerse/src/TycoonVerse.Infrastructure/Services/Auth/BiometricAuthenticationService.cs

using System;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace TycoonVerse.Infrastructure.Services.Auth
{
    /// <summary>
    /// Provides a high-level façade around the platform-specific biometric APIs
    /// (Touch ID, Face ID, Android Fingerprint, Windows Hello, …).
    /// 
    /// The service participates in the Infrastructure layer and is consumed by
    /// application-level view-models and use-cases through the
    /// <see cref="IBiometricAuthenticationService"/> abstraction.
    /// </summary>
    public sealed class BiometricAuthenticationService : IBiometricAuthenticationService
    {
        private readonly IDeviceBiometricProvider _deviceBiometricProvider;
        private readonly ISecureTokenStore          _secureTokenStore;
        private readonly ILogger<BiometricAuthenticationService> _logger;

        /// <summary>
        /// Raised when a biometric authentication completes successfully.
        /// </summary>
        public event EventHandler<BiometricAuthenticationEventArgs>? AuthenticationSucceeded;

        /// <summary>
        /// Raised when a biometric authentication fails (either user cancel or hardware failure).
        /// Subscribers should fall back to alternative auth strategies (PIN, password…).
        /// </summary>
        public event EventHandler<BiometricAuthenticationEventArgs>? AuthenticationFailed;

        public BiometricAuthenticationService(
            IDeviceBiometricProvider deviceBiometricProvider,
            ISecureTokenStore        secureTokenStore,
            ILogger<BiometricAuthenticationService> logger)
        {
            _deviceBiometricProvider = deviceBiometricProvider ?? throw new ArgumentNullException(nameof(deviceBiometricProvider));
            _secureTokenStore        = secureTokenStore        ?? throw new ArgumentNullException(nameof(secureTokenStore));
            _logger                  = logger                  ?? throw new ArgumentNullException(nameof(logger));
        }

        /// <inheritdoc />
        public async Task<AuthenticationResult> AuthenticateAsync(
            CancellationToken cancellationToken = default)
        {
            try
            {
                // Check availability first. Short-circuit quickly for unsupported devices.
                if (!await _deviceBiometricProvider.IsBiometricsAvailableAsync(cancellationToken)
                                                    .ConfigureAwait(false))
                {
                    const string reason = "Biometric hardware unavailable or not enrolled.";
                    _logger.LogWarning(reason);
                    return AuthenticationResult.Failed(reason);
                }

                // Show system-native biometric prompt.
                var biometricResult = await _deviceBiometricProvider.AuthenticateAsync(
                                                           "Authenticate to access your TycoonVerse wallet",
                                                           cancellationToken)
                                                       .ConfigureAwait(false);

                if (!biometricResult.IsSuccess)
                {
                    string msg = biometricResult.ErrorMessage ??
                                 "Unknown biometric error (the provider returned no reason).";

                    _logger.LogWarning("Biometric authentication failed: {Error}", msg);

                    OnAuthenticationFailed(msg);
                    return AuthenticationResult.Failed(msg);
                }

                // Retrieve encrypted session token from secure storage.
                var encryptedToken = await _secureTokenStore.GetAsync(Constants.SecureStorageKeys.SessionToken,
                                                                     cancellationToken)
                                                            .ConfigureAwait(false);

                if (string.IsNullOrEmpty(encryptedToken))
                {
                    // User logged in for the first time on this device and has no persisted session yet.
                    const string msg =
                        "No session token found. User must log in with credentials to establish a session.";
                    _logger.LogInformation(msg);

                    OnAuthenticationFailed(msg);
                    return AuthenticationResult.Failed(msg, requiresCredentialLogin: true);
                }

                // Decrypt the token with the biometric secret.
                var token = DecryptToken(encryptedToken, biometricResult.Secret);

                _logger.LogInformation("Biometric authentication succeeded.");
                OnAuthenticationSucceeded(token);

                return AuthenticationResult.Success(token);
            }
            catch (OperationCanceledException)
            {
                _logger.LogInformation("Biometric authentication canceled by user.");
                return AuthenticationResult.Failed("Authentication canceled by user.");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Unexpected exception while executing biometric authentication.");
                return AuthenticationResult.Failed(
                    "Unexpected authentication error. Please try again or contact support.");
            }
        }

        /// <summary>
        /// Encrypts and persists the session token. Should be invoked after the user has
        /// authenticated by credentials (email/pass, SSO, …) so that subsequent sign-ins
        /// can rely solely on biometrics.
        /// </summary>
        public async Task PersistSessionAsync(string plainSessionToken,
                                              CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(plainSessionToken))
                throw new ArgumentException("Token must not be null/empty.", nameof(plainSessionToken));

            // Use provider key to derive an encryption secret unique to the device.
            var secret = await _deviceBiometricProvider.GetDeviceSecretAsync(cancellationToken)
                                                       .ConfigureAwait(false);

            var cipher = EncryptToken(plainSessionToken, secret);

            await _secureTokenStore.SetAsync(Constants.SecureStorageKeys.SessionToken,
                                             cipher,
                                             cancellationToken)
                                   .ConfigureAwait(false);

            _logger.LogDebug("Session token encrypted and stored securely.");
        }

        #region Crypto helpers

        private static string EncryptToken(string plain, byte[] secret)
        {
            using Aes aes = Aes.Create();
            aes.Key = secret;
            aes.GenerateIV();

            using var encryptor = aes.CreateEncryptor();
            var plainBytes      = Encoding.UTF8.GetBytes(plain);
            var cipherBytes     = encryptor.TransformFinalBlock(plainBytes, 0, plainBytes.Length);

            // Prepend IV for later decryption; encode with Base64 for storage.
            var combined = new byte[aes.IV.Length + cipherBytes.Length];
            Buffer.BlockCopy(aes.IV,       0, combined, 0,                aes.IV.Length);
            Buffer.BlockCopy(cipherBytes,  0, combined, aes.IV.Length,    cipherBytes.Length);

            return Convert.ToBase64String(combined);
        }

        private static string DecryptToken(string cipher, byte[] secret)
        {
            var combined = Convert.FromBase64String(cipher);

            using Aes aes = Aes.Create();
            aes.Key = secret;

            // Extract IV embedded in the cipher text.
            var ivLen      = aes.BlockSize / 8; // bytes
            var iv         = new byte[ivLen];
            var cipherText = new byte[combined.Length - ivLen];

            Buffer.BlockCopy(combined, 0,        iv,         0, ivLen);
            Buffer.BlockCopy(combined, ivLen,    cipherText, 0, cipherText.Length);

            aes.IV = iv;

            using var decryptor = aes.CreateDecryptor();
            var decryptedBytes  = decryptor.TransformFinalBlock(cipherText, 0, cipherText.Length);

            return Encoding.UTF8.GetString(decryptedBytes);
        }

        #endregion

        #region Event dispatchers

        private void OnAuthenticationSucceeded(string sessionToken) =>
            AuthenticationSucceeded?.Invoke(
                this,
                new BiometricAuthenticationEventArgs(true, sessionToken));

        private void OnAuthenticationFailed(string error) =>
            AuthenticationFailed?.Invoke(
                this,
                new BiometricAuthenticationEventArgs(false, errorMessage: error));

        #endregion
    }

    #region Interfaces / contracts (kept internal to avoid external coupling in this snippet)

    /// <summary>
    /// Cross-platform abstraction for biometric hardware interactions.
    /// </summary>
    public interface IDeviceBiometricProvider
    {
        Task<bool> IsBiometricsAvailableAsync(CancellationToken cancellationToken = default);

        /// <summary>
        /// Shows the system biometric prompt and returns whether the user was authenticated.
        /// If successful it also returns a device-unique secret which can be used for
        /// encrypting/decrypting persistent tokens.
        /// </summary>
        Task<BiometricProviderResult> AuthenticateAsync(string promptMessage,
                                                        CancellationToken cancellationToken = default);

        /// <summary>
        /// Returns the device secret (hardware-bound key) without showing any UI.  
        /// Used for encryption when the user has already unlocked the device/session.
        /// </summary>
        Task<byte[]> GetDeviceSecretAsync(CancellationToken cancellationToken = default);
    }

    public record BiometricProviderResult(bool IsSuccess,
                                          byte[] Secret,
                                          string? ErrorMessage = null);

    /// <summary>
    /// Secure storage abstraction (Keychain, Keystore, DPAPI, etc.).
    /// </summary>
    public interface ISecureTokenStore
    {
        Task<string?> GetAsync(string key, CancellationToken cancellationToken = default);
        Task SetAsync(string key, string value, CancellationToken cancellationToken = default);
        Task RemoveAsync(string key, CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Public façade consumed throughout the application.
    /// </summary>
    public interface IBiometricAuthenticationService
    {
        /// <summary>
        /// Attempts to authenticate the current user using device biometrics.
        /// </summary>
        Task<AuthenticationResult> AuthenticateAsync(CancellationToken cancellationToken = default);

        /// <summary>
        /// Persists a credential/session in secure storage so that future sign-ins can rely
        /// solely on biometrics without credentials.
        /// </summary>
        Task PersistSessionAsync(string plainSessionToken,
                                 CancellationToken cancellationToken = default);

        event EventHandler<BiometricAuthenticationEventArgs>? AuthenticationSucceeded;
        event EventHandler<BiometricAuthenticationEventArgs>? AuthenticationFailed;
    }

    #endregion

    #region DTOs

    public sealed class AuthenticationResult
    {
        private AuthenticationResult(bool isSuccess,
                                     string? sessionToken = null,
                                     string? errorMessage = null,
                                     bool    requiresCredentialLogin = false)
        {
            IsSuccess               = isSuccess;
            SessionToken            = sessionToken;
            ErrorMessage            = errorMessage;
            RequiresCredentialLogin = requiresCredentialLogin;
        }

        public bool   IsSuccess               { get; }
        public string? SessionToken           { get; }
        public string? ErrorMessage           { get; }
        public bool   RequiresCredentialLogin { get; }

        public static AuthenticationResult Success(string sessionToken) =>
            new(true, sessionToken);

        public static AuthenticationResult Failed(string error,
                                                  bool requiresCredentialLogin = false) =>
            new(false, errorMessage: error,
                requiresCredentialLogin: requiresCredentialLogin);
    }

    public sealed class BiometricAuthenticationEventArgs : EventArgs
    {
        public BiometricAuthenticationEventArgs(bool isSuccess,
                                                string? sessionToken = null,
                                                string? errorMessage = null)
        {
            IsSuccess     = isSuccess;
            SessionToken  = sessionToken;
            ErrorMessage  = errorMessage;
        }

        public bool   IsSuccess    { get; }
        public string? SessionToken { get; }
        public string? ErrorMessage { get; }
    }

    #endregion

    #region Internal helpers

    internal static class Constants
    {
        internal static class SecureStorageKeys
        {
            public const string SessionToken = "tv.session.token";
        }
    }

    #endregion
}
```