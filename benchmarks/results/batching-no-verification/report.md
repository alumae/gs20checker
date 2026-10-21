# In-memory production batching validation

Model: `gpt-6-luna`; prompt version 4; status: **complete**.

Two shuffled passes through the production streaming processor, with ten rows per batch, strict canonical venue name/ID validation, individual fallback, and no follow-up candidate verification. The same audited 100-item set is used, including the documented HCI correction. Original workbook bytes are exported in memory after matching. These timings exclude browser upload/download transport and are not concurrent with the historical baseline. Provider caching is enabled; there is no local or shared result cache.

| Pass | All exact | Random | Challenge | Errors | Matching s | Total s | API requests | Individual fallbacks | Verifications |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 98/100 | 78/80 | 20/20 | 0 | 64.48 | 65.92 | 10 | 0 | 0 |
| 2 | 99/100 | 79/80 | 20/20 | 0 | 62.84 | 64.70 | 10 | 0 | 0 |

Historical audited results: single requests 99/100 and 97/100 in 201.15s and 199.02s; original batches 98/100 and 100/100 in 49.31s and 53.33s. See [original report](../report.md). The small set and repeated samples do not prove equivalent accuracy. SDK retries, if any, are included in request timings.

Pre-verification production baseline: 98/100 on both passes, matching in 51.51s and 47.12s with 10 and 11 API requests. See [baseline](../streaming/report.md).

Combined exact matches: 197/200; acceptance target: at least 196/200, with both passes complete.
Acceptance: **passed**.

## Disagreements

| Pass | Item | Expected | Actual | Model explanation |
| --- | --- | --- | --- | --- |
| 1 | etis-0063 | No match | Journal of Materials Research and Technology | The reference identifies the journal as Journal of Materials Science and Technology; this is the catalogue’s corresponding venue entry. |
| 1 | etis-1141 | HCI International | unmatched | The cited venue is HCI International 2025 – Late Breaking Papers, a distinct proceedings volume; the catalogue's HCI International entry does not establish this volume as the main conference proceedings. |
| 2 | etis-1141 | HCI International | unmatched | The reference specifies HCI International 2025 Late Breaking Papers, a proceedings volume not clearly equivalent to the catalogue's HCI International venue. |
