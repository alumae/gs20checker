# In-memory production batching validation

Model: `gpt-6-luna`; prompt version 2; status: **complete**.

Two shuffled passes through the production streaming processor, with ten rows per batch, strict canonical venue name/ID validation, and individual fallback. The same audited 100-item set is used, including the documented HCI correction. Original workbook bytes are exported in memory after matching. These timings exclude browser upload/download transport and are not concurrent with the historical baseline. Provider caching is enabled; there is no local or shared result cache.

| Pass | All exact | Random | Challenge | Errors | Matching s | Total s | API requests | Individual fallbacks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 98/100 | 78/80 | 20/20 | 0 | 51.51 | 52.83 | 10 | 0 |
| 2 | 98/100 | 78/80 | 20/20 | 0 | 47.12 | 48.46 | 11 | 1 |

Historical audited results: single requests 99/100 and 97/100 in 201.15s and 199.02s; original batches 98/100 and 100/100 in 49.31s and 53.33s. See [original report](../report.md). The small set and repeated samples do not prove equivalent accuracy. SDK retries, if any, are included in request timings.

`run.json` records the source hashes used during this run. A subsequent cleanup-only change ensures that buffers and the event loop are released even if closing the API client raises; that case is regression-tested separately. Matching logic and prompts are unchanged.

## Disagreements

| Pass | Item | Expected | Actual | Model explanation |
| --- | --- | --- | --- | --- |
| 1 | etis-0063 | No match | Journal of Materials Research and Technology | The reference and structured journal field say Journal of Material Science and Technology, which is not the catalogue entry Journal of Materials Research and Technology. |
| 1 | etis-1141 | HCI International | unmatched | This is a late-breaking-papers proceedings volume; the catalogue's HCI International entry does not clearly identify this distinct proceedings venue. |
| 2 | etis-0063 | No match | Journal of Materials Research and Technology | The structured journal field's “Journal of Material Science and Technology” is a spelling/word-order variant of Journal of Materials Research and Technology. |
| 2 | etis-0916 | No match | IEEE Access | The journal field names IEEE Open Journal of Power Electronics, which is not the catalogue's IEEE Open Journal of the Communications Society; these are distinct venues. |
