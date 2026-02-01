package com.wellsphere.connect.core.security;

import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import androidx.annotation.NonNull;
import androidx.annotation.RequiresApi;

import java.nio.ByteBuffer;
import java.security.GeneralSecurityException;
import java.security.InvalidAlgorithmParameterException;
import java.security.KeyStore;
import java.security.KeyStoreException;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;

import javax.crypto.BadPaddingException;
import javax.crypto.Cipher;
import javax.crypto.CipherInputStream;
import javax.crypto.CipherOutputStream;
import javax.crypto.IllegalBlockSizeException;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

import java.io.Closeable;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;

/**
 * EncryptionHelper is a small, opinionated façade over the Android Keystore.
 *
 * It provides:
 *   • Transparent generation & storage of an AES-256 key inside the system Keystore.
 *   • AES/GCM/NoPadding encryption of arbitrary byte[] or File payloads.
 *   • Base64 helpers for convenient String round-tripping.
 *
 * By design, the helper does NOT cache Cipher instances (thread safety) and will throw a
 * {@link EncryptionException} wrapping the underlying cause for easier upstream handling.
 *
 * <p>
 * NOTE: Only API 23+ is supported. On lower API levels, {@link #isAvailable()} will be false and
 * calls to encrypt/decrypt will throw immediately—WellSphere requires API 23+ anyway.
 * </p>
 */
public final class EncryptionHelper {

    // --- Public constants ----------------------------------------------------

    public static final String TRANSFORMATION = "AES/GCM/NoPadding";
    public static final int GCM_IV_LENGTH = 12;            // 96 bits—the recommended size.
    public static final int GCM_TAG_LENGTH = 128;          // 128 bits authentication tag.
    public static final int AES_KEY_SIZE = 256;            // 256 bits (if permitted by the device).
    public static final String KEYSTORE_PROVIDER = "AndroidKeyStore";
    public static final String KEY_ALIAS = "wellsphere_connect_aes_key";

    // --- Singleton wiring ----------------------------------------------------

    private static volatile EncryptionHelper sInstance;

    /**
     * Returns the global {@link EncryptionHelper}. You may call this from any thread.
     */
    public static EncryptionHelper getInstance() {
        if (sInstance == null) {
            synchronized (EncryptionHelper.class) {
                if (sInstance == null) {
                    sInstance = new EncryptionHelper();
                }
            }
        }
        return sInstance;
    }

    // --- Public API ----------------------------------------------------------

    public boolean isAvailable() {
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.M;
    }

