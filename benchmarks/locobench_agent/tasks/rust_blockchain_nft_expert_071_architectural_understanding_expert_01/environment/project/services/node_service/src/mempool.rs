```rust
//! Transaction mempool for the CanvasChain Symphony node service.
//!
//! The mempool is responsible for:
//! 1. Receiving and validating inbound transactions.
//! 2. Storing transactions in memory until they are either included in a
//!    block, time-out, or are explicitly removed.
//! 3. Prioritising transactions by gas price/fee.
//! 4. Broadcasting newly accepted transactions over the local event bus.
//!
//! Concurrency
//! -----------
//! The mempool is `Send + Sync` and guarded by a [`parking_lot::RwLock`] so that
//! reads do not block each other while writes are exclusive.  Internally we use
//! a [`BinaryHeap`] to maintain a max-heap ordered by `gas_price` so that the
//! highest-paying transactions are popped first when building a block.
//!
//! Performance
//! -----------
//! ‑ Inserts are **O(log n)** due to the heap.
//! ‑ Look-ups/removals are amortised **O(1)** via a secondary `HashMap`.
//!
//! The heap can contain stale entries (transactions already removed from the
//! `HashMap`).  These are lazily discarded when they reach the top of the heap
//! which keeps the implementation simple without sacrificing asymptotic
//! complexity.
//!
//! # Features
//! * TTL eviction to avoid unbounded growth.
//! * Capacity guard to protect against DoS attacks.
//! * Pluggable event bus so that unit tests can inject a dummy bus.
//! * Instrumentation with the `tracing` crate.

use std::{
    cmp::Ordering,
    collections::{BinaryHeap, HashMap},
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use bytes::Bytes;
use ethers_core::types::{Address, H256};
use parking_lot::RwLock;
use sha2::{Digest, Sha256};
use thiserror::Error;
use tokio::time;

#[cfg(feature = "metrics")]
use prometheus::{IntCounter, IntGauge};

/// Event bus abstraction so the mempool does not depend on a concrete
/// messaging backend.
pub trait EventBus: Send + Sync + 'static {
    /// Publish a newly accepted transaction to the network-wide transaction
    /// topic/channel.
    fn publish_new_transaction(&self, tx: &Transaction);
}

/// A transaction as recognised by the mempool.
///
/// NOTE: The canonical transaction-format lives in the smart-contract runtime
/// crate; here we only need a subset of the fields for queueing.
#[derive(Debug, Clone)]
pub struct Transaction {
    pub hash: H256,
    pub from: Address,
    pub nonce: u64,
    pub gas_price: u64,
    pub gas_limit: u64,
    pub payload: Bytes,
    pub size: usize,
    pub timestamp: u64, // seconds since UNIX_EPOCH
    pub signature: Bytes,
}

impl Transaction {
    /// Creates a new transaction and computes its hash locally.
    /// In production the hash would come from the caller.
    pub fn new(
        from: Address,
        nonce: u64,
        gas_price: u64,
        gas_limit: u64,
        payload: Bytes,
        signature: Bytes,
    ) -> Self {
        let size = payload.len() + signature.len() + 32 /* misc overhead */;
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time went backwards")
            .as_secs();

        // Very naive hashing for demonstration.  A real implementation would
        // encode the tx according to the CanvasChain VM spec and sign it.
        let mut hasher = Sha256::new();
        hasher.update(&from.0);
        hasher.update(&nonce.to_be_bytes());
        hasher.update(&gas_price.to_be_bytes());
        hasher.update(&gas_limit.to_be_bytes());
        hasher.update(&payload);
        hasher.update(&signature);
        let hash = H256::from_slice(&hasher.finalize());

        Transaction {
            hash,
            from,
            nonce,
            gas_price,
            gas_limit,
            payload,
            size,
            timestamp,
            signature,
        }
    }
}

/// An entry stored in the priority heap.
#[derive(Clone)]
struct HeapEntry {
    priority: u64,
    timestamp: u64,
    tx_hash: H256,
}

impl Ord for HeapEntry {
    fn cmp(&self, other: &Self) -> Ordering {
        // Max-heap: higher priority first, then older transactions first.
        self.priority
            .cmp(&other.priority)
            .then_with(|| other.timestamp.cmp(&self.timestamp))
    }
}
impl PartialOrd for HeapEntry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
impl PartialEq for HeapEntry {
    fn eq(&self, other: &Self) -> bool {
        self.tx_hash == other.tx_hash
    }
}
impl Eq for HeapEntry {}

/// Configuration parameters for the mempool.
#[derive(Debug, Clone)]
pub struct MempoolConfig {
    /// Maximum number of transactions stored concurrently.
    pub capacity: usize,
    /// Time-to-live for a transaction.  Older transactions are evicted.
    pub tx_ttl: Duration,
    /// Maximum transaction size in bytes.
    pub max_tx_size: usize,
}

impl Default for MempoolConfig {
    fn default() -> Self {
        Self {
            capacity: 50_000,
            tx_ttl: Duration::from_secs(60 * 60), // 1h
            max_tx_size: 128 * 1024,              // 128 KiB
        }
    }
}

/// Runtime errors returned by the mempool.
#[derive(Debug, Error)]
pub enum MempoolError {
    #[error("mempool capacity reached")]
    CapacityFull,
    #[error("transaction already present")]
    AlreadyPresent,
    #[error("transaction size {0} exceeds maximum allowed")]
    Oversized(usize),
}

/// Thread-safe mempool implementation.
pub struct Mempool<B: EventBus> {
    cfg: MempoolConfig,
    /// Index by transaction hash for fast look-ups.
    txs: RwLock<HashMap<H256, Arc<Transaction>>>,
    /// Priority queue for pop-max.
    heap: RwLock<BinaryHeap<HeapEntry>>,
    /// Event bus handle for broadcasting accepted transactions.
    bus: Arc<B>,
    #[cfg(feature = "metrics")]
    gauge_tx_count: IntGauge,
    #[cfg(feature = "metrics")]
    counter_tx_ingress: IntCounter,
}

impl<B: EventBus> Mempool<B> {
    pub fn new(cfg: MempoolConfig, bus: Arc<B>) -> Self {
        #[cfg(feature = "metrics")]
        {
            let gauge_tx_count = IntGauge::new("mempool_tx_count", "Transactions in mempool")
                .expect("metrics registry");
            let counter_tx_ingress =
                IntCounter::new("mempool_tx_ingress_total", "Total accepted transactions")
                    .expect("metrics registry");
            prometheus::default_registry()
                .register(Box::new(gauge_tx_count.clone()))
                .ok();
            prometheus::default_registry()
                .register(Box::new(counter_tx_ingress.clone()))
                .ok();

            Self {
                cfg,
                txs: Default::default(),
                heap: Default::default(),
                bus,
                gauge_tx_count,
                counter_tx_ingress,
            }
        }

        #[cfg(not(feature = "metrics"))]
        Self {
            cfg,
            txs: Default::default(),
            heap: Default::default(),
            bus,
        }
    }

    /// Starts the TTL cleaner in the background.
    pub async fn start_ttl_evictor(self: Arc<Self>, interval: Duration) {
        let cfg = self.cfg.clone();
        tokio::spawn(async move {
            let mut ticker = time::interval(interval);
            loop {
                ticker.tick().await;
                let deadline = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .expect("clock error")
                    .as_secs();
                let evicted = self.evict_expired(deadline, cfg.tx_ttl);
                if evicted > 0 {
                    tracing::debug!(count = evicted, "Evicted expired transactions");
                }
            }
        });
    }

    /// Attempts to insert a transaction into the mempool.
    ///
    /// Errors if the pool is full, the transaction already exists, or violates
    /// basic static rules (size, gas limit, etc.).
    pub fn insert(&self, tx: Transaction) -> Result<(), MempoolError> {
        if tx.size > self.cfg.max_tx_size {
            return Err(MempoolError::Oversized(tx.size));
        }

        {
            let guard = self.txs.read();
            if guard.contains_key(&tx.hash) {
                return Err(MempoolError::AlreadyPresent);
            }
            if guard.len() >= self.cfg.capacity {
                return Err(MempoolError::CapacityFull);
            }
        }

        // Passed admissibility checks – acquire write lock.
        let mut map_guard = self.txs.write();
        let mut heap_guard = self.heap.write();

        // Re-check under the write lock to avoid race.
        if map_guard.contains_key(&tx.hash) {
            return Err(MempoolError::AlreadyPresent);
        }
        if map_guard.len() >= self.cfg.capacity {
            return Err(MempoolError::CapacityFull);
        }

        let tx_arc = Arc::new(tx.clone());

        map_guard.insert(tx.hash, tx_arc.clone());
        heap_guard.push(HeapEntry {
            priority: tx.gas_price,
            timestamp: tx.timestamp,
            tx_hash: tx.hash,
        });

        drop(heap_guard);
        drop(map_guard);

        #[cfg(feature = "metrics")]
        {
            self.gauge_tx_count.inc();
            self.counter_tx_ingress.inc();
        }

        self.bus.publish_new_transaction(&tx);

        tracing::trace!(hash = ?tx.hash, "Transaction inserted into mempool");
        Ok(())
    }

    /// Remove the transaction from the mempool (e.g. because it was included in
    /// a block).
    pub fn remove(&self, tx_hash: &H256) -> Option<Arc<Transaction>> {
        let removed = self.txs.write().remove(tx_hash);
        if removed.is_some() {
            #[cfg(feature = "metrics")]
            self.gauge_tx_count.dec();
        }
        removed
    }

    /// Returns `true` if a transaction with `hash` is present in the mempool.
    pub fn contains(&self, hash: &H256) -> bool {
        self.txs.read().contains_key(hash)
    }

    /// Number of transactions currently stored.
    pub fn len(&self) -> usize {
        self.txs.read().len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Pop transactions up to `max_count` while staying below `max_block_size`.
    ///
    /// Stale heap entries are skipped transparently.
    pub fn select_transactions(
        &self,
        max_count: usize,
        max_block_size: usize,
    ) -> Vec<Arc<Transaction>> {
        let mut selected = Vec::with_capacity(max_count);
        let mut heap_guard = self.heap.write();
        let mut map_guard = self.txs.write();

        let mut current_block_size = 0usize;

        while selected.len() < max_count {
            let Some(candidate) = heap_guard.pop() else { break };

            // Skip stale.
            let Some(tx) = map_guard.get(&candidate.tx_hash) else {
                continue;
            };

            if current_block_size + tx.size > max_block_size {
                // Stop if adding would exceed block size limit.
                break;
            }

            // Drain from the map so it can't be selected twice.
            let tx = map_guard
                .remove(&candidate.tx_hash)
                .expect("exists; we just looked it up");

            current_block_size += tx.size;
            selected.push(tx);

            #[cfg(feature = "metrics")]
            self.gauge_tx_count.dec();
        }

        selected
    }

    /// Iterate over all transactions (read-only).
    pub fn all_transactions(&self) -> Vec<Arc<Transaction>> {
        self.txs
            .read()
            .values()
            .cloned()
            .collect::<Vec<Arc<Transaction>>>()
    }

    /// Evicts expired transactions.  Returns the number removed.
    fn evict_expired(&self, now_secs: u64, ttl: Duration) -> usize {
        let mut removed = Vec::<H256>::new();
        {
            let guard = self.txs.read();
            for (hash, tx) in guard.iter() {
                if now_secs.saturating_sub(tx.timestamp) > ttl.as_secs() {
                    removed.push(*hash);
                }
            }
        }

        if removed.is_empty() {
            return 0;
        }

        let mut guard = self.txs.write();
        for hash in &removed {
            guard.remove(hash);
            #[cfg(feature = "metrics")]
            self.gauge_tx_count.dec();
        }

        removed.len()
    }
}

/* -------------------------------------------------------------------------- */
/*                                    Tests                                   */
/* -------------------------------------------------------------------------- */

#[cfg(test)]
mod tests {
    use super::*;
    use ethers_core::types::Address;
    use rand::{distributions::Alphanumeric, Rng};

    struct DummyBus;
    impl EventBus for DummyBus {
        fn publish_new_transaction(&self, _tx: &Transaction) {}
    }

    fn random_address() -> Address {
        let bytes: [u8; 20] = rand::random();
        Address::from(bytes)
    }

    fn random_payload(n: usize) -> Bytes {
        let s: String = rand::thread_rng()
            .sample_iter(&Alphanumeric)
            .take(n)
            .map(char::from)
            .collect();
        Bytes::from(s)
    }

    fn build_tx(gas_price: u64) -> Transaction {
        Transaction::new(
            random_address(),
            rand::random::<u64>(),
            gas_price,
            30_000,
            random_payload(128),
            Bytes::from_static(b"sig"),
        )
    }

    fn mempool() -> Mempool<DummyBus> {
        Mempool::new(MempoolConfig::default(), Arc::new(DummyBus))
    }

    #[test]
    fn insert_and_contains() {
        let mp = mempool();
        let tx = build_tx(10);
        assert!(mp.insert(tx.clone()).is_ok());
        assert!(mp.contains(&tx.hash));
    }

    #[test]
    fn reject_duplicates() {
        let mp = mempool();
        let tx = build_tx(10);
        assert!(mp.insert(tx.clone()).is_ok());
        assert_eq!(mp.insert(tx), Err(MempoolError::AlreadyPresent));
    }

    #[test]
    fn capacity_limit() {
        let mut cfg = MempoolConfig::default();
        cfg.capacity = 1;
        let mp = Mempool::new(cfg, Arc::new(DummyBus));

        let tx1 = build_tx(1);
        let tx2 = build_tx(2);
        assert!(mp.insert(tx1).is_ok());
        assert_eq!(mp.insert(tx2), Err(MempoolError::CapacityFull));
    }

    #[test]
    fn select_highest_gas_price_first() {
        let mp = mempool();
        let tx_low = build_tx(1);
        let tx_high = build_tx(1000);

        mp.insert(tx_low.clone()).unwrap();
        mp.insert(tx_high.clone()).unwrap();

        let selected = mp.select_transactions(2, usize::MAX);
        assert_eq!(selected[0].hash, tx_high.hash);
        assert_eq!(selected[1].hash, tx_low.hash);
    }

    #[test]
    fn evict_by_ttl() {
        let mut cfg = MempoolConfig::default();
        cfg.tx_ttl = Duration::from_secs(1);
        let mp = Mempool::new(cfg, Arc::new(DummyBus));

        let mut tx = build_tx(55);
        tx.timestamp -= 5; // Pretend it's old
        mp.insert(tx).unwrap();

        assert_eq!(mp.evict_expired(tx.timestamp + 5, Duration::from_secs(1)), 1);
        assert_eq!(mp.len(), 0);
    }
}
```