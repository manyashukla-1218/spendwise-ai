"""Anomaly detection on unit price: robust per-item z-score + Isolation Forest (explainable reasons)."""

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from .cleaning import GENERIC_ITEMS


def detect(df: pd.DataFrame) -> pd.DataFrame:
    """df needs: item, unit_price, quantity, amount. Adds anomaly_score, is_anomaly, anomaly_reason.
    Rows with vague/generic items are not checked (their 'item' mixes unrelated purchases).
    """
    full = df.copy()
    full["anomaly_score"], full["is_anomaly"], full["anomaly_reason"] = 0.0, False, ""
    checkable = ~full["item"].str.lower().isin(GENERIC_ITEMS)
    if checkable.sum() < 30:
        return full
    res = _detect(
        full[checkable].drop(columns=["anomaly_score", "is_anomaly", "anomaly_reason"])
    )
    for c in ("anomaly_score", "is_anomaly", "anomaly_reason"):
        full.loc[checkable, c] = res[c].values
    return full


def _detect(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["anomaly_score"] = 0.0
    df["is_anomaly"] = False
    df["anomaly_reason"] = ""
    if len(df) < 30:
        return df

    med = df.groupby("item")["unit_price"].transform("median")
    df["_ratio"] = df["unit_price"] / med
    df["_lr"] = np.log(df["_ratio"])
    grp = df.groupby("item")["_lr"]
    mad = grp.transform(lambda s: np.median(np.abs(s - np.median(s))) * 1.4826)
    cnt = grp.transform("count")
    global_mad = np.median(np.abs(df["_lr"] - np.median(df["_lr"]))) * 1.4826 or 0.05
    scale = mad.where((cnt >= 8) & (mad > 0.01), global_mad).clip(lower=0.03)
    df["_z"] = (df["_lr"] - grp.transform("median")) / scale

    feats = np.column_stack(
        [df["_lr"], np.log1p(df["quantity"]), np.log1p(df["amount"])]
    )
    iso = IsolationForest(n_estimators=150, contamination=0.01, random_state=42).fit(
        feats
    )
    df["_iso"] = -iso.score_samples(feats)  # higher = more unusual
    iso_flag = iso.predict(feats) == -1

    flag = (df["_z"].abs() > 6) | (iso_flag & (df["_ratio"] > 1.8))
    df["is_anomaly"] = flag
    df["anomaly_score"] = (df["_z"].abs() / 6).clip(upper=3).round(3)
    reasons = []
    for r, m, f in zip(df["_ratio"], med, flag):
        if not f:
            reasons.append("")
        elif r >= 1:
            reasons.append(
                f"Unit price is {r:.1f}x the typical price (median Rs {m:,.0f}) for this item"
            )
        else:
            reasons.append(
                f"Unit price is only {r:.2f}x the typical price (median Rs {m:,.0f}) for this item"
            )
    df["anomaly_reason"] = reasons
    return df.drop(columns=[c for c in df.columns if c.startswith("_")])
