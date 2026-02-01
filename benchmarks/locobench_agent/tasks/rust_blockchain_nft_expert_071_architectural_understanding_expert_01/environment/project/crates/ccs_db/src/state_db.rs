```rust
//! Persistent world-state database abstraction for CanvasChain Symphony.
//!
//! The `StateDb` is the canonical source of truth for chain execution.  It
//! stores **accounts**, **contract byte-code** and **key–value storage** for
//! every smart contract.  Each block commit generates a deterministic *state
//! root* (a Blake3 Merkle accumulation of all key–value pairs) that can later
//! be proven against light-client requests or off-chain indexers.
//!
//! Elasticity requirements of the Symphony runtime dictate that the database
//! must support:
//!   * atomic multi-key updates (Write-Set)
//!   * cheap, read-only snapshots per block height
//!   * forward-only pruning (retain the last *N* roots and fast-prune the rest)
//!
//! This implementation relies on `sled` for embedded, high-performance storage
//! and an append-only **versioned column family** layout to avoid write
//! amplification while retaining historical states.

use std::{
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
};

use blake3::Hasher;
use parking_lot::RwLock;
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use sled::{
    transaction::{
        ConflictableTransactionError, TransactionError, TransactionResult, Transactional,
        TransactionalTree,
    },
    Db, IVec,
};
use thiserror::Error;
use tokio::sync::broadcast;

/// Logical identifier for an account or contract.
pub type Address = [u8; 32];

/// Hashed representation of the entire world state for a given block height.
pub type StateRoot = [u8; 32];

/// Ordering key prefix for versioned writes: `{height}/{raw_key}`.
///
/// We keep the numerical height in big-endian to preserve lexicographic order.
fn compose_versioned_key(height: u64, raw_key: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(8 + raw_key.len());
    out.extend_from_slice(&height.to_be_bytes());
    out.extend_from_slice(raw_key);
    out
}

/// Decode a versioned key returning `(height, raw_key)`.
fn split_versioned_key(versioned: &[u8]) -> (u64, &[u8]) {
    let (height_bytes, raw) = versioned.split_at(8);
    (
        u64::from_be_bytes(height_bytes.try_into().expect("8 bytes")),
        raw,
    )
}

/// High-level account record stored in the `StateDb`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AccountState {
    pub balance: u128,
    pub nonce: u64,
    /// Hash of contract bytecode (if any).
    pub code_hash: Option<[u8; 32]>,
    /// Merklized root of the contract storage tree.
    pub storage_root: [u8; 32],
}

impl Default for AccountState {
    fn default() -> Self {
        Self {
            balance: 0,
            nonce: 0,
            code_hash: None,
            storage_root: [0u8; 32],
        }
    }
}

/// Arbitrary write operation encoded in a block's *write-set*.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum WriteOp<V> {
    Put(Vec<u8>, V),
    Delete(Vec<u8>),
}

/// Aggregated writes performed by the execution engine for a single block.
pub type WriteSet<V> = Vec<WriteOp<V>>;

/// Notification emitted after every successful `commit_block`.
#[derive(Debug, Clone)]
pub struct StateCommitEvent {
    pub block_height: u64,
    pub new_state_root: StateRoot,
}

/// Custom errors bubbled up by the `StateDb`.
#[derive(Debug, Error)]
pub enum StateDbError {
    #[error("sled error: {0}")]
    Sled(#[from] sled::Error),

    #[error("serialization error: {0}")]
    Bincode(#[from] bincode::Error),

    #[error("conflicting write transaction")]
    Conflict,

    #[error("requested historical height ({requested}) is pruned – oldest available: {oldest}")]
    Pruned { requested: u64, oldest: u64 },
}

/// Primary database wrapper offering high-level typed APIs.
pub struct StateDb {
    db: Db,
    /// Tree for versioned state entries.
    tree: sled::Tree,
    /// Monotonically increasing block height.
    current_height: AtomicU64,
    /// Oldest height still retained (everything below is pruned).
    oldest_height: AtomicU64,
    /// Broadcast channel for commit notifications.
    event_tx: broadcast::Sender<StateCommitEvent>,
    /// Path on disk (used on `prune`).
    _path: PathBuf,
    /// Global rw-lock for snapshot safety.
    guard: Arc<RwLock<()>>,
}

impl StateDb {
    /// Open or create a new `StateDb` at `path`.
    pub fn open<P: AsRef<Path>>(path: P) -> Result<Self, StateDbError> {
        let db = sled::open(&path)?;
        let tree = db.open_tree("state")?;

        // Determine the current and oldest heights by scanning prefix keys.
        let (mut current_height, mut oldest_height) = (0u64, u64::MAX);
        for key in tree.iter().keys() {
            let k = key?;
            let (h, _) = split_versioned_key(&k);
            if h > current_height {
                current_height = h;
            }
            if h < oldest_height {
                oldest_height = h;
            }
        }
        if oldest_height == u64::MAX {
            oldest_height = 0;
        }

        let (event_tx, _) = broadcast::channel(64);
        Ok(Self {
            db,
            tree,
            current_height: AtomicU64::new(current_height),
            oldest_height: AtomicU64::new(oldest_height),
            event_tx,
            _path: path.as_ref().to_path_buf(),
            guard: Arc::new(RwLock::new(())),
        })
    }

    /// Subscribe to state-commit events.
    pub fn subscribe(&self) -> broadcast::Receiver<StateCommitEvent> {
        self.event_tx.subscribe()
    }

    /// Retrieve the value associated with `raw_key` *at the latest height*.
    pub fn get<V: DeserializeOwned>(&self, raw_key: &[u8]) -> Result<Option<V>, StateDbError> {
        let height = self.current_height.load(Ordering::SeqCst);
        self.get_at(height, raw_key)
    }

    /// Retrieve a historical value at `height`.
    pub fn get_at<V: DeserializeOwned>(
        &self,
        height: u64,
        raw_key: &[u8],
    ) -> Result<Option<V>, StateDbError> {
        let oldest = self.oldest_height.load(Ordering::SeqCst);
        if height < oldest {
            return Err(StateDbError::Pruned {
                requested: height,
                oldest,
            });
        }

        let _r = self.guard.read(); // protect against concurrent pruning
        let versioned_key = compose_versioned_key(height, raw_key);
        Ok(self
            .tree
            .get(versioned_key)?
            .map(|ivec| bincode::deserialize(&ivec))
            .transpose()?)
    }

    /// Store a single value at the *next* block height.
    ///
    /// This is mostly useful for tests; production execution typically uses
    /// `commit_block` that atomically writes a full `WriteSet`.
    pub fn put<V: Serialize>(&self, raw_key: &[u8], value: &V) -> Result<(), StateDbError> {
        self.commit_block::<V>(WriteSet::from([WriteOp::Put(
            raw_key.to_vec(),
            value.clone(),
        )]))
        .map(|_| ())
    }

    /// Atomically apply a `write_set`, advance `current_height` and
    /// deterministically compute the new `StateRoot`.
    pub fn commit_block<V: Serialize>(&self, write_set: WriteSet<V>) -> Result<StateRoot, StateDbError> {
        let new_height = self.current_height.load(Ordering::SeqCst) + 1;
        {
            // Acquire read-lock to forbid pruning during commit.
            let _r = self.guard.read();
            // --- transactional write ---
            let result: TransactionResult<(), StateDbError, _> =
                (&self.tree).transaction(|tx_tree| {
                    for op in &write_set {
                        match op {
                            WriteOp::Put(k, v) => {
                                let vk = compose_versioned_key(new_height, k);
                                let bytes = bincode::serialize(v)?;
                                tx_tree.insert(vk, bytes)
                                    .map_err(|e| ConflictableTransactionError::Abort(StateDbError::Sled(e)))?;
                            }
                            WriteOp::Delete(k) => {
                                let vk = compose_versioned_key(new_height, k);
                                tx_tree.remove(vk)
                                    .map_err(|e| ConflictableTransactionError::Abort(StateDbError::Sled(e)))?;
                            }
                        }
                    }
                    Ok(())
                });

            match result {
                Ok(_) => {}
                Err(TransactionError::Storage(e)) => return Err(StateDbError::Sled(e)),
                Err(TransactionError::Abort(e)) => return Err(e),
            }
        }

        // Sync to disk.
        self.db.flush()?;

        // Re-compute and persist new root.
        let new_root = self.compute_state_root(new_height)?;
        self.current_height.store(new_height, Ordering::SeqCst);

        // Notify subscribers – ignore send failures (no active listeners).
        let _ = self
            .event_tx
            .send(StateCommitEvent { block_height: new_height, new_state_root: new_root });

        Ok(new_root)
    }

    /// Deterministically compute the Blake3 root for a given `height`.
    ///
    /// The root is the hash of the concatenation of `hash(key) || hash(value)`
    /// in lexicographic key order.  While *not* a Patricia-Merkle tree, this
    /// approach provides collision resistance and is fast to compute.
    pub fn compute_state_root(&self, height: u64) -> Result<StateRoot, StateDbError> {
        let prefix = height.to_be_bytes();
        let mut hasher = Hasher::new();

        for kv in self.tree.scan_prefix(prefix) {
            let (k, v) = kv?;
            hasher.update(blake3::hash(&k).as_bytes());
            hasher.update(blake3::hash(&v).as_bytes());
        }
        Ok(*hasher.finalize().as_bytes())
    }

    /// Permanently remove historical states below `keep_from_height`.
    pub fn prune(&self, keep_from_height: u64) -> Result<(), StateDbError> {
        {
            // Exclusive lock to block reads while we delete keys.
            let _w = self.guard.write();
            let oldest = self.oldest_height.load(Ordering::SeqCst);
            if keep_from_height <= oldest {
                // Nothing to do.
                return Ok(());
            }

            // Delete per-key.
            for kv in self.tree.range(..compose_versioned_key(keep_from_height, b"")) {
                let (k, _) = kv?;
                self.tree.remove(k)?;
            }
            self.db.flush()?;
            self.oldest_height.store(keep_from_height, Ordering::SeqCst);
        }

        Ok(())
    }
}

// ---------- High-level helpers for specific Symphony domains ---------- //

impl StateDb {
    /// Convenience wrapper around `get` dedicated to `AccountState` lookups.
    pub fn get_account(&self, address: &Address) -> Result<Option<AccountState>, StateDbError> {
        self.get::<AccountState>(address)
    }

    /// Store an entire `AccountState` at the next block height.
    pub fn set_account(
        &self,
        address: &Address,
        account: &AccountState,
    ) -> Result<StateRoot, StateDbError> {
        self.commit_block::<AccountState>(WriteSet::from([WriteOp::Put(
            address.to_vec(),
            account.clone(),
        )]))
    }

    /// Retrieve arbitrary contract storage key for a given contract `address`.
    pub fn get_contract_storage<V: DeserializeOwned>(
        &self,
        address: &Address,
        storage_key: &[u8],
    ) -> Result<Option<V>, StateDbError> {
        let mut composite = Vec::from(address.as_slice());
        composite.extend_from_slice(storage_key);
        self.get::<V>(&composite)
    }

    /// Put a value under contract storage.
    pub fn set_contract_storage<V: Serialize>(
        &self,
        address: &Address,
        storage_key: &[u8],
        value: &V,
    ) -> Result<StateRoot, StateDbError> {
        let mut composite = Vec::from(address.as_slice());
        composite.extend_from_slice(storage_key);
        self.commit_block::<V>(WriteSet::from([WriteOp::Put(composite, value.clone())]))
    }
}

// ----------------------- Tests ----------------------- //

#[cfg(test)]
mod tests {
    use super::*;
    use rand::Rng;
    use tempfile::TempDir;

    fn random_address() -> Address {
        rand::thread_rng().gen()
    }

    #[test]
    fn basic_read_write_account() {
        let tmp = TempDir::new().expect("tmp dir");
        let db = StateDb::open(tmp.path()).unwrap();

        let addr = random_address();
        let mut acct = AccountState::default();
        acct.balance = 42;

        let root1 = db.set_account(&addr, &acct).unwrap();
        assert_eq!(db.get_account(&addr).unwrap(), Some(acct.clone()));

        acct.balance = 1337;
        let root2 = db.set_account(&addr, &acct).unwrap();
        assert_eq!(db.get_account(&addr).unwrap(), Some(acct));

        assert_ne!(root1, root2);
    }

    #[test]
    fn pruning_works() {
        let tmp = TempDir::new().unwrap();
        let db = StateDb::open(tmp.path()).unwrap();
        let addr = random_address();
        let acct = AccountState::default();

        // write 5 blocks
        for _ in 0..5 {
            db.set_account(&addr, &acct).unwrap();
        }

        // prune first 3
        db.prune(3).unwrap();

        // requesting block 2 should fail
        assert!(matches!(
            db.get_at::<AccountState>(2, &addr),
            Err(StateDbError::Pruned { .. })
        ));

        // latest works
        assert!(db.get_account(&addr).unwrap().is_some());
    }
}
```