```rust
//! Index database layer for CanvasChain Symphony
//!
//! This module is responsible for maintaining **bidirectional indices**
//! that are frequently queried by the higher-level services.
//!
//! # Overview
//! * `owner → [nft_id]` :  Used by wallet / marketplace UIs to fetch all
//!   assets held by a particular address.
//! * `nft_id → owner` :  Used by consensus and governance layers to
//!   verify ownership during votes, staking, or royalty streaming.
//!
//! sled is used as the underlying embedded KV-store because it is
//! performant, crash-safe and does not require a daemon process.  Should
//! the project outgrow sled, the thin abstraction provided here makes it
//! straightforward to swap in RocksDB, FoundationDB, etc.

use std::path::Path;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use sled::{
    transaction::{ConflictableTransactionError, Transactional, TransactionalTree},
    IVec, Tree,
};
use thiserror::Error;
use uuid::Uuid;

/// Canonical representation of a wallet / account address.
///
/// We intentionally store the raw bytes so the code works with Ed25519,
/// BLS, or post-quantum public keys without recompilation.
pub type OwnerId = Vec<u8>;

/// Unique identifier for an NFT instrument.
pub type NftId = Uuid;

/// Internal prefix constants used for generating composite keys.
/// These are **NOT** user-facing and may change without notice.
const PREFIX_OWNER_TO_NFT: &str = "owner_to_nfts";
const PREFIX_NFT_TO_OWNER: &str = "nft_to_owner";

/// Thin wrapper around sled that offers higher-level, domain-specific
/// APIs required by the CanvasChain orchestration layer.  The struct is
/// cheap to clone since all fields are internally reference-counted.
#[derive(Clone)]
pub struct IndexDb {
    inner: Arc<sled::Db>,
    owner_to_nfts: Tree,
    nft_to_owner: Tree,
}

/// Serializable vector helper used to store `Vec<Uuid>` inside sled.
#[derive(Serialize, Deserialize, Debug, Clone)]
struct UuidVec(Vec<Uuid>);

/// Domain-specific error type returned by [`IndexDb`] operations.
#[derive(Error, Debug)]
pub enum IndexDbError {
    #[error("sled error: {0}")]
    Sled(#[from] sled::Error),

    #[error("serialization error: {0}")]
    Bincode(#[from] bincode::Error),

    #[error("transaction conflict")]
    TransactionConflict,
}

impl From<ConflictableTransactionError<IndexDbError>> for IndexDbError {
    fn from(e: ConflictableTransactionError<IndexDbError>) -> Self {
        match e {
            ConflictableTransactionError::Abort(inner) => inner,
            ConflictableTransactionError::Conflict => IndexDbError::TransactionConflict,
        }
    }
}

impl IndexDb {
    /// Opens (or creates) an index database at the given path.
    ///
    /// # Errors
    /// Returns [`IndexDbError::Sled`] if the underlying sled instance
    /// cannot be opened.
    pub fn open<P: AsRef<Path>>(path: P) -> Result<Self, IndexDbError> {
        let db = sled::open(path)?;

        let owner_to_nfts = db.open_tree(PREFIX_OWNER_TO_NFT)?;
        let nft_to_owner = db.open_tree(PREFIX_NFT_TO_OWNER)?;

        Ok(Self {
            inner: Arc::new(db),
            owner_to_nfts,
            nft_to_owner,
        })
    }

    /// Creates or updates the bidirectional index for a newly minted NFT.
    ///
    /// Both sides (`owner→nft` and `nft→owner`) are updated atomically in
    /// a single sled transaction to guarantee consistency.
    pub fn index_nft(&self, owner: &OwnerId, nft_id: &NftId) -> Result<(), IndexDbError> {
        (&self.owner_to_nfts, &self.nft_to_owner)
            .transaction(|(o2n, n2o)| {
                // Update owner → [nft_list]
                let mut nft_vec = Self::load_nft_vec(o2n, owner)?;
                if !nft_vec.contains(nft_id) {
                    nft_vec.push(*nft_id);
                }
                o2n.insert(owner, Self::serialize(&UuidVec(nft_vec.clone()))?)?;

                // Update nft → owner
                n2o.insert(nft_id.as_bytes(), owner)?;

                Ok(())
            })?;

        Ok(())
    }

    /// Removes an existing NFT from its owner indices (used for burns /
    /// transfers).  The caller is responsible for re-indexing the new
    /// owner after a transfer.
    pub fn deindex_nft(&self, owner: &OwnerId, nft_id: &NftId) -> Result<(), IndexDbError> {
        (&self.owner_to_nfts, &self.nft_to_owner)
            .transaction(|(o2n, n2o)| {
                // Update owner → [nft_list]
                let mut nft_vec = Self::load_nft_vec(o2n, owner)?;
                nft_vec.retain(|id| id != nft_id);
                o2n.insert(owner, Self::serialize(&UuidVec(nft_vec))?)?;

                // Remove nft → owner
                n2o.remove(nft_id.as_bytes())?;

                Ok(())
            })?;

        Ok(())
    }

    /// Returns **all** NFTs owned by the supplied account.
    ///
    /// This function is heavily queried by the wallet UI, so it is
    /// optimized for read-only performance.
    pub fn nfts_by_owner(&self, owner: &OwnerId) -> Result<Vec<NftId>, IndexDbError> {
        let bytes = match self.owner_to_nfts.get(owner)? {
            Some(v) => v,
            None => return Ok(Vec::new()),
        };

        let UuidVec(v) = Self::deserialize(&bytes)?;
        Ok(v)
    }

    /// Returns the current owner (address) for the given NFT, or `None`
    /// if the NFT has not been indexed or was burned.
    pub fn owner_of(&self, nft_id: &NftId) -> Result<Option<OwnerId>, IndexDbError> {
        let owner = self
            .nft_to_owner
            .get(nft_id.as_bytes())?
            .map(|ivec| ivec.to_vec());
        Ok(owner)
    }

    /// Returns the internal sled handle.  This is primarily useful for
    /// advanced queries (e.g. custom iterators) that are not yet exposed
    /// by the high-level API.
    pub fn raw_db(&self) -> Arc<sled::Db> {
        Arc::clone(&self.inner)
    }

    // ---------------------------------------------------------------- //
    // Helper methods
    // ---------------------------------------------------------------- //

    /// Loads and deserializes the NFT list for a given owner, falling
    /// back to an empty vector when the key does not exist.
    fn load_nft_vec(tree: &TransactionalTree, owner: &OwnerId) -> Result<Vec<Uuid>, IndexDbError> {
        Ok(match tree.get(owner)? {
            Some(bytes) => {
                let UuidVec(v) = Self::deserialize(&bytes)?;
                v
            }
            None => Vec::new(),
        })
    }

    #[inline]
    fn serialize<T: ?Sized + Serialize>(value: &T) -> Result<Vec<u8>, IndexDbError> {
        Ok(bincode::serialize(value)?)
    }

    #[inline]
    fn deserialize<T: for<'d> Deserialize<'d>>(bytes: &IVec) -> Result<T, IndexDbError> {
        Ok(bincode::deserialize(bytes)?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rand::Rng;
    use tempfile::TempDir;

    fn random_owner() -> OwnerId {
        (0..32).map(|_| rand::thread_rng().gen()).collect()
    }

    #[test]
    fn round_trip_indexing() {
        let tmp_dir = TempDir::new().expect("temp dir");
        let db = IndexDb::open(tmp_dir.path()).expect("open db");

        let owner = random_owner();
        let nft_a = Uuid::new_v4();
        let nft_b = Uuid::new_v4();

        // Index two NFTs
        db.index_nft(&owner, &nft_a).expect("index nft_a");
        db.index_nft(&owner, &nft_b).expect("index nft_b");

        let mut nfts = db.nfts_by_owner(&owner).expect("list nfts");
        nfts.sort_unstable();
        assert_eq!(nfts, vec![nft_a, nft_b].into_iter().sorted().collect::<Vec<_>>());

        // Owner lookup
        assert_eq!(db.owner_of(&nft_a).expect("owner"), Some(owner.clone()));

        // De-index one NFT
        db.deindex_nft(&owner, &nft_a).expect("deindex");

        let nfts_after = db.nfts_by_owner(&owner).expect("list after");
        assert_eq!(nfts_after, vec![nft_b]);
        assert_eq!(db.owner_of(&nft_a).expect("owner_of"), None);
    }
}
```