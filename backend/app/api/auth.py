
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit, config
from ..cache import cache
from ..database import get_db
from ..deps import Principal, get_principal, require
from ..models import ApiKey, AuditLog, User
from ..security import (DUMMY_HASH, ROLES, create_token, hash_password, new_api_key, verify_password)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class NewUser(BaseModel):
    email: str = Field(min_length=3, max_length=200, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=8, max_length=200)
    role: str


class NewKey(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    role: str = "viewer"


def _check_role(role: str):
    if role not in ROLES:
        raise HTTPException(422, f"role must be one of {list(ROLES)}")


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if cache.incr(f"login:{email}", ttl=900) > config.LOGIN_MAX_ATTEMPTS:          # brute-force protection
        raise HTTPException(429, "Too many login attempts. Try again in 15 minutes.")
    user = db.query(User).filter(User.email == email).first()
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)   # same work for unknown e-mails
    if not user or not ok or not user.is_active:
        raise HTTPException(401, "Incorrect email or password")
    token = create_token(user.id, user.tenant_id, user.role)
    db.add(AuditLog(tenant_id=user.tenant_id, actor=user.email, action="login", detail=""))
    db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_in": config.JWT_TTL_MINUTES * 60,
            "role": user.role, "tenant_id": user.tenant_id, "email": user.email}


@router.get("/me")
def me(p: Principal = Depends(get_principal)):
    return {"tenant_id": p.tenant_id, "role": p.role, "actor": p.actor}


@router.get("/users")
def list_users(p: Principal = Depends(require("admin")), db: Session = Depends(get_db)):
    rows = db.query(User).filter(User.tenant_id == p.tenant_id).order_by(User.id).all()
    return [{"id": u.id, "email": u.email, "role": u.role, "is_active": u.is_active} for u in rows]


@router.post("/users", status_code=201)
def create_user(body: NewUser, p: Principal = Depends(require("admin")), db: Session = Depends(get_db)):
    _check_role(body.role)
    user = User(tenant_id=p.tenant_id, email=body.email.strip().lower(), password_hash=hash_password(body.password),
                role=body.role)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A user with this email already exists")
    audit.log(db, p, "user_created", f"{user.email} role={user.role}")
    db.commit()
    return {"id": user.id, "email": user.email, "role": user.role}


@router.post("/users/{user_id}/deactivate")
def deactivate_user(user_id: int, p: Principal = Depends(require("admin")), db: Session = Depends(get_db)):
    user = db.query(User).filter_by(id=user_id, tenant_id=p.tenant_id).first()     # tenant-scoped lookup
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == p.user_id:
        raise HTTPException(400, "You cannot deactivate yourself")
    user.is_active = False
    audit.log(db, p, "user_deactivated", user.email)
    db.commit()
    return {"ok": True}


@router.get("/api-keys")
def list_keys(p: Principal = Depends(require("admin")), db: Session = Depends(get_db)):
    rows = db.query(ApiKey).filter(ApiKey.tenant_id == p.tenant_id).order_by(ApiKey.id).all()
    return [{"id": k.id, "name": k.name, "prefix": k.prefix, "role": k.role, "is_active": k.is_active,
             "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None} for k in rows]


@router.post("/api-keys", status_code=201)
def create_key(body: NewKey, p: Principal = Depends(require("admin")), db: Session = Depends(get_db)):
    _check_role(body.role)
    plain, prefix, key_hash = new_api_key()
    key = ApiKey(tenant_id=p.tenant_id, name=body.name, prefix=prefix, key_hash=key_hash, role=body.role)
    db.add(key)
    db.flush()
    audit.log(db, p, "api_key_created", f"{body.name} role={body.role} prefix={prefix}")
    db.commit()
    return {"id": key.id, "name": key.name, "role": key.role, "api_key": plain,
            "note": "Store this key now: it is shown only once and cannot be retrieved later."}


@router.delete("/api-keys/{key_id}")
def revoke_key(key_id: int, p: Principal = Depends(require("admin")), db: Session = Depends(get_db)):
    key = db.query(ApiKey).filter_by(id=key_id, tenant_id=p.tenant_id).first()
    if not key:
        raise HTTPException(404, "API key not found")
    key.is_active = False
    audit.log(db, p, "api_key_revoked", f"{key.name} prefix={key.prefix}")
    db.commit()
    return {"ok": True}


@router.get("/audit-logs")
def audit_logs(limit: int = 50, p: Principal = Depends(require("admin")), db: Session = Depends(get_db)):
    rows = (db.query(AuditLog).filter(AuditLog.tenant_id == p.tenant_id)
            .order_by(AuditLog.id.desc()).limit(min(limit, 200)).all())
    return [{"time": r.created_at.isoformat() if r.created_at else None, "actor": r.actor, "action": r.action,
             "detail": r.detail} for r in rows]
