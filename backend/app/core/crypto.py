"""Encryption at rest for third-party credentials (connector API keys, AWS secrets).

Fernet provides authenticated symmetric encryption (AES-128-CBC + HMAC-SHA256).
The key comes from CONNECTOR_ENCRYPTION_KEY and never touches the database, so a
database dump alone does not reveal any credential. Several comma-separated keys
enable rotation: the first encrypts, every key is tried when decrypting.

Generate a key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from fastapi import status

from app.core.config import Settings
from app.core.errors import AppError


class EncryptionUnavailable(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message, code="encryption_unavailable", status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )


def cipher(settings: Settings) -> MultiFernet:
    if settings.connector_encryption_key is None:
        raise EncryptionUnavailable(
            "Connectors are disabled: set CONNECTOR_ENCRYPTION_KEY so credentials can be "
            "encrypted at rest (see .env.example)."
        )
    raw = settings.connector_encryption_key.get_secret_value()
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except (ValueError, TypeError) as exc:
        raise EncryptionUnavailable(
            "CONNECTOR_ENCRYPTION_KEY is not a valid Fernet key (32 url-safe base64 bytes)."
        ) from exc


def encryption_configured(settings: Settings) -> bool:
    try:
        cipher(settings)
    except EncryptionUnavailable:
        return False
    return True


def encrypt_json(settings: Settings, value: dict[str, Any]) -> str:
    return cipher(settings).encrypt(json.dumps(value).encode("utf-8")).decode("ascii")


def decrypt_json(settings: Settings, token: str) -> dict[str, Any]:
    try:
        return json.loads(cipher(settings).decrypt(token.encode("ascii")))
    except InvalidToken as exc:
        raise EncryptionUnavailable(
            "Stored credentials cannot be decrypted with the configured "
            "CONNECTOR_ENCRYPTION_KEY. Restore the previous key or re-enter the credentials."
        ) from exc


def mask_secret(value: str) -> str:
    """'sk-ant-admin01-abc…' -> 'sk-ant-…9Xyz'. Short values reveal nothing."""
    value = value.strip()
    if len(value) < 12:
        return "…"
    return f"{value[:7]}…{value[-4:]}"
