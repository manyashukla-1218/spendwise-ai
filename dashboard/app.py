"""SpendWise AI dashboard (Streamlit). Talks to the FastAPI backend only through its REST API."""
import os
import time

import pandas as pd
import requests
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")
DEMO_PASSWORD = os.getenv("DEMO_USER_PASSWORD", "demo-pass-123")
COMPANIES = {"acme": "Acme Manufacturing", "nova": "Nova Retail", "orbit": "Orbit Logistics"}
DEMO_USERS = {f"{role.title()} · {name}": f"{role}@{tid}.demo"
              for tid, name in COMPANIES.items() for role in ("admin", "analyst", "viewer")}

st.set_page_config(page_title="SpendWise AI", page_icon="📊", layout="wide")
st.sidebar.title("📊 SpendWise AI")
S = st.session_state


def logout():
    for k in ("token", "role", "tenant_id", "email"):
        S.pop(k, None)


# ---------------- sign-in ----------------
if "token" not in S:
    st.sidebar.subheader("Sign in")
    who = st.sidebar.selectbox("Demo account", list(DEMO_USERS))
    email = st.sidebar.text_input("Email", DEMO_USERS[who], key=f"email_{who}")
    password = st.sidebar.text_input("Password", DEMO_PASSWORD, type="password")
    if st.sidebar.button("Sign in", type="primary"):
        try:
            r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
            if r.status_code == 200:
                d = r.json()
                S.token, S.role, S.tenant_id, S.email = d["access_token"], d["role"], d["tenant_id"], d["email"]
                st.rerun()
            elif r.status_code == 429:
                st.sidebar.error("Too many attempts. Try again later.")
            else:
                st.sidebar.error("Incorrect email or password.")
        except Exception as e:  # noqa
            st.sidebar.error(f"Cannot reach the API: {e}")
    st.sidebar.caption("Demo accounts only (synthetic data). Roles: viewer = read-only, analyst = upload/review/copilot, "
                       "admin = everything incl. retrain and user/API-key management.")
    st.title("Sign in to SpendWise AI")
    st.info("Pick a demo account in the sidebar (the password is pre-filled) and press **Sign in**.")
    st.stop()

ROLE, TENANT_ID = S.role, S.tenant_id
tenant = COMPANIES.get(TENANT_ID, TENANT_ID)
CAN_WRITE = ROLE in ("analyst", "admin")
IS_ADMIN = ROLE == "admin"
HEAD = {"Authorization": f"Bearer {S.token}"}

st.sidebar.success(f"{S.email}\nrole: **{ROLE}**")
if st.sidebar.button("Sign out"):
    logout()
    st.rerun()
pages = ["Overview", "Upload & Jobs", "Review Queue", "Savings & Tail Spend", "Anomalies", "AI Copilot", "Model"]
if IS_ADMIN:
    pages.append("Admin")
page = st.sidebar.radio("Go to", pages)
st.sidebar.caption("Synthetic demo data only.")


def _handle_http_error(e):
    code = e.response.status_code
    if code == 401:
        logout()
        st.warning("Your session expired. Please sign in again.")
        st.stop()
    if code == 403:
        st.error("Your role does not allow this action.")
    else:
        st.error(f"{code}: {e.response.text[:300]}")


def get(path, **params):
    try:
        r = requests.get(f"{API}{path}", headers=HEAD, params=params, timeout=60)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        _handle_http_error(e)
    except Exception as e:  # noqa
        st.error(f"API error: {e}")
    return None


def post(path, **kw):
    try:
        r = requests.post(f"{API}{path}", headers=HEAD, timeout=120, **kw)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        _handle_http_error(e)
    except Exception as e:  # noqa
        st.error(f"API error: {e}")
    return None


