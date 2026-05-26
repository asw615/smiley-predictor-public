#import "helpers.typ": nv, sm

#sm(level: 1)[Conclusions]

On a dataset of 8,067 Danish-restaurant inspections, three summary features of the Google Maps review window lifted top-decile precision from a class-frequency baseline of 0.149 to 0.201 under restaurant-grouped cross-validation. LLM-extracted hygiene flags added nothing measurable beyond the summary features, and eleven of twelve per-flag odds ratios were consistent with the null.

We do not recommend deployment based on this work. Our dataset has a 14.9% non-happy rate against 9.3% in the comparable register slice (restaurants in the same category, inspections after 2022, pooled across the three retained slots), so deployment precision would be lower than what we report, though we do not estimate the magnitude of the drop. A register slice retaining every inspection per restaurant, rather than only the four most recent, would help determine whether the observed lift is real or mainly an artefact of the four-slot cap. Whether such a dataset would materially improve predictive performance is less clear, because several of the other limitations would remain.
