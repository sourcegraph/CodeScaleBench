```rust
//! nft_factory.rs
//!
//! CanvasChain Symphony – Minting Service
//! --------------------------------------
//! Factory & Strategy pattern–powered NFT minting logic.
//! Creates multilayer NFTs, signs mint payloads with a pluggable crypto
//! backend and broadcasts events onto the internal event-bus.
//!
//! This file purposefully hides transport concerns (gRPC, HTTP, etc.); the
//! factory is a pure domain component that can be wired into whatever
//! outer-layer the micro-service exposes.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use tokio::sync::RwLock;
use tracing::{debug, error, info, instrument};
use uuid::Uuid;

use thiserror::Error;

/// ------------------------------------------------------------------------------------------------
/// Domain Types
/// ------------------------------------------------------------------------------------------------

/// Human-readable, multi-layer NFT metadata sent by the client.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MintRequest {
    /// Wallet address of the creator in bech32 / hex format (depends on chain).
    pub creator_wallet: String,
    /// An ordered list of media layers that compose the artwork.
    pub layers: Vec<NftLayer>,
    /// Royalty basis-points (1/100 of a percent).
    pub royalty_bps: u16,
    /// Arbitrary on-chain attributes (e.g. color_palette → “pastel”).
    pub attributes: HashMap<String, String>,
    /// Number used once to avoid replay attacks.
    pub nonce: u64,
}

/// Individual layer of the final NFT.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NftLayer {
    pub id: u32,
    /// IPFS / Arweave / S3 URI
    pub uri: String,
}

/// Normalised payload that the chain client can send to the runtime.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MintPayload {
    pub idempotency_key: Uuid,
    pub creator_wallet: String,
    pub metadata_cid: String,
    pub royalty_bps: u16,
    pub signature: Vec<u8>,
}

/// Successful on-chain minting result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NftReceipt {
    pub token_id: u64,
    pub tx_hash: String,
    pub signature: Vec<u8>,
}

/// ------------------------------------------------------------------------------------------------
/// Error Handling
/// ------------------------------------------------------------------------------------------------

#[derive(Error, Debug)]
pub enum FactoryError {
    #[error("invalid royalty basis points: {0}")]
    InvalidRoyalty(u16),
    #[error("mint payload validation error: {0}")]
    Validation(String),
    #[error("crypto error: {0}")]
    Crypto(#[from] CryptoError),
    #[error("blockchain client error: {0}")]
    Blockchain(#[from] BlockchainError),
    #[error("event bus error: {0}")]
    EventBus(#[from] EventBusError),
}

#[derive(Error, Debug)]
pub enum CryptoError {
    #[error("unsupported curve")]
    UnsupportedCurve,
    #[error("signature generation failed")]
    SignFailure,
}

#[derive(Error, Debug)]
pub enum BlockchainError {
    #[error("node unreachable")]
    NodeUnreachable,
    #[error("transaction rejected: {0}")]
    TransactionRejected(String),
}

#[derive(Error, Debug)]
pub enum EventBusError {
    #[error("publish failed")]
    PublishFailed,
}

/// ------------------------------------------------------------------------------------------------
/// Traits (Strategy / Port abstractions)
/// ------------------------------------------------------------------------------------------------

/// Unified crypto-signer strategy so we can swap Ed25519, BLS, PQ, etc.
#[async_trait]
pub trait CryptoSigner: Send + Sync {
    /// ‘Human’ name of the algorithm (ed25519, bls12381, falcon, …).
    fn algorithm(&self) -> &'static str;

    /// Public identifier derived from the secret key (hex / bech32).
    fn public_key(&self) -> String;

    /// Sign arbitrary message bytes.
    async fn sign(&self, message: &[u8]) -> Result<Vec<u8>, CryptoError>;
}

/// Port for whatever chain client we’re using (substrate, cosmos, homework-chain).
#[async_trait]
pub trait BlockchainClient: Send + Sync {
    async fn submit_mint(&self, payload: MintPayload) -> Result<String, BlockchainError>;
    async fn latest_token_id(&self) -> Result<u64, BlockchainError>;
}

/// Simplistic event bus publisher (fan-out / kafka / nats / anything).
#[async_trait]
pub trait EventPublisher: Send + Sync {
    async fn publish<M: Serialize + Send + Sync>(&self, topic: &str, msg: &M) -> Result<(), EventBusError>;
}

/// ------------------------------------------------------------------------------------------------
/// NFT Factory (Concrete implementation of the Factory pattern)
/// ------------------------------------------------------------------------------------------------

/// Shared reference-counted pointer to immutable factory configuration.
#[derive(Debug, Clone)]
pub struct FactoryConfig {
    /// Maximum allowed royalty (bps). Prevents creator mistakes.
    pub max_royalty_bps: u16,
    /// Event bus topic for successful mints.
    pub event_topic_success: String,
    /// Event bus topic for failed mints.
    pub event_topic_failure: String,
}

pub struct NftFactory<S, C, E>
where
    S: CryptoSigner,
    C: BlockchainClient,
    E: EventPublisher,
{
    signer: Arc<S>,
    chain: Arc<C>,
    bus: Arc<E>,
    config: Arc<FactoryConfig>,
    // optionally keep some internal state (metrics, counters, etc.)
    minted_counter: RwLock<u64>,
}

impl<S, C, E> NftFactory<S, C, E>
where
    S: CryptoSigner + 'static,
    C: BlockchainClient + 'static,
    E: EventPublisher + 'static,
{
    pub fn new(signer: Arc<S>, chain: Arc<C>, bus: Arc<E>, config: FactoryConfig) -> Self {
        Self {
            signer,
            chain,
            bus,
            config: Arc::new(config),
            minted_counter: RwLock::new(0),
        }
    }

    /// Validate, sign, submit and broadcast the mint request.
    #[instrument(skip_all, level = "info", fields(creator = %req.creator_wallet))]
    pub async fn mint_nft(&self, req: MintRequest) -> Result<NftReceipt, FactoryError> {
        self.validate_request(&req)?;

        // ---------------------------------------------------------------------
        // 1. Serialize metadata to JSON; in reality we would push to IPFS/Arweave
        // and obtain a CID, we’ll fake it by hashing the JSON.
        // ---------------------------------------------------------------------
        let metadata_json = serde_json::to_vec(&req)
            .map_err(|e| FactoryError::Validation(format!("metadata serialization: {e}")))?;

        let metadata_cid = hex::encode(blake3::hash(&metadata_json).as_bytes());

        // ---------------------------------------------------------------------
        // 2. Build chain payload and sign it with the selected algorithm.
        // ---------------------------------------------------------------------
        let idempotency_key = Uuid::new_v4();
        let mut payload_bytes = Vec::new();
        payload_bytes.extend_from_slice(idempotency_key.as_bytes());
        payload_bytes.extend_from_slice(metadata_cid.as_bytes());
        payload_bytes.extend_from_slice(&req.royalty_bps.to_le_bytes());
        payload_bytes.extend_from_slice(req.creator_wallet.as_bytes());
        payload_bytes.extend_from_slice(&req.nonce.to_le_bytes());

        let signature = self.signer.sign(&payload_bytes).await?;

        let payload = MintPayload {
            idempotency_key,
            creator_wallet: req.creator_wallet.clone(),
            metadata_cid,
            royalty_bps: req.royalty_bps,
            signature: signature.clone(),
        };

        // ---------------------------------------------------------------------
        // 3. Submit mint extrinsic / transaction to the chain.
        // ---------------------------------------------------------------------
        let tx_hash = match self.chain.submit_mint(payload.clone()).await {
            Ok(h) => h,
            Err(e) => {
                // fire & forget failure event
                let _ = self
                    .bus
                    .publish(
                        &self.config.event_topic_failure,
                        &MintFailureEvent::from_request(&req, &format!("{e}")),
                    )
                    .await;
                return Err(e.into());
            }
        };

        // ---------------------------------------------------------------------
        // 4. Retrieve token ID (optimistic assumption we mint sequentially).
        // ---------------------------------------------------------------------
        let token_id = self.chain.latest_token_id().await?;

        // ---------------------------------------------------------------------
        // 5. Bump metrics & broadcast success event.
        // ---------------------------------------------------------------------
        {
            let mut counter = self.minted_counter.write().await;
            *counter += 1;
        }

        let receipt = NftReceipt {
            token_id,
            tx_hash: tx_hash.clone(),
            signature,
        };

        self.bus
            .publish(&self.config.event_topic_success, &receipt)
            .await?;

        info!(token_id, tx_hash, "NFT minted successfully");
        Ok(receipt)
    }

    // -------------------
    // internal helpers
    // -------------------
    fn validate_request(&self, req: &MintRequest) -> Result<(), FactoryError> {
        if req.royalty_bps > self.config.max_royalty_bps {
            return Err(FactoryError::InvalidRoyalty(req.royalty_bps));
        }
        if req.layers.is_empty() {
            return Err(FactoryError::Validation("at least one layer required".into()));
        }
        if req.creator_wallet.trim().is_empty() {
            return Err(FactoryError::Validation("creator_wallet is empty".into()));
        }
        Ok(())
    }
}

/// ------------------------------------------------------------------------------------------------
/// Event Definitions
/// ------------------------------------------------------------------------------------------------

#[derive(Debug, Serialize)]
struct MintFailureEvent {
    pub creator_wallet: String,
    pub timestamp_ms: u128,
    pub reason: String,
}

impl MintFailureEvent {
    fn from_request(req: &MintRequest, reason: &str) -> Self {
        Self {
            creator_wallet: req.creator_wallet.clone(),
            timestamp_ms: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("system time ok")
                .as_millis(),
            reason: reason.to_string(),
        }
    }
}

/// ------------------------------------------------------------------------------------------------
/// Dummy/Mock implementations behind ‘test’ feature so we can run unit tests.
/// ------------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    // --------------------
    // Mock crypto signer
    // --------------------
    struct MockSigner;
    #[async_trait]
    impl CryptoSigner for MockSigner {
        fn algorithm(&self) -> &'static str {
            "mocked-ed25519"
        }

        fn public_key(&self) -> String {
            "deadbeef".to_string()
        }

        async fn sign(&self, message: &[u8]) -> Result<Vec<u8>, CryptoError> {
            Ok(blake3::hash(message).as_bytes().to_vec())
        }
    }

    // --------------------
    // Mock chain client
    // --------------------
    struct MockChain {
        counter: Mutex<u64>,
    }

    #[async_trait]
    impl BlockchainClient for MockChain {
        async fn submit_mint(&self, _payload: MintPayload) -> Result<String, BlockchainError> {
            let mut c = self.counter.lock().unwrap();
            *c += 1;
            Ok(format!("0x{:x}", *c))
        }

        async fn latest_token_id(&self) -> Result<u64, BlockchainError> {
            let c = self.counter.lock().unwrap();
            Ok(*c)
        }
    }

    // --------------------
    // Mock event bus
    // --------------------
    struct MockBus;
    #[async_trait]
    impl EventPublisher for MockBus {
        async fn publish<M: Serialize + Send + Sync>(
            &self,
            topic: &str,
            msg: &M,
        ) -> Result<(), EventBusError> {
            let payload = serde_json::to_string(msg).unwrap();
            debug!(topic, payload, "mock bus publish");
            Ok(())
        }
    }

    #[tokio::test]
    async fn test_mint_success() {
        let signer = Arc::new(MockSigner);
        let chain = Arc::new(MockChain {
            counter: Mutex::new(0),
        });
        let bus = Arc::new(MockBus);
        let factory = NftFactory::new(
            signer,
            chain,
            bus,
            FactoryConfig {
                max_royalty_bps: 2_000, // 20%
                event_topic_success: "nft.mint.success".into(),
                event_topic_failure: "nft.mint.failure".into(),
            },
        );

        let req = MintRequest {
            creator_wallet: "0xabc123".into(),
            layers: vec![NftLayer {
                id: 1,
                uri: "ipfs://QmDUMMY".into(),
            }],
            royalty_bps: 500,
            attributes: HashMap::new(),
            nonce: 42,
        };

        let receipt = factory.mint_nft(req.clone()).await.unwrap();
        assert_eq!(receipt.token_id, 1);
        assert!(!receipt.tx_hash.is_empty());
    }

    #[tokio::test]
    async fn test_invalid_royalty() {
        let signer = Arc::new(MockSigner);
        let chain = Arc::new(MockChain {
            counter: Mutex::new(0),
        });
        let bus = Arc::new(MockBus);
        let factory = NftFactory::new(
            signer,
            chain,
            bus,
            FactoryConfig {
                max_royalty_bps: 2_000,
                event_topic_success: "nft.mint.success".into(),
                event_topic_failure: "nft.mint.failure".into(),
            },
        );

        let req = MintRequest {
            creator_wallet: "0xabc123".into(),
            layers: vec![NftLayer {
                id: 1,
                uri: "ipfs://QmDUMMY".into(),
            }],
            royalty_bps: 22_000, // 220%
            attributes: HashMap::new(),
            nonce: 1,
        };

        let err = factory.mint_nft(req).await.unwrap_err();
        matches!(err, FactoryError::InvalidRoyalty(_));
    }
}
```