import argparse
import asyncio
import hashlib
import json
import random
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

from utils.io import normalize_text, read_csv, write_csv
from utils.paths import (
    LOGS_DATA_DIR,
    MATCHING_DATA_DIR,
    PROCESSED_DATA_DIR,
    REVIEWS_DATA_DIR,
    ensure_data_directories,
)
from scraping.rpc_reviews import (
    RPC_PROVIDER,
    build_rpc_place_rows,
)


DEFAULT_INPUT_PATH = PROCESSED_DATA_DIR / "smileystatus_scrape_full_6k.csv"
DEFAULT_OUTPUT_STEM = "full_6k"
DEFAULT_MATCH_INPUT_PATH = LOGS_DATA_DIR / f"google_maps_match_input_{DEFAULT_OUTPUT_STEM}.csv"
DEFAULT_MATCHES_PATH = MATCHING_DATA_DIR / f"google_maps_matches_{DEFAULT_OUTPUT_STEM}.csv"
DEFAULT_FILTERED_MATCHES_PATH = MATCHING_DATA_DIR / f"google_maps_matches_{DEFAULT_OUTPUT_STEM}_food_service.csv"
DEFAULT_REVIEWS_PATH = REVIEWS_DATA_DIR / f"google_reviews_{DEFAULT_OUTPUT_STEM}.csv"
DEFAULT_RPC_REVIEWS_PATH = REVIEWS_DATA_DIR / f"google_reviews_{DEFAULT_OUTPUT_STEM}.csv"
DEFAULT_RPC_SESSION_LOG_PATH = LOGS_DATA_DIR / f"google_reviews_rpc_sessions_{DEFAULT_OUTPUT_STEM}.csv"
DEFAULT_RPC_BATCH_LOG_PATH = LOGS_DATA_DIR / f"google_reviews_scrape_status_{DEFAULT_OUTPUT_STEM}.csv"
DEFAULT_RESOLUTION_JSON_PATH = LOGS_DATA_DIR / f"google_maps_place_resolution_{DEFAULT_OUTPUT_STEM}.json"

SMILEY_DATE_COLUMNS = [
    "seneste_kontrol_dato",
    "naestseneste_kontrol_dato",
    "tredjeseneste_kontrol_dato",
    "fjerdeseneste_kontrol_dato",
]

MATCH_INPUT_HEADERS = [
    "restaurant_id",
    "navnelbnr",
    "cvrnr",
    "name",
    "address",
    "postal_code",
    "city",
    "smiley_url",
    "google_query",
    "google_maps_search_url",
]

MATCHES_HEADERS = [
    "restaurant_id",
    "navnelbnr",
    "provider",
    "match_status",
    "google_place_id",
    "google_fid",
    "google_cid",
    "google_maps_url",
    "matched_name",
    "matched_address",
    "matched_postal_code",
    "matched_city",
    "matched_primary_category",
    "matched_categories",
    "matched_rating",
    "matched_review_count",
    "matched_price_level",
    "matched_price_median_dkk",
    "match_confidence",
    "match_notes",
    "matched_at",
]

REVIEWS_HEADERS = [
    "restaurant_id",
    "provider",
    "google_place_id",
    "google_fid",
    "google_maps_url",
    "review_id",
    "review_url",
    "reviewer_id",
    "reviewer_name",
    "reviewer_profile_url",
    "reviewer_review_count",
    "reviewer_is_local_guide",
    "rating",
    "review_text",
    "review_language",
    "published_at",
    "published_at_relative",
    "published_at_estimated_date",
    "published_at_estimated_days_ago",
    "edited_at",
    "likes_count",
    "owner_response_text",
    "owner_response_at",
    "review_sort_order",
    "scraped_at",
]

RPC_SESSION_HEADERS = [
    "restaurant_id",
    "matched_name",
    "google_place_id",
    "google_maps_url",
    "status",
    "attempts",
    "used_search_navigation",
    "review_rows_written",
    "review_rows_seen",
    "navigation_kind",
    "stop_reason",
    "started_at",
    "completed_at",
    "duration_seconds",
    "error",
]

RPC_BATCH_HEADERS = [
    "status",
    "matches_path",
    "output_path",
    "session_log_path",
    "started_at",
    "updated_at",
    "target_places",
    "attempted_places",
    "completed_places",
    "failed_places",
    "pending_places",
    "skipped_non_canonical",
    "skipped_completed_places",
    "used_search_navigation_places",
    "review_rows_written",
    "review_rows_with_exact_published_at",
    "review_rows_with_exact_edited_at",
    "completed_places_with_known_review_count",
    "expected_review_count_sum",
    "collected_review_count_sum_known_places",
    "review_completeness_ratio",
    "median_duration_seconds",
    "mean_duration_seconds",
    "failure_rate",
    "completed_restaurant_ids",
    "failed_restaurant_ids",
    "pending_restaurant_ids",
]

REVIEW_SORT_LABELS = {
    "most_relevant": ["Mest relevante", "Most relevant"],
    "newest": ["Nyeste", "Newest"],
    "highest_rating": ["Højeste bedømmelse", "Highest rating"],
    "lowest_rating": ["Laveste bedømmelse", "Lowest rating"],
}

# Food-service filter rule:
# A row passes iff its haystack (normalized primary_category + name) contains
# at least one INCLUDE keyword AND does not contain any EXCLUDE keyword AND
# its primary category is not a price-range string (e.g. "100-200 kr.").
# "hotel" is intentionally absent from EXCLUDE: hotels without a restaurant
# operation don't match any INCLUDE keyword and are dropped anyway; including
# hotel-restaurants and kro-hotels was the correct intent.
FOOD_SERVICE_INCLUDE_KEYWORDS = [
    "restaurant",
    "restauranter",
    "bistro",
    "cafe",
    "café",
    "cafeteria",
    "coffee",
    "kaffe",
    "pizza",
    "pizzeria",
    "burger",
    "sushi",
    "grill",
    "bar",
    "bbq",
    "barbeque",
    "barbecue",
    "take away",
    "takeaway",
    "thai",
    "bager",
    "bakery",
    "isbutik",
    "ice cream",
    "sandwich",
    "sandwichbar",
    "deli",
    "delikatesse",
    "street food",
    "food court",
    "spisestue",
    "spisested",
    "kro",
    "gastropub",
    "pølsebod",
    "polsebod",
    "madbod",
    "kebab",
    "kebabbutik",
    "catering",
    "madselskab",
    "madpartner",
    "frokostordning",
]

FOOD_SERVICE_EXCLUDE_KEYWORDS = [
    "uddannelsesinstitution",
    "school",
    "apotek",
    "pharmacy",
    "plejehjem",
    "hospital",
    "bank",
    "campingplads",
    "byggemarked",
    "hardware",
]

# Matches strings like "100-200 kr." or "50 kr." that Google Maps returns as
# a pricing tier rather than an actual category name.
import re as _re
_PRICE_RANGE_RE = _re.compile(r"^\d.*kr\.?$")

REVIEW_EXTRACTOR_JS = r"""
() => {
  const cards = [...document.querySelectorAll('div.jftiEf')];
  return cards.map((card, index) => {
    const reviewerButton = card.querySelector('button.al6Kxe');
    const ratingLabel = card.querySelector('span[role="img"]')?.getAttribute('aria-label') || '';
    const ownerBlock = [...card.querySelectorAll('div, span')]
      .map((el) => (el.innerText || '').trim())
      .find((text) =>
        text.startsWith('Svar fra ejeren') ||
        text.startsWith('Response from the owner') ||
        text.startsWith('Response from owner')
      ) || '';
    return {
      review_id: card.getAttribute('data-review-id') || reviewerButton?.getAttribute('data-review-id') || '',
      reviewer_name: card.querySelector('.d4r55')?.innerText?.trim() || '',
      reviewer_profile_url: reviewerButton?.getAttribute('data-href') || card.querySelector('a[href*="/maps/contrib/"]')?.href || '',
      reviewer_meta: card.querySelector('.RfnDt')?.innerText?.trim() || '',
      rating_label: ratingLabel,
      published_text: card.querySelector('.rsqaWe')?.innerText?.trim() || '',
      review_text: card.querySelector('.wiI7pd')?.innerText?.trim()
        || card.querySelector('.MyEned')?.innerText?.trim()
        || '',
      owner_response_text: ownerBlock,
      likes_text: [...card.querySelectorAll('button, span, div')]
        .map((el) => (el.innerText || '').trim())
        .find((text) => /^[0-9]+$/.test(text)) || '',
      language: document.documentElement.lang || '',
      review_url: '',
      reviewer_id: '',
      edited_at: '',
      owner_response_at: '',
      card_index: index,
    };
  });
}
"""


