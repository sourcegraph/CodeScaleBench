```rust
//! Auction engine for the marketplace micro-service.
//!
//! Responsibilities
//! ----------------
//! 1. Create, store and track English auctions for multilayer NFTs.
//! 2. Enforce bidding rules (reserve price, minimum increment, anti-sniping).
//! 3. Periodically finalize ended auctions and emit events onto the service bus.
//!
//! The engine is designed for dependency-injection: any persistent storage that
//! implements `AuctionStore` can be plugged in.  Out of the box we provide an
//! in-memory implementation that is perfect for unit tests and local dev
//! environments.
//!
//! The module is *asynchronous* and uses Tokio for non-blocking execution.
//!
//! # Example
//! ```no_run
//! # use marketplace_service::auction_engine::*;
//! # #[tokio::main]
//! # async fn main() -> anyhow::Result<()> {
//! let engine = AuctionEngine::with_memory_store(Default::default());
//!
//! let auction_id = engine
//!     .create_auction(CreateAuction {
//!         nft_id: NftId::new(),
//!         seller_id: UserId::new(),
//!         reserve_price: 10_000,
//!         duration: chrono::Duration::hours(24),
//!     })
//!     .await?;
//!
//! engine
//!     .place_bid(auction_id, UserId::new(), 11_000)
//!     .await?;
//!
//! // spawn finalize loop
//! engine.clone().spawn_finalize_loop(tokio::time::Duration::from_secs(30));
//! # Ok(()) }
//! ```

use std::{
    collections::HashMap,
    fmt,
    sync::Arc,
    time::Duration as StdDuration,
};

use async_trait::async_trait;
use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokio::{
    sync::{broadcast, RwLock},
    task::JoinHandle,
};
use uuid::Uuid;

/* -------------------------------------------------------------------------- */
/*                                Type Aliases                                */
/* -------------------------------------------------------------------------- */

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub struct AuctionId(Uuid);

impl AuctionId {
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub struct UserId(Uuid);

impl UserId {
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub struct NftId(Uuid);

impl NftId {
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }
}

/* -------------------------------------------------------------------------- */
/*                                 DTOs / API                                 */
/* -------------------------------------------------------------------------- */

/// Immutable auction parameters used for construction.
#[derive(Debug)]
pub struct CreateAuction {
    pub nft_id: NftId,
    pub seller_id: UserId,
    /// Minimum price in the platform's smallest denomination (e.g. wei).
    pub reserve_price: u128,
    /// How long the auction should stay active.
    pub duration: Duration,
}

/// Public view of a bid.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Bid {
    pub bidder_id: UserId,
    pub amount: u128,
    pub timestamp: DateTime<Utc>,
}

/* -------------------------------------------------------------------------- */
/*                                  Domain                                    */
/* -------------------------------------------------------------------------- */

#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum AuctionStatus {
    Pending,
    Active,
    Finalized,
    Cancelled,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Auction {
    pub id: AuctionId,
    pub nft_id: NftId,
    pub seller_id: UserId,
    pub reserve_price: u128,
    pub start_time: DateTime<Utc>,
    pub end_time: DateTime<Utc>,
    pub status: AuctionStatus,
    pub highest_bid: Option<Bid>,
}

impl Auction {
    /// Returns whether the auction is open for bids.
    pub fn is_active(&self, now: DateTime<Utc>) -> bool {
        matches!(self.status, AuctionStatus::Active)
            && now >= self.start_time
            && now < self.end_time
    }

    /// Returns whether auction should be finalized (elapsed or cancelled).
    pub fn should_finalize(&self, now: DateTime<Utc>) -> bool {
        matches!(self.status, AuctionStatus::Active) && now >= self.end_time
    }
}

/* -------------------------------------------------------------------------- */
/*                                    Store                                   */
/* -------------------------------------------------------------------------- */

/// Storage abstraction. Can be backed by Postgres, Redis, RocksDB, etc.
#[async_trait]
pub trait AuctionStore: Send + Sync + 'static {
    async fn insert(&self, auction: Auction) -> Result<(), EngineError>;
    async fn update(&self, auction: &Auction) -> Result<(), EngineError>;
    async fn get(&self, id: AuctionId) -> Result<Option<Auction>, EngineError>;
    async fn all_due_for_finalize(
        &self,
        now: DateTime<Utc>,
    ) -> Result<Vec<AuctionId>, EngineError>;
}

/* --------------------------- In-memory implementation --------------------------- */

type AuctionMap = Arc<RwLock<HashMap<AuctionId, Auction>>>;

/// An in-memory, thread-safe store backed by a `HashMap`.
/// Meant for tests / local development, *not* production.
#[derive(Clone, Default)]
pub struct MemoryAuctionStore {
    map: AuctionMap,
}

