```python
"""
ledgerquest.engine.state.serializer
===================================

High-level, pluggable game-state (de)serialisation utilities.

Why another serializer?
-----------------------
•  The engine runs *server-less* and stores long-lived state in DynamoDB/S3.
•  Lambda payloads have hard size limits and are cold-start sensitive.
•  We therefore need optional compression, encryption and a *tiny* header that
   can be inspected without materialising the whole blob.

A typical on-disk / on-wire artefact therefore looks like this::

    +---------------- header (JSON) ---------------+  <-- not compressed/encrypted
    | {"fmt":"json","enc":false,"zip":true,...}    |
    +---------------------------------------------+
    | <CR><LF>                                     |
    | <CR><LF>    <-- header/body delimiter        |
    +---------------------------------------------+
    | 0x1F 0x8B 0x08 ...          <-- body bytes   |  <-- may be zipped/encrypted
    +---------------------------------------------+

The module purposely avoids tight coupling to the engine’s ECS internals.  Game
sub-systems can *register* bespoke (de)serialisers at runtime:

    >>> @register_serializer(Vector)
    ... def _(v): return {'x': v.x, 'y': v.y, 'z': v.z}
    >>> @register_deserializer("Vector")
    ... def _(d): return Vector(**d)

If nothing is registered, dataclasses, Pydantic models and plain primitives
“just work”.
"""
from __future__ import annotations

import gzip
import enum
import importlib
import io
import json
import logging
import secrets
from dataclasses import asdict, is_dataclass
from types import ModuleType
from typing import Any, Callable, Dict, Tuple, Type

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Optional dependencies
# --------------------------------------------------------------------------- #
try:
    import msgpack  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    msgpack = None  # fmt: off

try:
    from cryptography.fernet import Fernet, InvalidToken  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    Fernet, InvalidToken = None, None  # fmt: off


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
__all__ = [
    "SerializationFormat",
    "SerializationError",
    "dumps",
    "loads",
    "register_serializer",
    "register_deserializer",
]

_HEADER_DELIM: bytes = b"\r\n\r\n"  # delimiter between header and body
_PROTOCOL_VERSION: int = 1          # bump when breaking on-disk format changes


class SerializationFormat(str, enum.Enum):
    """Supported wire formats."""

    JSON = "json"
    MSGPACK = "msgpack"


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #
class SerializationError(RuntimeError):
    """Raised when serialisation or deserialisation fails."""


# --------------------------------------------------------------------------- #
# Registry for custom (de)serialisers
# --------------------------------------------------------------------------- #
_Serializer = Callable[[Any], Any]
_Deserializer = Callable[[Any], Any]

_serializers: Dict[Type[Any], _Serializer] = {}
_deserializers: Dict[str, _Deserializer] = {}


def register_serializer(target_type: Type[Any]) -> Callable[[_Serializer], _Serializer]:
    """
    Decorator to register a custom *to-primitive* function for ``target_type``.

    The function must accept an instance of ``target_type`` and return a value
    that the selected ``SerializationFormat`` natively understands (i.e. JSON /
    MsgPack primitives).

    Example
    -------
        @register_serializer(Vector)
        def _(v: Vector) -> dict[str, float]:
            return {"x": v.x, "y": v.y, "z": v.z}
    """

    def decorator(func: _Serializer) -> _Serializer:
        _serializers[target_type] = func
        logger.debug("Registered serializer for %s: %s", target_type, func)
        return func

    return decorator


def register_deserializer(type_name: str) -> Callable[[_Deserializer], _Deserializer]:
    """
    Decorator to register a function that turns *primitive* data back into a
    rich Python object.

    ``type_name`` **must** match the fully-qualified type name emitted by the
    corresponding serializer (module.path:ClassName).
    """

    def decorator(func: _Deserializer) -> _Deserializer:
        _deserializers[type_name] = func
        logger.debug("Registered deserializer for %s: %s", type_name, func)
        return func

    return decorator


# --------------------------------------------------------------------------- #
# Public helpers
# --------------------------------------------------------------------------- #
def dumps(
    obj: Any,
    *,
    fmt: SerializationFormat = SerializationFormat.JSON,
    compress: bool | int = False,
    encryption_key: bytes | None = None,
    metadata: dict[str, Any] | None = None,
) -> bytes:
    """
    Serialise *obj* according to *fmt* and return raw bytes suitable for
    DynamoDB/S3.

    Parameters
    ----------
    obj:
        The Python object to serialise.
    fmt:
        Wire format.  ``json`` has broader tool support, while ``msgpack`` is
        more bandwidth-efficient (but optional).
    compress:
        ``False``: no compression. ``True``: default level 6.  ``int``: gzip
        compression level (0-9).
    encryption_key:
        32-byte Fernet key if encryption is desired.  Requires
        ``pip install cryptography``.
    metadata:
        Additional key/value pairs to embed in the *header* (e.g. game/session
        identifiers).  Must be JSON serialisable.

    Raises
    ------
    SerializationError
        On unsupported formats, missing dependencies, etc.
    """
    logger.debug(
        "Serialising object of type %s (fmt=%s, compress=%s, enc=%s)",
        type(obj),
        fmt,
        compress,
        bool(encryption_key),
    )

    header: dict[str, Any] = {
        "proto": _PROTOCOL_VERSION,
        "fmt": fmt.value,
        "zip": bool(compress),
        "enc": bool(encryption_key),
        # Fully-qualified type: 'package.module:ClassName'
        "type": f"{obj.__class__.__module__}:{obj.__class__.__qualname__}",
    }
    if metadata:
        header["meta"] = metadata

    # 1. To primitive
    primitive = _to_primitive(obj)

    # 2. Encode to bytes
    try:
        body: bytes
        if fmt is SerializationFormat.JSON:
            body = json.dumps(primitive, separators=(",", ":")).encode("utf-8")
        elif fmt is SerializationFormat.MSGPACK:
            if msgpack is None:  # pragma: no cover
                raise SerializationError("msgpack not installed. `pip install msgpack`")
            body = msgpack.packb(primitive, use_bin_type=True)
        else:  # pragma: no cover
            raise SerializationError(f"Unsupported format: {fmt}")
    except (TypeError, ValueError) as exc:
        raise SerializationError(f"Unable to serialise object: {exc}") from exc

    # 3. Optional compression
    if compress:
        level = 6 if compress is True else int(compress)
        body = gzip.compress(body, mtime=0, compresslevel=level)  # deterministic

    # 4. Optional encryption
    if encryption_key:
        if Fernet is None:  # pragma: no cover
            raise SerializationError(
                "cryptography missing: `pip install cryptography`"
            )
        try:
            f = Fernet(encryption_key)
            body = f.encrypt(body)
        except Exception as exc:  # pragma: no cover
            raise SerializationError(f"Encryption failed: {exc}") from exc

    # 5. Binary envelope: header + delimiter + body
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    blob = header_bytes + _HEADER_DELIM + body
    logger.debug("Serialised payload: %d bytes (header=%d)", len(blob), len(header_bytes))
    return blob


def loads(
    blob: bytes,
    *,
    encryption_key: bytes | None = None,
    safe_mode: bool = True,
) -> Any:
    """
    Inverse operation of :func:`~ledgerquest.engine.state.serializer.dumps`.

    Parameters
    ----------
    blob:
        The raw bytes previously produced by :pyfunc:`dumps`.
    encryption_key:
        Fernet key if the payload is encrypted.
    safe_mode:
        If *True* (default) errors are *never* swallowed.  If *False* we log a
        warning and return ``None`` on failure (useful for telemetry pipelines
        where partial failure is tolerable).

    Raises
    ------
    SerializationError
        On any fatal issue *unless* ``safe_mode=False``.
    """
    try:
        header_bytes, body = _split_blob(blob)
        header = json.loads(header_bytes)
        logger.debug("Deserialising payload (header=%s)", header)

        _validate_header(header, encryption_key)

        # 1. Decrypt if necessary
        if header["enc"]:
            if Fernet is None:  # pragma: no cover
                raise SerializationError(
                    "cryptography missing but payload is encrypted"
                )
            try:
                body = Fernet(encryption_key).decrypt(body)
            except (InvalidToken, Exception) as exc:  # pragma: no cover
                raise SerializationError(f"Decryption error: {exc}") from exc

        # 2. Decompress if necessary
        if header["zip"]:
            body = gzip.decompress(body)

        # 3. Decode primitive
        fmt = SerializationFormat(header["fmt"])
        if fmt is SerializationFormat.JSON:
            primitive = json.loads(body.decode("utf-8"))
        elif fmt is SerializationFormat.MSGPACK:
            if msgpack is None:  # pragma: no cover
                raise SerializationError("msgpack not installed.")
            primitive = msgpack.unpackb(body, raw=False)
        else:  # pragma: no cover
            raise SerializationError(f"Unsupported format {fmt}")

        # 4. Convertible to object?
        type_name: str | None = header.get("type")
        obj = _from_primitive(primitive, type_name)
        return obj

    except SerializationError:
        raise
    except Exception as exc:  # pragma: no cover
        if safe_mode:
            raise SerializationError(f"Deserialisation failed: {exc}") from exc
        logger.warning("Failed to deserialise blob: %s", exc, exc_info=True)
        return None


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _split_blob(blob: bytes) -> Tuple[bytes, bytes]:
    """Return ``(header, body)``."""
    try:
        idx = blob.index(_HEADER_DELIM)
    except ValueError as exc:  # pragma: no cover
        raise SerializationError("Malformed payload: missing header delimiter") from exc
    return blob[:idx], blob[idx + len(_HEADER_DELIM) :]


def _validate_header(header: dict[str, Any], encryption_key: bytes | None) -> None:
    """Consistency checks before we operate on the body."""
    if header.get("proto") != _PROTOCOL_VERSION:  # pragma: no cover
        raise SerializationError(
            f"Incompatible protocol version {header['proto']} "
            f"(expected {_PROTOCOL_VERSION})"
        )
    if header["enc"] and not encryption_key:  # pragma: no cover
        raise SerializationError("Payload is encrypted but no key provided")


def _to_primitive(obj: Any) -> Any:
    """
    Convert *obj* to a JSON/MsgPack compatible structure by applying (in order):

    1. Custom serializer registered via :pyfunc:`register_serializer`.
    2. ``dataclasses.asdict`` for dataclass instances.
    3. ``model.dict()`` for Pydantic models.
    4. ``__dict__`` fallback for plain objects.
    """
    # 1. Registry
    for tp, fn in _serializers.items():
        if isinstance(obj, tp):
            primitive = fn(obj)
            logger.debug("Serialised via registry for %s", tp)
            return primitive

    # 2. Dataclasses
    if is_dataclass(obj):
        return asdict(obj)

    # 3. Pydantic
    if hasattr(obj, "model_dump"):  # Pydantic v2
        return obj.model_dump(mode="json")
    if hasattr(obj, "dict"):  # Pydantic v1
        return obj.dict()

    # 4. Built-ins are considered already primitive
    if isinstance(obj, (list, dict, str, int, float, bool, type(None))):
        return obj

    # 5. Fallback: object's __dict__
    if hasattr(obj, "__dict__"):
        return obj.__dict__

    raise SerializationError(f"Object of type {type(obj)} is not serialisable")


def _from_primitive(primitive: Any, type_name: str | None) -> Any:
    """
    Attempt to reconstruct the original Python object via:

    1. Custom deserializer registry.
    2. Importing the class and feeding the primitive into its constructor.
    3. As a last resort, return the primitive untouched.
    """
    if type_name and type_name in _deserializers:
        try:
            return _deserializers[type_name](primitive)
        except Exception as exc:  # pragma: no cover
            raise SerializationError(
                f"Custom deserializer for {type_name} failed: {exc}"
            ) from exc

    if type_name:
        mod_name, _, cls_name = type_name.partition(":")
        try:
            mod: ModuleType = importlib.import_module(mod_name)
            cls: Type[Any] = getattr(mod, cls_name)
            return cls(**primitive) if isinstance(primitive, dict) else cls(primitive)
        except Exception as exc:  # noqa: BLE001 pragma: no cover
            logger.debug(
                "Could not instantiate %s via reflection: %s. "
                "Falling back to primitive.",
                type_name,
                exc,
            )

    return primitive


# --------------------------------------------------------------------------- #
# Convenience features
# --------------------------------------------------------------------------- #
def generate_fernet_key() -> bytes:
    """
    Utility wrapper that returns a *url-safe* random 32-byte key suitable
    for the *encryption_key* parameter in :pyfunc:`dumps`.
    """
    if Fernet is None:  # pragma: no cover
        raise SerializationError("cryptography not installed")
    return Fernet.generate_key()


def estimate_size(obj: Any, **kwargs: Any) -> int:
    """
    Return the byte size of the serialised representation.  Internally this
    performs a full serialisation cycle but discards the result.
    """
    return len(dumps(obj, **kwargs))


# --------------------------------------------------------------------------- #
# Debug / self-test
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Round-trip sanity check
    sample = {"answer": 42, "payload": [1, 2, 3]}
    key = generate_fernet_key()

    for fmt in SerializationFormat:
        blob = dumps(sample, fmt=fmt, compress=True, encryption_key=key)
        restored = loads(blob, encryption_key=key)
        assert restored == sample
        logger.info("Roundtrip success (%s): %d bytes", fmt, len(blob))

    logger.info("All tests passed.")
```