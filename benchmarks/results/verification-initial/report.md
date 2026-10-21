# In-memory production batching validation

Model: `gpt-6-luna`; prompt version 3; status: **complete**.

Two shuffled passes through the production streaming processor, with ten rows per batch, strict canonical venue name/ID validation, individual fallback, and selective candidate verification. The same audited 100-item set is used, including the documented HCI correction. Original workbook bytes are exported in memory after matching. These timings exclude browser upload/download transport and are not concurrent with the historical baseline. Provider caching is enabled; there is no local or shared result cache.

| Pass | All exact | Random | Challenge | Errors | Matching s | Total s | API requests | Individual fallbacks | Verifications |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 97/100 | 78/80 | 19/20 | 0 | 142.56 | 143.64 | 64 | 0 | 54 |
| 2 | 98/100 | 79/80 | 19/20 | 0 | 132.36 | 134.21 | 64 | 0 | 54 |

Historical audited results: single requests 99/100 and 97/100 in 201.15s and 199.02s; original batches 98/100 and 100/100 in 49.31s and 53.33s. See [original report](../report.md). The small set and repeated samples do not prove equivalent accuracy. SDK retries, if any, are included in request timings.

Pre-verification production baseline: 98/100 on both passes, matching in 51.51s and 47.12s with 10 and 11 API requests. See [baseline](../streaming/report.md).

Combined exact matches: 195/200; acceptance target: at least 196/200, with both passes complete.

This initial implementation did not meet the acceptance target. The subsequent revision
adds verification for unsupported positives with explicit venue fields, tightens journal
identity and demonstration-track instructions, and accommodates lost conjunctions in
whole ETIS venue fields. Original annotations remain unchanged. The LREC diagnostic run
overlapped approximately the first 18 seconds of pass 1; later timing runs are sequential.

## Disagreements

| Pass | Item | Expected | Actual | Model explanation |
| --- | --- | --- | --- | --- |
| 1 | etis-0063 | No match | Journal of Materials Research and Technology | The reference identifies the journal as Journal of Material Science and Technology (JMST), a wording variant of the shortlisted Journal of Materials Research and Technology. |
| 1 | etis-0604 | No match | IEEE Transactions on Industrial Electronics | The stated journal is IEEE Transactions on Industry Applications; that distinct journal is not listed, and this similar catalogue title is not equivalent. |
| 1 | etis-0967 | No match | Conference of the European Chapter of the Association for Computational Linguistics (EACL) | The reference identifies the EACL 2026 Proceedings of System Demonstrations; this is a demonstration track within the EACL conference, not a separate venue. |
| 2 | etis-0157 | Biomass and Bioenergy | unmatched | The reference identifies the journal as Biomass and Bioenergy (volume 209, article 108972), not Fuel. The shortlisted venue is not a match. |
| 2 | etis-0967 | No match | Conference of the European Chapter of the Association for Computational Linguistics (EACL) | The reference identifies the EACL 2026 Proceedings of System Demonstrations. This is a demonstration track within the EACL conference, not a separate main conference or journal. |
