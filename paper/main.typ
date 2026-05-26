#import "wordcount.typ": count-section, total-chars, total-text-chars, total-figs, total-fig-chars, total-pages

#set document(
  title: "Predicting Danish Food-Safety Inspection Outcomes from Google Maps Reviews",
  author: ("Søren Søndergaard Meiner", "Niels Værbak"),
)

// AU-style running header. Logo pulled out into the left margin, authors in the middle,
// course info on the right.
#let au_header = block(width: 100%)[
  #set par(justify: false, leading: 0.55em, spacing: 0.4em)
  #set text(size: 10pt)
  #place(left + horizon, dx: -1.9cm, dy:-0.1cm, image("figures/au_logo.png", width: 1.4cm))
  #grid(
    columns: (1fr, auto),
    align: (left + horizon, right + horizon),
    column-gutter: 0.8em,
    [Søren Søndergaard Meiner \ Niels Værbak],
    [MSc Cognitive Science, Aarhus University \ Data Science, Prediction, and Forecasting - 27/05/2026],
  )
  #v(0.3em)
  #line(length: 100%, stroke: 0.5pt)
]

#set page(
  paper: "a4",
  margin: (x: 2.54cm, top: 3.2cm, bottom: 2.54cm),
  header: au_header,
  footer: context align(center)[#counter(page).display("1")],
  numbering: none,
)

#set text(
  lang: "en",
  region: "GB",
  size: 11pt,
)

// 1.5 line spacing as agreed compromise (APA strictly requires 2.0)
// Larger paragraph spacing for clearer separation between paragraphs in body text.
#set par(
  justify: true,
  leading: 0.85em,
  first-line-indent: 0pt,
  spacing: 1.6em,
)

#set heading(numbering: "1.1")

// Heading spacing matches LaTeX article defaults (converted from ex → em):
//   \section       3.5ex above, 2.3ex below  ≈ 1.75em / 1.15em
//   \subsection    3.25ex above, 1.5ex below ≈ 1.6em  / 0.75em
//   \subsubsection 3.25ex above, 1.5ex below ≈ 1.6em  / 0.75em
// H1 still starts on a fresh page; the "above" gap is therefore redundant.
#show heading.where(level: 1): it => {
  pagebreak(weak: true)
  block(above: 0pt, below: 0.75em, it)
}
#show heading.where(level: 2): it => block(above: 1.6em, below: 0.75em, it)
#show heading.where(level: 3): it => block(above: 1.6em, below: 0.75em, it)

// Author-attribution helpers for sub-headings (exam submission).
// Defined in helpers.typ so the section files (evaluated as their own modules
// via #include) can import them too.
#import "helpers.typ": nv, sm

// Captions (tables and figures): left-aligned, italic, 10pt
#show figure: set figure(gap: 0.8em)
#show figure.caption: it => align(left, text(size: 10pt, style: "italic", it))

// Image figures: wrap image + caption in a single thin-bordered frame
// with a hairline divider between the image and its caption.
#show figure.where(kind: image): it => block(
  stroke: 0.5pt,
  inset: 8pt,
  width: 100%,
  breakable: false,
  {
    align(center, it.body)
    v(0.5em)
    line(length: 100%, stroke: 0.5pt)
    block(above: 0.6em, it.caption)
  }
)

// Gestalt-minimal tables (Journal of Surgical Research, 2025):
// only a hairline below the header row; no verticals, no row shading, no outer box.
// Top and bottom rules are added via a block wrapper around the table.
#set table(
  stroke: (x, y) => (
    bottom: if y == 0 { 0.5pt } else { none },
    top: none,
    left: none,
    right: none,
  ),
  inset: (x: 8pt, y: 7pt),
  fill: none,
)

#show table: it => block(
  stroke: (top: 0.6pt, bottom: 0.6pt),
  inset: 0pt,
  width: 100%,
  it,
)

// Title page, no running header or footer
#set page(header: none, footer: none)
#v(2cm)
#align(center)[
  #text(size: 18pt, weight: "bold")[
    Stars to Smileys: Predicting Danish Food-Safety Inspections from Google Maps Reviews
  ]

  #text(size: 13pt)[(F26.147222U007.A)]
  #v(3em)
  #text(size: 12pt)[Søren Søndergaard Meiner (SM), *202205445\@post.au.dk*]
  #v(1em)
  #text(size: 12pt)[Niels Værbak (NV), *202109225\@post.au.dk*]
  #v(4em)
  #text(size: 12pt)[Total character count: #total-chars (#total-pages pages)]
  #v(1em)
  #text(size: 11pt, style: "italic")[Text: #total-text-chars characters]
  #v(0.4em)
  #text(size: 11pt, style: "italic")[Figures: #total-figs figures, #total-fig-chars characters]
  #v(3em)
  #text(size: 12pt)[Code availability]
  #v(0.4em)
  #text(size: 12pt)[https://github.com/asw615/smiley-predictor-public]
]
#v(1fr)
#align(left)[
  #text(size: 11pt)[*Keywords*: food-safety inspection prediction, Google Maps reviews, large language models, public-health surveillance]
]

#pagebreak()

// Restore the running header for body pages; no footer for abstract and TOC
#set page(
  header: au_header,
  footer: none,
)

// Abstract first, on its own page, unnumbered and excluded from the outline.
#include "sections/00_abstract.typ"

#pagebreak()

// Table of contents — bold level-1 entries, indented sub-entries, no leader dots,
// tightened to always fit on a single page.
#show outline: set text(size: 10pt)
#show outline: set par(leading: 0.5em, spacing: 0.5em)
#set outline.entry(fill: repeat[ ])
#show outline.entry.where(level: 1): it => {
  v(0.8em, weak: true)
  strong(it)
}
#outline(title: [Table of Contents], indent: n => n * 1em, depth: 3)

#pagebreak()

// Numbered sections with page numbers starting at 1 in "page 1/x" format
#set page(
  footer: context align(right)[Page #counter(page).display()/#counter(page).final().first()],
)
#counter(page).update(1)
#count-section("Introduction", include "sections/01_introduction.typ")
#count-section("Research questions", include "sections/02_research_questions.typ")
#count-section("Data", include "sections/03_data.typ")
#count-section("Data wrangling", include "sections/04_data_wrangling.typ")
#count-section("Method", include "sections/05_method.typ")
#count-section("Results", include "sections/06_results.typ")
#count-section("Discussion", include "sections/07_discussion.typ")
#count-section("Conclusions", include "sections/08_conclusions.typ")
#count-section("Communication", include "sections/09_communication.typ")

// Bibliography, APA 7 style. Hanging indent and double spacing are handled by the CSL.
#bibliography("refs.bib", title: "References", style: "apa")

#include "sections/10_appendix.typ"
