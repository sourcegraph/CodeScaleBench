package com.wellsphere.connect.core.security;

import android.app.Activity;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.CancellationSignal;

import androidx.annotation.NonNull;
import androidx.annotation.RequiresApi;
import androidx.biometric.BiometricManager;
import androidx.biometric.BiometricPrompt;
import androidx.core.content.ContextCompat;

import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.Arrays;
import java.util.Objects;
import java.util.concurrent.Executor;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.IvParameterSpec;

/**
 * BiometricAuthManager is a production-ready, thread-safe wrapper around AndroidX BiometricPrompt.
 * <p>
 * Responsibilities:
 * <ul>
 *     <li>Verify whether the current device &amp; user have biometric capability/enrollment.</li>
 *     <li>Generate &amp; keep a hardware-backed AES secret key in the Android Keystore.</li>
 *     <li>Expose high-level authenticate() API with proper cipher handling and lifecycle safety.</li>
 *     <li>Optionally encrypt and persist a session token for automatic re-authentication.</li>
 * </ul>
 *
 * The manager intentionally hides low-level details to make ViewModels/UI less error-prone while
 * preserving security guarantees (e.g. KeyGenParameterSpec.setUserAuthenticationRequired).
 */
public final class BiometricAuthManager {

    // ----  PUBLIC TYPES ------------------------------------------------------------------------

    /**
     * Callback for clients to receive authentication events.
     */
    public interface AuthCallback {

        /**
         * Called when authentication has succeeded and (optionally) a decrypted token is provided.
         *
         * @param token Decrypted session token, or {@code null} if none was stored/required.
         */
        void onAuthSuccess(String token);

        /**
         * Called when authentication failed due to user interaction (e.g. cancel, too many attempts).
         *
         * @param reason Message safe to expose in UI.
         */
        void onAuthFailed(@NonNull String reason);

        /**
         * Called when an unrecoverable error occurred (e.g. crypto failure).
         *
         * @param t Throwable detailing the root cause.
         */
        void onError(@NonNull Throwable t);
    }

    // ----  SINGLETON ---------------------------------------------------------------------------

    private static final Object LOCK = new Object();
    private static BiometricAuthManager INSTANCE;

    public static BiometricAuthManager getInstance(@NonNull Context context) {
        synchronized (LOCK) {
            if (INSTANCE == null) {
                INSTANCE = new BiometricAuthManager(context.getApplicationContext());
            }
            return INSTANCE;
        }
    }

    // ----  CONSTANTS ---------------------------------------------------------------------------

    private static final String ANDROID_KEYSTORE = "AndroidKeyStore";
    private static final String KEY_ALIAS = "wellsphere_biometric_aes_key";
    private static final String PREF_FILE = "wellsphere_biometric_prefs";
    private static final String PREF_CIPHER_TEXT = "cipher_text";
    private static final String PREF_IV = "init_vector";

    // ----  MEMBERS -----------------------------------------------------------------------------

    private final Context appContext;
    private final Executor mainExecutor;
    private final SharedPreferences prefs;
    private final KeyStore keyStore;

    // ----  CONSTRUCTOR -------------------------------------------------------------------------

    private BiometricAuthManager(Context context) {
        appContext = Objects.requireNonNull(context);
        mainExecutor = ContextCompat.getMainExecutor(appContext);
        prefs = appContext.getSharedPreferences(PREF_FILE, Context.MODE_PRIVATE);
        try {
            keyStore = KeyStore.getInstance(ANDROID_KEYSTORE);
            keyStore.load(null);
        } catch (Exception e) {
            // This is fatal: Without KeyStore we cannot offer biometric login.
            throw new IllegalStateException("Unable to load AndroidKeyStore", e);
        }
    }

    // ----  BIOMETRIC CAPABILITY CHECKS ---------------------------------------------------------

