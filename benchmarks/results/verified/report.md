# In-memory production batching validation

Model: `gpt-6-luna`; prompt version 4; status: **complete**.

Two shuffled passes through the production streaming processor, with ten rows per batch, strict canonical venue name/ID validation, individual fallback, and selective candidate verification. The same audited 100-item set is used, including the documented HCI correction. Original workbook bytes are exported in memory after matching. These timings exclude browser upload/download transport and are not concurrent with the historical baseline. Provider caching is enabled; there is no local or shared result cache.

| Pass | All exact | Random | Challenge | Errors | Matching s | Total s | API requests | Individual fallbacks | Verifications |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 98/100 | 79/80 | 19/20 | 0 | 164.15 | 165.68 | 76 | 11 | 55 |
| 2 | 99/100 | 79/80 | 20/20 | 0 | 150.24 | 151.61 | 65 | 1 | 54 |

Historical audited results: single requests 99/100 and 97/100 in 201.15s and 199.02s; original batches 98/100 and 100/100 in 49.31s and 53.33s. See [original report](../report.md). The small set and repeated samples do not prove equivalent accuracy. SDK retries, if any, are included in request timings.

Pre-verification production baseline: 98/100 on both passes, matching in 51.51s and 47.12s with 10 and 11 API requests. See [baseline](../streaming/report.md).

Combined exact matches: 197/200; acceptance target: at least 196/200, with both passes complete.
Acceptance: **passed**.

## Targeted regression and interpretation

The final code matched the Lillepalu & Alumäe LREC publication correctly in all five
single-reference checks and all five original ten-row batch checks. See [recorded
regression results](lrec.json). These checks finished before this timing run started;
the recorded source hashes match the final production matching and candidate code.

The initial candidate-verification iteration scored 195/200 and is preserved in
[its report](../verification-initial/report.md). The final revision adds checks for
unsupported positive results with structured venue fields, tightens journal identity
and demonstration-track distinctions, and handles lost conjunctions in whole ETIS
venue fields. These changes were informed by errors on this same benchmark: the scores
are development/regression results, not an independent holdout evaluation. Neither the
frozen annotations nor the catalogue was changed.

Verification rechecked 54–55% of these rows. Average matching time increased from
49.31s to 157.19s per 100 publications (about 3.2×); malformed-output fallback also
contributed, especially in pass 1. Individual API requests and verification requests
are included in the timing and counts above. This trades much of the earlier batching
speedup for explicit candidate checks; it does not establish a general accuracy gain.

## Disagreements

| Pass | Item | Expected | Actual | Model explanation |
| --- | --- | --- | --- | --- |
| 1 | etis-0494 | IEEE Transactions on Smart Grids | unmatched | The reference and journal field identify IEEE Transactions on Smart Grid. That journal is not among the shortlisted venues; the similar IEEE Transactions on Power Systems and IEEE Transactions on Sustainable Energy are distinct journals. |
| 1 | etis-1141 | HCI International | unmatched | The reference identifies the publication as the HCI International 2025 Late Breaking Papers proceedings, Part III—not the main HCI International conference proceedings. No shortlisted candidate explicitly names this distinct proceedings series. |
| 2 | etis-1141 | HCI International | unmatched | The reference identifies a Springer proceedings volume titled “HCI International 2025 – Late Breaking Papers,” a late-breaking-papers track rather than the main HCI International proceedings. None of the candidates explicitly names that track; the similarly named main-conference candidate is not an exact venue match. |
