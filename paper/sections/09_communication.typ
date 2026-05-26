= Communication

#text(size: 14pt, weight: "bold")[Can Google Maps reviews help target health inspections?]

#v(0.1em)

#text(size: 11pt, style: "italic")[A research brief for Fødevarestyrelsen, May 2026]

#v(0.5em)

#block(
  fill: rgb("#EFF4FA"),
  stroke: (left: 3pt + rgb("#2C5282")),
  inset: (x: 14pt, y: 10pt),
  width: 100%,
)[
*Key findings* 
- We tested whether Google Maps reviews of Danish restaurants give early warning that the next smiley inspection will not return a happy face. 
- Simple summaries of the reviews gave a modest lift in ranking restaurants by risk. A second step that read the review text for hygiene mentions added no further information.
- The model is not suitable for inspection planning based on this work. We outline what would change that.
]

*Background.* Around 3% of routine smiley inspections return a non-happy outcome. We asked whether the reviews that customers leave on Google Maps could give early warning that the next inspection will not return a happy face, as one possible input to risk-based scheduling rather than a replacement for the current routine.

*What we did.* We linked two public sources, Fødevarestyrelsen's smiley register and Google Maps reviews gathered from the public pages of around 3,000 Danish restaurants. For every pair of consecutive inspections, we summarised the reviews written in between (count, mean star rating, share of one- and two-star reviews) and asked a statistical model to predict whether the next inspection would return a non-happy outcome. A second step used a large language model to check each lower-rated review for mentions of any of six hygiene problems, including pests, food-safety issues, and visible dirt. We then tested whether those mentions improved the predictions.

// Palette
#let c-input-fill = rgb("#EAF2FB")
#let c-input-stroke = rgb("#2C5282")
#let c-step-fill = rgb("#F7F8FB")
#let c-step-stroke = rgb("#475569")
#let c-output-fill = rgb("#E8F3E8")
#let c-output-stroke = rgb("#2F7D32")
#let c-arrow = rgb("#475569")

#let arrow-glyph(height: 12pt) = box(
  width: 8pt,
  height: height,
)[
  #place(top + left, dx: 4pt, line(
    start: (0pt, 0pt),
    end: (0pt, height - 5pt),
    stroke: 1.5pt + c-arrow,
  ))
  #place(top + left, dy: height - 5pt, polygon(
    fill: c-arrow,
    (0pt, 0pt),
    (8pt, 0pt),
    (4pt, 5pt),
  ))
]

#let wf-arrow = block(
  above: 0.35em,
  below: 0.35em,
  width: 100%,
  align(center, arrow-glyph()),
)

#let wf-input(title, subtitle) = block(
  fill: c-input-fill,
  stroke: 0.8pt + c-input-stroke,
  inset: (x: 10pt, y: 6pt),
  radius: 4pt,
  width: 100%,
  align(center)[
    *#title* \
    #text(size: 9pt)[#subtitle]
  ],
)

#let wf-step(body) = block(
  fill: c-step-fill,
  stroke: 0.6pt + c-step-stroke,
  inset: (x: 10pt, y: 6pt),
  radius: 4pt,
  width: 100%,
  align(center, body),
)

#let wf-output(body) = block(
  fill: c-output-fill,
  stroke: 0.8pt + c-output-stroke,
  inset: (x: 10pt, y: 6pt),
  radius: 4pt,
  width: 100%,
  align(center, body),
)

#let wf-arrow = block(
  above: 0.5em,
  below: 0.5em,
  width: 100%,
  align(center, arrow-glyph()),
)

#let wf-converge(height: 24pt) = block(
  above: 0.35em,
  below: 0.25em,
  width: 100%,
  box(width: 100%, height: height)[
    #place(top + left, curve(
      stroke: 1.5pt + c-arrow,
      fill: none,
      curve.move((25%, 0pt)),
      curve.cubic(
        (25%, height * 0.5),
        (50%, height * 0.5),
        (50%, height - 5pt),
      ),
    ))
    #place(top + left, curve(
      stroke: 1.5pt + c-arrow,
      fill: none,
      curve.move((75%, 0pt)),
      curve.cubic(
        (75%, height * 0.5),
        (50%, height * 0.5),
        (50%, height - 5pt),
      ),
    ))
    #place(bottom + center, polygon(
      fill: c-arrow,
      (0pt, 0pt),
      (8pt, 0pt),
      (4pt, 5pt),
    ))
  ]
)

#figure(
  block(width: 96%, [
    #grid(
      columns: (1fr, 1fr),
      column-gutter: 1em,
      wf-input(
        "Smiley register",
        "Fødevarestyrelsen's public inspection outcomes",
      ),
      wf-input(
        "Google Maps reviews",
        "public restaurant reviews",
      ),
    )
    #wf-converge()
    #wf-step[
      For each inspection, gather the reviews written since the previous one
    ]
    #wf-arrow
    #wf-step[
      Summarise each inspection's reviews \
      #text(size: 9pt)[(count, mean star rating, share of low-star reviews)]
    ]
    #wf-arrow
    #wf-step[
      Predict whether the next smiley will be non-happy
    ]
    #wf-arrow
    #wf-output[
      *Judge the predictions on inspections the model never saw*
    ]
  ]),
  caption: [How we tested whether Google reviews predict the next smiley grade. Two public sources feed a single per-inspection pipeline, evaluated on inspections held out from training.],
  kind: image,
) <fig-workflow>

*What we found.* On a sample of 8,067 inspections, the simple review summaries did help the model put restaurants likely to fail their next inspection near the top of the list. Among the restaurants the model flagged as highest-risk, around one in five returned a non-happy grade, compared with around one in seven if those restaurants had been picked at random. The text-reading step did not improve on the simple summaries. Of twelve targeted statistical tests on the hygiene categories, one came back significant, which is within the range that twelve tests would produce by chance.

#grid(
  columns: (1fr, 1fr),
  column-gutter: 1.6em,
  [
  *What this tells you* 
  - Volume, mean rating, and low-rating share contain weak but non-zero information about smiley risk in our data.
  - Reading review text for hygiene categories added nothing on top of those simple summaries under our setup. 
  - The 15% non-happy rate in our sample is well above the 3% population rate, so the numbers here are not what you would see if the model were run on the full register today.
  ],
  [
    *What it does not tell you*
    - That the model is ready to support inspection planning. It is not.
    - That review text is uninformative in general. A different reading scheme might do better.
    - That the lift would hold up on a register that includes the full inspection history per restaurant rather than only the four most recent grades.
  ]
)

*What would change the picture.* A register slice that includes each restaurant's full inspection history, rather than just the four most recent grades, would let us test whether the lift we measured is real or an artefact of that limit. A richer text-reading setup on the same slice would test whether the language of the reviews contains information our scheme missed.