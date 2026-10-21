# Single-request versus batching benchmark

Run status: **complete**. Model: `gpt-6-luna`. Started: 2026-10-18T16:57:54.447225+00:00.

## Protocol

100 original ETIS rows: 80 sampled without replacement (seed 20261018) and 20 deliberately difficult rows. Labels were manually authored by the Codex assistant before either method ran; they are not independently human-reviewed. The test contains 34 positive and 66 negative venue labels. Use the random subset to assess typical workbook performance; the combined score is deliberately enriched with difficult cases.

Catalogue snapshot: 2026-10-16T13:23:26.662250+00:00. Frozen labels: 2026-10-18T16:55:17.242008+00:00. Test-set SHA-256: `72050c7efa6acd21409dcf5378a449629e9a8ba717356d0fe4a68cf914f16fc4`.

Both methods use the same model, catalogue, matching rules, low reasoning effort, 45-second request timeout, and up to two SDK retries. Baseline invokes the production request and validation directly, bypassing SQLite. Batches contain 10 independent publications and receive 10 times the output-token ceiling. No gold labels or annotation rationales are sent. All requests are sequential with store=False.

The run schedules 2 paired passes. Odd passes run single then batch; even passes run batch then single. Each pass uses a new shuffle; each pair uses identical item order. Provider prompt caching stays enabled: cache state is not controlled, and these are not cold-cache comparisons. Timings include SDK retries, validation, and per-round checkpoint overhead, but exclude model-access preflight, annotation, startup, and report generation. Interrupted runs report active segments rather than uninterrupted wall time.

## Accuracy against original frozen annotations

Exact accuracy requires the correct catalogue ID or a correct no-match. Errors and unattempted items count against accuracy. Match precision/recall describe the binary listed/unlisted decision among valid responses; wrong venue IDs are counted separately. Service errors remain explicit, rather than being converted into nonmatches.

| Pass | Method | All exact | Random exact | Challenge exact | Precision | Recall | False + | False − | Wrong venue | Errors / missing |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | single | 98/100 | 78/80 | 20/20 | 94.4% | 100.0% | 2 | 0 | 0 | 0 / 0 |
| 1 | batch | 99/100 | 80/80 | 19/20 | 100.0% | 100.0% | 0 | 0 | 1 | 0 / 0 |
| 2 | batch | 99/100 | 79/80 | 20/20 | 97.1% | 100.0% | 1 | 0 | 0 | 0 / 0 |
| 2 | single | 98/100 | 78/80 | 20/20 | 97.1% | 100.0% | 1 | 0 | 0 | 1 / 0 |

### Documented annotation correction

Error review after predictions began identified a mistake in the original row-1141 annotation. HCI International **is** in the catalogue, and its official proceedings inventory includes the paper's Late Breaking Papers volume. The correct venue is HCI International. This is supported by the [conference proceedings inventory](https://2025.hci.international/proceedings.html) and the [Springer chapter](https://link.springer.com/chapter/10.1007/978-3-032-12660-3_9).

The original test set is preserved above. The separately versioned `testset-audited.json` applies the evidence-backed correction (35 positives, 65 negatives); no model requests were changed or rerun. This audit was informed by a disagreement, so corrected scores are explicitly post hoc. The following table uses the audited labels:

| Pass | Method | All exact | Random exact | Challenge exact | Precision | Recall | False + | False − | Wrong venue |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | single | 99/100 | 79/80 | 20/20 | 97.2% | 100.0% | 1 | 0 | 0 |
| 1 | batch | 98/100 | 79/80 | 19/20 | 100.0% | 97.1% | 0 | 1 | 1 |
| 2 | batch | 100/100 | 80/80 | 20/20 | 100.0% | 100.0% | 0 | 0 | 0 |
| 2 | single | 97/100 | 77/80 | 20/20 | 97.1% | 97.1% | 1 | 1 | 0 |

## Speed and tokens

| Pass | Method | Elapsed s | s/publication | Publications/min | Requests | Retries | Request median s | Request p95 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | single | 201.15 | 2.01 | 29.83 | 100 | 0 | 1.81 | 3.18 |
| 1 | batch | 49.31 | 0.49 | 121.69 | 10 | 0 | 4.70 | 5.92 |
| 2 | batch | 53.33 | 0.53 | 112.51 | 10 | 0 | 5.13 | 6.46 |
| 2 | single | 199.02 | 1.99 | 30.15 | 100 | 0 | 1.80 | 2.71 |

Pass 1: **4.08× speedup** from batching.

