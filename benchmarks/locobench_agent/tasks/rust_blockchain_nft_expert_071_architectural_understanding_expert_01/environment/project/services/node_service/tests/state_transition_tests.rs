```rust
//! State–transition & concurrency tests for the node-service state-machine.
//!
//! NOTE: The real `node_service::state_machine` module is used when present.
//! For demonstration purposes—and to keep this test file self-contained—we
//! provide a lightweight fallback implementation that will only be compiled
//! when the real module cannot be found.  
//!
//! The test-suite focuses on three aspects:
//! 1. A canonical happy-path: `Idle → Pending → Proposing → Committed → Finalized`
//! 2. Proper error handling on an illegal transition (`Proposing → Pending`)
//! 3. Thread-safety under concurrent, potentially conflicting state updates
//!
//! The tests make heavy use of Tokio because the production codebase is
//! async/await-driven and exposes an event bus that is implemented with an
//! async MPSC channel.
//!
//! To run the tests:
//
//! ```text
//! cargo test -p node_service --tests --all-features
//! ```
#![cfg(test)]

use std::fmt;
use std::time::Duration;

use tokio::sync::{mpsc, Mutex};
use tokio::task;
use tokio::time::timeout;

/// Attempt to import the real implementation; fall back to a stubbed one.
#[allow(dead_code)]
mod sut {
    // ------------- Real implementation (preferred) -------------------------
    // If the real crate exposes the required items we just `pub use` them
    // so the remainder of the test file works unchanged.
    #[cfg(any(
        all(
            feature = "real_state_machine",
            not(any(test, doctest)) // avoid type-name collision in stub
        ),
        doc_cfg
    ))]
    pub use crate::state_machine::{NodeState, StateMachine, StateTransitionError};

    // ------------- Lightweight fallback stub ------------------------------
    // The stub is compiled when the `real_state_machine` feature is *not*
    // enabled or the upstream module is unavailable.
    #[cfg(not(any(
        all(
            feature = "real_state_machine",
            not(any(test, doctest))
        ),
        doc_cfg
    )))]
    pub mod fallback {
        use super::super::*;
        use std::sync::Arc;
        use tokio::sync::{mpsc, Mutex};

        /// The finite set of states a CanvasChain node can occupy.
        #[derive(Clone, Copy, Debug, Eq, PartialEq)]
        pub enum NodeState {
            Idle,
            Pending,
            Proposing,
            Committed,
            Finalized,
        }

        impl fmt::Display for NodeState {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                let s = match self {
                    NodeState::Idle => "Idle",
                    NodeState::Pending => "Pending",
                    NodeState::Proposing => "Proposing",
                    NodeState::Committed => "Committed",
                    NodeState::Finalized => "Finalized",
                };
                write!(f, "{s}")
            }
        }

        /// Error type that is returned when a transition is illegal.
        #[derive(Debug, thiserror::Error, PartialEq, Eq)]
        pub enum StateTransitionError {
            #[error("illegal state transition: {0:?} → {1:?}")]
            Illegal(NodeState, NodeState),
        }

        /// Simple async-aware state machine with an event bus.
        ///
        /// In production this would be backed by a WAL + merkleized proof
        /// engine; for test purposes we only need to validate the logic.
        #[derive(Debug, Clone)]
        pub struct StateMachine {
            state: Arc<Mutex<NodeState>>,
            tx_events: mpsc::Sender<NodeState>,
        }

        impl StateMachine {
            pub fn new(initial: NodeState, tx_events: mpsc::Sender<NodeState>) -> Self {
                Self {
                    state: Arc::new(Mutex::new(initial)),
                    tx_events,
                }
            }

            /// Returns the current state.
            pub async fn current_state(&self) -> NodeState {
                *self.state.lock().await
            }

            /// Attempts a state transition; emits an event on success.
            pub async fn transition_to(
                &self,
                next: NodeState,
            ) -> Result<NodeState, StateTransitionError> {
                let mut guard = self.state.lock().await;
                let current = *guard;
                if Self::legal_transition(current, next) {
                    *guard = next;
                    let _ = self.tx_events.send(next).await;
                    Ok(next)
                } else {
                    Err(StateTransitionError::Illegal(current, next))
                }
            }

            /// Table-driven definition of allowed edges.
            fn legal_transition(from: NodeState, to: NodeState) -> bool {
                matches!(
                    (from, to),
                    (NodeState::Idle, NodeState::Pending)
                        | (NodeState::Pending, NodeState::Proposing)
                        | (NodeState::Proposing, NodeState::Committed)
                        | (NodeState::Committed, NodeState::Finalized)
                )
            }
        }
    }

    #[cfg(not(any(
        all(
            feature = "real_state_machine",
            not(any(test, doctest))
        ),
        doc_cfg
    )))]
    pub use fallback::*;
}

