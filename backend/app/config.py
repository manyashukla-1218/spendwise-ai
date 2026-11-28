"""Central configuration. Everything is overridable with environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

# Load a local .env file (git-ignored) if present, e.g. LLM_API_KEY=... Real environment variables win.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:  # python-dotenv optional
    pass

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'spendwise.db'}")
REDIS_URL = os.getenv("REDIS_URL", "")
USE_CELERY = os.getenv("USE_CELERY", "false").lower() == "true"

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "data" / "uploads"))
MODEL_DIR = Path(os.getenv("MODEL_DIR", BASE_DIR / "ml" / "saved_models"))
TRAIN_FILE = Path(os.getenv("TRAIN_FILE", BASE_DIR / "data" / "generated" / "train_labeled.csv"))

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

# ---- Authentication / authorisation ----
APP_ENV = os.getenv("APP_ENV", "dev")                      # set APP_ENV=production on a real deployment
JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-secret-change-me")
JWT_TTL_MINUTES = int(os.getenv("JWT_TTL_MINUTES", "60"))
SEED_DEMO = os.getenv("SEED_DEMO", "true").lower() == "true"     # create demo users/keys (turn OFF in production)
DEMO_USER_PASSWORD = os.getenv("DEMO_USER_PASSWORD", "demo-pass-123")
LOGIN_MAX_ATTEMPTS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "10"))  # per email per 15 minutes


def validate_security():
    """Refuse to start in production with insecure defaults."""
    if APP_ENV == "production":
        problems = []
        if JWT_SECRET == "dev-insecure-secret-change-me" or len(JWT_SECRET) < 32:
            problems.append("JWT_SECRET must be set to a random string of at least 32 characters")
        if SEED_DEMO:
            problems.append("SEED_DEMO must be false (no demo users or demo API keys in production)")
        if problems:
            raise RuntimeError("Insecure production configuration: " + "; ".join(problems))
