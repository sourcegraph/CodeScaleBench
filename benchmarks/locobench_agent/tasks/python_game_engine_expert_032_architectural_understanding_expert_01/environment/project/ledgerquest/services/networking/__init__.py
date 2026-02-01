```python
"""
ledgerquest.services.networking

The networking service is responsible for keeping track of all active
WebSocket connections, routing inbound messages to the correct handler,
and broadcasting outbound messages to the appropriate audience
(player-only, party, tenant-wide, global, etc.).

The implementation purposely avoids any game-specific logic; it simply
provides a thin, battle-tested abstraction on top of:
    • Amazon API Gateway (WebSocket Management API)
    • Amazon DynamoDB (connection registry for multi-tenant isolation)

Typical usage from a Lambda function configured as the $default route
for a WebSocket API:

    from ledgerquest.services.networking import (
        WebsocketEventDispatcher,
        ConnectionStore,
        MessageRouter,
    )

    router = MessageRouter()
    # Register command handlers
    router.register("PING", handle_ping)
    router.register("MOVE", gameplay.handle_move)

    dispatcher = WebsocketEventDispatcher(
        connection_store=ConnectionStore(),
        router=router,
    )

    def lambda_handler(event, context):
        return dispatcher.dispatch(event, context)
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import string
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

__all__ = [
    "MessageEnvelope",
    "ConnectionStore",
    "WebsocketClient",
    "MessageRouter",
    "WebsocketEventDispatcher",
]

# --------------------------------------------------------------------------- #
# Logging configuration
# --------------------------------------------------------------------------- #
_logger = logging.getLogger("ledgerquest.networking")
if not _logger.handlers:
    # Avoid adding multiple handlers in Lambda's re-use context
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Data models
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MessageEnvelope:
    """
    A strongly-typed representation of the JSON payload coming from the
    WebSocket `$default` integration.

    Example raw event from API Gateway:

        {
            "requestContext": {
                "connectionId": "ABcDEF123=",
                "eventType": "MESSAGE",
                "routeKey": "$default",
                "domainName": "abc123.execute-api.us-east-1.amazonaws.com",
                "stage": "prod",
                "authorizer": { ... }
            },
            "body": "{\"command\":\"PING\",\"payload\":{}}"
        }
    """

    # metadata
    event_type: str
    connection_id: str
    tenant_id: str
    player_id: Optional[str]

    # message specific
    command: str
    payload: Dict[str, Any]

    # raw record for low-level access / debugging
    raw_event: Dict[str, Any]

    @classmethod
    def from_apigw_event(cls, event: Dict[str, Any]) -> "MessageEnvelope":
        """Parse an API Gateway WebSocket event into a `MessageEnvelope`."""
        try:
            request_ctx = event["requestContext"]
            body: Dict[str, Any] = json.loads(event.get("body") or "{}")
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid API Gateway WebSocket event") from exc

        authorizer = request_ctx.get("authorizer", {})
        tenant_id = authorizer.get("tenantId") or body.get("tenantId") or "public"
        player_id = authorizer.get("playerId") or body.get("playerId")

        return cls(
            event_type=request_ctx.get("eventType", "MESSAGE"),
            connection_id=request_ctx["connectionId"],
            tenant_id=str(tenant_id),
            player_id=str(player_id) if player_id is not None else None,
            command=body.get("command", "").upper(),
            payload=body.get("payload", {}) or {},
            raw_event=event,
        )


# --------------------------------------------------------------------------- #
# DynamoDB Connection Registry
# --------------------------------------------------------------------------- #


class ConnectionStore:
    """
    CRUD wrapper around a DynamoDB table that stores active WebSocket
    connections. Each item maintains isolation by tenant, with optional
    sub-isolation for individual players or sessions.

    The table is expected to use:
        • partition key:  PK  ==  "TENANT#{tenant_id}"
        • sort key:       SK  ==  "CONN#{connection_id}"
    """

    _DEFAULT_TABLE_NAME = os.getenv("CONNECTIONS_TABLE_NAME", "lq_connection_registry")
    _DDB_RESOURCE = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION"))

    def __init__(self, table_name: Optional[str] = None) -> None:
        self._table = self._DDB_RESOURCE.Table(table_name or self._DEFAULT_TABLE_NAME)

    # ----------------------------- public API ----------------------------- #

    def put(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        player_id: Optional[str] = None,
        ttl_seconds: int = 86_400,
    ) -> None:
        """
        Store (or update) the connection reference with an optional TTL. The
        TTL is used by DynamoDB's native TTL mechanism to automatically clean
        up zombie connections that never sent a `$disconnect` event.
        """
        item = {
            "PK": f"TENANT#{tenant_id}",
            "SK": f"CONN#{connection_id}",
            "connectionId": connection_id,
            "tenantId": tenant_id,
            "playerId": player_id,
            "createdAt": int(time.time()),
            "expiresAt": int(time.time()) + ttl_seconds,
        }
        _logger.debug("Persisting connection to DynamoDB: %s", item)
        try:
            self._table.put_item(Item=item)
        except ClientError as err:
            _logger.exception("Unable to store connection in DynamoDB: %s", err)
            raise

    def delete(self, *, tenant_id: str, connection_id: str) -> None:
        """Remove a connection from the registry."""
        try:
            self._table.delete_item(
                Key={
                    "PK": f"TENANT#{tenant_id}",
                    "SK": f"CONN#{connection_id}",
                }
            )
            _logger.debug(
                "Deleted connection %s for tenant %s", connection_id, tenant_id
            )
        except ClientError as err:
            _logger.exception("Unable to delete connection: %s", err)
            raise

    def list_connections(self, *, tenant_id: str) -> List[str]:
        """
        Return the list of active connection IDs for the specified tenant.
        """
        try:
            response = self._table.query(
                KeyConditionExpression="PK = :pk",
                ExpressionAttributeValues={":pk": f"TENANT#{tenant_id}"},
                ProjectionExpression="connectionId",
            )
            ids = [item["connectionId"] for item in response.get("Items", [])]
            _logger.debug("Tenant %s has %d active connections", tenant_id, len(ids))
            return ids
        except ClientError as err:
            _logger.exception("Unable to query connections: %s", err)
            raise


# --------------------------------------------------------------------------- #
# API Gateway Management Client
# --------------------------------------------------------------------------- #


class WebsocketClient:
    """
    Thin wrapper around the API Gateway Management API that automatically
    stubs requests with the correct `endpoint_url` derived from the incoming
    event or from explicit configuration.

    The `endpoint_url` format:
        https://{api_id}.execute-api.{region}.amazonaws.com/{stage}
    """

    def __init__(self, endpoint_url: str) -> None:
        self._client = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=endpoint_url,
            region_name=os.getenv("AWS_REGION"),
        )
        self._endpoint_url = endpoint_url

    # ----------------------------- public API ----------------------------- #

    def send(self, connection_id: str, data: Dict[str, Any]) -> bool:
        """
        Push a JSON-serialisable document to a single websocket.

        Returns:
            bool: True if successful, False if connection no longer exists.
        """
        payload = json.dumps(data, separators=(",", ":")).encode()
        try:
            self._client.post_to_connection(ConnectionId=connection_id, Data=payload)
            _logger.debug("Sent payload to %s: %s", connection_id, data)
            return True
        except ClientError as err:
            status = err.response["ResponseMetadata"]["HTTPStatusCode"]
            if status == 410:  # Gone
                _logger.info("Connection %s is gone (410), will be removed", connection_id)
                return False
            _logger.exception("Failed to post to connection %s: %s", connection_id, err)
            raise

    def broadcast(self, connection_ids: Iterable[str], data: Dict[str, Any]) -> Tuple[int, List[str]]:
        """
        Broadcast a message to multiple connections. Connections that return a
        410 (gone) status will be collected and returned for the caller to
        optionally remove from the store.

        Returns:
            Tuple[successful_count, stale_connection_ids]
        """
        stale: List[str] = []
        sent = 0
        for cid in set(connection_ids):  # de-dupe to avoid double sends
            ok = self.send(cid, data)
            if ok:
                sent += 1
            else:
                stale.append(cid)
        _logger.debug("Broadcast result: sent=%d stale=%d", sent, len(stale))
        return sent, stale

    # --------------------------- factory helpers --------------------------- #

    @staticmethod
    def from_event(event: Dict[str, Any]) -> "WebsocketClient":
        """
        Build a WebsocketClient where endpoint_url is derived from the `domainName`
        and `stage` present in the API Gateway requestContext.
        """
        request_ctx = event["requestContext"]
        domain = request_ctx["domainName"]
        stage = request_ctx["stage"]
        endpoint_url = f"https://{domain}/{stage}"
        return WebsocketClient(endpoint_url=endpoint_url)


# --------------------------------------------------------------------------- #
# Message Routing
# --------------------------------------------------------------------------- #


class MessageRouter:
    """
    Registry + dispatcher of message-level commands.

    Game or application code can register handlers that accept a
    `MessageEnvelope` object. The router will invoke the first matching
    handler keyed by `command`.

    Handlers should raise exceptions to indicate an error; the dispatcher
    will automatically catch and send a failure response to the caller.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[[MessageEnvelope], Dict[str, Any]]] = {}

    def register(
        self,
        command: str,
        handler: Callable[[MessageEnvelope], Dict[str, Any]],
    ) -> None:
        command = command.upper()
        if command in self._handlers:
            raise ValueError(f"Handler already registered for command '{command}'")
        self._handlers[command] = handler
        _logger.info("Registered handler for command '%s': %s", command, handler)

    # ------------------------------------------------------------------ #

    def dispatch(self, envelope: MessageEnvelope) -> Dict[str, Any]:
        """
        Execute the handler registered for the envelope’s command. If no
        handler exists, returns a default "Not Implemented" message.
        """
        handler = self._handlers.get(envelope.command)
        if handler is None:
            _logger.warning(
                "No handler found for command '%s'. Returning not_implemented.",
                envelope.command,
            )
            return {
                "ok": False,
                "error": {"code": "NOT_IMPLEMENTED", "message": "Unknown command."},
            }
        try:
            _logger.debug(
                "Routing command '%s' to %s", envelope.command, handler.__qualname__
            )
            response = handler(envelope)
            return {"ok": True, "data": response} if isinstance(response, dict) else response
        except Exception as exc:  # pylint: disable=broad-except
            _logger.exception("Handler for command '%s' raised: %s", envelope.command, exc)
            return {
                "ok": False,
                "error": {"code": "UNHANDLED_EXCEPTION", "message": str(exc)},
            }


# --------------------------------------------------------------------------- #
# High-level Dispatcher (suitable for Lambda entrypoint)
# --------------------------------------------------------------------------- #


class WebsocketEventDispatcher:
    """
    Glue class that takes the raw Lambda event, converts it into a
    MessageEnvelope, routes it, and handles connect / disconnect bookkeeping.
    """

    def __init__(
        self,
        *,
        connection_store: ConnectionStore,
        router: MessageRouter,
    ) -> None:
        self._store = connection_store
        self._router = router

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def dispatch(self, event: Dict[str, Any], context: Any) -> Dict[str, Any]:
        """
        Entry-point: delegate to the appropriate handler depending on the
        `eventType` present in requestContext.
        """
        envelope = MessageEnvelope.from_apigw_event(event)
        event_type = envelope.event_type.upper()
        _logger.info(
            "Received %s event for connection %s (tenant=%s player=%s command=%s)",
            event_type,
            envelope.connection_id,
            envelope.tenant_id,
            envelope.player_id,
            envelope.command,
        )

        # Instantiate the client lazily – API endpoint derived from event
        ws_client = WebsocketClient.from_event(event)

        if event_type == "CONNECT":
            return self._on_connect(envelope)
        if event_type == "DISCONNECT":
            return self._on_disconnect(envelope)
        if event_type == "MESSAGE":
            return self._on_message(envelope, ws_client)
        _logger.warning("Unknown eventType '%s'", event_type)
        return {"statusCode": 400, "body": "Unknown event type."}

    # ------------------------------------------------------------------ #
    # Internal handlers
    # ------------------------------------------------------------------ #

    def _on_connect(self, envelope: MessageEnvelope) -> Dict[str, Any]:
        """Store the connection in DynamoDB."""
        # We generate a random playerId if not provided; useful for guests.
        player_id = envelope.player_id or _random_id(prefix="guest")
        self._store.put(
            tenant_id=envelope.tenant_id,
            connection_id=envelope.connection_id,
            player_id=player_id,
        )
        _logger.info(
            "Connection registered: tenant=%s conn=%s player=%s",
            envelope.tenant_id,
            envelope.connection_id,
            player_id,
        )
        return {"statusCode": 200, "body": "Connected."}

    def _on_disconnect(self, envelope: MessageEnvelope) -> Dict[str, Any]:
        """Remove the connection from DynamoDB."""
        self._store.delete(
            tenant_id=envelope.tenant_id, connection_id=envelope.connection_id
        )
        _logger.info(
            "Connection removed: tenant=%s conn=%s",
            envelope.tenant_id,
            envelope.connection_id,
        )
        return {"statusCode": 200, "body": "Disconnected."}

    def _on_message(
        self, envelope: MessageEnvelope, ws_client: WebsocketClient
    ) -> Dict[str, Any]:
        """
        Route the message and send whatever response the handler returns back
        to the caller. Also broadcasts failure/success notifications if the
        handler requests it via the returned payload.
        """
        result = self._router.dispatch(envelope)
        _logger.debug("Handler result for command %s: %s", envelope.command, result)

        # Direct response to the caller
        ok = ws_client.send(envelope.connection_id, result)
        if not ok:
            # Stale – remove
            self._store.delete(
                tenant_id=envelope.tenant_id, connection_id=envelope.connection_id
            )

        # Optional broadcast
        broadcast_msg = result.get("_broadcast") if isinstance(result, dict) else None
        if broadcast_msg:
            connections = self._store.list_connections(tenant_id=envelope.tenant_id)
            sent, stale = ws_client.broadcast(connections, broadcast_msg)
            _logger.info(
                "Broadcast '%s' to %d/%d connections (stale=%d)",
                envelope.command,
                sent,
                len(connections),
                len(stale),
            )
            for cid in stale:
                self._store.delete(
                    tenant_id=envelope.tenant_id,
                    connection_id=cid,
                )

        # Lambda integration expects an HTTP-style dict
        return {"statusCode": 200, "body": "OK"}


# --------------------------------------------------------------------------- #
# Utilities
# --------------------------------------------------------------------------- #


def _random_id(length: int = 12, *, prefix: str = "") -> str:
    alphabet = string.ascii_letters + string.digits
    return prefix + "".join(secrets.choice(alphabet) for _ in range(length))
```