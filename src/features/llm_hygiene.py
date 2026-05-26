"""LLM hygiene-signal classifier for Danish restaurant reviews.

Talks to a local Ollama server (default `gemma4:e4b`) via `/api/generate` with
Structured Outputs. API-facing work and the deterministic split / metric /
window-aggregation helpers are kept separate so the latter can be tested
without a live server.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.utils.paths import MATCHING_DATA_DIR, PROCESSED_DATA_DIR, RAW_DATA_DIR, REVIEWS_DATA_DIR

ANNOTATED_PATH = RAW_DATA_DIR / "Reviews annoteret (200 styks) - Sheet1.csv"
DEFAULT_SMILEY_XLSX = RAW_DATA_DIR / "smileystatus.xlsx"
DEFAULT_MATCHES = MATCHING_DATA_DIR / "google_maps_matches_full_6k_food_service.csv"
RESTAURANT_BRANCHE = "Serveringsvirksomhed - Restauranter m.v."
WINDOW_DATE_CUTOFF = pd.Timestamp("2022-01-01")
DEFAULT_OLLAMA_MODEL = "gemma4:e4b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_KEEP_ALIVE = "30m"
DEFAULT_EVAL_PREDICTIONS = PROCESSED_DATA_DIR / "llm_hygiene_annotated_eval_predictions.csv"
DEFAULT_EVAL_METRICS = PROCESSED_DATA_DIR / "llm_hygiene_annotated_eval_metrics.json"
DEFAULT_REVIEW_PREDICTIONS = PROCESSED_DATA_DIR / "llm_hygiene_review_predictions.csv"
DEFAULT_HIGH_RATING_PREDICTIONS = PROCESSED_DATA_DIR / "llm_hygiene_high_rating_check_predictions.csv"
DEFAULT_HIGH_RATING_SUMMARY = PROCESSED_DATA_DIR / "llm_hygiene_high_rating_check_summary.json"
DEFAULT_FULL_REVIEWS_WITH_PREDICTIONS = PROCESSED_DATA_DIR / "google_reviews_full_6k_with_llm_hygiene.csv"
DEFAULT_WINDOW_FEATURES = PROCESSED_DATA_DIR / "llm_hygiene_window_features.parquet"
DEFAULT_FULL_REVIEWS = REVIEWS_DATA_DIR / "google_reviews_full_6k.csv"
DEFAULT_PANEL = PROCESSED_DATA_DIR / "panel.parquet"

HYGIENE_COLS = [
    "pest_or_vermin",
    "foreign_object_in_food",
    "food_safety_concern",
    "visible_dirtness",
    "staff_hygiene",
    "illness_after_eating",
]

OUTPUT_COLUMNS = [
    "hygiene_signal",
    *HYGIENE_COLS,
    "confidence",
    "evidence",
]

LLM_WINDOW_FEATURE_COLS = [
    "llm_hygiene_scored_review_count",
    "llm_hygiene_any",
    "llm_hygiene_signal_count",
    *[f"llm_{col}_any" for col in HYGIENE_COLS],
    *[f"llm_{col}_rate" for col in HYGIENE_COLS],
]

CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "name": "hygiene_review_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "hygiene_signal": {
                "type": "boolean",
                "description": "True if the review contains at least one hygiene or food-safety signal.",
            },
            "pest_or_vermin": {"type": "boolean"},
            "foreign_object_in_food": {"type": "boolean"},
            "food_safety_concern": {"type": "boolean"},
            "visible_dirtness": {"type": "boolean"},
            "staff_hygiene": {"type": "boolean"},
            "illness_after_eating": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {
                "type": "string",
                "description": "A short Danish evidence phrase from the review, or an empty string if none.",
            },
        },
        "required": OUTPUT_COLUMNS,
    },
}

SYSTEM_PROMPT = """Klassificer danske Google Maps-anmeldelser for konkrete hygiejne- og fødevaresikkerhedssignaler.

Sæt kun flag ved konkrete påstande. Almindelige klager over service, pris, ventetid, smag, portionsstørrelse eller stemning er ikke nok.