    /**
     * Indicates whether device hardware and user enrollment can satisfy biometric auth.
     */
    public boolean isBiometricAvailable() {
        int result = BiometricManager.from(appContext)
                                     .canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG);
        return result == BiometricManager.BIOMETRIC_SUCCESS;
    }

    // ----  PUBLIC API --------------------------------------------------------------------------

    /**
     * Start biometric authentication workflow.
     *
     * @param activity      Hosting activity (must be foreground / resumed).
     * @param promptTitle   Title shown on biometric prompt.
     * @param callback      Consumer of auth results.
     */
    public void authenticate(@NonNull Activity activity,
                             @NonNull String promptTitle,
                             @NonNull AuthCallback callback) {

        if (!isBiometricAvailable()) {
            callback.onAuthFailed("Biometric hardware unavailable or not enrolled");
            return;
        }

        try {
            Cipher cipher = prefs.contains(PREF_CIPHER_TEXT)
                            ? getDecryptCipher()
                            : getEncryptCipher();    // first-time enrollment

            BiometricPrompt.CryptoObject cryptoObject = new BiometricPrompt.CryptoObject(cipher);
            BiometricPrompt.PromptInfo promptInfo = new BiometricPrompt.PromptInfo.Builder()
                    .setTitle(promptTitle)
                    .setSubtitle("Authenticate to continue")
                    .setNegativeButtonText("Cancel")
                    .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
                    .build();

            BiometricPrompt biometricPrompt =
                    new BiometricPrompt(activity, mainExecutor, new PromptCallback(callback));

            biometricPrompt.authenticate(promptInfo, cryptoObject);

        } catch (GeneralSecurityException gse) {
            callback.onError(gse);
        }
    }

    /**
     * Clear any encrypted token persisted in SharedPreferences.
     * Typically called on logout or when user revokes biometric consent.
     */
    public void clearStoredToken() {
        prefs.edit().clear().apply();
    }

    // ----  PRIVATE HELPERS ---------------------------------------------------------------------

    private Cipher getEncryptCipher() throws GeneralSecurityException {
        SecretKey secretKey = getOrCreateSecretKey();
        Cipher cipher = Cipher.getInstance("AES/CBC/PKCS7Padding");
        cipher.init(Cipher.ENCRYPT_MODE, secretKey);
        return cipher;
    }

    private Cipher getDecryptCipher() throws GeneralSecurityException {
        byte[] iv = getStoredIv();
        if (iv == null) {
            throw new GeneralSecurityException("Missing IV for decryption");
        }
        SecretKey secretKey = getOrCreateSecretKey();
        Cipher cipher = Cipher.getInstance("AES/CBC/PKCS7Padding");
        cipher.init(Cipher.DECRYPT_MODE, secretKey, new IvParameterSpec(iv));
        return cipher;
    }

    private SecretKey getOrCreateSecretKey() throws GeneralSecurityException {
        if (keyStore.containsAlias(KEY_ALIAS)) {
            return ((SecretKey) keyStore.getKey(KEY_ALIAS, null));
        }

        KeyGenerator generator = KeyGenerator.getInstance("AES", ANDROID_KEYSTORE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            generator.init(KeyGenSpecs.build(KEY_ALIAS));
        } else {
            throw new GeneralSecurityException("Biometric auth requires API 23+");
        }
        return generator.generateKey();
    }

    private byte[] getStoredIv() {
        String base64 = prefs.getString(PREF_IV, null);
        return base64 == null ? null : android.util.Base64.decode(base64, android.util.Base64.DEFAULT);
    }

    private void persistToken(byte[] cipherText, byte[] iv) {
        prefs.edit()
             .putString(PREF_CIPHER_TEXT, android.util.Base64.encodeToString(cipherText, android.util.Base64.DEFAULT))
             .putString(PREF_IV, android.util.Base64.encodeToString(iv, android.util.Base64.DEFAULT))
             .apply();
    }

    // ----  INTERNAL CALLBACK  ------------------------------------------------------------------

    private class PromptCallback extends BiometricPrompt.AuthenticationCallback {

        private final AuthCallback external;

        PromptCallback(AuthCallback external) {
            this.external = external;
        }

        @Override
        public void onAuthenticationError(int errorCode, @NonNull CharSequence errString) {
            if (errorCode == BiometricPrompt.ERROR_NEGATIVE_BUTTON
                || errorCode == BiometricPrompt.ERROR_USER_CANCELED
                || errorCode == BiometricPrompt.ERROR_CANCELED) {
                external.onAuthFailed(errString.toString());
            } else {
                external.onError(new RuntimeException(errString.toString()));
            }
        }

        @Override
        public void onAuthenticationSucceeded(@NonNull BiometricPrompt.AuthenticationResult result) {
            try {
                Cipher cipher = Objects.requireNonNull(result.getCryptoObject()).getCipher();
                if (prefs.contains(PREF_CIPHER_TEXT)) {
                    // Existing token -> decrypt
                    byte[] cipherText = android.util.Base64.decode(
                            prefs.getString(PREF_CIPHER_TEXT, null),
                            android.util.Base64.DEFAULT);
                    String token = new String(cipher.doFinal(cipherText));
                    external.onAuthSuccess(token);
                } else {
                    // First run -> generate & encrypt random token
                    String token = java.util.UUID.randomUUID().toString();
                    byte[] encrypted = cipher.doFinal(token.getBytes());
                    persistToken(encrypted, cipher.getIV());
                    external.onAuthSuccess(token);
                }
            } catch (Exception e) {
                external.onError(e);
            }
        }

        @Override
        public void onAuthenticationFailed() {
            // Non-fatal, just inform UI that the attempt was invalid.
            external.onAuthFailed("Fingerprint not recognized. Try again.");
        }
    }

    // ----  KEYGEN PARAMETER SPEC BUILDER (M API) -----------------------------------------------

    @RequiresApi(api = Build.VERSION_CODES.M)
    private static final class KeyGenSpecs {

        static android.security.keystore.KeyGenParameterSpec build(String alias) {
            return new android.security.keystore.KeyGenParameterSpec.Builder(
                    alias,
                    android.security.keystore.KeyProperties.PURPOSE_ENCRYPT
                            | android.security.keystore.KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(android.security.keystore.KeyProperties.BLOCK_MODE_CBC)
                    .setEncryptionPaddings(android.security.keystore.KeyProperties.ENCRYPTION_PADDING_PKCS7)
                    .setUserAuthenticationRequired(true)     // ties key to biometric
                    .setInvalidatedByBiometricEnrollment(true) // revoke on new enrollment
                    .build();
        }
    }
}