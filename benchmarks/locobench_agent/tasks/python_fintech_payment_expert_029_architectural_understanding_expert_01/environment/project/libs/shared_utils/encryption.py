```python
"""
crowdpay_connect.libs.shared_utils.encryption
============================================

A collection of encryption / decryption utilities shared across the CrowdPay
Connect code-base.  The module intentionally has no direct business-logic
dependency so that it can be imported from any micro-service, CLI, or data
pipeline that requires cryptographic primitives.

Key Features
------------
* AES-256-GCM symmetric encryption (confidentiality + integrity)
* RSA-4096 asymmetric encryption / decryption & digital signature utilities
* Hybrid (envelope) encryption – large payloads are encrypted with AES; the
  randomly generated AES key is itself encrypted with the recipient’s RSA
  public key
* Pass-phrase derived keys (PBKDF2-HMAC-SHA-256) for low-entropy secrets
* High-level helpers to (de)serialize encrypted messages to JSON for transport
  through event streams or REST APIs

Security-First Defaults
-----------------------
* Secure random number generation via the `secrets` stdlib module
* 12-byte nonces for AES-GCM, avoiding counter reuse
* 100k PBKDF2 iterations with per-key 128-bit random salts
* Constant-time verification in signature & tag checks

External Dependency
-------------------
cryptography>=3.4

The dependency is intentionally lightweight and battle-tested for production
systems.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

__all__ = [
    "EncryptionError",
    "EncryptedMessage",
    "SymmetricEncryptor",
    "AsymmetricEncryptor",
    "HybridEncryptor",
    "derive_key_from_passphrase",
]

_LOGGER = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #


class EncryptionError(RuntimeError):
    """Raised whenever an encryption-related operation fails for any reason."""


# --------------------------------------------------------------------------- #
# Data Classes                                                                #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class EncryptedMessage:
    """
    Wire format for encrypted payloads exchanged between CrowdPay services.

    The message can be safely serialized to / from JSON while preserving
    cryptographic artefacts in base64 form.
    """

    # Envelope fields
    enc_key: str  # RSA-encrypted AES key - base64
    nonce: str  # AES-GCM nonce           - base64
    tag: str  # AES-GCM auth tag          - base64
    ciphertext: str  # AES-GCM ciphertext - base64
    created_utc: str  # ISO 8601 creation timestamp
    aad: Optional[str] = None  # Associated Aditional Data (if any) - base64

    # --------------------------------------------------------------------- #
    # (De)serialization helpers                                             #
    # --------------------------------------------------------------------- #

    def to_json(self) -> str:
        """Return a compact JSON representation suitable for transport."""
        return json.dumps(self.__dict__, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "EncryptedMessage":
        """Parse a JSON string back into an EncryptedMessage instance."""
        return cls(**json.loads(raw))

    # --------------------------------------------------------------------- #
    # Byte helpers                                                          #
    # --------------------------------------------------------------------- #

    def _b(self, field: str) -> bytes:  # noqa: D401
        """Decode a base64-encoded field into raw bytes."""
        return base64.b64decode(getattr(self, field))

    def key_bytes(self) -> bytes:
        return self._b("enc_key")

    def nonce_bytes(self) -> bytes:
        return self._b("nonce")

    def tag_bytes(self) -> bytes:
        return self._b("tag")

    def ciphertext_bytes(self) -> bytes:
        return self._b("ciphertext")

    def aad_bytes(self) -> Optional[bytes]:
        return base64.b64decode(self.aad) if self.aad else None


# --------------------------------------------------------------------------- #
# Symmetric Encryption                                                        #
# --------------------------------------------------------------------------- #


class SymmetricEncryptor:
    """AES-256-GCM convenience wrapper."""

    _NONCE_SIZE = 12  # Per NIST SP 800-38D
    _KEY_SIZE = 32  # 256 bits

    def __init__(self, key: bytes):
        if not isinstance(key, (bytes, bytearray)):
            raise TypeError("AES key must be bytes")
        if len(key) != self._KEY_SIZE:
            raise ValueError("AES key size must be 32 bytes (256 bits)")
        self._key = bytes(key)  # defensive copy
        self._aead = AESGCM(self._key)

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    @classmethod
    def generate_key(cls) -> bytes:
        """Return a newly generated 256-bit AES key."""
        return secrets.token_bytes(cls._KEY_SIZE)

    def encrypt(
        self, plaintext: bytes, *, aad: Optional[bytes] = None
    ) -> Tuple[bytes, bytes, bytes]:
        """
        Encrypt `plaintext` and return a tuple of (nonce, ciphertext, tag).

        The nonce is generated per encryption call; callers MUST persist it
        alongside the ciphertext in order to decrypt later.
        """
        if not isinstance(plaintext, (bytes, bytearray)):
            raise TypeError("Plaintext must be bytes")

        nonce = secrets.token_bytes(self._NONCE_SIZE)
        _LOGGER.debug("Generated AES-GCM nonce: %s", base64.b64encode(nonce))

        # AESGCM.encrypt returns nonce|ciphertext|tag in one go, so we split.
        ct_with_tag = self._aead.encrypt(nonce, plaintext, aad)
        ciphertext, tag = ct_with_tag[:-16], ct_with_tag[-16:]
        return nonce, ciphertext, tag

    def decrypt(
        self, *, nonce: bytes, ciphertext: bytes, tag: bytes, aad: Optional[bytes] = None
    ) -> bytes:
        """
        Decrypt and return the plaintext. Raises `EncryptionError`
        if authentication fails.
        """
        ct_with_tag = ciphertext + tag
        try:
            return self._aead.decrypt(nonce, ct_with_tag, aad)
        except InvalidTag as exc:
            _LOGGER.warning("AES-GCM authentication failed: %s", exc)
            raise EncryptionError("Decryption failed: invalid authentication tag") from exc


# --------------------------------------------------------------------------- #
# Asymmetric Encryption & Signatures                                          #
# --------------------------------------------------------------------------- #


class AsymmetricEncryptor:
    """RSA-4096 OAEP / PSS utility helper."""

    _KEY_SIZE = 4096
    _PUB_EXPONENT = 0x10001  # 65537

    def __init__(
        self,
        *,
        private_key: Optional[rsa.RSAPrivateKey] = None,
        public_key: Optional[rsa.RSAPublicKey] = None,
    ):
        if not (private_key or public_key):
            raise ValueError("Either private_key or public_key must be supplied")

        self._private_key = private_key
        self._public_key = (
            public_key or private_key.public_key()  # type: ignore[arg-type]
        )

    # --------------------------------------------------------------------- #
    # Static Helpers                                                        #
    # --------------------------------------------------------------------- #

    @staticmethod
    def generate_key_pair() -> Tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
        """Generate a new RSA-4096 key pair."""
        private = rsa.generate_private_key(
            public_exponent=AsymmetricEncryptor._PUB_EXPONENT,
            key_size=AsymmetricEncryptor._KEY_SIZE,
            backend=default_backend(),
        )
        return private, private.public_key()

    # --------------------------------------------------------------------- #
    # Encryption / Decryption                                               #
    # --------------------------------------------------------------------- #

    def encrypt(self, plaintext: bytes) -> bytes:
        if self._public_key is None:
            raise EncryptionError("Public key is not available for encryption")

        return self._public_key.encrypt(
            plaintext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

    def decrypt(self, ciphertext: bytes) -> bytes:
        if self._private_key is None:
            raise EncryptionError("Private key required for decryption")
        try:
            return self._private_key.decrypt(
                ciphertext,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
        except ValueError as exc:
            raise EncryptionError("RSA decryption failed") from exc

    # --------------------------------------------------------------------- #
    # Signature                                                             #
    # --------------------------------------------------------------------- #

    def sign(self, message: bytes) -> bytes:
        if self._private_key is None:
            raise EncryptionError("Private key required for signing")
        return self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

    def verify(self, signature: bytes, message: bytes) -> None:
        try:
            self._public_key.verify(
                signature,
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
        except InvalidSignature as exc:
            raise EncryptionError("Signature verification failed") from exc

    # --------------------------------------------------------------------- #
    # Serialization                                                         #
    # --------------------------------------------------------------------- #

    @staticmethod
    def _serialize_key(
        key: rsa.RSAPrivateKey | rsa.RSAPublicKey, *, private: bool, password: Optional[bytes] = None
    ) -> bytes:
        if private:
            enc_algo = (
                serialization.BestAvailableEncryption(password) if password else serialization.NoEncryption()
            )
            return key.private_bytes(  # type: ignore[return-value]
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=enc_algo,
            )
        return key.public_bytes(  # type: ignore[arg-type]
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def export_private_pem(self, *, password: Optional[bytes] = None) -> bytes:
        if self._private_key is None:
            raise EncryptionError("Private key not available")
        return self._serialize_key(self._private_key, private=True, password=password)

    def export_public_pem(self) -> bytes:
        return self._serialize_key(self._public_key, private=False)

    # --------------------------------------------------------------------- #
    # Factory                                                               #
    # --------------------------------------------------------------------- #

    @classmethod
    def from_pem(
        cls,
        *,
        private_pem: Optional[bytes] = None,
        public_pem: Optional[bytes] = None,
        password: Optional[bytes] = None,
    ) -> "AsymmetricEncryptor":
        """
        Load an `AsymmetricEncryptor` from PEM-encoded keys.
        Password is only used when loading encrypted private keys.
        """
        private_key = None
        public_key = None

        if private_pem:
            private_key = serialization.load_pem_private_key(
                private_pem, password=password, backend=default_backend()
            )
            if not isinstance(private_key, rsa.RSAPrivateKey):
                raise TypeError("Provided private key is not RSA")
            public_key = private_key.public_key()

        if public_pem:
            public_key = serialization.load_pem_public_key(public_pem, backend=default_backend())
            if not isinstance(public_key, rsa.RSAPublicKey):
                raise TypeError("Provided public key is not RSA")

        return cls(private_key=private_key, public_key=public_key)


# --------------------------------------------------------------------------- #
# Hybrid (Envelope) Encryption                                                #
# --------------------------------------------------------------------------- #


class HybridEncryptor:
    """
    Large payload encryption helper – uses AES-256-GCM under the hood and
    protects the AES session key with RSA-4096-OAEP.

    Typical workflow
    ----------------
    sender  = HybridEncryptor(public_key=<recipient_pub_key>)
    message = sender.encrypt_json({"ssn": "...", "dob": "..."}))

    # JSON traverses network...

    receiver = HybridEncryptor(private_key=<recipient_priv_key>)
    data     = receiver.decrypt_json(message)
    """

    def __init__(
        self,
        *,
        private_key: Optional[rsa.RSAPrivateKey] = None,
        public_key: Optional[rsa.RSAPublicKey] = None,
    ):
        self._rsa = AsymmetricEncryptor(private_key=private_key, public_key=public_key)

    # --------------------------------------------------------------------- #
    # Encrypt                                                               #
    # --------------------------------------------------------------------- #

    def _encrypt(self, plaintext: bytes, *, aad: Optional[bytes] = None) -> EncryptedMessage:
        # 1. Generate session key
        aes_key = SymmetricEncryptor.generate_key()
        _LOGGER.debug("Generated one-time AES key (base64): %s", base64.b64encode(aes_key))

        # 2. Encrypt data
        aes = SymmetricEncryptor(aes_key)
        nonce, ciphertext, tag = aes.encrypt(plaintext, aad=aad)

        # 3. Encrypt AES key with RSA
        enc_key = self._rsa.encrypt(aes_key)

        # 4. Build envelope
        return EncryptedMessage(
            enc_key=base64.b64encode(enc_key).decode(),
            nonce=base64.b64encode(nonce).decode(),
            tag=base64.b64encode(tag).decode(),
            ciphertext=base64.b64encode(ciphertext).decode(),
            created_utc=datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"),
            aad=base64.b64encode(aad).decode() if aad else None,
        )

    def encrypt_json(self, payload: Any, *, aad: Optional[bytes] = None) -> str:
        """
        Encrypt an arbitrary JSON-serializable `payload` and return the
        wire-formatted encrypted message (JSON string).
        """
        try:
            plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        except (TypeError, ValueError) as exc:
            raise EncryptionError(f"Payload is not JSON serializable: {exc}") from exc

        envelope = self._encrypt(plaintext, aad=aad)
        return envelope.to_json()

    # --------------------------------------------------------------------- #
    # Decrypt                                                               #
    # --------------------------------------------------------------------- #

    def _decrypt(self, envelope: EncryptedMessage) -> bytes:
        # 1. Unwrap AES key
        aes_key = self._rsa.decrypt(envelope.key_bytes())

        # 2. Decrypt data
        aes = SymmetricEncryptor(aes_key)
        return aes.decrypt(
            nonce=envelope.nonce_bytes(),
            ciphertext=envelope.ciphertext_bytes(),
            tag=envelope.tag_bytes(),
            aad=envelope.aad_bytes(),
        )

    def decrypt_json(self, raw_message: str) -> Any:
        """
        Decrypt a message produced by `encrypt_json` and return the original
        Python object.
        """
        envelope = EncryptedMessage.from_json(raw_message)
        plaintext = self._decrypt(envelope)
        try:
            return json.loads(plaintext)
        except json.JSONDecodeError as exc:
            raise EncryptionError("Decrypted payload is not valid JSON") from exc


# --------------------------------------------------------------------------- #
# Pass-phrase Based Key Derivation                                            #
# --------------------------------------------------------------------------- #


def derive_key_from_passphrase(
    passphrase: str,
    *,
    salt: Optional[bytes] = None,
    iterations: int = 100_000,
) -> Tuple[bytes, bytes]:
    """
    Derive a 256-bit key from a human-memorable `passphrase` using PBKDF2-HMAC-SHA-256.

    Parameters
    ----------
    passphrase : str
        User-supplied passphrase (Unicode); it will be UTF-8 encoded before use.
    salt : bytes, optional
        Cryptographically random salt.  If not supplied, a new 16-byte salt is generated
        and returned alongside the derived key.
    iterations : int, default 100_000
        PBKDF2 iteration count.  Higher values increase computational complexity
        making brute-force attacks more expensive.

    Returns
    -------
    key : bytes
        The 32-byte derived key suitable for AES-256.
    salt : bytes
        The salt used during derivation (generated if input was None).
    """
    if not isinstance(passphrase, str):
        raise TypeError("Passphrase must be a Unicode string")

    salt = salt or secrets.token_bytes(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
        backend=default_backend(),
    )
    key = kdf.derive(passphrase.encode("utf-8"))
    return key, salt
```