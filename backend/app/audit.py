from .models import AuditLog


def log(db, principal, action: str, detail: str = ""):
    """Write an audit record that says WHO did WHAT (caller commits)."""
    db.add(AuditLog(tenant_id=principal.tenant_id, actor=principal.actor, action=action, detail=detail))