Kategorier:
- pest_or_vermin: dyr/skadedyr/insekter/fluer/rotter/mus/maddiker i mad eller lokale.
- foreign_object_in_food: hår, plastik, glas, metal, sten eller andet fremmedlegeme i mad/drikke.
- food_safety_concern: usikker mad/håndtering, rå/ikke gennemstegt risikomad, fordærvet/harsk mad, allergen/vegansk forurening, genbrugte rester, usikker buffet/opbevaring, eller sikkerhedsrelevant kold mad.
- visible_dirtness: konkret snavs, mug/skimmel, spindelvæv, beskidte borde/gulve/toiletter/buffet.
- staff_hygiene: personalets hygiejne påvirker madlavning/servering direkte.
- illness_after_eating: madforgiftning, opkast, diarré, mavepine/kramper eller kvalme efter spisning.

Regler:
- hygiene_signal = OR af de seks kategorier.
- Vage ord som "ulækkert", "klamt" eller "dårlig mad" er ikke nok uden konkret hygiejne/sikkerhedsdetalje.
- COVID/mundbind er kun staff_hygiene hvis det direkte handler om madhåndtering.
- evidence: kort tekstbid fra anmeldelsen; tom ved intet signal.
"""


@dataclass(frozen=True)
class Metrics:
    n: int
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float
    recall: float
    f1: float
    accuracy: float


def _bool_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    raw = df[column]
    numeric = pd.to_numeric(raw, errors="coerce").fillna(0).ne(0)
    text = raw.fillna("").astype(str).str.strip().str.lower().isin({"1", "1.0", "true", "yes"})
    return numeric | text


def read_annotated(path: Path = ANNOTATED_PATH) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = {"review_text", *HYGIENE_COLS} - set(df.columns)
    if missing:
        raise ValueError(f"annotated CSV is missing columns: {sorted(missing)}")
    for col in HYGIENE_COLS:
        df[col] = _bool_series(df, col)
    df["hygiene_signal"] = df[HYGIENE_COLS].any(axis=1)
    df["row_id"] = df.index.astype(int)
    df["review_hash"] = df["review_text"].map(stable_review_hash)
    return df


def split_annotated(
    df: pd.DataFrame,
    *,
    pool_size: int = 40,
    seed: int = 42,
    positive_pool_size: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if pool_size <= 0 or pool_size >= len(df):
        raise ValueError("pool_size must be positive and smaller than the annotated dataset")
    if positive_pool_size is None:
        few_shot_pool = df.sample(pool_size, random_state=seed)
    else:
        positives = df[df["hygiene_signal"]]
        negatives = df[~df["hygiene_signal"]]
        n_pos = min(max(0, positive_pool_size), len(positives), pool_size)
        n_neg = pool_size - n_pos
        if n_neg > len(negatives):
            raise ValueError("pool_size leaves too few negatives for the requested positive_pool_size")
        few_shot_pool = pd.concat([
            positives.sample(n_pos, random_state=seed),
            negatives.sample(n_neg, random_state=seed + 1),
        ])
    eval_set = df.drop(few_shot_pool.index)
    return few_shot_pool.sort_index().reset_index(drop=True), eval_set.sort_index().reset_index(drop=True)


def stable_review_hash(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:16]


def select_few_shot_examples(
    pool: pd.DataFrame,
    *,
    max_examples: int = 14,
    max_negatives: int = 4,
) -> pd.DataFrame:
    if max_examples < 2:
        raise ValueError("max_examples must be at least 2")
    selected: list[int] = []
    positives = pool[pool["hygiene_signal"]].copy()
    positives["_category_count"] = positives[HYGIENE_COLS].sum(axis=1)

    for col in HYGIENE_COLS:
        matches = positives[positives[col] & ~positives.index.isin(selected)]
        if not matches.empty:
            selected.append(int(matches.sort_values("_category_count", ascending=False).index[0]))
        if len(selected) >= max_examples - 1:
            break

    remaining_positive_slots = max(0, max_examples - max_negatives - len(selected))
    if remaining_positive_slots:
        remaining = positives[~positives.index.isin(selected)].sort_values("_category_count", ascending=False)
        selected.extend([int(i) for i in remaining.head(remaining_positive_slots).index])

    negative_slots = min(max_negatives, max_examples - len(selected))
    negatives = pool[~pool["hygiene_signal"]]
    selected.extend([int(i) for i in negatives.head(negative_slots).index])

    if len(selected) < max_examples:
        remaining = pool[~pool.index.isin(selected)]
        selected.extend([int(i) for i in remaining.head(max_examples - len(selected)).index])

    return pool.loc[selected].reset_index(drop=True)


def format_examples(examples: pd.DataFrame) -> str:
    lines = ["Eksempler:"]
    for i, row in examples.iterrows():
        true_labels = [col for col in HYGIENE_COLS if bool(row[col])]
        label_text = ", ".join(true_labels) if true_labels else "no_hygiene_signal"
        review = str(row["review_text"]).replace("\n", " ").strip()
        if len(review) > 260:
            review = review[:257].rstrip() + "..."
        lines.append(f"{i + 1}. Anmeldelse: {review}")
        lines.append(f"   Labels: {label_text}")
    return "\n".join(lines)


def build_instructions(examples: pd.DataFrame) -> str:
    return SYSTEM_PROMPT + "\n\n" + format_examples(examples)


def normalize_prediction(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in HYGIENE_COLS:
        out[col] = bool(raw.get(col, False))
    out["hygiene_signal"] = any(out[col] for col in HYGIENE_COLS)
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    out["confidence"] = max(0.0, min(1.0, confidence))
    out["evidence"] = str(raw.get("evidence", "") or "")[:500]
    return out


def coerce_prediction_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ["hygiene_signal", *HYGIENE_COLS]:
        if col in out.columns:
            if out[col].dtype == bool:
                continue
            out[col] = out[col].fillna(False).map(
                lambda value: str(value).strip().lower() in {"1", "true", "yes"}
            )
    if "confidence" in out.columns:
        out["confidence"] = pd.to_numeric(out["confidence"], errors="coerce").fillna(0.0)
    return out


def append_predictions_to_reviews(
    reviews: pd.DataFrame,
    predictions: pd.DataFrame,
    *,
    key_col: str,
) -> pd.DataFrame:
    pred = coerce_prediction_columns(predictions)
    keep = [key_col, *OUTPUT_COLUMNS]
    missing = [col for col in keep if col not in pred.columns]
    if missing:
        raise ValueError(f"prediction table is missing columns: {missing}")

    pred = pred[keep].drop_duplicates(key_col, keep="last").rename(
        columns={
            "hygiene_signal": "llm_hygiene_signal",
            **{col: f"llm_{col}" for col in HYGIENE_COLS},
            "confidence": "llm_hygiene_confidence",
            "evidence": "llm_hygiene_evidence",
        }
    )
    out = reviews.merge(pred, on=key_col, how="left")
    bool_cols = ["llm_hygiene_signal", *[f"llm_{col}" for col in HYGIENE_COLS]]
    for col in bool_cols:
        out[col] = out[col].fillna(False).astype(bool)
    out["llm_hygiene_confidence"] = pd.to_numeric(
        out["llm_hygiene_confidence"], errors="coerce"
    ).fillna(0.0)
    out["llm_hygiene_evidence"] = out["llm_hygiene_evidence"].fillna("")
    out["llm_hygiene_model_scored"] = out[key_col].isin(pred[key_col])
    return out


def build_ollama_request_body(
    *,
    review_text: str,
    instructions: str,
    model: str,
    think: bool = False,
    keep_alive: str = DEFAULT_OLLAMA_KEEP_ALIVE,
) -> dict[str, Any]:
    prompt = (
        f"{instructions}\n\n"
        "Returner kun JSON, der matcher schemaet.\n\n"
        f"Klassificer denne anmeldelse:\n{review_text}"
    )
    # Ollama wants either an int (seconds; -1 = keep forever) or a duration string
    # like "30m". argparse gives us a string, so coerce numeric forms to int.
    # Ollama accepts an int (seconds, -1 = keep forever) or a duration like "30m".
    keep_alive_value: int | str = keep_alive
    try:
        keep_alive_value = int(keep_alive)
    except (TypeError, ValueError):
        pass
    return {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": think,
        "format": CLASSIFICATION_SCHEMA["schema"],
        "keep_alive": keep_alive_value,
        "options": {"temperature": 0, "num_predict": 512, "num_ctx": 8192},
    }


def classify_review_ollama(
    *,
    review_text: str,
    instructions: str,
    model: str,
    ollama_url: str,
    think: bool = False,
    keep_alive: str = DEFAULT_OLLAMA_KEEP_ALIVE,
    max_retries: int = 3,
) -> dict[str, Any]:
    payload = build_ollama_request_body(
        review_text=review_text,
        instructions=instructions,
        model=model,
        think=think,
        keep_alive=keep_alive,
    )
    data = json.dumps(payload).encode("utf-8")
    endpoint = ollama_url.rstrip("/") + "/api/generate"
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            request = urllib.request.Request(
                endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=300) as response:
                result = json.loads(response.read().decode("utf-8"))
            return normalize_prediction(json.loads(result["response"]))
        except (KeyError, json.JSONDecodeError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(
        f"Ollama classification failed after {max_retries + 1} attempts; "
        f"check that Ollama is running and model {model!r} is pulled"
    ) from last_error


def load_prediction_cache(path: Path, key_col: str) -> dict[str, dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return {}
    if key_col not in df.columns:
        return {}
    return {str(row[key_col]): row.to_dict() for _, row in df.iterrows()}


def interleave_by_restaurant(df: pd.DataFrame, restaurant_col: str = "restaurant_id") -> pd.DataFrame:
    """Round-robin order so we cover N restaurants in N steps, not 1 restaurant
    900 deep before touching another."""
    out = df.copy()
    out["_cycle"] = out.groupby(restaurant_col).cumcount()
    out = out.sort_values(["_cycle", restaurant_col]).drop(columns=["_cycle"])
    return out.reset_index(drop=True)


def classify_dataframe(
    rows: pd.DataFrame,
    *,
    key_col: str,
    text_col: str,
    instructions: str,
    model: str,
    output_path: Path,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    ollama_think: bool = False,
    ollama_keep_alive: str = DEFAULT_OLLAMA_KEEP_ALIVE,
    limit: int | None = None,
    max_workers: int = 1,
) -> pd.DataFrame:
    import csv as _csv
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    from threading import Lock

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_prediction_cache(output_path, key_col)
    work = rows.head(limit).copy() if limit is not None else rows.copy()

    work_keys = work[key_col].astype(str)
    todo_mask = ~work_keys.isin(cache)
    todo = work[todo_mask]
    cached_count = int((~todo_mask).sum())
    total = len(work)

    write_header = not output_path.exists() or output_path.stat().st_size == 0
    new_count = 0
    lock = Lock()
    writer_state: dict[str, Any] = {"writer": None}

    def _classify_row(row: pd.Series) -> tuple[pd.Series, dict[str, Any] | None]:
        try:
            prediction = classify_review_ollama(
                review_text=str(row[text_col]),
                instructions=instructions,
                model=model,
                ollama_url=ollama_url,
                think=ollama_think,
                keep_alive=ollama_keep_alive,
            )
            return row, prediction
        except Exception as exc:
            # Skip and let the next resume retry; no cache entry written.
            print(f"WARN: classify failed for {row.get(key_col, '?')}: {exc}")
            return row, None

    with output_path.open("a", encoding="utf-8", newline="") as fh:

        def _emit(row: pd.Series, prediction: dict[str, Any]) -> None:
            nonlocal new_count, write_header
            result = {**row.to_dict(), **prediction}
            with lock:
                if writer_state["writer"] is None:
                    writer_state["writer"] = _csv.DictWriter(fh, fieldnames=list(result.keys()))
                    if write_header:
                        writer_state["writer"].writeheader()
                        write_header = False
                writer_state["writer"].writerow(result)
                new_count += 1
                if new_count % 10 == 0:
                    fh.flush()
                    done = cached_count + new_count
                    print(f"classified {done} / {total} reviews ({new_count} new this run)")

        if max_workers <= 1:
            for _, row in todo.iterrows():
                row, prediction = _classify_row(row)
                if prediction is not None:
                    _emit(row, prediction)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                # Bounded sliding window so completions interleave with submissions.
                todo_iter = (row for _, row in todo.iterrows())
                inflight_cap = max_workers * 4
                inflight: set = set()
                for row in todo_iter:
                    inflight.add(ex.submit(_classify_row, row))
                    if len(inflight) >= inflight_cap:
                        done, inflight = wait(inflight, return_when=FIRST_COMPLETED)
                        for fut in done:
                            r, prediction = fut.result()
                            if prediction is not None:
                                _emit(r, prediction)
                while inflight:
                    done, inflight = wait(inflight, return_when=FIRST_COMPLETED)
                    for fut in done:
                        r, prediction = fut.result()
                        if prediction is not None:
                            _emit(r, prediction)

        fh.flush()

    out = pd.read_csv(output_path) if output_path.exists() else pd.DataFrame()
    out = coerce_prediction_columns(out)
    out.to_csv(output_path, index=False)
    return out


def compute_binary_metrics(y_true: pd.Series, y_pred: pd.Series) -> Metrics:
    yt = y_true.astype(bool)
    yp = y_pred.astype(bool)
    tp = int((yt & yp).sum())
    fp = int((~yt & yp).sum())
    fn = int((yt & ~yp).sum())
    tn = int((~yt & ~yp).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(yt) if len(yt) else 0.0
    return Metrics(len(yt), tp, fp, fn, tn, precision, recall, f1, accuracy)


def evaluate_annotated(args: argparse.Namespace) -> None:
    annotated = read_annotated(args.annotated)
    pool, eval_set = split_annotated(
        annotated,
        pool_size=args.pool_size,
        seed=args.seed,
        positive_pool_size=args.positive_pool_size,
    )
    examples = select_few_shot_examples(pool, max_examples=args.max_examples, max_negatives=args.max_negatives)
    instructions = build_instructions(examples)

    predictions = classify_dataframe(
        eval_set,
        key_col="row_id",
        text_col="review_text",
        instructions=instructions,
        model=args.model,
        output_path=args.predictions_out,
        ollama_url=args.ollama_url,
        ollama_think=args.ollama_think,
        ollama_keep_alive=args.ollama_keep_alive,
        limit=args.limit,
        max_workers=args.max_workers,
    )
    merged = eval_set.merge(predictions, on="row_id", suffixes=("_human", "_pred"))
    metrics = compute_binary_metrics(merged["hygiene_signal_human"], merged["hygiene_signal_pred"])
    payload = {
        "model": args.model,
        "seed": args.seed,
        "pool_size": args.pool_size,
        "positive_pool_size": args.positive_pool_size,
        "eval_size": int(len(merged)),
        "few_shot_row_ids": examples["row_id"].astype(int).tolist(),
        "binary_metrics": metrics.__dict__,
    }
    args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(json.dumps(payload["binary_metrics"], indent=2))
    print(f"Wrote predictions to {args.predictions_out}")
    print(f"Wrote metrics to {args.metrics_out}")


def filter_to_in_scope_reviews(
    reviews: pd.DataFrame,
    *,
    smiley_path: Path,
    matches_path: Path,
) -> pd.DataFrame:
    """Reviews dated 2022-01-01 onward that fall inside a smiley inspection window."""
    smiley = pd.read_excel(smiley_path)
    restaurants = smiley[smiley["branche"] == RESTAURANT_BRANCHE].copy()

    date_cols = [
        "fjerdeseneste_kontrol_dato",
        "tredjeseneste_kontrol_dato",
        "naestseneste_kontrol_dato",
        "seneste_kontrol_dato",
    ]
    for col in date_cols:
        restaurants[col] = pd.to_datetime(restaurants[col], errors="coerce")

    window_rows: list[dict] = []
    for _, r in restaurants.iterrows():
        dates = sorted(d for d in (r[c] for c in date_cols) if pd.notna(d))
        for i in range(len(dates) - 1):
            window_rows.append(
                {"restaurant_id": int(r["navnelbnr"]), "window_start": dates[i], "window_end": dates[i + 1]}
            )
    windows = pd.DataFrame(window_rows)

    matches = pd.read_csv(matches_path)
    matched_rids = set(matches["navnelbnr"].dropna().astype(int))

    reviews = reviews.copy()
    reviews["_date"] = pd.to_datetime(reviews["published_at_estimated_date"], errors="coerce")

    in_matched = reviews["restaurant_id"].isin(matched_rids)
    after_cutoff = reviews["_date"] >= WINDOW_DATE_CUTOFF

    candidate_reviews = reviews[in_matched & after_cutoff].copy()
    merged = candidate_reviews.merge(windows, on="restaurant_id")
    in_window_mask = (merged["_date"] > merged["window_start"]) & (merged["_date"] <= merged["window_end"])
    in_scope_ids = set(merged.loc[in_window_mask, "review_id"].dropna())

    result = reviews[reviews["review_id"].isin(in_scope_ids)].drop(columns=["_date"])
    return result


def score_full_reviews(args: argparse.Namespace) -> None:
    annotated = read_annotated(args.annotated)
    pool, _ = split_annotated(
        annotated,
        pool_size=args.pool_size,
        seed=args.seed,
        positive_pool_size=args.positive_pool_size,
    )
    examples = select_few_shot_examples(pool, max_examples=args.max_examples, max_negatives=args.max_negatives)
    instructions = build_instructions(examples)

    if not args.reviews.exists():
        raise FileNotFoundError(f"review CSV not found: {args.reviews}")
    reviews = pd.read_csv(args.reviews)
    if args.text_col not in reviews.columns:
        raise ValueError(f"review CSV is missing text column {args.text_col!r}")
    if args.key_col not in reviews.columns:
        reviews[args.key_col] = reviews.index.astype(str)

    reviews_in_scope = filter_to_in_scope_reviews(
        reviews, smiley_path=args.smiley, matches_path=args.matches
    )
    print(
        f"In-scope reviews (published >= 2022, inside inspection window): "
        f"{len(reviews_in_scope)} / {len(reviews)}"
    )

    review_text = reviews_in_scope[args.text_col].fillna("").astype(str).str.strip()
    reviews_with_text = reviews_in_scope[review_text.str.len() > 0].copy()
    reviews_with_text[args.text_col] = review_text.loc[reviews_with_text.index]

    # Skip 4-5 star reviews; we assume they carry no hygiene signal. Saves
    # ~75% of LLM calls. The check-high-rating subcommand validates this.
    if args.max_rating is not None and args.max_rating >= 0:
        rating = pd.to_numeric(reviews_with_text.get("rating"), errors="coerce")
        keep = rating <= args.max_rating
        before = len(reviews_with_text)
        reviews_with_text = reviews_with_text[keep.fillna(False)].copy()
        print(
            f"Rating filter (rating <= {args.max_rating}): "
            f"{len(reviews_with_text)} / {before} reviews kept for LLM scoring"
        )

    reviews_to_score = reviews_with_text.drop_duplicates(args.key_col, keep="first").copy()
    reviews_to_score = interleave_by_restaurant(reviews_to_score, restaurant_col="restaurant_id")
    print(f"Scoring order: round-robin across {reviews_to_score['restaurant_id'].nunique()} restaurants")

    predictions = classify_dataframe(
        reviews_to_score,
        key_col=args.key_col,
        text_col=args.text_col,
        instructions=instructions,
        model=args.model,
        output_path=args.output,
        ollama_url=args.ollama_url,
        ollama_think=args.ollama_think,
        ollama_keep_alive=args.ollama_keep_alive,
        limit=args.limit,
        max_workers=args.max_workers,
    )
    joined = append_predictions_to_reviews(reviews, predictions, key_col=args.key_col)
    args.joined_output.parent.mkdir(parents=True, exist_ok=True)
    joined.to_csv(args.joined_output, index=False)

    print(f"Wrote review-level LLM predictions to {args.output}")
    print(f"Wrote full review dataset with LLM predictions to {args.joined_output}")
    print(f"Rows in source reviews: {len(reviews)}")
    print(f"Rows in scope (>= 2022, inside window): {len(reviews_in_scope)}")
    print(f"Rows with non-empty review_text eligible for scoring: {len(reviews_with_text)}")
    print(f"Unique {args.key_col} values submitted for scoring: {len(reviews_to_score)}")
    print(f"Rows with model predictions in joined output: {int(joined['llm_hygiene_model_scored'].sum())}")


def check_high_rating_assumption(args: argparse.Namespace) -> None:
    """Sanity-check the 4-5 star = no-signal assumption on a random subset."""
    annotated = read_annotated(args.annotated)
    pool, _ = split_annotated(
        annotated,
        pool_size=args.pool_size,
        seed=args.seed,
        positive_pool_size=args.positive_pool_size,
    )
    examples = select_few_shot_examples(pool, max_examples=args.max_examples, max_negatives=args.max_negatives)
    instructions = build_instructions(examples)

    if not args.reviews.exists():
        raise FileNotFoundError(f"review CSV not found: {args.reviews}")
    reviews = pd.read_csv(args.reviews)
    if args.text_col not in reviews.columns:
        raise ValueError(f"review CSV is missing text column {args.text_col!r}")
    if args.key_col not in reviews.columns:
        reviews[args.key_col] = reviews.index.astype(str)

    if args.in_scope_only:
        reviews_scope = filter_to_in_scope_reviews(
            reviews, smiley_path=args.smiley, matches_path=args.matches
        )
        print(f"In-scope reviews (>= 2022, inside window): {len(reviews_scope)} / {len(reviews)}")
    else:
        reviews_scope = reviews

    rating = pd.to_numeric(reviews_scope.get("rating"), errors="coerce")
    high = reviews_scope[rating.isin([4, 5])].copy()
    review_text = high[args.text_col].fillna("").astype(str).str.strip()
    high = high[review_text.str.len() > 0].copy()
    high[args.text_col] = review_text.loc[high.index]
    high = high.drop_duplicates(args.key_col, keep="first")
    print(f"High-rated (4-5★) candidates with text: {len(high)}")

    if len(high) > args.sample_size:
        high = high.sample(n=args.sample_size, random_state=args.sample_seed)
    high = high.reset_index(drop=True)
    print(f"Sampled {len(high)} reviews for assumption check (seed={args.sample_seed})")

    predictions = classify_dataframe(
        high,
        key_col=args.key_col,
        text_col=args.text_col,
        instructions=instructions,
        model=args.model,
        output_path=args.output,
        ollama_url=args.ollama_url,
        ollama_think=args.ollama_think,
        ollama_keep_alive=args.ollama_keep_alive,
        limit=args.limit,
        max_workers=args.max_workers,
    )

    pred = coerce_prediction_columns(predictions)
    flagged = pred[pred["hygiene_signal"]]
    summary = {
        "model": args.model,
        "sample_size_requested": int(args.sample_size),
        "n_scored": int(len(pred)),
        "n_flagged": int(len(flagged)),
        "flag_rate": float(len(flagged) / len(pred)) if len(pred) else 0.0,
        "per_category_counts": {col: int(pred[col].sum()) for col in HYGIENE_COLS},
        "sample_seed": int(args.sample_seed),
        "in_scope_only": bool(args.in_scope_only),
    }
    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    args.summary_out.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Wrote predictions to {args.output}")
    print(f"Wrote summary to {args.summary_out}")


def aggregate_window_features(panel: pd.DataFrame, predictions: pd.DataFrame) -> pd.DataFrame:
    if "review_id" not in predictions.columns:
        raise ValueError("review prediction file must include review_id")
    pred = predictions.drop_duplicates("review_id", keep="last").set_index("review_id")
    bool_cols = ["hygiene_signal", *HYGIENE_COLS]
    for col in bool_cols:
        pred[col] = pred[col].fillna(False).astype(bool)
    pred["confidence"] = pd.to_numeric(pred.get("confidence", 0.0), errors="coerce").fillna(0.0)

    rows = []
    for _, window in panel.iterrows():
        review_ids = [rid for rid in window["review_ids"] if rid in pred.index]
        if review_ids:
            w = pred.loc[review_ids]
            scored = int(len(w))
            signal = w["hygiene_signal"].astype(bool)
            row = {
                "inspection_id": window["inspection_id"],
                "llm_hygiene_scored_review_count": scored,
                "llm_hygiene_any": bool(signal.any()),
                "llm_hygiene_signal_count": int(signal.sum()),
            }
            for col in HYGIENE_COLS:
                flag_count = int(w[col].sum())
                row[f"llm_{col}_any"] = bool(flag_count > 0)
                row[f"llm_{col}_rate"] = (flag_count / scored) if scored > 0 else 0.0
        else:
            row = {"inspection_id": window["inspection_id"]}
            for col in LLM_WINDOW_FEATURE_COLS:
                row[col] = False if col.endswith("_any") else 0 if col.endswith("_count") else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def write_table(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def aggregate_windows(args: argparse.Namespace) -> None:
    panel = pd.read_parquet(args.panel)
    predictions = read_table(args.predictions)
    features = aggregate_window_features(panel, predictions)
    write_table(features, args.output)
    print(f"Wrote {len(features)} window-level LLM feature rows to {args.output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_OLLAMA_MODEL)
    parser.add_argument(
        "--ollama-url",
        default=DEFAULT_OLLAMA_URL,
        help="base URL for the local Ollama server",
    )
    parser.add_argument(
        "--ollama-think",
        action="store_true",
        default=False,
        help="enable thinking mode for Ollama models that support it (default: off)",
    )
    parser.add_argument(
        "--ollama-keep-alive",
        default=DEFAULT_OLLAMA_KEEP_ALIVE,
        help="how long Ollama keeps the model loaded between requests (e.g. '30m', '2h', '-1' for forever)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="number of concurrent classification requests; set OLLAMA_NUM_PARALLEL on the server to match",
    )
    parser.add_argument("--annotated", type=Path, default=ANNOTATED_PATH)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pool-size", type=int, default=40)
    parser.add_argument(
        "--positive-pool-size",
        type=int,
        default=16,
        help="number of human-positive reviews reserved in the few-shot pool; use -1 for an unstratified random pool",
    )
    parser.add_argument("--max-examples", type=int, default=14)
    parser.add_argument("--max-negatives", type=int, default=4)

    sub = parser.add_subparsers(dest="command", required=True)

    eval_p = sub.add_parser("evaluate-annotated", help="Run held-out evaluation on the human-labeled CSV")
    eval_p.add_argument("--predictions-out", type=Path, default=DEFAULT_EVAL_PREDICTIONS)
    eval_p.add_argument("--metrics-out", type=Path, default=DEFAULT_EVAL_METRICS)
    eval_p.add_argument("--limit", type=int, default=None, help="Classify only the first N eval rows")
    eval_p.set_defaults(func=evaluate_annotated)

    score_p = sub.add_parser("score-full-reviews", help="Classify the full Google review CSV")
    score_p.add_argument("--reviews", type=Path, default=DEFAULT_FULL_REVIEWS)
    score_p.add_argument("--smiley", type=Path, default=DEFAULT_SMILEY_XLSX, help="smileystatus.xlsx for inspection window filtering")
    score_p.add_argument("--matches", type=Path, default=DEFAULT_MATCHES, help="food-service matches CSV for restaurant filtering")
    score_p.add_argument("--output", type=Path, default=DEFAULT_REVIEW_PREDICTIONS)
    score_p.add_argument("--joined-output", type=Path, default=DEFAULT_FULL_REVIEWS_WITH_PREDICTIONS)
    score_p.add_argument("--key-col", default="review_id")
    score_p.add_argument("--text-col", default="review_text")
    score_p.add_argument(
        "--max-rating",
        type=int,
        default=3,
        help="only classify reviews with rating <= this value; 4-5 star reviews are "
        "assumed to carry no hygiene signal a priori. Use -1 to disable.",
    )
    score_p.add_argument("--limit", type=int, default=None)
    score_p.set_defaults(func=score_full_reviews)

    hr_p = sub.add_parser(
        "check-high-rating",
        help="Sample 4-5★ reviews and classify them to validate the no-hygiene-signal assumption",
    )
    hr_p.add_argument("--reviews", type=Path, default=DEFAULT_FULL_REVIEWS)
    hr_p.add_argument("--smiley", type=Path, default=DEFAULT_SMILEY_XLSX)
    hr_p.add_argument("--matches", type=Path, default=DEFAULT_MATCHES)
    hr_p.add_argument("--output", type=Path, default=DEFAULT_HIGH_RATING_PREDICTIONS)
    hr_p.add_argument("--summary-out", type=Path, default=DEFAULT_HIGH_RATING_SUMMARY)
    hr_p.add_argument("--key-col", default="review_id")
    hr_p.add_argument("--text-col", default="review_text")
    hr_p.add_argument("--sample-size", type=int, default=1000)
    hr_p.add_argument("--sample-seed", type=int, default=20260518)
    hr_p.add_argument(
        "--in-scope-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="apply the >=2022 + inside-inspection-window filter before sampling (default: on)",
    )
    hr_p.add_argument("--limit", type=int, default=None)
    hr_p.set_defaults(func=check_high_rating_assumption)

    agg_p = sub.add_parser("aggregate-windows", help="Aggregate review predictions to inspection-window features")
    agg_p.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    agg_p.add_argument("--predictions", type=Path, default=DEFAULT_REVIEW_PREDICTIONS)
    agg_p.add_argument("--output", type=Path, default=DEFAULT_WINDOW_FEATURES)
    agg_p.set_defaults(func=aggregate_windows)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.positive_pool_size is not None and args.positive_pool_size < 0:
        args.positive_pool_size = None
    args.func(args)


if __name__ == "__main__":
    main()
