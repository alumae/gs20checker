# Current production batching validation

Model: `gpt-6-luna`; prompt 7; venue policy 2; status: **complete**.

Two shuffled passes through the production streaming processor, batches of ten, strict name/ID validation and malformed-output fallback. No candidate verification. Each pass exports the original workbook in memory. Matching times exclude export and browser transport; provider caching and load are uncontrolled.

Companion tracks count as the main conference; workshops do not. Missing ETIS punctuation does not change venue identity. The policy overlay and earlier HCI audit are recorded in labels.json; original annotations and reports are preserved. These are repeated decisions, not independent samples. Labels are assistant-authored and not independently human-reviewed.

| Pass | Correct | False + | False − | Wrong ID | Errors | Matching s | Calls | Fallbacks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 48/50 | 2 | 0 | 0 | 0 | 37.80 | 5 | 0 |
| 2 | 50/50 | 0 | 0 | 0 | 0 | 44.73 | 5 | 0 |

Combined: **98/100**. Configured 98% accuracy threshold: **passed**.

Prior saved predictions from `benchmarks/results/venue-policy-v2-final/fresh/run.json`, rescored under the same NEW policy: **98/100**. This is a label-policy rescore, not a new run of the old model prompt. Historical reports retain their original scores.

## Disagreements

- Pass 1, etis-0076: expected no match; returned IEEE Open Journal of the Communications Society. The publication venue is IEEE Open Journal of Power Electronics; that same journal is listed in the catalogue.
- Pass 1, etis-0270: expected no match; returned Materials. The publication venue is Materials & Design; the catalogue lists this same journal as “Materials & Design.”
