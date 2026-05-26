import argparse
import random

from utils.io import load_xlsx_rows, write_csv
from utils.paths import (
    INPUT_XLSX_PATH,
    PROCESSED_DATA_DIR,
    ensure_data_directories,
)


REVIEW_COLUMNS = [
    "seneste_kontrol",
    "naestseneste_kontrol",
    "tredjeseneste_kontrol",
]
ADDRESS_COLUMN = "adresse1"
ZIP_COLUMN = "postnr"
INDUSTRY_COLUMN = "branche"
TARGET_INDUSTRY = "Serveringsvirksomhed - Restauranter m.v."
RANDOM_SEED = 42
MIN_REVIEWS_REQUIRED = 3


def is_missing(value) -> bool:
    return value is None or str(value).strip() == ""


def filter_rows(rows):
    filtered = []
    for row in rows:
        if str(row.get(INDUSTRY_COLUMN) or "").strip() != TARGET_INDUSTRY:
            continue
        present_reviews = sum(
            0 if is_missing(row.get(column)) else 1 for column in REVIEW_COLUMNS
        )
        if present_reviews < MIN_REVIEWS_REQUIRED:
            continue
        if is_missing(row.get(ADDRESS_COLUMN)):
            continue
        if is_missing(row.get(ZIP_COLUMN)):
            continue
        filtered.append(row)
    return filtered


def is_seneste_problem(row) -> bool:
    """True iff seneste_kontrol is a valid problem smiley (2, 3, or 4).

    Returns False for missing, unparseable, or out-of-range values (e.g. 0).
    Smiley scale is 1-4; anything else is treated as invalid and not sampled
    into the problem stratum.
    """
    value = row.get("seneste_kontrol")
    if is_missing(value):
        return False
    try:
        smiley = int(str(value).strip())
    except ValueError:
        return False
    return smiley in (2, 3, 4)


def is_seneste_clean(row) -> bool:
    """True iff seneste_kontrol == 1. Invalid/missing values are excluded
    from both the problem and clean strata."""
    value = row.get("seneste_kontrol")
    if is_missing(value):
        return False
    try:
        return int(str(value).strip()) == 1
    except ValueError:
        return False


def stratified_sample(rows, n, seed):
    """Take every seneste_problem row, fill the remainder with seneste_clean."""
    problem = [r for r in rows if is_seneste_problem(r)]
    clean = [r for r in rows if is_seneste_clean(r)]
    n_excluded = len(rows) - len(problem) - len(clean)

    n_problem = len(problem)
    n_clean = min(n - n_problem, len(clean))
    if n_clean < 0:
        n_clean = 0

    actual_n = n_problem + n_clean
    if actual_n < n:
        print(
            f"WARNING: pool exhausted. Requested N={n}, delivering N={actual_n} "
            f"({n_problem} problem + {n_clean} clean)."
        )
    if n_excluded:
        print(
            f"NOTE: {n_excluded} row(s) excluded from sampling due to invalid/missing "
            f"seneste_kontrol (smiley not in {{1,2,3,4}})."
        )

    rng = random.Random(seed)
    sampled = list(problem) + rng.sample(clean, n_clean)
    rng.shuffle(sampled)
    stats = {
        "pool_seneste_problem": len(problem),
        "pool_seneste_clean": len(clean),
        "pool_excluded_invalid": n_excluded,
        "sampled_problem": n_problem,
        "sampled_clean": n_clean,
    }
    return sampled, stats


def build_preprocessed_datasets(n, output_stem=None, seed=RANDOM_SEED):
    ensure_data_directories()
    headers, rows = load_xlsx_rows(INPUT_XLSX_PATH)
    cleaned_rows = filter_rows(rows)

    summary = {
        "input_rows": len(rows),
        "cleaned_rows": len(cleaned_rows),
    }

    stem = output_stem or f"stratified_{n}"
    output_path = PROCESSED_DATA_DIR / f"smileystatus_scrape_{stem}.csv"
    sampled, stats = stratified_sample(cleaned_rows, n, seed)
    write_csv(output_path, headers, sampled)
    summary["scrape_output_path"] = output_path
    summary["scrape_strategy"] = "all_problem_fill_clean"
    summary["scrape_size"] = len(sampled)
    summary["scrape_stats"] = stats
    summary["scrape_output_stem"] = stem
    return summary


def build_parser():
    p = argparse.ArgumentParser(
        description="Filter and sample restaurants for scraping."
    )
    p.add_argument(
        "--n",
        type=int,
        required=True,
        help="Sample size for the scrape set (e.g. 6000 for the full scrape).",
    )
    p.add_argument(
        "--output-stem",
        default=None,
        help="Stem for the scrape CSV: smileystatus_scrape_<stem>.csv. "
             "Defaults to 'stratified_<n>' when --n is given.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=RANDOM_SEED,
        help="Random seed for the scrape sample.",
    )
    return p


def main():
    args = build_parser().parse_args()
    summary = build_preprocessed_datasets(
        n=args.n, output_stem=args.output_stem, seed=args.seed
    )
    print(f"Input rows: {summary['input_rows']}")
    print(
        f"Rows after requiring branche '{TARGET_INDUSTRY}', at least "
        f"{MIN_REVIEWS_REQUIRED} reviews, and non-missing address/zip fields: "
        f"{summary['cleaned_rows']}"
    )
    print(
        f"Saved {summary['scrape_size']}-row scrape set "
        f"({summary['scrape_strategy']}) to: {summary['scrape_output_path']}"
    )
    if "scrape_stats" in summary:
        s = summary["scrape_stats"]
        print(
            f"  seneste_problem pool: {s['pool_seneste_problem']}  "
            f"seneste_clean pool: {s['pool_seneste_clean']}"
        )
        print(
            f"  sampled: {s['sampled_problem']} problem / {s['sampled_clean']} clean"
        )
