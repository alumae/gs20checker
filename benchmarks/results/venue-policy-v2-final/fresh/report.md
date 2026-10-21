# Current production batching validation

Model: `gpt-6-luna`; prompt 6; venue policy 2; status: **complete**.

Two shuffled passes through the production streaming processor, batches of ten, strict name/ID validation and malformed-output fallback. No candidate verification. Each pass exports the original workbook in memory. Matching times exclude export and browser transport; provider caching and load are uncontrolled.

Companion tracks count as the main conference; workshops do not. Missing ETIS punctuation does not change venue identity. The policy overlay and earlier HCI audit are recorded in labels.json; original annotations and reports are preserved. These are repeated decisions, not independent samples. Labels are assistant-authored and not independently human-reviewed.

| Pass | Correct | False + | False − | Wrong ID | Errors | Matching s | Calls | Fallbacks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 50/50 | 0 | 0 | 0 | 0 | 59.95 | 5 | 0 |
| 2 | 48/50 | 2 | 0 | 0 | 0 | 52.06 | 5 | 0 |

Combined: **98/100**. Configured 98% accuracy threshold: **passed**.

Prior saved predictions from `benchmarks/results/batching-no-verification/fresh50.json`, rescored under the same NEW policy: **99/100**. This is a label-policy rescore, not a new run of the old model prompt. Historical reports retain their original scores.

## Disagreements

- Pass 2, etis-0515: expected no match; returned International Economics. The publication identifies International Economics and Economic Policy, which is distinct from the catalogue's International Economics.
- Pass 2, etis-0890: expected no match; returned Journal of Agricultural and Food Chemistry. The journal is Journal of Chemical & Engineering Data; that journal is not listed. Correction? No exact entry found.
