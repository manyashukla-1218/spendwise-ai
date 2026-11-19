from celery import Celery

from .. import config

celery_app = Celery("spendwise", broker=config.REDIS_URL or "memory://", backend=config.REDIS_URL or None)
celery_app.conf.task_acks_late = True
celery_app.autodiscover_tasks(["backend.app.workers"])
from . import tasks  # noqa: E402,F401
