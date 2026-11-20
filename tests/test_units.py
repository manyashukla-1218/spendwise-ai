import pandas as pd

from backend.app.services import anomaly, cleaning
from backend.app.services.normalization import normalize_name


def test_supplier_name_normalization():
    assert normalize_name("Alpha Technologies Pvt. Ltd.") == "alpha technologies"
    assert normalize_name("ALPHA TECHNOLOGIES PRIVATE LIMITED") == "alpha technologies"
    assert normalize_name("A.B.C. Limited") == "abc"


def test_cleaning_rejects_bad_rows_and_duplicates():
    df = pd.DataFrame(
        {
            "txn_date": ["2026-01-01", "2026-01-01", "not-a-date", "2026-01-03"],
            "supplier_name": ["A", "A", "B", "C"],
            "description": ["x", "x", "y", "z"],
            "quantity": [1, 1, 1, -5],
            "unit_price": [10, 10, 10, 10],
        }
    )
    clean, rep = cleaning.clean_dataframe(df)
    assert (
        len(clean) == 1
        and rep["rejected_duplicates"] == 1
        and rep["rejected_invalid"] == 2
    )


def test_anomaly_detector_flags_injected_outliers():
    rows = [
        {
            "item": "laptop",
            "unit_price": 58000 + (i % 7) * 300,
            "quantity": 2,
            "amount": 0,
        }
        for i in range(120)
    ]
    rows[5]["unit_price"] = 190000
    rows[60]["unit_price"] = 210000
    df = pd.DataFrame(rows)
    df["amount"] = df["unit_price"] * df["quantity"]
    out = anomaly.detect(df)
    assert out.loc[[5, 60], "is_anomaly"].all()
    assert out["is_anomaly"].sum() <= 6


def test_vague_items_are_not_flagged_as_anomalies():
    rows = [
        {
            "item": "laptop",
            "unit_price": 58000 + (i % 7) * 300,
            "quantity": 2,
            "amount": 0,
        }
        for i in range(120)
    ]
    # a vague 'item' mixes unrelated purchases -> huge price spread, but must NOT be flagged
    rows += [
        {"item": "misc purchase", "unit_price": p, "quantity": 1, "amount": 0}
        for p in (300, 450, 90000, 250000, 1200, 700)
    ]
    df = pd.DataFrame(rows)
    df["amount"] = df["unit_price"] * df["quantity"]
    out = anomaly.detect(df)
    assert not out.loc[out["item"] == "misc purchase", "is_anomaly"].any()


def test_cache_version_bump_and_zero_ttl():
    from backend.app.cache import bump_version, cache, tenant_version

    v = tenant_version("t-x")
    bump_version("t-x")  # uses ttl=0 ("no expiry"); Redis used to reject this
    assert tenant_version("t-x") == v + 1
    cache.set("k-ttl0", {"a": 1}, ttl=0)
    assert cache.get("k-ttl0") == {"a": 1}