#[async_trait]
impl AuctionStore for MemoryAuctionStore {
    async fn insert(&self, auction: Auction) -> Result<(), EngineError> {
        let mut map = self.map.write().await;
        map.insert(auction.id, auction);
        Ok(())
    }

    async fn update(&self, auction: &Auction) -> Result<(), EngineError> {
        let mut map = self.map.write().await;
        if let Some(a) = map.get_mut(&auction.id) {
            *a = auction.clone();
            Ok(())
        } else {
            Err(EngineError::AuctionNotFound)
        }
    }

    async fn get(&self, id: AuctionId) -> Result<Option<Auction>, EngineError> {
        let map = self.map.read().await;
        Ok(map.get(&id).cloned())
    }

    async fn all_due_for_finalize(
        &self,
        now: DateTime<Utc>,
    ) -> Result<Vec<AuctionId>, EngineError> {
        let map = self.map.read().await;
        Ok(map
            .values()
            .filter(|a| a.should_finalize(now))
            .map(|a| a.id)
            .collect())
    }
}

/* -------------------------------------------------------------------------- */
/*                               Event definitions                            */
/* -------------------------------------------------------------------------- */

#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum AuctionEvent {
    AuctionCreated(AuctionId),
    BidPlaced {
        auction_id: AuctionId,
        bidder_id: UserId,
        amount: u128,
    },
    AuctionFinalized {
        auction_id: AuctionId,
        winner: Option<UserId>,
        amount: Option<u128>,
    },
    AuctionCancelled(AuctionId),
}

/* -------------------------------------------------------------------------- */
/*                               Error handling                               */
/* -------------------------------------------------------------------------- */

#[derive(Debug, Error)]
pub enum EngineError {
    #[error("auction not found")]
    AuctionNotFound,
    #[error("auction is not active")]
    AuctionNotActive,
    #[error("bid below reserve price")]
    ReserveNotMet,
    #[error("bid increment too low")]
    IncrementTooLow,
    #[error("seller cannot bid on own auction")]
    SellerCannotBid,
    #[error("auction already finalized or cancelled")]
    InvalidAuctionState,
    #[error("storage error: {0}")]
    Storage(#[from] anyhow::Error),
    #[error("broadcast error")]
    Broadcast,
}

/* -------------------------------------------------------------------------- */
/*                                AuctionEngine                               */
/* -------------------------------------------------------------------------- */

#[derive(Clone)]
pub struct AuctionEngine<S: AuctionStore> {
    store: Arc<S>,
    /// Minimum bid increment (e.g. 1% of current highest) expressed as basis points.
    min_increment_bps: u16,
    /// Tokio broadcast channel for events.
    event_tx: broadcast::Sender<AuctionEvent>,
}

impl<S: AuctionStore> AuctionEngine<S> {
    /// Create an engine using the provided store.
    pub fn new(store: S, min_increment_bps: u16) -> Self {
        let (event_tx, _) = broadcast::channel(1024);
        Self {
            store: Arc::new(store),
            min_increment_bps,
            event_tx,
        }
    }

    /// Convenience helper for tests/local dev.
    pub fn with_memory_store(config: EngineConfig) -> Self {
        Self::new(MemoryAuctionStore::default(), config.min_increment_bps)
    }

    /// Subscribe to auction events (fire-and-forget).
    pub fn subscribe(&self) -> broadcast::Receiver<AuctionEvent> {
        self.event_tx.subscribe()
    }

    /* ----------------------------- API methods ----------------------------- */

    /// Creates an auction and stores it. Emits `AuctionCreated`.
    pub async fn create_auction(
        &self,
        params: CreateAuction,
    ) -> Result<AuctionId, EngineError> {
        let now = Utc::now();
        let auction = Auction {
            id: AuctionId::new(),
            nft_id: params.nft_id,
            seller_id: params.seller_id,
            reserve_price: params.reserve_price,
            start_time: now,
            end_time: now + params.duration,
            status: AuctionStatus::Active,
            highest_bid: None,
        };
        self.store.insert(auction.clone()).await?;
        self.emit(AuctionEvent::AuctionCreated(auction.id))?;
        Ok(auction.id)
    }

