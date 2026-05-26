# smiley-predictor

Predict a Danish restaurant's next food-safety smiley from its Google
Maps reviews.

Three classes: happy, neutral, sad. Grade 3 is dropped (under 0.3% of
inspections after 2022, not enough to learn from).

## What it does

1. Sample restaurants from the public smiley dataset.
2. Match each to a Google Maps place and scrape reviews.
3. Attach reviews to inspections by date window.
4. Build tabular features. Optionally add six hygiene flags scored by a
   local Gemma 4 via Ollama.
5. Evaluate logistic regression and XGBoost. 5-fold place-grouped CV,
   restaurant-clustered bootstrap CIs.

## Structure

```
data/       raw inputs, processed intermediates, matching, reviews, logs
paper/      Typst paper, compile with `typst compile paper/main.typ`
src/        preprocessing, scraping, features, modeling, analysis, utils
```

## Setup

Two virtualenvs. Playwright and the modeling stack disagree about
transitive deps, so they live apart.

```bash
# Modeling
python3 -m venv .venv-modeling
.venv-modeling/bin/pip install -r requirements-modeling.txt

# Scraping (Python 3.10+)
python3 -m venv .venv
.venv/bin/pip install -r requirements-scraping.txt
.venv/bin/playwright install chromium
```

## Running it

Activate the right venv before each block.

### 1. Sample restaurants, modeling venv

```bash
source .venv-modeling/bin/activate
python src/preprocess.py --n 6000 --output-stem full_6k
```

Writes `data/processed/smileystatus_scrape_full_6k.csv`.

### 2. Scrape Google Maps, scraping venv

```bash
deactivate 2>/dev/null
source .venv/bin/activate

python src/scrape.py setup \
  --input data/processed/smileystatus_scrape_full_6k.csv \
  --output-stem full_6k

python src/scrape.py resolve-places \
  --input data/logs/google_maps_match_input_full_6k.csv \
  --output data/matching/google_maps_matches_full_6k.csv \
  --resolution-json data/logs/google_maps_place_resolution_full_6k.json

python src/scrape.py filter-matches \
  --input  data/matching/google_maps_matches_full_6k.csv \
  --output data/matching/google_maps_matches_full_6k_food_service.csv

python src/scrape.py collect-rpc-reviews \
  --input data/matching/google_maps_matches_full_6k_food_service.csv \
  --output data/reviews/google_reviews_full_6k.csv \
  --restaurants data/processed/smileystatus_scrape_full_6k.csv \
  --session-log data/logs/google_reviews_rpc_sessions_full_6k.csv \
  --batch-log   data/logs/google_reviews_scrape_status_full_6k.csv \
  --max-new-places 500
```

Takes hours and depends on Google's mood. The logs under `data/logs/`
let it resume, so interrupting is fine.

### 3. Features, LLM flags, evaluation, figures, modeling venv

```bash
deactivate
source .venv-modeling/bin/activate

# Features
python -m src.features.panel
python -m src.features.tabular

# Optional: LLM hygiene flags (needs a local Ollama server)
bash src/analysis/run_llm_hygiene_cloud.sh
python -m src.features.llm_hygiene aggregate-windows

# Cross-validated evaluation
python -m src.modeling.eval \
  --features data/processed/features.parquet \
  --llm-window-features data/processed/llm_hygiene_window_features.parquet

# Figures for the paper
python -m src.analysis.results_figures
python -m src.analysis.per_flag_univariate
```

## Data

- `data/raw/smileystatus.xlsx`, the smiley scheme from Fødevarestyrelsen
  ([findsmiley.dk](https://www.foedevarestyrelsen.dk/find-smiley/)).
- `data/raw/Reviews annoteret (200 styks) - Sheet1.csv`, 200
  hand-labelled reviews. Few-shot pool plus held-out eval for the
  Gemma 4 classifier.
- Google Maps reviews are scraped per run via the Maps RPC endpoint
  (`src/scraping/`).
