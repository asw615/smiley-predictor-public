= Discussion

Summary review features give a modest ranking lift over the class-frequency baseline. The LLM-extracted hygiene flags add nothing on top.

== Main findings

RQ1 asked whether simple summary statistics of the review window, review count, mean star rating, and share of low-star reviews, improve ranking over a class-frequency baseline. They do, but only modestly. When the logistic model ranks inspections by these three summary features, 20.1% of the highest-risk decile turn out non-happy, against 14.9% under a random pick. This is a relative gain of 35% in top-decile precision (0.149 to 0.201). The same signal shows up as not-happy PR-AUC, which moves from 0.149 at the class-frequency baseline to 0.182 (95% CI 0.169 to 0.197). The gain holds up at the per-class level for both the neutral grade (PR-AUC 0.158, CI 0.146 to 0.172, base rate 0.129) and the sad grade (0.027, CI 0.021 to 0.036, base rate 0.020), though the absolute gains over each base rate are small.

Logistic regression matches or beats XGBoost on every metric. On not-happy PR-AUC the summary-feature LR scores 0.182 against 0.174 for XGBoost, with overlapping bootstrap intervals. The LR is better on point estimate but the intervals overlap, so we do not claim a separation. The biggest XGBoost shortfall is on the sad grade, where its PR-AUC of 0.021 barely beats the 0.020 base rate while LR reaches 0.027. That, together with the easier reading of a linear model's coefficients, is why we treat the summary-feature logistic regression as the best of the four models.

One caveat applies to all four models. The lift above comes from a panel where non-happy grades appear more often than in the underlying population. Our dataset contains 14.9% non-happy, against 9.3% in the comparable slice of the Smiley register (restaurants in the same category, inspections after 2022, pooled across the three retained inspection slots). Top-decile precision and PR-AUC both depend on this base rate, so performance would be lower on the full register.

== Hygiene flags

RQ2 asked whether structured hygiene flags extracted from the review text by an LLM add ranking power on top of those summary statistics. They do not. Adding the six LLM-extracted hygiene flags to the summary features does not change the result. Every per-class PR-AUC interval overlaps with the summary-only interval for both the logistic regression and the XGBoost models (@tab-headline-metrics). Top-decile precision moves from 0.201 to 0.216 with the flags added, but this falls inside the bootstrap noise and we do not treat it as a real gain.

Eleven of the twelve odds ratios in @tab-per-flag-univariate include 1. The exception is the food-safety-concern flag on the sad-vs-happy test, with an OR of 2.32 (1.24 to 4.25). With twelve tests at the 5% level, chance alone gives about 0.6 false positives, so one positive is consistent with the null. We therefore treat it as suggestive.

The cleanest way to diagnose this null would have been to fit a flag-only alongside the summary-only and the combined models, so the increments could be read against each other. We did not, and that is a planning mistake we want to flag openly. Without that fit we cannot separate three different explanations: the flags carry information the summary features already carry (redundancy), our six-category schema is too coarse for how diners describe hygiene, or the per-review LLM scoring is too noisy. The 1,000 test of the four and five star reviews had a 0.09% false-positive rate, which makes the LLM extraction noise less likely, but we cannot rule it out. We suspect redundancy and schema coarseness account for most of the null, but that is an interpretation.

We chose flags over sentence embeddings for interpretability. A health inspector using the model needs to be able to ask why a restaurant was flagged by the model, and a positive for a pest-or-vermin flag can answer that, while an embedding can not directly. We did test embeddings over the same windows and got broadly similar PR-AUC, so interpretability cost us little in model performance. Recent benchmarks suggest that instruction-tuned LLMs at the size that we used reach competitive zero-shot accuracy on this kind of task @aarab2026btzscbenchmarkzeroshottext @kostina2025llmtextclassification.

