import uuid

import pytest
from sqlalchemy import text

from backend.app import config, security
from backend.app.database import SessionLocal

PW = config.DEMO_USER_PASSWORD
ADMIN_KEY = {"X-API-Key": "demo-acme-key"}


def login(client, email, password=PW):
    return client.post("/auth/login", json={"email": email, "password": password})


def bearer(client, email, password=PW):
    r = login(client, email, password)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_no_or_bad_credentials_rejected(client):
    assert client.get("/analytics/overview").status_code == 401
    assert (
        client.get("/analytics/overview", headers={"X-API-Key": "nope"}).status_code
        == 401
    )
    assert (
        client.get(
            "/analytics/overview", headers={"Authorization": "Bearer not.a.jwt"}
        ).status_code
        == 401
    )


def test_login_and_me(client):
    r = login(client, "admin@acme.demo")
    assert (
        r.status_code == 200
        and r.json()["role"] == "admin"
        and r.json()["tenant_id"] == "acme"
    )
    me = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
    ).json()
    assert me["tenant_id"] == "acme" and me["role"] == "admin"


def test_wrong_password_and_unknown_user_look_identical(client):
    a = login(client, "admin@acme.demo", "wrong-password")
    b = login(client, f"{uuid.uuid4().hex}@nowhere.test", "wrong-password")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_role_matrix_viewer_analyst_admin(client):
    viewer, analyst, admin = (
        bearer(client, f"{r}@acme.demo") for r in ("viewer", "analyst", "admin")
    )
    csv = (
        "txn_date,supplier_name,description,quantity,unit_price\n"
        "2026-01-01,Alpha Traders,Laptop 14 inch,1,58000\n"
    ).encode()
    files = {"file": ("rbac_test.csv", csv, "text/csv")}
    # viewer: read-only
    assert client.get("/analytics/overview", headers=viewer).status_code == 200
    assert client.post("/uploads", files=files, headers=viewer).status_code == 403
    assert (
        client.post(
            "/copilot", json={"question": "top suppliers"}, headers=viewer
        ).status_code
        == 403
    )
    assert client.post("/review/retrain", headers=viewer).status_code == 403
    assert client.get("/auth/users", headers=viewer).status_code == 403
    # analyst: can work, cannot administer
    assert (
        client.post(
            "/copilot", json={"question": "top suppliers"}, headers=analyst
        ).status_code
        == 200
    )
    assert client.post("/review/retrain", headers=analyst).status_code == 403
    assert client.get("/auth/api-keys", headers=analyst).status_code == 403
    # admin: passes the permission gate (retrain then fails for a business reason: no feedback), can manage users
    assert client.post("/review/retrain", headers=admin).status_code != 403
    assert client.get("/auth/users", headers=admin).status_code == 200


def test_admin_creates_user_and_passwords_are_hashed(client):
    admin = bearer(client, "admin@acme.demo")
    email = f"{uuid.uuid4().hex[:8]}@acme.test"
    r = client.post(
        "/auth/users",
        json={"email": email, "password": "correct-horse-1", "role": "viewer"},
        headers=admin,
    )
    assert r.status_code == 201
    assert (
        client.post(
            "/auth/users",
            json={"email": email, "password": "correct-horse-1", "role": "viewer"},
            headers=admin,
        ).status_code
        == 409
    )  # duplicate
    assert (
        client.post(
            "/auth/users",
            json={"email": "x@y.test", "password": "short", "role": "viewer"},
            headers=admin,
        ).status_code
        == 422
    )  # weak password
    assert (
        client.post(
            "/auth/users",
            json={"email": "z@y.test", "password": "long-enough-1", "role": "god"},
            headers=admin,
        ).status_code
        == 422
    )  # unknown role
    assert login(client, email, "correct-horse-1").status_code == 200
    with SessionLocal() as db:
        h = db.execute(
            text("select password_hash from users where email=:e"), {"e": email}
        ).scalar()
    assert h.startswith("scrypt$") and "correct-horse-1" not in h


def test_api_key_lifecycle_and_hashed_storage(client):
    admin = bearer(client, "admin@acme.demo")
    r = client.post(
        "/auth/api-keys", json={"name": "ci-bot", "role": "viewer"}, headers=admin
    )
    assert r.status_code == 201
    plain, kid = r.json()["api_key"], r.json()["id"]
    assert plain.startswith("sw_")
    listed = client.get("/auth/api-keys", headers=admin).json()
    assert all(
        "api_key" not in k and "key_hash" not in k for k in listed
    )  # never shown again
    with SessionLocal() as db:  # plaintext is nowhere in the DB
        rows = db.execute(
            text("select name, prefix, key_hash, role from api_keys")
        ).fetchall()
    assert not any(plain in str(v) for row in rows for v in row)
    h = {"X-API-Key": plain}
    assert client.get("/analytics/overview", headers=h).status_code == 200
    assert (
        client.post("/review/retrain", headers=h).status_code == 403
    )  # viewer key cannot retrain
    assert client.delete(f"/auth/api-keys/{kid}", headers=admin).status_code == 200
    assert client.get("/analytics/overview", headers=h).status_code == 401  # revoked