PLACE_METADATA_EXTRACTOR_JS = r"""
() => {
  const result = { price_level: '', price_median_dkk: '', categories: '' };
  const currencyRe = /^[€$£¥₩₹₽₺₴₪₫₦₱฿₡₲₭₮₵₸₼₾₿]{1,4}$/;
  const priceLabelRe = /\b(price|pris|prisklasse|prisniveau)\b/i;
  const priceValueRe = /\b(cheap|inexpensive|moderate|moderately expensive|expensive|very expensive|billig|moderat|middel|mellemklasse|dyr|meget dyr)\b/i;
  const priceRangeRe = /(?:over\s*\d[\d.]*\s*kr\.?|\d[\d.]*\s*-\s*\d[\d.]*\s*kr\.?)/gi;
  const clean = raw => (raw || '').replace(/\s+/g, ' ').trim();
  const priceRanges = raw => {
    const seenRanges = new Set();
    return (clean(raw).match(priceRangeRe) || [])
      .map(range => clean(range))
      .filter(range => {
        const key = range.toLowerCase();
        if (seenRanges.has(key)) return false;
        seenRanges.add(key);
        return true;
      });
  };
  const parseDkk = raw => Number(String(raw || '').replace(/\./g, '').replace(',', '.'));
  const histogramMedian = table => {
    const bins = [];
    for (const row of table.querySelectorAll('tr')) {
      const label = clean(row.querySelector('td')?.innerText || '');
      const percentLabel = row.querySelector('[role="img"][aria-label]')?.getAttribute('aria-label') || '';
      const percentMatch = percentLabel.match(/(\d+(?:[,.]\d+)?)\s*%/);
      if (!percentMatch) continue;
      const rangeMatch = label.match(/^(\d[\d.]*)\s*-\s*(\d[\d.]*)\s*kr\.?$/i);
      const openMatch = label.match(/^over\s*(\d[\d.]*)\s*kr\.?$/i);
      let low = null;
      let high = null;
      if (rangeMatch) {
        low = parseDkk(rangeMatch[1]);
        high = parseDkk(rangeMatch[2]);
      } else if (openMatch) {
        low = parseDkk(openMatch[1]);
      }
      const percent = parseDkk(percentMatch[1]);
      if (Number.isFinite(low) && Number.isFinite(percent) && percent > 0) {
        bins.push({ low, high, percent });
      }
    }
    if (!bins.length) return '';
    const widths = bins
      .filter(bin => Number.isFinite(bin.high) && bin.high > bin.low)
      .map(bin => bin.high - bin.low);
    const fallbackWidth = widths.length ? widths[widths.length - 1] : 100;
    const total = bins.reduce((sum, bin) => sum + bin.percent, 0);
    if (!total) return '';
    const midpoint = total / 2;
    let cumulative = 0;
    for (const bin of bins) {
      const previous = cumulative;
      cumulative += bin.percent;
      if (cumulative >= midpoint) {
        const high = Number.isFinite(bin.high) ? bin.high : bin.low + fallbackWidth;
        const fraction = Math.max(0, Math.min(1, (midpoint - previous) / bin.percent));
        return String(Math.round(bin.low + fraction * (high - bin.low)));
      }
    }
    const last = bins[bins.length - 1];
    return String(Math.round(last.low));
  };
  const setPrice = raw => {
    const text = clean(raw);
    if (!text || result.price_level) return;
    if (currencyRe.test(text)) {
      result.price_level = text;
      return;
    }
    const symbolMatch = text.match(/[€$£¥₩₹₽₺₴₪₫₦₱฿₡₲₭₮₵₸₼₾₿]{1,4}/);
    if (symbolMatch && priceLabelRe.test(text)) {
      result.price_level = symbolMatch[0];
      return;
    }
    const ranges = priceRanges(text);
    if (ranges.length) {
      result.price_level = ranges.join('; ');
      return;
    }
    if (priceLabelRe.test(text) && text.length <= 80) {
      const valueMatch = text.match(priceValueRe);
      result.price_level = valueMatch ? valueMatch[0] : text;
      return;
    }
    if (priceValueRe.test(text) && /prisniveau|price level/i.test(text)) {
      result.price_level = text.match(priceValueRe)[0];
    }
  };

  // --- Price level: span[role="img"] with currency innerText ---
  // Google Maps uses <span role="img" aria-label="Moderat prisniveau">$$</span>
  for (const el of document.querySelectorAll('span[role="img"]')) {
    setPrice(el.innerText || el.getAttribute('aria-label') || '');
    if (result.price_level) break;
  }

  // --- Categories + price level from .DkEaL cluster ---
  const seen = new Set();
  const cats = [];
  const addCat = raw => {
    const t = clean(raw);
    if (t.length > 1 && t.length < 80 && !/^(tilføj|add )/i.test(t) && !/^[€$£¥·•\s\d]+$/.test(t) && !seen.has(t.toLowerCase())) {
      seen.add(t.toLowerCase());
      cats.push(t);
    }
  };
  for (const el of document.querySelectorAll('button.DkEaL, a.DkEaL, span.DkEaL')) {
    const text = clean(el.innerText || el.getAttribute('aria-label') || '');
    if (!result.price_level && (currencyRe.test(text) || priceLabelRe.test(text))) {
      setPrice(text);
    } else {
      addCat(text);
    }
  }

  // --- Price level fallback: aria-label containing pris/price ---
  if (!result.price_level) {
    for (const el of document.querySelectorAll('[aria-label]')) {
      const label = el.getAttribute('aria-label') || '';
      if (priceLabelRe.test(label)) {
        setPrice(el.innerText || label);
        if (result.price_level) break;
      }
    }
  }

  // --- Price range fallback: Danish Maps may expose a "prisintervaller" histogram instead of "$$" ---
  if (!result.price_level) {
    for (const el of document.querySelectorAll('[aria-label], table, div')) {
      const label = el.getAttribute('aria-label') || '';
      const text = clean(el.innerText || el.textContent || '');
      if (/prisintervaller|price ranges|price intervals/i.test(label) || priceRanges(text).length >= 2) {
        setPrice(text);
        if (result.price_level) break;
      }
    }
  }
  for (const table of document.querySelectorAll('table[aria-label]')) {
    const label = table.getAttribute('aria-label') || '';
    if (/prisintervaller|price ranges|price intervals/i.test(label)) {
      result.price_median_dkk = histogramMedian(table);
      break;
    }
  }

  // --- Category fallback: "€€ · Category" spans ---
  if (!cats.length) {
    for (const el of document.querySelectorAll('span')) {
      if (el.children.length) continue;
      const text = clean(el.innerText || '');
      const split = text.match(/^([€$£¥₩₹₽₺₴₪₫₦₱฿₡₲₭₮₵₸₼₾₿]{1,4})\s*[·•]\s*(.{2,60})$/);
      if (split) { setPrice(split[1]); addCat(split[2]); continue; }
      if (!result.price_level) setPrice(text);
      const m = text.match(/^(?:[€$£¥₩₹₽₺₴₪₫₦₱฿₡₲₭₮₵₸₼₾₿]{0,4}\s*[·•]\s*)(.{2,60})$/);
      if (m) { addCat(m[1]); if (cats.length >= 5) break; }
    }
  }

  result.categories = cats.join(', ');
  return result;
}
"""


def safe_get(value, *indexes):
    current = value
    for index in indexes:
        if not isinstance(current, list) or len(current) <= index:
            return None
        current = current[index]
    return current


def build_google_query(row):
    parts = [
        normalize_text(row.get("navn1", "")),
        normalize_text(row.get("adresse1", "")),
        normalize_text(row.get("postnr", "")),
        normalize_text(row.get("By", "")),
        "Denmark",
    ]
    return ", ".join(part for part in parts if part)


def build_match_input_rows(rows):
    prepared_rows = []
    for row in rows:
        restaurant_id = normalize_text(row.get("navnelbnr", ""))
        google_query = build_google_query(row)
        prepared_rows.append(
            {
                "restaurant_id": restaurant_id,
                "navnelbnr": restaurant_id,
                "cvrnr": normalize_text(row.get("cvrnr", "")),
                "name": normalize_text(row.get("navn1", "")),
                "address": normalize_text(row.get("adresse1", "")),
                "postal_code": normalize_text(row.get("postnr", "")),
                "city": normalize_text(row.get("By", "")),
                "smiley_url": normalize_text(row.get("URL", "")),
                "google_query": google_query,
                "google_maps_search_url": (
                    "https://www.google.com/maps/search/?api=1&query="
                    + quote_plus(google_query)
                ),
            }
        )
    return prepared_rows


def setup_pipeline(input_path: Path, output_stem: str):
    ensure_data_directories()
    rows = read_csv(input_path)
    match_input_rows = build_match_input_rows(rows)

    match_input_path = LOGS_DATA_DIR / f"google_maps_match_input_{output_stem}.csv"
    matches_path = MATCHING_DATA_DIR / f"google_maps_matches_{output_stem}.csv"

    write_csv(match_input_path, MATCH_INPUT_HEADERS, match_input_rows)
    write_csv(matches_path, MATCHES_HEADERS, [])

    return {
        "match_input_rows": len(match_input_rows),
        "match_input_path": match_input_path,
        "matches_path": matches_path,
    }

def parse_reviewer_meta(meta_text: str):
    review_count = ""
    is_local_guide = False
    if not meta_text:
        return review_count, is_local_guide

    normalized = normalize_text(meta_text)
    is_local_guide = "local guide" in normalized.lower()
    match = re.search(r"([0-9][0-9\.\,]*)\s+(?:anmeldelser|reviews|review)", normalized, re.I)
    if match:
        review_count = match.group(1).replace(".", "").replace(",", "")
    return review_count, is_local_guide


def parse_rating_label(rating_label: str):
    if not rating_label:
        return ""
    match = re.search(r"([0-9]+(?:[.,][0-9]+)?)", rating_label)
    return match.group(1).replace(",", ".") if match else ""


def parse_relative_time_text(relative_text: str, scraped_at: datetime):
    text = normalize_text(relative_text).lower()
    if not text:
        return "", ""

    patterns = [
        (r"for\s+(\d+)\s+minut(?:ter)?\s+siden", 1 / 1440),
        (r"for\s+én\s+minut\s+siden", 1 / 1440),
        (r"for\s+et\s+minut\s+siden", 1 / 1440),
        (r"for\s+(\d+)\s+time(?:r)?\s+siden", 1 / 24),
        (r"for\s+en\s+time\s+siden", 1 / 24),
        (r"for\s+(\d+)\s+dag(?:e)?\s+siden", 1),
        (r"for\s+en\s+dag\s+siden", 1),
        (r"for\s+(\d+)\s+uge(?:r)?\s+siden", 7),
        (r"for\s+én\s+uge\s+siden", 7),
        (r"for\s+(\d+)\s+måned(?:er)?\s+siden", 30),
        (r"for\s+én\s+måned\s+siden", 30),
        (r"for\s+(\d+)\s+år\s+siden", 365),
        (r"for\s+et\s+år\s+siden", 365),
        (r"(\d+)\s+minutes?\s+ago", 1 / 1440),
        (r"a\s+minute\s+ago", 1 / 1440),
        (r"(\d+)\s+hours?\s+ago", 1 / 24),
        (r"an\s+hour\s+ago", 1 / 24),
        (r"(\d+)\s+days?\s+ago", 1),
        (r"a\s+day\s+ago", 1),
        (r"(\d+)\s+weeks?\s+ago", 7),
        (r"a\s+week\s+ago", 7),
        (r"(\d+)\s+months?\s+ago", 30),
        (r"a\s+month\s+ago", 30),
        (r"(\d+)\s+years?\s+ago", 365),
        (r"a\s+year\s+ago", 365),
    ]

    for pattern, day_multiplier in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        count = 1
        if match.groups():
            count = int(match.group(1))
        days_ago = count * day_multiplier
        estimated_datetime = scraped_at - timedelta(days=days_ago)
        return estimated_datetime.date().isoformat(), str(days_ago)

    return "", ""


def microseconds_to_iso8601(value):
    if value in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc).isoformat()
    except Exception:
        return ""


