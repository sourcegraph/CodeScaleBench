```rust
//! Key Manager
//!
//! The Key Manager is responsible for generating, encrypting, storing and
//! retrieving private keys for the wallet–service.  It supports multiple
//! signing curves (Ed25519 and Secp256k1 today; BLS can be added behind a
//! feature-flag) and uses Argon2 + ChaCha20-Poly1305 to protect keys at
//! rest.
//!
//! The module follows a Strategy pattern where each curve implements the
//! `SigningCurve` trait.  A very small, file–based keystore is provided for
//! demo/PoC purposes; in production an HSM or KMS implementation should
//! instead be plugged in via the same trait.
//!
//! NOTE: All public functions are `async` to keep the API uniform even
//! though the current implementation is I/O–bound only.

use std::{
    fs::{self, File},
    io::Write,
    path::{Path, PathBuf},
    sync::Arc,
};

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use chacha20poly1305::{
    aead::{Aead, AeadCore, KeyInit, OsRng as ChaOsRng},
    ChaCha20Poly1305, Key, Nonce,
};
use rand_core::RngCore;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokio::sync::RwLock;
use uuid::Uuid;

// ─────────────────────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────────────────────

/// Supported signature algorithms.
///
/// New curves (BLS, PQ, …) can be enabled behind a Cargo feature flag and
/// added here without touching the rest of the service.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub enum CryptoAlgorithm {
    Ed25519,
    Secp256k1,
}

/// A minimal, curve-agnostic keypair.
///
/// The concrete key material is stored encrypted on disk; we only keep the
/// public key and metadata in memory.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WalletMeta {
    pub id:              Uuid,
    pub algo:            CryptoAlgorithm,
    pub public_key:      Vec<u8>,
    pub encrypted_sk:    Vec<u8>,
    pub enc_salt:        Vec<u8>,
    pub enc_nonce:       Vec<u8>,
    pub created_at:      DateTime<Utc>,
}

/// Top-level manager.
///
/// Internally uses a `KeyStore` implementation and a registry of available
/// signing curves.
#[derive(Clone)]
pub struct KeyManager {
    keystore: Arc<dyn KeyStore>,
    curves:   CurveRegistry,
}

impl KeyManager {
    /// Create a new manager with the default [`FileKeyStore`].
    pub async fn new<P: AsRef<Path>>(file: P) -> Result<Self, KeyManagerError> {
        let ks = FileKeyStore::open(file).await?;
        let mut registry = CurveRegistry::default();
        registry.register(Box::<Ed25519Curve>::default());
        registry.register(Box::<Secp256k1Curve>::default());

        Ok(Self {
            keystore: Arc::new(ks),
            curves:   registry,
        })
    }

    /// Creates and persists a brand new wallet.
    pub async fn create_wallet(
        &self,
        password: &[u8],
        algo: CryptoAlgorithm,
    ) -> Result<WalletMeta, KeyManagerError> {
        let curve = self
            .curves
            .get(algo)
            .ok_or(KeyManagerError::UnsupportedAlgorithm)?;

        // 1) Generate a fresh keypair
        let (sk, pk) = curve.generate()?;

        // 2) Encrypt the secret key with Argon2 + ChaCha20-Poly1305
        let (ciphertext, salt, nonce) = encrypt_secret(password, &sk)?;

        // 3) Store on disk
        let wallet = WalletMeta {
            id: Uuid::new_v4(),
            algo,
            public_key: pk,
            encrypted_sk: ciphertext,
            enc_salt: salt.to_vec(),
            enc_nonce: nonce.to_vec(),
            created_at: Utc::now(),
        };

        self.keystore.put(&wallet).await?;
        Ok(wallet)
    }

    /// Unlock a wallet, returning the raw secret key in memory for
    /// subsequent signing.  The caller is responsible for zeroizing the
    /// buffer after use.
    pub async fn unlock_wallet(
        &self,
        id: Uuid,
        password: &[u8],
    ) -> Result<UnlockedWallet, KeyManagerError> {
        let meta = self
            .keystore
            .get(id)
            .await?
            .ok_or(KeyManagerError::WalletNotFound)?;

        let curve = self
            .curves
            .get(meta.algo)
            .ok_or(KeyManagerError::UnsupportedAlgorithm)?;

        let sk = decrypt_secret(
            password,
            &meta.encrypted_sk,
            &meta.enc_salt,
            &meta.enc_nonce,
        )?;

        Ok(UnlockedWallet {
            meta,
            secret_key: sk,
            curve,
        })
    }

    /// Sign an arbitrary message with the given wallet.
    pub async fn sign(
        &self,
        wallet: &UnlockedWallet,
        message: &[u8],
    ) -> Result<Vec<u8>, KeyManagerError> {
        wallet.curve.sign(&wallet.secret_key, message)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Unlocked wallet (ephemeral)
// ─────────────────────────────────────────────────────────────────────────────

/// Ephemeral wallet handle.
///
/// The secret key is kept in memory only and never persisted; once the value
/// goes out of scope it should be considered locked again.
pub struct UnlockedWallet<'a> {
    meta:       WalletMeta,
    secret_key: Vec<u8>,
    curve:      &'a dyn SigningCurve,
}

impl<'a> UnlockedWallet<'a> {
    pub fn public_key(&self) -> &[u8] {
        &self.meta.public_key
    }

    pub fn id(&self) -> Uuid {
        self.meta.id
    }

    pub fn algo(&self) -> CryptoAlgorithm {
        self.meta.algo
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Signing curves (Strategy pattern)
// ─────────────────────────────────────────────────────────────────────────────

/// Strategy trait for crypto curves.
pub trait SigningCurve: Send + Sync {
    fn algorithm(&self) -> CryptoAlgorithm;

    /// Generate a fresh keypair.
    fn generate(&self) -> Result<(Vec<u8>, Vec<u8>), KeyManagerError>;

    /// Sign `message` with the raw secret key.
    fn sign(&self, secret: &[u8], message: &[u8]) -> Result<Vec<u8>, KeyManagerError>;

    /// Verify a signature – primarily for unit tests.
    #[allow(dead_code)]
    fn verify(
        &self,
        public: &[u8],
        message: &[u8],
        signature: &[u8],
    ) -> Result<(), KeyManagerError>;
}

/// Registry holding all curve implementations.
#[derive(Default, Clone)]
struct CurveRegistry {
    curves: Arc<RwLock<Vec<Box<dyn SigningCurve>>>>,
}

impl CurveRegistry {
    fn register(&mut self, curve: Box<dyn SigningCurve>) {
        tokio::task::block_in_place(|| {
            let mut guard = futures::executor::block_on(self.curves.write());
            guard.push(curve);
        });
    }

    fn get(&self, algo: CryptoAlgorithm) -> Option<&dyn SigningCurve> {
        tokio::task::block_in_place(|| {
            let guard = futures::executor::block_on(self.curves.read());
            guard
                .iter()
                .find(|c| c.algorithm() == algo)
                .map(|b| b.as_ref())
        })
    }
}

// ─── Ed25519 ────────────────────────────────────────────────────────────────

#[derive(Default)]
struct Ed25519Curve;

impl SigningCurve for Ed25519Curve {
    fn algorithm(&self) -> CryptoAlgorithm {
        CryptoAlgorithm::Ed25519
    }

    fn generate(&self) -> Result<(Vec<u8>, Vec<u8>), KeyManagerError> {
        use ed25519_dalek::{Keypair, SignatureError, Signer};
        let kp: Keypair = Keypair::generate(&mut rand_core::OsRng);
        Ok((kp.secret.to_bytes().to_vec(), kp.public.to_bytes().to_vec()))
    }

    fn sign(&self, secret: &[u8], message: &[u8]) -> Result<Vec<u8>, KeyManagerError> {
        use ed25519_dalek::{Keypair, PublicKey, SecretKey, Signer};
        let secret = SecretKey::from_bytes(secret)?;
        let public: PublicKey = (&secret).into();
        let kp = Keypair { secret, public };
        Ok(kp.sign(message).to_bytes().to_vec())
    }

    fn verify(
        &self,
        public: &[u8],
        message: &[u8],
        signature: &[u8],
    ) -> Result<(), KeyManagerError> {
        use ed25519_dalek::{PublicKey, Signature, Verifier};
        let pk = PublicKey::from_bytes(public)?;
        let sig = Signature::from_bytes(signature)?;
        pk.verify(message, &sig)?;
        Ok(())
    }
}

// ─── Secp256k1 ──────────────────────────────────────────────────────────────

#[derive(Default)]
struct Secp256k1Curve;

impl SigningCurve for Secp256k1Curve {
    fn algorithm(&self) -> CryptoAlgorithm {
        CryptoAlgorithm::Secp256k1
    }

    fn generate(&self) -> Result<(Vec<u8>, Vec<u8>), KeyManagerError> {
        use k256::{
            ecdsa::{SigningKey, VerifyingKey},
            elliptic_curve::SecretKey as ECSecret,
        };
        let sk = SigningKey::random(&mut rand_core::OsRng);
        let pk = VerifyingKey::from(&sk);
        let sk_bytes = ECSecret::from(sk).to_bytes().to_vec();
        Ok((sk_bytes, pk.to_encoded_point(false).as_bytes().to_vec()))
    }

    fn sign(&self, secret: &[u8], message: &[u8]) -> Result<Vec<u8>, KeyManagerError> {
        use k256::ecdsa::{signature::Signer as _, Signature, SigningKey};
        let sk = SigningKey::from_bytes(secret.into())?;
        let sig: Signature = sk.sign(message);
        Ok(sig.as_ref().to_vec())
    }

    fn verify(
        &self,
        public: &[u8],
        message: &[u8],
        signature: &[u8],
    ) -> Result<(), KeyManagerError> {
        use k256::ecdsa::{signature::Verifier as _, Signature, VerifyingKey};
        let vk = VerifyingKey::from_sec1_bytes(public)?;
        let sig = Signature::from_der(signature)?;
        vk.verify(message, &sig)?;
        Ok(())
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Keystore (file-based JSON)
// ─────────────────────────────────────────────────────────────────────────────

#[async_trait]
trait KeyStore: Send + Sync {
    async fn put(&self, wallet: &WalletMeta) -> Result<(), KeyManagerError>;
    async fn get(&self, id: Uuid) -> Result<Option<WalletMeta>, KeyManagerError>;
}

/// A very small file-based keystore.
///
/// Thread-safe via `RwLock` plus atomic write-to-tmp-then-rename.
struct FileKeyStore {
    path:   PathBuf,
    cache:  RwLock<Vec<WalletMeta>>,
}

impl FileKeyStore {
    async fn open<P: AsRef<Path>>(p: P) -> Result<Self, KeyManagerError> {
        let path = p.as_ref().to_path_buf();
        if !path.exists() {
            // create empty file
            tokio::fs::write(&path, b"[]").await?;
        }

        let data = tokio::fs::read(&path).await?;
        let wallets: Vec<WalletMeta> = serde_json::from_slice(&data)?;
        Ok(Self {
            path,
            cache: RwLock::new(wallets),
        })
    }

    async fn persist(&self, list: &[WalletMeta]) -> Result<(), KeyManagerError> {
        let tmp_path = self
            .path
            .with_extension("tmp");

        let data = serde_json::to_vec_pretty(list)?;
        // atomic write to tmp then rename
        tokio::task::spawn_blocking({
            let tmp_path = tmp_path.clone();
            let data = data.clone();
            move || -> Result<(), KeyManagerError> {
                let mut tmp_file = File::create(&tmp_path)?;
                tmp_file.write_all(&data)?;
                tmp_file.sync_all()?;
                fs::rename(&tmp_path, &self.path)?;
                Ok(())
            }
        })
        .await??;

        Ok(())
    }
}

#[async_trait]
impl KeyStore for FileKeyStore {
    async fn put(&self, wallet: &WalletMeta) -> Result<(), KeyManagerError> {
        let mut guard = self.cache.write().await;
        guard.push(wallet.clone());
        self.persist(&guard).await?;
        Ok(())
    }

    async fn get(&self, id: Uuid) -> Result<Option<WalletMeta>, KeyManagerError> {
        let guard = self.cache.read().await;
        Ok(guard.iter().cloned().find(|w| w.id == id))
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Crypto helpers (Argon2 + ChaCha20-Poly1305)
// ─────────────────────────────────────────────────────────────────────────────

const CHACHA_NONCE_SIZE: usize = 12;
const ARGON_SALT_LEN: usize = 16;
const ARGON_MEM_COST_KIB: u32 = 64 * 1024; // 64 MiB
const ARGON_ITER: u32 = 3;

fn encrypt_secret(
    password: &[u8],
    secret: &[u8],
) -> Result<(Vec<u8>, [u8; ARGON_SALT_LEN], [u8; CHACHA_NONCE_SIZE]), KeyManagerError> {
    let mut salt = [0u8; ARGON_SALT_LEN];
    ChaOsRng.fill_bytes(&mut salt);
    let key = derive_key(password, &salt)?;

    let cipher = ChaCha20Poly1305::new(Key::from_slice(&key));
    let mut nonce = [0u8; CHACHA_NONCE_SIZE];
    ChaOsRng.fill_bytes(&mut nonce);

    let ciphertext = cipher.encrypt(Nonce::from_slice(&nonce), secret)?;
    Ok((ciphertext, salt, nonce))
}

fn decrypt_secret(
    password: &[u8],
    ciphertext: &[u8],
    salt: &[u8],
    nonce: &[u8],
) -> Result<Vec<u8>, KeyManagerError> {
    let key = derive_key(password, salt)?;
    let cipher = ChaCha20Poly1305::new(Key::from_slice(&key));
    let plaintext = cipher.decrypt(Nonce::from_slice(nonce), ciphertext)?;
    Ok(plaintext)
}

fn derive_key(password: &[u8], salt: &[u8]) -> Result<[u8; 32], KeyManagerError> {
    use argon2::{
        password_hash::{PasswordHasher, Salt},
        Argon2, Params, Version,
    };
    let params = Params::new(
        ARGON_MEM_COST_KIB,
        ARGON_ITER,
        1,
        Some(32),
    )?;
    let argon = Argon2::new(argon2::Algorithm::Argon2id, Version::V0x13, params);
    let hash = argon.hash_password(password, Some(Salt::from(salt)))?;
    let mut key = [0u8; 32];
    key.copy_from_slice(hash.hash.ok_or(KeyManagerError::KdfFailed)?.as_bytes());
    Ok(key)
}

// ─────────────────────────────────────────────────────────────────────────────
// Error types
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Error, Debug)]
pub enum KeyManagerError {
    // I/O
    #[error("I/O: {0}")]
    Io(#[from] std::io::Error),

    // Serde
    #[error("serialization: {0}")]
    Serde(#[from] serde_json::Error),

    // Crypto libs
    #[error("ed25519: {0}")]
    Ed25519(#[from] ed25519_dalek::SignatureError),

    #[error("secp256k1: {0}")]
    Secp256k1(#[from] k256::ecdsa::Error),

    #[error("crypto: {0}")]
    Crypto(#[from] chacha20poly1305::aead::Error),

    #[error("argon2: {0}")]
    Argon2(#[from] argon2::password_hash::Error),

    // Custom
    #[error("wallet not found")]
    WalletNotFound,

    #[error("unsupported algorithm")]
    UnsupportedAlgorithm,

    #[error("kdf failed")]
    KdfFailed,
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::NamedTempFile;

    #[tokio::test]
    async fn roundtrip_ed25519() {
        // Set up temporary keystore file
        let file = NamedTempFile::new().unwrap();
        let km = KeyManager::new(file.path()).await.unwrap();

        // Create wallet
        let pwd = b"correct horse battery staple";
        let wallet = km
            .create_wallet(pwd, CryptoAlgorithm::Ed25519)
            .await
            .unwrap();

        // Unlock + sign
        let unlocked = km.unlock_wallet(wallet.id, pwd).await.unwrap();
        let msg = b"hello canvaschain";
        let sig = km.sign(&unlocked, msg).await.unwrap();

        // Verify
        let curve = km.curves.get(CryptoAlgorithm::Ed25519).unwrap();
        curve
            .verify(unlocked.public_key(), msg, &sig)
            .expect("signature should verify");
    }
}
```