= Data

We pair the Danish smiley register with Google Maps reviews. Google Maps is one of the most used review platforms for local businesses @brightlocal2026review. Pairing review-platform text with public inspection records has precedent in US and German studies @kang2013whereeat @farronato2025consumerreviews @hering2025hygienecasting, but no Danish counterpart exists.

== The smiley register

The register stores each inspection as an integer grade from 1 to 4 and shows the four most recent grades per establishment alongside the address, postcode, and a Danish industry classifier (branche). The 2022 reform retired one of the four values @foedevarestyrelsen_findsmiley. In the post-reform data, grade 1 maps to the happy pictogram, grade 2 to neutral, and grade 4 to sad, with grade 3 no longer in regular use.

Fødevarestyrelsen publishes the register as a downloadable Excel snapshot at findsmiley.dk. We work from a single snapshot pulled in May 2026, which has 58,458 establishments nationwide, with inspection dates running up to mid-April 2026.

== Google Maps reviews

Each Google Maps review has a star rating from 1 to 5, a free-text body and a timestamp. Google does not expose a public bulk export of reviews, so the platform has to be queried per-place.

== Ethics

Building the panel meant querying publicly visible Google reviews one place at a time, since no Danish dataset links review text to inspection outcomes. The reviews are already public, and we collected only the fields the research question needs (star rating, review text, and timestamp). Google reviews contain personal data, such as reviewer names and freely written opinions, so we follow the data-minimisation principle of the General Data Protection Regulation. We keep the scraped corpus on local storage and publish only our code and aggregate outputs, and none of the raw scraped review data is uploaded to the public repository.