def parse_listugcposts_payload(response_text: str):
    if not response_text:
        return []
    text = response_text
    if text.startswith(")]}'"):
        text = text[4:]
    payload = json.loads(text)
    review_entries = safe_get(payload, 2, 0) or []
    parsed_reviews = []

    for entry in review_entries:
        root = safe_get(entry, 1) or []
        reviewer = safe_get(root, 4, 5) or []
        language = safe_get(entry, 2, 14, 0) or ""
        text_value = safe_get(entry, 2, 15, 0, 0) or ""
        published_at = microseconds_to_iso8601(safe_get(root, 2))
        edited_at = microseconds_to_iso8601(safe_get(root, 3))
        parsed_reviews.append(
            {
                "network_review_id": safe_get(entry, 0) or "",
                "published_at": published_at,
                "edited_at": edited_at,
                "published_at_relative": safe_get(root, 6) or "",
                "reviewer_name": safe_get(reviewer, 0) or "",
                "reviewer_profile_url": safe_get(reviewer, 2, 0) or "",
                "reviewer_id": safe_get(reviewer, 3) or "",
                "reviewer_review_count": str(safe_get(reviewer, 5) or ""),
                "reviewer_is_local_guide": str("Local Guide" in normalize_text(safe_get(reviewer, 10, 0) or "")),
                "rating": str(safe_get(root, 14, 4) or ""),
                "review_text": text_value,
                "review_language": language,
                "review_url": safe_get(entry, 4, 3, 0) or "",
                "likes_count": "",
                "owner_response_text": "",
                "owner_response_at": "",
            }
        )
    return parsed_reviews


def build_network_review_lookup(network_reviews):
    lookup = {}
    for review in network_reviews:
        key = (
            normalize_text(review.get("reviewer_name", "")).lower(),
            normalize_text(review.get("published_at_relative", "")).lower(),
            normalize_text(review.get("review_text", ""))[:120].lower(),
        )
        lookup.setdefault(key, []).append(review)
    return lookup


def normalize_network_review_record(place_row, network_review, sort_key):
    scraped_at = datetime.now(timezone.utc)
    published_at = normalize_text(network_review.get("published_at", ""))
    published_relative = normalize_text(network_review.get("published_at_relative", ""))
    published_date = published_at[:10] if published_at else ""
    published_days_ago = ""
    if published_at:
        try:
            published_dt = datetime.fromisoformat(published_at)
            published_days_ago = str(round((scraped_at - published_dt).total_seconds() / 86400, 3))
        except Exception:
            published_days_ago = ""

    return {
        "restaurant_id": place_row["restaurant_id"],
        "provider": RPC_PROVIDER,
        "google_place_id": place_row.get("google_place_id", ""),
        "google_fid": place_row.get("google_fid", ""),
        "google_maps_url": place_row.get("google_maps_url", ""),
        "review_id": normalize_text(network_review.get("network_review_id", "")),
        "review_url": normalize_text(network_review.get("review_url", "")),
        "reviewer_id": normalize_text(network_review.get("reviewer_id", "")),
        "reviewer_name": normalize_text(network_review.get("reviewer_name", "")),
        "reviewer_profile_url": normalize_text(network_review.get("reviewer_profile_url", "")),
        "reviewer_review_count": normalize_text(network_review.get("reviewer_review_count", "")),
        "reviewer_is_local_guide": normalize_text(network_review.get("reviewer_is_local_guide", "")),
        "rating": normalize_text(network_review.get("rating", "")),
        "review_text": normalize_text(network_review.get("review_text", "")),
        "review_language": normalize_text(network_review.get("review_language", "")),
        "published_at": published_at or published_relative,
        "published_at_relative": published_relative,
        "published_at_estimated_date": published_date,
        "published_at_estimated_days_ago": published_days_ago,
        "edited_at": normalize_text(network_review.get("edited_at", "")),
        "likes_count": normalize_text(network_review.get("likes_count", "")),
        "owner_response_text": normalize_text(network_review.get("owner_response_text", "")),
        "owner_response_at": normalize_text(network_review.get("owner_response_at", "")),
        "review_sort_order": sort_key,
        "scraped_at": scraped_at.isoformat(),
    }


def make_fallback_review_id(restaurant_id: str, record):
    fingerprint = "|".join(
        [
            restaurant_id,
            normalize_text(record.get("reviewer_name", "")),
            normalize_text(record.get("published_text", "")),
            normalize_text(record.get("review_text", ""))[:200],
        ]
    )
    return hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()


def parse_google_fid(google_maps_url: str):
    match = re.search(r"!1s([^!]+:[^!]+)", google_maps_url or "")
    return match.group(1) if match else ""


def extract_hex_place_token(value: str):
    match = re.search(r"(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)", value or "")
    return match.group(1) if match else ""


def build_canonical_maps_place_url(place_name: str, place_token: str):
    if not place_token:
        return ""
    slug = quote_plus(normalize_text(place_name) or "place")
    return f"https://www.google.com/maps/place/{slug}/data=!4m2!3m1!1s{place_token}"


def enrich_place_row_from_browser_url(place_row, browser_url: str):
    resolved_url = normalize_text(browser_url)
    place_token = parse_google_fid(resolved_url) or extract_hex_place_token(resolved_url)
    if not place_token:
        return place_row

    enriched_row = dict(place_row)
    enriched_row["google_place_id"] = normalize_text(enriched_row.get("google_place_id", "")) or place_token
    enriched_row["google_fid"] = normalize_text(enriched_row.get("google_fid", "")) or place_token
    enriched_row["google_maps_url"] = (
        build_canonical_maps_place_url(enriched_row.get("matched_name", ""), place_token)
        or resolved_url
    )
    return enriched_row


def canonicalize_maps_input_url(url: str):
    normalized = normalize_text(url)
    normalized = re.sub(r"([?&])hl=[^&]+", "", normalized)
    normalized = normalized.replace("?&", "?").rstrip("&? ")
    return normalized


def normalize_resolution_results(source_rows, scrape_results):
    rows_by_url = {
        canonicalize_maps_input_url(row["google_maps_search_url"]): row for row in source_rows
    }
    results_by_url = {
        canonicalize_maps_input_url(result.input_url): result for result in scrape_results
    }
    normalized_rows = []
    matched_count = 0

    for input_url, source_row in rows_by_url.items():
        result = results_by_url.get(input_url)
        place = result.place if result and result.success else None
        google_maps_url = normalize_text(getattr(place, "google_maps_url", "") or getattr(place, "url", ""))
        match_status = "matched" if google_maps_url else "not_found"
        if match_status == "matched":
            matched_count += 1

        normalized_rows.append(
            {
                "restaurant_id": source_row["restaurant_id"],
                "navnelbnr": source_row["navnelbnr"],
                "provider": "gmaps_scraper",
                "match_status": match_status,
                "google_place_id": normalize_text(getattr(place, "place_id", "") if place else ""),
                "google_fid": parse_google_fid(google_maps_url),
                "google_cid": "",
                "google_maps_url": google_maps_url,
                "matched_name": normalize_text(getattr(place, "name", "") if place else ""),
                "matched_address": normalize_text(getattr(place, "address", "") if place else ""),
                "matched_postal_code": source_row["postal_code"],
                "matched_city": source_row["city"],
                "matched_primary_category": normalize_text(getattr(place, "category", "") if place else ""),
                "matched_categories": normalize_text(getattr(place, "categories", "") if place else ""),
                "matched_rating": normalize_text(getattr(place, "rating", "") if place else ""),
                "matched_review_count": normalize_text(getattr(place, "review_count", "") if place else ""),
                "matched_price_level": normalize_text(getattr(place, "price_level", "") if place else ""),
                "matched_price_median_dkk": "",
                "match_confidence": "auto_unverified" if google_maps_url else "none",
                "match_notes": (
                    "Automatically resolved from Google Maps search URL; not manually verified."
                    if google_maps_url
                    else normalize_text(result.error if result else "No result returned.")
                ),
                "matched_at": datetime.now(timezone.utc).isoformat() if google_maps_url else "",
            }
        )

    return normalized_rows, matched_count


def normalize_match_text(value: str):
    text = normalize_text(value).lower()
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def is_food_service_match(row):
    category = normalize_match_text(row.get("matched_primary_category", ""))
    name = normalize_match_text(row.get("matched_name", ""))
    haystack = " ".join(part for part in [category, name] if part)
    if not haystack:
        return False
    if category and any(keyword in category for keyword in FOOD_SERVICE_EXCLUDE_KEYWORDS):
        return False
    # Reject rows where Google returned a pricing tier string as the primary
    # category (e.g. "100-200 kr.") — those are garbage matches.
    raw_category = str(row.get("matched_primary_category", "")).strip()
    if raw_category and _PRICE_RANGE_RE.match(raw_category):
        return False
    return any(keyword in haystack for keyword in FOOD_SERVICE_INCLUDE_KEYWORDS)


def filter_matches_for_food_service(input_path: Path, output_path: Path):
    ensure_data_directories()
    rows = read_csv(input_path)
    filtered_rows = [row for row in rows if row.get("match_status") == "matched" and is_food_service_match(row)]
    write_csv(output_path, MATCHES_HEADERS, filtered_rows)
    return {
        "input_rows": len(rows),
        "filtered_rows": len(filtered_rows),
        "output_path": output_path,
    }


def resolve_places(match_input_path: Path, output_path: Path, resolution_json_path: Path, concurrency: int, language: str):
    ensure_data_directories()
    from gmaps_scraper import ScrapeConfig, scrape_batch

    source_rows = read_csv(match_input_path)
    urls = [row["google_maps_search_url"] for row in source_rows if row.get("google_maps_search_url")]
    config = ScrapeConfig(
        concurrency=concurrency,
        headless=True,
        language=language,
        delay_min=2.0,
        delay_max=4.0,
        save_interval=10,
    )
    scrape_results = asyncio.run(
        scrape_batch(urls=urls, config=config, output_path=resolution_json_path, resume=True)
    )
    normalized_rows, matched_count = normalize_resolution_results(source_rows, scrape_results)
    write_csv(output_path, MATCHES_HEADERS, normalized_rows)
    return {
        "input_rows": len(source_rows),
        "matched_rows": matched_count,
        "output_path": output_path,
        "resolution_json_path": resolution_json_path,
    }


def build_place_search_query(place_row):
    parts = [
        normalize_text(place_row.get("matched_name", "")),
        normalize_text(place_row.get("matched_address", "")),
        normalize_text(place_row.get("matched_postal_code", "")),
        normalize_text(place_row.get("matched_city", "")),
        "Denmark",
    ]
    return ", ".join(part for part in parts if part)


def build_search_navigation_url(place_row):
    query = build_place_search_query(place_row)
    if not query:
        return ""
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(query)


