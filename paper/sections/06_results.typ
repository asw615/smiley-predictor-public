= Results

== Cross-validation results

@tab-headline-metrics reports per-class PR-AUC (one-vs-rest), the derived not-happy PR-AUC, and precision at the top decile of the not-happy score, with restaurant-clustered bootstrap 95% intervals on the PR-AUC values from 2,000 resamples. @fig-pr-auc-forest plots each smiley class as a separate panel.

#let mc(est, lo, hi) = [#est \ #text(size: 11pt)[(#lo, #hi)]]

#figure(
  text(size:12pt)[#table(
    columns: (auto, auto, auto, auto, auto, auto),
    align: (left, center, center, center, center, center),
    inset: (x: 4pt, y: 5pt),
    stroke: 0.5pt,
    table.header(
      [#strong[Model]],
      [#strong[Happy]],
      [#strong[Neutral]],
      [#strong[Sad]],
      [#strong[Not-happy]],
      [#strong[P\@10]],
    ),
    [Class-frequency baseline],    mc("0.851", "0.841", "0.860"), mc("0.129", "0.120", "0.139"), mc("0.020", "0.016", "0.024"), mc("0.149", "0.140", "0.159"), [0.149],
    [Summary, LR],                 mc("0.877", "0.867", "0.887"), mc("0.158", "0.146", "0.172"), mc("0.027", "0.021", "0.036"), mc("0.182", "0.169", "0.197"), [0.201],
    [Summary, XGB],                mc("0.865", "0.854", "0.875"), mc("0.151", "0.139", "0.165"), mc("0.021", "0.017", "0.027"), mc("0.174", "0.161", "0.190"), [0.185],
    [Summary + LLM flags, LR],     mc("0.875", "0.866", "0.886"), mc("0.162", "0.150", "0.177"), mc("0.027", "0.021", "0.036"), mc("0.183", "0.169", "0.199"), [0.216],
    [Summary + LLM flags, XGB],    mc("0.864", "0.854", "0.874"), mc("0.156", "0.143", "0.172"), mc("0.021", "0.017", "0.029"), mc("0.181", "0.167", "0.198"), [0.203],
  )],
  caption: [Out-of-fold PR-AUC (per class and derived not-happy), and top-decile precision on the 8,067-inspection dataset, with restaurant-clustered bootstrap 95% CIs.],
) <tab-headline-metrics>

Not-happy PR-AUC ranges from 0.149 at the class-frequency baseline to 0.183 for the summary plus LLM flags LR (@tab-headline-metrics, @fig-pr-auc-forest). The two LR models sit within each other's bootstrap intervals on every class column. The XGBoost models sit below both LR models on not-happy PR-AUC at 0.174 and 0.181; all four bootstrap intervals overlap. Top-decile precision ranges from 0.149 at the class-frequency baseline to 0.216 at the summary plus LLM flags LR.

#figure(
  image("../figures/fig_pr_auc_forest.pdf", width: 100%),
  caption: [One-vs-rest PR-AUC for each smiley class, with restaurant-clustered bootstrap 95% intervals. The dotted line marks the class-frequency baseline.],
) <fig-pr-auc-forest>

== Hygiene flag odds ratios

@tab-per-flag-univariate reports adjusted odds ratios for each of the six hygiene categories across two contrasts, neutral-vs-happy and sad-vs-happy. @fig-per-flag-forest plots both contrasts on a log scale.

#figure(
  text(size: 10pt, table(
    columns: (auto, auto, auto, auto),
    align: (left, right, right, right),
    table.header(
      [#strong[Category]],
      [#strong[n flagged]],
      [#strong[OR neutral vs happy (95% CI)]],
      [#strong[OR sad vs happy (95% CI)]],
    ),
    [pest or vermin], [120], [0.79 (0.46, 1.21)], [0.98 (0.46, 2.02)],
    [foreign object in food], [183], [1.21 (0.81, 1.74)], [1.01 (0.41, 2.39)],
    [food-safety concern], [1,247], [1.06 (0.86, 1.30)], [2.32 (1.24, 4.25)],
    [visible dirt], [428], [1.02 (0.75, 1.36)], [1.62 (0.65, 3.20)],
    [staff hygiene], [184], [1.32 (0.90, 1.86)], [1.38 (0.43, 3.10)],
    [illness after eating], [299], [1.19 (0.86, 1.62)], [1.47 (0.56, 2.92)],
  )),
  caption: [Adjusted odds ratios from a per-flag univariate logistic regression for each of the six hygiene categories, with restaurant-clustered bootstrap 95% intervals. Categories ordered by sad-vs-happy OR.],
) <tab-per-flag-univariate>
\

#figure(
  image("../figures/fig_per_flag_forest.pdf", width: 100%),
  caption: [Adjusted ORs for each hygiene category on the neutral-vs-happy and sad-vs-happy tests, log scale with restaurant-clustered bootstrap 95% CIs.],
) <fig-per-flag-forest>

Point estimates in @tab-per-flag-univariate range from 0.79 (pest or vermin, neutral-vs-happy) to 2.32 (food-safety concern, sad-vs-happy). Eleven of the twelve confidence intervals include 1 (@fig-per-flag-forest). The exception is the food-safety-concern flag on the sad-vs-happy contrast, with an adjusted OR of 2.32 (95% CI 1.24 to 4.25).
