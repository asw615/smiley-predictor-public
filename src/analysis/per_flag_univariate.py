"""Per-flag adjusted odds ratios for the multinomial smiley target.

For each of the six hygiene flags and each non-happy class (neutral, sad),
fit a one-vs-happy logistic regression on the subset of windows that are
either happy or that class:

    y == c ~ llm_<flag>_any + log1p(scored_review_count)

The log1p(scored) term adjusts for exposure (a flag is more likely to fire
when more reviews are classified). Output: per_flag_univariate.{md,json} in
data/processed/.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from src.features.llm_hygiene import HYGIENE_COLS

ROOT = Path(__file__).resolve().parents[2]
FEATURES_PATH = ROOT / "data" / "processed" / "features.parquet"
LLM_PATH = ROOT / "data" / "processed" / "llm_hygiene_window_features.parquet"
OUT_MD = ROOT / "data" / "processed" / "per_flag_univariate.md"
OUT_JSON = ROOT / "data" / "processed" / "per_flag_univariate.json"

SEED = 42069
N_BOOT = 2000

CLASS_LABELS = {1: "neutral", 2: "sad"}


def fit_or(X: np.ndarray, y: np.ndarray) -> float:
    """Adjusted OR for column 0 of X."""
    lr = LogisticRegression(max_iter=1000, random_state=SEED)
    lr.fit(X, y)
    return float(np.exp(lr.coef_[0, 0]))


def clustered_bootstrap_or(
    X: np.ndarray, y: np.ndarray, groups: np.ndarray, *, n: int = N_BOOT, seed: int = SEED
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    unique = np.unique(groups)
    by_g = {g: np.where(groups == g)[0] for g in unique}
    ors = []
    for _ in range(n):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([by_g[g] for g in sampled])
        ys = y[idx]
        if ys.sum() == 0 or ys.sum() == len(ys):
            continue
        try:
            ors.append(fit_or(X[idx], ys))
        except (ValueError, np.linalg.LinAlgError):
            continue
    if not ors:
        return float("nan"), float("nan")
    lo, hi = np.quantile(ors, [0.025, 0.975])
    return float(lo), float(hi)


def main() -> None:
    feats = pd.read_parquet(FEATURES_PATH)
    llm = pd.read_parquet(LLM_PATH)
    df = feats.merge(llm, on="inspection_id", how="left")
    df["llm_hygiene_scored_review_count"] = df["llm_hygiene_scored_review_count"].fillna(0)
    df["log1p_scored"] = np.log1p(df["llm_hygiene_scored_review_count"])
    y3 = df["target_3class"].to_numpy().astype(int)
    groups = df["place_id"].to_numpy()

    overall = {
        "happy_share": float((y3 == 0).mean()),
        "neutral_share": float((y3 == 1).mean()),
        "sad_share": float((y3 == 2).mean()),
        "n_total": int(len(df)),
    }

    rows = []
    for flag in HYGIENE_COLS:
        col = f"llm_{flag}_any"
        df[col] = df[col].fillna(False).astype(int)
        flag_any = df[col].to_numpy().astype(np.float64)
        n_pos = int(flag_any.sum())
        if n_pos:
            flagged_classes = y3[flag_any == 1]
            neutral_rate_flagged = float((flagged_classes == 1).mean())
            sad_rate_flagged = float((flagged_classes == 2).mean())
        else:
            neutral_rate_flagged = sad_rate_flagged = float("nan")

        flag_row = {
            "flag": flag,
            "n_windows_flagged": n_pos,
            "neutral_rate_flagged": neutral_rate_flagged,
            "sad_rate_flagged": sad_rate_flagged,
            "contrasts": {},
        }
        for c, label in CLASS_LABELS.items():
            mask = (y3 == 0) | (y3 == c)
            y_bin = (y3[mask] == c).astype(int)
            X = np.column_stack([flag_any[mask], df.loc[mask, "log1p_scored"].to_numpy()])
            groups_c = groups[mask]
            if X[:, 0].sum() == 0 or X[:, 0].sum() == len(X):
                or_point = float("nan")
                or_lo = or_hi = float("nan")
            else:
                or_point = fit_or(X, y_bin)
                or_lo, or_hi = clustered_bootstrap_or(X, y_bin, groups_c)
            flag_row["contrasts"][label] = {
                "or_adjusted": or_point,
                "or_ci95": [or_lo, or_hi],
                "n_in_contrast": int(mask.sum()),
                "n_positive_in_contrast": int(y_bin.sum()),
            }
        rows.append(flag_row)

    OUT_JSON.write_text(json.dumps({"overall": overall, "flags": rows}, indent=2))

    lines = [
        f"n_total = {overall['n_total']}  |  happy {overall['happy_share']:.3f}  "
        f"neutral {overall['neutral_share']:.3f}  sad {overall['sad_share']:.3f}",
        "",
        "| flag | n flagged | neutral OR (95% CI) | sad OR (95% CI) |",
        "|---|---|---|---|",
    ]
    for r in rows:
        n_neu = r["contrasts"]["neutral"]
        n_sad = r["contrasts"]["sad"]
        lines.append(
            "| {flag} | {n} | {nor:.2f} [{nlo:.2f}, {nhi:.2f}] | {sor:.2f} [{slo:.2f}, {shi:.2f}] |".format(
                flag=r["flag"], n=r["n_windows_flagged"],
                nor=n_neu["or_adjusted"], nlo=n_neu["or_ci95"][0], nhi=n_neu["or_ci95"][1],
                sor=n_sad["or_adjusted"], slo=n_sad["or_ci95"][0], shi=n_sad["or_ci95"][1],
            )
        )
    OUT_MD.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nWrote {OUT_MD}\nWrote {OUT_JSON}")


if __name__ == "__main__":
    main()
