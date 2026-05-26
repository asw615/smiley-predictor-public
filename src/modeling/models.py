"""Three-class classifiers for the per-visit panel.

Target: {0 = happy, 1 = neutral, 2 = sad}. Every model implements `.fit(X, y)`
and `.predict_proba(X) -> (n, 3)`. No class weighting, no calibration, no
hyperparameter tuning.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

N_CLASSES = 3

TABULAR_COLS = [
    "log1p_review_count",
    "mean_star",
    "share_low_star",
]

# Six per-category indicators. The aggregate `any` flag is redundant (OR of
# these six) and `_rate` collinear with `_any` for one-review windows.
LLM_HYGIENE_COLS = [
    "llm_pest_or_vermin_any",
    "llm_foreign_object_in_food_any",
    "llm_food_safety_concern_any",
    "llm_visible_dirtness_any",
    "llm_staff_hygiene_any",
    "llm_illness_after_eating_any",
]

XGB_PARAMS = dict(
    n_estimators=400,
    max_depth=5,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    objective="multi:softprob",
    num_class=N_CLASSES,
    eval_metric="mlogloss",
    tree_method="hist",
    n_jobs=-1,
    random_state=42069,
)


class PrevalenceBaseline:
    """Predict the training-fold per-class marginal for every test row."""

    name = "baseline_prevalence"

    def fit(self, X, y) -> "PrevalenceBaseline":
        y = np.asarray(y).astype(int)
        rates = np.zeros(N_CLASSES, dtype=np.float64)
        for c in range(N_CLASSES):
            rates[c] = float((y == c).mean())
        self.rates_ = rates
        return self

    def predict_proba(self, X) -> np.ndarray:
        n = len(X) if hasattr(X, "__len__") else X.shape[0]
        return np.tile(self.rates_, (n, 1))


@dataclass
class _SklearnPipelineModel:
    name: str
    pipeline: Pipeline

    def fit(self, X, y):
        self.pipeline.fit(X, y)
        return self

    def predict_proba(self, X) -> np.ndarray:
        return self.pipeline.predict_proba(X)


def _linear_pipeline() -> Pipeline:
    # multinomial is the default for multi-class lbfgs since sklearn 1.5.
    return Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value=0.0)),
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(max_iter=2000, random_state=42069)),
    ])


def lr_summary() -> _SklearnPipelineModel:
    return _SklearnPipelineModel(name="lr_summary", pipeline=_linear_pipeline())


def lr_summary_llm() -> _SklearnPipelineModel:
    return _SklearnPipelineModel(name="lr_summary_llm", pipeline=_linear_pipeline())


class XGBMultinomial:
    """Wrapper around XGBClassifier that exposes `predict_proba` returning (n, 3)."""

    def __init__(self, name: str, **xgb_kwargs):
        self.name = name
        params = {**XGB_PARAMS, **xgb_kwargs}
        self.clf = XGBClassifier(**params)

    def fit(self, X, y):
        self.clf.fit(X, y)
        return self

    def predict_proba(self, X) -> np.ndarray:
        return self.clf.predict_proba(X)


def xgb_summary() -> XGBMultinomial:
    return XGBMultinomial(name="xgb_summary")


def xgb_summary_llm() -> XGBMultinomial:
    return XGBMultinomial(name="xgb_summary_llm")


def build_feature_matrix(features_df, *, kind: str):
    """Return (X, feature_names) for one of: baseline, summary, summary_llm."""
    if kind == "baseline":
        return np.zeros((len(features_df), 1), dtype=np.float32), ["_intercept"]
    if kind == "summary":
        X = features_df[TABULAR_COLS].to_numpy(dtype=np.float32)
        return X, list(TABULAR_COLS)
    if kind == "summary_llm":
        missing = [c for c in LLM_HYGIENE_COLS if c not in features_df.columns]
        if missing:
            raise ValueError(f"features_df is missing LLM hygiene columns: {missing}")
        cols = TABULAR_COLS + LLM_HYGIENE_COLS
        X = features_df[cols].to_numpy(dtype=np.float32)
        return X, list(cols)
    raise ValueError(f"unknown kind: {kind!r}")