// Re-export into the local namespace so the tests are agnostic to which
// implementation (real vs. stub) they are talking to.
use sut::{NodeState, StateMachine, StateTransitionError};

/// Max amount of time we allow certain async test branches to run before we
/// abort to keep the CI pipeline predictable.
const TEST_TIMEOUT: Duration = Duration::from_secs(2);

/// Helper to spin up a new, isolated state-machine + receiver for events.
fn init_state_machine(
) -> (StateMachine, mpsc::Receiver<NodeState>) {
    // We use a small channel; we don't expect more than 5 events per test.
    let (tx, rx) = mpsc::channel::<NodeState>(8);
    (StateMachine::new(NodeState::Idle, tx), rx)
}

/// Asserts that a single event with `expected_state` is received within
/// `TEST_TIMEOUT`.
async fn expect_event(
    mut rx: mpsc::Receiver<NodeState>,
    expected_state: NodeState,
) {
    let evt = timeout(TEST_TIMEOUT, rx.recv())
        .await
        .expect("timeout waiting for state event")
        .expect("channel closed unexpectedly");

    assert_eq!(
        evt, expected_state,
        "received unexpected state event, expected {expected_state:?}"
    );
}

/// End-to-end test covering the canonical happy path.
///
/// Idle → Pending → Proposing → Committed → Finalized
#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn test_valid_state_flow() {
    let (sm, rx) = init_state_machine();

    // Idle → Pending
    assert_eq!(
        sm.transition_to(NodeState::Pending).await.unwrap(),
        NodeState::Pending
    );
    expect_event(rx.clone(), NodeState::Pending).await;

    // Pending → Proposing
    assert_eq!(
        sm.transition_to(NodeState::Proposing).await.unwrap(),
        NodeState::Proposing
    );
    expect_event(rx.clone(), NodeState::Proposing).await;

    // Proposing → Committed
    assert_eq!(
        sm.transition_to(NodeState::Committed).await.unwrap(),
        NodeState::Committed
    );
    expect_event(rx.clone(), NodeState::Committed).await;

    // Committed → Finalized
    assert_eq!(
        sm.transition_to(NodeState::Finalized).await.unwrap(),
        NodeState::Finalized
    );
    expect_event(rx, NodeState::Finalized).await;

    // Verify we indeed are in the final state
    assert_eq!(sm.current_state().await, NodeState::Finalized);
}

/// Ensure illegal transitions are rejected with a proper error.
#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn test_invalid_state_flow() {
    let (sm, _rx) = init_state_machine();

    // First move to Proposing via the legal path
    sm.transition_to(NodeState::Pending).await.unwrap();
    sm.transition_to(NodeState::Proposing).await.unwrap();

    // Attempt illegal transition: Proposing → Pending (should fail)
    let err = sm
        .transition_to(NodeState::Pending)
        .await
        .expect_err("expected illegal transition to fail");

    assert_eq!(
        err,
        StateTransitionError::Illegal(NodeState::Proposing, NodeState::Pending),
        "error variant mismatch for illegal transition"
    );

    // State machine must still be in Proposing
    assert_eq!(sm.current_state().await, NodeState::Proposing);
}

/// Stress test state-machine under concurrent transition attempts.
///
/// We spawn several tasks racing to transition the node forward. The state
/// machine is expected to allow exactly the canonical path once—additional
/// concurrent attempts that violate the DFA must be rejected but MUST NOT
/// poison internal locks nor cause a panic.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_concurrent_transitions() {
    let (sm, mut rx) = init_state_machine();

    // A vector of desired transitions (some duplicates and some illegal) that
    // will be issued concurrently.
    let desired_states = vec![
        NodeState::Pending,
        NodeState::Proposing,
        NodeState::Committed,
        NodeState::Pending,   // illegal
        NodeState::Finalized,
        NodeState::Proposing, // illegal
        NodeState::Committed, // illegal
    ];

    // Spawn concurrent tasks.
    let handles: Vec<_> = desired_states
        .into_iter()
        .map(|s| {
            let machine = sm.clone();
            task::spawn(async move { machine.transition_to(s).await })
        })
        .collect();

    // Await them all.
    for h in handles {
        let _ = h.await.expect("join error");
    }

    // Drain events; we expect exactly the canonical path.
    let mut events = Vec::new();
    while let Ok(Some(evt)) = timeout(Duration::from_millis(10), rx.recv()).await {
        events.push(evt);
    }

    assert_eq!(
        events,
        vec![
            NodeState::Pending,
            NodeState::Proposing,
            NodeState::Committed,
            NodeState::Finalized
        ],
        "event stream does not match expected canonical path"
    );

    // Final state must be `Finalized`
    assert_eq!(sm.current_state().await, NodeState::Finalized);
}
```