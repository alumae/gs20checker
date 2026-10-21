# Current production batching validation

Model: `gpt-6-luna`; prompt 7; venue policy 2; status: **complete**.

Two shuffled passes through the production streaming processor, batches of ten, strict name/ID validation and malformed-output fallback. No candidate verification. Each pass exports the original workbook in memory. Matching times exclude export and browser transport; provider caching and load are uncontrolled.

Companion tracks count as the main conference; workshops do not. Missing ETIS punctuation does not change venue identity. The policy overlay and earlier HCI audit are recorded in labels.json; original annotations and reports are preserved. These are repeated decisions, not independent samples. Labels are assistant-authored and not independently human-reviewed.

| Pass | Correct | False + | False − | Wrong ID | Errors | Matching s | Calls | Fallbacks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100/100 | 0 | 0 | 0 | 0 | 74.71 | 10 | 0 |
| 2 | 98/100 | 2 | 0 | 0 | 0 | 67.05 | 10 | 0 |

Combined: **198/200**. Configured 98% accuracy threshold: **passed**.

Prior saved predictions from `benchmarks/results/venue-policy-v2-final/run.json`, rescored under the same NEW policy: **197/200**. This is a label-policy rescore, not a new run of the old model prompt. Historical reports retain their original scores.

## Disagreements

- Pass 2, etis-0067: expected no match; returned IEEE Open Journal of the Communications Society. Publication venue is IEEE Open Journal of Power Electronics; that same journal is listed.
- Pass 2, etis-0238: expected no match; returned Land Degradation & Development. The publication venue is *Local Environment*, which is listed in the catalogue.
