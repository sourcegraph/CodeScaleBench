```rust
// services/api_gateway/src/observer/subject.rs

//! Subject/Observer implementation used by the API-gateway service.
//!
//! The API-gateway listens to the global event-bus (NATS, Kafka, etc.) and
//! translates raw blockchain events into strongly-typed `SubjectEvent`s.  
//! These events are fanned-out to in-process observers such as:
//!   • HTTP/WebSocket notifiers  
//!   • Prometheus metrics collectors  
//!   • Realtime dashboards  
//!   • Audit / compliance append-only stores  
//!
//! The design follows the classical Observer pattern but is adapted for a
//! multi-threaded, asynchronous Rust environment by using `async_trait` and
//! interior-mutable, reference-counted containers (`Arc<RwLock<..>>`).
//!
//! External crates used:
//!   • `async_trait`   – enables async functions in traits
//!   • `parking_lot`   – faster, lightweight RwLock
//!   • `thiserror`     – concise custom error implementation
//!   • `uuid`          – unique IDs for observer handles

use async_trait::async_trait;
use parking_lot::RwLock;
use std::{
    collections::HashMap,
    sync::{Arc, Weak},
};
use thiserror::Error;
use tokio::task;
use uuid::Uuid;

/// High-level events emitted by the CanvasChain Symphony that are relevant
/// to the API-gateway layer.  
/// NOTE: Variants are intentionally kept generic; specialized data can be
///       encoded inside the `serde_json::Value` blob for forward-compatibility.
#[derive(Debug, Clone)]
pub enum SubjectEvent {
    NewBlock {
        height: u64,
        hash: String,
        timestamp: u64,
    },
    NftMinted {
        token_id: String,
        creator: String,
        metadata_uri: String,
    },
    OwnershipTransferred {
        token_id: String,
        from: String,
        to: String,
    },
    GovernanceProposal {
        proposal_id: u32,
        title: String,
    },
    ComposerElected {
        epoch: u64,
        node_id: String,
    },
    /// Catch-all for un-modelled or experimental events.
    Custom(serde_json::Value),
}

/// Trait that every observer (subscriber) must implement.
///
/// Implementors **must** be `Send + Sync` because notifications are
/// dispatched from a multi-threaded async runtime.
#[async_trait]
pub trait Observer: Send + Sync {
    /// Called whenever the `Subject` publishes a new `event`.
    ///
    /// Implementations should return quickly; heavy work should be delegated
    /// to background tasks to avoid blocking the notifier.
    async fn on_event(&self, event: &SubjectEvent);
}

/// Describes problems that may occur while manipulating observers.
#[derive(Debug, Error)]
pub enum SubjectError {
    #[error("observer `{0}` not found")]
    ObserverNotFound(Uuid),
    #[error("internal subject error: {0}")]
    Internal(String),
}

/// RAII handle returned by `Subject::subscribe`.  
/// When the handle is dropped, the observer is automatically un-registered.
pub struct Subscription {
    id: Uuid,
    /// Weak reference so that the `Subscription` does not keep the whole
    /// `Subject` alive when the `Subject` itself is supposed to shut down.
    subject: Weak<Inner>,
}

impl Drop for Subscription {
    fn drop(&mut self) {
        if let Some(subject) = self.subject.upgrade() {
            // Best-effort un-subscribe; errors are silently ignored because
            // dropping should never panic.
            let _ = subject.remove_observer(&self.id);
        }
    }
}

struct Inner {
    observers: RwLock<HashMap<Uuid, Arc<dyn Observer>>>,
}

impl Inner {
    fn add_observer(&self, id: Uuid, observer: Arc<dyn Observer>) {
        self.observers.write().insert(id, observer);
    }

    fn remove_observer(&self, id: &Uuid) -> Result<(), SubjectError> {
        let mut guard = self.observers.write();
        guard
            .remove(id)
            .map(|_| ())
            .ok_or_else(|| SubjectError::ObserverNotFound(*id))
    }

    fn snapshot(&self) -> Vec<(Uuid, Arc<dyn Observer>)> {
        // Clone the `Arc`s so we can release the lock before awaiting.
        self.observers
            .read()
            .iter()
            .map(|(id, obs)| (*id, Arc::clone(obs)))
            .collect()
    }
}

/// Concrete `Subject` that observers can subscribe to.
#[derive(Clone)]
pub struct Subject {
    inner: Arc<Inner>,
}

impl Subject {
    /// Create a fresh `Subject` with zero observers.
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Inner {
                observers: RwLock::new(HashMap::new()),
            }),
        }
    }

    /// Register an `observer` and get back a `Subscription` token.
    ///
    /// When the caller drops the token, the observer will be removed.
    pub fn subscribe<O>(&self, observer: O) -> Subscription
    where
        O: Observer + 'static,
    {
        let id = Uuid::new_v4();
        self.inner.add_observer(id, Arc::new(observer));

        Subscription {
            id,
            subject: Arc::downgrade(&self.inner),
        }
    }

    /// Manually remove an observer. Useful if the caller lost its
    /// `Subscription` token or wants to perform explicit clean-up.
    pub fn unsubscribe(&self, id: Uuid) -> Result<(), SubjectError> {
        self.inner.remove_observer(&id)
    }

    /// Notify **all** observers about an `event`.
    ///
    /// The notifications are dispatched asynchronously on the Tokio runtime;
    /// failures in individual observers are logged but do **not** abort the
    /// entire notification cycle.
    pub fn notify(&self, event: SubjectEvent) {
        let observers = self.inner.snapshot();

        // Spawn tasks for each observer to run concurrently.
        for (_id, observer) in observers {
            let ev_clone = event.clone();
            task::spawn(async move {
                if let Err(e) = Self::safe_notify(observer, ev_clone).await {
                    // TODO: replace with structured logging framework
                    eprintln!("observer error: {e}");
                }
            });
        }
    }

    /// Wrapper that catches panics and converts them into `SubjectError`s.
    async fn safe_notify(
        observer: Arc<dyn Observer>,
        event: SubjectEvent,
    ) -> Result<(), SubjectError> {
        // Any panic inside `observer.on_event` should not unwind across `await`
        // boundaries; catch_unwind converts it to a recoverable error.
        let res = std::panic::AssertUnwindSafe(observer.on_event(&event))
            .catch_unwind()
            .await;

        match res {
            Ok(_) => Ok(()),
            Err(panic) => {
                let msg = if let Some(&str_msg) = panic.downcast_ref::<&'static str>() {
                    str_msg.to_string()
                } else if let Some<String> str_buf = panic.downcast_ref::<String>() {
                    str_buf.clone()
                } else {
                    "unknown panic".into()
                };

                Err(SubjectError::Internal(msg))
            }
        }
    }

    /// Returns the number of currently registered observers (for testing /
    /// metrics). This is a cheap, lock-free read.
    pub fn observer_count(&self) -> usize {
        self.inner.observers.read().len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    struct TestObserver {
        calls: Arc<AtomicUsize>,
    }

    #[async_trait]
    impl Observer for TestObserver {
        async fn on_event(&self, _event: &SubjectEvent) {
            self.calls.fetch_add(1, Ordering::SeqCst);
        }
    }

    #[tokio::test]
    async fn it_notifies_all_observers() {
        let subject = Subject::new();
        let counter = Arc::new(AtomicUsize::new(0));

        for _ in 0..5 {
            let obs = TestObserver {
                calls: Arc::clone(&counter),
            };
            subject.subscribe(obs);
        }

        subject.notify(SubjectEvent::Custom(serde_json::json!({ "k": "v" })));

        // Wait for tasks to complete
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;

        assert_eq!(counter.load(Ordering::SeqCst), 5);
    }

    #[tokio::test]
    async fn unsubscribe_works() {
        let subject = Subject::new();
        let counter = Arc::new(AtomicUsize::new(0));

        let subscription = subject.subscribe(TestObserver {
            calls: Arc::clone(&counter),
        });

        // Drop the subscription immediately to un-subscribe
        drop(subscription);

        subject.notify(SubjectEvent::Custom(serde_json::json!({})));
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;

        assert_eq!(counter.load(Ordering::SeqCst), 0);
    }
}
```