#import "helpers.typ": nv, sm

#nv(level: 1)[Data Wrangling]

The smiley register and Google Maps were not built for our task @foedevarestyrelsen_smileystatistik. The register lists everything from restaurants to grocers, bakers, and canteens, with no single column that cleanly separates the types. Google sometimes returns the wrong place when a name is shared across many locations, as happens with chains and franchises, and exhaustive scraping of all restaurants is beyond our quota.

== Data manipulation <sec-data-manipulation>

#sm(level: 3)[Restaurant filtering]

We restrict the public snapshot from the smiley register @foedevarestyrelsen_smileydata to standard restaurants, excluding (among others) bars, grocers, bakers, and wholesale and transport companies. This leaves 20,467 establishments. Retained restaurants must have at least three of the four inspection slots filled and a non-empty street address and postcode, the latter required for matching against Google Maps.

#nv(level: 3)[Sampling strategy]

We stratify the sample on the most recent inspection outcome. Every restaurant whose most recent smiley differs from 1 (the happy grade) is included, giving 405 non-happy restaurants and exhausting the non-happy most-recent class in the eligible snapshot. The remaining 5,595 slots are filled by uniform random selection from the eligible snapshot, without geographic stratification. Because we kept every non-happy restaurant instead of sampling proportionally, the dataset's non-happy share is higher than the register-level rate.

The 6,000-restaurant target was set by a one-day scraping ceiling. Pilot runs gave a per-place query rate of around 16 seconds at the median, and we anticipated roughly half of the 6,000 candidates dropping out at the food-service filter, leaving a working budget of about 3,000 scraped places.

#sm(level: 3)[Inspection period]

We keep only inspections dated 1 January 2022 or later, the effective date of the smiley-scheme reform. The cutoff also removes 2020 and 2021 inspections that occurred under pandemic closures, which had an atypical inspection cadence @foedevarestyrelsen_smileystatistik.

== Data acquisition <sec-data-acquisition>

#nv(level: 3)[Place resolution and food-service filter]

We match each of the 6,000 sampled restaurants to a Google Maps place by querying the platform with name and address. Google can return a confident match for the wrong entity when the name is generic or shared with a nearby business, so before any reviews are scraped we apply a Danish food-service keyword filter to the candidate's normalised category and name. A candidate is kept only if its text contains at least one include keyword (restaurant, pizzeria, café, and similar). The full lists are in @sec-keyword-filter. Of the 6,000 sampled restaurants, 3,097 (51.6%) pass this filter, with the remainder either failing to match to a Google place or resolving to a non-food-service entity. A hand-curated keyword list also risks dropping genuine restaurants whose Google category falls outside our vocabulary. We do not have labelled ground truth for the full sample, so we cannot quantify either false exclusions or incorrect Google Maps matches.

#sm(level: 3)[Review scraping]

We pull reviews from each retained place by calling the same internal Remote Procedure Call (RPC) endpoint that the Google Maps front-end uses when a user scrolls the review pane. We issue the calls with headless Chromium driven by Playwright @playwright2026, which manages the session cookies and consent state Google attaches to the request. The RPC returns the newest reviews first. Of the 3,097 retained places, 100 return no Google reviews at all, and a further 40 return reviews, but none of those reviews fall inside any of their inspection windows, so they cannot contribute features. The remaining 2,957 places each contribute at least one inspection row to the dataset.

#nv(level: 3)[Language handling]

Google auto-translates non-Danish reviews into the browser's display language, so the reviews we scraped are in Danish even when originally written in another language. We use this machine-translated text as-is in the downstream features rather than re-pulling originals, which are not exposed by the RPC.

#sm(level: 3)[Review windows]

To predict upcoming inspections without leakage, we build a review window for each inspection containing only reviews that were available before the visit. The window collects Google reviews published after the previous inspection (or 1 January 2022, whichever is later) and on or before the inspection date itself.

The snapshot from the smiley register keeps only the restaurant's four most-recent inspections, so a restaurant inspected eight times since 2022 still contributes at most four rows. The oldest of the four retained slots is dropped from the prediction targets, because no earlier inspection exists in the snapshot to anchor the start of its review window. Each restaurant therefore contributes at most three prediction rows.

Window length follows the inspection cadence. The mean window spans 319 days, with a median of 245 days. Restaurants placed on a tight follow-up schedule have shorter windows, and restaurants on the normal routine cadence receive longer windows reaching back to the previous inspection @foedevarestyrelsen_kontrolfrekvens.

#nv[Final dataset]

The final dataset contains 8,086 inspections across 2,957 restaurants, with a non-happy share of 14.9%.

Of those rows, 34.1% have no in-window reviews. The remaining 5,315 non-empty windows carry a median of 12 reviews (mean 32, 90th percentile 80), and 94.4% include at least one review with text content while 5.6% consist of star-only ratings.
