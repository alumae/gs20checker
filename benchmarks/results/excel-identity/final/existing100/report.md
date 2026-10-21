# Current production batching validation

Model: `gpt-6-luna`; prompt 8; venue policy 2; status: **complete**.

Two shuffled passes through the production streaming processor, batches of ten, strict name/ID validation and malformed-output fallback. No candidate verification. Each pass exports the original workbook in memory. Matching times exclude export and browser transport; provider caching and load are uncontrolled.

Companion tracks count as the main conference; workshops do not. Missing ETIS punctuation does not change venue identity. The policy overlay and earlier HCI audit are recorded in labels.json; original annotations and reports are preserved. These are repeated decisions, not independent samples. Labels are assistant-authored and not independently human-reviewed.

| Pass | Correct | False + | False − | Wrong ID | Errors | Matching s | Calls | Fallbacks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100/100 | 0 | 0 | 0 | 0 | 66.94 | 11 | 1 |
| 2 | 98/100 | 1 | 1 | 0 | 0 | 75.55 | 11 | 1 |

Combined: **198/200**. Configured 98% accuracy threshold: **passed**.

Prior saved predictions from `benchmarks/results/venue-policy-v2-final/run.json`, rescored under the same NEW policy: **197/200**. This is a label-policy rescore, not a new run of the old model prompt. Historical reports retain their original scores.

## Disagreements

- Pass 2, etis-0067: expected no match; returned IEEE Open Journal of the Communications Society. The publication venue is IEEE Open Journal of Power Electronics; that same journal is listed in the catalogue.
- Pass 2, etis-1088: expected IEEE Conference on Decision and Control; returned no match/error. Publication venue is the IEEE Conference on Decision and Control (CDC); that venue is not listed.
