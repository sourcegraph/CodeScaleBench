```rust
//! Integration-tests for the pluggable cryptographic strategy layer.
//!
//! These tests exercise the public surface of `ccs_crypto` from the viewpoint
//! of the rest of the CanvasChain Symphony workspace.  We purposefully do **not**
//! reach into crate internals—only the public API—so that refactors which keep
//! the API stable will *not* break these tests, while any change that silently
//! alters the contract will be detected at compile-time or runtime.
//!
//! The scenarios covered include:
//! 1. Round-trip sign → verify for every built-in curve.
//! 2. Cross-curve negative verification (sign with curve A, verify with B).
//! 3. `dyn CryptoStrategy` dynamic-dispatch usage.
//! 4. Concurrency & thread-safety of both the strategy implementations and the
//!    global `StrategyRegistry`.
//! 5. Property-based fuzzing of arbitrary messages to avoid trivial
//!    “all-zeroes” or empty vector corner-cases.

#![cfg(test)]

use std::{
    sync::Arc,
    thread,
    time::{Duration, Instant},
};

use once_cell::sync::Lazy;
use proptest::prelude::*;
use rand::{rngs::OsRng, RngCore};

use ccs_crypto::{
    error::CryptoError,
    registry::{CurveId, StrategyRegistry},
    strategy::CryptoStrategy,
    // Concrete strategy implementations shipped with the crate
    strategies::{
        bls12381::Bls12381Strategy,
        ed25519::Ed25519Strategy,
        secp256k1::Secp256k1Strategy,
    },
    types::{PrivateKey, PublicKey, Signature},
};

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

static MESSAGE: Lazy<Vec<u8>> = Lazy::new(|| {
    b"CanvasChain Symphony – inspired test vector 🌐🎨 (v1.0)".to_vec()
});

fn round_trip<S>(strategy: &S, msg: &[u8])
where
    S: CryptoStrategy,
{
    let (pk, sk) = strategy
        .generate_keypair()
        .expect("key-gen should succeed on happy path");

    let signature = strategy
        .sign(&sk, msg)
        .expect("signing must succeed with a freshly generated key");

    strategy
        .verify(&pk, msg, &signature)
        .expect("verification of freshly signed message should succeed");
}

// -----------------------------------------------------------------------------
// 1. Basic round-trip tests per curve
// -----------------------------------------------------------------------------

#[test]
fn ed25519_round_trip_static_msg() {
    let strategy = Ed25519Strategy::default();
    round_trip(&strategy, &MESSAGE);
}

#[test]
fn bls12381_round_trip_static_msg() {
    let strategy = Bls12381Strategy::default();
    round_trip(&strategy, &MESSAGE);
}

#[test]
fn secp256k1_round_trip_static_msg() {
    let strategy = Secp256k1Strategy::default();
    round_trip(&strategy, &MESSAGE);
}

// -----------------------------------------------------------------------------
// 2. Cross-curve negative test
// -----------------------------------------------------------------------------

#[test]
fn cross_curve_verification_must_fail() {
    let ed25519 = Ed25519Strategy::default();
    let bls = Bls12381Strategy::default();

    let (pk_ed, sk_ed) = ed25519.generate_keypair().unwrap();
    let signature_by_ed = ed25519.sign(&sk_ed, &MESSAGE).unwrap();

    // Attempt to verify Ed25519 signature with a BLS strategy.
    let err = bls
        .verify(&pk_ed, &MESSAGE, &signature_by_ed)
        .expect_err("cross-curve verification MUST fail");
    assert!(
        matches!(err, CryptoError::VerificationFailed),
        "unexpected error variant: {err:?}"
    );
}

// -----------------------------------------------------------------------------
// 3. Dynamic-dispatch smoke test
// -----------------------------------------------------------------------------

#[test]
fn dyn_crypto_strategy_round_trip() {
    let strat_objects: Vec<Arc<dyn CryptoStrategy>> = vec![
        Arc::new(Ed25519Strategy::default()),
        Arc::new(Bls12381Strategy::default()),
        Arc::new(Secp256k1Strategy::default()),
    ];

    for strategy in strat_objects {
        round_trip(&*strategy, &MESSAGE);
    }
}

// -----------------------------------------------------------------------------
// 4. Registry lookup & thread-safety
// -----------------------------------------------------------------------------

#[test]
fn registry_can_resolve_built_in_curves() {
    let registry = StrategyRegistry::global();
    let curves = [
        CurveId::Ed25519,
        CurveId::Bls12381,
        CurveId::Secp256k1,
    ];

    for id in curves {
        let strat = registry
            .get(id)
            .expect("built-in strategy should be registered");
        round_trip(&*strat, &MESSAGE);
    }
}

#[test]
fn registry_is_thread_safe() {
    // Stress-test concurrent key-gen & signing.
    let registry = StrategyRegistry::global();

    // 4 threads per curve ‑ just enough to prove Send/Sync correctness without
    // materially elongating the CI job.
    let mut handles = Vec::new();
    for id in [CurveId::Ed25519, CurveId::Bls12381, CurveId::Secp256k1] {
        for _ in 0..4 {
            let strat = registry.get(id).unwrap();
            let msg = MESSAGE.clone();
            handles.push(thread::spawn(move || {
                for _ in 0..128 {
                    round_trip(&*strat, &msg);
                }
            }));
        }
    }

    for h in handles {
        h.join().expect("thread panicked");
    }
}

// -----------------------------------------------------------------------------
// 5. Property-based testing: random message payloads
// -----------------------------------------------------------------------------

proptest! {
    #[test]
    fn prop_round_trip_random_msgs(raw in prop::collection::vec(any::<u8>(), 1..2048)) {
        let strategy = Ed25519Strategy::default();
        round_trip(&strategy, &raw);
    }
}

// -----------------------------------------------------------------------------
// 6. Time-constant verification (regression for early-return mistakes)
// -----------------------------------------------------------------------------

/// Very coarse heuristic to catch accidental early-return implementations in
/// `verify()`.  We compare the time taken to verify a correct signature and an
/// obviously incorrect one.  The delta must be within a small threshold.
/// NOTE: This is **not** a replacement for dedicated side-channel analysis; it
/// merely guards against regressions during refactors.
#[test]
fn verification_time_is_constantish() {
    const N: usize = 8_192; // number of repetitions per scenario
    const THRESHOLD_NS: u128 = 50_000; // ~0.05 ms tolerance

    let strat = Ed25519Strategy::default();
    let (pk, sk) = strat.generate_keypair().unwrap();

    let good_sig = strat.sign(&sk, &MESSAGE).unwrap();
    let mut bad_sig = good_sig.clone();
    // Flip a single bit: cheap way to ensure invalid signature of same length.
    let byte = &mut bad_sig.as_mut_bytes()[0];
    *byte ^= 0b0000_0001;

    // helper closure
    let bench = |sig: &Signature| {
        let start = Instant::now();
        for _ in 0..N {
            let _ = strat.verify(&pk, &MESSAGE, sig).is_ok();
        }
        start.elapsed()
    };

    let good_dur = bench(&good_sig);
    let bad_dur = bench(&bad_sig);

    let delta = if good_dur > bad_dur {
        good_dur - bad_dur
    } else {
        bad_dur - good_dur
    };

    assert!(
        delta.as_nanos() < THRESHOLD_NS,
        "verification timing differs too much: good={good_dur:?}, bad={bad_dur:?}"
    );
}

// -----------------------------------------------------------------------------
// 7. Negative test: signing with an empty private key
// -----------------------------------------------------------------------------

/// Some callers may try to construct `PrivateKey::default()` which is expected
/// to be an error when used for signing.  Make sure we propagate a *nice*
/// `CryptoError::InvalidKey`.
#[test]
fn signing_with_empty_private_key_fails() {
    let strat = Bls12381Strategy::default();
    let empty_sk = PrivateKey::default();

    let err = strat
        .sign(&empty_sk, &MESSAGE)
        .expect_err("signing with default key must error");

    assert!(
        matches!(err, CryptoError::InvalidKey),
        "unexpected error variant: {err:?}"
    );
}

// -----------------------------------------------------------------------------
// 8. Stress test: large payload (1 MiB)
// -----------------------------------------------------------------------------

#[test]
fn large_payload_round_trip() {
    let strat = Secp256k1Strategy::default();
    let mut buf = vec![0_u8; 1 << 20]; // 1 MiB
    OsRng.fill_bytes(&mut buf);
    round_trip(&strat, &buf);
}
```