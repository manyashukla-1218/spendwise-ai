"""Central configuration. Everything is overridable with environment variables."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'spendwise.db'}")
REDIS_URL = os.getenv("REDIS_URL", "")
USE_CELERY = os.getenv("USE_CELERY", "false").lower() == "true"

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "data" / "uploads"))
MODEL_DIR = Path(os.getenv("MODEL_DIR", BASE_DIR / "ml" / "saved_models"))
TRAIN_FILE = Path(
    os.getenv("TRAIN_FILE", BASE_DIR / "data" / "generated" / "train_labeled.csv")
)

# Classification: below this confidence a transaction goes to the human review queue
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.60"))

# Supplier entity resolution thresholds (RapidFuzz token_sort_ratio, 0-100)
SUPPLIER_AUTO_MERGE = float(os.getenv("SUPPLIER_AUTO_MERGE", "90"))
SUPPLIER_REVIEW = float(os.getenv("SUPPLIER_REVIEW", "78"))

RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "120"))

# Copilot LLM (OpenAI-compatible endpoint: Groq / Gemini / OpenRouter ...)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")

# Demo tenants (id, name, api_key). Change keys before any real use.
DEMO_TENANTS = [
    ("acme", "Acme Manufacturing", "demo-acme-key"),
    ("nova", "Nova Retail", "demo-nova-key"),
    ("orbit", "Orbit Logistics", "demo-orbit-key"),
]
