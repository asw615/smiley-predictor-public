import re
from pathlib import Path

from utils.io import normalize_text, read_csv


RPC_PROVIDER = "google_maps_rpc"


def parse_google_fid(google_maps_url: str):
    match = re.search(r"!1s([^!]+:[^!]+)", google_maps_url or "")
    return match.group(1) if match else ""


def canonicalize_maps_url(url: str):
    normalized = normalize_text(url)
    normalized = re.sub(r"([?&])hl=[^&]+", "", normalized)
    normalized = re.sub(r"([?&])authuser=[^&]+", "", normalized)
    normalized = re.sub(r"([?&])entry=[^&]+", "", normalized)
    normalized = re.sub(r"([?&])g_ep=[^&]+", "", normalized)
    normalized = re.sub(r"([?&])rclk=[^&]+", "", normalized)
    normalized = normalized.replace("?&", "?").rstrip("&? ")
    return normalized


def slugify_place_label(value: str):
    text = normalize_text(value)
    if not text:
        return ""
    text = re.sub(r"\s+", "+", text)
    text = re.sub(r"[^A-Za-z0-9+%_-]", "", text)
    return text


def is_search_maps_url(url: str):
    return "/maps/search/" in (url or "")


def extract_hex_place_token(value: str):
    match = re.search(r"(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)", value or "")
    return match.group(1) if match else ""


def build_canonical_gosom_place_url(row):
    source_url = canonicalize_maps_url(row.get("google_maps_url", ""))
    if not source_url or is_search_maps_url(source_url):
        return ""

    place_token = parse_google_fid(source_url) or extract_hex_place_token(source_url)
    if not place_token:
        place_token = extract_hex_place_token(row.get("google_place_id", ""))
    if not place_token:
        return ""

    slug = slugify_place_label(row.get("matched_name", "")) or "place"
    return f"https://www.google.com/maps/place/{slug}/data=!4m2!3m1!1s{place_token}"


def build_rpc_place_rows(matches_path: Path, restaurant_ids=None, limit: int = 0):
    selected_ids = {normalize_text(value) for value in (restaurant_ids or []) if normalize_text(value)}
    place_rows = []
    skipped_non_canonical = 0
    skipped_non_matched = 0

    for row in read_csv(matches_path):
        if row.get("match_status") != "matched":
            skipped_non_matched += 1
            continue

        restaurant_id = normalize_text(row.get("restaurant_id", ""))
        if selected_ids and restaurant_id not in selected_ids:
            continue

        canonical_url = canonicalize_maps_url(build_canonical_gosom_place_url(row))
        scrape_url = canonical_url or normalize_text(row.get("google_maps_url", ""))
        if not scrape_url:
            skipped_non_canonical += 1
            continue

        normalized_row = dict(row)
        normalized_row["restaurant_id"] = restaurant_id
        normalized_row["google_maps_url"] = scrape_url
        place_rows.append(normalized_row)

    if limit:
        place_rows = place_rows[:limit]

    return {
        "place_rows": place_rows,
        "skipped_non_canonical": skipped_non_canonical,
        "skipped_non_matched": skipped_non_matched,
    }
