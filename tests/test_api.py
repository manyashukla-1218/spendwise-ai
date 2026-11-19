import time
from pathlib import Path

from tests.conftest import A, B

DATA = Path(__file__).resolve().parents[1] / "data" / "generated"


def _wait(client, headers, upload_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/uploads/{upload_id}", headers=headers).json()
        if r["status"] in ("done", "failed"):
            return r
        time.sleep(0.5)
    raise AssertionError("timeout")


def test_requires_api_key(client):
    assert client.get("/analytics/overview").status_code == 401
    assert (
        client.get("/analytics/overview", headers={"X-API-Key": "wrong"}).status_code
        == 401
    )


def test_full_flow_idempotency_and_tenant_isolation(client):
    csv = (DATA / "tenant_orbit.csv").read_bytes()[:400_000]
    csv = csv[: csv.rfind(b"\n")]  # whole lines only (~1.7k rows)
    r = client.post(
        "/uploads", files={"file": ("orbit_small.csv", csv, "text/csv")}, headers=A
    )
    assert r.status_code == 202 and r.json()["duplicate"] is False
    up = _wait(client, A, r.json()["id"])
    assert up["status"] == "done", up
    assert up["rows_loaded"] > 1000

    # idempotency: same file again is not processed twice
    r2 = client.post(
        "/uploads", files={"file": ("again.csv", csv, "text/csv")}, headers=A
    )
    assert r2.json()["duplicate"] is True and r2.json()["id"] == r.json()["id"]

    ov = client.get("/analytics/overview", headers=A).json()
    assert ov["transactions"] == up["rows_loaded"] and ov["total_spend"] > 0
    assert ov["anomalies"] > 0

    # tenant isolation: another tenant sees nothing
    ov_b = client.get("/analytics/overview", headers=B).json()
    assert ov_b["transactions"] == 0
    assert client.get(f"/uploads/{r.json()['id']}", headers=B).status_code == 404

    # analytics endpoints work
    assert len(client.get("/analytics/categories", headers=A).json()) >= 10
    pv = client.get("/analytics/price-variance", headers=A).json()
    assert pv["total_potential_savings"] > 0
    assert client.get("/analytics/tail-spend", headers=A).json()["tail_suppliers"] > 0
    assert client.get("/analytics/anomalies?limit=5", headers=A).json()["items"]
    assert (
        client.get("/analytics/transactions?limit=10", headers=A).json()["total"]
        == ov["transactions"]
    )


def test_review_feedback_and_retrain(client):
    q = client.get("/review/classifications?limit=5", headers=A).json()
    assert q["total_pending"] > 0
    item = q["items"][0]
    cat = q["categories"][0]
    assert (
        client.post(
            f"/review/classifications/{item['id']}", json={"category": cat}, headers=A
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/review/classifications/{item['id']}",
            json={"category": "Nonsense"},
            headers=A,
        ).status_code
        == 422
    )
    # reviewer from another tenant cannot touch it
    assert (
        client.post(
            f"/review/classifications/{item['id']}", json={"category": cat}, headers=B
        ).status_code
        == 404
    )
    out = client.post("/review/retrain", headers=A).json()
    assert out["n_feedback_rows"] == 1 and out["accuracy_on_base_holdout"] > 0.8


def test_supplier_review_queue(client):
    ms = client.get("/review/suppliers", headers=A).json()
    if ms:
        r = client.post(f"/review/suppliers/{ms[0]['match_id']}/approve", headers=A)
        assert r.status_code == 200


def test_copilot_rule_based_mode(client):
    r = client.post(
        "/copilot",
        json={"question": "Which supplier has the highest spend?"},
        headers=A,
    ).json()
    assert (
        r["mode"] == "rule-based" and r["tools_used"] == ["top_suppliers"] and r["data"]
    )
    r = client.post(
        "/copilot", json={"question": "show me unusual transactions"}, headers=A
    ).json()
    assert r["tools_used"] == ["anomalies"]
