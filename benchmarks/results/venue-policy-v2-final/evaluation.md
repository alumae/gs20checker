# Companion-track and ETIS punctuation evaluation

Final application prompt: **6**. Venue policy: **2**. Batches of ten; no candidate verification.

## Policy and annotation changes

Official companion proceedings and Demo, Challenge, Findings, and Late Breaking tracks count as the parent conference. Workshops remain separate; a listed workshop may match its own entry. Missing punctuation, ampersands/and, spacing and damaged entity fragments are tolerated when the venue identity is clear. Different substantive journal names remain distinct. Canonical output IDs and names remain exact.

The versioned policy overlay relabels ETIS row 967 (EACL System Demonstrations) as main EACL. The earlier audit already labels HCI Late Breaking Papers positively. Existing labels already accept missing ampersands in listed journals. Absent journals such as Materials & Design remain unmatched. Original annotations and historical reports were not overwritten.

## Final live benchmark

| Set | Pass 1 | Pass 2 | Combined | Prior predictions rescored under policy 2 | Mean matching seconds |
| --- | --- | --- | --- | --- | --- |
| Original 100 | 98/100 | 99/100 | 197/200 | 195/200 | 112.80 |
| Additional 50 | 50/50 | 48/50 | 98/100 | 99/100 | 56.00 |

Two passes reuse the same 150 publications: 300 decisions are not 300 independent samples. All results are development evaluations; labels are assistant-authored, not independently human-reviewed. Old predictions were rescored, not rerun. Timing differences across runs also reflect provider load and cache state.

## Focused policy regressions

- single: **19/19**; zero verification calls.
- batch: **18/19**; zero verification calls.

These 19 targeted cases include EACL Demo/Challenge/Findings/Companion tracks, HCI late breaking, unlisted workshops (including one in a companion volume), the listed SLT workshop, six punctuation variants, two absent journals, a challenge mentioned only in a paper title, and two LREC references. Synthetic references are explicitly marked. They are not an independent accuracy sample.

## Remaining errors

- Original 100, pass 1, etis-1028: expected Journal of Paleontology; returned no match/error. Journal of Paleontology is not listed in the catalogue.
- Original 100, pass 1, etis-0157: expected Biomass and Bioenergy; returned no match/error. Biomass & Bioenergy is not listed; the catalogue entry Biomass and Bioenergy is a different journal title.
- Original 100, pass 2, etis-1088: expected IEEE Conference on Decision and Control; returned no match/error. IEEE Conference on Decision and Control is not listed under that name; the catalogue entry is American Control Conference, a different venue.
- Additional 50, pass 2, etis-0890: expected no match; returned Journal of Agricultural and Food Chemistry. The journal is Journal of Chemical & Engineering Data; that journal is not listed. Correction? No exact entry found.
- Additional 50, pass 2, etis-0515: expected no match; returned International Economics. The publication identifies International Economics and Economic Policy, which is distinct from the catalogue's International Economics.

The rules are explicit, but Luna still makes occasional errors: it rejected one Biomass & Bioenergy reference despite the punctuation rule and returned two false positives whose explanations indicated different/unlisted journals. No additional verification requests or heuristic rewriting of model decisions were introduced.

## Development history and validation

The initial prompt-5 run is preserved in `../venue-policy-v2/`: 196/200 original, 95/100 additional, and 19/19 in each focused mode. It exposed contradictory decision fields and explanations. Prompt 6 adds an explicit no-match/null example and consistency instruction, without changing evaluation labels. The final results above are a rerun after this data-informed prompt revision, not an untouched holdout test.

Validation: 115 pytest tests passed; JavaScript stream tests passed; Ruff checks passed. Artifact checks confirmed source hashes, complete item coverage, and zero verification calls. No catalogue or original workbook data changed.

Details: [original set](report.md), [additional set](fresh/report.md), [focused cases](policy-cases.md), [predictions](predictions.csv).
