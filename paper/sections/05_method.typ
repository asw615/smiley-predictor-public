= Method

== Target classes <sec-outcome>

We drop the 19 grade-3 rows, leaving 8,067 inspections at 85.1% happy, 12.9% neutral, and 2.0% sad. When a retained inspection's immediate predecessor was a dropped grade-3 row, we re-anchor its review window to the next retained inspection preceding it in the Smiley register snapshot.

== Features

Each between-inspection review window is summarised by three features (@tab-summary-features). The mean star rating is missing for empty windows. For the LR, missing values are imputed at the training-fold mean before standardisation. XGBoost handles missing values through its sparsity-aware splits @chen2016xgboost.

#figure(
  table(
    columns: (auto, 1fr),
    align: (left, left),
    table.header([Feature], [Definition]),
    [log review count], [log of one plus the number of in-window reviews],
    [mean star rating], [arithmetic mean of in-window star ratings, missing when the window is empty],
    [low-star share], [share of in-window reviews with a one- or two-star rating],
  ),
  caption: [The three window-level summary features.],
) <tab-summary-features>

We adapt a six-category hygiene schema from the keyword lists of #cite(<schomberg2016supplementing>, form: "prose") and #cite(<hering2025hygienecasting>, form: "prose") (@tab-hygiene-schema). 

#figure(
  table(
    columns: (auto, 1fr),
    align: (left, left),
    table.header([Category], [Danish definition supplied to the model]),
    [pest/vermin], [dyr/skadedyr/insekter/fluer/rotter/mus/maddiker i mad eller lokale],
    [foreign object in food], [hår, plastik, glas, metal, sten eller andet fremmedlegeme i mad/drikke],
    [food-safety concern], [usikker mad/håndtering, rå/ikke gennemstegt risikomad, fordærvet/harsk mad, allergen/vegansk forurening, genbrugte rester, usikker buffet/opbevaring, eller sikkerhedsrelevant kold mad],
    [visible dirt], [konkret snavs, mug/skimmel, spindelvæv, beskidte borde/gulve/toiletter/buffet],
    [staff hygiene], [personalets hygiejne påvirker madlavning/servering direkte],
    [illness after eating], [madforgiftning, opkast, diarré, mavepine/kramper eller kvalme efter spisning],
  ),
  caption: [The six hygiene categories and the Danish definitions supplied to the classifier.],
) <tab-hygiene-schema>

The hygiene schema gives one binary indicator per window per category. An indicator is positive when at least one in-window review carries that category label, and zero otherwise. Windows with no scored reviews receive structural zeros.

=== Per-review hygiene labelling <sec-annotation>

We label each scraped review against the six hygiene categories. Reviews rated three stars or fewer are passed to Google's Gemma 4B @gemma2024, run locally with Ollama @ollama2024 under a JSON-schema response that returns one boolean per category. The prompt is Danish, includes a small set of few-shot examples @brown2020fewshot, and instructs the model to ignore complaints about service, price, taste, or waiting time. The full prompt can be found in @prompt-gemma-4. Reviews rated four or five stars are ignored by the model and receive all-negative hygiene flags. To figure out the risk of skipping high-rated reviews, we passed a stratified sample of 1,000 of them (217 four-star, 783 five-star) through the same Gemma 4B classifier. It flagged 9 (0.09%), with the per-category breakdown in @sec-high-star-inspection. This is an upper bound on the share of high-rated reviews the classifier would have marked had we run it on the full corpus

== Models

A class-frequency baseline predicts the training-fold class proportions for every test row. We also fit a two-feature logistic regression on mean star rating and log(1 + review count), as a consumer-rating reference. Both establish the floor that any text-derived feature set has to beat.

The main comparison is a 2×2 design over the feature sets and classifiers. We construct two feature sets where the first is the three summary features alone and the second set is the summary features combined with the six hygiene flags. The classifiers are multinomial logistic regression (LR) and XGBoost @chen2016xgboost. Each of the four combinations is fit per fold and pooled out-of-fold for evaluation.

We fit the LR with a multinomial softmax loss and an L2 penalty at the default C = 1, using scikit-learn @pedregosa2011scikit. Missing mean ratings are imputed at the training-fold mean, then all features are standardised. The XGBoost classifiers are not tuned. They run at default settings (400 trees, depth 5, learning rate 0.05, row and column subsample 0.8, histogram tree method) and produce three-class softmax probabilities.

Hyperparameters are pre-specified rather than tuned. Class imbalance is handled by neither weighting nor resampling, and no post-hoc calibration is applied. Tuning, weighting, or calibration would affect the four models unevenly, which would make comparison between the models difficult. 

== Evaluation

We partition the panel into five folds, grouped by restaurant so that all inspections of a given place fall in the same fold, and stratified on the three-class target @sogaard2021random @pedregosa2011scikit. All metrics are computed on the pooled out-of-fold predictions.

At a 14.9% not-happy rate, a model can achieve high ROC-AUC while placing few non-happy inspections near the top of the predicted ranking, so we use PR-AUC as the primary metric @saito2015precision. We report it per class in a one-vs-rest framing, and as a not-happy score defined as one minus the predicted happy probability. We also report precision at the top decile of that ranking.

Confidence intervals come from 2,000 bootstrap resamples at the restaurant level. Resamples that contain only one class are discarded, since PR-AUC is undefined in that case. Top-decile precision is reported as a point estimate.

== Sensitivity analyses

=== Per-flag adjusted odds ratios

For each hygiene category, we fit a separate pairwise logistic regression to estimate whether a positive flag for that category in a window raises the odds of a neutral or sad inspection over a happy one. We control for the log of one plus the scored review count, since a flag is more likely to be positive when more reviews were scored. This gives twelve odds ratios, one for each of the six categories times the two non-happy classes. Confidence intervals come from the same restaurant-clustered bootstrap used for the cross-validated metrics. The twelve tests are not corrected for multiple comparisons, so we report the odds ratios as suggestive rather than confirmed findings.

All code for the scraping, data wrangling, and modelling is available in the repository linked on the title page.