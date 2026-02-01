```python
"""
CrowdPay Connect – Risk & Compliance Service
--------------------------------------------

core.rule_engine
~~~~~~~~~~~~~~~~

A lightweight, yet production-grade, rule-engine used by the
Risk & Compliance micro-service to perform *real-time* KYC, AML,
and fraud checks on every payment‐related domain event.

Key design goals
----------------
1. Security-by-Design
2. Hot-swappable rule definitions (YAML/JSON/DB)
3. Deterministic execution & auditability
4. Event-sourcing friendly – every decision is published as an
   immutable ComplianceEvent.

The engine purposefully avoids *eval()* and executes only a safe
subset of Python AST nodes.  Expressions are compiled into pure
Python callables cached in an LRU for speed.
"""

from __future__ import annotations

import ast
import json
import logging
import pathlib
import threading
import types
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import lru_cache, partial
from time import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

LOGGER = logging.getLogger("crowdpay.risk_compliance.rule_engine")
LOGGER.addHandler(logging.NullHandler())

__all__ = [
    "RiskLevel",
    "Decision",
    "Transaction",
    "UserProfile",
    "Rule",
    "RuleResult",
    "RuleEngine",
]


# --------------------------------------------------------------------------- #
#  Data-structures                                                            #
# --------------------------------------------------------------------------- #


class RiskLevel(Enum):
    """Relative severity of a compliance or fraud finding."""

    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()
    CRITICAL = auto()


class Decision(Enum):
    """Final decision after rule evaluation."""

    APPROVE = auto()
    MANUAL_REVIEW = auto()
    REJECT = auto()


@dataclass(frozen=True, slots=True)
class Transaction:
    """Subset of fields relevant to rule-evaluation.

    In production, the Transaction object will be hydrated from the event store
    or read side of the CQRS projection layer.
    """

    tx_id: str
    pod_id: str
    user_id: str
    amount: float
    currency: str
    country: str
    created_at: float


@dataclass(frozen=True, slots=True)
class UserProfile:
    """Minimalist representation of a user involved in the transaction."""

    user_id: str
    kyc_status: str
    reputation_score: float
    country: str
    is_pep: bool  # Politically exposed person


@dataclass(slots=True)
class Rule:
    """In-memory representation of a compliance/risk rule."""

    name: str
    description: str
    priority: int = 50  # Higher priority executed first
    conditions: Sequence[str] = field(default_factory=tuple)
    on_match: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

    # -- runtime compiled artefacts ----------------------------------------- #
    _compiled_conditions: Optional[List[Callable[..., bool]]] = field(
        default=None, init=False, repr=False
    )


@dataclass(frozen=True, slots=True)
class RuleResult:
    """Outcome of a single rule evaluation."""

    rule_name: str
    matched: bool
    risk_level: Optional[RiskLevel] = None
    decision: Optional[Decision] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
#  Safe expression compiler                                                   #
# --------------------------------------------------------------------------- #


_ALLOWED_AST_NODES = {
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.IfExp,
    ast.Compare,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.Attribute,
}


def _safe_compile(expr: str) -> Callable[..., bool]:
    """
    Compile an *expression* into a safe callable.

    The expression is first validated to contain only non-malicious AST nodes.
    """
    try:
        parsed = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid rule condition syntax: {expr!r}") from exc

    for node in ast.walk(parsed):
        if not isinstance(node, tuple(_ALLOWED_AST_NODES)):
            raise ValueError(
                f"Disallowed operation {node.__class__.__name__} in condition: {expr!r}"
            )

    compiled = compile(parsed, filename="<rule_condition>", mode="eval")

    def _predicate(**ctx: Any) -> bool:
        return bool(eval(compiled, {"__builtins__": {}}, ctx))

    return _predicate


@lru_cache(maxsize=512)
def _compile_condition(expr: str) -> Callable[..., bool]:
    """LRU cached wrapper around the AST safe compiler."""
    return _safe_compile(expr)


# --------------------------------------------------------------------------- #
#  Compliance event publisher (stub)                                          #
# --------------------------------------------------------------------------- #


class ComplianceEventPublisher:
    """Thin wrapper responsible for publishing compliance events.

    In production this can push to Kafka, NATS Jetstream, or any other event bus.
    """

    def publish(self, event: Dict[str, Any]) -> None:
        LOGGER.debug("Publishing compliance event: %s", json.dumps(event))
        # Placeholder: plug in your real broker here.


# --------------------------------------------------------------------------- #
#  Rule Engine                                                                 #
# --------------------------------------------------------------------------- #


class RuleEngine:
    """Evaluates risk & compliance rules on domain events.

    Thread-safe: rules may be executed concurrently once loaded.
    """

    _lock: threading.Lock
    _rules: List[Rule]
    _publisher: ComplianceEventPublisher

    def __init__(
        self,
        rule_sources: Iterable[pathlib.Path | Dict[str, Any]],
        *,
        publisher: Optional[ComplianceEventPublisher] = None,
    ) -> None:
        """
        Parameters
        ----------
        rule_sources:
            Collection of YAML/JSON files *or* pre-parsed rule dictionaries
            from which rules will be loaded at start-up.  Hot reloading can be
            achieved by constructing a new engine instance.
        publisher:
            Event publisher; if ``None``, a default stub is used.
        """
        self._lock = threading.RLock()
        self._rules = []
        self._publisher = publisher or ComplianceEventPublisher()
        self._load_rules(rule_sources)

    # --------------------------------------------------------------------- #
    #  Public interface                                                     #
    # --------------------------------------------------------------------- #

    def evaluate(
        self, *, tx: Transaction, user: UserProfile, extra_ctx: Optional[Dict[str, Any]] = None
    ) -> List[RuleResult]:
        """
        Evaluate all active rules against the transaction & user context.

        Returns a list of RuleResult items sorted by rule priority.
        """
        ctx = {
            "transaction": tx,
            "user": user,
            **(extra_ctx or {}),
        }
        LOGGER.debug("Starting rule evaluation for tx=%s", tx.tx_id)
        results: List[RuleResult] = []
        with self._lock:
            for rule in sorted(self._rules, key=lambda r: r.priority, reverse=True):
                if not rule.enabled:
                    continue

                if rule._compiled_conditions is None:
                    rule._compiled_conditions = [
                        _compile_condition(expr) for expr in rule.conditions
                    ]

                matched = all(predicate(**ctx) for predicate in rule._compiled_conditions)

                if matched:
                    result = self._on_rule_match(rule=rule, ctx=ctx)
                    results.append(result)
                    LOGGER.info(
                        "Rule matched: '%s' (decision=%s, risk=%s) on tx=%s",
                        rule.name,
                        result.decision,
                        result.risk_level,
                        tx.tx_id,
                    )
                else:
                    results.append(
                        RuleResult(
                            rule_name=rule.name,
                            matched=False,
                        )
                    )

        return results

    # --------------------------------------------------------------------- #
    #  Internal helpers                                                     #
    # --------------------------------------------------------------------- #

    def _on_rule_match(self, *, rule: Rule, ctx: Dict[str, Any]) -> RuleResult:
        """
        Build RuleResult, publish event, and return it.
        """
        decision_str = rule.on_match.get("decision", "MANUAL_REVIEW").upper()
        risk_str = rule.on_match.get("risk_level", "MEDIUM").upper()

        try:
            decision = Decision[decision_str]
        except KeyError:
            decision = Decision.MANUAL_REVIEW

        try:
            risk = RiskLevel[risk_str]
        except KeyError:
            risk = RiskLevel.MEDIUM

        result = RuleResult(
            rule_name=rule.name,
            matched=True,
            decision=decision,
            risk_level=risk,
            metadata={k: v for k, v in rule.on_match.items() if k not in {"decision", "risk_level"}},
        )

        event_payload = {
            "event_id": f"cmpl-{int(time()*1000)}",
            "timestamp": int(time()),
            "rule_name": rule.name,
            "tx_id": ctx["transaction"].tx_id,
            "user_id": ctx["user"].user_id,
            "decision": decision.name,
            "risk_level": risk.name,
            "metadata": result.metadata,
        }

        self._publisher.publish(event_payload)
        return result

    def _load_rules(self, sources: Iterable[pathlib.Path | Dict[str, Any]]) -> None:
        """
        Populate in-memory rule list from given sources.

        Supports JSON (.json) or YAML (.yml/.yaml) files, as well as raw dicts.
        """
        import yaml  # Locally scoped import to avoid dependency if not needed.

        for src in sources:
            try:
                if isinstance(src, pathlib.Path):
                    if not src.exists():
                        raise FileNotFoundError(src)
                    with src.open("rt", encoding="utf-8") as fp:
                        if src.suffix.lower() in {".yaml", ".yml"}:
                            raw_rules = yaml.safe_load(fp)
                        elif src.suffix.lower() == ".json":
                            raw_rules = json.load(fp)
                        else:
                            LOGGER.warning("Unsupported rule file type: %s", src)
                            continue
                elif isinstance(src, dict):
                    raw_rules = [src]  # Single rule dict
                else:
                    LOGGER.warning("Unknown rule source: %s", src)
                    continue

                for raw in raw_rules:
                    rule = self._build_rule(raw)
                    self._rules.append(rule)
                    LOGGER.debug("Loaded rule: %s", rule.name)

            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.error("Failed to load rule from %s: %s", src, exc, exc_info=True)

        if not self._rules:
            raise RuntimeError("No rules loaded – risk compliance engine cannot start!")

    @staticmethod
    def _build_rule(data: Dict[str, Any]) -> Rule:
        """Validate and convert raw dict to Rule dataclass."""
        required_fields = {"name", "description", "conditions"}
        missing = required_fields - data.keys()
        if missing:
            raise ValueError(f"Rule definition missing fields: {missing}")

        return Rule(
            name=data["name"],
            description=data["description"],
            priority=int(data.get("priority", 50)),
            conditions=tuple(map(str.strip, data["conditions"])),
            on_match=dict(data.get("actions") or {}),
            enabled=bool(data.get("enabled", True)),
        )


# --------------------------------------------------------------------------- #
#  Example usage (will be stripped during package build)                      #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.DEBUG)

    # Example rule definitions defined inline for demonstration purposes.
    RULES = [
        {
            "name": "HighAmountCrossBorder",
            "description": "Flag cross-border transfers over $10k",
            "priority": 90,
            "conditions": [
                "transaction.amount > 10_000",
                "transaction.country != user.country",
            ],
            "actions": {
                "risk_level": "HIGH",
                "decision": "MANUAL_REVIEW",
                "alert_code": "AML-HACB-001",
            },
        },
        {
            "name": "UnverifiedUserLargeTx",
            "description": "Reject large transactions from non-KYC verified users",
            "priority": 95,
            "conditions": [
                "user.kyc_status != 'VERIFIED'",
                "transaction.amount >= 5_000",
            ],
            "actions": {
                "risk_level": "CRITICAL",
                "decision": "REJECT",
                "alert_code": "KYC-UVU-002",
            },
        },
    ]

    engine = RuleEngine(rule_sources=[RULES[0], RULES[1]])

    result = engine.evaluate(
        tx=Transaction(
            tx_id="TX123456",
            pod_id="POD987",
            user_id="USER42",
            amount=12_500,
            currency="USD",
            country="US",
            created_at=time(),
        ),
        user=UserProfile(
            user_id="USER42",
            kyc_status="PENDING",
            reputation_score=42.0,
            country="CA",
            is_pep=False,
        ),
    )

    for r in result:
        print(r)
```