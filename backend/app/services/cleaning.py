import re

import pandas as pd

REQUIRED = ["txn_date", "supplier_name", "description", "quantity", "unit_price"]

# Vague descriptions say nothing about WHAT was bought, so they must not be used as an "item"
# for price comparison or anomaly detection (they mix unrelated purchases together).
GENERIC_ITEMS = {
    "misc purchase",
    "invoice payment",
    "general expenses",
    "service charges",
    "payment as per po",
    "annual renewal",
    "monthly charges",
    "maintenance charges",
    "",
}


class ValidationError(Exception):
    pass


def derive_item(desc: str) -> str:
    s = re.sub(r"(?i)\b(po|inv)[- ]?\d+\b", " ", str(desc))
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-zA-Z ]", " ", s).lower()
    return " ".join(s.split())


def clean_dataframe(df: pd.DataFrame):
    """Validate + clean an uploaded CSV. Returns (clean_df, report)."""
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValidationError(f"Missing required columns: {missing}")
    total = len(df)

    for c in ("supplier_name", "description"):
        df[c] = df[c].astype(str).str.strip()
    df["txn_date"] = pd.to_datetime(df["txn_date"], errors="coerce").dt.date
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce")
    if "amount" not in df.columns:
        df["amount"] = df["quantity"] * df["unit_price"]
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(
        df["quantity"] * df["unit_price"]
    )
    if "supplier_email" not in df.columns:
        df["supplier_email"] = ""
    df["supplier_email"] = (
        df["supplier_email"].fillna("").astype(str).str.strip().str.lower()
    )
    if "item" not in df.columns:
        df["item"] = ""
    df["item"] = df["item"].fillna("").astype(str).str.strip().str.lower()
    mask_blank = df["item"] == ""
    df.loc[mask_blank, "item"] = df.loc[mask_blank, "description"].map(derive_item)

    bad = (
        df["txn_date"].isna()
        | df["quantity"].isna()
        | df["unit_price"].isna()
        | (df["quantity"] <= 0)
        | (df["unit_price"] <= 0)
        | df["supplier_name"].isin(["", "nan"])
        | df["description"].isin(["", "nan"])
    )
    rejected_invalid = int(bad.sum())
    df = df[~bad]
    before = len(df)
    df = df.drop_duplicates(
        subset=["txn_date", "supplier_name", "description", "quantity", "unit_price"]
    )
    report = {
        "rows_total": total,
        "rejected_invalid": rejected_invalid,
        "rejected_duplicates": before - len(df),
        "rows_clean": len(df),
    }
    return df.reset_index(drop=True), report
