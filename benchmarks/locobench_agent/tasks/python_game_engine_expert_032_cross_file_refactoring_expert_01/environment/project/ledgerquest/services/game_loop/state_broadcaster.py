```python
"""
ledgerquest.services.game_loop.state_broadcaster
================================================

Server-side helper responsible for propagating the latest frame / turn / tick
state to interested recipients in a **serverless** deployment of LedgerQuest.
The broadcaster fulfils two primary duties:

1.  Real-time fan-out over API Gateway WebSocket connections so browsers or
    native clients can immediately reflect authoritative world state.

2.  System-level publication to EventBridge so autonomous services
    (metering, audit, AI-workers, etc.) can asynchronously react to or
    persist the same state change without tight coupling to the game-loop
    Lambda.

The implementation purposefully avoids long-lived state and is therefore
safe to be executed in parallel across multiple Lambda invocations that take
part in a distributed game loop orchestrated by AWS Step Functions.

Any public method can be unit-tested offline; for integration tests, the
`BROADCAST_MOCK_MODE` environment variable can be set to `"true"` so that no
real AWS calls are made.

Author: LedgerQuest Engineering Team
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import partial
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError
from boto3.dynamodb.types import TypeSerializer  # For loss-less Dynamo-style JSON

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
_LOGGER = logging.getLogger("ledgerquest.state_broadcaster")
_LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


# -----------------------------------------------------------------------------
# Serializer helpers
# -----------------------------------------------------------------------------
class _ExtendedJSONEncoder(json.JSONEncoder):
    """JSONEncoder that understands Decimal, datetimes and bytes."""

    def default(self, o: Any) -> Any:  # noqa: D401
        if isinstance(o, Decimal):
            if o % 1 == 0:
                return int(o)
            return float(o)
        if isinstance(o, (datetime,)):
            return o.isoformat()
        if isinstance(o, (bytes, bytearray)):
            return o.decode("utf-8")
        return super().default(o)


def _to_json(data: Mapping[str, Any]) -> str:
    """Serialize world state to canonical JSON string."""
    return json.dumps(data, cls=_ExtendedJSONEncoder, separators=(",", ":"))


# -----------------------------------------------------------------------------
#   Models
# -----------------------------------------------------------------------------
@dataclass
class BroadcastResult:
    """Aggregated outcome of a broadcast attempt."""

    attempted_connection_count: int = 0
    failed_connection_ids: List[str] | None = None
    eventbridge_event_id: Optional[str] = None
    duration_ms: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "attemptedConnections": self.attempted_connection_count,
            "failedConnectionIds": self.failed_connection_ids or [],
            "eventId": self.eventbridge_event_id,
            "durationMs": round(self.duration_ms, 2),
        }


# -----------------------------------------------------------------------------
#   Core broadcaster
# -----------------------------------------------------------------------------
class StateBroadcaster:
    """
    Fan-out helper for world state updates.

    Parameters
    ----------
    event_bus_name:
        Name of the EventBridge bus that should receive a system-level
        `WorldStateUpdated` event.
    websocket_api_id:
        API Gateway WebSocket API identifier (the **API ID**, not the full URL).
    region_name:
        AWS region for both EventBridge and API Gateway Management API.
    """

    # AWS WebSockets limit is 128 KB per message. We stay well under to allow
    # some encoding overhead.
    _MAX_WS_PAYLOAD_BYTES: int = 120 * 1024

    def __init__(
        self,
        *,
        event_bus_name: str,
        websocket_api_id: str,
        region_name: str = "us-east-1",
    ) -> None:
        self._event_bus_name = event_bus_name
        self._ws_api_id = websocket_api_id
        self._region = region_name

        # Boto3 clients are created lazily so that unit tests can monkey-patch
        # `boto3.client` before first use.
        self._event_bridge = None
        self._apigw_mgmt = None

        # Flag to disable external calls during local tests or CI.
        self._mock_mode: bool = os.getenv("BROADCAST_MOCK_MODE", "false").lower() == "true"

    # ---------------------------------------------------------------------
    #   Public helpers
    # ---------------------------------------------------------------------
    def broadcast(
        self,
        *,
        world_state: Mapping[str, Any],
        connection_ids: List[str],
        tenant_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> BroadcastResult:
        """
        Broadcast the provided `world_state` to connected players plus EventBridge.

        The method is synchronous **but** uses a thread-pool internally for
        concurrent WebSocket writes to reduce the tail latency of large fan-outs.
        """
        started = time.perf_counter()

        serialised_state: str = _to_json(world_state)
        serialised_size = len(serialised_state.encode("utf-8"))
        if serialised_size > self._MAX_WS_PAYLOAD_BYTES:
            # The state is too large to be sent in a single WebSocket frame.
            raise ValueError(
                f"Serialised state is {serialised_size / 1024:.1f} KB, "
                f"which exceeds the maximum allowed payload size of "
                f"{self._MAX_WS_PAYLOAD_BYTES / 1024} KB."
            )

        _LOGGER.debug(
            "Broadcasting frame for tenant %s to %s connection(s). Payload ≈ %.1f KB",
            tenant_id,
            len(connection_ids),
            serialised_size / 1024,
        )

        failed_ws_ids: List[str] = self._fan_out_websocket(
            payload=serialised_state,
            connection_ids=connection_ids,
        )
        event_id: Optional[str] = self._publish_eventbridge(
            tenant_id=tenant_id,
            world_state=world_state,
            metadata=metadata or {},
        )

        elapsed_ms = (time.perf_counter() - started) * 1000

        result = BroadcastResult(
            attempted_connection_count=len(connection_ids),
            failed_connection_ids=failed_ws_ids,
            eventbridge_event_id=event_id,
            duration_ms=elapsed_ms,
        )
        _LOGGER.info("State broadcast completed: %s", result.as_dict())
        return result

    # ------------------------------------------------------------------
    #   AWS resource accessors (lazily created)
    # ------------------------------------------------------------------
    @property
    def _eventbridge(self):
        if self._event_bridge is None:
            if self._mock_mode:
                self._event_bridge = _MockBoto3Client("events")  # type: ignore[arg-type]
            else:
                self._event_bridge = boto3.client(
                    "events",
                    region_name=self._region,
                    config=Config(retries={"max_attempts": 3, "mode": "standard"}),
                )
        return self._event_bridge

    @property
    def _apigw_management(self):
        if self._apigw_mgmt is None:
            if self._mock_mode:
                self._apigw_mgmt = _MockBoto3Client("apigw-managementapi")  # type: ignore[arg-type]
            else:
                endpoint = f"https://{self._ws_api_id}.execute-api.{self._region}.amazonaws.com/prod"
                self._apigw_mgmt = boto3.client(
                    "apigw-managementapi",
                    region_name=self._region,
                    endpoint_url=endpoint,
                    config=Config(retries={"max_attempts": 3, "mode": "standard"}),
                )
        return self._apigw_mgmt

    # ------------------------------------------------------------------
    #   EventBridge publication
    # ------------------------------------------------------------------
    def _publish_eventbridge(
        self,
        *,
        tenant_id: str,
        world_state: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> Optional[str]:
        """Publish a `WorldStateUpdated` event to EventBridge."""
        if self._mock_mode:
            _LOGGER.debug("[mock] Skipping EventBridge publish.")
            return "mock-event-id"

        envelope = {
            "id": world_state.get("tick") or int(time.time() * 1000),
            "timestamp": datetime.utcnow().isoformat(),
            "tenantId": tenant_id,
            "worldState": world_state,
            "meta": metadata,
        }

        try:
            response = self._eventbridge.put_events(
                Entries=[
                    {
                        "Source": "ledgerquest.game-loop",
                        "DetailType": "WorldStateUpdated",
                        "Detail": json.dumps(envelope, cls=_ExtendedJSONEncoder),
                        "EventBusName": self._event_bus_name,
                        "Time": datetime.utcnow(),
                    }
                ]
            )
            event_id = (response.get("Entries") or [{}])[0].get("EventId")
            _LOGGER.debug("Published EventBridge world-state event %s", event_id)
            return event_id
        except ClientError as exc:
            _LOGGER.error("Failed to publish EventBridge event: %s", exc, exc_info=True)
        return None

    # ------------------------------------------------------------------
    #   WebSocket fan-out
    # ------------------------------------------------------------------
    def _fan_out_websocket(
        self,
        *,
        payload: str,
        connection_ids: List[str],
        batch_size: int = 50,
    ) -> List[str]:
        """
        Post the serialized world state to each `connection_id`.

        AWS API Gateway Management API has a soft concurrency limit; we therefore
        chunk long lists into batches. Fan-out is executed via a ThreadPool to
        maximise throughput without exhausting Lambda CPU allocation.
        """
        if self._mock_mode:
            _LOGGER.debug("[mock] Skipping WebSocket fan-out.")
            return []

        # Trim whitespace / encoding once instead of each invocation.
        prepared_payload: bytes = payload.encode("utf-8")

        failed_ids: List[str] = []
        work = [
            connection_ids[i : i + batch_size]  # noqa: E203
            for i in range(0, len(connection_ids), batch_size)
        ]
        _LOGGER.debug(
            "Dispatching %d WebSocket batch(es) (batch size=%d).",
            len(work),
            batch_size,
        )

        with ThreadPoolExecutor(max_workers=min(32, len(work))) as executor:
            futures = [
                executor.submit(
                    self._post_to_connections,
                    prepared_payload,
                    sub_list,
                )
                for sub_list in work
            ]

            for fut in as_completed(futures):
                failed_ids.extend(fut.result())

        return failed_ids

    def _post_to_connections(
        self,
        payload: bytes,
        connection_ids: List[str],
    ) -> List[str]:
        """Helper for thread-pool: write to a slice of connections."""
        failed: List[str] = []
        for conn_id in connection_ids:
            try:
                self._apigw_management.post_to_connection(
                    Data=payload,
                    ConnectionId=conn_id,
                )
            except self._apigw_management.exceptions.GoneException:
                # Client disconnected—mark for removal by caller.
                failed.append(conn_id)
            except (ClientError, EndpointConnectionError) as exc:
                _LOGGER.warning(
                    "WebSocket write to %s failed: %s", conn_id, exc, exc_info=False
                )
                failed.append(conn_id)
        return failed


# -----------------------------------------------------------------------------
#   Lambda entry-point
# -----------------------------------------------------------------------------
def lambda_handler(event: Dict[str, Any], _context) -> Dict[str, Any]:
    """
    Lambda adapter for AWS Step Functions.

    The incoming `event` is expected to follow this contract:

    {
        "tenantId": "acme-supply-chain",
        "worldState": { ... ECS snapshot ... },
        "connectionIds": ["abc123", "def456"],
        "metadata": {         # optional
            "frameDuration": 16,
            "instanceId": "game-7",
            ...
        }
    }

    The method returns the input enriched with broadcast metrics so that
    subsequent Step Functions tasks (e.g., metrics or cleanup) can make
    informed decisions.
    """
    _LOGGER.debug("Lambda invoked with event: %s", event)

    missing_keys = [k for k in ("tenantId", "worldState", "connectionIds") if k not in event]
    if missing_keys:
        raise KeyError(f"Missing keys in input event: {', '.join(missing_keys)}")

    broadcaster = StateBroadcaster(
        event_bus_name=os.environ["EVENT_BUS_NAME"],
        websocket_api_id=os.environ["WEBSOCKET_API_ID"],
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )

    result = broadcaster.broadcast(
        world_state=event["worldState"],
        connection_ids=event["connectionIds"],
        tenant_id=event["tenantId"],
        metadata=event.get("metadata") or {},
    )

    # Merge broadcast result back so SFN can inspect
    enriched_event: Dict[str, Any] = dict(event)  # shallow copy
    enriched_event["broadcastMetrics"] = result.as_dict()
    return enriched_event


# -----------------------------------------------------------------------------
#   Internal mocks for offline testing
# -----------------------------------------------------------------------------
class _MockBoto3Client:
    """Very lightweight stub to replace boto3 clients in unit tests."""

    def __init__(self, service_name: str):
        self._service = service_name

    # ---- EventBridge ----
    def put_events(self, Entries: List[Dict[str, Any]]) -> Dict[str, Any]:  # noqa: N803
        _LOGGER.debug("[mock] EventBridge.put_events(%s)", Entries)
        return {"Entries": [{"EventId": "mock-id"}]}

    # ---- APIGW Management ----
    class exceptions:  # noqa: D401  # pylint: disable=too-few-public-methods
        class GoneException(Exception):
            """Raised when connection no longer exists."""

    def post_to_connection(self, *, Data: bytes, ConnectionId: str):  # noqa: N803
        _LOGGER.debug("[mock] post_to_connection(ConnectionId=%s, bytes=%d)", ConnectionId, len(Data))
        if ConnectionId.startswith("gone"):
            # Simulate stale connection
            raise self.exceptions.GoneException("Stale connection")

    # Fallback for any other attribute access
    def __getattr__(self, item):
        raise AttributeError(f"_MockBoto3Client has no attribute '{item}'")
```