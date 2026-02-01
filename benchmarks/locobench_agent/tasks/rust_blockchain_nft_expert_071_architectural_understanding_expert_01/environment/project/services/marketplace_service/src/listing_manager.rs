```rust
//! Marketplace ‑ Listing Manager
//!
//! This module is responsible for orchestrating the full life-cycle of NFT
//! listings in the CanvasChain Symphony marketplace micro-service.  
//! It follows Repository + Event Driven patterns to keep storage concerns and
//! side-effects clearly separated from business logic.
//!
//! Responsibilities
//! * Create / update / cancel fixed-price listings
//! * Atomically settle purchases (reserve → transfer → close)
//! * Publish `MarketplaceEvent`s on the internal event bus
//! * Provide a type-safe façade for gRPC handlers & GraphQL resolvers
//!
//! Note: In production, `ListingRepository` would be backed by Postgres or
//! RocksDB; here we ship an in-memory implementation for completeness.

#![allow(clippy::large_enum_variant)]

use std::{
    collections::HashMap,
    sync::Arc,
    time::Duration,
};

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use rust_decimal::Decimal;
use tokio::{
    sync::{broadcast, RwLock},
    time::timeout,
};
use tracing::{debug, error, info, instrument};
use uuid::Uuid;

// region: ───── Domain Types ──────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ListingId(Uuid);

impl ListingId {
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AccountId(Uuid);

impl AccountId {
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum ListingStatus {
    Active,
    Reserved { buyer: AccountId, reserved_at: DateTime<Utc> },
    Sold,
    Cancelled,
}

#[derive(Debug, Clone)]
pub struct Listing {
    pub id: ListingId,
    pub owner: AccountId,
    pub nft_contract: String,
    pub token_id: String,
    pub price: Decimal,
    pub status: ListingStatus,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

// endregion: ──────────────────────────────────────────────────────────────────

// region: ───── Errors ────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum ListingError {
    #[error("Listing not found")]
    NotFound,
    #[error("Listing is not active")]
    NotActive,
    #[error("Reserved listing. Only buyer {0:?} can proceed")]
    Reserved(AccountId),
    #[error("Listing already sold")]
    AlreadySold,
    #[error("Listing already cancelled")]
    AlreadyCancelled,
    #[error("Repository error: {0}")]
    Repository(String),
    #[error("Event dispatch failed: {0}")]
    EventDispatch(String),
    #[error("Operation timed-out")]
    Timeout,
}

// endregion: ──────────────────────────────────────────────────────────────────

// region: ───── Repository Trait ──────────────────────────────────────────────

#[async_trait]
pub trait ListingRepository: Send + Sync + 'static {
    async fn insert(&self, listing: Listing) -> Result<(), ListingError>;
    async fn get(&self, id: ListingId) -> Result<Listing, ListingError>;
    async fn update(&self, listing: Listing) -> Result<(), ListingError>;
    async fn list_active(&self) -> Result<Vec<Listing>, ListingError>;
}

// endregion: ──────────────────────────────────────────────────────────────────

// region: ───── In-Memory Repository (example impl) ───────────────────────────

/// Simple, thread-safe in-memory repository.  
/// In production this would be swapped for a SQL or KV store implementation.
pub struct InMemoryListingRepository {
    /// Internal map guarded by a read-write lock
    listings: RwLock<HashMap<ListingId, Listing>>,
}

impl InMemoryListingRepository {
    pub fn new() -> Self {
        Self {
            listings: RwLock::new(HashMap::new()),
        }
    }
}

#[async_trait]
impl ListingRepository for InMemoryListingRepository {
    #[instrument(skip(self, listing))]
    async fn insert(&self, listing: Listing) -> Result<(), ListingError> {
        let mut map = self.listings.write().await;
        map.insert(listing.id, listing);
        Ok(())
    }

    #[instrument(skip(self))]
    async fn get(&self, id: ListingId) -> Result<Listing, ListingError> {
        let map = self.listings.read().await;
        map.get(&id).cloned().ok_or(ListingError::NotFound)
    }

    #[instrument(skip(self, listing))]
    async fn update(&self, listing: Listing) -> Result<(), ListingError> {
        let mut map = self.listings.write().await;
        map.insert(listing.id, listing);
        Ok(())
    }

    #[instrument(skip(self))]
    async fn list_active(&self) -> Result<Vec<Listing>, ListingError> {
        let map = self.listings.read().await;
        Ok(map
            .values()
            .filter(|l| matches!(l.status, ListingStatus::Active))
            .cloned()
            .collect())
    }
}

// endregion: ──────────────────────────────────────────────────────────────────

// region: ───── Event Bus Types ───────────────────────────────────────────────

#[derive(Debug, Clone)]
pub enum MarketplaceEvent {
    ListingCreated(Listing),
    ListingReserved {
        listing_id: ListingId,
        buyer: AccountId,
    },
    ListingPurchased {
        listing_id: ListingId,
        buyer: AccountId,
    },
    ListingCancelled(ListingId),
}

// endregion: ──────────────────────────────────────────────────────────────────

// region: ───── Listing Manager Facade ────────────────────────────────────────

#[derive(Clone)]
pub struct ListingManager<R: ListingRepository> {
    repo: Arc<R>,
    events: broadcast::Sender<MarketplaceEvent>,
}

/// Upper bound for potentially blocking database operations.
const DB_OP_TIMEOUT: Duration = Duration::from_secs(3);

impl<R: ListingRepository> ListingManager<R> {
    pub fn new(repo: Arc<R>) -> Self {
        let (tx, _) = broadcast::channel(256);
        Self { repo, events: tx }
    }

    /// Subscribe to marketplace events.
    pub fn subscribe(&self) -> broadcast::Receiver<MarketplaceEvent> {
        self.events.subscribe()
    }

    #[instrument(skip(self))]
    pub async fn create_listing(
        &self,
        owner: AccountId,
        nft_contract: String,
        token_id: String,
        price: Decimal,
    ) -> Result<ListingId, ListingError> {
        let listing = Listing {
            id: ListingId::new(),
            owner,
            nft_contract,
            token_id,
            price,
            status: ListingStatus::Active,
            created_at: Utc::now(),
            updated_at: Utc::now(),
        };

        timeout(DB_OP_TIMEOUT, self.repo.insert(listing.clone()))
            .await
            .map_err(|_| ListingError::Timeout)?
            ?;

        self.dispatch_event(MarketplaceEvent::ListingCreated(listing))?;

        Ok(listing.id)
    }

    #[instrument(skip(self))]
    pub async fn reserve_listing(
        &self,
        listing_id: ListingId,
        buyer: AccountId,
    ) -> Result<(), ListingError> {
        let mut listing = timeout(DB_OP_TIMEOUT, self.repo.get(listing_id))
            .await
            .map_err(|_| ListingError::Timeout)??
            ;

        match listing.status {
            ListingStatus::Active => {
                listing.status = ListingStatus::Reserved {
                    buyer,
                    reserved_at: Utc::now(),
                };
                listing.updated_at = Utc::now();
            }
            ListingStatus::Reserved { buyer: original, .. } if original == buyer => {
                // Idempotent
                return Ok(());
            }
            ListingStatus::Reserved { buyer: other, .. } => {
                return Err(ListingError::Reserved(other));
            }
            ListingStatus::Sold => return Err(ListingError::AlreadySold),
            ListingStatus::Cancelled => return Err(ListingError::AlreadyCancelled),
        }

        timeout(DB_OP_TIMEOUT, self.repo.update(listing.clone()))
            .await
            .map_err(|_| ListingError::Timeout)??
            ;

        self.dispatch_event(MarketplaceEvent::ListingReserved { listing_id, buyer })?;
        Ok(())
    }

    #[instrument(skip(self))]
    pub async fn cancel_listing(&self, listing_id: ListingId, caller: AccountId) -> Result<(), ListingError> {
        let mut listing = timeout(DB_OP_TIMEOUT, self.repo.get(listing_id))
            .await
            .map_err(|_| ListingError::Timeout)??
            ;

        if listing.owner != caller {
            return Err(ListingError::Repository("Only owner can cancel".into()));
        }

        match listing.status {
            ListingStatus::Sold => return Err(ListingError::AlreadySold),
            ListingStatus::Cancelled => return Err(ListingError::AlreadyCancelled),
            _ => {}
        }

        listing.status = ListingStatus::Cancelled;
        listing.updated_at = Utc::now();

        timeout(DB_OP_TIMEOUT, self.repo.update(listing.clone()))
            .await
            .map_err(|_| ListingError::Timeout)??
            ;

        self.dispatch_event(MarketplaceEvent::ListingCancelled(listing_id))?;
        Ok(())
    }

    #[instrument(skip(self))]
    pub async fn purchase_listing(
        &self,
        listing_id: ListingId,
        buyer: AccountId,
    ) -> Result<(), ListingError> {
        let mut listing = timeout(DB_OP_TIMEOUT, self.repo.get(listing_id))
            .await
            .map_err(|_| ListingError::Timeout)??
            ;

        // Pre-flight state validation
        match &listing.status {
            ListingStatus::Active => {
                // We allow direct purchase without reservation
            }
            ListingStatus::Reserved { buyer: reserved_buyer, .. } if *reserved_buyer == buyer => {}
            ListingStatus::Reserved { buyer: reserved_buyer, .. } => {
                return Err(ListingError::Reserved(*reserved_buyer));
            }
            ListingStatus::Sold => return Err(ListingError::AlreadySold),
            ListingStatus::Cancelled => return Err(ListingError::AlreadyCancelled),
        }

        // TODO: integrate with payment processor / smart contract to transfer funds & NFT

        // When settlement succeeds:
        listing.status = ListingStatus::Sold;
        listing.updated_at = Utc::now();

        timeout(DB_OP_TIMEOUT, self.repo.update(listing.clone()))
            .await
            .map_err(|_| ListingError::Timeout)??
            ;

        self.dispatch_event(MarketplaceEvent::ListingPurchased { listing_id, buyer })?;
        Ok(())
    }

    #[instrument(skip(self))]
    pub async fn get_listing(&self, listing_id: ListingId) -> Result<Listing, ListingError> {
        timeout(DB_OP_TIMEOUT, self.repo.get(listing_id))
            .await
            .map_err(|_| ListingError::Timeout)?
    }

    #[instrument(skip(self))]
    pub async fn list_active(&self) -> Result<Vec<Listing>, ListingError> {
        timeout(DB_OP_TIMEOUT, self.repo.list_active())
            .await
            .map_err(|_| ListingError::Timeout)?
    }

    fn dispatch_event(&self, evt: MarketplaceEvent) -> Result<(), ListingError> {
        self.events
            .send(evt)
            .map(|_| ())
            .map_err(|e| ListingError::EventDispatch(e.to_string()))
    }
}

// endregion: ──────────────────────────────────────────────────────────────────

// region: ───── Tests ─────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use rust_decimal_macros::dec;

    fn setup_manager() -> ListingManager<InMemoryListingRepository> {
        ListingManager::new(Arc::new(InMemoryListingRepository::new()))
    }

    #[tokio::test]
    async fn lifecycle_ok() {
        let manager = setup_manager();
        let owner = AccountId::new();
        let buyer = AccountId::new();

        let listing_id = manager
            .create_listing(
                owner,
                "0xArtNFT".into(),
                "123".into(),
                dec!(1.25),
            )
            .await
            .unwrap();

        manager.reserve_listing(listing_id, buyer).await.unwrap();
        manager.purchase_listing(listing_id, buyer).await.unwrap();

        let listing = manager.get_listing(listing_id).await.unwrap();
        assert!(matches!(listing.status, ListingStatus::Sold));
    }

    #[tokio::test]
    async fn cancel_flow_ok() {
        let manager = setup_manager();
        let owner = AccountId::new();

        let listing_id = manager
            .create_listing(
                owner,
                "0xArtNFT".into(),
                "Token42".into(),
                dec!(0.75),
            )
            .await
            .unwrap();

        manager.cancel_listing(listing_id, owner).await.unwrap();
        let listing = manager.get_listing(listing_id).await.unwrap();
        assert!(matches!(listing.status, ListingStatus::Cancelled));
    }
}

// endregion: ──────────────────────────────────────────────────────────────────
```