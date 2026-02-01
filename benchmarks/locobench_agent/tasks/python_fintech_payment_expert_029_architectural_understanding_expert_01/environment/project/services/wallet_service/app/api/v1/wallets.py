```python
"""
crowdpay_connect.services.wallet_service.app.api.v1.wallets

This module exposes versioned HTTP APIs for wallet–related operations in the
CrowdPay Connect platform.  All endpoints are asynchronous, protected by
authentication middleware, and leverage dependency-injected domain services.
"""

from __future__ import annotations

import decimal
import logging
import uuid
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field, condecimal, constr

from crowdpay_connect.services.wallet_service.app.core.exceptions import (
    CurrencyMismatchError,
    DuplicateRequestError,
    InsufficientFundsError,
    WalletNotFoundError,
)
from crowdpay_connect.services.wallet_service.app.core.models import User
from crowdpay_connect.services.wallet_service.app.core.use_cases.wallet_uc import (
    WalletUseCase,
)
from crowdpay_connect.services.wallet_service.app.infrastructure.event_bus import (
    EventBus,
)
from crowdpay_connect.shared.http.depends import (
    get_current_user,
    get_event_bus,
    get_wallet_use_case,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wallets", tags=["wallets"])

# --------------------------------------------------------------------------- #
# Pydantic DTOs                                                               #
# --------------------------------------------------------------------------- #


class WalletCreateRequest(BaseModel):
    """
    Request payload for creating a new CrowdPod wallet.
    """

    name: constr(min_length=3, max_length=50)
    base_currency: constr(min_length=3, max_length=3) = Field(
        ..., description="ISO-4217 currency code (e.g. USD, EUR)"
    )
    # Allow user to pre-fund a wallet as part of creation
    initial_balance: condecimal(max_digits=20, decimal_places=2) = Field(
        decimal.Decimal("0.00"), ge=0
    )


class WalletResponse(BaseModel):
    """
    Public representation of a wallet.  Domain object is flattened for the API.
    """

    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    base_currency: str
    available_balance: decimal.Decimal
    created_at: str
    updated_at: str


class TopUpRequest(BaseModel):
    """
    Request payload for topping up an existing wallet.
    """

    amount: condecimal(max_digits=20, decimal_places=2, gt=0)
    currency: constr(min_length=3, max_length=3)


class TransferRequest(BaseModel):
    """
    Request payload for transferring funds between wallets.
    """

    destination_wallet_id: uuid.UUID
    amount: condecimal(max_digits=20, decimal_places=2, gt=0)
    currency: constr(min_length=3, max_length=3)


# --------------------------------------------------------------------------- #
# Helper functions                                                            #
# --------------------------------------------------------------------------- #


def _require_idempotency_key(
    idempotency_key: Optional[str],
) -> str:
    """
    Ensures that an Idempotency-Key header is present on mutation-endpoints.

    Raises
    ------
    HTTPException
        When the header is missing.
    """
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required header: Idempotency-Key",
        )
    return idempotency_key


def _domain_to_response(domain_obj: Any) -> WalletResponse:
    """
    Maps a Wallet domain entity to API response DTO.

    The domain layer purposefully hides persistence details (ORM, etc.).

    Parameters
    ----------
    domain_obj:
        Wallet domain entity.

    Returns
    -------
    WalletResponse
        Serializable DTO for API transport.
    """
    return WalletResponse(
        id=domain_obj.id,
        name=domain_obj.name,
        owner_id=domain_obj.owner_id,
        base_currency=domain_obj.base_currency,
        available_balance=domain_obj.available_balance,
        created_at=domain_obj.created_at.isoformat(),
        updated_at=domain_obj.updated_at.isoformat(),
    )


def _http_error_from_domain(exc: Exception) -> HTTPException:
    """
    Converts domain-level exceptions to safe HTTP responses.

    Centralising this logic makes it easier to maintain consistent error
    handling across endpoints.
    """
    if isinstance(exc, WalletNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found",
        )
    if isinstance(exc, InsufficientFundsError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Insufficient funds",
        )
    if isinstance(exc, CurrencyMismatchError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Currency mismatch",
        )
    if isinstance(exc, DuplicateRequestError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate request",
        )
    # Fallback: hide internal details from client
    logger.exception("Unhandled domain exception: %s", exc)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unhandled error",
    )


# --------------------------------------------------------------------------- #
# API Endpoints                                                               #
# --------------------------------------------------------------------------- #


@router.post(
    "",
    response_model=WalletResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new wallet",
    description="Creates a CrowdPod wallet for the authenticated user.",
)
async def create_wallet(
    payload: WalletCreateRequest,
    current_user: User = Depends(get_current_user),
    wallet_uc: WalletUseCase = Depends(get_wallet_use_case),
    event_bus: EventBus = Depends(get_event_bus),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> WalletResponse:
    """
    POST /wallets

    Allows a user to create a new CrowdPod wallet. Creation publishes a
    `wallet.created` domain event for downstream handlers (KYC checks, etc.).
    """
    idempotency_key = _require_idempotency_key(idempotency_key)

    try:
        wallet = await wallet_uc.create_wallet(
            user_id=current_user.id,
            name=payload.name,
            base_currency=payload.base_currency.upper(),
            initial_balance=payload.initial_balance,
            idempotency_key=idempotency_key,
        )
        await event_bus.publish(
            topic="wallet.created",
            payload={"wallet_id": str(wallet.id), "owner_id": str(current_user.id)},
        )
    except Exception as exc:  # domain-level error
        raise _http_error_from_domain(exc) from exc

    return _domain_to_response(wallet)


@router.get(
    "/{wallet_id}",
    response_model=WalletResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a wallet",
    description="Returns wallet details. User must be the owner or have view "
    "permissions as defined by ACL.",
)
async def get_wallet(
    wallet_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    wallet_uc: WalletUseCase = Depends(get_wallet_use_case),
) -> WalletResponse:
    """
    GET /wallets/{wallet_id}

    Fetch wallet by identifier.
    """
    try:
        wallet = await wallet_uc.get_wallet(
            wallet_id=wallet_id, requester_id=current_user.id
        )
    except Exception as exc:
        raise _http_error_from_domain(exc) from exc

    return _domain_to_response(wallet)


@router.post(
    "/{wallet_id}/top-up",
    response_model=WalletResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Top-up a wallet",
    description="Credits funds into the specified wallet. Operation is "
    "idempotent and will reject duplicates based on the `Idempotency-Key`.",
)
async def top_up_wallet(
    wallet_id: uuid.UUID,
    payload: TopUpRequest,
    current_user: User = Depends(get_current_user),
    wallet_uc: WalletUseCase = Depends(get_wallet_use_case),
    event_bus: EventBus = Depends(get_event_bus),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> WalletResponse:
    """
    POST /wallets/{wallet_id}/top-up

    Funds are credited after passing risk assessment and AML checks (handled
    asynchronously via event listeners).
    """
    idempotency_key = _require_idempotency_key(idempotency_key)

    try:
        wallet = await wallet_uc.top_up(
            wallet_id=wallet_id,
            amount=payload.amount,
            currency=payload.currency.upper(),
            requester_id=current_user.id,
            idempotency_key=idempotency_key,
        )
        await event_bus.publish(
            topic="wallet.top_up",
            payload={
                "wallet_id": str(wallet_id),
                "amount": str(payload.amount),
                "currency": payload.currency.upper(),
            },
        )
    except Exception as exc:
        raise _http_error_from_domain(exc) from exc

    return _domain_to_response(wallet)


@router.post(
    "/{wallet_id}/transfer",
    response_model=WalletResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Transfer funds between wallets",
    description="Executes an atomic transfer from source wallet to destination "
    "wallet.  The transfer participates in a distributed Saga to ensure "
    "consistency across multi-step, multi-currency operations.",
)
async def transfer_funds(
    wallet_id: uuid.UUID,
    payload: TransferRequest,
    current_user: User = Depends(get_current_user),
    wallet_uc: WalletUseCase = Depends(get_wallet_use_case),
    event_bus: EventBus = Depends(get_event_bus),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> WalletResponse:
    """
    POST /wallets/{wallet_id}/transfer

    Returns the *updated* state of the source wallet after withdrawal.  Clients
    can subscribe to event streams for eventual confirmation on the destination
    wallet.
    """
    idempotency_key = _require_idempotency_key(idempotency_key)

    try:
        wallet = await wallet_uc.transfer_funds(
            source_wallet_id=wallet_id,
            destination_wallet_id=payload.destination_wallet_id,
            amount=payload.amount,
            currency=payload.currency.upper(),
            requester_id=current_user.id,
            idempotency_key=idempotency_key,
        )
        # Emit saga initiation event
        await event_bus.publish(
            topic="wallet.transfer_initiated",
            payload={
                "source_wallet_id": str(wallet_id),
                "destination_wallet_id": str(payload.destination_wallet_id),
                "amount": str(payload.amount),
                "currency": payload.currency.upper(),
            },
        )
    except Exception as exc:
        raise _http_error_from_domain(exc) from exc

    return _domain_to_response(wallet)


# --------------------------------------------------------------------------- #
# Health check endpoint (useful for k8s liveness/readiness probes)            #
# --------------------------------------------------------------------------- #


@router.get(
    "/_health",
    summary="Wallet service healthcheck",
    include_in_schema=False,
)
async def healthcheck(_: Request) -> Response:  # noqa: D401
    """
    Lightweight health probe that avoids hitting external dependencies.

    This endpoint intentionally bypasses dependency injection to keep the
    liveness probe isolated from downstream failures (DB, event bus, etc.).
    """
    return Response(content="OK", media_type="text/plain")
```