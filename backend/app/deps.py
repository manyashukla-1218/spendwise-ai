from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import config
from .cache import cache
from .database import get_db
from .models import Tenant


def current_tenant(x_api_key: str = Header(default=""), db: Session = Depends(get_db)) -> Tenant:
    """Authentication + multi-tenancy: the tenant comes from the API key, never from the request body."""
    t = db.query(Tenant).filter(Tenant.api_key == x_api_key).first() if x_api_key else None
    if not t:
        raise HTTPException(401, "Invalid or missing X-API-Key")
    n = cache.incr(f"rl:{t.id}", ttl=60)                 # rate limiting: N requests / minute / tenant
    if n > config.RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "Rate limit exceeded. Try again in a minute.")
    return t
