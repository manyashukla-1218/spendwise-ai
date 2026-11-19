import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["REDIS_URL"] = ""
os.environ["MODEL_DIR"] = f"{_tmp}/models"
os.environ["TRAIN_FILE"] = str(ROOT / "data" / "generated" / "train_labeled.csv")
os.environ["USE_CELERY"] = "false"
os.environ["LLM_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402

A = {"X-API-Key": "demo-acme-key"}
B = {"X-API-Key": "demo-nova-key"}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
