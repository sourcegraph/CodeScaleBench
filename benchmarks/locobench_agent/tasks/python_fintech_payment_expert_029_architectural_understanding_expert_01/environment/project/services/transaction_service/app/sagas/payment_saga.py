```python
"""
crowdpay_connect.services.transaction_service.app.sagas.payment_saga

Distributed Saga that orchestrates social payments inside CrowdPay Connect.

The PaymentSaga coordinates multiple micro-components to ensure that a complex
payment—spanning KYC verification, risk assessment, multi-currency conversion,
and immutable settlement—succeeds atomically or rolls back in a consistent,
auditable manner.

Author: CrowdPay Connect Engineering
Copyright: (c) 2024 CrowdPay
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Dict, List, Optional

# --------------------------------------------------------------------------- #
#                              Logging configuration                           #
# --------------------------------------------------------------------------- #

logger = logging.getLogger("crowdpay.payment_saga")
logger.addHandler(logging.NullHandler())

# --------------------------------------------------------------------------- #
#                              Domain primitives                               #
# --------------------------------------------------------------------------- #


class Currency(str, Enum):
    """Supported ISO-4217 currencies."""
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    NGN = "NGN"
    GHS = "GHS"


@dataclass(frozen=True)
class PaymentCommand:
    """Client-facing command that triggers the PaymentSaga."""
    payer_id: str
    crowdpod_id: str
    amount: float
    source_currency: Currency
    target_currency: Currency
    idempotency_key: str  # Used by API gateway to provide at-least-once semantics.


class PaymentStatus(str, Enum):
    PENDING = auto()
    COMPLETED = auto()
    FAILED = auto()
    COMPENSATED = auto()


@dataclass
class PaymentResult:
    """Final outcome of the saga."""
    transaction_id: str
    status: PaymentStatus
    message: Optional[str] = None
    events: List[Dict] = field(default_factory=list)  # Serialized domain events


# --------------------------------------------------------------------------- #
#                           Infrastructure contracts                           #
# --------------------------------------------------------------------------- #


class EventBus:
    """Interface for publishing domain events to Kafka/Pulsar/…
    The real implementation is injected at runtime by the service container."""
    def publish(self, topic: str, event: Dict) -> None:  # pragma: no cover
        raise NotImplementedError


class WalletService:
    def debit(self, user_id: str, amount: float, currency: Currency) -> str:  # noqa: D401 E501
        """Returns a ledger entry id."""
        raise NotImplementedError

    def credit(self, user_id: str, amount: float, currency: Currency) -> str:
        raise NotImplementedError


class KYCService:
    def verify_customer(self, user_id: str) -> bool:
        raise NotImplementedError


class RiskService:
    def assess_payment(self, user_id: str, amount: float, currency: Currency) -> bool:
        raise NotImplementedError


class ForexService:
    def convert(self, amount: float, source: Currency, target: Currency) -> float:
        raise NotImplementedError


class SettlementService:
    def settle_transaction(self, transaction_id: str) -> bool:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
#                               Saga machinery                                 #
# --------------------------------------------------------------------------- #

SagaAction = Callable[["SagaContext"], None]
CompensationAction = Callable[["SagaContext"], None]


@dataclass
class SagaStep:
    """Represents a single step within a saga."""
    name: str
    action: SagaAction
    compensation: Optional[CompensationAction] = None


class SagaExecutionError(Exception):
    """Raised when a saga step fails."""


@dataclass
class SagaContext:
    """
    Transient data shared between saga steps; lives only for the lifetime of the
    PaymentSaga execution.
    """
    command: PaymentCommand
    transaction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    journal: Dict[str, Dict] = field(default_factory=dict)  # Step results
    events: List[Dict] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#                               Payment Saga                                   #
# --------------------------------------------------------------------------- #

class PaymentSaga:
    """
    Orchestrates a distributed payment.

    The implementation is synchronous for readability, yet compatible with
    celery / asyncio wrappers because each step is pure I/O.
    """

    def __init__(
        self,
        wallet_service: WalletService,
        kyc_service: KYCService,
        risk_service: RiskService,
        forex_service: ForexService,
        settlement_service: SettlementService,
        event_bus: EventBus,
    ) -> None:
        self.wallet = wallet_service
        self.kyc = kyc_service
        self.risk = risk_service
        self.forex = forex_service
        self.settlement = settlement_service
        self.bus = event_bus

    # --------------------------------------------------------------------- #
    #                          Public entry point                           #
    # --------------------------------------------------------------------- #

    def execute(self, command: PaymentCommand) -> PaymentResult:
        """
        Run the saga and return a final PaymentResult—for API serialization.

        Idempotency is expected to be handled by an upstream layer (API GW +
        database). This coordinator focuses strictly on happy-path/rollback
        logic.
        """
        context = SagaContext(command=command)
        steps = self._build_steps()

        logger.info(
            "Starting PaymentSaga: transaction_id=%s, idempotency_key=%s",
            context.transaction_id,
            command.idempotency_key,
        )

        completed_steps: List[SagaStep] = []

        try:
            for step in steps:
                logger.debug("Executing step '%s' for transaction %s", step.name, context.transaction_id)
                step.action(context)  # Execute main action
                completed_steps.append(step)
                logger.debug("Step '%s' completed", step.name)
        except Exception as exc:
            logger.warning("Step '%s' failed: %s. Triggering compensation.", step.name, exc)
            self._compensate(context, reversed(completed_steps))
            # Persist FAILURE event
            self.bus.publish(
                topic="payments.lifecycle",
                event={
                    "event_type": "PaymentFailed",
                    "transaction_id": context.transaction_id,
                    "reason": str(exc),
                },
            )
            return PaymentResult(
                transaction_id=context.transaction_id,
                status=PaymentStatus.FAILED,
                message=str(exc),
                events=context.events,
            )

        # ------------------------------  Commit  -------------------------- #
        self.bus.publish(
            topic="payments.lifecycle",
            event={
                "event_type": "PaymentCompleted",
                "transaction_id": context.transaction_id,
            },
        )
        return PaymentResult(
            transaction_id=context.transaction_id,
            status=PaymentStatus.COMPLETED,
            events=context.events,
        )

    # --------------------------------------------------------------------- #
    #                           Private helpers                             #
    # --------------------------------------------------------------------- #

    def _build_steps(self) -> List[SagaStep]:
        """
        Dynamically constructs saga steps; easy to reorder / extend without
        modifying execute() control flow.
        """
        return [
            SagaStep(
                name="kyc_verification",
                action=self._action_verify_kyc,
                # no compensation, nothing to undo
            ),
            SagaStep(
                name="risk_assessment",
                action=self._action_risk_assessment,
            ),
            SagaStep(
                name="debit_payer",
                action=self._action_debit_payer,
                compensation=self._compensate_debit_payer,
            ),
            SagaStep(
                name="currency_conversion",
                action=self._action_currency_conversion,
                compensation=self._compensate_currency_conversion,
            ),
            SagaStep(
                name="credit_crowdpod",
                action=self._action_credit_crowdpod,
                compensation=self._compensate_credit_crowdpod,
            ),
            SagaStep(
                name="settlement",
                action=self._action_settlement,
                compensation=self._compensate_settlement,
            ),
        ]

    def _compensate(self, context: SagaContext, steps: List[SagaStep]) -> None:
        """Executes compensation in LIFO order."""
        for step in steps:
            if step.compensation is None:
                continue
            try:
                logger.debug(
                    "Compensating step '%s' for transaction %s",
                    step.name,
                    context.transaction_id,
                )
                step.compensation(context)
                logger.debug("Compensation for '%s' successful", step.name)
            except Exception as exc:  # noqa: BLE001
                # Compensation errors are fatal; manual intervention required.
                logger.error(
                    "Compensation for step '%s' failed! Transaction '%s' may "
                    "require manual reconciliation: %s",
                    step.name,
                    context.transaction_id,
                    exc,
                )
                self.bus.publish(
                    topic="payments.lifecycle",
                    event={
                        "event_type": "PaymentCompensationFailed",
                        "transaction_id": context.transaction_id,
                        "failed_step": step.name,
                        "reason": str(exc),
                    },
                )
                raise

    # --------------------------------------------------------------------- #
    #                           Saga step actions                           #
    # --------------------------------------------------------------------- #

    def _action_verify_kyc(self, ctx: SagaContext) -> None:
        """Ensure payer has a valid KYC profile."""
        if not self.kyc.verify_customer(ctx.command.payer_id):
            raise SagaExecutionError("KYC verification failed")
        ctx.events.append(
            {"event_type": "KycVerified", "user_id": ctx.command.payer_id}
        )

    def _action_risk_assessment(self, ctx: SagaContext) -> None:
        """Invoke real-time transaction risk evaluation."""
        approved = self.risk.assess_payment(
            user_id=ctx.command.payer_id,
            amount=ctx.command.amount,
            currency=ctx.command.source_currency,
        )
        if not approved:
            raise SagaExecutionError("Payment declined by risk engine")
        ctx.events.append(
            {"event_type": "PaymentRiskApproved", "user_id": ctx.command.payer_id}
        )

    def _action_debit_payer(self, ctx: SagaContext) -> None:
        """Debit the payer's wallet."""
        ledger_id = self.wallet.debit(
            user_id=ctx.command.payer_id,
            amount=ctx.command.amount,
            currency=ctx.command.source_currency,
        )
        ctx.journal["debit_ledger_id"] = ledger_id
        ctx.events.append(
            {"event_type": "WalletDebited", "ledger_id": ledger_id}
        )

    def _compensate_debit_payer(self, ctx: SagaContext) -> None:
        """Reverse payer debit."""
        ledger_id = self.wallet.credit(
            user_id=ctx.command.payer_id,
            amount=ctx.command.amount,
            currency=ctx.command.source_currency,
        )
        ctx.events.append(
            {
                "event_type": "WalletDebitReversed",
                "original_ledger_id": ctx.journal.get("debit_ledger_id"),
                "compensation_ledger_id": ledger_id,
            }
        )

    def _action_currency_conversion(self, ctx: SagaContext) -> None:
        """Convert funds if source & target currencies differ."""
        if ctx.command.source_currency == ctx.command.target_currency:
            ctx.journal["converted_amount"] = ctx.command.amount
            logger.debug("No currency conversion required.")
            return

        converted_amount = self.forex.convert(
            amount=ctx.command.amount,
            source=ctx.command.source_currency,
            target=ctx.command.target_currency,
        )
        if converted_amount <= 0:
            raise SagaExecutionError("Currency conversion failed")

        ctx.journal["converted_amount"] = converted_amount
        ctx.events.append(
            {
                "event_type": "CurrencyConverted",
                "from": ctx.command.source_currency,
                "to": ctx.command.target_currency,
                "original_amount": ctx.command.amount,
                "converted_amount": converted_amount,
            }
        )

    def _compensate_currency_conversion(self, ctx: SagaContext) -> None:
        """
        Currency conversion compensation is effectively a no-op because the
        actual wallet funds have not left the platform yet—it only informs the
        ledger entry that conversion was voided. In real-life scenarios, fx
        markets may require booking a compensating trade.
        """
        ctx.events.append(
            {
                "event_type": "CurrencyConversionVoided",
                "transaction_id": ctx.transaction_id,
            }
        )

    def _action_credit_crowdpod(self, ctx: SagaContext) -> None:
        """Credit funds to the CrowdPod wallet."""
        amount = ctx.journal.get("converted_amount", ctx.command.amount)
        ledger_id = self.wallet.credit(
            user_id=ctx.command.crowdpod_id,
            amount=amount,
            currency=ctx.command.target_currency,
        )
        ctx.journal["credit_ledger_id"] = ledger_id
        ctx.events.append(
            {"event_type": "CrowdPodCredited", "ledger_id": ledger_id}
        )

    def _compensate_credit_crowdpod(self, ctx: SagaContext) -> None:
        """Reverse CrowdPod credit."""
        amount = ctx.journal.get("converted_amount", ctx.command.amount)
        ledger_id = self.wallet.debit(
            user_id=ctx.command.crowdpod_id,
            amount=amount,
            currency=ctx.command.target_currency,
        )
        ctx.events.append(
            {
                "event_type": "CrowdPodCreditReversed",
                "original_ledger_id": ctx.journal.get("credit_ledger_id"),
                "compensation_ledger_id": ledger_id,
            }
        )

    def _action_settlement(self, ctx: SagaContext) -> None:
        """Mark transaction as settled in the clearing subsystem."""
        settled = self.settlement.settle_transaction(ctx.transaction_id)
        if not settled:
            raise SagaExecutionError("Settlement failed")
        ctx.events.append(
            {"event_type": "TransactionSettled", "transaction_id": ctx.transaction_id}
        )

    def _compensate_settlement(self, ctx: SagaContext) -> None:
        """
        Settlement compensation is domain-specific; often done via a manual
        “break” queue. Here we merely publish an alert.
        """
        self.bus.publish(
            topic="payments.lifecycle",
            event={
                "event_type": "SettlementVoided",
                "transaction_id": ctx.transaction_id,
            },
        )
        ctx.events.append(
            {"event_type": "SettlementVoided", "transaction_id": ctx.transaction_id}
        )
```