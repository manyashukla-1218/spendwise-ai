"""Spend classification: TF-IDF (word + char n-grams) + Logistic Regression, with confidence scores.
Low-confidence predictions go to the human review queue; reviewer feedback is used to retrain.
"""

import json
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline

from .. import config
from ..models import Feedback, ModelVersion

_cache = {}


def build_pipeline():
    feats = FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    ngram_range=(1, 2), sublinear_tf=True, lowercase=True, min_df=1
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    sublinear_tf=True,
                    lowercase=True,
                    min_df=2,
                ),
            ),
        ]
    )
    return Pipeline(
        [("tfidf", feats), ("clf", LogisticRegression(max_iter=400, C=8.0))]
    )


def load_base_split():
    if not config.TRAIN_FILE.exists():
        raise FileNotFoundError(
            f"{config.TRAIN_FILE} not found. Run: python scripts/generate_data.py"
        )
    df = pd.read_csv(config.TRAIN_FILE)[["description", "category"]].dropna()
    return train_test_split(
        df["description"],
        df["category"],
        test_size=0.2,
        random_state=42,
        stratify=df["category"],
    )


def _evaluate(model, X_test, y_test):
    pred = model.predict(X_test)
    labels = sorted(set(y_test))
    return {
        "accuracy": float(accuracy_score(y_test, pred)),
        "macro_f1": float(f1_score(y_test, pred, average="macro")),
        "report": classification_report(
            y_test, pred, output_dict=True, zero_division=0
        ),
        "labels": labels,
        "confusion_matrix": confusion_matrix(y_test, pred, labels=labels).tolist(),
        "n_test": int(len(y_test)),
    }


def train_base():
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    Xtr, Xte, ytr, yte = load_base_split()
    model = build_pipeline().fit(Xtr, ytr)
    metrics = _evaluate(model, Xte, yte)
    metrics.update(
        {
            "n_train": int(len(ytr)),
            "trained_at": datetime.utcnow().isoformat(),
            "version": "base",
        }
    )
    joblib.dump(model, config.MODEL_DIR / "base.joblib")
    (config.MODEL_DIR / "base_metrics.json").write_text(json.dumps(metrics, indent=2))
    _cache.pop("base", None)
    return metrics


def _path(tenant_id):
    p = config.MODEL_DIR / f"{tenant_id}.joblib"
    return p if p.exists() else config.MODEL_DIR / "base.joblib"


def get_model(tenant_id):
    p = _path(tenant_id)
    if not p.exists():
        train_base()
        p = _path(tenant_id)
    key = (str(p), p.stat().st_mtime)
    if key not in _cache:
        _cache.clear()
        _cache[key] = joblib.load(p)
    version = (
        "base" if p.name == "base.joblib" else f"{tenant_id}-{int(p.stat().st_mtime)}"
    )
    return _cache[key], version


def predict(model, texts):
    proba = model.predict_proba(list(texts))
    idx = proba.argmax(axis=1)
    classes = model.classes_
    return [classes[i] for i in idx], proba.max(axis=1), proba


def top_k(model, text, k=3):
    proba = model.predict_proba([text])[0]
    order = np.argsort(proba)[::-1][:k]
    return [
        {"category": model.classes_[i], "confidence": round(float(proba[i]), 3)}
        for i in order
    ]


def retrain_tenant(db, tenant_id):
    """Base training data + this tenant's human-corrected rows -> new tenant model."""
    Xtr, Xte, ytr, yte = load_base_split()
    fb = db.query(Feedback).filter(Feedback.tenant_id == tenant_id).all()
    if not fb:
        raise ValueError(
            "No reviewer feedback yet. Correct some items in the review queue first."
        )
    fb_X = pd.Series([f.description for f in fb])
    fb_y = pd.Series([f.correct_category for f in fb])
    # human corrections are valuable: weight them by repeating (simple, transparent approach)
    X = pd.concat([Xtr, fb_X, fb_X, fb_X], ignore_index=True)
    y = pd.concat([ytr, fb_y, fb_y, fb_y], ignore_index=True)
    model = build_pipeline().fit(X, y)
    m = _evaluate(model, Xte, yte)
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, config.MODEL_DIR / f"{tenant_id}.joblib")
    mv = ModelVersion(
        tenant_id=tenant_id,
        version=f"{tenant_id}-{datetime.utcnow():%Y%m%d%H%M%S}",
        accuracy=m["accuracy"],
        macro_f1=m["macro_f1"],
        n_train=int(len(y)),
        n_feedback=len(fb),
    )
    db.add(mv)
    db.commit()
    _cache.clear()
    return {
        "version": mv.version,
        "accuracy_on_base_holdout": m["accuracy"],
        "macro_f1": m["macro_f1"],
        "n_train": int(len(y)),
        "n_feedback_rows": len(fb),
    }
