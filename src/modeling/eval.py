"""5-fold place-grouped CV on the 3-class smiley target.

Reports per-class PR-AUC and ROC-AUC (one-vs-rest), a derived not-happy PR-AUC
(PR-AUC of `1 - p_happy` against `y != happy`), top-label ECE, and precision
at the top decile of the not-happy score. All rank metrics carry
restaurant-clustered percentile bootstrap 95% CIs from 2,000 resamples.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold

from src.features.tabular import OUT_PATH as FEATURES_PATH
from src.modeling.models import (
    LLM_HYGIENE_COLS,
    N_CLASSES,
    PrevalenceBaseline,
    build_feature_matrix,
    lr_summary,
    lr_summary_llm,
    xgb_summary,
    xgb_summary_llm,
)

SEED = 42069
N_SPLITS = 5
N_BOOT = 2000
TOP_DECILE = 0.10

CLASS_NAMES = ["happy", "neutral", "sad"]

ROOT = Path(__file__).resolve().parents[2]
METRICS_PATH = ROOT / "data" / "processed" / "metrics.json"

MODELS = [
    ("baseline_prevalence", "baseline", PrevalenceBaseline),
    ("lr_summary",          "summary", lr_summary),
    ("xgb_summary",         "summary", xgb_summary),
]

LLM_MODELS = [
    ("lr_summary_llm",  "summary_llm", lr_summary_llm),
    ("xgb_summary_llm", "summary_llm", xgb_summary_llm),
]


def per_class_pr_auc(y: np.ndarray, P: np.ndarray) -> np.ndarray:
    out = np.zeros(N_CLASSES, dtype=np.float64)
    for c in range(N_CLASSES):
        yc = (y == c).astype(int)
        out[c] = float(average_precision_score(yc, P[:, c]))
    return out


def per_class_roc_auc(y: np.ndarray, P: np.ndarray) -> np.ndarray:
    out = np.zeros(N_CLASSES, dtype=np.float64)
    for c in range(N_CLASSES):
        yc = (y == c).astype(int)
        if yc.sum() == 0 or yc.sum() == len(yc):
            out[c] = float("nan")
            continue
        out[c] = float(roc_auc_score(yc, P[:, c]))
    return out


def not_happy_pr_auc(y: np.ndarray, P: np.ndarray) -> float:
    y_bin = (y != 0).astype(int)
    score = 1.0 - P[:, 0]
    return float(average_precision_score(y_bin, score))


def not_happy_roc_auc(y: np.ndarray, P: np.ndarray) -> float:
    y_bin = (y != 0).astype(int)
    score = 1.0 - P[:, 0]
    return float(roc_auc_score(y_bin, score))


def top_label_ece(y: np.ndarray, P: np.ndarray, n_bins: int = 10) -> float:
    pred_class = P.argmax(axis=1)
    top_p = P[np.arange(len(P)), pred_class]
    correct = (pred_class == y).astype(int)
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(top_p, bins, right=True) - 1, 0, n_bins - 1)
    ece = 0.0
    n = len(y)
    for b in range(n_bins):
        mask = idx == b
        if not mask.any():
            continue
        ece += mask.sum() / n * abs(top_p[mask].mean() - correct[mask].mean())
    return float(ece)


def precision_at_top_decile_not_happy(y: np.ndarray, P: np.ndarray, fraction: float = TOP_DECILE) -> dict:
    """Precision and per-class recall at the top `fraction` of (1 - p_happy)."""
    score = 1.0 - P[:, 0]
    k = max(1, int(np.floor(len(P) * fraction)))
    threshold = np.partition(score, -k)[-k]
    flagged = score >= threshold
    y_bin = (y != 0).astype(int)
    tp = int((flagged & (y_bin == 1)).sum())
    fp = int((flagged & (y_bin == 0)).sum())
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / max(1, int(y_bin.sum()))
    recall_neutral = int((flagged & (y == 1)).sum()) / max(1, int((y == 1).sum()))
    recall_sad = int((flagged & (y == 2)).sum()) / max(1, int((y == 2).sum()))
    return {
        "precision_not_happy": float(precision),
        "recall_not_happy": float(recall),
        "recall_neutral": float(recall_neutral),
        "recall_sad": float(recall_sad),
        "threshold": float(threshold),
    }


def clustered_bootstrap_ci(
    y: np.ndarray, P: np.ndarray, groups: np.ndarray,
    scorer, *, n: int = N_BOOT, seed: int = SEED, alpha: float = 0.05,
) -> tuple[float, float, int]:
    """Resample restaurants with replacement; scorer takes (y, P) -> float."""
    rng = np.random.default_rng(seed)
    unique_groups = np.unique(groups)
    group_to_idx = {g: np.where(groups == g)[0] for g in unique_groups}
    scores = []
    rejections = 0
    for _ in range(n):
        sampled = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        idx = np.concatenate([group_to_idx[g] for g in sampled])
        ys, Ps = y[idx], P[idx]
        if len(np.unique(ys)) < 2:
            rejections += 1
            continue
        try:
            scores.append(scorer(ys, Ps))
        except ValueError:
            rejections += 1
    if not scores:
        return float("nan"), float("nan"), rejections
    lo, hi = np.nanquantile(scores, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi), int(rejections)


def run_cv(features: pd.DataFrame, *, model_specs=MODELS) -> tuple[pd.DataFrame, dict]:
    y = features["target_3class"].to_numpy().astype(int)
    groups = features["place_id"].to_numpy()
    skf = StratifiedGroupKFold(n_splits=N_SPLITS, shuffle=True, random_state=SEED)
    folds = list(skf.split(features, y, groups=groups))

    oof_records = {"inspection_id": features["inspection_id"].to_numpy(),
                   "place_id": features["place_id"].to_numpy(),
                   "y": y}
    fold_summaries = []

    for model_name, kind, builder in model_specs:
        X, _ = build_feature_matrix(features, kind=kind)
        P_oof = np.zeros((len(features), N_CLASSES), dtype=np.float64)
        per_fold = []
        for fold_idx, (train_idx, test_idx) in enumerate(folds):
            model = builder()
            model.fit(X[train_idx], y[train_idx])
            P = model.predict_proba(X[test_idx])
            P_oof[test_idx] = P
            per_fold.append({
                "fold": fold_idx,
                "n_train": int(len(train_idx)),
                "n_test": int(len(test_idx)),
                "test_class_rates": [float((y[test_idx] == c).mean()) for c in range(N_CLASSES)],
            })
        for c in range(N_CLASSES):
            oof_records[f"{model_name}__p{c}"] = P_oof[:, c]
        fold_summaries.append({"model": model_name, "folds": per_fold})

    oof = pd.DataFrame(oof_records)
    return oof, {"folds": fold_summaries}


def _proba(oof: pd.DataFrame, model_name: str) -> np.ndarray:
    return np.stack([oof[f"{model_name}__p{c}"].to_numpy() for c in range(N_CLASSES)], axis=1)


def summarize(oof: pd.DataFrame, *, model_specs=MODELS) -> dict:
    y = oof["y"].to_numpy().astype(int)
    groups = oof["place_id"].to_numpy()
    summary = {}
    for model_name, _, _ in model_specs:
        P = _proba(oof, model_name)
        per_pr = per_class_pr_auc(y, P)
        per_roc = per_class_roc_auc(y, P)
        nh_pr = not_happy_pr_auc(y, P)
        nh_roc = not_happy_roc_auc(y, P)
        ece = top_label_ece(y, P)
        op = precision_at_top_decile_not_happy(y, P)

        per_pr_ci = []
        for c in range(N_CLASSES):
            lo, hi, _ = clustered_bootstrap_ci(
                y, P, groups,
                lambda yy, PP, c=c: float(average_precision_score((yy == c).astype(int), PP[:, c])),
            )
            per_pr_ci.append([lo, hi])

        nh_pr_lo, nh_pr_hi, _ = clustered_bootstrap_ci(
            y, P, groups,
            lambda yy, PP: float(average_precision_score((yy != 0).astype(int), 1.0 - PP[:, 0])),
        )

        summary[model_name] = {
            "pr_auc_per_class": per_pr.tolist(),
            "pr_auc_per_class_ci95": per_pr_ci,
            "roc_auc_per_class": per_roc.tolist(),
            "pr_auc_not_happy": nh_pr,
            "pr_auc_not_happy_ci95": [nh_pr_lo, nh_pr_hi],
            "roc_auc_not_happy": nh_roc,
            "top_label_ece": ece,
            **op,
        }
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default=str(FEATURES_PATH))
    ap.add_argument("--llm-window-features", default=None)
    args = ap.parse_args()

    features = pd.read_parquet(args.features)
    model_specs = MODELS
    if args.llm_window_features:
        llm = pd.read_parquet(args.llm_window_features)
        features = features.merge(llm, on="inspection_id", how="left")
        for col in LLM_HYGIENE_COLS:
            features[col] = features[col].fillna(False)
        model_specs = MODELS + LLM_MODELS

    oof, fold_info = run_cv(features, model_specs=model_specs)
    summary = summarize(oof, model_specs=model_specs)

    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps({"summary": summary, "per_fold": fold_info, "class_names": CLASS_NAMES}, indent=2))

    print(f"Wrote metrics to {METRICS_PATH}")
    print()
    print("Per-class PR-AUC (happy / neutral / sad), not-happy PR-AUC, ECE, P@10%:")
    for name, m in summary.items():
        per_pr = m["pr_auc_per_class"]
        nh = m["pr_auc_not_happy"]
        ece = m["top_label_ece"]
        p10 = m["precision_not_happy"]
        print(f"  {name:24s}  {per_pr[0]:.3f} / {per_pr[1]:.3f} / {per_pr[2]:.3f}   not-happy={nh:.3f}   ECE={ece:.3f}   P@10={p10:.3f}")


if __name__ == "__main__":
    main()
