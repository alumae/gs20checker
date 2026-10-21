# Excel venue-identity correction

## Findings

The six publication fields used by matching align between the original and result workbooks on all 1,161 rows. The error at Excel row 997 is a model decision, not a shifted Excel row. Its note rejects the chosen journal while its structured output selects International Journal of Language & Communication Disorders. The actual journal, **International Journal of River Basin Management**, is present in the stored catalogue (ID `3cedd737709511003eb8`), ranked **19** in **Life Sciences & Earth Sciences / Hydrology & Water Resources**.

The audit identified 23 positive results with contradictory notes, including six whose actual journals are listed. Two additional rows were marked No despite an exact journal identity. Seven valid journal aliases are included as controls. These 32 cases are frozen in `benchmarks/regressions/excel-identity.json`; `workbook-audit.csv` records the original results and reviewed labels. These are selected development regressions, not an estimate of workbook-wide error rate.

## Changes

- A unique complete structured journal name resolves locally before requesting the model. Normalization tolerates ETIS punctuation and connector damage but preserves word order and substantive words. Normalized collisions and conference/workshop names are left to the model. Absence of an exact match is not treated as a negative decision.
- This lookup resolves 294 rows in the supplied workbook, including all eight missed or misidentified exact journal names. It applies to both ETIS and BibTeX journal fields, not article-title or reference substrings.
- Prompt/schema version 8 emits the brief note first, then the verdict, canonical name, and opaque ID. The canonical name must be chosen before its ID. Existing strict ID/name validation remains.
- Batching, request-local memory, cancellation, and structural fallback remain. No candidate-verification calls or databases were added.

OpenAI documents that [structured outputs follow schema key order](https://developers.openai.com/api/docs/guides/structured-outputs). The hypothesis that selecting names before IDs reduces identity mistakes is an empirical mitigation, not a semantic guarantee.

## Final live validation

All runs used the configured Luna model and the existing catalogue. Each suite made two shuffled passes. The final accuracy runs overlapped in time, so timings below are observations rather than a controlled speed comparison.

| Suite | Pass 1 | Pass 2 | API requests | Individual fallbacks | Verification calls | Seconds per pass |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| [Excel regressions](final/regressions.json) | 32/32 | 32/32 | 4 + 4 | 0 | 0 | 26.6, 23.6 |
| [Venue policy cases](final/policy-cases.json) | 19/19 | 19/19 | 2 + 2 | 0 | 0 | 13.1, 14.9 |
| [Existing 100](final/existing100/run.json) | 100/100 | 98/100 | 11 + 11 | 2 | 0 | 66.9, 75.6 |
| [Additional 50](final/fresh50/run.json) | 49/50 | 50/50 | 14 + 5 | 9 | 0 | 131.4, 33.2 |

The broader sets score **297/300 repeated decisions** (198/200 existing, 99/100 additional), compared with 295/300 in the previous prompt-6 run. These are repeated evaluations on 150 publications, not 300 independent examples. The targeted Excel and policy suites are reported separately because they overlap the broader data and contain selected/synthetic cases.

## Remaining failures and latency

- Existing set, pass 2: row 67, IEEE Open Journal of Power Electronics, was incorrectly matched to IEEE Open Journal of the Communications Society. Row 1088, IEEE Conference on Decision and Control, was incorrectly rejected.
- Additional set, pass 1: row 76 repeats the same unlisted IEEE Open Journal of Power Electronics false positive.
- The first additional-set batch omitted one of its nine unresolved input IDs. Existing envelope validation correctly rejected the association and retried all nine items individually. That pass took 131.4 seconds versus 33.2 seconds for the other pass. This slowdown is structural fallback, not semantic candidate verification.
- Local exact matching guarantees the reported River Basin journal lookup for the supplied structured field. The fuzzy model path still makes errors; the successful targeted checks do not guarantee all future decisions.

## Preserved development attempt

Prompt 7 moved the note first but retained ID-before-name ordering. It scored 64/64 targeted decisions, 198/200 existing, and 98/100 additional decisions. Its failures prompted the final name-before-ID change; this is data-informed refinement. The initial artifacts remain at the root of this directory, with `matching-prompt7.py` preserving its source. The final results are under `final/`; no earlier predictions or labels were overwritten.

## Automated checks and use

`pytest -q`: **129 passed**. `ruff check .` and `ruff format --check .` passed. Tests cover exact River Basin lookup without API calls, punctuation tolerance, ambiguous normalized names, conference/title exclusions, and correct mixed local/model row export.

Restart Flask and process the original `sample_data/Publications.xlsx` to obtain a new export. `sample_data/Publications_result.xlsx` remains unchanged; its hash is recorded in `audit-source.json`. The whole workbook was not rerun against the API during this correction.
