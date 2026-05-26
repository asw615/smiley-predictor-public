= Data Wrangling

The Smileyordningen register and Google Maps were not built for our task @foedevarestyrelsen_smileystatistik. The register lists everything from restaurants to grocers, bakers and canteens, with no single column that cleanly separates the types. Google sometimes returns the wrong place when a name is shared across many locations, as with chains and franchises, and exhaustive scraping of all restaurants is beyond our quota.

== Data manipulation <sec-data-manipulation>

=== Restaurant filtering

We restrict the public snapshot from Smileyordningen @foedevarestyrelsen_smileydata to standard restaurants (excluding, among others, bars, grocery, bakers, wholesale and transport companies), leaving 20,467 establishments. Retained restaurants must have at least three of the four inspection slots filled, together with a non-empty street address and postcode. The inspection requirement ensures that each restaurant has recent inspection records, and the address fields are necessary to identify the place with Google Maps.

=== Sampling strategy

The sample is constructed by case-control sampling on the most recent inspection outcome. Every restaurant whose most recent smiley differs from 1 is included (405 in total, exhausting the positive class), and the remaining 5,595 slots are filled by uniform random selection from the eligible snapshot without geographic restriction. 

The 6,000-restaurant target was set by the scraping budget. At the observed per-place rate (around 16 seconds at the median, see @sec-data-acquisition) and the roughly 50% drop-out to the food-service filter, 6,000 candidates end up being reduced to approximately 3,000 scraped places and a full day of scraping, which was the operational ceiling we set ourselves. 

=== Inspection period

We keep only inspections dated 1 January 2022 or later, the effective date of the smiley-scheme reform, and exclude any remaining grade-3 inspections. The cutoff also removes the 2020 and 2021 inspections that occurred under pandemic closures, which had an atypical inspection cadence @foedevarestyrelsen_smileystatistik.

== Data acquisition <sec-data-acquisition>

=== Place resolution and food-service filter

We match each of the 6,000 sampled restaurants to a Google Maps place by querying the platform with name and address. Google can return a confident match for the wrong entity when the name is generic or shared with a nearby business, so before any reviews are scraped, we apply a Danish food-service keyword filter to the candidate's normalised category and name. A candidate is kept only if its text contains at least one include keyword (restaurant, pizzeria, café, and similar). The full lists are in @sec-keyword-filter. Of the 6,000 sampled restaurants, 3,097 (51.6%) pass this filter, with the remainder either failing to match to a Google place or resolving to a non-food-service entity. The risk of running a hand-curated keyword list is that we may also drop some genuine restaurants whose Google category is outside of our vocabulary. We also lack labelled ground truth for the full sample, so we cannot quantify either false exclusions or incorrect Google Maps matches.

=== Review scraping

We pull reviews from each retained place by calling the same internal Remote Procedure Call (RPC) endpoint that the Google Maps front-end uses when a user scrolls the review pane. Calls are issued using headless Chromium under Playwright browser @playwright2026, which manages the session cookies and consent state Google sends to the request. The RPC returns reviews ordered by the most recent review. Of the 3,097 retained places, 100 returned no Google reviews at all, and a further 40 is dropped as they are outside any windows (described in @sec-data-manipulation), leaving 2,957 places each containing at least one inspection row.

=== Language handling

Google auto-translates non-Danish reviews into the browser's display language, so the reviews we scraped are in Danish even when originally written in another language. We use this machine-translated text as-is in the downstream features rather than re-pulling originals, which are not available through the same channels on Google.

=== Review windows

To predict upcoming inspections, we build a review window for each inspection containing only reviews that were available before the visit. The window collects Google reviews published after the previous inspection (or 1 January 2022, whichever is later) and on or before the inspection date itself.

The snapshot from Smileyordningen keeps only the restaurant's four most-recent inspections, so a restaurant inspected eight times since 2022 still contributes at most four rows. The oldest of the retained slots is dropped from the prediction targets, since no earlier inspection exists in the snapshot to anchor the start of its review window.

Window length follows the inspection cadence. The mean window spans 319 days, with a median of 245 days. Restaurants placed on a tight follow-up schedule have shorter windows of recent reviews, while restaurants on the normal routine cadence receive longer windows reaching back to the previous inspection @foedevarestyrelsen_kontrolfrekvens.

== Final dataset

The final dataset contains 8,086 inspections across 2,957 restaurants and the share of inspections with a non-happy outcome is 14.9%.

Of the those rows, 34.1% have no in-window reviews. The remaining 5,315 non-empty windows carry a median of 12 reviews (mean 32, 90th percentile 80), with 94.4% including at least one review with text content and 5.6% consisting of star-only ratings.
