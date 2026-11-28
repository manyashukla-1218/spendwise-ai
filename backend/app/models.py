"""Database schema. Every business table carries tenant_id (multi-tenancy)."""
from datetime import datetime

from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint)

from .database import Base


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(String(40), primary_key=True)
    name = Column(String(200), nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(40), ForeignKey("tenants.id"), nullable=False, index=True)
    email = Column(String(200), unique=True, nullable=False, index=True)
    password_hash = Column(String(300), nullable=False)          # scrypt, never the password itself
    role = Column(String(20), nullable=False)                    # viewer | analyst | admin
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiKey(Base):
    """Machine credentials. Only a SHA-256 hash is stored; the key itself is shown once at creation."""
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(40), ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    prefix = Column(String(16), nullable=False)                  # first characters, for identification only
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    role = Column(String(20), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime)


class Upload(Base):
    __tablename__ = "uploads"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(40), ForeignKey("tenants.id"), index=True, nullable=False)
    filename = Column(String(300))
    file_hash = Column(String(64), nullable=False)
    status = Column(String(20), default="queued")  # queued|processing|done|failed
    rows_total = Column(Integer, default=0)
    rows_loaded = Column(Integer, default=0)
    rows_rejected = Column(Integer, default=0)
    error = Column(Text)
    duration_s = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Idempotency: the same file can't be ingested twice by the same tenant
    __table_args__ = (UniqueConstraint("tenant_id", "file_hash", name="uq_upload_tenant_hash"),)


class Supplier(Base):
    """Canonical (resolved) supplier."""
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(40), ForeignKey("tenants.id"), nullable=False)
    name = Column(String(300), nullable=False)
    norm_key = Column(String(300), nullable=False)
    email_domain = Column(String(200))
    __table_args__ = (Index("ix_supplier_tenant_key", "tenant_id", "norm_key"),)


class SupplierMatch(Base):
    """Borderline duplicate suspicion waiting for a human decision."""
    __tablename__ = "supplier_matches"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(40), ForeignKey("tenants.id"), nullable=False, index=True)
    supplier_id = Column(Integer, nullable=False)       # newly created supplier
    candidate_id = Column(Integer, nullable=False)      # existing supplier it may duplicate
    raw_name = Column(String(300))
    score = Column(Float)
    status = Column(String(20), default="pending")      # pending|approved|rejected


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(40), ForeignKey("tenants.id"), nullable=False)
    upload_id = Column(Integer, ForeignKey("uploads.id"))
    txn_date = Column(Date, nullable=False)
    raw_supplier = Column(String(300))
    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    description = Column(Text)
    item = Column(String(300))
    quantity = Column(Float)
    unit_price = Column(Float)
    amount = Column(Float)
    category = Column(String(100))          # final category (predicted or human-corrected)
    confidence = Column(Float)
    review_status = Column(String(20), default="auto")   # auto|pending|reviewed
    model_version = Column(String(50))
    anomaly_score = Column(Float)
    is_anomaly = Column(Boolean, default=False)
    anomaly_reason = Column(Text)
    __table_args__ = (
        Index("ix_txn_tenant_cat", "tenant_id", "category"),
        Index("ix_txn_tenant_supplier", "tenant_id", "supplier_id"),
        Index("ix_txn_tenant_review", "tenant_id", "review_status"),
        Index("ix_txn_tenant_date", "tenant_id", "txn_date"),
    )


class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(40), nullable=False, index=True)
    txn_id = Column(Integer, nullable=False)
    description = Column(Text)
    predicted = Column(String(100))
    correct_category = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(40), nullable=False, index=True)
    version = Column(String(50))
    accuracy = Column(Float)
    macro_f1 = Column(Float)
    n_train = Column(Integer)
    n_feedback = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(40), index=True)
    actor = Column(String(200))                                  # who did it (user email or key name)
    action = Column(String(100))
    detail = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
