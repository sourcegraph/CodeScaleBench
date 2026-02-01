```python
"""
crowdpay_connect.services.crowdpod_service.app.api.v1.pods

This module exposes the version-1 REST API for CrowdPods.  The API is deliberately
thin; it translates HTTP/JSON payloads into domain calls and turns domain-level
errors into well-defined HTTP errors.  All business rules live in the
`CrowdPodService` and downstream domain components.

Author: CrowdPay Connect Team
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field, constr, validator

# NOTE: These objects live in other packages of the service.  They are imported
# here to keep the API layer free from business logic.
from crowdpay_connect.services.crowdpod_service.app.core.exceptions import (
    CrowdPodNotFoundError,
    InsufficientFundsError,
    KYCVerificationRequiredError,
    RiskAssessmentFailedError,
    UnauthorizedOperationError,
)
from crowdpay_connect.services.crowdpod_service.app.core.models.currency import (
    Currency,
)
from crowdpay_connect.services.crowdpod_service.app.core.services.pod_service import (
    CrowdPodService,
    CrowdPodSummary,
)
from crowdpay_connect.shared.infrastructure.tracing import CorrelationId, get_cid

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Pydantic API Schemas
# ------------------------------------------------------------------------------


class CrowdPodCreateRequest(BaseModel):
    """
    Schema used to create a new CrowdPod.
    """

    name: constr(min_length=3, max_length=64)
    description: Optional[constr(max_length=255)] = None
    base_currency: Currency = Field(
        ..., description="3-letter ISO-4217 base currency for the pod"
    )
    owner_id: uuid.UUID
    members: Optional[List[uuid.UUID]] = Field(
        None, description="Initial list of user-ids to be invited to the pod"
    )

    # Business safeguard to prevent accidental public pods
    is_public: bool = Field(False, description="If True, pod is discoverable")

    @validator("members", always=True)
    def include_owner_in_members(cls, v, values):
        owner = values.get("owner_id")
        members = v or []
        if owner and owner not in members:
            members.append(owner)
        return members


class CrowdPodUpdateRequest(BaseModel):
    """
    Partial update for CrowdPod meta-data.
    """

    name: Optional[constr(min_length=3, max_length=64)] = None
    description: Optional[constr(max_length=255)] = None
    is_public: Optional[bool] = None


class MoneyRequest(BaseModel):
    """
    Base payload for deposit / withdraw.
    """

    amount: float = Field(..., gt=0, description="Monetary amount")
    currency: Currency = Field(..., description="ISO-4217 currency")
    reference: Optional[str] = Field(None, max_length=140)


class CrowdPodResponse(BaseModel):
    """
    Canonical API representation of a CrowdPod.
    """

    id: uuid.UUID
    name: str
    description: Optional[str] = None
    owner_id: uuid.UUID
    members: List[uuid.UUID]
    base_currency: Currency
    balance: float
    is_public: bool
    created_at: datetime
    updated_at: datetime


class CrowdPodListResponse(BaseModel):
    total: int
    items: List[CrowdPodSummary]


# ------------------------------------------------------------------------------
# Dependency Injection
# ------------------------------------------------------------------------------


def get_pod_service() -> CrowdPodService:
    """
    Resolve an instance of `CrowdPodService` from the IOC container.

    In production we leverage a proper DI container (e.g. `punq`, `wired`) that in
    turn provides instrumented repositories, event-bus clients, and so on.
    """
    return CrowdPodService()  # type: ignore  # Real wiring lives elsewhere


# ------------------------------------------------------------------------------
# APIRouter
# ------------------------------------------------------------------------------

router = APIRouter(
    prefix="/pods",
    tags=["pods"],
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Validation Error"},
        status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"},
        status.HTTP_403_FORBIDDEN: {"description": "Operation not permitted"},
        status.HTTP_404_NOT_FOUND: {"description": "Resource not found"},
    },
)


# ------------------------------------------------------------------------------
#                          Helper utilities
# ------------------------------------------------------------------------------


def _map_exception(exc: Exception) -> HTTPException:  # noqa: C901
    """
    Translate domain-level exceptions into FastAPI HTTPException objects.
    """
    if isinstance(exc, CrowdPodNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, UnauthorizedOperationError):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, RiskAssessmentFailedError):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Risk assessment failed. Deposit rejected.",
        )
    if isinstance(exc, KYCVerificationRequiredError):
        return HTTPException(
            status.HTTP_428_PRECONDITION_REQUIRED,
            detail="KYC verification required.",
        )
    if isinstance(exc, InsufficientFundsError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    # Fallback to internal error
    logger.exception("Unhandled domain exception")
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")


# ------------------------------------------------------------------------------
#                          Endpoint definitions
# ------------------------------------------------------------------------------


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CrowdPodResponse,
    summary="Create a new CrowdPod",
)
async def create_pod(
    payload: CrowdPodCreateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    cid: CorrelationId = Depends(get_cid),
    service: CrowdPodService = Depends(get_pod_service),
) -> CrowdPodResponse:
    """
    Kick-off a Saga that creates a new CrowdPod, provisions its wallet, and emits
    the corresponding domain events.
    """
    try:
        pod = await service.create_pod(payload, cid=cid, background=background_tasks)
        return CrowdPodResponse(**pod.dict())
    except Exception as exc:
        raise _map_exception(exc) from exc


@router.get(
    "/{pod_id}",
    response_model=CrowdPodResponse,
    summary="Retrieve a specific CrowdPod",
)
async def get_pod(
    pod_id: uuid.UUID = Path(..., description="CrowdPod identifier"),
    cid: CorrelationId = Depends(get_cid),
    service: CrowdPodService = Depends(get_pod_service),
) -> CrowdPodResponse:
    try:
        pod = await service.get_pod(pod_id, cid=cid)
        return CrowdPodResponse(**pod.dict())
    except Exception as exc:
        raise _map_exception(exc) from exc


@router.get(
    "",
    response_model=CrowdPodListResponse,
    summary="List CrowdPods (paginated)",
)
async def list_pods(
    owner_id: Optional[uuid.UUID] = Query(
        None, description="Filter pods owned by a specific user"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cid: CorrelationId = Depends(get_cid),
    service: CrowdPodService = Depends(get_pod_service),
) -> CrowdPodListResponse:
    pods, total = await service.list_pods(
        owner_id=owner_id, limit=limit, offset=offset, cid=cid
    )
    return CrowdPodListResponse(total=total, items=pods)


@router.patch(
    "/{pod_id}",
    response_model=CrowdPodResponse,
    summary="Update CrowdPod metadata",
)
async def update_pod(
    pod_id: uuid.UUID,
    payload: CrowdPodUpdateRequest,
    cid: CorrelationId = Depends(get_cid),
    service: CrowdPodService = Depends(get_pod_service),
) -> CrowdPodResponse:
    try:
        pod = await service.update_pod(pod_id, payload, cid=cid)
        return CrowdPodResponse(**pod.dict())
    except Exception as exc:
        raise _map_exception(exc) from exc


@router.post(
    "/{pod_id}/deposit",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Deposit funds into a CrowdPod",
)
async def deposit(
    pod_id: uuid.UUID,
    payload: MoneyRequest,
    background_tasks: BackgroundTasks,
    cid: CorrelationId = Depends(get_cid),
    service: CrowdPodService = Depends(get_pod_service),
) -> Response:
    """
    The deposit endpoint triggers an asynchronous Saga because it may involve:
      - Multi-currency FX conversion via liquidity partners
      - Risk scoring
      - Event-sourced ledger write
      - Downstream notifications to pod members
    """
    try:
        await service.deposit(pod_id, payload, cid=cid, background=background_tasks)
        return Response(
            status_code=status.HTTP_202_ACCEPTED,
            headers={"X-Correlation-Id": str(cid)},
        )
    except Exception as exc:
        raise _map_exception(exc) from exc


@router.post(
    "/{pod_id}/withdraw",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Withdraw funds from a CrowdPod",
)
async def withdraw(
    pod_id: uuid.UUID,
    payload: MoneyRequest,
    background_tasks: BackgroundTasks,
    cid: CorrelationId = Depends(get_cid),
    service: CrowdPodService = Depends(get_pod_service),
) -> Response:
    try:
        await service.withdraw(pod_id, payload, cid=cid, background=background_tasks)
        return Response(
            status_code=status.HTTP_202_ACCEPTED,
            headers={"X-Correlation-Id": str(cid)},
        )
    except Exception as exc:
        raise _map_exception(exc) from exc


@router.post(
    "/{pod_id}/close",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Close a CrowdPod",
)
async def close_pod(
    pod_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    x_user_id: uuid.UUID = Header(
        ..., alias="X-User-Id", description="Requesting user's identifier"
    ),
    cid: CorrelationId = Depends(get_cid),
    service: CrowdPodService = Depends(get_pod_service),
) -> Response:
    """
    Close a CrowdPod if its balance is zero and all obligations are settled.
    """
    try:
        await service.close_pod(
            pod_id=pod_id, requester_id=x_user_id, cid=cid, background=background_tasks
        )
        return Response(
            status_code=status.HTTP_202_ACCEPTED,
            headers={"X-Correlation-Id": str(cid)},
        )
    except Exception as exc:
        raise _map_exception(exc) from exc
```