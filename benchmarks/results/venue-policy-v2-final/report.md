# Current production batching validation

Model: `gpt-6-luna`; prompt 6; venue policy 2; status: **complete**.

Two shuffled passes through the production streaming processor, batches of ten, strict name/ID validation and malformed-output fallback. No candidate verification. Each pass exports the original workbook in memory. Matching times exclude export and browser transport; provider caching and load are uncontrolled.

Companion tracks count as the main conference; workshops do not. Missing ETIS punctuation does not change venue identity. The policy overlay and earlier HCI audit are recorded in labels.json; original annotations and reports are preserved. These are repeated decisions, not independent samples. Labels are assistant-authored and not independently human-reviewed.

| Pass | Correct | False + | False − | Wrong ID | Errors | Matching s | Calls | Fallbacks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 98/100 | 0 | 2 | 0 | 0 | 97.17 | 10 | 0 |
| 2 | 99/100 | 0 | 1 | 0 | 0 | 128.42 | 11 | 1 |

Combined: **197/200**. Configured 98% accuracy threshold: **passed**.

Prior saved predictions from `benchmarks/results/batching-no-verification/run.json`, rescored under the same NEW policy: **195/200**. This is a label-policy rescore, not a new run of the old model prompt. Historical reports retain their original scores.

## Disagreements

- Pass 1, etis-0157: expected Biomass and Bioenergy; returned no match/error. Biomass & Bioenergy is not listed; the catalogue entry Biomass and Bioenergy is a different journal title.
- Pass 1, etis-1028: expected Journal of Paleontology; returned no match/error. Journal of Paleontology is not listed in the catalogue.
- Pass 2, etis-1088: expected IEEE Conference on Decision and Control; returned no match/error. IEEE Conference on Decision and Control is not listed under that name; the catalogue entry is American Control Conference, a different venue.
