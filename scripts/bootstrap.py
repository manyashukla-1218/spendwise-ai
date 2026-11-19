"""Run once before starting the API: makes sure data exists and the base model is trained."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app import config  # noqa: E402

if not config.TRAIN_FILE.exists():
    from scripts import generate_data
    generate_data.main()
if not (config.MODEL_DIR / "base.joblib").exists():
    from backend.app.services import classification
    m = classification.train_base()
    print(f"Base model trained: accuracy={m['accuracy']:.3f} macro_f1={m['macro_f1']:.3f}")
