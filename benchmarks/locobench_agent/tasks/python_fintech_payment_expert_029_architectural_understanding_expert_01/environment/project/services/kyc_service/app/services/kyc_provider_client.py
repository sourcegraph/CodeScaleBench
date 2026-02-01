```python
"""
crowdpay_connect.services.kyc_service.app.services.kyc_provider_client

Adapter-facing client that brokers communication between CrowdPay’s KYC
domain layer and one or more third-party KYC vendors (e.g., Onfido,
Trulioo).  The client is intentionally opinionated:

1.  All outbound calls are asynchronous and wrapped in a resilient retry
   policy (exponential back-off w/ jitter).
2. Non-deterministic provider responses are normalised into a common
   internal model (KYCVerificationResult).
3. All significant events are immediately pushed onto the local event bus
   for downstream handlers (Event Sourcing, CQRS read models, etc.).

The module is **provider-agnostic**  – concrete HTTP mechanics live in
pluggable “adapter” classes that implement `BaseProviderAdapter`.
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Mapping, MutableMapping, Optional, Type

import httpx
import pydantic
import tenacity
from pydantic import BaseSettings, Field

# --------------------------------------------------------------------------- #
# Logging & Tracing setup
# --------------------------------------------------------------------------- #
logger = logging.getLogger("crowdpay.kyc")
logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
class RuntimeSettings(BaseSettings):
    """
    Runtime configuration for the KYC provider client.  Values can be
    supplied from .env files, environment variables, docker-secrets, etc.
    """

    kyc_provider: str = Field(
        ...,
        env="KYC_PROVIDER",
        description="Identifier of the primary KYC provider "
        "(e.g. 'onfido', 'trulioo').",
    )
    # Onfido
    onfido_api_key: Optional[str] = Field(None, env="ONFIDO_API_KEY")
    onfido_base_url: str = Field(
        "https://api.eu.onfido.com/v3.5", env="ONFIDO_BASE_URL"
    )

    # Trulioo
    trulioo_api_key: Optional[str] = Field(None, env="TRULIOO_API_KEY")
    trulioo_base_url: str = Field(
        "https://gateway.trulioo.com/trial", env="TRULIOO_BASE_URL"
    )

    # Generic HTTP behaviour
    request_timeout_secs: float = Field(10.0, env="KYC_HTTP_TIMEOUT_SECS")
    max_retries: int = Field(3, env="KYC_HTTP_MAX_RETRIES")
    retry_base_backoff_secs: float = Field(0.25, env="KYC_HTTP_RETRY_BACKOFF")

    class Config:
        extra = "ignore"


settings = RuntimeSettings()  # Singleton-ish


# --------------------------------------------------------------------------- #
# Domain models
# --------------------------------------------------------------------------- #
class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class KYCVerificationResult:
    provider: str
    reference_id: str  # internal provider id
    status: VerificationStatus
    risk_score: Optional[float]  # 0-100, where 100 == high risk
    raw: Mapping[str, Any]  # Unmodified provider response payload


@dataclass(frozen=True)
class KYCVerificationRequest:
    """
    Minimal subset of attributes that the CrowdPay KYC domain requires.

    NOTE: In a real implementation, this would be far richer, contain document
    bytes, device fingerprints, selfies, AML flags, etc.
    """

    user_id: str
    first_name: str
    last_name: str
    dob: str  # ISO date
    address: str


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #
class KYCProviderError(Exception):
    """Base class for all provider-level errors."""


class KYCTransientError(KYCProviderError):
    """Raised for temporary / recoverable problems (network, 5xx, etc.)."""


class KYCConfigError(KYCProviderError):
    """Mis-configuration detected at runtime."""


class KYCNotFoundError(KYCProviderError):
    """Verification, user, or resource could not be located."""


# --------------------------------------------------------------------------- #
# Provider adapter definitions
# --------------------------------------------------------------------------- #
class BaseProviderAdapter(abc.ABC):
    """
    A small subset of functions that every KYC provider adapter must expose.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        settings: RuntimeSettings,
    ) -> None:
        self._client = client
        self._settings = settings

    @property
    @abc.abstractmethod
    def name(self) -> str:  # noqa: D401
        """Human-friendly provider name."""

    # --------------------------------------------------------------------- #
    # Main API surface
    # --------------------------------------------------------------------- #
    @abc.abstractmethod
    async def submit_verification(
        self, payload: KYCVerificationRequest
    ) -> KYCVerificationResult:
        """
        Submit a new verification request to the vendor.
        """

    @abc.abstractmethod
    async def fetch_verification(
        self, reference_id: str
    ) -> KYCVerificationResult:
        """
        Retrieve the latest status of a verification previously submitted.
        """

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #
    def _http_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            settings.request_timeout_secs,
            connect=settings.request_timeout_secs,
            read=settings.request_timeout_secs,
            write=settings.request_timeout_secs,
        )

    @staticmethod
    def _retry_policy() -> tenacity.AsyncRetrying:
        """
        Common retry policy for flaky external services.
        """
        return tenacity.AsyncRetrying(
            reraise=True,
            stop=tenacity.stop_after_attempt(settings.max_retries),
            wait=tenacity.wait_exponential(
                multiplier=settings.retry_base_backoff_secs
            )
            + tenacity.wait_random(0, 0.250),
            retry=tenacity.retry_if_exception_type(KYCTransientError),
            before_sleep=lambda retry_state: logger.warning(
                "Transient error when calling KYC provider: %s. Retrying %d/%d",
                retry_state.outcome.exception(),
                retry_state.attempt_number,
                settings.max_retries,
            ),
        )


# --------------------------------------------------------------------------- #
# Concrete provider implementations
# --------------------------------------------------------------------------- #
class OnfidoAdapter(BaseProviderAdapter):
    @property
    def name(self) -> str:  # noqa: D401
        return "onfido"

    # ------------------------------------------- #
    async def submit_verification(
        self, payload: KYCVerificationRequest
    ) -> KYCVerificationResult:
        """
        POST /v3.5/checks
        https://documentation.onfido.com/#create-check
        """
        if not self._settings.onfido_api_key:
            raise KYCConfigError("ONFIDO_API_KEY is required")

        url = f"{self._settings.onfido_base_url}/checks"

        body = {
            "applicant": {
                "first_name": payload.first_name,
                "last_name": payload.last_name,
                "dob": payload.dob,
                "address": payload.address,
            },
            "report_names": ["document", "facial_similarity_photo"],
            "tags": [f"crowdpay:user:{payload.user_id}"],
        }

        headers = {
            "Authorization": f"Token token={self._settings.onfido_api_key}",
            "Content-Type": "application/json",
        }

        async for attempt in self._retry_policy():
            with attempt:
                try:
                    resp = await self._client.post(
                        url,
                        json=body,
                        headers=headers,
                        timeout=self._http_timeout(),
                    )
                except httpx.HTTPError as exc:  # network / DNS issues, etc.
                    logger.exception("Network error contacting Onfido")
                    raise KYCTransientError("network problem") from exc

                if 500 <= resp.status_code < 600:
                    raise KYCTransientError(
                        f"Onfido server error {resp.status_code}"
                    )

                if resp.status_code != 201:
                    logger.error(
                        "Onfido rejected verification (%s): %s",
                        resp.status_code,
                        resp.text,
                    )
                    raise KYCProviderError(
                        f"unexpected status code: {resp.status_code}"
                    )

        data = resp.json()
        verification_id = data["id"]

        return KYCVerificationResult(
            provider=self.name,
            reference_id=verification_id,
            status=VerificationStatus.PENDING,
            risk_score=None,
            raw=data,
        )

    # ------------------------------------------- #
    async def fetch_verification(
        self, reference_id: str
    ) -> KYCVerificationResult:
        url = f"{self._settings.onfido_base_url}/checks/{reference_id}"
        headers = {
            "Authorization": f"Token token={self._settings.onfido_api_key}",
            "Accept": "application/json",
        }

        async for attempt in self._retry_policy():
            with attempt:
                try:
                    resp = await self._client.get(
                        url, headers=headers, timeout=self._http_timeout()
                    )
                except httpx.HTTPError as exc:
                    raise KYCTransientError("network problem") from exc

                if resp.status_code == 404:
                    raise KYCNotFoundError(reference_id)
                if 500 <= resp.status_code < 600:
                    raise KYCTransientError(
                        f"Onfido server error {resp.status_code}"
                    )
                if resp.status_code != 200:
                    raise KYCProviderError(resp.text)

        data = resp.json()
        provider_status = data["status"]  # 'in_progress', 'complete', etc.

        status_map = {
            "in_progress": VerificationStatus.PENDING,
            "awaiting_data": VerificationStatus.PENDING,
            "completed": VerificationStatus.APPROVED
            if data.get("result") == "clear"
            else VerificationStatus.REJECTED,
        }

        return KYCVerificationResult(
            provider=self.name,
            reference_id=reference_id,
            status=status_map.get(provider_status, VerificationStatus.FAILED),
            risk_score=None,
            raw=data,
        )


class TruliooAdapter(BaseProviderAdapter):
    @property
    def name(self) -> str:  # noqa: D401
        return "trulioo"

    # ------------------------------------------- #
    async def submit_verification(
        self, payload: KYCVerificationRequest
    ) -> KYCVerificationResult:
        if not self._settings.trulioo_api_key:
            raise KYCConfigError("TRULIOO_API_KEY is required")

        url = f"{self._settings.trulioo_base_url}/verify"

        headers = {
            "x-trulioo-api-key": self._settings.trulioo_api_key,
            "Content-Type": "application/json",
        }

        body = {
            "AcceptTruliooTermsAndConditions": True,
            "CleansedAddress": False,
            "CallBackUrl": "",
            "ConfigurationName": "Identity Verification",
            "CountryCode": "US",  # For demo purposes
            "DataFields": {
                "PersonInfo": {
                    "FirstGivenName": payload.first_name,
                    "FirstSurName": payload.last_name,
                    "DayOfBirth": int(payload.dob.split("-")[2]),
                    "MonthOfBirth": int(payload.dob.split("-")[1]),
                    "YearOfBirth": int(payload.dob.split("-")[0]),
                },
                "Location": {
                    "BuildingNumber": "1",
                    "StreetName": payload.address,
                    "City": "Unknown",
                    "StateProvinceCode": "CA",
                    "PostalCode": "00000",
                },
            },
        }

        async for attempt in self._retry_policy():
            with attempt:
                try:
                    resp = await self._client.post(
                        url,
                        json=body,
                        headers=headers,
                        timeout=self._http_timeout(),
                    )
                except httpx.HTTPError as exc:
                    raise KYCTransientError("network problem") from exc

                if 500 <= resp.status_code < 600:
                    raise KYCTransientError(
                        f"Trulioo server error {resp.status_code}"
                    )
                if resp.status_code != 200:
                    raise KYCProviderError(
                        f"Trulioo error: ({resp.status_code}) {resp.text}"
                    )

        data = resp.json()
        transaction_id = data["TransactionID"]

        # Immediate result is often available synchronously for Trulioo
        match_status = data["Record"]["RecordStatus"]
        status = (
            VerificationStatus.APPROVED
            if match_status == "match"
            else VerificationStatus.REJECTED
        )

        # Simplistic risk score
        score = (
            0.0
            if status == VerificationStatus.APPROVED
            else random.uniform(50, 100)
        )

        return KYCVerificationResult(
            provider=self.name,
            reference_id=transaction_id,
            status=status,
            risk_score=score,
            raw=data,
        )

    # ------------------------------------------- #
    async def fetch_verification(
        self, reference_id: str
    ) -> KYCVerificationResult:
        url = (
            f"{self._settings.trulioo_base_url}/verify/"
            f"transaction/{reference_id}"
        )
        headers = {
            "x-trulioo-api-key": self._settings.trulioo_api_key,
            "Accept": "application/json",
        }

        async for attempt in self._retry_policy():
            with attempt:
                try:
                    resp = await self._client.get(
                        url, headers=headers, timeout=self._http_timeout()
                    )
                except httpx.HTTPError as exc:
                    raise KYCTransientError("network problem") from exc

                if resp.status_code == 404:
                    raise KYCNotFoundError(reference_id)
                if 500 <= resp.status_code < 600:
                    raise KYCTransientError(
                        f"Trulioo server error {resp.status_code}"
                    )
                if resp.status_code != 200:
                    raise KYCProviderError(resp.text)

        data = resp.json()
        match_status = data["Record"]["RecordStatus"]
        status = (
            VerificationStatus.APPROVED
            if match_status == "match"
            else VerificationStatus.REJECTED
        )

        return KYCVerificationResult(
            provider=self.name,
            reference_id=reference_id,
            status=status,
            risk_score=None,
            raw=data,
        )


# --------------------------------------------------------------------------- #
# Provider registry & client façade
# --------------------------------------------------------------------------- #
_ADAPTER_REGISTRY: Dict[str, Type[BaseProviderAdapter]] = {
    "onfido": OnfidoAdapter,
    "trulioo": TruliooAdapter,
}


class KYCProviderClient:
    """
    High-level façade used by the KYC domain service to interact with
    external vendors.  The client lazily instantiates the appropriate
    adapter based on runtime settings and caches HTTP connection pools.
    """

    def __init__(
        self,
        custom_settings: Optional[RuntimeSettings] = None,
    ) -> None:
        self._settings = custom_settings or settings

        adapter_cls = _ADAPTER_REGISTRY.get(self._settings.kyc_provider)
        if not adapter_cls:
            raise KYCConfigError(
                f"Unsupported KYC provider: {self._settings.kyc_provider}"
            )

        # Reuse HTTP connection pooling
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._settings.request_timeout_secs)
        )

        self._adapter: BaseProviderAdapter = adapter_cls(
            self._http_client, settings=self._settings
        )

    # --------------------------------------------------------------------- #
    # Public API wrappers
    # --------------------------------------------------------------------- #
    async def submit_verification(
        self, request: KYCVerificationRequest
    ) -> KYCVerificationResult:
        logger.info(
            "Submitting KYC verification for user=%s via %s",
            request.user_id,
            self._adapter.name,
        )
        result = await self._adapter.submit_verification(request)
        await self._publish_event("KYC_SUBMITTED", result)
        return result

    async def fetch_verification(
        self, reference_id: str
    ) -> KYCVerificationResult:
        logger.debug(
            "Fetching KYC status for reference=%s via %s",
            reference_id,
            self._adapter.name,
        )
        result = await self._adapter.fetch_verification(reference_id)
        await self._publish_event("KYC_STATUS_UPDATED", result)
        return result

    # ------------------------------------------------------------------ #
    # Infrastructure helpers
    # ------------------------------------------------------------------ #
    async def _publish_event(
        self, topic: str, payload: KYCVerificationResult
    ) -> None:
        """
        Very lightweight event bus stub.  In production this would forward
        to NATS, Kafka, RabbitMQ, or an internal event-sourcing publisher.
        """
        logger.info(
            "Event published topic=%s payload=%s",
            topic,
            json.dumps(
                {
                    "provider": payload.provider,
                    "reference_id": payload.reference_id,
                    "status": payload.status,
                    "risk_score": payload.risk_score,
                },
                default=str,
            ),
        )

    async def close(self) -> None:
        await self._http_client.aclose()

    # ------------------------------------------------------------------ #
    # Async context-manager helpers
    # ------------------------------------------------------------------ #
    async def __aenter__(self) -> "KYCProviderClient":  # noqa: D401
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]  # noqa: E501
        await self.close()


# --------------------------------------------------------------------------- #
# Demo / manual testing
# --------------------------------------------------------------------------- #
async def _demo() -> None:  # pragma: no cover
    """
    Very naive demo that submits and polls for a verification using the
    configured provider.  Run it with:

        KYC_PROVIDER=trulioo TRULIOO_API_KEY=xxx python -m kyc_provider_client
    """
    client = KYCProviderClient()
    req = KYCVerificationRequest(
        user_id="user_123",
        first_name="Alice",
        last_name="Liddell",
        dob="1985-06-30",
        address="42 Wonderland Ave",
    )

    async with client:
        submit_result = await client.submit_verification(req)
        logger.info("Submitted result=%s", submit_result)

        # Poll until non-pending or timeout
        max_wait_secs = 15
        start = time.time()
        while True:
            await asyncio.sleep(2)
            res = await client.fetch_verification(submit_result.reference_id)
            logger.info("Current status=%s", res.status)
            if res.status != VerificationStatus.PENDING:
                break
            if time.time() - start > max_wait_secs:
                logger.warning("Timed out waiting for KYC completion")
                break


if __name__ == "__main__":  # pragma: no cover
    # Basic stdout logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(asctime)s [%(name)s] %(message)s",
    )
    asyncio.run(_demo())
```