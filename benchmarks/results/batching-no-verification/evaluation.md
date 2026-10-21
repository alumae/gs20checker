# Current system accuracy benchmark

Model: `gpt-6-luna`. Full-catalogue batches of ten; candidate verification disabled.

## Results

| Set | Pass | Correct | False positives | False negatives | Wrong venue | Errors | Matching seconds | API requests |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| existing | 1 | 98/100 | 1 | 1 | 0 | 0 | 64.48 | 10 |
| existing | 2 | 99/100 | 0 | 1 | 0 | 0 | 62.84 | 10 |
| fresh | 1 | 50/50 | 0 | 0 | 0 | 0 | 34.07 | 6 |
| fresh | 2 | 49/50 | 1 | 0 | 0 | 0 | 35.15 | 7 |

Original set: **197/200 (98.5%)**. Additional 50-item set: **99/100 (99%)**. Together: **296/300 repeated decisions (98.7%)**.

Malformed-output fallbacks: 3 (0 original set; 3 fresh set). No semantic verification calls occurred. Result errors: 0. The original 100-item suite passed its configured 196/200 threshold.

## LREC regression

Single citation: **5/5**. Original workbook batch: **5/5**. These checks are separate from the accuracy totals.

## Disagreements

- existing, pass 1, etis-0063: expected **no match**, returned **Journal of Materials Research and Technology**. The reference identifies the journal as Journal of Materials Science and Technology; this is the catalogue’s corresponding venue entry.
- existing, pass 1, etis-1141: expected **HCI International**, returned **no match**. The cited venue is HCI International 2025 – Late Breaking Papers, a distinct proceedings volume; the catalogue's HCI International entry does not establish this volume as the main conference proceedings.
- existing, pass 2, etis-1141: expected **HCI International**, returned **no match**. The reference specifies HCI International 2025 Late Breaking Papers, a proceedings volume not clearly equivalent to the catalogue's HCI International venue.
- fresh, pass 2, etis-0270: expected **no match**, returned **Additive Manufacturing**. No catalogue entry for Materials & Design; the journal is not the listed Additive Manufacturing venue.

The Materials & Design false positive contradicts its own explanation: the note says the journal is not listed, but the structured result selects Additive Manufacturing. Canonical name/ID validation cannot reject this semantic inconsistency.

## Interpretation and reproduction

Two shuffled passes over 100 previously audited items and 50 separately frozen items. These are 150 distinct publications, not 300 independent samples. Labels were authored by the Codex assistant and are not independently human-reviewed. The earlier audit corrected the HCI label; original labels are preserved.

The two sets run separately through the production streaming processor, including request-local deduplication, batching, validation, cancellation support and in-memory XLSX export. Matching times exclude export and browser transfer. Runs were sequential. Provider caching and server load are uncontrolled. The earlier embedding benchmark mixed all 150 publications, so its batch compositions differ from this evaluation.

No prompts, labels, or application code were changed during this benchmark. Result files preserve model outputs, request timings/usage, item order, and source hashes.

Commands (use new output paths to avoid overwriting historical results):

```bash
python -m benchmarks.streaming --output-dir benchmarks/results/batching-no-verification
PYTHONPATH=. python benchmarks/results/batching-no-verification/fresh_runner.py
python -m benchmarks.regressions --output benchmarks/results/batching-no-verification/lrec.json
PYTHONPATH=. python benchmarks/results/batching-no-verification/summarize.py
```

Details: [original set report](report.md), [fresh set outputs](fresh50.json), [LREC outputs](lrec.json), [all predictions](predictions.csv).
