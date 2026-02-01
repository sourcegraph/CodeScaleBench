```python
"""
crowdpay_connect/services/user_service/app/repositories/user_repository.py

Repository layer for the User aggregate root. Encapsulates all persistence-
related concerns for the user domain while surfacing a clean API to the
application-service layer (a.k.a. “use-cases”).

Implemented with:
  • SQLAlchemy 2.0 async API
  • Optional Redis read-through caching
  • Outbox-style event dispatching (event‐sourced architecture)

Author: CrowdPay Connect Core Team
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import List, Optional

from redis.asyncio import Redis
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events.dispatcher import EventDispatcher
from app.events.user_events import (
    UserCreatedEvent,
    UserDeletedEvent,
    UserUpdatedEvent,
    UserVerifiedEvent,
)
from app.exceptions import DatabaseExecutionError, DuplicateUserError, UserNotFoundError
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.utils.time import utcnow

_logger = logging.getLogger(__name__)


class UserRepository:
    """
    Persistence gateway for the User aggregate.

    NOTE:
        The repository isolates the domain layer from the underlying
        infrastructure (DB, cache, message broker, etc.).  Nothing outside of
        this package should know *how* users are stored or retrieved.
    """

    _CACHE_TTL_SECONDS = 60 * 5  # 5-minute sliding window

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        dispatcher: EventDispatcher,
        cache: Optional[Redis] = None,
    ) -> None:
        self._session_factory = session_factory
        self._dispatcher = dispatcher
        self._cache = cache

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    async def create_user(self, payload: UserCreate) -> User:
        """
        Persist a newly registered user and publish an integration event.
        """
        user = User(
            id=uuid.uuid4(),
            email=payload.email.lower(),
            full_name=payload.full_name,
            locale=payload.locale or "en_US",
            country_code=payload.country_code,
            hashed_password=payload.hashed_password,
            kyc_status="PENDING",
            reputation_score=0,
            is_active=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )

        async with self._session_factory() as session:
            session.add(user)
            try:
                await session.commit()
            except IntegrityError as exc:  # unique-constraint on email
                await session.rollback()
                _logger.debug("User creation failed: duplicate email (%s)", user.email)
                raise DuplicateUserError(f"Email '{user.email}' is already registered") from exc
            except SQLAlchemyError as exc:
                await session.rollback()
                _logger.exception("Unhandled SQL error during user create")
                raise DatabaseExecutionError("Failed to create a new user") from exc

        await self._dispatcher.publish(UserCreatedEvent(user_id=user.id))
        await self._cache_user(user)
        return user

    async def get_user_by_id(self, user_id: uuid.UUID, *, use_cache: bool = True) -> User:
        """
        Retrieve a user by primary key (UUID). Raises UserNotFoundError when not found.
        """
        if use_cache and (cached := await self._fetch_user_from_cache(user_id)):
            return cached

        async with self._session_factory() as session:
            stmt = select(User).where(User.id == user_id, User.is_active.is_(True))
            result = await session.execute(stmt)
            user: Optional[User] = result.scalar_one_or_none()

        if not user:
            raise UserNotFoundError(f"User with id '{user_id}' does not exist")

        await self._cache_user(user)
        return user

    async def get_user_by_email(self, email: str) -> User:
        """
        Case-insensitive lookup by e-mail address.
        """
        email = email.lower()

        async with self._session_factory() as session:
            stmt = select(User).where(User.email == email, User.is_active.is_(True))
            result = await session.execute(stmt)
            user: Optional[User] = result.scalar_one_or_none()

        if not user:
            raise UserNotFoundError(f"User with email '{email}' does not exist")

        await self._cache_user(user)
        return user

    async def list_users(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        country_code: Optional[str] = None,
    ) -> List[User]:
        """
        Return a page of users; optionally filtered by country.
        """
        async with self._session_factory() as session:
            stmt = select(User).where(User.is_active.is_(True))
            if country_code:
                stmt = stmt.where(User.country_code == country_code.upper())
            stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_user(self, user_id: uuid.UUID, payload: UserUpdate) -> User:
        """
        Update mutable fields for a given user.
        """
        async with self._session_factory() as session:
            stmt = (
                update(User)
                .where(User.id == user_id, User.is_active.is_(True))
                .values(
                    full_name=payload.full_name,
                    locale=payload.locale,
                    updated_at=utcnow(),
                )
                .returning(User)
            )
            try:
                result = await session.execute(stmt)
                await session.commit()
            except SQLAlchemyError as exc:
                await session.rollback()
                _logger.exception("Unhandled SQL error during user update")
                raise DatabaseExecutionError("Failed to update user") from exc

        user: Optional[User] = result.scalar_one_or_none()
        if not user:
            raise UserNotFoundError(f"User with id '{user_id}' does not exist")

        await self._invalidate_cache(user_id)
        await self._dispatcher.publish(UserUpdatedEvent(user_id=user_id))
        return user

    async def soft_delete_user(self, user_id: uuid.UUID) -> None:
        """
        Mark user inactive (soft delete) to preserve referential integrity.
        """
        async with self._session_factory() as session:
            stmt = (
                update(User)
                .where(User.id == user_id, User.is_active.is_(True))
                .values(is_active=False, updated_at=utcnow())
            )
            try:
                result = await session.execute(stmt)
                await session.commit()
            except SQLAlchemyError as exc:
                await session.rollback()
                _logger.exception("Unhandled SQL error during user delete")
                raise DatabaseExecutionError("Failed to delete user") from exc

        if result.rowcount == 0:
            raise UserNotFoundError(f"User with id '{user_id}' does not exist")

        await self._invalidate_cache(user_id)
        await self._dispatcher.publish(UserDeletedEvent(user_id=user_id))

    async def mark_user_verified(
        self, *, user_id: uuid.UUID, kyc_reference: str, risk_score: int
    ) -> User:
        """
        Confirm that user has passed external KYC/AML checks and assign initial risk score.
        """
        async with self._session_factory() as session:
            stmt = (
                update(User)
                .where(User.id == user_id, User.is_active.is_(True))
                .values(
                    kyc_status="VERIFIED",
                    kyc_reference=kyc_reference,
                    risk_score=risk_score,
                    updated_at=utcnow(),
                )
                .returning(User)
            )
            try:
                result = await session.execute(stmt)
                await session.commit()
            except SQLAlchemyError as exc:
                await session.rollback()
                _logger.exception("Unhandled SQL error during user verification")
                raise DatabaseExecutionError("Failed to verify user") from exc

        user: Optional[User] = result.scalar_one_or_none()
        if not user:
            raise UserNotFoundError(f"User with id '{user_id}' does not exist")

        await self._invalidate_cache(user_id)
        await self._dispatcher.publish(
            UserVerifiedEvent(user_id=user_id, kyc_reference=kyc_reference)
        )
        return user

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    async def _cache_user(self, user: User) -> None:
        if not self._cache:
            return

        key = self._cache_key(user.id)
        try:
            await self._cache.setex(
                key,
                self._CACHE_TTL_SECONDS,
                json.dumps(user.to_dict(), default=str),
            )
        except Exception:  # pragma: no cover
            _logger.debug("Unable to cache user (%s)", user.id, exc_info=True)

    async def _fetch_user_from_cache(self, user_id: uuid.UUID) -> Optional[User]:
        if not self._cache:
            return None

        key = self._cache_key(user_id)
        try:
            raw = await self._cache.get(key)
            if not raw:
                return None
            data = json.loads(raw)
            return User.from_dict(data)  # type: ignore[arg-type]
        except Exception:  # pragma: no cover
            _logger.debug("Unable to deserialize cached user (%s)", user_id, exc_info=True)
            return None

    async def _invalidate_cache(self, user_id: uuid.UUID) -> None:
        if not self._cache:
            return

        key = self._cache_key(user_id)
        try:
            await self._cache.delete(key)
        except Exception:  # pragma: no cover
            _logger.debug("Unable to invalidate cache (%s)", user_id, exc_info=True)

    @staticmethod
    def _cache_key(user_id: uuid.UUID) -> str:  # noqa: D401
        """Reduces collision risk by explicitly scoping the cache namespace."""
        return f"user:{user_id}"
```