To check that the LLM was not inventing flags, we hand-labelled 200 reviews against the same six categories. Agreement was generally high across most categories (Cohen's K ranging from 0.46 to 0.92; see @cohen-k). In several of the disagreements, the model had caught hygiene mentions that we had missed on the first read. The remaining disagreements were generally cases where the category assignment itself was ambiguous enough that human coders could also have disagreed.

The one positive OR fits the wider literature. Food-safety concern is the category most aligned with what #cite(<farronato2025consumerreviews>, form: "prose") calls diner-observable problems, and that is the category in which we would most expect reviews to carry signal. The categories whose effects disappear once we control for review volume are the ones whose content overlaps the summary features, which is consistent with the redundancy interpretation of the results. 

== Comparison with previous literature

Our modest result fits the strongest recent benchmark. #cite(<altenburger2019yelp>, form: "prose") re-analysed the Seattle inspection data that first suggested reviews could target inspections, and showed the apparent signal was an artefact of sampling only the extreme-scoring restaurants. On their full 13,000-inspection register, reviews predict the outcome poorly, add little once a restaurant's own inspection history is in the model, and fail to beat structured features even when given as word-embedding representations of the text. Our small gain, which was carried by mean star rating and review count, is consistent with that finding, and our text-derived hygiene flags add nothing on top. 

#cite(<farronato2025consumerreviews>, form: "prose") reach a similar conclusion. Using New York City inspections and Yelp, they find reviews informative about the hygiene problems diners directly experience, such as pests and food temperature, and far less informative about the worker-hygiene and facility-maintenance failures the customer never sees. The smiley scheme collapses both kinds of failure into one grade, where a neutral face can be issued for paperwork lapses, temperature-log misses, or staff-training gaps no diner could observe. A review-based signal should therefore weaken when observable and non-observable failures are grouped together, which is what our flag null shows. The single inspection exception is consistent with this reading, since the food-safety-concern flag tracks spoiled or unsafe food, one of the few hygiene dimensions reviews appear to capture reliably.

Against the earlier US literature, which reports 78%–90%+ classification scores on smaller curated datasets, the contrast is mainly about what the model is trying to predict, not how @kang2013whereeat @schomberg2016supplementing @wong2016predicting. The 612-inspection Seattle subset, the San Francisco pilot, and the Kitchener-Waterloo benchmark target quantities closer to violation prediction or hand-labelled illness detection than the smiley scheme's mixed-criterion grade. A median of twelve reviews per inspection window is a thinner text base than those studies work with. This paper's negative-leaning result therefore does not contradict that literature so much as it documents what happens when comparable methods meet a coarser regulatory target on a smaller per-restaurant evidence base.

== Limitations

=== Geographic and sampling biases

Our sample is concentrated in larger Danish cities, because urban restaurants attract more reviews and rural ones drop out at the empty-window step, which already removes 34% of the inspection rows. A review-based predictor cannot apply to a restaurant that nobody reviews. A West Jutland sausage vendor with a loyal local clientele will have an empty window, not because the food is poor, but because the customers already know what they are getting. Tourist areas and reviewers with strong opinions are over-represented in what remains, so any signal we estimate is limited to an urban, high-variance reviewer mix @zhu2022reviewbias. The register already records each establishment's zip code, which we left out of the feature set. Adding zip code, or a  urban-rural classifier derived from it, could let the model capture regional variation in reviewing behaviour, though it cannot recover the rural restaurants that drop out due to empty windows.

The register also keeps only each restaurant's four most-recent inspections. That means we under-count historical non-happy events at frequently-inspected establishments and over-count them at the most-recent slot.

Augmenting Google Maps with other review platforms (Trustpilot, Yelp, or TripAdvisor) could in principle reduce the empty-window rate. We did not try this option for two reasons. Neither of the platforms have the coverage Google Maps does for Danish restaurants, and cross-platform aggregation would risk duplicating reviews when a single diner posts about the same visit on multiple sites. De-duplication across platforms would require reviewer-identity matching, which is not possible, unless the review posted on multiple platforms is identical.

=== The hygiene schema

The six-category schema was adapted from #cite(<schomberg2016supplementing>, form: "prose") and #cite(<hering2025hygienecasting>, form: "prose"), both of which used English-language data. We did not validate it against an external taxonomy, nor had it reviewed by domain experts before running it on Danish reviews. This could result in two risks: we may have missed categories Danish diners actually use, and our category boundaries may not match how Danish reviewers actually divide up hygiene problems, so the LLM has to force ambiguous cases into the nearest box. The null finding for flags is therefore a statement about this schema on this dataset, not about whether structured extraction from reviews could lift the score in principle. An expert-reviewed schema with severity rating, or a learned text representation pooled across the window, would test this directly. 

=== Unannotated 4- and 5-star reviews

We ran the LLM only on reviews with 1, 2, or 3 stars and treated 4- and 5-star reviews as carrying no hygiene flags. We did this because running Gemma over the full review corpus was too computationally expensive, and the high-star test (0.09% false-positive rate, see @sec-annotation) suggested the cost of skipping them was small. The test only examined how many high-star reviews carry a true flag, and not how informative those flags would be, if we had them.

Reviewer behaviour makes this worse. Star ratings are an ordinal Likert-type scale, and reviewers use them very differently. Some reserve five stars for the best meal of their life, while others give five stars by default unless something is genuinely wrong @chen1995responsestyle. A diner of the second type may describe a real hygiene problem inside an otherwise positive five-star review, and our pipeline will never see it.

=== Fake reviews

Not every Google review is genuine. #cite(<Gryka2023Detecting>, form: "prose") built a Polish-language fake-review dataset and classified 14% of restaurant reviews in it as fake. Comparable rates have been reported on Yelp @Luca2016Fake. A restaurant that buys five-star reviews to bury bad ones looks cleaner to our pipeline than it really is, and this weakens exactly the low-grade hygiene signal we are trying to detect.

=== Google Maps matching and machine translation

The pipeline matched 6,000 register entries to Google Maps places using name and address heuristics, and we did not test the matches against ground truth. Chains and franchise restaurants are especially likely to share names, and they cluster in cities, so any match error probably reinforces the urban skew described above. A 100-place manual check would put a number on the match error rate, but we did not run one.

Google also auto-translates non-Danish reviews into Danish before serving them. The classifier therefore sees machine-translated text for an unknown fraction of reviews, and any nuance lost in translation is invisible to our pipeline.

=== Prior inspection history

We excluded prior inspection year and slot from the feature set because the register keeps only four inspections per restaurant. Including them would have meant fitting features that tell how far back the snapshot reaches, and not how often the restaurant is actually inspected. #cite(<altenburger2019yelp>, form:"prose")'s Seattle full-register replication suggests a model with real inspection history would beat reviews alone, and that the right benchmark for reviews in practice is reviews-plus-history, not reviews alone. We cannot fit this comparison on this register, as we do not have access to the full history of the restaurants. 

== Potential uses of the model

The ranking improvement over baseline is too small to use the model as a primary inspection ranker. Two regulatory workflows could still benefit from it.

=== Complaint triage

Fødevarestyrelsen already operates a public complaint channel @foedevarestyrelsen_klage. The model could re-rank items in that queue using the establishment's review history, so a complaint about a restaurant with a deteriorating review trajectory gets seen before a complaint about a restaurant whose reviews look unremarkable. This is the use we find most defensible, because the model does not have to find problems where no one has reported them. It only has to add information to a queue that already exists. 

A precedent exists. New York city has run a deployed complaint-triage classifier on Yelp reviews since 2012, supporting ten outbreaks and 8,523 complaints @effland2018discovering. A pre-study at Fødevarestyrelsen, fitting the model on archival complaints, and then comparing violations found at predicted inspections against the baseline, would show whether this works on Danish data.

=== Off-schedule visits

The Danish inspection cadence is publicly documented and risk-tiered @foedevarestyrelsen_bekendtgoerelse. A restaurant that knows roughly when its next visit will fall can clean up shortly before. The value of a review-based predictor is therefore not in re-ordering the scheduled queue, where the schedule can be gamed, but in flagging restaurants whose reviews suggest current hygiene problems the next scheduled visit will not catch in time. 

A simpler version of the same idea uses raw flag rates instead of the fitted model. The proportion of hygiene-flags at a restaurant is interpretable on its own and does not depend on the ranking model staying calibrated over time. A fixed-threshold could trigger an off-schedule visit @mu2024aifoodsafety. We did not test this directly. A fresh-sample benchmark comparing flag rates between non-compliant and compliant restaurants would be needed first.

=== Consumer-facing scores

Putting the model's score in front of consumers is technically straightforward but operationally fragile. Reviews are semi-anonymous and cheap to post, so a public score creates incentives for rivals to leave negative reviews and for upset customers to pile on extra ones. The current pipeline has no way to detect or filter either. We do not recommend this as a deployment target.

== Future directions

The cheapest follow-up is to refit the same models on a flag-only feature set, where we hold the data, the folds, and the labels fixed. Comparing summary-only, flag-only and summary+flag fits on the same folds would separate the three explanations for the null finding on the LLM flags. 

A finer schema, a learned representation, or both would test whether the six-category cut is the bottleneck. A Danish-language transformer encoder pooled across each window is one option. A finer extraction schema with severity ratings is another. 

The highest-value experiment is administrative rather than computational. A register pull from Fødevarestyrelsen that retains every inspection, rather than only the four most recent per establishment, would resolve the four-slot ceiling, allow prior-inspection history to be used in the feature set, and put the data on the same footing as #cite(<altenburger2019yelp>, form:"prose")'s Seattle full-register replication. The full register is presumably available inside the Fødevarestyrelsen's systems.

The same snapshot would also support an establishment-level benchmark comparing flag rates between restaurants with non-happy histories and clean ones. This would allow us to test the red-flag-rate proposal in the previous section.