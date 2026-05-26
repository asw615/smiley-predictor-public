// Per-section word / character counter.
// Each figure adds 800 characters; figure captions and image alt text are also
// walked and counted on top. Each citation contributes a fixed CHARS/WORDS
// allowance because the rendered citation text is unavailable at walk time.
// Frontpage, abstract, TOC, headers, footers, and references are excluded by
// not wrapping them in `count-section` / `compute-counts`.

#let CHARS-PER-FIGURE = 800
#let CHARS-PER-PAGE = 2400

// Citations don't expose their rendered text at walk time, so we approximate.
// A parenthetical "(Smith, 2020)" is ~14 chars; prose "Smith (2020)" is ~13.
// Adjust if your bibliography style produces noticeably longer references.
#let CHARS-PER-CITATION = 15
#let WORDS-PER-CITATION = 2

#let fmt2(x) = {
  let rounded = calc.round(x, digits: 2)
  let s = str(rounded)
  if "." in s {
    let parts = s.split(".")
    let decimals = parts.at(1)
    if decimals.len() == 1 { parts.at(0) + "." + decimals + "0" }
    else { s }
  } else {
    s + ".00"
  }
}

#let _empty = (text: "", figs: 0, cites: 0)

#let _combine(parts) = (
  text: parts.map(p => p.text).join(""),
  figs: parts.map(p => p.figs).sum(default: 0),
  cites: parts.map(p => p.cites).sum(default: 0),
)

#let _walk(elem) = {
  if type(elem) == str {
    (text: elem, figs: 0, cites: 0)
  } else if type(elem) == content {
    let f = elem.func()
    if f == figure {
      // 1 figure + recurse into caption and body so caption text + image alt
      // text get counted on top of the per-figure 800-char allowance.
      let parts = ()
      if elem.has("caption") and elem.caption != none {
        parts.push(_walk(elem.caption))
      }
      if elem.has("body") {
        parts.push(_walk(elem.body))
      }
      let inner = _combine(parts)
      (text: inner.text, figs: 1 + inner.figs, cites: inner.cites)
    } else if f == cite {
      (text: "", figs: 0, cites: 1)
    } else if f == image {
      let alt = if elem.has("alt") and elem.alt != none { elem.alt } else { "" }
      (text: alt, figs: 0, cites: 0)
    } else if elem.has("text") {
      (text: elem.text, figs: 0, cites: 0)
    } else if elem.has("children") {
      _combine(elem.children.map(_walk))
    } else if elem.has("body") {
      _walk(elem.body)
    } else {
      _empty
    }
  } else {
    _empty
  }
}

#let section-counts = state("section-counts", ())

#let count-section(name, body) = {
  let r = _walk(body)
  let chars = r.text.clusters().len() + r.cites * CHARS-PER-CITATION
  let words = r.text.matches(regex("\S+")).len() + r.cites * WORDS-PER-CITATION
  section-counts.update(arr => arr + ((
    name: name,
    chars: chars,
    words: words,
    figs: r.figs,
    cites: r.cites,
  ),))
  body
}

#let _totals(counts) = {
  let text-chars = counts.map(c => c.chars).sum(default: 0)
  let figs = counts.map(c => c.figs).sum(default: 0)
  let words = counts.map(c => c.words).sum(default: 0)
  let cites = counts.map(c => c.at("cites", default: 0)).sum(default: 0)
  (
    words: words,
    text-chars: text-chars,
    figs: figs,
    cites: cites,
    fig-chars: figs * CHARS-PER-FIGURE,
    total-chars: text-chars + figs * CHARS-PER-FIGURE,
  )
}

#let total-chars = context {
  let t = _totals(section-counts.final())
  [#t.total-chars]
}

#let total-text-chars = context {
  let t = _totals(section-counts.final())
  [#t.text-chars]
}

#let total-words = context {
  let t = _totals(section-counts.final())
  [#t.words]
}

#let total-figs = context {
  let t = _totals(section-counts.final())
  [#t.figs]
}

#let total-fig-chars = context {
  let t = _totals(section-counts.final())
  [#t.fig-chars]
}

#let total-pages = context {
  let t = _totals(section-counts.final())
  [#fmt2(t.total-chars / CHARS-PER-PAGE)]
}

#let compute-counts(name, body) = {
  let r = _walk(body)
  (
    name: name,
    chars: r.text.clusters().len() + r.cites * CHARS-PER-CITATION,
    words: r.text.matches(regex("\S+")).len() + r.cites * WORDS-PER-CITATION,
    figs: r.figs,
    cites: r.cites,
  )
}

#let render-summary(counts) = {
  let cells = ()
  for c in counts {
    let section-total = c.chars + c.figs * CHARS-PER-FIGURE
    let section-pages = section-total / CHARS-PER-PAGE
    cells.push([#c.name])
    cells.push(align(right)[#c.words])
    cells.push(align(right)[#c.chars])
    cells.push(align(right)[#c.at("cites", default: 0)])
    cells.push(align(right)[#c.figs])
    cells.push(align(right)[#section-total])
    cells.push(align(right)[#fmt2(section-pages)])
  }
  let t = _totals(counts)
  table(
    columns: 7,
    align: (left, right, right, right, right, right, right),
    stroke: 0.5pt,
    table.header(
      [*Section*],
      [*Words*],
      [*Text chars*],
      [*Citations*],
      [*Figures*],
      [*Total chars*],
      [*Pages*],
    ),
    ..cells,
    [*Total*],
    align(right)[*#t.words*],
    align(right)[*#t.text-chars*],
    align(right)[*#t.cites*],
    align(right)[*#t.figs*],
    align(right)[*#t.total-chars*],
    align(right)[*#fmt2(t.total-chars / CHARS-PER-PAGE)*],
  )
  v(0.8em)
  [One standard page = #CHARS-PER-PAGE characters. Text chars include #CHARS-PER-CITATION chars per citation; words include #WORDS-PER-CITATION per citation.]
}