def delete(path):
    try:
        r = requests.delete(f"{API}{path}", headers=HEAD, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        _handle_http_error(e)
    return None


def inr(x):
    return f"₹{x:,.0f}"


if page == "Overview":
    st.title(f"Spend overview · {tenant}")
    ov = get("/analytics/overview")
    if ov and ov["transactions"] == 0:
        st.info("No data yet. Go to **Upload & Jobs** and upload a tenant CSV from `data/generated/`.")
    elif ov:
        c = st.columns(5)
        c[0].metric("Total spend", inr(ov["total_spend"]))
        c[1].metric("Transactions", f"{ov['transactions']:,}")
        c[2].metric("Suppliers", ov["suppliers"])
        c[3].metric("Pending reviews", ov["pending_classification_reviews"] + ov["pending_supplier_reviews"])
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
            f = pd.DataFrame(tr["forecast"]).set_index("month")["spend"].rename("projection") if tr["forecast"] else None
            r.line_chart(pd.concat([h, f], axis=1) if f is not None else h)
            r.caption(tr.get("note", ""))
        st.subheader("Top suppliers")
        st.dataframe(pd.DataFrame(get("/analytics/suppliers", n=10)))

elif page == "Upload & Jobs":
    st.title("Upload & processing jobs")
    if CAN_WRITE:
        f = st.file_uploader("Procurement CSV", type=["csv"])
        st.caption("Required columns: txn_date, supplier_name, description, quantity, unit_price "
                   "(optional: supplier_email, item, amount)")
        if f and st.button("Upload"):
            res = post("/uploads", files={"file": (f.name, f.getvalue(), "text/csv")})
            if res:
                st.success("Duplicate file – skipped (idempotent)." if res.get("duplicate") else f"Queued as job #{res['id']}")
    else:
        st.info("Your role (viewer) can follow processing jobs but cannot upload files.")
    jobs = get("/uploads")
    if jobs:
        st.dataframe(pd.DataFrame(jobs))
        if any(j["status"] in ("queued", "processing") for j in jobs):
            time.sleep(2)
            st.rerun()

elif page == "Review Queue":
    st.title("Human-in-the-loop review")
    t1, t2 = st.tabs(["Low-confidence classifications", "Suspected duplicate suppliers"])
    with t1:
        q = get("/review/classifications", limit=10)
        if q:
            st.write(f"**{q['total_pending']}** transactions need review (lowest confidence first).")
            for it in q["items"]:
                with st.container(border=True):
                    st.write(f"**{it['description']}**  ·  {inr(it['amount'])}")
                    st.caption("Model top-3: " + " | ".join(f"{x['category']} ({x['confidence']:.0%})" for x in it["top3"]))
                    c1, c2 = st.columns([3, 1])
                    cat = c1.selectbox("Correct category", q["categories"],
                                       index=q["categories"].index(it["predicted"]), key=f"c{it['id']}")
                    if CAN_WRITE and c2.button("Confirm", key=f"b{it['id']}"):
                        post(f"/review/classifications/{it['id']}", json={"category": cat})
                        st.rerun()
            if not IS_ADMIN:
                st.caption("Confirm/correct needs the analyst role; retraining the model needs the admin role.")
            if IS_ADMIN and st.button("🔁 Retrain model with my corrections"):
                out = post("/review/retrain")
                if out:
                    st.success(f"New model {out['version']} · base-holdout accuracy {out['accuracy_on_base_holdout']:.1%} · "
                               f"{out['resolved_automatically']} pending items now auto-resolved")
    with t2:
        ms = get("/review/suppliers") or []
        st.write(f"**{len(ms)}** possible duplicates")
        for m in ms[:15]:
            with st.container(border=True):
                st.write(f"**{m['supplier_a']}** ({m['domain_a'] or 'no domain'})  ↔  **{m['supplier_b']}** "
                         f"({m['domain_b'] or 'no domain'})  ·  similarity {m['similarity']}")
                a, b = st.columns(2)
                if CAN_WRITE and a.button("Same supplier – merge", key=f"m{m['match_id']}"):
                    post(f"/review/suppliers/{m['match_id']}/approve")
                    st.rerun()
                if CAN_WRITE and b.button("Different", key=f"r{m['match_id']}"):
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
        c[0].metric("Tail suppliers", f"{ts['tail_suppliers']} of {ts['suppliers_total']}")
        c[1].metric("Share of suppliers", f"{ts['tail_supplier_share_pct']}%")
        c[2].metric("Share of spend", f"{ts['tail_spend_share_pct']}%")
        st.subheader("Consolidation candidates (categories with most tail suppliers)")
        st.dataframe(pd.DataFrame(ts["consolidation_candidates"]))

elif page == "Anomalies":
    st.title("Unusual transactions")
    an = get("/analytics/anomalies", limit=100)
    if an:
        st.write(f"**{an['total']}** flagged (robust per-item z-score + Isolation Forest)")
        st.dataframe(pd.DataFrame(an["items"]))

elif page == "AI Copilot":
    st.title("AI Procurement Copilot")
    st.caption("The model can only call validated, read-only analytics tools – no direct database access.")
    if not CAN_WRITE:
        st.info("The copilot needs the analyst role (it consumes LLM quota). Sign in as an analyst or admin.")
    else:
        q = st.text_input("Ask about your spend", "Which suppliers should we look at to save money?")
        if st.button("Ask") and q:
            res = post("/copilot", json={"question": q})
            if res:
                st.write(res["answer"])
                st.caption(f"mode: {res['mode']} · tools used: {', '.join(res['tools_used'])}")
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

elif page == "Admin":
    st.title("Administration")
    t1, t2, t3 = st.tabs(["Users", "API keys", "Audit log"])
    with t1:
        st.dataframe(pd.DataFrame(get("/auth/users") or []))
        with st.form("new_user"):
            c = st.columns(3)
            e = c[0].text_input("Email")
            pw = c[1].text_input("Password (min 8 chars)", type="password")
            ro = c[2].selectbox("Role", ["viewer", "analyst", "admin"])
            if st.form_submit_button("Create user") and e and pw:
                if post("/auth/users", json={"email": e, "password": pw, "role": ro}):
                    st.success(f"Created {e} ({ro})")
    with t2:
        keys = get("/auth/api-keys") or []
        st.dataframe(pd.DataFrame(keys))
        with st.form("new_key"):
            c = st.columns(2)
            n = c[0].text_input("Key name", "my-integration")
            ro = c[1].selectbox("Role", ["viewer", "analyst", "admin"], key="key_role")
            if st.form_submit_button("Create API key"):
                res = post("/auth/api-keys", json={"name": n, "role": ro})
                if res:
                    st.warning("Copy this key now. It is shown only once and is stored only as a hash.")
                    st.code(res["api_key"])
        kid = st.number_input("Revoke key id", min_value=0, step=1)
        if st.button("Revoke") and kid:
            if delete(f"/auth/api-keys/{int(kid)}"):
                st.success("Revoked")
                st.rerun()
    with t3:
        st.dataframe(pd.DataFrame(get("/auth/audit-logs", limit=100) or []))
