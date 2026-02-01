```rust
//! Minting service business logic.
//!
//! This module orchestrates the full NFT-minting life-cycle for the
//! `CanvasChain Symphony` platform.  
//! Responsibilities:
//!   * Validate incoming mint-requests coming from the gRPC edge
//!     (wallet/mobile/CLI/third-party SDK).
//!   * Verify request signatures using the pluggable [`SignatureStrategy`]
//!     trait (Strategy Pattern).
//!   * Enforce governance & business rules (max layers, throttling, etc.).
//!   * Emit a transaction to the on-chain smart-contract via
//!     [`BlockchainClient`] (Proxy / Facade).
//!   * Broadcast a domain event to the global event-bus so that other
//!     micro-services (marketplace, royalty, UI) can react in real-time.
//!
//! The code purposefully avoids concrete network/blockchain details so that
//! the core logic can be unit-tested in isolation or reused by a WASM front-end
//! without pulling native crypto libraries.
//!
//! IMPORTANT: Real key-handling is **NOT** implemented here—private keys must
//! never be loaded into application memory. All signing happens inside secure
//! enclaves or wallet extensions.  
//! This module *only* performs **verification**.

#![forbid(unsafe_code)]

use std::{fmt, sync::Arc};

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokio::time::{timeout, Duration};
use tracing::{debug, error, info, instrument};
use uuid::Uuid;

/* ------------------------------------------------------------------------- */
/*                               Public Models                               */
/* ------------------------------------------------------------------------- */

/// Parameters provided by a client wishing to mint a new NFT.
///
/// NOTE: The binary‐compatible representation is also used over gRPC.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MintRequest {
    /// Wallet address of the caller (must match signature).
    pub creator_address: String,
    /// Content‐addressed URI that describes the NFT layers/traits manifest.
    pub metadata_uri: String,
    /// Number of composable sub-layers in this NFT (1..=MAX_LAYERS)
    pub layers: u8,
    /// Unix epoch millis to mitigate replay attacks.
    pub timestamp: i64,
    /// Arbitrary number to make the request unique (client-side).
    pub nonce: Uuid,
    /// Cryptographic signature over the canonical hash of the request.
    pub signature: Vec<u8>,
}

/// Returned to the caller after a successful mint operation.
///
/// It contains the on-chain transaction hash so that UIs can poll for
/// confirmations.  
/// The struct purposefully excludes any sensitive data.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MintReceipt {
    pub request_id: Uuid,
    pub tx_hash: String,
    pub block_height: u64,
}

/* ------------------------------------------------------------------------- */
/*                              Error Handling                               */
/* ------------------------------------------------------------------------- */

#[derive(Debug, Error)]
pub enum MintingError {
    #[error("validation failed: {0}")]
    Validation(String),
    #[error("signature rejected")]
    InvalidSignature,
    #[error("blockchain client error: {0}")]
    Blockchain(#[from] BlockchainError),
    #[error("could not publish event: {0}")]
    EventBus(#[from] EventBusError),
    #[error("internal timeout")]
    Timeout,
}

/// Errors propagated from the blockchain client façade.
#[derive(Debug, Error)]
#[error("{message}")]
pub struct BlockchainError {
    message: String,
}

impl BlockchainError {
    pub fn new<S: Into<String>>(msg: S) -> Self {
        Self {
            message: msg.into(),
        }
    }
}

/// Errors propagated from the async event broker.
#[derive(Debug, Error)]
#[error("{message}")]
pub struct EventBusError {
    message: String,
}

impl EventBusError {
    pub fn new<S: Into<String>>(msg: S) -> Self {
        Self {
            message: msg.into(),
        }
    }
}

/* ------------------------------------------------------------------------- */
/*                          External Infrastructure                          */
/* ------------------------------------------------------------------------- */

/// Abstraction over the low-level Chain RPC (Proxy Pattern).
#[async_trait]
pub trait BlockchainClient: Send + Sync {
    /// Submit an already-signed smart-contract call.
    async fn submit_nft_mint_tx(
        &self,
        call_data: Vec<u8>,
    ) -> Result<SubmitTxResponse, BlockchainError>;
}

/// What the chain returns after broadcasting a tx.
#[derive(Debug, Clone)]
pub struct SubmitTxResponse {
    pub tx_hash: String,
    pub block_height: u64,
}

/// Event-bus producer for pub-sub.  
/// We keep the contract minimal: one topic + raw bytes.
#[async_trait]
pub trait EventPublisher: Send + Sync {
    async fn publish(&self, topic: &str, payload: Vec<u8>) -> Result<(), EventBusError>;
}

/* ------------------------------------------------------------------------- */
/*                           Signature Verification                          */
/* ------------------------------------------------------------------------- */

/// Strategy pattern to support multiple curves/implementations.
#[async_trait]
pub trait SignatureStrategy: Send + Sync + fmt::Debug {
    /// Verify that `sig` is a valid signature of `message` produced by `address`.
    async fn verify(
        &self,
        address: &str,
        message: &[u8],
        sig: &[u8],
    ) -> Result<(), MintingError>;
}

#[cfg(feature = "ed25519")]
pub mod ed25519_strategy {
    use super::*;
    use ed25519_dalek::{PublicKey, Signature, Verifier};
    use sha2::{Digest, Sha512};

    /// Implementation using Ed25519 (default).
    #[derive(Debug, Default)]
    pub struct Ed25519Verifier;

    #[async_trait]
    impl SignatureStrategy for Ed25519Verifier {
        async fn verify(
            &self,
            address: &str,
            message: &[u8],
            sig: &[u8],
        ) -> Result<(), MintingError> {
            let public_key_bytes = hex::decode(address)
                .map_err(|_| MintingError::InvalidSignature)?;
            let public_key =
                PublicKey::from_bytes(&public_key_bytes).map_err(|_| MintingError::InvalidSignature)?;

            let hashed = Sha512::digest(message);
            let signature = Signature::from_bytes(sig).map_err(|_| MintingError::InvalidSignature)?;

            public_key
                .verify(&hashed, &signature)
                .map_err(|_| MintingError::InvalidSignature)
        }
    }
}

#[cfg(feature = "bls")]
pub mod bls_strategy {
    use super::*;
    // `blst` (or any BLS crate) would go here; omitted for brevity.
    #[derive(Debug, Default)]
    pub struct BlsVerifier;

    #[async_trait]
    impl SignatureStrategy for BlsVerifier {
        async fn verify(
            &self,
            _address: &str,
            _message: &[u8],
            _sig: &[u8],
        ) -> Result<(), MintingError> {
            // TODO: Implement real verification.
            Err(MintingError::InvalidSignature)
        }
    }
}

/* ------------------------------------------------------------------------- */
/*                              Minting Engine                               */
/* ------------------------------------------------------------------------- */

/// Hard business limits enforced by governance.
const MAX_LAYERS: u8 = 32;
const MAX_METADATA_URI_LEN: usize = 2048;
const SIGNING_TIMEOUT_MS: u64 = 750;

/// The core orchestration façade consumed by the gRPC handlers.
#[derive(Debug)]
pub struct MintingService {
    blockchain: Arc<dyn BlockchainClient>,
    event_bus: Arc<dyn EventPublisher>,
    sig_strategy: Arc<dyn SignatureStrategy>,
}

impl MintingService {
    pub fn new(
        blockchain: Arc<dyn BlockchainClient>,
        event_bus: Arc<dyn EventPublisher>,
        sig_strategy: Arc<dyn SignatureStrategy>,
    ) -> Self {
        Self {
            blockchain,
            event_bus,
            sig_strategy,
        }
    }

    /// Perform full mint workflow.
    #[instrument(skip(self, req))]
    pub async fn mint(&self, req: MintRequest) -> Result<MintReceipt, MintingError> {
        self.validate(&req)?;

        // Hash message deterministically.
        let message = self.hash_request(&req);

        // Verify signature with timeout guard.
        timeout(
            Duration::from_millis(SIGNING_TIMEOUT_MS),
            self.sig_strategy.verify(&req.creator_address, &message, &req.signature),
        )
        .await
        .map_err(|_| MintingError::Timeout)??;

        info!("signature verified for {}", req.creator_address);

        // Construct on-chain call (ABI encoding depends on your smart contract;
        // using a placeholder here).
        let call_data = self.encode_contract_call(&req);

        // Submit to blockchain and await inclusion.
        let SubmitTxResponse {
            tx_hash,
            block_height,
        } = self.blockchain.submit_nft_mint_tx(call_data).await?;

        info!(%tx_hash, %block_height, "NFT mint transaction submitted");

        // Notify the ecosystem.
        let event_payload = serde_json::to_vec(&req).expect("MintRequest is serializable");
        self.event_bus
            .publish("nft.minted", event_payload)
            .await?;

        Ok(MintReceipt {
            request_id: req.nonce,
            tx_hash,
            block_height,
        })
    }

    fn validate(&self, req: &MintRequest) -> Result<(), MintingError> {
        if req.layers == 0 || req.layers > MAX_LAYERS {
            return Err(MintingError::Validation(format!(
                "layers must be 1..={MAX_LAYERS}"
            )));
        }
        if req.metadata_uri.len() > MAX_METADATA_URI_LEN {
            return Err(MintingError::Validation(
                "metadata URI too long".to_string(),
            ));
        }
        // Additional anti-replay and timestamp validations would go here.
        Ok(())
    }

    fn hash_request(&self, req: &MintRequest) -> Vec<u8> {
        use blake2::{Blake2b512, Digest};

        let mut hasher = Blake2b512::new();
        hasher.update(req.creator_address.as_bytes());
        hasher.update(req.metadata_uri.as_bytes());
        hasher.update(&[req.layers]);
        hasher.update(&req.timestamp.to_le_bytes());
        hasher.update(req.nonce.as_bytes());
        hasher.finalize().to_vec()
    }

    fn encode_contract_call(&self, req: &MintRequest) -> Vec<u8> {
        // Placeholder ABI encoding.
        let mut bytes = Vec::with_capacity(64);
        bytes.extend(req.creator_address.as_bytes());
        bytes.extend(req.metadata_uri.as_bytes());
        bytes.extend(&[req.layers]);
        bytes
    }
}

/* ------------------------------------------------------------------------- */
/*                                 Testing                                   */
/* ------------------------------------------------------------------------- */

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::sync::Mutex;

    /* ----------------------------- Mocks ---------------------------------- */

    struct MockBlockchain {
        store: Mutex<HashMap<String, Vec<u8>>>,
    }

    #[async_trait]
    impl BlockchainClient for MockBlockchain {
        async fn submit_nft_mint_tx(
            &self,
            call_data: Vec<u8>,
        ) -> Result<SubmitTxResponse, BlockchainError> {
            let tx_hash = hex::encode(blake2::Blake2s256::digest(&call_data));
            self.store
                .lock()
                .unwrap()
                .insert(tx_hash.clone(), call_data);
            Ok(SubmitTxResponse {
                tx_hash,
                block_height: 42,
            })
        }
    }

    struct MockEventBus;
    #[async_trait]
    impl EventPublisher for MockEventBus {
        async fn publish(&self, _topic: &str, _payload: Vec<u8>) -> Result<(), EventBusError> {
            Ok(())
        }
    }

    #[derive(Debug)]
    struct AlwaysAcceptSig;
    #[async_trait]
    impl SignatureStrategy for AlwaysAcceptSig {
        async fn verify(
            &self,
            _address: &str,
            _message: &[u8],
            _sig: &[u8],
        ) -> Result<(), MintingError> {
            Ok(())
        }
    }

    /* --------------------------- Test Cases ------------------------------- */

    #[tokio::test]
    async fn happy_path_mints() {
        let svc = MintingService::new(
            Arc::new(MockBlockchain {
                store: Mutex::new(HashMap::new()),
            }),
            Arc::new(MockEventBus),
            Arc::new(AlwaysAcceptSig),
        );

        let req = MintRequest {
            creator_address: "deadbeef".into(),
            metadata_uri: "ipfs://QmSomething".into(),
            layers: 3,
            timestamp: chrono::Utc::now().timestamp_millis(),
            nonce: Uuid::new_v4(),
            signature: vec![],
        };

        let receipt = svc.mint(req.clone()).await.unwrap();
        assert!(!receipt.tx_hash.is_empty());
        assert_eq!(receipt.block_height, 42);
    }

    #[tokio::test]
    async fn rejects_too_many_layers() {
        let svc = MintingService::new(
            Arc::new(MockBlockchain {
                store: Mutex::new(HashMap::new()),
            }),
            Arc::new(MockEventBus),
            Arc::new(AlwaysAcceptSig),
        );

        let req = MintRequest {
            creator_address: "deadbeef".into(),
            metadata_uri: "ipfs://QmSomething".into(),
            layers: MAX_LAYERS + 1,
            timestamp: chrono::Utc::now().timestamp_millis(),
            nonce: Uuid::new_v4(),
            signature: vec![],
        };

        let err = svc.mint(req).await.unwrap_err();
        matches!(err, MintingError::Validation(_));
    }
}
```