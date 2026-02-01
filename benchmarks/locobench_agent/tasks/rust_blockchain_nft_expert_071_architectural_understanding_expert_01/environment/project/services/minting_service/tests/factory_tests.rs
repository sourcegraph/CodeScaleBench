```rust
//! Factory–pattern integration tests for the Minting micro-service.
//!
//! These tests exercise the `InstrumentFactory`―the component responsible for
//! turning an on-chain template into a fully-fledged multilayer NFT
//! “instrument”.  In production the factory interacts with a persistent
//! template registry, emits domain events on a service-wide event bus and
//! records the new instrument in the metadata store.  
//!
//! In the test-suite we wire the factory up against in-memory doubles of those
//! collaborators so that we can deterministically validate its behaviour
//! (error handling, event emission, concurrency safety, …) without depending on
//! external infrastructure such as Postgres, Kafka or a live validator set.

#![cfg(test)]

use std::{
    collections::HashSet,
    sync::Arc,
    time::Duration,
};

use futures::{future::join_all, StreamExt};
use once_cell::sync::Lazy;
use tokio::{
    sync::{broadcast, RwLock},
    time,
};
use tracing::{debug, info};

use minting_service::{
    errors::FactoryError,
    event::{EventBus, MintEvent},
    factory::{InstrumentFactory, SpawnRequest},
    registry::{TemplateDescriptor, TemplateId, TemplateRegistry},
};

// -------------------------------------------------------------------------------------------------
// ── Log initialisation ────────────────────────────────────────────────────────────────────────────
// -------------------------------------------------------------------------------------------------

// Install a test logger *once* for the whole test-binary.  `serial_test` is not
// needed because `Lazy` guarantees single initialisation even with concurrent
// test execution.
static LOG_HANDLE: Lazy<()> = Lazy::new(|| {
    let _ = tracing_subscriber::fmt()
        .with_env_filter("debug")
        .with_test_writer()
        .try_init();
});

// -------------------------------------------------------------------------------------------------
// ── In-memory test doubles ────────────────────────────────────────────────────────────────────────
// -------------------------------------------------------------------------------------------------

/// Tiny in-memory implementation of [`TemplateRegistry`] suitable for unit &
/// integration tests.
#[derive(Debug, Default)]
struct InMemoryRegistry {
    inner: RwLock<Vec<TemplateDescriptor>>,
}

#[async_trait::async_trait]
impl TemplateRegistry for InMemoryRegistry {
    async fn register(&self, descriptor: TemplateDescriptor) -> TemplateId {
        let mut guard = self.inner.write().await;
        guard.push(descriptor.clone());
        descriptor.id()
    }

    async fn find(&self, id: TemplateId) -> Option<TemplateDescriptor> {
        let guard = self.inner.read().await;
        guard.iter().find(|d| d.id() == id).cloned()
    }
}

/// Broadcast-based [`EventBus`] mock that allows multiple consumers to observe
/// emitted domain events.
#[derive(Debug)]
struct TestEventBus {
    tx: broadcast::Sender<MintEvent>,
}

impl TestEventBus {
    fn new(buffer: usize) -> Self {
        let (tx, _) = broadcast::channel(buffer);
        Self { tx }
    }
}

#[async_trait::async_trait]
impl EventBus for TestEventBus {
    async fn publish(&self, evt: MintEvent) {
        // A test bus *must* never block: ignore slow
        // receivers but log the back-pressure.
        if self.tx.send(evt).is_err() {
            debug!("no active event listeners – dropping event");
        }
    }

    fn subscribe(&self) -> broadcast::Receiver<MintEvent> {
        self.tx.subscribe()
    }
}

// -------------------------------------------------------------------------------------------------
// ── Test harness helpers ──────────────────────────────────────────────────────────────────────────
// -------------------------------------------------------------------------------------------------

/// Convenience wrapper that wires up a production `InstrumentFactory` against
/// in-memory registries/buses so each test gets an isolated environment.
async fn bootstrap_factory() -> (
    InstrumentFactory,
    Arc<InMemoryRegistry>,
    broadcast::Receiver<MintEvent>,
) {
    Lazy::force(&LOG_HANDLE);

    let registry = Arc::new(InMemoryRegistry::default());
    let event_bus = Arc::new(TestEventBus::new(16));

    // The factory constructor used in production.  If the real implementation
    // changes the signature, only this helper needs to be touched.
    let factory = InstrumentFactory::new(
        registry.clone(),
        event_bus.clone(),
        /* additional config = */ Default::default(),
    );

    (factory, registry, event_bus.subscribe())
}

/// Helper that registers a minimalistic template and returns its id.
async fn register_test_template(
    registry: &Arc<InMemoryRegistry>,
    name: &str,
) -> TemplateId {
    let descriptor = TemplateDescriptor::builder()
        .name(name)
        .author("factory-tests")
        .bytecode(Vec::from(name.as_bytes()))
        .build()
        .expect("template descriptor");

    registry.register(descriptor).await
}

// -------------------------------------------------------------------------------------------------
// ── Test-cases ────────────────────────────────────────────────────────────────────────────────────
// -------------------------------------------------------------------------------------------------

#[tokio::test]
async fn spawn_single_instrument_should_emit_event() {
    let (factory, registry, mut events) = bootstrap_factory().await;
    let tpl_id = register_test_template(&registry, "sine-oscillator").await;

    let handle = factory
        .spawn_instrument(
            SpawnRequest::builder()
                .template_id(tpl_id)
                .owner("tz1-artist-wallet".into())
                .salt(42)
                .build()
                .unwrap(),
        )
        .await
        .expect("spawn succeeds");

    assert_eq!(handle.template, tpl_id);
    assert_eq!(handle.owner, "tz1-artist-wallet");
    assert!(handle.address.starts_with("cc"));

    // The factory should have emitted a *single* `InstrumentMinted` event.
    let evt = time::timeout(Duration::from_millis(50), events.recv())
        .await
        .expect("event present")
        .expect("channel open");

    match evt {
        MintEvent::InstrumentMinted { ref address, template, .. } => {
            assert_eq!(template, tpl_id);
            assert_eq!(address, &handle.address);
        }
        other => panic!("unexpected event {other:?}"),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn concurrent_spawns_produce_unique_addresses() {
    const INSTANCES: usize = 64;

    let (factory, registry, _events) = bootstrap_factory().await;
    let tpl_id = register_test_template(&registry, "choir-pad").await;

    // Spawn a fleet of `INSTRUMENTS` concurrent mint requests.
    let futs = (0..INSTANCES).map(|salt| {
        let factory = factory.clone();
        async move {
            factory
                .spawn_instrument(
                    SpawnRequest::builder()
                        .template_id(tpl_id)
                        .owner(format!("user-{salt}"))
                        .salt(salt as u64)
                        .build()
                        .unwrap(),
                )
                .await
                .map(|h| h.address)
        }
    });

    let results = join_all(futs).await;

    // Validate *all* spawns succeeded and addresses are unique.
    let mut uniq = HashSet::with_capacity(INSTANCES);
    for res in results {
        let addr = res.expect("spawn ok");
        assert!(
            uniq.insert(addr.clone()),
            "duplicate address detected: {addr}"
        );
    }
}

#[tokio::test]
async fn spawn_fails_for_unknown_template() {
    let (factory, _registry, _events) = bootstrap_factory().await;
    let random_tpl_id = TemplateId::from_u128(0xdead_beef);

    let err = factory
        .spawn_instrument(
            SpawnRequest::builder()
                .template_id(random_tpl_id)
                .owner("alice".into())
                .salt(0)
                .build()
                .unwrap(),
        )
        .await
        .expect_err("expected failure");

    matches!(err, FactoryError::UnknownTemplate { .. })
        .then_some(())
        .expect("error variant should be UnknownTemplate");
}
```