def build_existing_review_rows(existing_rows, restaurant_ids_to_replace):
    replace_ids = {
        normalize_text(restaurant_id)
        for restaurant_id in restaurant_ids_to_replace
        if normalize_text(restaurant_id)
    }
    if not replace_ids:
        return list(existing_rows)
    return [
        row
        for row in existing_rows
        if normalize_text(row.get("restaurant_id", "")) not in replace_ids
    ]


def build_completed_restaurant_ids(session_rows):
    return {
        normalize_text(row.get("restaurant_id", ""))
        for row in session_rows
        if normalize_text(row.get("status", "")) == "completed"
    }


def upsert_rpc_session_row(session_rows, session_row):
    restaurant_id = normalize_text(session_row.get("restaurant_id", ""))
    updated_rows = [
        row
        for row in session_rows
        if normalize_text(row.get("restaurant_id", "")) != restaurant_id
    ]
    updated_rows.append(session_row)
    return updated_rows


async def wait_random_seconds(min_seconds: float, max_seconds: float):
    if max_seconds <= 0:
        return
    lower = max(0.0, min_seconds)
    upper = max(lower, max_seconds)
    await asyncio.sleep(random.uniform(lower, upper))


def parse_bool_text(value):
    return normalize_text(value).lower() == "true"


def parse_int_text(value):
    text = normalize_text(value)
    if not text:
        return None
    text = text.replace(".", "").replace(",", "")
    return int(text) if text.isdigit() else None


def parse_float_text(value):
    text = normalize_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def excel_serial_to_datetime(serial_value: str):
    if not normalize_text(serial_value):
        return None
    try:
        serial = int(float(serial_value))
    except Exception:
        return None
    return datetime(1899, 12, 30) + timedelta(days=serial)


def parse_review_cutoff_datetime(value: str):
    text = normalize_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except Exception:
        pass
    try:
        return datetime.fromisoformat(text[:10])
    except Exception:
        return None


def build_review_bounds_by_restaurant(restaurants_path: Path | None):
    if not restaurants_path:
        return {}

    bounds = {}
    for row in read_csv(restaurants_path):
        restaurant_id = normalize_text(row.get("navnelbnr", ""))
        control_dates = [
            date_value
            for date_value in (
                excel_serial_to_datetime(row.get(column, ""))
                for column in SMILEY_DATE_COLUMNS
            )
            if date_value is not None
        ]
        if restaurant_id and len(control_dates) >= 2:
            bounds[restaurant_id] = {
                "start": min(control_dates),
                "end": max(control_dates),
            }
    return bounds


def oldest_review_datetime(review_rows):
    dates = []
    for row in review_rows:
        published_at = (
            parse_review_cutoff_datetime(row.get("published_at", ""))
            or parse_review_cutoff_datetime(row.get("published_at_estimated_date", ""))
        )
        if published_at is not None:
            dates.append(published_at)
    return min(dates) if dates else None


def trim_reviews_to_bounds(review_rows, review_bounds):
    if not review_bounds:
        return list(review_rows)

    start_datetime = review_bounds["start"]
    end_datetime = review_bounds["end"]
    trimmed_rows = []
    for row in review_rows:
        published_at = (
            parse_review_cutoff_datetime(row.get("published_at", ""))
            or parse_review_cutoff_datetime(row.get("published_at_estimated_date", ""))
        )
        if published_at is not None and start_datetime < published_at <= end_datetime:
            trimmed_rows.append(row)
    return trimmed_rows