def test_tokens_expired_tampered_and_wrong_secret_rejected(client):
    with SessionLocal() as db:
        uid = db.execute(
            text("select id from users where email='admin@acme.demo'")
        ).scalar()
    expired = security.create_token(uid, "acme", "admin", ttl_minutes=-1)
    assert (
        client.get(
            "/auth/me", headers={"Authorization": f"Bearer {expired}"}
        ).status_code
        == 401
    )
    good = security.create_token(uid, "acme", "admin")
    tampered = good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB")
    assert (
        client.get(
            "/auth/me", headers={"Authorization": f"Bearer {tampered}"}
        ).status_code
        == 401
    )
    # a token claiming a different tenant than the user's real tenant is refused
    forged = security.create_token(uid, "nova", "admin")
    assert (
        client.get(
            "/auth/me", headers={"Authorization": f"Bearer {forged}"}
        ).status_code
        == 401
    )


def test_role_is_read_from_database_not_from_token(client):
    admin = bearer(client, "admin@acme.demo")
    email = f"{uuid.uuid4().hex[:8]}@acme.test"
    uid = client.post(
        "/auth/users",
        json={"email": email, "password": "correct-horse-1", "role": "viewer"},
        headers=admin,
    ).json()["id"]
    with SessionLocal() as db:  # craft a token that CLAIMS admin for a viewer
        forged = security.create_token(uid, "acme", "admin")
    h = {"Authorization": f"Bearer {forged}"}
    assert client.get("/auth/me", headers=h).json()["role"] == "viewer"
    assert client.post("/review/retrain", headers=h).status_code == 403
    # deactivating a user kills their existing token immediately
    assert (
        client.post(f"/auth/users/{uid}/deactivate", headers=admin).status_code == 200
    )
    assert client.get("/auth/me", headers=h).status_code == 401


def test_users_and_keys_are_tenant_scoped(client):
    nova = bearer(client, "admin@nova.demo")
    emails = [u["email"] for u in client.get("/auth/users", headers=nova).json()]
    assert emails and all(
        e.endswith("@nova.demo") or e.endswith("@nova.test") for e in emails
    )
    acme_key_id = client.get("/auth/api-keys", headers=ADMIN_KEY).json()[0]["id"]
    assert (
        client.delete(f"/auth/api-keys/{acme_key_id}", headers=nova).status_code == 404
    )


def test_audit_log_records_the_actor(client):
    admin = bearer(client, "admin@acme.demo")
    client.post(
        "/auth/api-keys", json={"name": "audit-check", "role": "viewer"}, headers=admin
    )
    logs = client.get("/auth/audit-logs?limit=20", headers=admin).json()
    hit = [
        x
        for x in logs
        if x["action"] == "api_key_created" and "audit-check" in x["detail"]
    ]
    assert hit and hit[0]["actor"] == "admin@acme.demo"


def test_login_brute_force_is_throttled(client):
    email = f"{uuid.uuid4().hex}@brute.test"
    codes = [
        login(client, email, "guess").status_code
        for _ in range(config.LOGIN_MAX_ATTEMPTS + 2)
    ]
    assert codes[0] == 401 and codes[-1] == 429


def test_rate_limit_per_tenant(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MIN", 5)
    h = {"X-API-Key": "demo-orbit-key"}
    codes = [client.get("/analytics/overview", headers=h).status_code for _ in range(8)]
    assert 429 in codes and codes[0] == 200


def test_production_refuses_insecure_defaults(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "SEED_DEMO", True)
    monkeypatch.setattr(config, "JWT_SECRET", "dev-insecure-secret-change-me")
    with pytest.raises(RuntimeError):
        config.validate_security()
    monkeypatch.setattr(config, "SEED_DEMO", False)
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)
    config.validate_security()  # secure configuration is accepted


def test_password_hash_roundtrip():
    h = security.hash_password("s3cret-pass")
    assert security.verify_password("s3cret-pass", h) and not security.verify_password(
        "other", h
    )
    assert not security.verify_password("s3cret-pass", "garbage")


def test_create_admin_script_makes_a_working_admin(client):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "create_admin", config.BASE_DIR / "scripts" / "create_admin.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    email = f"{uuid.uuid4().hex[:8]}@prod.test"
    tenant = f"prod{uuid.uuid4().hex[:6]}"
    mod.create_admin(tenant, "Prod Co", email, "a-long-password-1")
    r = login(client, email, "a-long-password-1")
    assert (
        r.status_code == 200
        and r.json()["role"] == "admin"
        and r.json()["tenant_id"] == tenant
    )
    with pytest.raises(ValueError):
        mod.create_admin(tenant, "Prod Co", email, "a-long-password-1")  # duplicate
    with pytest.raises(ValueError):
        mod.create_admin(tenant, "Prod Co", "x@y.test", "short")  # weak password
