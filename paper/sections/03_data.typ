= Data

We pair the Danish smiley register with Google Maps reviews. Google Maps is one of the most used review platforms for local businesses @brightlocal2026review. Pairing review-platform text with public inspection records has precedent in US and German studies @kang2013whereeat @farronato2025consumerreviews @hering2025hygienecasting, but no Danish counterpart exists.

== The smiley register

The register stores each inspection as an integer grade from 1 to 4 and shows the four most recent grades per establishment alongside the address, postcode, and a Danish industry classifier (branche). The 2022 reform retired one of the four values @foedevarestyrelsen_findsmiley. In the post-reform data, grade 1 maps to the happy pictogram, grade 2 to neutral, and grade 4 to sad, with grade 3 no longer in regular use.

Fødevarestyrelsen publishes the register as a downloadable Excel snapshot at findsmiley.dk. We work from a single snapshot pulled in May 2026, which has 58,458 establishments nationwide, with inspection dates running up to mid-April 2026.

== Google Maps reviews

Each Google Maps review has a star rating from 1 to 5, a free-text body and a timestamp. Google does not expose a public bulk export of reviews, so the platform has to be queried per-place.
