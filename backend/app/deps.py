"""Authentication (who are you?) and authorisation (what may you do?).
Credentials: `Authorization: Bearer <JWT>` (people, from /auth/login) or `X-API-Key: <key>` (machines)."""
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import config
from .cache import cache
from .database import get_db
from .models import ApiKey, User
from .security import ROLES, decode_token, hash_api_key


@dataclass
class Principal:
    tenant_id: str
    role: str
    actor: str                      # shown in audit logs
    user_id: int | None = None
    key_id: int | None = None

    @property
    def id(self) -> str:            # the tenant id (kept so existing route code `t.id` keeps working)
        return self.tenant_id


def _unauthorized(msg="Invalid or missing credentials"):
    return HTTPException(401, msg, headers={"WWW-Authenticate": "Bearer"})


def get_principal(authorization: str = Header(default=""), x_api_key: str = Header(default=""),
                  db: Session = Depends(get_db)) -> Principal:
    principal = None
    if authorization.lower().startswith("bearer "):
        try:
            claims = decode_token(authorization[7:].strip())
        except jwt.PyJWTError:
            raise _unauthorized("Invalid or expired token")
        user = db.get(User, int(claims["sub"]))
        if user and user.is_active and user.tenant_id == claims.get("tenant"):
            # role/tenant are re-read from the database, so demoting or disabling a user takes effect immediately
            principal = Principal(user.tenant_id, user.role, user.email, user_id=user.id)
    elif x_api_key:
        key = db.query(ApiKey).filter(ApiKey.key_hash == hash_api_key(x_api_key), ApiKey.is_active.is_(True)).first()
        if key:
            now = datetime.utcnow()
            if key.last_used_at is None or now - key.last_used_at > timedelta(minutes=5):
                key.last_used_at = now
                db.commit()
            principal = Principal(key.tenant_id, key.role, f"key:{key.name}", key_id=key.id)
    if principal is None:
        raise _unauthorized()
    if cache.incr(f"rl:{principal.tenant_id}", ttl=60) > config.RATE_LIMIT_PER_MIN:      # per-tenant rate limit
        raise HTTPException(429, "Rate limit exceeded. Try again in a minute.")
    return principal


def require(min_role: str):
    """Dependency factory: `Depends(require("analyst"))` allows analyst and admin, rejects viewer with 403."""
    def dep(p: Principal = Depends(get_principal)) -> Principal:
        if ROLES[p.role] < ROLES[min_role]:
            raise HTTPException(403, f"Requires role '{min_role}' or higher (you are '{p.role}')")
        return p
    return dep
