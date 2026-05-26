"""Per-visit inspection panel with between-inspections review windows.

The 4 inspection columns in smileystatus.xlsx are melted into long form, then
each row is joined to Google reviews dated strictly after the previous
inspection (or 2022-01-01, whichever is later) and on or before the current
inspection. Review dates come from `published_at_estimated_date` -- the precise
`published_at` is populated for only ~9% of rows. `fjerdeseneste` rows are
dropped as targets but kept as priors for `tredjeseneste`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
XLSX_PATH = ROOT / "data" / "raw" / "smileystatus.xlsx"
REVIEWS_PATH = ROOT / "data" / "reviews" / "google_reviews_full_6k.csv"
MATCHES_PATH = ROOT / "data" / "matching" / "google_maps_matches_full_6k_food_service.csv"
SCRAPE_STATUS_PATH = ROOT / "data" / "logs" / "google_reviews_scrape_status_full_6k.csv"
OUT_PATH = ROOT / "data" / "processed" / "panel.parquet"

TARGET_BRANCHE = "Serveringsvirksomhed - Restauranter m.v."
INSPECTION_START = pd.Timestamp("2022-01-01")
# Matches the LLM scoring floor so the panel's reviews are a subset of what
# Gemma classified.
REVIEW_DATE_FLOOR = pd.Timestamp("2022-01-01")

INSPECTION_COLS = [
    ("seneste_kontrol", "seneste_kontrol_dato", 1),
    ("naestseneste_kontrol", "naestseneste_kontrol_dato", 2),
    ("tredjeseneste_kontrol", "tredjeseneste_kontrol_dato", 3),
    ("fjerdeseneste_kontrol", "fjerdeseneste_kontrol_dato", 4),
]


def load_failed_place_ids() -> set[int]:
    status = pd.read_csv(SCRAPE_STATUS_PATH)
    field = status.iloc[0]["failed_restaurant_ids"]
    return {int(x) for x in re.findall(r"\d+", str(field))}


def load_scraped_place_ids() -> set[int]:
    matches = pd.read_csv(MATCHES_PATH)
    matched = set(matches["navnelbnr"].astype(int))
    return matched - load_failed_place_ids()


def load_inspections() -> pd.DataFrame:
    """Long-form inspection table, all 4 slots per restaurant. Caller filters."""
    df = pd.read_excel(XLSX_PATH, sheet_name=0)
    df = df[df["branche"] == TARGET_BRANCHE].copy()
    df["place_id"] = df["navnelbnr"].astype(int)

    long_parts = []
    for code_col, date_col, idx in INSPECTION_COLS:
        part = df[["place_id", "postnr", "By", "Geo_Lng", "Geo_Lat", code_col, date_col]].copy()
        part = part.rename(columns={code_col: "smiley", date_col: "inspection_date"})
        part["inspection_index"] = idx
        part["smiley"] = pd.to_numeric(part["smiley"], errors="coerce")
        part["inspection_date"] = pd.to_datetime(part["inspection_date"], errors="coerce")
        long_parts.append(part)

    long = pd.concat(long_parts, ignore_index=True)
    long = long.dropna(subset=["inspection_date", "smiley"])
    long = long[long["smiley"].isin([1, 2, 3, 4])]
    long["smiley"] = long["smiley"].astype(int)
    # Grade 3 was retired from the visual scheme in 2022 and appears in <0.3%
    # of post-2022 rows -- too few to model as its own class. Visible scheme:
    # 1 = happy, 2 = neutral, 4 = sad.
    long = long[long["smiley"] != 3]
    long["target"] = (long["smiley"] != 1).astype(int)
    long["target_3class"] = long["smiley"].map({1: 0, 2: 1, 4: 2}).astype(int)
    return long.reset_index(drop=True)


def load_reviews() -> pd.DataFrame:
    cols = ["restaurant_id", "review_id", "rating", "review_text", "review_language", "published_at_estimated_date"]
    r = pd.read_csv(REVIEWS_PATH, usecols=cols)
    r = r.rename(columns={"restaurant_id": "place_id"})
    r["place_id"] = r["place_id"].astype(int)
    r["published_at"] = pd.to_datetime(r["published_at_estimated_date"], errors="coerce")
    r = r.drop(columns=["published_at_estimated_date"])
    r = r.dropna(subset=["published_at", "review_id"])
    # ~763 review_ids appear in more than one place-session. Keep one copy each.
    r = r.drop_duplicates(subset="review_id", keep="first")
    return r.reset_index(drop=True)


def attach_between_inspection_reviews(panel: pd.DataFrame, reviews: pd.DataFrame) -> pd.DataFrame:
    """Window: (prev_inspection or 2022-01-01, current_inspection]."""
    by_place = reviews.groupby("place_id", sort=False)
    review_ids_col: list[list[str]] = []
    n_reviews_col: list[int] = []

    for _, row in panel.iterrows():
        prev = row["prev_inspection_date"]
        cutoff_start = max(prev, REVIEW_DATE_FLOOR) if pd.notna(prev) else REVIEW_DATE_FLOOR
        cutoff_end = row["inspection_date"]
        try:
            place_reviews = by_place.get_group(row["place_id"])
        except KeyError:
            review_ids_col.append([])
            n_reviews_col.append(0)
            continue
        mask = (
            (place_reviews["published_at"] > cutoff_start)
            & (place_reviews["published_at"] <= cutoff_end)
            & (place_reviews["published_at"] >= REVIEW_DATE_FLOOR)
        )
        window = place_reviews.loc[mask, "review_id"].tolist()
        review_ids_col.append(window)
        n_reviews_col.append(len(window))

    out = panel.copy()
    out["review_ids"] = review_ids_col
    out["n_reviews_in_window"] = n_reviews_col
    out["empty_window"] = out["n_reviews_in_window"] == 0
    return out


def build_panel() -> pd.DataFrame:
    scraped = load_scraped_place_ids()
    inspections = load_inspections()
    inspections = inspections[inspections["place_id"].isin(scraped)].copy()
    # Compute prev_inspection_date before the cohort filter so a pre-2022
    # inspection can still anchor a 2022-onward window.
    inspections = inspections.sort_values(["place_id", "inspection_date"]).reset_index(drop=True)
    inspections["prev_inspection_date"] = (
        inspections.groupby("place_id")["inspection_date"].shift(1)
    )
    inspections = inspections[
        (inspections["inspection_date"] >= INSPECTION_START)
        & (inspections["inspection_index"] != 4)
    ].copy()
    inspections["inspection_id"] = (
        inspections["place_id"].astype(str) + "__" + inspections["inspection_index"].astype(str)
    )

    reviews = load_reviews()
    reviews = reviews[reviews["place_id"].isin(scraped)]

    panel = attach_between_inspection_reviews(inspections, reviews)
    cols = [
        "inspection_id", "place_id", "inspection_date", "prev_inspection_date",
        "inspection_index", "smiley", "target", "target_3class", "postnr", "By", "Geo_Lng", "Geo_Lat",
        "n_reviews_in_window", "empty_window", "review_ids",
    ]
    return panel[cols].sort_values(["place_id", "inspection_index"]).reset_index(drop=True)


def main() -> None:
    panel = build_panel()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(OUT_PATH, index=False)
    window_start = panel["prev_inspection_date"].where(
        panel["prev_inspection_date"].notna() & (panel["prev_inspection_date"] >= REVIEW_DATE_FLOOR),
        REVIEW_DATE_FLOOR,
    )
    window_days = (panel["inspection_date"] - window_start).dt.days
    print(f"Wrote {len(panel)} inspections to {OUT_PATH}")
    print(f"  places: {panel['place_id'].nunique()}")
    print(f"  empty_window: {panel['empty_window'].sum()} ({panel['empty_window'].mean():.3%})")
    print(f"  positive rate (smiley != 1): {panel['target'].mean():.3%}")
    print(f"  reviews-in-window: mean={panel['n_reviews_in_window'].mean():.1f}, median={panel['n_reviews_in_window'].median():.0f}")
    print(f"  window-days: mean={window_days.mean():.0f}, median={window_days.median():.0f}, max={window_days.max()}")


if __name__ == "__main__":
    main()