def compute_median(values):
    if not values:
        return ""
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return round(sorted_values[midpoint], 3)
    return round((sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2, 3)


def is_exact_timestamp(value: str):
    return "T" in normalize_text(value)


def build_rpc_batch_status(completed_places: int, failed_places: int, pending_places: int):
    if pending_places:
        return "in_progress"
    if completed_places == 0 and failed_places == 0:
        return "not_started"
    if failed_places:
        return "completed_with_failures"
    return "completed"


def summarize_rpc_collection(
    target_place_rows,
    review_rows,
    session_rows,
    matches_path: Path | None = None,
    output_path: Path | None = None,
    session_log_path: Path | None = None,
    started_at: str = "",
    updated_at: str = "",
    skipped_non_canonical: int = 0,
    skipped_completed_places: int = 0,
):
    target_ids = []
    target_place_by_id = {}
    for row in target_place_rows:
        restaurant_id = normalize_text(row.get("restaurant_id", ""))
        if not restaurant_id or restaurant_id in target_place_by_id:
            continue
        target_ids.append(restaurant_id)
        target_place_by_id[restaurant_id] = row
    target_id_set = set(target_ids)

    latest_session_by_restaurant = {}
    for row in session_rows:
        restaurant_id = normalize_text(row.get("restaurant_id", ""))
        if restaurant_id and restaurant_id in target_id_set:
            latest_session_by_restaurant[restaurant_id] = row

    reviews_by_restaurant = defaultdict(list)
    exact_published_at = 0
    exact_edited_at = 0
    for row in review_rows:
        restaurant_id = normalize_text(row.get("restaurant_id", ""))
        if restaurant_id not in target_id_set:
            continue
        reviews_by_restaurant[restaurant_id].append(row)
        if is_exact_timestamp(row.get("published_at", "")):
            exact_published_at += 1
        if is_exact_timestamp(row.get("edited_at", "")):
            exact_edited_at += 1

    completed_ids = []
    failed_ids = []
    used_search_navigation_places = 0
    duration_seconds = []
    expected_review_count_sum = 0
    collected_review_count_sum_known_places = 0
    completed_places_with_known_review_count = 0

    for restaurant_id in target_ids:
        session_row = latest_session_by_restaurant.get(restaurant_id)
        if not session_row:
            continue

        status = normalize_text(session_row.get("status", ""))
        if parse_bool_text(session_row.get("used_search_navigation", "")):
            used_search_navigation_places += 1
        duration_value = parse_float_text(session_row.get("duration_seconds", ""))
        if duration_value is not None:
            duration_seconds.append(duration_value)

        if status == "completed":
            completed_ids.append(restaurant_id)
            expected_review_count = parse_int_text(
                target_place_by_id[restaurant_id].get("matched_review_count", "")
            )
            if expected_review_count is not None:
                completed_places_with_known_review_count += 1
                expected_review_count_sum += expected_review_count
                collected_review_count_sum_known_places += len(
                    {
                        normalize_text(review.get("review_id", ""))
                        for review in reviews_by_restaurant.get(restaurant_id, [])
                    }
                )
        elif status == "failed":
            failed_ids.append(restaurant_id)

    pending_ids = [
        restaurant_id
        for restaurant_id in target_ids
        if restaurant_id not in set(completed_ids) and restaurant_id not in set(failed_ids)
    ]

    target_places = len(target_ids)
    attempted_places = len(latest_session_by_restaurant)
    completed_places = len(completed_ids)
    failed_places = len(failed_ids)
    pending_places = len(pending_ids)
    review_rows_written = sum(len(rows) for rows in reviews_by_restaurant.values())
    mean_duration = (
        round(sum(duration_seconds) / len(duration_seconds), 3) if duration_seconds else ""
    )
    median_duration = compute_median(duration_seconds)
    failure_rate = (
        round(failed_places / target_places, 4) if target_places else ""
    )
    completeness_ratio = (
        round(collected_review_count_sum_known_places / expected_review_count_sum, 4)
        if expected_review_count_sum
        else ""
    )

    return {
        "status": build_rpc_batch_status(
            completed_places=completed_places,
            failed_places=failed_places,
            pending_places=pending_places,
        ),
        "matches_path": str(matches_path) if matches_path else "",
        "output_path": str(output_path) if output_path else "",
        "session_log_path": str(session_log_path) if session_log_path else "",
        "started_at": started_at,
        "updated_at": updated_at,
        "target_places": target_places,
        "attempted_places": attempted_places,
        "completed_places": completed_places,
        "failed_places": failed_places,
        "pending_places": pending_places,
        "skipped_non_canonical": skipped_non_canonical,
        "skipped_completed_places": skipped_completed_places,
        "used_search_navigation_places": used_search_navigation_places,
        "review_rows_written": review_rows_written,
        "review_rows_with_exact_published_at": exact_published_at,
        "review_rows_with_exact_edited_at": exact_edited_at,
        "completed_places_with_known_review_count": completed_places_with_known_review_count,
        "expected_review_count_sum": expected_review_count_sum,
        "collected_review_count_sum_known_places": collected_review_count_sum_known_places,
        "review_completeness_ratio": completeness_ratio,
        "median_duration_seconds": median_duration,
        "mean_duration_seconds": mean_duration,
        "failure_rate": failure_rate,
        "completed_restaurant_ids": "|".join(completed_ids),
        "failed_restaurant_ids": "|".join(failed_ids),
        "pending_restaurant_ids": "|".join(pending_ids),
    }


def write_rpc_batch_status(batch_log_path: Path, summary):
    write_csv(batch_log_path, RPC_BATCH_HEADERS, [summary])


async def handle_consent_dialog(page):
    await page.wait_for_timeout(random.randint(1100, 1900))

    button_names = [
        "Afvis alle",
        "Acceptér alle",
        "Accepter alle",
        "Reject all",
        "Accept all",
    ]
    for name in button_names:
        try:
            button = page.get_by_role("button", name=name).first
            if await button.count():
                await button.click()
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                await page.wait_for_timeout(random.randint(800, 1400))
                return
        except Exception:
            continue

    selectors = [
        'button:has-text("Afvis alle")',
        'button:has-text("Acceptér alle")',
        'button:has-text("Accepter alle")',
        'button:has-text("Reject all")',
        'button:has-text("Accept all")',
        'form[action*="consent"] button',
    ]
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if await button.count():
                await button.click()
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                await page.wait_for_timeout(random.randint(800, 1400))
                return
        except Exception:
            continue


async def detect_google_block_or_consent(page):
    try:
        text = normalize_text((await page.locator("body").inner_text(timeout=5000))[:4000]).lower()
    except Exception:
        return ""
    block_markers = [
        "unusual traffic",
        "our systems have detected",
        "not a robot",
        "captcha",
        "detected unusual traffic",
        "usædvanlig trafik",
    ]
    if any(marker in text for marker in block_markers):
        return "possible_google_block"
    consent_markers = [
        "before you continue to google",
        "før du fortsætter til google",
        "accept all",
        "afvis alle",
    ]
    if any(marker in text for marker in consent_markers):
        return "consent_not_cleared"
    return ""


async def open_reviews_tab(page):
    await page.wait_for_timeout(random.randint(1100, 1900))
    locator_candidates = [
        page.locator('[role="tab"]', has_text=re.compile("Anmeldelser|Reviews", re.I)).first,
        page.locator('button', has_text=re.compile("Anmeldelser|Reviews", re.I)).first,
    ]
    tab_locator = None
    for locator in locator_candidates:
        try:
            if await locator.count():
                tab_locator = locator
                break
        except Exception:
            continue
    if tab_locator is None:
        return False
    await tab_locator.click()
    await page.wait_for_timeout(random.randint(1100, 1900))
    await page.wait_for_selector("div.jftiEf", timeout=30000)
    return True


async def extract_place_metadata_from_page(page):
    try:
        result = await page.evaluate(PLACE_METADATA_EXTRACTOR_JS)
        return (
            normalize_text(result.get("price_level", "")),
            normalize_text(result.get("price_median_dkk", "")),
            normalize_text(result.get("categories", "")),
        )
    except Exception:
        return ("", "", "")


def update_matches_place_metadata(matches_path: Path, metadata_by_id: dict):
    if not metadata_by_id:
        return
    rows = read_csv(matches_path)
    changed = False
    updated_rows = []
    for row in rows:
        restaurant_id = normalize_text(row.get("restaurant_id", ""))
        meta = metadata_by_id.get(restaurant_id)
        if not meta:
            updated_rows.append(row)
            continue
        price_level, price_median_dkk, categories = meta
        row = dict(row)
        if price_level and not normalize_text(row.get("matched_price_level", "")):
            row["matched_price_level"] = price_level
            changed = True
        if price_median_dkk and not normalize_text(row.get("matched_price_median_dkk", "")):
            row["matched_price_median_dkk"] = price_median_dkk
            changed = True
        if categories and not normalize_text(row.get("matched_categories", "")):
            row["matched_categories"] = categories
            changed = True
        updated_rows.append(row)
    if changed:
        write_csv(matches_path, MATCHES_HEADERS, updated_rows)


async def navigate_to_reviews_panel(page, place_row, sort_key: str):
    navigation_attempts = [
        ("canonical", normalize_text(place_row.get("google_maps_url", ""))),
        ("search", build_search_navigation_url(place_row)),
    ]

    for navigation_kind, target_url in navigation_attempts:
        if not target_url:
            continue
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            await handle_consent_dialog(page)
            block_status = await detect_google_block_or_consent(page)
            if block_status:
                return {
                    "opened": False,
                    "used_search_navigation": navigation_kind == "search",
                    "navigation_kind": navigation_kind,
                    "target_url": target_url,
                    "error": block_status,
                    "price_level": "",
                    "price_median_dkk": "",
                    "categories": "",
                }
            price_level, price_median_dkk, categories = await extract_place_metadata_from_page(page)
            if not await open_reviews_tab(page):
                continue
            if not price_level or not price_median_dkk or not categories:
                fallback_price_level, fallback_price_median_dkk, fallback_categories = await extract_place_metadata_from_page(page)
                price_level = price_level or fallback_price_level
                price_median_dkk = price_median_dkk or fallback_price_median_dkk
                categories = categories or fallback_categories
            await set_review_sort(page, sort_key)
            return {
                "opened": True,
                "used_search_navigation": navigation_kind == "search",
                "navigation_kind": navigation_kind,
                "target_url": target_url,
                "error": "",
                "price_level": price_level,
                "price_median_dkk": price_median_dkk,
                "categories": categories,
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue

    return {
        "opened": False,
        "used_search_navigation": False,
        "navigation_kind": "",
        "target_url": "",
        "error": locals().get("last_error", "Could not open reviews tab."),
        "price_level": "",
        "price_median_dkk": "",
        "categories": "",
    }


async def set_review_sort(page, sort_key: str):
    labels = REVIEW_SORT_LABELS.get(sort_key)
    if not labels:
        return

    button_patterns = labels + [item for values in REVIEW_SORT_LABELS.values() for item in values]
    sort_button = None
    for label in button_patterns:
        locator = page.locator("button", has_text=label).first
        if await locator.count():
            sort_button = locator
            break
    if sort_button is None:
        return

    await sort_button.click()
    await page.wait_for_timeout(random.randint(350, 700))

    for label in labels:
        locator = page.locator('[role="menuitemradio"]', has_text=label).first
        if await locator.count():
            await locator.click()
            await page.wait_for_timeout(random.randint(900, 1600))
            return


async def expand_visible_review_cards(page):
    await page.evaluate(
        """() => {
            const labels = new Set(['Mere', 'More']);
            for (const button of document.querySelectorAll('button.w8nwRe, button')) {
                const text = (button.innerText || '').trim();
                if (labels.has(text)) {
                    button.click();
                }
            }
        }"""
    )
    await page.wait_for_timeout(random.randint(280, 560))


async def get_review_panel_state(page):
    return await page.evaluate(
        """() => {
            const firstCard = document.querySelector('div.jftiEf');
            const container = firstCard?.parentElement?.parentElement
                || document.querySelector('div.m6QErb.DxyBCb.kA9KIf.dS8AEf.XiKgde');
            if (!container) {
                return { found: false, scrollTop: 0, scrollHeight: 0, clientHeight: 0, visibleCount: 0 };
            }
            return {
                found: true,
                scrollTop: container.scrollTop,
                scrollHeight: container.scrollHeight,
                clientHeight: container.clientHeight,
                visibleCount: document.querySelectorAll('div.jftiEf').length,
            };
        }"""
    )


async def scroll_reviews_panel(page):
    return await page.evaluate(
        """() => {
            const firstCard = document.querySelector('div.jftiEf');
            const container = firstCard?.parentElement?.parentElement
                || document.querySelector('div.m6QErb.DxyBCb.kA9KIf.dS8AEf.XiKgde');
            if (!container) {
                return { found: false, scrollTop: 0, scrollHeight: 0, clientHeight: 0, moved: false };
            }
            const before = container.scrollTop;
            container.scrollTop = container.scrollHeight;
            return {
                found: true,
                scrollTop: container.scrollTop,
                scrollHeight: container.scrollHeight,
                clientHeight: container.clientHeight,
                moved: container.scrollTop !== before,
            };
        }"""
    )


async def wait_for_review_panel_growth(page, previous_scroll_height: int, previous_visible_count: int, timeout_ms: int = 4000):
    elapsed_ms = 0
    while elapsed_ms < timeout_ms:
        await page.wait_for_timeout(250)
        elapsed_ms += 250
        state = await get_review_panel_state(page)
        if not state.get("found"):
            return state
        if (
            state.get("scrollHeight", 0) > previous_scroll_height
            or state.get("visibleCount", 0) > previous_visible_count
        ):
            return state
    return await get_review_panel_state(page)


def normalize_local_review_record(place_row, raw_record, sort_key):
    restaurant_id = place_row["restaurant_id"]
    scraped_at = datetime.now(timezone.utc)
    review_id = normalize_text(raw_record.get("review_id", ""))
    if not review_id:
        review_id = make_fallback_review_id(restaurant_id, raw_record)

    reviewer_review_count, reviewer_is_local_guide = parse_reviewer_meta(
        raw_record.get("reviewer_meta", "")
    )
    rating = parse_rating_label(raw_record.get("rating_label", ""))
    published_relative = normalize_text(raw_record.get("published_text", ""))
    published_estimated_date, published_estimated_days_ago = parse_relative_time_text(
        published_relative,
        scraped_at,
    )

    return {
        "restaurant_id": restaurant_id,
        "provider": RPC_PROVIDER,
        "google_place_id": place_row.get("google_place_id", ""),
        "google_fid": place_row.get("google_fid", ""),
        "google_maps_url": place_row.get("google_maps_url", ""),
        "review_id": review_id,
        "review_url": normalize_text(raw_record.get("review_url", "")),
        "reviewer_id": normalize_text(raw_record.get("reviewer_id", "")),
        "reviewer_name": normalize_text(raw_record.get("reviewer_name", "")),
        "reviewer_profile_url": normalize_text(raw_record.get("reviewer_profile_url", "")),
        "reviewer_review_count": reviewer_review_count,
        "reviewer_is_local_guide": str(reviewer_is_local_guide),
        "rating": rating,
        "review_text": normalize_text(raw_record.get("review_text", "")),
        "review_language": normalize_text(raw_record.get("language", "")),
        "published_at": published_estimated_date or published_relative,
        "published_at_relative": published_relative,
        "published_at_estimated_date": published_estimated_date,
        "published_at_estimated_days_ago": published_estimated_days_ago,
        "edited_at": normalize_text(raw_record.get("edited_at", "")),
        "likes_count": normalize_text(raw_record.get("likes_text", "")),
        "owner_response_text": normalize_text(raw_record.get("owner_response_text", "")),
        "owner_response_at": normalize_text(raw_record.get("owner_response_at", "")),
        "review_sort_order": sort_key,
        "scraped_at": scraped_at.isoformat(),
    }


def enrich_dom_review_with_network(dom_review, network_lookup):
    key = (
        normalize_text(dom_review.get("reviewer_name", "")).lower(),
        normalize_text(dom_review.get("published_at_relative", "")).lower(),
        normalize_text(dom_review.get("review_text", ""))[:120].lower(),
    )
    matches = network_lookup.get(key) or []
    if not matches:
        return dom_review

    network_review = matches.pop(0)
    dom_review["review_id"] = network_review.get("network_review_id") or dom_review["review_id"]
    dom_review["review_url"] = network_review.get("review_url") or dom_review["review_url"]
    dom_review["reviewer_id"] = network_review.get("reviewer_id") or dom_review["reviewer_id"]
    dom_review["reviewer_profile_url"] = (
        network_review.get("reviewer_profile_url") or dom_review["reviewer_profile_url"]
    )
    dom_review["reviewer_review_count"] = (
        network_review.get("reviewer_review_count") or dom_review["reviewer_review_count"]
    )
    dom_review["reviewer_is_local_guide"] = (
        network_review.get("reviewer_is_local_guide") or dom_review["reviewer_is_local_guide"]
    )
    dom_review["rating"] = network_review.get("rating") or dom_review["rating"]
    dom_review["review_text"] = network_review.get("review_text") or dom_review["review_text"]
    dom_review["review_language"] = (
        network_review.get("review_language") or dom_review["review_language"]
    )
    dom_review["published_at"] = network_review.get("published_at") or dom_review["published_at"]
    dom_review["published_at_relative"] = (
        network_review.get("published_at_relative") or dom_review["published_at_relative"]
    )
    if network_review.get("published_at"):
        dom_review["published_at_estimated_date"] = network_review["published_at"][:10]
        try:
            published_dt = datetime.fromisoformat(network_review["published_at"])
            scraped_dt = datetime.fromisoformat(dom_review["scraped_at"])
            dom_review["published_at_estimated_days_ago"] = str(
                round((scraped_dt - published_dt).total_seconds() / 86400, 3)
            )
        except Exception:
            pass
    dom_review["edited_at"] = network_review.get("edited_at") or dom_review["edited_at"]
    return dom_review


def merge_dom_and_network_review(dom_review, network_review):
    if "T" in normalize_text(network_review.get("published_at", "")) and "T" not in normalize_text(
        dom_review.get("published_at", "")
    ):
        dom_review["published_at"] = normalize_text(network_review.get("published_at", ""))
        dom_review["published_at_estimated_date"] = dom_review["published_at"][:10]
        try:
            published_dt = datetime.fromisoformat(dom_review["published_at"])
            scraped_dt = datetime.fromisoformat(dom_review["scraped_at"])
            dom_review["published_at_estimated_days_ago"] = str(
                round((scraped_dt - published_dt).total_seconds() / 86400, 3)
            )
        except Exception:
            pass

    for field in [
        "review_url",
        "reviewer_id",
        "reviewer_profile_url",
        "reviewer_review_count",
        "reviewer_is_local_guide",
        "review_language",
        "edited_at",
    ]:
        if normalize_text(network_review.get(field, "")) and not normalize_text(
            dom_review.get(field, "")
        ):
            dom_review[field] = normalize_text(network_review[field])
    return dom_review


async def scrape_reviews_for_place(
    page,
    place_row,
    max_reviews: int,
    sort_key: str,
    review_bounds=None,
    max_scroll_attempts: int = 120,
    scroll_idle_limit: int = 4,
    growth_timeout_ms: int = 2000,
):
    network_reviews = []

    async def on_response(response):
        if "maps/rpc/listugcposts" not in response.url:
            return
        try:
            payload_text = await response.text()
            network_reviews.extend(parse_listugcposts_payload(payload_text))
        except Exception:
            return

    page.on("response", on_response)
    navigation = await navigate_to_reviews_panel(page, place_row, sort_key)
    if not navigation["opened"]:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
        return {
            "reviews": [],
            "used_search_navigation": False,
            "place_row": place_row,
            "review_rows_seen": 0,
            "navigation_kind": navigation.get("navigation_kind", ""),
            "stop_reason": navigation.get("error", "navigation_failed"),
            "price_level": "",
            "price_median_dkk": "",
            "categories": "",
        }

    place_row = enrich_place_row_from_browser_url(place_row, page.url)

    seen_reviews = {}
    stalled_loops = 0
    previous_count = 0
    stop_reason = "max_scroll_attempts"
    effective_idle_limit = random.randint(scroll_idle_limit, scroll_idle_limit + 2)

    for _ in range(max_scroll_attempts):
        await expand_visible_review_cards(page)
        extracted = await page.evaluate(REVIEW_EXTRACTOR_JS)
        network_lookup = build_network_review_lookup(network_reviews)
        for raw_record in extracted:
            normalized = normalize_local_review_record(
                place_row,
                raw_record,
                sort_key,
            )
            normalized = enrich_dom_review_with_network(normalized, network_lookup)
            seen_reviews[normalized["review_id"]] = normalized
        network_review_count = len(
            {review.get("network_review_id") for review in network_reviews if review.get("network_review_id")}
        )
        effective_count = max(len(seen_reviews), network_review_count)
        if max_reviews and effective_count >= max_reviews:
            stop_reason = "max_reviews_per_place"
            break
        if sort_key == "newest" and review_bounds:
            current_reviews = list(seen_reviews.values()) + [
                normalize_network_review_record(place_row, network_review, sort_key)
                for network_review in network_reviews
            ]
            oldest_seen = oldest_review_datetime(current_reviews)
            if oldest_seen is not None and oldest_seen <= review_bounds["start"]:
                stop_reason = "smiley_window_start_reached"
                break

        if effective_count == previous_count:
            stalled_loops += 1
        else:
            stalled_loops = 0
        if stalled_loops >= effective_idle_limit:
            stop_reason = "scroll_idle_limit"
            break

        previous_count = effective_count
        panel_state = await get_review_panel_state(page)
        scroll_result = await scroll_reviews_panel(page)
        if not scroll_result.get("found"):
            stop_reason = "reviews_panel_not_found"
            break
        await wait_for_review_panel_growth(
            page,
            previous_scroll_height=panel_state.get("scrollHeight", 0),
            previous_visible_count=panel_state.get("visibleCount", len(extracted)),
            timeout_ms=random.randint(int(growth_timeout_ms * 0.8), int(growth_timeout_ms * 1.2)),
        )
    try:
        page.remove_listener("response", on_response)
    except Exception:
        pass

    unique_network_reviews = []
    seen_network_ids = set()
    for network_review in network_reviews:
        network_id = network_review.get("network_review_id", "")
        if network_id and network_id not in seen_network_ids:
            seen_network_ids.add(network_id)
            unique_network_reviews.append(
                normalize_network_review_record(
                    place_row,
                    network_review,
                    sort_key,
                )
            )

    reviews = {row["review_id"]: row for row in unique_network_reviews}
    for row in seen_reviews.values():
        if row["review_id"] in reviews:
            row = merge_dom_and_network_review(row, reviews[row["review_id"]])
        reviews[row["review_id"]] = row
    reviews = list(reviews.values())
    review_rows_seen = len(reviews)
    reviews = trim_reviews_to_bounds(reviews, review_bounds)
    if max_reviews:
        reviews = reviews[:max_reviews]
    return {
        "reviews": reviews,
        "used_search_navigation": navigation["used_search_navigation"],
        "place_row": place_row,
        "review_rows_seen": review_rows_seen,
        "navigation_kind": navigation.get("navigation_kind", ""),
        "stop_reason": stop_reason,
        "price_level": navigation.get("price_level", ""),
        "price_median_dkk": navigation.get("price_median_dkk", ""),
        "categories": navigation.get("categories", ""),
    }


def scrape_local_reviews(
    matches_path: Path,
    output_path: Path,
    max_reviews_per_place: int,
    sort_key: str,
    limit: int,
    max_new_places: int,
    language: str,
    headless: bool,
    restaurant_ids=None,
    restaurants_path: Path | None = None,
    session_log_path: Path | None = None,
    batch_log_path: Path | None = None,
    resume: bool = True,
    max_scroll_attempts: int = 120,
    scroll_idle_limit: int = 4,
    growth_timeout_ms: int = 2000,
    place_retry_attempts: int = 2,
    place_delay_min_seconds: float = 2.0,
    place_delay_max_seconds: float = 6.0,
    retry_delay_min_seconds: float = 10.0,
    retry_delay_max_seconds: float = 25.0,
):
    ensure_data_directories()
    from playwright.async_api import async_playwright

    existing_output_rows = read_csv(output_path)
    existing_session_rows = read_csv(session_log_path) if session_log_path else []
    completed_restaurant_ids = build_completed_restaurant_ids(existing_session_rows) if resume else set()
    review_bounds_by_restaurant = build_review_bounds_by_restaurant(restaurants_path)
    batch_started_at = datetime.now(timezone.utc).isoformat()

    selection = build_rpc_place_rows(
        matches_path=matches_path,
        restaurant_ids=restaurant_ids,
        limit=limit,
    )
    place_rows = selection["place_rows"]
    skipped_non_canonical = selection["skipped_non_canonical"]

    selected_place_rows = list(place_rows)

    skipped_completed_places = 0
    if completed_restaurant_ids:
        unprocessed_place_rows = []
        for place_row in place_rows:
            restaurant_id = normalize_text(place_row.get("restaurant_id", ""))
            if restaurant_id in completed_restaurant_ids:
                skipped_completed_places += 1
                continue
            unprocessed_place_rows.append(place_row)
        place_rows = unprocessed_place_rows

    deferred_for_next_batch = 0
    if max_new_places and len(place_rows) > max_new_places:
        deferred_for_next_batch = len(place_rows) - max_new_places
        place_rows = place_rows[:max_new_places]

    existing_rows_to_keep = build_existing_review_rows(
        existing_output_rows,
        [row.get("restaurant_id", "") for row in place_rows],
    )
    accumulated_rows = list(existing_rows_to_keep)
    session_rows = list(existing_session_rows)

    def persist_batch_status():
        if not batch_log_path:
            return
        summary = summarize_rpc_collection(
            target_place_rows=selected_place_rows,
            review_rows=accumulated_rows,
            session_rows=session_rows,
            matches_path=matches_path,
            output_path=output_path,
            session_log_path=session_log_path,
            started_at=batch_started_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
            skipped_non_canonical=skipped_non_canonical,
            skipped_completed_places=skipped_completed_places,
        )
        write_rpc_batch_status(batch_log_path, summary)
        return summary

    batch_summary = persist_batch_status()

    if not place_rows:
        if session_log_path and session_rows:
            write_csv(session_log_path, RPC_SESSION_HEADERS, session_rows)
        write_csv(output_path, REVIEWS_HEADERS, accumulated_rows)
        batch_summary = persist_batch_status()
        return {
            "matched_places": len(selected_place_rows),
            "review_rows": len(accumulated_rows),
            "output_path": output_path,
            "failed_places": [],
            "skipped_non_canonical": skipped_non_canonical,
            "skipped_completed_places": skipped_completed_places,
            "deferred_for_next_batch": deferred_for_next_batch,
            "session_log_path": session_log_path,
            "batch_log_path": batch_log_path,
            "batch_summary": batch_summary,
        }

    async def _run():
        async with async_playwright() as playwright:
            browser = await playwright.firefox.launch(headless=headless)
            context = await browser.new_context(
                locale=language,
                timezone_id="Europe/Copenhagen",
                viewport={"width": 1440, "height": 1200},
            )
            await context.add_cookies(
                [
                    {
                        "name": "CONSENT",
                        "value": "YES+cb.20240101-01-p0.en+FX+430",
                        "domain": ".google.com",
                        "path": "/",
                    }
                ]
            )
            failed_places = []
            price_levels_by_id = {}
            total_places = len(place_rows)
            for place_index, place_row in enumerate(place_rows):
                restaurant_id = normalize_text(place_row.get("restaurant_id", ""))
                matched_name = normalize_text(place_row.get("matched_name", ""))
                print(
                    f"[collect-rpc-reviews] {place_index + 1}/{total_places} "
                    f"restaurant_id={restaurant_id} name={matched_name}",
                    flush=True,
                )
                started_at = datetime.now(timezone.utc)
                reviews = []
                used_search_navigation = False
                error = ""
                attempts_used = 0
                resolved_place_row = dict(place_row)
                review_bounds = review_bounds_by_restaurant.get(restaurant_id)
                review_rows_seen = 0
                navigation_kind = ""
                stop_reason = ""

                session_rows[:] = upsert_rpc_session_row(
                    session_rows,
                    {
                        "restaurant_id": restaurant_id,
                        "matched_name": normalize_text(resolved_place_row.get("matched_name", "")),
                        "google_place_id": normalize_text(resolved_place_row.get("google_place_id", "")),
                        "google_maps_url": normalize_text(resolved_place_row.get("google_maps_url", "")),
                        "status": "in_progress",
                        "attempts": "0",
                        "used_search_navigation": "False",
                        "review_rows_written": "0",
                        "review_rows_seen": "0",
                        "navigation_kind": "",
                        "stop_reason": "",
                        "started_at": started_at.isoformat(),
                        "completed_at": "",
                        "duration_seconds": "",
                        "error": "",
                    },
                )
                if session_log_path:
                    write_csv(session_log_path, RPC_SESSION_HEADERS, session_rows)
                persist_batch_status()

                for attempt in range(1, place_retry_attempts + 1):
                    attempts_used = attempt
                    page = await context.new_page()
                    try:
                        result = await scrape_reviews_for_place(
                            page,
                            place_row,
                            max_reviews=max_reviews_per_place,
                            sort_key=sort_key,
                            review_bounds=review_bounds,
                            max_scroll_attempts=max_scroll_attempts,
                            scroll_idle_limit=scroll_idle_limit,
                            growth_timeout_ms=growth_timeout_ms,
                        )
                        reviews = result["reviews"]
                        resolved_place_row = result.get("place_row", resolved_place_row)
                        review_rows_seen = result.get("review_rows_seen", review_rows_seen)
                        navigation_kind = result.get("navigation_kind", navigation_kind)
                        stop_reason = result.get("stop_reason", stop_reason)
                        used_search_navigation = (
                            used_search_navigation or result["used_search_navigation"]
                        )
                        scraped_price_level = result.get("price_level", "")
                        scraped_price_median_dkk = result.get("price_median_dkk", "")
                        scraped_categories = result.get("categories", "")
                        if scraped_price_level or scraped_price_median_dkk or scraped_categories:
                            price_levels_by_id[restaurant_id] = (
                                scraped_price_level,
                                scraped_price_median_dkk,
                                scraped_categories,
                            )
                        if reviews or review_rows_seen:
                            error = ""
                            break
                        error = stop_reason or "No reviews collected."
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                    finally:
                        await page.close()
                    if attempt < place_retry_attempts:
                        await wait_random_seconds(
                            retry_delay_min_seconds,
                            retry_delay_max_seconds,
                        )

                if not reviews and not review_rows_seen:
                    failed_places.append(place_row.get("restaurant_id", ""))
                accumulated_without_place = build_existing_review_rows(
                    accumulated_rows,
                    [restaurant_id],
                )
                deduped_place_rows = list(
                    {
                        (row["restaurant_id"], row["review_id"]): row
                        for row in reviews
                    }.values()
                )
                accumulated_rows[:] = accumulated_without_place + deduped_place_rows
                write_csv(output_path, REVIEWS_HEADERS, accumulated_rows)

                completed_at = datetime.now(timezone.utc)
                session_rows[:] = upsert_rpc_session_row(
                    session_rows,
                    {
                        "restaurant_id": restaurant_id,
                        "matched_name": normalize_text(resolved_place_row.get("matched_name", "")),
                        "google_place_id": normalize_text(resolved_place_row.get("google_place_id", "")),
                        "google_maps_url": normalize_text(resolved_place_row.get("google_maps_url", "")),
                        "status": "completed" if (reviews or review_rows_seen) else "failed",
                        "attempts": str(attempts_used),
                        "used_search_navigation": str(used_search_navigation),
                        "review_rows_written": str(len(deduped_place_rows)),
                        "review_rows_seen": str(review_rows_seen),
                        "navigation_kind": navigation_kind,
                        "stop_reason": stop_reason,
                        "started_at": started_at.isoformat(),
                        "completed_at": completed_at.isoformat(),
                        "duration_seconds": str(
                            round((completed_at - started_at).total_seconds(), 3)
                        ),
                        "error": error,
                    },
                )
                if session_log_path:
                    write_csv(session_log_path, RPC_SESSION_HEADERS, session_rows)
                persist_batch_status()
                print(
                    f"[collect-rpc-reviews] {place_index + 1}/{total_places} "
                    f"done restaurant_id={restaurant_id} "
                    f"status={'completed' if (reviews or review_rows_seen) else 'failed'} "
                    f"written={len(deduped_place_rows)} seen={review_rows_seen} "
                    f"duration_seconds={round((completed_at - started_at).total_seconds(), 3)}",
                    flush=True,
                )
                if place_index < len(place_rows) - 1:
                    await wait_random_seconds(
                        place_delay_min_seconds,
                        place_delay_max_seconds,
                    )
            await context.close()
            await browser.close()
            return failed_places, price_levels_by_id

    failed_places, price_levels_by_id = asyncio.run(_run())
    update_matches_place_metadata(matches_path, price_levels_by_id)
    batch_summary = persist_batch_status()
    return {
        "matched_places": len(selected_place_rows),
        "review_rows": len(accumulated_rows),
        "output_path": output_path,
        "failed_places": failed_places,
        "skipped_non_canonical": skipped_non_canonical,
        "skipped_completed_places": skipped_completed_places,
        "deferred_for_next_batch": deferred_for_next_batch,
        "session_log_path": session_log_path,
        "batch_log_path": batch_log_path,
        "batch_summary": batch_summary,
    }


def collect_rpc_reviews(
    matches_path: Path,
    output_path: Path,
    restaurant_ids=None,
    restaurants_path: Path | None = None,
    limit: int = 0,
    max_new_places: int = 0,
    max_reviews_per_place: int = 0,
    sort_key: str = "newest",
    language: str = "da-DK",
    headless: bool = True,
    session_log_path: Path | None = None,
    batch_log_path: Path | None = None,
    resume: bool = True,
    max_scroll_attempts: int = 120,
    scroll_idle_limit: int = 4,
    growth_timeout_ms: int = 2000,
    place_retry_attempts: int = 2,
    place_delay_min_seconds: float = 2.0,
    place_delay_max_seconds: float = 6.0,
    retry_delay_min_seconds: float = 10.0,
    retry_delay_max_seconds: float = 25.0,
):
    return scrape_local_reviews(
        matches_path=matches_path,
        output_path=output_path,
        max_reviews_per_place=max_reviews_per_place,
        sort_key=sort_key,
        limit=limit,
        max_new_places=max_new_places,
        language=language,
        headless=headless,
        restaurant_ids=restaurant_ids,
        restaurants_path=restaurants_path,
        session_log_path=session_log_path,
        batch_log_path=batch_log_path,
        resume=resume,
        max_scroll_attempts=max_scroll_attempts,
        scroll_idle_limit=scroll_idle_limit,
        growth_timeout_ms=growth_timeout_ms,
        place_retry_attempts=place_retry_attempts,
        place_delay_min_seconds=place_delay_min_seconds,
        place_delay_max_seconds=place_delay_max_seconds,
        retry_delay_min_seconds=retry_delay_min_seconds,
        retry_delay_max_seconds=retry_delay_max_seconds,
    )


def summarize_rpc_batch(
    matches_path: Path,
    reviews_path: Path,
    session_log_path: Path,
    restaurant_ids=None,
    limit: int = 0,
    batch_log_path: Path | None = None,
):
    selection = build_rpc_place_rows(
        matches_path=matches_path,
        restaurant_ids=restaurant_ids,
        limit=limit,
    )
    target_place_rows = selection["place_rows"]
    session_rows = read_csv(session_log_path)
    skipped_completed_places = 0
    completed_restaurant_ids = build_completed_restaurant_ids(session_rows)
    if completed_restaurant_ids:
        skipped_completed_places = sum(
            1
            for row in target_place_rows
            if normalize_text(row.get("restaurant_id", "")) in completed_restaurant_ids
        )

    summary = summarize_rpc_collection(
        target_place_rows=target_place_rows,
        review_rows=read_csv(reviews_path),
        session_rows=session_rows,
        matches_path=matches_path,
        output_path=reviews_path,
        session_log_path=session_log_path,
        started_at="",
        updated_at=datetime.now(timezone.utc).isoformat(),
        skipped_non_canonical=selection["skipped_non_canonical"],
        skipped_completed_places=skipped_completed_places,
    )
    if batch_log_path:
        write_rpc_batch_status(batch_log_path, summary)
    return summary


def build_parser():
    parser = argparse.ArgumentParser(description="Google review workflow utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser(
        "setup", help="Prepare matching and review output files."
    )
    setup_parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT_PATH),
        help="CSV file containing restaurants to prepare for matching and scraping.",
    )
    setup_parser.add_argument(
        "--output-stem",
        default=DEFAULT_OUTPUT_STEM,
        help="Stem used for output filenames, for example 'full_6k'.",
    )

    resolve_parser = subparsers.add_parser(
        "resolve-places",
        help="Automatically resolve Google Maps search URLs into stable place URLs.",
    )
    resolve_parser.add_argument(
        "--input",
        default=str(DEFAULT_MATCH_INPUT_PATH),
        help="CSV file with google_maps_search_url values.",
    )
    resolve_parser.add_argument(
        "--output",
        default=str(DEFAULT_MATCHES_PATH),
        help="CSV file where normalized place matches should be written.",
    )
    resolve_parser.add_argument(
        "--resolution-json",
        default=str(DEFAULT_RESOLUTION_JSON_PATH),
        help="Raw JSON file for the underlying gmaps-scraper resolution results.",
    )
    resolve_parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Concurrent place-resolution workers.",
    )
    resolve_parser.add_argument(
        "--language",
        default="da",
        help="Google Maps language code to use during resolution.",
    )

    rpc_reviews_parser = subparsers.add_parser(
        "collect-rpc-reviews",
        help="Collect review rows directly from the Google Maps review RPC for matched places.",
    )
    rpc_reviews_parser.add_argument(
        "--input",
        default=str(DEFAULT_FILTERED_MATCHES_PATH),
        help="Resolved matches CSV used to select Google Maps place or search URLs.",
    )
    rpc_reviews_parser.add_argument(
        "--output",
        default=str(DEFAULT_RPC_REVIEWS_PATH),
        help="CSV file where normalized RPC review rows should be written.",
    )
    rpc_reviews_parser.add_argument(
        "--restaurants",
        default="",
        help=(
            "Optional restaurant CSV with smiley control dates. When provided with "
            "--sort newest, scraping stops after reaching reviews older than the "
            "earliest smiley window start for each restaurant and stores only "
            "reviews inside the restaurant's smiley date span."
        ),
    )
    rpc_reviews_parser.add_argument(
        "--session-log",
        default=str(DEFAULT_RPC_SESSION_LOG_PATH),
        help="CSV file where per-place collection session rows should be written.",
    )
    rpc_reviews_parser.add_argument(
        "--batch-log",
        default=str(DEFAULT_RPC_BATCH_LOG_PATH),
        help="CSV file where one-row batch status metadata should be updated during the run.",
    )
    rpc_reviews_parser.add_argument(
        "--restaurant-id",
        action="append",
        default=[],
        help="Optional restaurant_id filter. Repeat for multiple places.",
    )
    rpc_reviews_parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help=(
            "Cap the total matched places considered (selection happens BEFORE the resume "
            "filter — use --max-new-places for batched runs)."
        ),
    )
    rpc_reviews_parser.add_argument(
        "--max-new-places",
        type=int,
        default=0,
        help=(
            "Cap NEW (not-yet-completed) places processed this run. Applied AFTER the resume "
            "filter, so repeated invocations advance through the input in fixed-size batches. "
            "Use 0 for no cap."
        ),
    )
    rpc_reviews_parser.add_argument(
        "--max-reviews-per-place",
        type=int,
        default=0,
        help="Maximum number of review rows to keep per place. Use 0 for no limit.",
    )
    rpc_reviews_parser.add_argument(
        "--sort",
        choices=sorted(REVIEW_SORT_LABELS),
        default="newest",
        help="Review ordering to request before collecting network review responses.",
    )
    rpc_reviews_parser.add_argument(
        "--language",
        default="da-DK",
        help="Browser locale for Google Maps pages.",
    )
    rpc_reviews_parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the Playwright browser window while collecting reviews.",
    )
    rpc_reviews_parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Reprocess targeted places even if they were already marked completed in the session log.",
    )
    rpc_reviews_parser.add_argument(
        "--max-scroll-attempts",
        type=int,
        default=120,
        help="Maximum scroll iterations per place before stopping.",
    )
    rpc_reviews_parser.add_argument(
        "--scroll-idle-limit",
        type=int,
        default=6,
        help="Consecutive loops with no growth before stopping for a place.",
    )
    rpc_reviews_parser.add_argument(
        "--growth-timeout-ms",
        type=int,
        default=4000,
        help="How long to wait for additional review cards after each bottom scroll.",
    )
    rpc_reviews_parser.add_argument(
        "--place-retry-attempts",
        type=int,
        default=2,
        help="How many times to retry a place before marking it failed.",
    )
    rpc_reviews_parser.add_argument(
        "--place-delay-min-seconds",
        type=float,
        default=4.0,
        help="Minimum polite delay between places.",
    )
    rpc_reviews_parser.add_argument(
        "--place-delay-max-seconds",
        type=float,
        default=10.0,
        help="Maximum polite delay between places.",
    )
    rpc_reviews_parser.add_argument(
        "--retry-delay-min-seconds",
        type=float,
        default=10.0,
        help="Minimum delay before retrying a failed place attempt.",
    )
    rpc_reviews_parser.add_argument(
        "--retry-delay-max-seconds",
        type=float,
        default=25.0,
        help="Maximum delay before retrying a failed place attempt.",
    )

    summarize_rpc_parser = subparsers.add_parser(
        "summarize-rpc-batch",
        help="Summarize an RPC collection batch from matches, reviews, and session CSVs.",
    )
    summarize_rpc_parser.add_argument(
        "--input",
        default=str(DEFAULT_FILTERED_MATCHES_PATH),
        help="Resolved matches CSV used to define the target matched places.",
    )
    summarize_rpc_parser.add_argument(
        "--reviews",
        default=str(DEFAULT_RPC_REVIEWS_PATH),
        help="Normalized RPC reviews CSV to inspect.",
    )
    summarize_rpc_parser.add_argument(
        "--session-log",
        default=str(DEFAULT_RPC_SESSION_LOG_PATH),
        help="Per-place RPC session CSV to inspect.",
    )
    summarize_rpc_parser.add_argument(
        "--output",
        default=str(DEFAULT_RPC_BATCH_LOG_PATH),
        help="Optional CSV file where the one-row summary should be written.",
    )
    summarize_rpc_parser.add_argument(
        "--restaurant-id",
        action="append",
        default=[],
        help="Optional restaurant_id filter. Repeat for multiple places.",
    )
    summarize_rpc_parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional limit on how many matched places to summarize.",
    )
    filter_parser = subparsers.add_parser(
        "filter-matches",
        help="Keep only likely food-service matches before review scraping.",
    )
    filter_parser.add_argument(
        "--input",
        default=str(DEFAULT_MATCHES_PATH),
        help="Resolved matches CSV to filter.",
    )
    filter_parser.add_argument(
        "--output",
        default=str(DEFAULT_FILTERED_MATCHES_PATH),
        help="Filtered matches CSV to write.",
    )

    return parser


