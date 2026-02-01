```python
"""
LedgerQuest Engine – Networking Sub-System
==========================================

connection_handler.py
---------------------

Implements a high-level façade around AWS API Gateway WebSocket connection
management.  The class is purposely decoupled from the underlying execution
environment (AWS Lambda, LocalStack, pytest) so that it can be used both
inside Lambda handlers **and** during offline integration tests.

Responsibilities
----------------
1. Persistently register / deregister connection-ids in DynamoDB.
2. Provide convenience helpers for targeted, group and broadcast messaging.
3. Transparently handle multi-tenant isolation and disconnect race-conditions.
4. Offer best-practice resiliency (retries, exponential back-off, structured
   logging).

The module is intentionally *stateless*; all long-lived state is stored inside
DynamoDB in keeping with LedgerQuest’s serverless philosophy.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from random import random
from typing import Any, Dict, Iterable, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError

# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------

_DEFAULT_DDB_TABLE = "ledgerquest_connection_registry"
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BACKOFF_BASE_SECONDS = 0.25          # initial back-off for retries
_DEFAULT_BROADCAST_CHUNK_SIZE = 100           # API Gateway Management API limit

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------------------
# Custom Exceptions
# --------------------------------------------------------------------------------------


class ConnectionError(Exception):
    """Generic connection handling failure."""


class TooManyRetries(ConnectionError):
    """Raised when exponential back-off is exhausted."""


# --------------------------------------------------------------------------------------
# Data Models
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConnectionRecord:
    """
    Lightweight representation of a single websocket connection.

    Attributes
    ----------
    connection_id: str
        The API Gateway connection id.
    tenant_id: str
        The tenant (organisation / customer) the player belongs to.
    player_id: str
        The logical player identifier in the game world.
    room_id: Optional[str]
        Optional game ‘room’ / ‘session’ the player is currently in.
    """
    connection_id: str
    tenant_id: str
    player_id: str
    room_id: Optional[str] = None

    @classmethod
    def from_ddb_item(cls, item: Dict[str, Any]) -> "ConnectionRecord":
        """Create a new ConnectionRecord from a DynamoDB item."""
        return cls(
            connection_id=item["connection_id"],
            tenant_id=item["tenant_id"],
            player_id=item["player_id"],
            room_id=item.get("room_id"),
        )

    def to_ddb_item(self) -> Dict[str, Any]:
        """Serialise this record to the DynamoDB attribute format."""
        item = {
            "connection_id": self.connection_id,
            "tenant_id": self.tenant_id,
            "player_id": self.player_id,
        }
        if self.room_id:
            item["room_id"] = self.room_id
        return item


# --------------------------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------------------------


def _exponential_backoff(attempt: int) -> float:
    """
    Calculate jittered exponential back-off duration.

    Parameters
    ----------
    attempt: int
        Zero-based attempt counter.

    Returns
    -------
    float
        Seconds to sleep.
    """
    base = _DEFAULT_BACKOFF_BASE_SECONDS * (2 ** attempt)
    # Full jitter – see AWS Architecture Blog:
    # https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
    return random() * base


def _get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set and no default exists"
        )
    return value


# --------------------------------------------------------------------------------------
# Core Handler
# --------------------------------------------------------------------------------------


class ConnectionHandler:
    """
    High-level utility for working with API Gateway WebSocket connections.

    The instance is cheap to create and is designed to be instantiated inside the
    Lambda handler on every cold / warm start.
    """

    # Region and endpoint are derived from the Lambda context via env-vars.
    def __init__(
        self,
        *,
        ddb_table_name: str = _DEFAULT_DDB_TABLE,
        aws_region: str | None = None,
        api_gateway_endpoint: str | None = None,
        http_timeout_seconds: int = 5,
    ) -> None:
        self._ddb_table_name = ddb_table_name

        aws_region = aws_region or _get_env("AWS_REGION", "us-east-1")

        # Build boto3 clients
        self._ddb = boto3.resource("dynamodb", region_name=aws_region)
        self._table = self._ddb.Table(self._ddb_table_name)

        endpoint_override = (
            api_gateway_endpoint
            or _build_apigw_management_endpoint(
                _get_env("APIGW_DOMAIN"), _get_env("APIGW_STAGE")
            )
        )

        self._apigw = boto3.client(
            "apigatewaymanagementapi",
            region_name=aws_region,
            endpoint_url=endpoint_override,
            config=Config(read_timeout=http_timeout_seconds, retries={"max_attempts": 0}),
        )

        logger.debug(
            "ConnectionHandler initialised – DDB table=%s, API endpoint=%s",
            self._ddb_table_name,
            endpoint_override,
        )

    # ------------------------------------------------------------------
    # CRUD operations for the connection registry
    # ------------------------------------------------------------------

    def register_connection(self, record: ConnectionRecord) -> None:
        """
        Persist a new connection record in DynamoDB.

        Duplicate writes are safe because the primary key is the connection_id.
        """
        logger.info("Registering new connection %s for player %s", record.connection_id, record.player_id)
        attempt = 0
        while attempt <= _DEFAULT_MAX_RETRIES:
            try:
                self._table.put_item(
                    Item=record.to_ddb_item(),
                    ConditionExpression="attribute_not_exists(connection_id)",
                )
                return
            except self._table.meta.client.exceptions.ConditionalCheckFailedException:
                logger.warning("Connection %s already registered", record.connection_id)
                return
            except ClientError as exc:
                logger.error("Failed to register connection (%s) – %s", record.connection_id, exc)
                self._retry_or_raise(exc, attempt)
                attempt += 1

    def deregister_connection(self, connection_id: str) -> None:
        """
        Remove a connection record from DynamoDB.

        If the record doesn’t exist the operation is ignored.
        """
        logger.info("Deregistering connection %s", connection_id)
        attempt = 0
        while attempt <= _DEFAULT_MAX_RETRIES:
            try:
                self._table.delete_item(Key={"connection_id": connection_id})
                return
            except ClientError as exc:
                logger.error("Failed to deregister connection (%s) – %s", connection_id, exc)
                self._retry_or_raise(exc, attempt)
                attempt += 1

    def fetch_by_connection(self, connection_id: str) -> Optional[ConnectionRecord]:
        """Fetch a single record by its connection id."""
        try:
            response = self._table.get_item(Key={"connection_id": connection_id})
            item = response.get("Item")
            return ConnectionRecord.from_ddb_item(item) if item else None
        except ClientError as exc:
            logger.exception("Unable to read from DynamoDB: %s", exc)
            raise

    def fetch_by_player(self, tenant_id: str, player_id: str) -> List[ConnectionRecord]:
        """
        Return all websocket connections for a given player.

        A single player may have multiple concurrent connections (e.g. multiple
        browser tabs or devices).
        """
        # Requires a GSI on (tenant_id, player_id)
        logger.debug("Fetching connections for player '%s' (tenant '%s')", player_id, tenant_id)
        index_name = "by_tenant_player"
        try:
            response = self._table.query(
                IndexName=index_name,
                KeyConditionExpression="tenant_id = :t AND player_id = :p",
                ExpressionAttributeValues={":t": tenant_id, ":p": player_id},
            )
            return [ConnectionRecord.from_ddb_item(i) for i in response.get("Items", [])]
        except self._table.meta.client.exceptions.ResourceNotFoundException:
            logger.error(
                "DDB Global Secondary Index '%s' not found on table '%s'", index_name, self._ddb_table_name
            )
            return []
        except ClientError as exc:
            logger.exception("Query failure: %s", exc)
            return []

    def list_room_connections(self, room_id: str, tenant_id: str) -> List[ConnectionRecord]:
        """
        Return all connections currently inside a room.

        Relies on a GSI (tenant_id, room_id).
        """
        index_name = "by_tenant_room"
        try:
            response = self._table.query(
                IndexName=index_name,
                KeyConditionExpression="tenant_id = :t AND room_id = :r",
                ExpressionAttributeValues={":t": tenant_id, ":r": room_id},
            )
            return [ConnectionRecord.from_ddb_item(i) for i in response.get("Items", [])]
        except self._table.meta.client.exceptions.ResourceNotFoundException:
            logger.error(
                "DDB Global Secondary Index '%s' not found on table '%s'", index_name, self._ddb_table_name
            )
            return []
        except ClientError as exc:
            logger.exception("Query failure: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Messaging operations
    # ------------------------------------------------------------------

    def send(self, connection_id: str, payload: Dict[str, Any] | str | bytes) -> None:
        """
        Send a message to a **single** connection id.

        The payload will be serialised as JSON unless it’s already bytes/str.
        """
        attempt = 0
        data = self._encode_payload(payload)

        while attempt <= _DEFAULT_MAX_RETRIES:
            try:
                logger.debug("Sending payload to connection %s", connection_id)
                self._apigw.post_to_connection(ConnectionId=connection_id, Data=data)
                return
            except self._apigw.exceptions.GoneException:
                logger.info("Connection %s is gone – cleaning up", connection_id)
                self.deregister_connection(connection_id)
                return
            except ClientError as exc:
                logger.warning("Failed to send to %s – %s (attempt %d)", connection_id, exc, attempt)
                self._retry_or_raise(exc, attempt)
                attempt += 1
            except EndpointConnectionError as exc:
                logger.error("API endpoint unreachable – %s", exc)
                self._retry_or_raise(exc, attempt)
                attempt += 1

    def send_to_player(
        self, tenant_id: str, player_id: str, payload: Dict[str, Any] | str | bytes
    ) -> None:
        """Send a message to every active connection for a single player."""
        records = self.fetch_by_player(tenant_id, player_id)
        if not records:
            logger.debug("No active connections for player %s", player_id)
            return
        self._broadcast((r.connection_id for r in records), payload)

    def send_to_room(
        self, tenant_id: str, room_id: str, payload: Dict[str, Any] | str | bytes
    ) -> None:
        """Broadcast a message to everyone in a particular room."""
        records = self.list_room_connections(room_id, tenant_id)
        if not records:
            logger.debug("No active connections in room %s", room_id)
            return
        self._broadcast((r.connection_id for r in records), payload)

    def broadcast_global(
        self, payload: Dict[str, Any] | str | bytes, *, tenant_id: Optional[str] = None
    ) -> None:
        """
        Broadcast to **all** connections (optionally filter by tenant).

        Warning: consider rate-limits & costs when using this call.
        """
        scan_kwargs: Dict[str, Any] = {}
        if tenant_id:
            scan_kwargs["FilterExpression"] = "tenant_id = :t"
            scan_kwargs["ExpressionAttributeValues"] = {":t": tenant_id}

        logger.info("Initiating global broadcast%s", f" for tenant {tenant_id}" if tenant_id else "")
        records: List[ConnectionRecord] = []
        try:
            response = self._table.scan(**scan_kwargs)
            records.extend(response.get("Items", []))
            while response.get("LastEvaluatedKey"):
                response = self._table.scan(ExclusiveStartKey=response["LastEvaluatedKey"], **scan_kwargs)
                records.extend(response.get("Items", []))
        except ClientError as exc:
            logger.exception("Global scan failed: %s", exc)
            return

        self._broadcast((r["connection_id"] for r in records), payload)

    # ------------------------------------------------------------------
    # Helper internals
    # ------------------------------------------------------------------

    def _broadcast(self, connection_ids: Iterable[str], payload: Any) -> None:
        """
        Broadcast helper that sends to many connections concurrently while
        respecting the API Gateway 100 msg/sec/connection-id limit by chunking.
        """
        ids = list(connection_ids)
        if not ids:
            return

        data = self._encode_payload(payload)
        logger.info("Broadcasting to %d connections", len(ids))

        # Chunk because a single call must not exceed ~1 MB and for throttling
        for chunk_start in range(0, len(ids), _DEFAULT_BROADCAST_CHUNK_SIZE):
            chunk = ids[chunk_start : chunk_start + _DEFAULT_BROADCAST_CHUNK_SIZE]
            with ThreadPoolExecutor(max_workers=len(chunk)) as executor:
                futures = {executor.submit(self.send, cid, data): cid for cid in chunk}

                for future in as_completed(futures):
                    cid = futures[future]
                    try:
                        future.result()
                    except Exception as exc:  # noqa: BLE001 – log and continue
                        logger.error("Failed to broadcast to %s: %s", cid, exc)

            # Optional: small sleep to smooth throughput and avoid account-wide throttles
            time.sleep(0.02)

    @staticmethod
    def _encode_payload(payload: Dict[str, Any] | str | bytes) -> bytes:
        if isinstance(payload, bytes):
            return payload
        if isinstance(payload, str):
            return payload.encode("utf-8")
        # Assume dict-like object
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def _retry_or_raise(self, exc: Exception, attempt: int) -> None:
        """Retry helper with exponential back-off."""
        if attempt >= _DEFAULT_MAX_RETRIES:
            logger.error("Max retries reached – giving up")
            raise TooManyRetries from exc
        wait = _exponential_backoff(attempt)
        logger.debug("Backing off for %.2fs (attempt %d)", wait, attempt)
        time.sleep(wait)


# --------------------------------------------------------------------------------------
# Utils – building API Gateway endpoint based on env-vars
# --------------------------------------------------------------------------------------


def _build_apigw_management_endpoint(domain_name: str, stage: str) -> str:
    """
    Construct the ‘execute-api’ management WebSocket URL used by boto3.

    Parameters
    ----------
    domain_name: str
        e.g. abcdef123.execute-api.us-east-1.amazonaws.com
    stage: str
        the deployed stage name (e.g. 'prod')

    Returns
    -------
    str
        https://abcdef123.execute-api.us-east-1.amazonaws.com/prod
    """
    if domain_name.startswith("https://"):
        domain_name = domain_name.removeprefix("https://")
    return f"https://{domain_name}/{stage}"
```