"""SpendWise AI dashboard (Streamlit). Talks to the FastAPI backend only through its REST API."""

import os
import time

import pandas as pd
import requests
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")
TENANTS = {
    "Acme Manufacturing": "demo-acme-key",
    "Nova Retail": "demo-nova-key",
    "Orbit Logistics": "demo-orbit-key",
}

st.set_page_config(page_title="SpendWise AI", page_icon="📊", layout="wide")
st.sidebar.title("📊 SpendWise AI")
tenant = st.sidebar.selectbox("Company (tenant)", list(TENANTS))
HEAD = {"X-API-Key": TENANTS[tenant]}
page = st.sidebar.radio(
    "Go to",
    [
        "Overview",
        "Upload & Jobs",
        "Review Queue",
        "Savings & Tail Spend",
        "Anomalies",
        "AI Copilot",
        "Model",
    ],
)
st.sidebar.caption("Synthetic demo data only.")


def get(path, **params):
    try:
        r = requests.get(f"{API}{path}", headers=HEAD, params=params, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa
        st.error(f"API error: {e}")
        return None


def post(path, **kw):
    try:
        r = requests.post(f"{API}{path}", headers=HEAD, timeout=120, **kw)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        st.error(f"{e.response.status_code}: {e.response.text[:300]}")
    except Exception as e:  # noqa
        st.error(f"API error: {e}")


def inr(x):
    return f"₹{x:,.0f}"


if page == "Overview":
    st.title(f"Spend overview · {tenant}")
    ov = get("/analytics/overview")
    if ov and ov["transactions"] == 0:
        st.info(
            "No data yet. Go to **Upload & Jobs** and upload a tenant CSV from `data/generated/`."
        )
    elif ov:
        c = st.columns(5)
        c[0].metric("Total spend", inr(ov["total_spend"]))
        c[1].metric("Transactions", f"{ov['transactions']:,}")
        c[2].metric("Suppliers", ov["suppliers"])
        c[3].metric(
            "Pending reviews",
            ov["pending_classification_reviews"] + ov["pending_supplier_reviews"],
        )
        c[4].metric("Anomalies", ov["anomalies"])
        l, r = st.columns(2)
        cats = get("/analytics/categories")
        if cats:
            l.subheader("Spend by category")
            l.bar_chart(pd.DataFrame(cats).set_index("category")["spend"])
        tr = get("/analytics/trend")
        if tr:
            r.subheader("Monthly spend + 3-month projection")
            h = pd.DataFrame(tr["history"]).set_index("month")["spend"].rename("actual")
            f = (
                pd.DataFrame(tr["forecast"])
                .set_index("month")["spend"]
                .rename("projection")
                if tr["forecast"]
                else None
            )
            r.line_chart(pd.concat([h, f], axis=1) if f is not None else h)
            r.caption(tr.get("note", ""))
        st.subheader("Top suppliers")
        st.dataframe(pd.DataFrame(get("/analytics/suppliers", n=10)))

elif page == "Upload & Jobs":
    st.title("Upload & processing jobs")
    f = st.file_uploader("Procurement CSV", type=["csv"])
    st.caption(
        "Required columns: txn_date, supplier_name, description, quantity, unit_price "
        "(optional: supplier_email, item, amount)"
    )
    if f and st.button("Upload"):
        res = post("/uploads", files={"file": (f.name, f.getvalue(), "text/csv")})
        if res:
            st.success(
                "Duplicate file – skipped (idempotent)."
                if res.get("duplicate")
                else f"Queued as job #{res['id']}"
            )
    jobs = get("/uploads")
    if jobs:
        st.dataframe(pd.DataFrame(jobs))
        if any(j["status"] in ("queued", "processing") for j in jobs):
            time.sleep(2)
            st.rerun()

elif page == "Review Queue":
    st.title("Human-in-the-loop review")
    t1, t2 = st.tabs(
        ["Low-confidence classifications", "Suspected duplicate suppliers"]
    )
    with t1:
        q = get("/review/classifications", limit=10)
        if q:
            st.write(
                f"**{q['total_pending']}** transactions need review (lowest confidence first)."
            )
            for it in q["items"]:
                with st.container(border=True):
                    st.write(f"**{it['description']}**  ·  {inr(it['amount'])}")
                    st.caption(
                        "Model top-3: "
                        + " | ".join(
                            f"{x['category']} ({x['confidence']:.0%})"
                            for x in it["top3"]
                        )
                    )
                    c1, c2 = st.columns([3, 1])
                    cat = c1.selectbox(
                        "Correct category",
                        q["categories"],
                        index=q["categories"].index(it["predicted"]),
                        key=f"c{it['id']}",
                    )
                    if c2.button("Confirm", key=f"b{it['id']}"):
                        post(
                            f"/review/classifications/{it['id']}",
                            json={"category": cat},
                        )
                        st.rerun()
            if st.button("🔁 Retrain model with my corrections"):
                out = post("/review/retrain")
                if out:
                    st.success(
                        f"New model {out['version']} · base-holdout accuracy {out['accuracy_on_base_holdout']:.1%} · "
                        f"{out['resolved_automatically']} pending items now auto-resolved"
                    )
    with t2:
        ms = get("/review/suppliers") or []
        st.write(f"**{len(ms)}** possible duplicates")
        for m in ms[:15]:
            with st.container(border=True):
                st.write(
                    f"**{m['supplier_a']}** ({m['domain_a'] or 'no domain'})  ↔  **{m['supplier_b']}** "
                    f"({m['domain_b'] or 'no domain'})  ·  similarity {m['similarity']}"
                )
                a, b = st.columns(2)
                if a.button("Same supplier – merge", key=f"m{m['match_id']}"):
                    post(f"/review/suppliers/{m['match_id']}/approve")
                    st.rerun()
                if b.button("Different", key=f"r{m['match_id']}"):
                    post(f"/review/suppliers/{m['match_id']}/reject")
                    st.rerun()

elif page == "Savings & Tail Spend":
    st.title("Price variance & tail spend")
    pv = get("/analytics/price-variance")
    if pv and pv["items"]:
        st.metric("Estimated savings potential", inr(pv["total_potential_savings"]))
        st.caption(pv["note"])
        st.dataframe(pd.DataFrame(pv["items"]))
    ts = get("/analytics/tail-spend")
    if ts:
        c = st.columns(3)
        c[0].metric(
            "Tail suppliers", f"{ts['tail_suppliers']} of {ts['suppliers_total']}"
        )
        c[1].metric("Share of suppliers", f"{ts['tail_supplier_share_pct']}%")
        c[2].metric("Share of spend", f"{ts['tail_spend_share_pct']}%")
        st.subheader("Consolidation candidates (categories with most tail suppliers)")
        st.dataframe(pd.DataFrame(ts["consolidation_candidates"]))

elif page == "Anomalies":
    st.title("Unusual transactions")
    an = get("/analytics/anomalies", limit=100)
    if an:
        st.write(
            f"**{an['total']}** flagged (robust per-item z-score + Isolation Forest)"
        )
        st.dataframe(pd.DataFrame(an["items"]))

elif page == "AI Copilot":
    st.title("AI Procurement Copilot")
    st.caption(
        "The model can only call validated, read-only analytics tools – no direct database access."
    )
    q = st.text_input(
        "Ask about your spend", "Which suppliers should we look at to save money?"
    )
    if st.button("Ask") and q:
        res = post("/copilot", json={"question": q})
        if res:
            st.write(res["answer"])
            st.caption(
                f"mode: {res['mode']} · tools used: {', '.join(res['tools_used'])}"
            )
            if res.get("data"):
                with st.expander("Data used for this answer"):
                    st.json(res["data"])

elif page == "Model":
    st.title("Model versions")
    info = get("/review/model")
    if info:
        st.subheader("Base model (held-out synthetic test set)")
        st.json(info["base_model"])
        st.subheader("Tenant-specific versions (retrained with reviewer feedback)")
        st.dataframe(pd.DataFrame(info["tenant_versions"]))
