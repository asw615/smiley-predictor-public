from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
MATCHING_DATA_DIR = DATA_DIR / "matching"
REVIEWS_DATA_DIR = DATA_DIR / "reviews"
LOGS_DATA_DIR = DATA_DIR / "logs"

INPUT_XLSX_PATH = RAW_DATA_DIR / "smileystatus.xlsx"


def ensure_data_directories():
    for directory in [
        DATA_DIR,
        RAW_DATA_DIR,
        PROCESSED_DATA_DIR,
        MATCHING_DATA_DIR,
        REVIEWS_DATA_DIR,
        LOGS_DATA_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