    /// Places a new bid on an active auction.
    pub async fn place_bid(
        &self,
        auction_id: AuctionId,
        bidder_id: UserId,
        amount: u128,
    ) -> Result<(), EngineError> {
        let now = Utc::now();
        let mut auction = match self.store.get(auction_id).await? {
            Some(a) => a,
            None => return Err(EngineError::AuctionNotFound),
        };

        if !auction.is_active(now) {
            return Err(EngineError::AuctionNotActive);
        }

        if bidder_id == auction.seller_id {
            return Err(EngineError::SellerCannotBid);
        }

        // First bid must be >= reserve.
        if auction.highest_bid.is_none() && amount < auction.reserve_price {
            return Err(EngineError::ReserveNotMet);
        }

        // Ensure minimum increment.
        if let Some(ref high) = auction.highest_bid {
            let min_required =
                high.amount + Self::calc_increment(high.amount, self.min_increment_bps);
            if amount < min_required {
                return Err(EngineError::IncrementTooLow);
            }
        }

        // TODO: anti-sniping extension window can be applied here.

        auction.highest_bid = Some(Bid {
            bidder_id,
            amount,
            timestamp: now,
        });

        self.store.update(&auction).await?;
        self.emit(AuctionEvent::BidPlaced {
            auction_id,
            bidder_id,
            amount,
        })?;
        Ok(())
    }

    /// Cancels an auction by its seller before any bids are placed.
    pub async fn cancel_auction(
        &self,
        auction_id: AuctionId,
        requester: UserId,
    ) -> Result<(), EngineError> {
        let mut auction = match self.store.get(auction_id).await? {
            Some(a) => a,
            None => return Err(EngineError::AuctionNotFound),
        };

        if auction.seller_id != requester {
            return Err(EngineError::InvalidAuctionState);
        }

        if auction.highest_bid.is_some() || !matches!(auction.status, AuctionStatus::Active) {
            return Err(EngineError::InvalidAuctionState);
        }

        auction.status = AuctionStatus::Cancelled;
        self.store.update(&auction).await?;
        self.emit(AuctionEvent::AuctionCancelled(auction_id))?;
        Ok(())
    }

    /// Finalize an auction that reached its end time. Returns the winner if any.
    pub async fn finalize_auction(
        &self,
        auction_id: AuctionId,
    ) -> Result<Option<(UserId, u128)>, EngineError> {
        let mut auction = match self.store.get(auction_id).await? {
            Some(a) => a,
            None => return Err(EngineError::AuctionNotFound),
        };

        if !auction.should_finalize(Utc::now()) {
            return Err(EngineError::InvalidAuctionState);
        }

        auction.status = AuctionStatus::Finalized;
        let winner_info = auction
            .highest_bid
            .as_ref()
            .map(|b| (b.bidder_id, b.amount));

        self.store.update(&auction).await?;
        self.emit(AuctionEvent::AuctionFinalized {
            auction_id,
            winner: winner_info.map(|t| t.0),
            amount: winner_info.map(|t| t.1),
        })?;

        // TODO: trigger settlement workflow (escrow smart contract, royalties, etc.)
        Ok(winner_info)
    }

    /* ------------------------------- Internals ------------------------------ */

    fn emit(&self, evt: AuctionEvent) -> Result<(), EngineError> {
        self.event_tx
            .send(evt)
            .map_err(|_| EngineError::Broadcast)
            .map(|_| ())
    }

    fn calc_increment(current: u128, bps: u16) -> u128 {
        // basis points: 1 bps = 0.01 %
        (current * bps as u128) / 10_000u128
    }

    /* ----------------------------- Finalize loop ---------------------------- */

    /// Spawns a Tokio task that periodically finalizes elapsed auctions.
    ///
    /// NOTE: In a clustered deployment only the leader instance should run the
    /// loop to avoid double-finalization.  This is achieved via distributed
    /// locks (e.g. etcd/consul) at the service orchestrator layer.
    pub fn spawn_finalize_loop(self, interval: StdDuration) -> JoinHandle<()> {
        tokio::spawn(async move {
            let mut ticker = tokio::time::interval(interval);
            loop {
                ticker.tick().await;
                let now = Utc::now();
                match self.store.all_due_for_finalize(now).await {
                    Ok(ids) => {
                        for id in ids {
                            // best effort, log errors
                            if let Err(e) = self.finalize_auction(id).await {
                                tracing::warn!(
                                    auction_id = ?id,
                                    error = ?e,
                                    "failed to finalize auction"
                                );
                            }
                        }
                    }
                    Err(e) => tracing::error!(error = ?e, "finalize loop failed to fetch auctions"),
                }
            }
        })
    }
}

/* -------------------------------------------------------------------------- */
/*                              Engine configuration                          */
/* -------------------------------------------------------------------------- */

#[derive(Debug, Clone)]
pub struct EngineConfig {
    pub min_increment_bps: u16,
}

impl Default for EngineConfig {
    fn default() -> Self {
        Self { min_increment_bps: 50 } // 0.5%
    }
}

/* -------------------------------------------------------------------------- */
/*                                   Display                                  */
/* -------------------------------------------------------------------------- */

impl fmt::Display for AuctionId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}
```