"""Password hashing, API-key hashing and JWT helpers (no secrets are ever stored in plain text)."""
import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from . import config

ROLES = {"viewer": 1, "analyst": 2, "admin": 3}
_N, _R, _P = 2 ** 14, 8, 1


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, expected = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                            maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(expected))     # constant-time comparison
    except Exception:  # noqa  (malformed hash -> deny)
        return False


DUMMY_HASH = hash_password("not-a-real-password")      # used so unknown e-mails take the same time as wrong passwords


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()    # keys are long random strings, so a fast hash is appropriate


def new_api_key():
    """Returns (plain_key, prefix, key_hash). The plain key must be shown to the user once and never stored."""
    key = "sw_" + secrets.token_urlsafe(32)
    return key, key[:10], hash_api_key(key)


def create_token(user_id: int, tenant_id: str, role: str, ttl_minutes: int | None = None) -> str:
    ttl = config.JWT_TTL_MINUTES if ttl_minutes is None else ttl_minutes
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "tenant": tenant_id, "role": role, "iat": now, "exp": now + timedelta(minutes=ttl)}
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError on a bad signature, expired token or wrong algorithm."""
    return jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"], options={"require": ["exp", "sub"]})
