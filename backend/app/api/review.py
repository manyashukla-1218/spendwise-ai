from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..cache import bump_version
from ..database import get_db
from ..deps import Principal, require
from .. import audit
from ..models import Feedback, ModelVersion, Supplier, SupplierMatch, Transaction
from ..services import classification

router = APIRouter(prefix="/review", tags=["human-in-the-loop"])


class Correction(BaseModel):
    category: str


@router.get("/classifications")
def pending_classifications(limit: int = Query(20, le=100), t: Principal = Depends(require("viewer")),
                            db: Session = Depends(get_db)):
    q = db.query(Transaction).filter_by(tenant_id=t.id, review_status="pending")
    total = q.count()
    rows = q.order_by(Transaction.confidence.asc()).limit(limit).all()
    model, _ = classification.get_model(t.id)
    return {"total_pending": total, "categories": list(model.classes_), "items": [{
        "id": r.id, "description": r.description, "amount": r.amount, "predicted": r.category,
        "confidence": r.confidence, "top3": classification.top_k(model, r.description)} for r in rows]}


@router.post("/classifications/{txn_id}")
def correct_classification(txn_id: int, body: Correction, t: Principal = Depends(require("analyst")),
                           db: Session = Depends(get_db)):
    r = db.query(Transaction).filter_by(id=txn_id, tenant_id=t.id).first()
    if not r:
        raise HTTPException(404, "Transaction not found")
    model, _ = classification.get_model(t.id)
    if body.category not in set(model.classes_):
        raise HTTPException(422, f"Unknown category. Use one of: {list(model.classes_)}")
    db.add(Feedback(tenant_id=t.id, txn_id=r.id, description=r.description, predicted=r.category,
                    correct_category=body.category))
    r.category, r.review_status, r.confidence = body.category, "reviewed", 1.0
    audit.log(db, t, "classification_corrected", f"txn={r.id} -> {body.category}")
    db.commit()
    bump_version(t.id)
    return {"ok": True}


@router.post("/retrain")
def retrain(t: Principal = Depends(require("admin")), db: Session = Depends(get_db)):
    try:
        info = classification.retrain_tenant(db, t.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    model, version = classification.get_model(t.id)
    pend = db.query(Transaction).filter_by(tenant_id=t.id, review_status="pending").all()
    moved = 0
    if pend:
        cats, conf, _ = classification.predict(model, [p.description for p in pend])
        from ..config import CONF_THRESHOLD
        for p, c, cf in zip(pend, cats, conf):
            p.category, p.confidence, p.model_version = c, round(float(cf), 4), version
            if cf >= CONF_THRESHOLD:
                p.review_status = "auto"
                moved += 1
    audit.log(db, t, "model_retrained", str(info))
    db.commit()
    bump_version(t.id)
    return {**info, "pending_reclassified": len(pend), "resolved_automatically": moved}


@router.get("/model")
def model_info(t: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    import json
    from .. import config
    base = {}
    p = config.MODEL_DIR / "base_metrics.json"
    if p.exists():
        m = json.loads(p.read_text())
        base = {k: m[k] for k in ("accuracy", "macro_f1", "n_train", "n_test", "trained_at")}
    versions = db.query(ModelVersion).filter_by(tenant_id=t.id).order_by(ModelVersion.id.desc()).limit(10).all()
    return {"base_model": base, "tenant_versions": [{
        "version": v.version, "accuracy": v.accuracy, "macro_f1": v.macro_f1, "n_feedback": v.n_feedback,
        "created_at": v.created_at.isoformat()} for v in versions]}


@router.get("/suppliers")
def pending_supplier_matches(t: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    ms = db.query(SupplierMatch).filter_by(tenant_id=t.id, status="pending").order_by(SupplierMatch.score.desc()).limit(50).all()
    out = []
    for m in ms:
        a, b = db.get(Supplier, m.supplier_id), db.get(Supplier, m.candidate_id)
        if a and b:
            out.append({"match_id": m.id, "supplier_a": a.name, "domain_a": a.email_domain,
                        "supplier_b": b.name, "domain_b": b.email_domain, "similarity": m.score})
    return out


@router.post("/suppliers/{match_id}/{decision}")
def decide_supplier_match(match_id: int, decision: str, t: Principal = Depends(require("analyst")),
                          db: Session = Depends(get_db)):
    if decision not in ("approve", "reject"):
        raise HTTPException(422, "decision must be approve or reject")
    m = db.query(SupplierMatch).filter_by(id=match_id, tenant_id=t.id, status="pending").first()
    if not m:
        raise HTTPException(404, "Match not found")
    if decision == "approve":      # merge new supplier into the existing one
        db.query(Transaction).filter_by(tenant_id=t.id, supplier_id=m.supplier_id).update({"supplier_id": m.candidate_id})
        s = db.get(Supplier, m.supplier_id)
        if s:
            db.delete(s)
        m.status = "approved"
    else:
        m.status = "rejected"
    audit.log(db, t, f"supplier_match_{decision}d", f"match={m.id}")
    db.commit()
    bump_version(t.id)
    return {"ok": True, "status": m.status}