Pass 2: **3.73× speedup** from batching.

| Pass | Method | Input tokens | Cached input | Cache writes | Output | Reasoning (part of output) | Missing usage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | single | 11,178,262 | 11,051,172 | 126,790 | 6,704 | 1,750 | 0 |
| 1 | batch | 1,133,492 | 1,005,606 | 127,856 | 4,455 | 368 | 0 |
| 2 | batch | 1,133,492 | 1,117,340 | 16,122 | 4,594 | 437 | 0 |
| 2 | single | 11,178,262 | 11,177,962 | 0 | 6,464 | 1,597 | 0 |

Token counts are provider-reported usage for returned responses. Failed attempts without usage cannot be assigned a token cost. Prices are not inferred from token totals; caching and account-specific pricing affect actual charges.

## Error analysis (audited labels when available)

| Item / subset | Annotated venue | single pass 1 | batch pass 1 | batch pass 2 | single pass 2 | Rationale |
| --- | --- | --- | --- | --- | --- | --- |
| etis-0063 / random | No match | Journal of Materials Research and Technology | No match | No match | Journal of Manufacturing Systems | JMST DOI and title identify this journal despite the singular Material spelling; absent from the catalogue, unlike Materials Research and Technology. |
| etis-0132 / random | No match | No match | No match | No match | ERROR | Riga Technical University's power and electrical engineering conference is absent. |
| etis-0494 / challenge | IEEE Transactions on Smart Grids | IEEE Transactions on Smart Grids | IEEE Transactions on Sustainable Energy | IEEE Transactions on Smart Grids | IEEE Transactions on Smart Grids | Scholar snapshot adds a plural s to the official IEEE journal title; identity remains the same. |
| etis-1141 / random | HCI International | HCI International | No match | HCI International | No match | The original annotation missed the HCI International catalogue entry and overgeneralized the companion-proceedings exclusion. The official conference proceedings inventory includes LNCS 16333 (Late Breaking Papers, Part III) as part of the HCII 2025 proceedings. Springer identifies this chapter in that volume. This provides clear venue-identity evidence; it is not an ACM CHI paper. |

### Rejected responses

These failed requests remain errors in accuracy and throughput metrics; they were not silently retried as new model predictions.

| Pass / method | Items | Failure | Model output |
| --- | --- | --- | --- |
| 2 / single | etis-0132 | ValueError | {"matched":true,"venue_id":"8f1629b59a9bc?","note":"The reference names the IEEE International Scientific Conference on Power and Electrical Engineering of Riga Technical University (RTUCON), which is not listed in the catalogue."} |

### Policy sensitivity and order stability

Row 967 is an EACL System Demonstrations paper. The frozen annotation applies the app's conservative companion-proceedings rule and returns no match. Scholar's aggregation of that track has not been verified. The main EACL venue is listed; human review of this policy is warranted. Accuracy excluding this item:

- single pass 1: 98/99.
- batch pass 1: 97/99.
- batch pass 2: 99/99.
- single pass 2: 96/99.

single: 3 labels changed between passes (etis-0063, etis-0132, etis-1141).

batch: 2 labels changed between passes (etis-0494, etis-1141).

## Recommendation

Across both methods' completed passes, batching took 102.6s versus 400.2s for single requests: **3.90× faster**. Audited exact scores were **198/200 batched** and **196/200 single**. These totals contain repeated predictions on the same publications.

Batching merits a follow-up integration trial if this speed advantage is useful, but aggregate accuracy alone does not establish equivalent reliability. Review false positives, wrong IDs, and order-sensitive cases above before changing the production default. In particular, a syntactically valid catalogue ID can contradict the venue named in the model's explanation. A useful next experiment is to require both canonical venue name and ID, validate their agreement, and retry inconsistent items individually. That safeguard has not been tested here.

## Interpretation limits

These are 2 passes over the same 100 publications, not 200 independent test examples. Model randomness, server load, and cache state can affect both speed and labels. Order changes also change batch composition, so this experiment cannot attribute an individual change exclusively to batching. The benchmark tests matching against the bundled catalogue, not completeness of Scholar collection or the authenticity/publication status of each ETIS reference.

The production application is unchanged. Review item-level errors and any false positives before adopting batching; this small evaluation does not establish statistical equivalence of accuracy.

Artifacts: `predictions.csv` contains all attempted item-level decisions and notes; `summary.json` contains metrics; `run.json` contains request timings, usage, outputs, ordering, configuration, and reproducibility hashes.
