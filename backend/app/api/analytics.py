from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..cache import cached
from ..database import get_db
from ..deps import Principal, require
from ..models import Transaction
from ..services import analytics as A

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _df(db, t):
    return A.load_df(db, t.id)


@router.get("/overview")
def overview(t: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    return cached(t.id, "overview", lambda: A.overview(_df(db, t), db, t.id))


@router.get("/categories")
def categories(t: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    return cached(t.id, "categories", lambda: A.spend_by_category(_df(db, t)))


@router.get("/suppliers")
def suppliers(n: int = Query(10, le=100), category: str | None = None,
              t: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    return cached(t.id, f"suppliers:{n}:{category}", lambda: A.top_suppliers(_df(db, t), n, category))


@router.get("/trend")
def trend(t: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    return cached(t.id, "trend", lambda: A.monthly_trend(_df(db, t)))


@router.get("/price-variance")
def price_variance(t: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    return cached(t.id, "pv", lambda: A.price_variance(_df(db, t)))


@router.get("/tail-spend")
def tail_spend(t: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    return cached(t.id, "tail", lambda: A.tail_spend(_df(db, t)))


@router.get("/anomalies")
def anomalies(limit: int = Query(50, le=200), offset: int = 0,
              t: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    return A.anomalies(_df(db, t), limit, offset)


@router.get("/transactions")
def transactions(limit: int = Query(50, le=200), offset: int = 0, category: str | None = None,
                 t: Principal = Depends(require("viewer")), db: Session = Depends(get_db)):
    q = db.query(Transaction).filter(Transaction.tenant_id == t.id)         # pagination + tenant filter
    if category:
        q = q.filter(Transaction.category == category)
    total = q.count()
    rows = q.order_by(Transaction.id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [{
        "id": r.id, "date": str(r.txn_date), "supplier_id": r.supplier_id, "description": r.description,
        "amount": r.amount, "category": r.category, "confidence": r.confidence,
        "review_status": r.review_status} for r in rows]}
