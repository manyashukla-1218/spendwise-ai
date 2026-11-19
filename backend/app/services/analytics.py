"""Analytics on a tenant's transactions (pandas). Results are JSON-friendly and cached per tenant version."""

import numpy as np
import pandas as pd
from sqlalchemy import text

from ..models import Supplier, SupplierMatch, Transaction
from .cleaning import GENERIC_ITEMS


def load_df(db, tenant_id):
    q = (
        db.query(
            Transaction.id,
            Transaction.txn_date,
            Transaction.supplier_id,
            Supplier.name.label("supplier"),
            Transaction.description,
            Transaction.item,
            Transaction.quantity,
            Transaction.unit_price,
            Transaction.amount,
            Transaction.category,
            Transaction.confidence,
            Transaction.review_status,
            Transaction.is_anomaly,
            Transaction.anomaly_score,
            Transaction.anomaly_reason,
        )
        .join(Supplier, Supplier.id == Transaction.supplier_id, isouter=True)
        .filter(Transaction.tenant_id == tenant_id)
    )
    df = pd.read_sql(q.statement, db.bind)
    if len(df):
        df["txn_date"] = pd.to_datetime(df["txn_date"])
    return df


def _r(x):
    return round(float(x), 2)


def overview(df, db, tenant_id):
    pending_cls = int((df["review_status"] == "pending").sum()) if len(df) else 0
    pending_sup = (
        db.query(SupplierMatch).filter_by(tenant_id=tenant_id, status="pending").count()
    )
    return {
        "total_spend": _r(df["amount"].sum()) if len(df) else 0,
        "transactions": int(len(df)),
        "suppliers": int(df["supplier_id"].nunique()) if len(df) else 0,
        "categories": int(df["category"].nunique()) if len(df) else 0,
        "pending_classification_reviews": pending_cls,
        "pending_supplier_reviews": pending_sup,
        "anomalies": int(df["is_anomaly"].sum()) if len(df) else 0,
    }


def spend_by_category(df):
    if not len(df):
        return []
    g = df.groupby("category").agg(
        spend=("amount", "sum"),
        txns=("id", "count"),
        suppliers=("supplier_id", "nunique"),
    )
    g = g.sort_values("spend", ascending=False).reset_index()
    g["spend"] = g["spend"].round(2)
    return g.to_dict("records")


def top_suppliers(df, n=10, category=None):
    if not len(df):
        return []
    d = df if not category else df[df["category"].str.lower() == category.lower()]
    g = (
        d.groupby("supplier")
        .agg(spend=("amount", "sum"), txns=("id", "count"))
        .sort_values("spend", ascending=False)
    )
    g = g.head(n).reset_index()
    g["spend"] = g["spend"].round(2)
    return g.to_dict("records")


def monthly_trend(df, horizon=3):
    if not len(df):
        return {"history": [], "forecast": []}
    m = df.set_index("txn_date")["amount"].resample("MS").sum()
    hist = [{"month": d.strftime("%Y-%m"), "spend": _r(v)} for d, v in m.items()]
    fc = []
    if len(m) >= 6:
        y = m.values[-12:]
        x = np.arange(len(y))
        slope, intercept = np.polyfit(x, y, 1)
        for i in range(1, horizon + 1):
            d = m.index[-1] + pd.DateOffset(months=i)
            fc.append(
                {
                    "month": d.strftime("%Y-%m"),
                    "spend": _r(max(0, intercept + slope * (len(y) - 1 + i))),
                }
            )
    return {
        "history": hist,
        "forecast": fc,
        "note": "Forecast = simple linear trend on the last 12 months (indicative only).",
    }


def price_variance(df, top=15):
    """Same item bought from several suppliers at different prices -> negotiation / consolidation potential."""
    if not len(df):
        return {"total_potential_savings": 0, "items": []}
    d = df[(~df["is_anomaly"]) & (~df["item"].str.lower().isin(GENERIC_ITEMS))]
    per = (
        d.groupby(["item", "supplier"])
        .agg(
            avg_price=("unit_price", "mean"),
            qty=("quantity", "sum"),
            txns=("id", "count"),
        )
        .reset_index()
    )
    multi = per.groupby("item")["supplier"].nunique()
    per = per[per["item"].isin(multi[multi >= 2].index)]
    # ignore suppliers with a single tiny sample so one odd invoice doesn't set the benchmark
    per_ok = per[per["txns"] >= 3]
    out, total = [], 0.0
    for item, g in per_ok.groupby("item"):
        if len(g) < 2:
            continue
        best = g.loc[g["avg_price"].idxmin()]
        worst = g.loc[g["avg_price"].idxmax()]
        savings = float(((g["avg_price"] - best["avg_price"]) * g["qty"]).sum())
        total += savings
        out.append(
            {
                "item": item,
                "suppliers": int(len(g)),
                "best_supplier": best["supplier"],
                "best_price": _r(best["avg_price"]),
                "highest_supplier": worst["supplier"],
                "highest_price": _r(worst["avg_price"]),
                "spread_pct": _r((worst["avg_price"] / best["avg_price"] - 1) * 100),
                "potential_savings": _r(savings),
            }
        )
    out.sort(key=lambda r: -r["potential_savings"])
    return {
        "total_potential_savings": _r(total),
        "items": out[:top],
        "note": "Estimate = (supplier avg price - best supplier avg price) x quantity. Assumes comparable quality/terms.",
    }


def tail_spend(df):
    """Bottom suppliers that together make only 20% of spend (long tail) + consolidation candidates."""
    if not len(df):
        return {}
    s = df.groupby("supplier")["amount"].sum().sort_values()
    total = s.sum()
    cum = s.cumsum() / total
    tail = s[cum <= 0.20]
    tail_names = set(tail.index)
    t = df[df["supplier"].isin(tail_names)]
    by_cat = (
        t.groupby("category")["supplier"]
        .nunique()
        .sort_values(ascending=False)
        .head(8)
        .rename("tail_suppliers")
        .reset_index()
    )
    return {
        "suppliers_total": int(len(s)),
        "tail_suppliers": int(len(tail)),
        "tail_supplier_share_pct": _r(len(tail) / len(s) * 100),
        "tail_spend": _r(tail.sum()),
        "tail_spend_share_pct": _r(tail.sum() / total * 100),
        "consolidation_candidates": by_cat.to_dict("records"),
        "largest_tail_suppliers": [
            {"supplier": k, "spend": _r(v)}
            for k, v in tail.sort_values(ascending=False).head(15).items()
        ],
    }


def anomalies(df, limit=50, offset=0):
    d = df[df["is_anomaly"]].sort_values("anomaly_score", ascending=False)
    cols = [
        "id",
        "txn_date",
        "supplier",
        "description",
        "quantity",
        "unit_price",
        "amount",
        "category",
        "anomaly_score",
        "anomaly_reason",
    ]
    d = d[cols].iloc[offset : offset + limit].copy()
    d["txn_date"] = d["txn_date"].dt.strftime("%Y-%m-%d")
    return {"total": int(df["is_anomaly"].sum()), "items": d.to_dict("records")}
