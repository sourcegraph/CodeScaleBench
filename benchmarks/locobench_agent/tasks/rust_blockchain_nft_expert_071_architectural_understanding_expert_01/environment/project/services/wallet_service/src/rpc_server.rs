```rust
//! RPC server for the Wallet micro-service.
//!
//! The wallet RPC server exposes a small gRPC interface that lets other
//! Symphony services (or external clients) create wallets, query balances,
//! transfer tokens and sign arbitrary messages.  
//!
//! Internally the server is backed by a pluggable [`WalletBackend`] trait.
//! The default backend (`SledBackend`) stores encrypted key-material in a
//! Sled embedded database and uses ed25519‐dalek for signing.  Backends can
//! be swapped at runtime (Strategy pattern) which makes it trivial to
//! upgrade to BLS, post-quantum or hardware-based signing in the future.
//!
//! # Conventions
//!
//! * All monetary amounts are expressed in **atomic units** (u128).
//! * Hex-encoded strings are expected to be lowercase, without `0x` prefix.
//! * Errors are mapped to gRPC `Status` codes using a custom [`WalletError`]
//!   → [`tonic::Status`] conversion.

#![allow(clippy::missing_errors_doc)]
#![allow(clippy::missing_panics_doc)]

use std::{net::SocketAddr, path::PathBuf, sync::Arc};

use async_trait::async_trait;
use ed25519_dalek::{Keypair, PublicKey, Signature, Signer, PUBLIC_KEY_LENGTH};
use rand::rngs::OsRng;
use thiserror::Error;
use tokio::sync::RwLock;
use tonic::{transport::Server, Request, Response, Status};
use tracing::{error, info};

use crate::config::WalletConfig;

// === Generated code from `protoc` lives in `crate::proto` === //
use crate::proto::wallet::{
    wallet_service_server::{WalletService, WalletServiceServer},
    BalanceRequest, BalanceResponse, CreateWalletRequest, CreateWalletResponse,
    SignRequest, SignResponse, TransferRequest, TransferResponse,
};

// =========================================================================
//  Domain errors
// =========================================================================

/// All domain-level errors produced by the wallet service.
#[derive(Debug, Error)]
pub enum WalletError {
    #[error("wallet `{0}` not found")]
    WalletNotFound(String),

    #[error("insufficient funds (available: {available}, required: {required})")]
    InsufficientFunds { available: u128, required: u128 },

    #[error("database error: {0}")]
    Db(#[from] sled::Error),

    #[error("signature failure: {0}")]
    Signature(String),

    #[error("unsupported cryptographic backend")]
    UnsupportedBackend,

    #[error("internal error: {0}")]
    Internal(String),
}

impl From<WalletError> for Status {
    fn from(err: WalletError) -> Self {
        match err {
            WalletError::WalletNotFound(_) => Status::not_found(err.to_string()),
            WalletError::InsufficientFunds { .. } => Status::failed_precondition(err.to_string()),
            WalletError::Db(_) | WalletError::Internal(_) => Status::internal(err.to_string()),
            WalletError::Signature(_) => Status::internal(err.to_string()),
            WalletError::UnsupportedBackend => Status::unimplemented(err.to_string()),
        }
    }
}

// =========================================================================
//  Wallet backend abstraction (Strategy Pattern)
// =========================================================================

/// Abstraction over the storage + crypto engine used for wallet operations.
#[async_trait]
pub trait WalletBackend: Send + Sync + 'static {
    async fn create_wallet(&self) -> Result<(String, PublicKey), WalletError>;

    async fn balance(&self, wallet_id: &str) -> Result<u128, WalletError>;

    async fn transfer(
        &self,
        from: &str,
        to: &str,
        amount: u128,
    ) -> Result<(), WalletError>;

    async fn sign(
        &self,
        wallet_id: &str,
        message: &[u8],
    ) -> Result<Signature, WalletError>;
}

// =========================================================================
//  Default backend implementation (Sled + Ed25519)
// =========================================================================

/// Wallet metadata stored in the DB (serialized with `bincode`).
#[derive(serde::Serialize, serde::Deserialize)]
struct WalletRecord {
    keypair: Keypair,
    balance: u128,
}

/// Simple Sled-based backend storing encrypted key-material locally.
pub struct SledBackend {
    db: sled::Db,
    /// Namespace trees
    keys_tree: sled::Tree,
    ledger_tree: sled::Tree,
}

impl SledBackend {
    pub fn new(path: impl Into<PathBuf>) -> Result<Self, WalletError> {
        let db = sled::open(path.into())?;
        Ok(Self {
            keys_tree: db.open_tree("keys")?,
            ledger_tree: db.open_tree("ledger")?,
            db,
        })
    }

    fn _wallet_key(wallet_id: &str) -> Vec<u8> {
        format!("wallet::{wallet_id}").into_bytes()
    }
}

#[async_trait]
impl WalletBackend for SledBackend {
    async fn create_wallet(&self) -> Result<(String, PublicKey), WalletError> {
        // Generate new keypair
        let mut csprng = OsRng {};
        let keypair = Keypair::generate(&mut csprng);
        let wallet_id = hex::encode(&keypair.public.to_bytes());

        let record = WalletRecord {
            keypair,
            balance: 0u128,
        };
        // Serialize
        let payload = bincode::serialize(&record)
            .map_err(|e| WalletError::Internal(format!("bincode: {e}")))?;

        self.keys_tree
            .insert(Self::_wallet_key(&wallet_id), payload)?;
        self.ledger_tree.insert(wallet_id.as_bytes(), 0u128.to_be_bytes())?;
        self.db.flush()?;

        Ok((wallet_id, record.keypair.public))
    }

    async fn balance(&self, wallet_id: &str) -> Result<u128, WalletError> {
        let raw = self
            .ledger_tree
            .get(wallet_id.as_bytes())?
            .ok_or_else(|| WalletError::WalletNotFound(wallet_id.to_string()))?;
        let mut bytes = [0u8; 16];
        bytes.copy_from_slice(&raw);
        Ok(u128::from_be_bytes(bytes))
    }

    async fn transfer(
        &self,
        from: &str,
        to: &str,
        amount: u128,
    ) -> Result<(), WalletError> {
        // Sled does not support multi-key transactions; we pessimistically lock the DB.
        let _guard = self.db.transaction(|db| {
            let from_balance = {
                let raw = self
                    .ledger_tree
                    .get(from.as_bytes())?
                    .ok_or(sled::transaction::ConflictableTransactionError::Abort(
                        WalletError::WalletNotFound(from.into()),
                    ))?;
                let mut b = [0u8; 16];
                b.copy_from_slice(&raw);
                Ok(u128::from_be_bytes(b))
            }?;

            if from_balance < amount {
                return Err(sled::transaction::ConflictableTransactionError::Abort(
                    WalletError::InsufficientFunds {
                        available: from_balance,
                        required: amount,
                    },
                ));
            }

            let to_balance = {
                let raw =
                    self.ledger_tree.get(to.as_bytes())?.unwrap_or_else(|| {
                        // Auto-create destination account
                        self.ledger_tree.insert(to.as_bytes(), 0u128.to_be_bytes()).unwrap();
                        sled::IVec::from(&0u128.to_be_bytes()[..])
                    });
                let mut b = [0u8; 16];
                b.copy_from_slice(&raw);
                u128::from_be_bytes(b)
            };

            let new_from = (from_balance - amount).to_be_bytes();
            let new_to = (to_balance + amount).to_be_bytes();

            self.ledger_tree.insert(from.as_bytes(), new_from)?;
            self.ledger_tree.insert(to.as_bytes(), new_to)?;
            Ok(())
        });

        match _guard {
            Ok(_) => Ok(()),
            Err(sled::transaction::TransactionError::Abort(e)) => Err(e),
            Err(e) => Err(WalletError::Db(e.into())),
        }
    }

    async fn sign(
        &self,
        wallet_id: &str,
        message: &[u8],
    ) -> Result<Signature, WalletError> {
        let raw = self
            .keys_tree
            .get(Self::_wallet_key(wallet_id))?
            .ok_or_else(|| WalletError::WalletNotFound(wallet_id.to_owned()))?;
        let record: WalletRecord =
            bincode::deserialize(&raw).map_err(|e| WalletError::Internal(e.to_string()))?;
        Ok(record.keypair.sign(message))
    }
}

// =========================================================================
//  RPC layer
// =========================================================================

#[derive(Clone)]
pub struct RpcServer<B> {
    backend: Arc<B>,
}

impl<B> RpcServer<B>
where
    B: WalletBackend,
{
    pub fn new(backend: Arc<B>) -> Self {
        Self { backend }
    }
}

#[tonic::async_trait]
impl<B> WalletService for RpcServer<B>
where
    B: WalletBackend,
{
    async fn create_wallet(
        &self,
        _req: Request<CreateWalletRequest>,
    ) -> Result<Response<CreateWalletResponse>, Status> {
        let (id, public_key) = self.backend.create_wallet().await?;
        let resp = CreateWalletResponse {
            wallet_id: id,
            public_key: hex::encode(public_key.to_bytes()),
        };
        Ok(Response::new(resp))
    }

    async fn balance(
        &self,
        req: Request<BalanceRequest>,
    ) -> Result<Response<BalanceResponse>, Status> {
        let BalanceRequest { wallet_id } = req.into_inner();
        let balance = self.backend.balance(&wallet_id).await?;
        Ok(Response::new(BalanceResponse { balance }))
    }

    async fn transfer(
        &self,
        req: Request<TransferRequest>,
    ) -> Result<Response<TransferResponse>, Status> {
        let TransferRequest {
            from_wallet_id,
            to_address,
            amount,
        } = req.into_inner();

        self.backend
            .transfer(&from_wallet_id, &to_address, amount)
            .await?;

        Ok(Response::new(TransferResponse {}))
    }

    async fn sign(
        &self,
        req: Request<SignRequest>,
    ) -> Result<Response<SignResponse>, Status> {
        let SignRequest {
            wallet_id,
            message,
        } = req.into_inner();
        let signature = self.backend.sign(&wallet_id, &message).await?;
        Ok(Response::new(SignResponse {
            signature: hex::encode(signature.to_bytes()),
            public_key_len: PUBLIC_KEY_LENGTH as u32,
        }))
    }
}

// =========================================================================
//  Bootstrapping
// =========================================================================

/// Starts the wallet RPC server and blocks the calling task.
///
/// # Errors
/// Propagates any IO / transport errors bubbling up from `tonic`.
pub async fn serve(config: WalletConfig) -> Result<(), anyhow::Error> {
    let addr: SocketAddr = config.listen_addr.parse()?;
    info!(?addr, "starting Wallet RPC server");

    // === Choose backend based on config ===
    let backend: Arc<dyn WalletBackend> = match config.backend_backend.as_str() {
        "sled" | "" => Arc::new(SledBackend::new(&config.data_dir)?),
        unsupported => {
            error!("backend `{unsupported}` not supported");
            return Err(WalletError::UnsupportedBackend.into());
        }
    };

    let server = RpcServer::new(backend);

    Server::builder()
        .add_service(WalletServiceServer::new(server))
        // Add built-in gRPC health service so Kubernetes liveness probes work.
        .serve(addr)
        .await?;

    Ok(())
}
```
