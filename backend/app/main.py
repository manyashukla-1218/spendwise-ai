from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import config
from .api import analytics, auth, copilot, review, uploads
from .cache import cache
from .database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.validate_security()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title="SpendWise AI", version="1.0", lifespan=lifespan,
              description="Procurement spend intelligence: supplier resolution, AI classification, "
                          "anomaly detection, human review loop and an analytics copilot.")
for r in (auth.router, uploads.router, analytics.router, review.router, copilot.router):
    app.include_router(r)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "cache": cache.kind, "queue": "celery" if config.USE_CELERY else "background-tasks"}
