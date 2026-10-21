# Current production batching validation

Model: `gpt-6-luna`; prompt 5; venue policy 2; status: **complete**.

Two shuffled passes through the production streaming processor, batches of ten, strict name/ID validation and malformed-output fallback. No candidate verification. Each pass exports the original workbook in memory. Matching times exclude export and browser transport; provider caching and load are uncontrolled.

Companion tracks count as the main conference; workshops do not. Missing ETIS punctuation does not change venue identity. The policy overlay and earlier HCI audit are recorded in labels.json; original annotations and reports are preserved. These are repeated decisions, not independent samples. Labels are assistant-authored and not independently human-reviewed.

| Pass | Correct | False + | False − | Wrong ID | Errors | Matching s | Calls | Fallbacks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 50/50 | 0 | 0 | 0 | 0 | 25.22 | 5 | 0 |
| 2 | 45/50 | 4 | 0 | 0 | 1 | 26.64 | 6 | 1 |

Combined: **95/100**. Configured 98% accuracy threshold: **not met**.

Prior saved predictions from `benchmarks/results/batching-no-verification/fresh50.json`, rescored under the same NEW policy: **99/100**. This is a label-policy rescore, not a new run of the old model prompt. Historical reports retain their original scores.

## Disagreements

- Pass 2, etis-0193: expected no match; returned Applied Sciences. No match: the reference identifies Processes, which is not listed; Applied Sciences is a distinct journal.
- Pass 2, etis-0217: expected no match; returned International Conference on Machine Learning. SAC is the ACM/SIGAPP Symposium on Applied Computing; this conference is not listed in the catalogue.
- Pass 2, etis-0270: expected no match; returned no match/error. The model returned an invalid venue result after an individual retry.
- Pass 2, etis-0515: expected no match; returned International Review of Economics & Finance. The stated venue, International Economics and Economic Policy, is not listed; the catalogue's International Review of Economics & Finance is a different journal.
- Pass 2, etis-0890: expected no match; returned European Journal of Wood and Wood Products. No catalogue match: the cited journal is Journal of Chemical & Engineering Data, which is not listed.
