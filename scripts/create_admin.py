"""Create the first admin user for a tenant. Use this when SEED_DEMO=false (production), where no demo accounts exist.

    python scripts/create_admin.py --tenant acme --name "Acme Manufacturing" --email you@company.com
The password is asked interactively (never put it on the command line)."""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import models  # noqa: E402
from backend.app.database import SessionLocal, run_migrations  # noqa: E402
from backend.app.security import hash_password  # noqa: E402


def create_admin(tenant_id: str, tenant_name: str, email: str, password: str, role: str = "admin"):
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    run_migrations()
    with SessionLocal() as db:
        if not db.get(models.Tenant, tenant_id):
            db.add(models.Tenant(id=tenant_id, name=tenant_name))
            db.flush()
        email = email.strip().lower()
        if db.query(models.User).filter_by(email=email).first():
            raise ValueError(f"User {email} already exists")
        db.add(models.User(tenant_id=tenant_id, email=email, password_hash=hash_password(password), role=role))
        db.commit()
    return email


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--email", required=True)
    a = ap.parse_args()
    pw = getpass.getpass("Password (min 8 chars): ")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match")
    print("Created admin:", create_admin(a.tenant, a.name, a.email, pw))
