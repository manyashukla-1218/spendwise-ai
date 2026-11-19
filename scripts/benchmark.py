"""Measure REAL numbers on your machine (use these in your README/resume, not invented ones).
Usage: python scripts/benchmark.py
Uses a temporary SQLite DB, so it never touches your real data."""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/bench.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["MODEL_DIR"] = f"{tmp}/models"
os.environ["REDIS_URL"] = ""

import pandas as pd  # noqa: E402

from backend.app import config  # noqa: E402
from backend.app.database import SessionLocal, init_db  # noqa: E402
from backend.app.models import Supplier, SupplierMatch, Transaction, Upload  # noqa: E402
from backend.app.services import classification, pipeline  # noqa: E402

if not config.TRAIN_FILE.exists():
    from scripts import generate_data
    generate_data.main()

print("== Classification (held-out 20% of labelled synthetic history) ==")
m = classification.train_base()
print(f"accuracy={m['accuracy']:.3f}  macro_f1={m['macro_f1']:.3f}  n_train={m['n_train']}  n_test={m['n_test']}")

init_db()
config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
db = SessionLocal()
print("\n== Ingestion pipeline ==")
for tid in ("acme", "nova", "orbit"):
    src = ROOT / "data" / "generated" / f"tenant_{tid}.csv"
    raw = pd.read_csv(src)
    up = Upload(tenant_id=tid, filename=src.name, file_hash=tid, status="queued")
    db.add(up)
    db.commit()
    (config.UPLOAD_DIR / f"{up.id}.csv").write_bytes(src.read_bytes())
    t0 = time.time()
    pipeline.process_upload(up.id)
    dt = time.time() - t0
    db.refresh(up)
    tx = pd.read_sql(db.query(Transaction).filter_by(tenant_id=tid).statement, db.bind)
    # accuracy vs hidden ground truth (only possible because the data is synthetic)
    key = ["txn_date", "supplier_name", "description", "quantity", "unit_price"]
    raw["txn_date"] = pd.to_datetime(raw["txn_date"]).dt.date
    mg = tx.merge(raw.drop_duplicates(subset=key), left_on=["txn_date", "raw_supplier", "description", "quantity", "unit_price"],
                  right_on=key, how="left")
    acc_all = (mg["category"] == mg["true_category"]).mean()
    auto = mg[mg["review_status"] == "auto"]
    acc_auto = (auto["category"] == auto["true_category"]).mean()
    pend = int((tx["review_status"] == "pending").sum())
    print(f"[{tid}] rows={up.rows_loaded:,} time={dt:.1f}s ({up.rows_loaded / dt:,.0f} rows/s) "
          f"suppliers={db.query(Supplier).filter_by(tenant_id=tid).count()} "
          f"supplier_reviews={db.query(SupplierMatch).filter_by(tenant_id=tid).count()} "
          f"anomalies={int(tx['is_anomaly'].sum())} "
          f"cls_acc_all={acc_all:.3f} cls_acc_auto_accepted={acc_auto:.3f} pending_review={pend} ({pend / len(tx):.1%})")
db.close()
