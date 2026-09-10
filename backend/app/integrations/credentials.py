import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class CredentialsError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().credentials_encryption_key
    if not key:
        raise CredentialsError(
            "CREDENTIALS_ENCRYPTION_KEY is not set — refusing to handle integration secrets"
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise CredentialsError("CREDENTIALS_ENCRYPTION_KEY is not a valid Fernet key") from exc


def encrypt_credentials(data: dict[str, Any]) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode())


def decrypt_credentials(blob: bytes) -> dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(blob).decode())
    except InvalidToken as exc:
        raise CredentialsError(
            "Could not decrypt integration credentials — the encryption key may have changed"
        ) from exc
