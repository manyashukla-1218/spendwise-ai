import hashlib

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..deps import current_tenant
from ..models import AuditLog, Tenant, Upload
from ..services import pipeline

router = APIRouter(prefix="/uploads", tags=["uploads"])


def _dump(u: Upload):
    return {
        "id": u.id,
        "filename": u.filename,
        "status": u.status,
        "rows_total": u.rows_total,
        "rows_loaded": u.rows_loaded,
        "rows_rejected": u.rows_rejected,
        "error": u.error,
        "duration_s": u.duration_s,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.post("", status_code=202)
async def upload_csv(
    bg: BackgroundTasks,
    file: UploadFile = File(...),
    t: Tenant = Depends(current_tenant),
    db: Session = Depends(get_db),
):
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Only .csv files are accepted")
    h = hashlib.sha256(content).hexdigest()
    dup = db.query(Upload).filter_by(tenant_id=t.id, file_hash=h).first()
    if dup:  # idempotency
        return {
            **_dump(dup),
            "duplicate": True,
            "message": "Same file already uploaded; not processed again.",
        }
    up = Upload(tenant_id=t.id, filename=file.filename, file_hash=h, status="queued")
    db.add(up)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Duplicate upload")
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / f"{up.id}.csv").write_bytes(content)
    db.add(
        AuditLog(
            tenant_id=t.id,
            action="upload_received",
            detail=f"id={up.id} file={file.filename}",
        )
    )
    db.commit()
    if config.USE_CELERY:
        from ..workers.tasks import process_upload_task

        process_upload_task.delay(up.id)
    else:
        bg.add_task(pipeline.process_upload, up.id)
    return {**_dump(up), "duplicate": False}


@router.get("")
def list_uploads(t: Tenant = Depends(current_tenant), db: Session = Depends(get_db)):
    rows = (
        db.query(Upload)
        .filter_by(tenant_id=t.id)
        .order_by(Upload.id.desc())
        .limit(50)
        .all()
    )
    return [_dump(u) for u in rows]


@router.get("/{upload_id}")
def get_upload(
    upload_id: int, t: Tenant = Depends(current_tenant), db: Session = Depends(get_db)
):
    u = (
        db.query(Upload).filter_by(id=upload_id, tenant_id=t.id).first()
    )  # tenant-scoped lookup
    if not u:
        raise HTTPException(404, "Upload not found")
    return _dump(u)
