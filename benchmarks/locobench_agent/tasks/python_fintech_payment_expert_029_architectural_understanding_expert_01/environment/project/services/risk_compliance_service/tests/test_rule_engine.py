```python
"""
CrowdPay Connect
Risk & Compliance Service – Rule-Engine Test-Suite
--------------------------------------------------

These tests exercise the public contract of the RuleEngine component
located in `crowdpay_connect.services.risk_compliance_service.rule_engine`.

The intent is to cover:

1. Deterministic business behaviour (expected risk levels).
2. Runtime flexibility (hot-reloading / toggling of rules).
3. Non-functional guarantees (thread-safety, performance).
4. Diagnostic information (triggered rules returned to caller).

All tests are written with pytest and only rely on the public API of the
service.  Internal/private attributes are accessed exclusively via
`monkeypatch` to avoid white-box coupling.
"""
from __future__ import annotations

import concurrent.futures
import statistics
import time
from typing import List, Tuple

import pytest

# Public API under test.
from crowdpay_connect.services.risk_compliance_service.rule_engine import (
    RuleEngine,
    RiskAssessment,
    RuleViolation,
)

###############################################################################
# Fixtures
###############################################################################


@pytest.fixture(scope="module")
def rule_engine() -> RuleEngine:
    """
    Return a *singleton* RuleEngine instance for this test module.

    We consider the engine to be side-effect free once instantiated
    (e.g. rules are cached, services wired, etc.) – if that ever changes,
    simply switch to `function` scope.
    """
    engine = RuleEngine()
    # Ensure the engine boots cleanly in under a second in CI.
    t0 = time.perf_counter()
    engine.bootstrap()  # type: ignore[attr-defined]
    assert (time.perf_counter() - t0) < 1.0
    return engine


###############################################################################
# Helper Data
###############################################################################

# ––––– Transaction & User profile "builders" –––––


def _tx(amount: float, currency: str = "USD", cross_border: bool = False) -> dict:
    """
    Convenience helper to build a transaction payload
    accepted by the RuleEngine for tests below.
    """
    return {
        "id": "tx-test-123",
        "amount": amount,
        "currency": currency,
        "cross_border": cross_border,
        "timestamp": "2024-01-01T12:00:00Z",
        "actor_id": "user-abc",
        "crowdpod_id": "pod-xyz",
    }


def _profile(kyc_verified: bool, reputation: int = 50) -> dict:
    """Build a user profile input."""
    return {
        "user_id": "user-abc",
        "kyc_verified": kyc_verified,
        "reputation": reputation,  # 0—100 scale
        "badges": ["founding_member"],
    }


###############################################################################
# Business Rule Tests
###############################################################################


def _assert_risk(
    assessment: RiskAssessment,
    expected_level: str,
    min_rules: int | None = None,
) -> None:
    """Shared assertions for RiskAssessment correctness."""
    assert assessment.level == expected_level, assessment  # type: ignore[attr-defined]
    assert (
        0 <= assessment.score <= 100
    ), "Risk score must be a bounded 0–100 integer"

    if min_rules is not None:
        assert len(assessment.triggered_rules) >= min_rules


@pytest.mark.parametrize(
    "tx,profile,expected_level",
    [
        pytest.param(_tx(15.5), _profile(kyc_verified=True), "LOW", id="small-verified"),
        pytest.param(
            _tx(9_500.0),
            _profile(kyc_verified=False, reputation=20),
            "HIGH",
            id="large-unverified",
        ),
        pytest.param(
            _tx(500.0, currency="NGN", cross_border=True),
            _profile(kyc_verified=True, reputation=80),
            "MEDIUM",
            id="cross-border",
        ),
    ],
)
def test_risk_levels(
    rule_engine: RuleEngine,
    tx: dict,
    profile: dict,
    expected_level: str,
) -> None:
    """
    Validate that canonical transaction/profile permutations
    return the documented, expected risk level.
    """
    assessment = rule_engine.evaluate(tx, profile)
    _assert_risk(assessment, expected_level, min_rules=1)


def test_triggered_rule_details(rule_engine: RuleEngine) -> None:
    """
    The engine must return *actionable* diagnostics – including
    the human-readable message for each violated rule.
    """
    assessment = rule_engine.evaluate(
        _tx(20_000.00, cross_border=True),
        _profile(kyc_verified=False, reputation=10),
    )

    violated: List[RuleViolation] = assessment.triggered_rules
    assert violated, "At least one rule should have been violated"

    # All violation objects must have mandatory attributes.
    for v in violated:
        assert v.rule_name
        assert v.severity in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert v.message
        # Severity CRITICAL must automatically produce HIGH risk.
        if v.severity == "CRITICAL":
            assert assessment.level == "HIGH"


###############################################################################
# Non-Functional Tests
###############################################################################


def test_rule_caching(monkeypatch: pytest.MonkeyPatch, rule_engine: RuleEngine) -> None:
    """
    Ensure `_load_rules` is called exactly once, even if evaluate()
    is invoked multiple times.  We validate via monkeypatching.

    Note: We patch *after* `bootstrap` so any initial call isn't
    counted as part of the assertion.
    """

    call_counter = {"count": 0}

    def _spy_loader(original_loader):  # type: ignore
        def inner():
            call_counter["count"] += 1
            return original_loader()

        return inner

    # Patch private method & preserve original.
    original_loader = rule_engine._load_rules  # type: ignore[attr-defined]
    monkeypatch.setattr(
        rule_engine,
        "_load_rules",
        _spy_loader(original_loader),
        raising=True,
    )

    # Invoke the engine multiple times.
    for _ in range(5):
        rule_engine.evaluate(_tx(42.0), _profile(kyc_verified=True))

    assert call_counter["count"] == 0, (
        "RuleEngine should cache compiled rules; "
        "_load_rules was called during evaluation."
    )


def test_concurrent_evaluate(rule_engine: RuleEngine) -> None:
    """
    Verify that RuleEngine.evaluate is thread-safe and deterministic.

    We dispatch 50 concurrent evaluations and ensure:
    1. No exceptions raised.
    2. Risk scores are identical between runs for identical payloads.
    3. Execution time scales linearly (<2× single-thread median).
    """
    iterations = 50
    payloads: List[Tuple[dict, dict]] = [
        (_tx(amount=92.7, currency="EUR"), _profile(kyc_verified=True))
        for _ in range(iterations)
    ]

    t0_single = time.perf_counter()
    expected = rule_engine.evaluate(*payloads[0])
    t_single = time.perf_counter() - t0_single

    # Fire off workers.
    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as exc:
        futures = [
            exc.submit(rule_engine.evaluate, tx, profile)
            for tx, profile in payloads
        ]
        results = [f.result(timeout=2) for f in futures]
    t_total = time.perf_counter() - t0

    # Assert deterministic output.
    for res in results:
        assert res.score == expected.score
        assert res.level == expected.level

    # Performance: 50 calls / 10 workers – allow generous headroom.
    assert t_total < (t_single * iterations) / 4, (
        f"Concurrent execution too slow: {t_total:.3f}s "
        f"(single call {t_single:.3f}s)"
    )


###############################################################################
# Runtime Rule Toggle
###############################################################################


def test_dynamic_rule_toggle(rule_engine: RuleEngine, monkeypatch: pytest.MonkeyPatch):
    """
    Some regulators require the ability to toggle rules at runtime
    without a full service restart.  We mimic that capability by
    disabling a high-risk rule, then re-evaluating the same transaction
    to validate *observable* behaviour change.
    """

    tx = _tx(4_000.00, cross_border=True)
    profile = _profile(kyc_verified=False)

    assessment_before = rule_engine.evaluate(tx, profile)
    _assert_risk(assessment_before, "HIGH")

    # Dynamically disable the CROSS_BORDER_KYC rule.
    toggled = False

    def fake_is_enabled(rule_name: str) -> bool:  # noqa: D401
        nonlocal toggled
        # After first toggle, pretend rule is off.
        if rule_name == "CROSS_BORDER_KYC":
            return False
        return True

    # Patch the is_enabled callback (public API).
    monkeypatch.setattr(
        rule_engine,
        "is_rule_enabled",
        fake_is_enabled,
        raising=True,
    )
    toggled = True  # noqa: F841

    assessment_after = rule_engine.evaluate(tx, profile)

    # Expect risk to downgrade due to rule suppression.
    assert assessment_after.score < assessment_before.score
    assert assessment_after.level in {"LOW", "MEDIUM"}
    # The disabled rule must not appear in triggered list.
    assert all(
        v.rule_name != "CROSS_BORDER_KYC" for v in assessment_after.triggered_rules
    )


###############################################################################
# Statistical Predictability
###############################################################################


def test_risk_score_distribution(rule_engine: RuleEngine) -> None:
    """
    Generate a representative sample of random transactions to ensure
    risk scores stay within an acceptable variance – preventing skew
    that may break upstream reputation algorithms.
    """
    import random

    sample_size = 200
    scores: List[int] = []

    for _ in range(sample_size):
        amt = random.uniform(1.0, 10_000.0)
        cross = random.choice([True, False])
        rep = random.randint(0, 100)
        kyc = random.choice([True, False])

        assessment = rule_engine.evaluate(
            _tx(amt, currency=random.choice(["USD", "GBP", "NGN"]), cross_border=cross),
            _profile(kyc_verified=kyc, reputation=rep),
        )
        scores.append(assessment.score)

    # Reasonable variance – std-dev should not blow up.
    sigma = statistics.pstdev(scores)
    assert sigma < 25, f"Risk score variance unexpectedly high: σ={sigma:.2f}"

    # Mean should reside mid-range.
    mu = statistics.mean(scores)
    assert 30 <= mu <= 70, f"Risk score mean skewed: μ={mu:.2f}"
```