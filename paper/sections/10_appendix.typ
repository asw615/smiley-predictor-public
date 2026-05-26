// Appendix is a regular H1 (numbered in sequence with other sections).
// Sub-sections render (and cross-reference) as "Appendix 1", "Appendix 2", ...
#set heading(
  numbering: (..n) => {
    let parts = n.pos()
    if parts.len() == 1 {
      numbering("1", ..parts)
    } else [Appendix #parts.at(1)]
  },
  supplement: [],
)

= Appendix <sec-appendix>

== Food-service keyword filter <sec-keyword-filter>

The keyword filter described in the Google Maps data step of Data Wrangling matches each candidate place's normalised Google category and name against a keyword list. A candidate is retained only if its text contains at least one include keyword.

*Include keywords:* restaurant, bistro, cafe, café, cafeteria, coffee, kaffe, pizza, pizzeria, burger, sushi, grill, bar, bbq, barbeque, barbecue, take away, takeaway, thai, bager, bakery, isbutik, ice cream, sandwich, sandwichbar, deli, delikatesse, street food, food court, spisestue, spisested, kro, gastropub, pølsebod, polsebod, madbod, kebab, kebabbutik, catering, madselskab, madpartner, frokostordning.

== The prompt for classification using Gemma 4B <prompt-gemma-4>

Each review rated three stars or fewer is sent to a local Gemma 4B model
(`gemma4:e4b` via Ollama) in a single call. A strict JSON Schema
constrains the reply to eight required fields: six per-category
booleans, a seventh `hygiene_signal` which is set to true when any of the six fires, a
`confidence` between 0 and 1, and an `evidence` field carrying a short
Danish quote (empty when no signal fires).

#figure(
  [#[
    #show raw.where(block: true): it => block(
      fill: luma(245),
      stroke: none,
      inset: (x: 14pt, y: 12pt),
      radius: 3pt,
      width: 100%,
      breakable: true,
      text(size: 9pt, it),
    )

    ```
    Klassificer danske Google Maps-anmeldelser for konkrete hygiejne- og fødevaresikkerhedssignaler.

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
    ```
  ]],
  caption: [Danish system prompt for the Gemma 4B hygiene classifier
  (@listing-gemma-prompt). Only the six category booleans are used as
  features in the downstream model.],
  kind: "listing",
  supplement: [Listing],
) <listing-gemma-prompt>

Every call appends fourteen fixed Danish few-shot examples: one positive
per hygiene category where possible and up to four negatives.


== Inspection of skipped 4- and 5-star reviews <sec-high-star-inspection>

To check what we lose by skipping 4- and 5-star reviews, we passed 1,000 of them (217 four-star, 783 five-star) through the same Gemma 4B classifier. Nine triggered at least one category flag, an aggregate rate of 0.9% (@tab-high-star-inspection).

#figure(
  table(
    columns: (auto, auto),
    align: (left, right),
    table.header([Category], [n flagged (of 1,000)]),
    [pest/vermin], [0],
    [foreign object in food], [1],
    [food-safety concern], [3],
    [visible dirt], [2],
    [staff hygiene], [3],
    [illness after eating], [0],
  ),
  caption: [Per-category flag counts from a Gemma 4B inspection of 1,000 four- and five-star reviews. Aggregate flag rate 9/1,000 = 0.9%, treated as the miss rate of the default-negative heuristic.],
) <tab-high-star-inspection>

== Cohen's K for hygiene flags in annotated dataset <cohen-k>

Cohen's K scores for the different hygiene flags from Gemma 4B compared to a 200 hand-labelled dataset. Pest/vermin is undefined as there were no such cases in the dataset. 

#figure(
  table(
    columns: (auto, auto),
    align: (left, right),
    table.header([Category], [Cohen's K]),
    [pest/vermin], [undefined],
    [foreign object in food], [0.85],
    [food-safety concern], [0.46],
    [visible dirt], [0.89],
    [staff hygiene], [0.66],
    [illness after eating], [0.92],
  ),
  caption: [Per-category flag counts from a Gemma 4B inspection of 1,000 four- and five-star reviews. Aggregate flag rate 9/1,000 = 0.9%, treated as the miss rate of the default-negative heuristic.],
) <tab-cohen-k>


