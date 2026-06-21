"""Security primitives: password hashing, JWT, credential encryption.

Used by RBAC (Phase 7) and by encrypted storage of WITSML server
credentials (Phase 1). bcrypt is used directly to avoid passlib/bcrypt
version-detection noise; the API is identical in spirit.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from cryptography.fernet import Fernet

from app.config import settings

_BCRYPT_MAX_BYTES = 72


# ── Passwords ───────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:_BCRYPT_MAX_BYTES], hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ── JWT (REST + WebSocket auth) ─────────────────────────────────────────
def create_access_token(subject: str, extra: dict | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_alg)


def decode_token(token: str) -> dict:
    """Decode/verify a JWT. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_alg])


# ── Credential encryption at rest (Fernet) ──────────────────────────────
def _fernet() -> Fernet:
    key = settings.credential_encryption_key
    if not key:
        # Derive a stable key from SECRET_KEY so dev works without extra
        # config. Production MUST set CREDENTIAL_ENCRYPTION_KEY (README).
        digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest).decode("ascii")
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