def main():
    args = build_parser().parse_args()
    if args.command == "setup":
        summary = setup_pipeline(Path(args.input).resolve(), args.output_stem)
        print(f"Prepared match input rows: {summary['match_input_rows']}")
        print(f"Match input CSV: {summary['match_input_path']}")
        print(f"Matches schema CSV: {summary['matches_path']}")
        return

    if args.command == "resolve-places":
        summary = resolve_places(
            match_input_path=Path(args.input).resolve(),
            output_path=Path(args.output).resolve(),
            resolution_json_path=Path(args.resolution_json).resolve(),
            concurrency=args.concurrency,
            language=args.language,
        )
        print(f"Place-resolution input rows: {summary['input_rows']}")
        print(f"Automatically matched rows: {summary['matched_rows']}")
        print(f"Matches CSV: {summary['output_path']}")
        print(f"Raw resolution JSON: {summary['resolution_json_path']}")
        return

    if args.command == "collect-rpc-reviews":
        summary = collect_rpc_reviews(
            matches_path=Path(args.input).resolve(),
            output_path=Path(args.output).resolve(),
            restaurant_ids=args.restaurant_id,
            restaurants_path=Path(args.restaurants).resolve() if args.restaurants else None,
            limit=args.limit,
            max_new_places=args.max_new_places,
            max_reviews_per_place=args.max_reviews_per_place,
            sort_key=args.sort,
            language=args.language,
            headless=not args.headed,
            session_log_path=Path(args.session_log).resolve(),
            batch_log_path=Path(args.batch_log).resolve(),
            resume=not args.no_resume,
            max_scroll_attempts=args.max_scroll_attempts,
            scroll_idle_limit=args.scroll_idle_limit,
            growth_timeout_ms=args.growth_timeout_ms,
            place_retry_attempts=args.place_retry_attempts,
            place_delay_min_seconds=args.place_delay_min_seconds,
            place_delay_max_seconds=args.place_delay_max_seconds,
            retry_delay_min_seconds=args.retry_delay_min_seconds,
            retry_delay_max_seconds=args.retry_delay_max_seconds,
        )
        print(f"Matched places targeted: {summary['matched_places']}")
        print(f"Normalized review rows written: {summary['review_rows']}")
        print(f"Normalized review CSV: {summary['output_path']}")
        print(f"Session log CSV: {summary['session_log_path']}")
        print(f"Batch status CSV: {summary['batch_log_path']}")
        print(
            "Matched rows skipped because they did not have usable Google Maps URLs: "
            f"{summary['skipped_non_canonical']}"
        )
        print(
            "Matched rows skipped because they were already completed in the session log: "
            f"{summary['skipped_completed_places']}"
        )
        deferred = summary.get("deferred_for_next_batch", 0)
        if deferred:
            print(
                "Places deferred to the next batch (capped by --max-new-places): "
                f"{deferred}. Re-run the same command to process the next batch."
            )
        if summary["batch_summary"]:
            print(f"Batch status: {summary['batch_summary']['status']}")
            print(
                "Batch completion: "
                f"{summary['batch_summary']['completed_places']}/{summary['batch_summary']['target_places']}"
            )
            print(
                "Batch failure rate: "
                f"{summary['batch_summary']['failure_rate']}"
            )
            print(
                "Median place runtime seconds: "
                f"{summary['batch_summary']['median_duration_seconds']}"
            )
            print(
                "Review completeness ratio on places with known matched_review_count: "
                f"{summary['batch_summary']['review_completeness_ratio']}"
            )
        if summary["failed_places"]:
            print(f"Places where direct RPC collection failed: {','.join(summary['failed_places'])}")
        return

    if args.command == "summarize-rpc-batch":
        summary = summarize_rpc_batch(
            matches_path=Path(args.input).resolve(),
            reviews_path=Path(args.reviews).resolve(),
            session_log_path=Path(args.session_log).resolve(),
            restaurant_ids=args.restaurant_id,
            limit=args.limit,
            batch_log_path=Path(args.output).resolve() if args.output else None,
        )
        print(f"Batch status: {summary['status']}")
        print(f"Target places: {summary['target_places']}")
        print(f"Attempted places: {summary['attempted_places']}")
        print(f"Completed places: {summary['completed_places']}")
        print(f"Failed places: {summary['failed_places']}")
        print(f"Pending places: {summary['pending_places']}")
        print(f"Review rows written: {summary['review_rows_written']}")
        print(
            "Rows with exact published_at timestamps: "
            f"{summary['review_rows_with_exact_published_at']}"
        )
        print(
            "Rows with exact edited_at timestamps: "
            f"{summary['review_rows_with_exact_edited_at']}"
        )
        print(f"Failure rate: {summary['failure_rate']}")
        print(f"Median place runtime seconds: {summary['median_duration_seconds']}")
        print(
            "Review completeness ratio on completed places with known matched_review_count: "
            f"{summary['review_completeness_ratio']}"
        )
        if args.output:
            print(f"Batch summary CSV: {Path(args.output).resolve()}")
        return

    if args.command == "filter-matches":
        summary = filter_matches_for_food_service(
            input_path=Path(args.input).resolve(),
            output_path=Path(args.output).resolve(),
        )
        print(f"Resolved match rows read: {summary['input_rows']}")
        print(f"Food-service rows kept: {summary['filtered_rows']}")
        print(f"Filtered matches CSV: {summary['output_path']}")
        return
