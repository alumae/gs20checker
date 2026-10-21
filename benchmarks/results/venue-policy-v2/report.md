# Current production batching validation

Model: `gpt-6-luna`; prompt 5; venue policy 2; status: **complete**.

Two shuffled passes through the production streaming processor, batches of ten, strict name/ID validation and malformed-output fallback. No candidate verification. Each pass exports the original workbook in memory. Matching times exclude export and browser transport; provider caching and load are uncontrolled.

Companion tracks count as the main conference; workshops do not. Missing ETIS punctuation does not change venue identity. The policy overlay and earlier HCI audit are recorded in labels.json; original annotations and reports are preserved. These are repeated decisions, not independent samples. Labels are assistant-authored and not independently human-reviewed.

| Pass | Correct | False + | False − | Wrong ID | Errors | Matching s | Calls | Fallbacks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 96/100 | 1 | 3 | 0 | 0 | 55.98 | 10 | 0 |
| 2 | 100/100 | 0 | 0 | 0 | 0 | 56.94 | 10 | 0 |

Combined: **196/200**. Configured 98% accuracy threshold: **passed**.

Prior saved predictions from `benchmarks/results/batching-no-verification/run.json`, rescored under the same NEW policy: **195/200**. This is a label-policy rescore, not a new run of the old model prompt. Historical reports retain their original scores.

## Disagreements

- Pass 1, etis-0063: expected no match; returned The Journal of Rheumatology. The publication venue is Journal of Material Science and Technology, which is not listed. No matching catalogue venue.
- Pass 1, etis-0157: expected Biomass and Bioenergy; returned no match/error. Biomass & Bioenergy is not listed in the catalogue.
- Pass 1, etis-1088: expected IEEE Conference on Decision and Control; returned no match/error. The IEEE Conference on Decision and Control is not listed under this publication’s precise venue name in the supplied catalogue.
- Pass 1, etis-1141: expected HCI International; returned no match/error. HCI International is not listed as a conference in the catalogue; the proceedings series is not a listed venue.
