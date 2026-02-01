```python
"""
ledgerquest.services.game_loop.input_processor
================================================

The input_processor module is responsible for converting raw
interaction events (typically sent by Web-Socket clients or REST
gateways) into **Command** objects that the rest of the LedgerQuest
game-loop understands.  The processor also performs tenant-aware
validation, idempotency checks, and finally publishes the commands to
an internal EventBridge bus where downstream stateless engines (AI,
physics, etc.) will pick the items up.

Core Responsibilities
---------------------
1. JSON schema validation & sanitisation of inbound events.
2. Idempotency: guarantee “exactly-once” semantics using a lightweight
   DynamoDB token table.
3. Command translation (Command Pattern).
4. Emission of validated commands to AWS EventBridge with the proper
   routing keys so that subscriber Lambdas / Step-Function workflows
   can continue the game loop.

The module purposefully keeps all AWS calls small and synchronous
because the Lambda runtime is expected to finish within <50 ms most of
the time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError
from jsonschema import ValidationError, validate
from typing_extensions import TypedDict

__all__ = ["InputProcessor", "InputValidationError", "Command", "InputType"]

###############################################################################
# Logging configuration
###############################################################################

LOG_LEVEL = os.getenv("LEDGERQUEST_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger("ledgerquest.input_processor")


###############################################################################
# Exceptions
###############################################################################


class InputValidationError(RuntimeError):
    """Raised when an inbound event fails schema validation."""

    def __init__(self, message: str, *, event: Optional[dict] = None) -> None:
        super().__init__(message)
        self.event = event or {}


class DuplicateEventError(RuntimeError):
    """Raised when an event with the same `interaction_id` was processed."""


###############################################################################
# Data Model
###############################################################################


class InputType(str, Enum):
    """Allowed user input types."""

    MOVE = "MOVE"
    CAST_SKILL = "CAST_SKILL"
    CHAT = "CHAT"
    PAUSE = "PAUSE"


@dataclass(frozen=True)
class Command:
    """
    Canonical command object understood by the lower-level game systems.

    A command is immutable and is *always* emitted onto EventBridge, from
    where specialised engines pick them up.
    """

    tenant_id: str
    game_id: str
    player_id: str
    command: InputType
    payload: Dict[str, Any]
    interaction_id: str  # used for idempotency


###############################################################################
# AWS resource helpers
###############################################################################

_DDB_TABLE = os.getenv("LEDGERQUEST_IDEMPOTENCY_TABLE", "ledgerquest-idempotency")
_EVENT_BUS_ARN = os.getenv("LEDGERQUEST_EVENT_BUS_ARN")  # mandatory in prod


def _create_ddb_client() -> BaseClient:
    return boto3.client("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))


def _create_eventbridge_client() -> BaseClient:
    return boto3.client("events", region_name=os.getenv("AWS_REGION", "us-east-1"))


###############################################################################
# JSON Schemas for validation
###############################################################################

_BASE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": [
        "tenant_id",
        "game_id",
        "player_id",
        "interaction_id",
        "input_type",
        "payload",
    ],
    "properties": {
        "tenant_id": {"type": "string", "minLength": 1},
        "game_id": {"type": "string", "minLength": 1},
        "player_id": {"type": "string", "minLength": 1},
        "interaction_id": {"type": "string", "minLength": 1},
        "input_type": {"type": "string", "enum": [i.value for i in InputType]},
        "payload": {"type": "object"},
    },
    "additionalProperties": False,
}

###############################################################################
# Public Processor
###############################################################################


class InputProcessor:
    """
    Convert & forward raw front-end interaction events to game-loop
    commands.

    Real-world production considerations implemented:
    • **Validation** via JSON-Schema.
    • **Idempotency** via a DynamoDB token table.
    • **Observability** with structured logging (tenant-aware).
    """

    def __init__(
        self,
        *,
        ddb_client: Optional[BaseClient] = None,
        eventbridge_client: Optional[BaseClient] = None,
        schema: Dict[str, Any] = _BASE_SCHEMA,
        logger_: logging.Logger = logger,
    ) -> None:
        self.ddb = ddb_client or _create_ddb_client()
        self.eb = eventbridge_client or _create_eventbridge_client()
        self.schema = schema
        self.log = logger_

        if not _EVENT_BUS_ARN:
            raise EnvironmentError(
                "Environment variable LEDGERQUEST_EVENT_BUS_ARN must be set."
            )

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def handle_event(self, event: Dict[str, Any]) -> Command:
        """
        Full processing pipeline for a single inbound event.

        Parameters
        ----------
        event:
            The raw event (dict) sent by API Gateway or another
            upstream component.

        Returns
        -------
        Command
            The Command object that was dispatched.

        Raises
        ------
        InputValidationError
            If the event is malformed.
        DuplicateEventError
            If the interaction id was already processed.
        ClientError
            If AWS interactions fail.
        """

        self.log.debug("Received raw event: %s", event)

        # 1. Validate shape and semantics
        self._validate_event(event)
        self.log.debug("Event passed JSON-Schema validation.")

        # 2. Perform idempotency check
        self._ensure_not_duplicate(event)
        self.log.debug("Idempotency check cleared.")

        # 3. Convert to Command
        command = self._extract_command(event)
        self.log.debug("Converted to Command: %s", command)

        # 4. Publish to EventBridge
        self._publish_command(command)
        self.log.info(
            "Command %s dispatched to EventBridge for tenant=%s, game=%s, player=%s",
            command.command,
            command.tenant_id,
            command.game_id,
            command.player_id,
        )

        return command

    # --------------------------------------------------------------------- #
    # Validation
    # --------------------------------------------------------------------- #

    def _validate_event(self, event: Dict[str, Any]) -> None:
        """Raises InputValidationError on failure."""
        try:
            validate(instance=event, schema=self.schema)
        except ValidationError as exc:
            # Bubble up with friendly message
            raise InputValidationError(str(exc), event=event) from exc

    # --------------------------------------------------------------------- #
    # Idempotency
    # --------------------------------------------------------------------- #

    def _ensure_not_duplicate(self, event: Dict[str, Any]) -> None:
        """
        Creates a lightweight idempotency record in DynamoDB.  Because the
        function is short-lived we rely on DynamoDB conditional writes to
        guarantee uniqueness.
        """
        interaction_id = event["interaction_id"]
        tenant_id = event["tenant_id"]

        try:
            self.ddb.put_item(
                TableName=_DDB_TABLE,
                Item={
                    "tenant_id": {"S": tenant_id},
                    "interaction_id": {"S": interaction_id},
                },
                ConditionExpression="attribute_not_exists(interaction_id)",
            )
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise DuplicateEventError(
                    f"Duplicate interaction_id={interaction_id}"
                ) from err
            raise  # Bubble up everything else

    # --------------------------------------------------------------------- #
    # Command Creation
    # --------------------------------------------------------------------- #

    def _extract_command(self, event: Dict[str, Any]) -> Command:
        """Translate raw event into the internal Command dataclass."""
        return Command(
            tenant_id=event["tenant_id"],
            game_id=event["game_id"],
            player_id=event["player_id"],
            command=InputType(event["input_type"]),
            payload=event.get("payload", {}),
            interaction_id=event["interaction_id"],
        )

    # --------------------------------------------------------------------- #
    # Publishing
    # --------------------------------------------------------------------- #

    def _publish_command(self, cmd: Command) -> None:
        """Publish the command to the LedgerQuest internal event bus."""

        detail = json.dumps(
            {
                "tenant_id": cmd.tenant_id,
                "game_id": cmd.game_id,
                "player_id": cmd.player_id,
                "command": cmd.command.value,
                "payload": cmd.payload,
                "interaction_id": cmd.interaction_id,
            },
            separators=(",", ":"),
        )

        try:
            self.eb.put_events(
                Entries=[
                    {
                        "EventBusName": _EVENT_BUS_ARN,
                        "Source": "ledgerquest.api",
                        "DetailType": f"GAME::{cmd.command.value}",
                        "Detail": detail,
                    }
                ]
            )
        except ClientError as err:
            # Attempt to roll back idempotency token so that the caller can retry
            self._delete_idempotency_token(cmd)
            raise

    def _delete_idempotency_token(self, cmd: Command) -> None:
        """Rollback helper in case publishing fails."""
        try:
            self.ddb.delete_item(
                TableName=_DDB_TABLE,
                Key={
                    "tenant_id": {"S": cmd.tenant_id},
                    "interaction_id": {"S": cmd.interaction_id},
                },
            )
        except Exception:  # noqa: BLE001
            # Swallow: we do not want to mask the original failure.
            self.log.warning(
                "Failed to delete idempotency token for tenant=%s interaction=%s",
                cmd.tenant_id,
                cmd.interaction_id,
            )


###############################################################################
# Lambda entry point helper
###############################################################################

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Small adapter so the module can be used directly as an AWS Lambda
    handler with API Gateway (REST or WebSocket).

    The function returns a JSON structure that API-Gateway will relay
    back to the client.
    """

    processor = InputProcessor()

    try:
        cmd = processor.handle_event(event)
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "ok": True,
                    "interaction_id": cmd.interaction_id,
                    "message": "Command accepted.",
                }
            ),
        }
    except InputValidationError as exc:
        logger.info("Validation failure: %s", exc)
        return {
            "statusCode": 400,
            "body": json.dumps({"ok": False, "error": str(exc)}),
        }
    except DuplicateEventError as exc:
        logger.info("Duplicate event ignored: %s", exc)
        return {
            "statusCode": 202,
            "body": json.dumps(
                {"ok": True, "duplicate": True, "interaction_id": event.get("interaction_id")}
            ),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled error while processing input event.")
        return {
            "statusCode": 500,
            "body": json.dumps({"ok": False, "error": "Internal Server Error"}),
        }
```