    /**
     * Encrypt the given plaintext. The returned byte[] is a concatenation of IV + ciphertext,
     * allowing stateless round-tripping.
     *
     * @param plaintext bytes to encrypt
     * @return IV || CIPHERTEXT
     */
    public byte[] encrypt(@NonNull byte[] plaintext) {
        checkPreconditions();

        try {
            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey(), generateIvParams(cipher));
            byte[] encrypted = cipher.doFinal(plaintext);

            byte[] iv = cipher.getIV();
            ByteBuffer buffer = ByteBuffer.allocate(iv.length + encrypted.length);
            buffer.put(iv);
            buffer.put(encrypted);
            return buffer.array();

        } catch (GeneralSecurityException e) {
            throw new EncryptionException("Failed to encrypt payload", e);
        }
    }

    /**
     * Decrypt a byte[] previously produced by {@link #encrypt(byte[])}.
     */
    public byte[] decrypt(@NonNull byte[] ivAndCiphertext) {
        checkPreconditions();

        try {
            ByteBuffer buffer = ByteBuffer.wrap(ivAndCiphertext);

            byte[] iv = new byte[GCM_IV_LENGTH];
            buffer.get(iv);

            byte[] cipherText = new byte[buffer.remaining()];
            buffer.get(cipherText);

            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            GCMParameterSpec spec = new GCMParameterSpec(GCM_TAG_LENGTH, iv);
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), spec);

            return cipher.doFinal(cipherText);

        } catch (BadPaddingException | IllegalBlockSizeException e) {
            // Usually indicates wrong key or tampered data
            throw new EncryptionException("Invalid or corrupted ciphertext", e);
        } catch (GeneralSecurityException e) {
            throw new EncryptionException("Failed to decrypt payload", e);
        }
    }

    /**
     * Convenience method for String round-tripping. Internally uses UTF-8 and Base64 URL-safe
     * encoding without padding.
     */
    public String encryptToBase64(@NonNull String clearText) {
        byte[] cipher = encrypt(clearText.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        return Base64.encodeToString(cipher, Base64.URL_SAFE | Base64.NO_WRAP);
    }

    /**
     * Reverse operation for {@link #encryptToBase64(String)}.
     */
    public String decryptFromBase64(@NonNull String base64) {
        byte[] ivAndCipher = Base64.decode(base64, Base64.URL_SAFE | Base64.NO_WRAP);
        byte[] plain = decrypt(ivAndCipher);
        return new String(plain, java.nio.charset.StandardCharsets.UTF_8);
    }

    /**
     * Encrypts a file in streaming fashion and writes the result to {@code targetFile}.
     * The format is IV || CIPHERTEXT (same as byte[] methods).
     *
     * @param sourceFile clear-text file
     * @param targetFile encrypted output file (will be overwritten if it exists)
     */
    public void encryptFile(@NonNull File sourceFile, @NonNull File targetFile) {
        processFile(sourceFile, targetFile, Cipher.ENCRYPT_MODE);
    }

    /**
     * Decrypts {@code sourceFile} into {@code targetFile}. The {@code sourceFile} must have been
     * created by {@link #encryptFile(File, File)}.
     */
    public void decryptFile(@NonNull File sourceFile, @NonNull File targetFile) {
        processFile(sourceFile, targetFile, Cipher.DECRYPT_MODE);
    }

    /**
     * Removes the key from the Keystore. Usually only needed during a user sign-out flow.
     */
    public void destroyKey() {
        if (!isAvailable()) return;

        try {
            KeyStore ks = KeyStore.getInstance(KEYSTORE_PROVIDER);
            ks.load(null);
            ks.deleteEntry(KEY_ALIAS);
        } catch (Exception e) {
            throw new EncryptionException("Unable to delete keystore entry", e);
        }
    }

    // ----------------------------------------------------------------------------
    // Internal helpers
    // ----------------------------------------------------------------------------

    private EncryptionHelper() {
    }

    private void checkPreconditions() {
        if (!isAvailable()) {
            throw new EncryptionException("EncryptionHelper is not available on this device");
        }
    }

    @RequiresApi(api = Build.VERSION_CODES.M)
    private SecretKey getOrCreateKey() throws GeneralSecurityException {
        KeyStore keyStore = KeyStore.getInstance(KEYSTORE_PROVIDER);
        keyStore.load(null);

        // Key already exists?
        SecretKey key = (SecretKey) keyStore.getKey(KEY_ALIAS, null);
        if (key != null) {
            return key;
        }

        // Create fresh key.
        KeyGenerator keyGen = KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES, KEYSTORE_PROVIDER);

        KeyGenParameterSpec spec = new KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setKeySize(AES_KEY_SIZE)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                // Invalidate the key if the user disables lock-screen protections.
                .setUserAuthenticationRequired(false)
                .build();

        keyGen.init(spec);
        return keyGen.generateKey();
    }

    private GCMParameterSpec generateIvParams(Cipher cipher)
            throws InvalidAlgorithmParameterException {
        byte[] iv = new byte[GCM_IV_LENGTH];
        new SecureRandom().nextBytes(iv);
        return new GCMParameterSpec(GCM_TAG_LENGTH, iv);
    }

    private void processFile(@NonNull File source, @NonNull File target, int mode) {
        checkPreconditions();

        Cipher cipher;
        try {
            cipher = Cipher.getInstance(TRANSFORMATION);
            if (mode == Cipher.ENCRYPT_MODE) {
                cipher.init(mode, getOrCreateKey(), generateIvParams(cipher));
            } else {
                // For decryption we need to read IV from source first.
                byte[] iv = new byte[GCM_IV_LENGTH];
                try (FileInputStream in = new FileInputStream(source)) {
                    ensureRead(in.read(iv), iv.length);
                } catch (IOException e) {
                    throw new EncryptionException("Unable to read IV from encrypted file", e);
                }
                cipher.init(mode, getOrCreateKey(), new GCMParameterSpec(GCM_TAG_LENGTH, iv));
            }
        } catch (GeneralSecurityException e) {
            throw new EncryptionException("Failed to init cipher", e);
        }

        if (mode == Cipher.ENCRYPT_MODE) {
            try (FileInputStream in = new FileInputStream(source);
                 FileOutputStream out = new FileOutputStream(target)) {

                // Write IV first
                out.write(cipher.getIV());

                try (CipherOutputStream cos = new CipherOutputStream(out, cipher)) {
                    copyStreams(in, cos);
                }
            } catch (IOException e) {
                throw new EncryptionException("File encryption failed", e);
            }
        } else { // DECRYPT_MODE
            try (FileInputStream in = new FileInputStream(source);
                 FileOutputStream out = new FileOutputStream(target)) {

                // Skip IV bytes (already read above)
                long skipped = in.skip(GCM_IV_LENGTH);
                if (skipped != GCM_IV_LENGTH) {
                    throw new EncryptionException("Could not skip IV in encrypted file");
                }

                try (CipherInputStream cis = new CipherInputStream(in, cipher)) {
                    copyStreams(cis, out);
                }
            } catch (IOException e) {
                throw new EncryptionException("File decryption failed", e);
            }
        }
    }

    private void copyStreams(@NonNull FileInputStream in, @NonNull CipherOutputStream out)
            throws IOException {
        copyStreams((java.io.InputStream) in, (java.io.OutputStream) out);
    }

    private void copyStreams(@NonNull CipherInputStream in, @NonNull FileOutputStream out)
            throws IOException {
        copyStreams((java.io.InputStream) in, (java.io.OutputStream) out);
    }

    private void copyStreams(java.io.InputStream in, java.io.OutputStream out)
            throws IOException {
        byte[] buffer = new byte[8 * 1024];
        int n;
        while ((n = in.read(buffer)) != -1) {
            out.write(buffer, 0, n);
        }
        out.flush();
    }

    private void ensureRead(int bytesRead, int expected) throws IOException {
        if (bytesRead != expected) {
            throw new IOException("Expected " + expected + " bytes, but got " + bytesRead);
        }
    }

    // ----------------------------------------------------------------------------
    // Custom runtime exception for caller convenience.
    // ----------------------------------------------------------------------------

    public static class EncryptionException extends RuntimeException {
        EncryptionException(String message) {
            super(message);
        }

        EncryptionException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}