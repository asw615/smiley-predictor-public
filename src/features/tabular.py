"""Tabular feature set built from the per-visit panel.

`mean_star` stays NaN for empty windows (trees handle this natively; the LR
pipeline imputes it to 0 via SimpleImputer in models.py).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.features.panel import OUT_PATH as PANEL_PATH
from src.features.panel import REVIEWS_PATH

OUT_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "features.parquet"

FEATURE_COLS = [
    "log1p_review_count",
    "mean_star",
    "share_low_star",
]


def _load_reviews_min() -> pd.DataFrame:
    r = pd.read_csv(
        REVIEWS_PATH,
        usecols=["review_id", "rating", "published_at_estimated_date"],
    )
    r["published_at"] = pd.to_datetime(r["published_at_estimated_date"], errors="coerce")
    r = r.drop(columns=["published_at_estimated_date"])
    r = r.dropna(subset=["review_id", "published_at"])
    # ~763 review_ids appear in more than one place-session. Keep one copy each
    # so the join doesn't inflate per-window counts.
    r = r.drop_duplicates(subset="review_id", keep="first")
    return r.set_index("review_id")


def build_features(panel: pd.DataFrame, reviews: pd.DataFrame | None = None) -> pd.DataFrame:
    if reviews is None:
        reviews = _load_reviews_min()
    elif "review_id" in reviews.columns:
        reviews = reviews.set_index("review_id")

    exploded = panel[["inspection_id", "inspection_date", "review_ids"]].explode("review_ids")
    exploded = exploded.rename(columns={"review_ids": "review_id"}).dropna(subset=["review_id"])
    joined = exploded.join(reviews, on="review_id", how="left")
    joined = joined.dropna(subset=["rating"])

    grouped = joined.groupby("inspection_id", sort=False)
    agg = pd.DataFrame({
        "mean_star": grouped["rating"].mean(),
        "low_star_count": grouped["rating"].apply(lambda s: int((s <= 2).sum())),
    })

    out = panel.set_index("inspection_id").join(agg)
    out["review_count"] = out["n_reviews_in_window"].astype(int)
    out["log1p_review_count"] = np.log1p(out["review_count"])
    out["low_star_count"] = out["low_star_count"].fillna(0).astype(int)
    out["share_low_star"] = (
        out["low_star_count"] / out["review_count"].clip(lower=1)
    ).astype(float)
    keep = ["place_id", "inspection_date", "smiley", "target", "target_3class"] + FEATURE_COLS
    return out.reset_index()[["inspection_id"] + keep]


def main() -> None:
    panel = pd.read_parquet(PANEL_PATH)
    features = build_features(panel)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {len(features)} feature rows to {OUT_PATH}")
    print(f"  columns: {list(features.columns)}")
    print()
    print("Feature summary (non-empty windows):")
    nonempty = features[features["log1p_review_count"] > 0]
    print(nonempty[FEATURE_COLS].describe().round(3))


if __name__ == "__main__":
    main()
