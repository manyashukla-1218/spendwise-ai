"""Ingestion pipeline: CSV -> clean -> supplier resolution -> classification -> anomaly detection -> DB.
Runs inside a Celery worker (or a FastAPI background task when Redis/Celery is not used).
"""

import time

import pandas as pd

from .. import config
from ..cache import bump_version
from ..database import SessionLocal
from ..models import AuditLog, Transaction, Upload
from . import anomaly as anomaly_svc
from . import classification, cleaning, normalization


def recompute_anomalies(db, tenant_id):
    q = db.query(
        Transaction.id,
        Transaction.item,
        Transaction.unit_price,
        Transaction.quantity,
        Transaction.amount,
    ).filter(Transaction.tenant_id == tenant_id)
    df = pd.read_sql(q.statement, db.bind)
    if df.empty:
        return 0
    res = anomaly_svc.detect(df)
    db.bulk_update_mappings(
        Transaction,
        [
            {
                "id": int(i),
                "is_anomaly": bool(f),
                "anomaly_score": float(s),
                "anomaly_reason": r,
            }
            for i, f, s, r in zip(
                res["id"],
                res["is_anomaly"],
                res["anomaly_score"],
                res["anomaly_reason"],
            )
        ],
    )
    db.commit()
    return int(res["is_anomaly"].sum())


def process_upload(upload_id: int):
    db = SessionLocal()
    up = db.get(Upload, upload_id)
    t0 = time.time()
    try:
        up.status = "processing"
        db.commit()
        df = pd.read_csv(
            config.UPLOAD_DIR / f"{upload_id}.csv", dtype=str, keep_default_na=False
        )
        clean, rep = cleaning.clean_dataframe(df)

        pairs = list(zip(clean["supplier_name"], clean["supplier_email"]))
        mapping, sup_stats = normalization.resolve_suppliers(db, up.tenant_id, pairs)
        db.commit()

        model, version = classification.get_model(up.tenant_id)
        cats, conf, _ = classification.predict(model, clean["description"])

        rows = []
        for i, r in enumerate(clean.itertuples(index=False)):
            low = conf[i] < config.CONF_THRESHOLD
            rows.append(
                dict(
                    tenant_id=up.tenant_id,
                    upload_id=up.id,
                    txn_date=r.txn_date,
                    raw_supplier=r.supplier_name,
                    supplier_id=mapping[r.supplier_name],
                    description=r.description,
                    item=r.item,
                    quantity=float(r.quantity),
                    unit_price=float(r.unit_price),
                    amount=float(r.amount),
                    category=cats[i],
                    confidence=round(float(conf[i]), 4),
                    review_status="pending" if low else "auto",
                    model_version=version,
                )
            )
        for k in range(0, len(rows), 2000):  # batched inserts
            db.bulk_insert_mappings(Transaction, rows[k : k + 2000])
        db.commit()

        n_anom = recompute_anomalies(db, up.tenant_id)
        up.rows_total, up.rows_loaded = rep["rows_total"], len(rows)
        up.rows_rejected = rep["rejected_invalid"] + rep["rejected_duplicates"]
        up.status = "done"
        up.duration_s = round(time.time() - t0, 2)
        db.add(
            AuditLog(
                tenant_id=up.tenant_id,
                action="upload_processed",
                detail=f"upload={up.id} loaded={len(rows)} suppliers={sup_stats} anomalies={n_anom}",
            )
        )
        db.commit()
        bump_version(up.tenant_id)
    except Exception as e:  # noqa
        db.rollback()
        up = db.get(Upload, upload_id)
        up.status, up.error, up.duration_s = (
            "failed",
            str(e)[:500],
            round(time.time() - t0, 2),
        )
        db.commit()
        raise
    finally:
        db.close()
