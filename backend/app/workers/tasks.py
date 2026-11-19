from sqlalchemy.exc import OperationalError

from ..services import pipeline
from .celery_app import celery_app


@celery_app.task(name="process_upload", bind=True, autoretry_for=(OperationalError,),
                 retry_backoff=True, max_retries=3)
def process_upload_task(self, upload_id: int):
    pipeline.process_upload(upload_id)
    return {"upload_id": upload_id}
