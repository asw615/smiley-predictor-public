// Author-attribution helpers for sub-headings (exam submission).
// Append (NV) or (SM) to the heading text. Use as #nv[Title] for a level-2 heading,
// or #sm(level: 3)[Title] for a level-3 heading.
#let nv(body, level: 2) = heading(level: level)[#body (NV)]
#let sm(body, level: 2) = heading(level: level)[#body (SM)]
#let both(body, level: 2, ..args) = heading(level: level, ..args)[#body (NV, SM)]