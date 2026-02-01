```python
"""
CrowdPay Connect ‑ User API (v1)

This module exposes the public HTTP interface for all User-related
operations in the User-Service micro-service.  All endpoints are mounted
under /api/v1/users.

Design notes
------------
* FastAPI is used for its async support and automatic documentation.
* The router delegates business rules to a dedicated service layer
  (`crowdpay_connect.services.user_service.domain.services`) so that the
  API layer remains thin and free from domain logic.
* Domain and infrastructure errors are translated to proper HTTP status
  codes.
* Structured logging as well as audit events are emitted for traceability.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    Security,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, constr, validator

# --------------------------------------------------------------------------- #
# Service-layer imports (domain & adapters)                                   #
# --------------------------------------------------------------------------- #
try:
    from crowdpay_connect.services.user_service.domain.services import (
        UserService,
        UserServiceError,
    )
except ModuleNotFoundError:
    # The real service is available only inside the full project;
    # a minimal fallback is provided to keep this file self-contained
    class UserServiceError(Exception):
        """Base class for service-layer failures."""

    class _DummyUserService:
        async def create_user(self, *_a, **_kw):  # noqa: D401,E501
            raise NotImplementedError("UserService backend not configured")

        async def get_user(self, *_a, **_kw):
            raise NotImplementedError()

        async def update_user(self, *_a, **_kw):
            raise NotImplementedError()

        async def search_users(self, *_a, **_kw):
            raise NotImplementedError()

        async def get_kyc_status(self, *_a, **_kw):
            raise NotImplementedError()

        async def trigger_kyc_verification(self, *_a, **_kw):
            raise NotImplementedError()

    UserService = _DummyUserService  # type: ignore[assignment]

# --------------------------------------------------------------------------- #
# FastAPI router & dependencies                                               #
# --------------------------------------------------------------------------- #

logger = logging.getLogger("crowdpay.user_api.v1")
router = APIRouter(prefix="/api/v1/users", tags=["Users"])
bearer_scheme = HTTPBearer(auto_error=False)


async def get_user_service() -> UserService:  # noqa: D401
    """
    Dependency-provider for :class:`UserService`.

    In production this might pull from a DI container, create a Unit-of-Work
    per request, etc.
    """
    return UserService()  # type: ignore[call-arg]


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
    service: UserService = Depends(get_user_service),
):
    """
    Resolve & return the authenticated user from a JWT access-token.

    The actual JWT verification is delegated to the service-layer.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid credentials",
        )

    try:
        return await service.authenticate_token(credentials.credentials)
    except UserServiceError as exc:  # pragma: no cover
        logger.warning("Token authentication failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc


# --------------------------------------------------------------------------- #
# Pydantic schemas                                                            #
# --------------------------------------------------------------------------- #


class BaseUserModel(BaseModel):
    """Common fields shared by several schemas."""

    email: EmailStr = Field(..., example="jane.doe@example.com")
    first_name: constr(strip_whitespace=True, min_length=1, max_length=50)  # noqa: D401
    last_name: constr(strip_whitespace=True, min_length=1, max_length=50)

    @validator("first_name", "last_name")
    def title_case(cls, v: str) -> str:  # noqa: D401
        return v.title()

    class Config:
        orm_mode = True
        anystr_strip_whitespace = True
        validate_assignment = True
        schema_extra = {
            "example": {
                "email": "jane.doe@example.com",
                "first_name": "Jane",
                "last_name": "Doe",
            }
        }


class UserCreateRequest(BaseUserModel):
    """
    Payload for creating a brand-new user.

    Password rules would normally be stricter and validated elsewhere.
    """

    password: constr(min_length=8, max_length=128)  # noqa: D401
    referral_code: Optional[constr(max_length=15)] = Field(
        None, description="Optional referral code"
    )


class UserUpdateRequest(BaseModel):
    """Partial update (PATCH semantics)."""

    first_name: Optional[
        constr(strip_whitespace=True, min_length=1, max_length=50)
    ] = None
    last_name: Optional[
        constr(strip_whitespace=True, min_length=1, max_length=50)
    ] = None

    class Config:
        anystr_strip_whitespace = True
        validate_assignment = True
        schema_extra = {
            "example": {
                "first_name": "Janet",
                "last_name": "Dough",
            }
        }


class UserResponse(BaseUserModel):
    """Canonical representation returned by the API."""

    id: UUID
    created_at: datetime
    updated_at: datetime
    is_active: bool
    kyc_verified: bool


class KYCStatusResponse(BaseModel):
    """Represents the KYC status for a given user."""

    user_id: UUID
    status: str = Field(
        ...,
        description=(
            "Enum of <PENDING|VERIFIED|DECLINED|RETRY_REQUIRED|NOT_REQUESTED>"
        ),
        example="VERIFIED",
    )
    last_updated: datetime


# --------------------------------------------------------------------------- #
# Endpoint implementations                                                    #
# --------------------------------------------------------------------------- #


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
    summary="Create a new user account",
)
async def create_user(
    payload: UserCreateRequest,
    request: Request,
    service: UserService = Depends(get_user_service),
):
    """
    Register a brand-new user.

    The service-layer returns a fully-populated domain object which is
    serialised automatically by Pydantic.
    """
    client_ip = request.client.host if request.client else "unknown"
    logger.info("Attempting user creation from %s (%s)", client_ip, payload.email)

    try:
        user = await service.create_user(
            email=payload.email,
            first_name=payload.first_name,
            last_name=payload.last_name,
            password=payload.password,
            referral_code=payload.referral_code,
            source_ip=client_ip,
        )
    except UserServiceError as exc:
        logger.exception("User creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    logger.info("User %s created successfully", user.id)
    return user


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Retrieve user by ID",
)
async def get_user(
    user_id: UUID = Path(..., description="User ID"),
    _current_user=Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    """Return a single user identified by `user_id`."""
    try:
        user = await service.get_user(user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user
    except UserServiceError as exc:  # pragma: no cover
        logger.error("Service error while fetching user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Internal service error") from exc


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    summary="Update an existing user account",
)
async def update_user(
    user_id: UUID = Path(..., description="User ID"),
    payload: UserUpdateRequest | None = None,
    _current_user=Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    """
    Mutate user data.

    Only non-null attributes in the payload will be updated.
    """
    if payload is None or not payload.dict(exclude_unset=True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No update data provided",
        )

    try:
        user = await service.update_user(user_id, **payload.dict(exclude_unset=True))
        return user
    except UserServiceError as exc:
        logger.warning("Failed updating user %s: %s", user_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "",
    response_model=List[UserResponse],
    summary="Search & filter users",
)
async def search_users(  # noqa: WPS211
    q: Optional[str] = Query(None, description="Free-text search"),
    is_active: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    _current_user=Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    """
    Return a paginated list of users matching the given criteria.
    """
    try:
        return await service.search_users(
            query=q,
            is_active=is_active,
            page=page,
            per_page=per_page,
        )
    except UserServiceError as exc:  # pragma: no cover
        logger.error("User search failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal service error") from exc


@router.get(
    "/{user_id}/kyc",
    response_model=KYCStatusResponse,
    summary="Get KYC status",
)
async def get_kyc_status(
    user_id: UUID = Path(...),
    _current_user=Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    """
    Retrieve the current KYC verification status for a user.
    """
    try:
        return await service.get_kyc_status(user_id)
    except UserServiceError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail="User not found") from exc
        logger.error("KYC status retrieval failed for %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Internal service error") from exc


@router.post(
    "/{user_id}/kyc/verify",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger KYC verification",
)
async def trigger_kyc_verification(
    response: Response,
    user_id: UUID = Path(...),
    _current_user=Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    """
    Start (or re-start) the asynchronous KYC verification process.

    The endpoint is async-friendly: it enqueues a background task and
    immediately returns 202 ACCEPTED with a `Location` header pointing to
    the KYC status URL.
    """
    try:
        await service.trigger_kyc_verification(user_id)
    except UserServiceError as exc:
        logger.warning("Unable to trigger KYC for %s: %s", user_id, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # HATEOAS: tell the client where to poll
    response.headers["Location"] = f"/api/v1/users/{user_id}/kyc"
    return {"detail": "KYC verification initiated", "user_id": user_id}


# --------------------------------------------------------------------------- #
# Health-check (optional)                                                     #
# --------------------------------------------------------------------------- #


@router.get(
    "/health",
    summary="Lightweight health-check for the User API",
    include_in_schema=False,
)
async def health_check():
    """
    Return a static JSON indicating the service is reachable.

    This is used by orchestrators (K8s, Docker Swarm, etc.) for liveness /
    readiness probes.
    """
    return {
        "service": "user_service",
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "instance_id": str(uuid4())[:8],  # Helps spotting cache/proxy issues
    }
```