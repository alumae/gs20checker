# Embedding shortlist benchmark

Status: **complete**. Model: `gpt-6-luna`. Embeddings: `text-embedding-3-small`, 1536 dimensions.

## Protocol

The existing audited 100-item set (35 positive) is development data. The fresh seeded 50-item holdout (11 positive) was annotated by the Codex assistant against the catalogue before predictions; it has not been independently human-reviewed. Two passes reuse the same items; totals are repeated decisions, not independent samples.

Four arms run sequentially in batches of ten. Each pass shuffles all 150 items once; all arms share that order and batch composition. The second pass reverses arm order. Production uses the current AsyncMatcher, including selective verification. Lexical uses IDF-weighted token overlap with exact-name/acronym priority, capped at 20. Dense uses cosine similarity; hybrid unions dense results with exact names/acronyms without truncating the union.

Catalogue vectors contain venue names, parenthetical acronyms and known types, never categories or ranks. Queries combine populated journal/conference/proceedings fields, falling back to the reference. The LLM sees original fields and each item’s own shortlist. IDs and canonical names are validated per item; invalid output receives at most one individual retry with the same shortlist. There is no full-catalogue fallback.

K = **10**, selected using positive recall on the existing set only. The smallest of 5/10/20 covering every positive is chosen for each embedding arm; the shared K is the larger requirement. If recall is incomplete at 20, K remains 20 and misses are reported. Prompts and K are not tuned on fresh predictions.

Timings include query embedding calls, retrieval, matching, validation and SDK retries. Each arm/pass has a new client and no local query/result cache; duplicate query strings are embedded once per simulated upload. Catalogue indexing and recall calibration are excluded and reported separately. This is matcher throughput, excluding XLSX parsing/export and browser transfer. Provider caching and load are uncontrolled.

## Positive retrieval recall

| Set | Retrieval | K | Hits / positives | Misses |
| --- | --- | --- | --- | --- |
| existing | dense | 5 | 33/35 | etis-0223, etis-1141 |
| existing | dense | 10 | 35/35 | — |
| existing | dense | 20 | 35/35 | — |
| existing | hybrid | 5 | 35/35 | — |
| existing | hybrid | 10 | 35/35 | — |
| existing | hybrid | 20 | 35/35 | — |
| existing | lexical | 5 | 35/35 | — |
| existing | lexical | 10 | 35/35 | — |
| existing | lexical | 20 | 35/35 | — |
| fresh | dense | 5 | 11/11 | — |
| fresh | dense | 10 | 11/11 | — |
| fresh | dense | 20 | 11/11 | — |
| fresh | hybrid | 5 | 11/11 | — |
| fresh | hybrid | 10 | 11/11 | — |
| fresh | hybrid | 20 | 11/11 | — |
| fresh | lexical | 5 | 11/11 | — |
| fresh | lexical | 10 | 11/11 | — |
| fresh | lexical | 20 | 11/11 | — |

## Accuracy and speed

| Pass | Method | Existing exact | Fresh exact | FP / FN / wrong ID / errors | Seconds (150 items) | API calls | Fallbacks |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | production | 98/100 | 50/50 | 0 / 2 / 0 / 0 | 302.81 | 115 | 20 |
| 1 | lexical | 93/100 | 49/50 | 0 / 8 / 0 / 0 | 97.61 | 15 | 0 |
| 1 | dense | 93/100 | 47/50 | 1 / 9 / 0 / 0 | 100.46 | 17 | 0 |
| 1 | hybrid | 97/100 | 49/50 | 1 / 3 / 0 / 0 | 94.11 | 17 | 0 |
| 2 | hybrid | 96/100 | 50/50 | 0 / 4 / 0 / 0 | 94.08 | 17 | 0 |
| 2 | dense | 95/100 | 50/50 | 0 / 5 / 0 / 0 | 90.39 | 17 | 0 |
| 2 | lexical | 96/100 | 50/50 | 0 / 4 / 0 / 0 | 89.72 | 15 | 0 |
| 2 | production | 99/100 | 50/50 | 0 / 1 / 0 / 0 | 272.57 | 95 | 0 |

## Usage

| Pass | Method | Input | Cached input | Output | Embedding tokens | HTTP attempts |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | production | 3986865 | 3686088 | 14230 | 0 | 115 |
| 1 | lexical | 154634 | 0 | 8018 | 0 | 15 |
| 1 | dense | 95611 | 0 | 8083 | 2537 | 17 |
| 1 | hybrid | 99597 | 0 | 8412 | 2537 | 17 |
| 2 | hybrid | 99575 | 0 | 8233 | 2537 | 17 |
| 2 | dense | 95611 | 0 | 8014 | 2537 | 17 |
| 2 | lexical | 154634 | 0 | 8212 | 0 | 15 |
| 2 | production | 1750659 | 1676220 | 13896 | 0 | 95 |

Catalogue index: 62.59s, cache hit: False, 37 embedding requests, 31962 embedding tokens. Float32 vector data: 27.3 MiB before compression. Index fingerprint: `054041424ddc93a9ad2592d49dfdad718a44b808ee26dcf5455d369291bb6a9f`.

## Disagreements

- Pass 1 production, etis-0494 (challenge, llm): expected IEEE Transactions on Smart Grids; returned no match/error. The supplied journal field is “IEEE Transactions on Smart Grid,” while the shortlisted journal is “IEEE Transactions on Smart Grids.” These are distinct title strings, and the reference does not establish that they are the same venue.
- Pass 1 production, etis-1141 (random, llm): expected HCI International; returned no match/error. The reference identifies the publication as the distinct HCI International 2025 Late Breaking Papers proceedings, not the main HCI International conference. The shortlisted candidate is HCI International without a Late Breaking Papers track, so the venue identity does not match.
- Pass 1 lexical, etis-1106 (challenge, llm): expected Computer Speech & Language; returned no match/error. The journal is Computer Speech & Language, absent from this publication's candidates; the supplied spelling variation does not identify any listed venue.
- Pass 1 lexical, etis-0165 (random, llm): expected Internet Policy Review; returned no match/error. Internet Policy Review is explicitly the journal, but the corresponding candidate is not listed; no other candidate is an equivalent venue.
- Pass 1 lexical, etis-0494 (challenge, llm): expected IEEE Transactions on Smart Grids; returned no match/error. The cited journal is IEEE Transactions on Smart Grid, while the candidate is IEEE Transactions on Smart Grids; the titles differ and are not established as the same venue.
- Pass 1 lexical, etis-0157 (random, llm): expected Biomass and Bioenergy; returned no match/error. The reference identifies Biomass and Bioenergy; that journal is not among the candidates.
- Pass 1 lexical, etis-0501 (fresh, llm): expected Energy and Buildings; returned no match/error. The journal field identifies Energy and Buildings, but that venue is not included in this item's candidates.
- Pass 1 lexical, etis-0160 (random, llm): expected Ocean Modelling; returned no match/error. The journal field identifies Ocean Modelling, but that venue is not included in this item's candidates.
- Pass 1 lexical, etis-1141 (random, llm): expected HCI International; returned no match/error. This is in the HCI International 2025 Late Breaking Papers proceedings, a distinct late-breaking-paper publication; no candidate explicitly identifies that proceedings venue.
- Pass 1 lexical, etis-0223 (challenge, llm): expected Computer Human Interaction (CHI); returned no match/error. The reference identifies the CHI 2026 conference, but the shortlist has no clearly matching CHI conference candidate.
- Pass 1 dense, etis-1106 (challenge, llm): expected Computer Speech & Language; returned no match/error. The cited journal is Computer Speech & Language; no candidate names that venue.
- Pass 1 dense, etis-0494 (challenge, llm): expected IEEE Transactions on Smart Grids; returned no match/error. The supplied journal is “IEEE Transactions on Smart Grid,” while the reference says “IEEE Transactions on Smart Grid” only in neither field: it gives “IEEE Transactions on Smart Grid” as a candidate but the journal field is “IEEE Transactions on Smart Grid”? Actually the supplied journal is “IEEE Transactions on Smart Grid” — candidate says “IEEE Transactions on Smart Grids,” so the titles are not identical.
- Pass 1 dense, etis-0157 (random, llm): expected Biomass and Bioenergy; returned no match/error. The reference identifies Biomass & Bioenergy; none of the candidates is that journal. Biomass and Bioenergy is close, but the supplied venue title uses an ampersand, not “and”.
- Pass 1 dense, etis-0676 (random, llm): expected Scientific Reports; returned no match/error. The reference identifies Scientific Reports, but its candidate is marked as unknown type; the supplied fields do not establish whether it is the same publication venue.
- Pass 1 dense, etis-0526 (random, llm): expected Scientific Reports; returned no match/error. The reference identifies Scientific Reports, but its candidate is marked as unknown type; the supplied fields do not establish whether it is the same publication venue.
- Pass 1 dense, etis-0108 (fresh, llm): expected Atmosphere; returned no match/error. The reference identifies Atmosphere, but its candidate is marked as unknown type; the supplied fields do not establish whether it is the same publication venue.
- Pass 1 dense, etis-1141 (random, llm): expected HCI International; returned no match/error. The publication is HCI International 2025 Late Breaking Papers, a distinct proceedings volume; the HCI International candidate is not clearly the same publication venue.
- Pass 1 dense, etis-0722 (fresh, llm): expected IEEE Transactions on Energy Conversion; returned no match/error. The journal is IEEE Transactions on Energy Conversion, but its candidate is marked unknown type and does not provide clear evidence to verify identity as the publication venue.
- Pass 1 dense, etis-0213 (fresh, llm): expected IEEE Access; returned no match/error. The journal field explicitly names IEEE Access, but the candidate's type is unknown, so venue identity cannot be verified from the supplied evidence.
- Pass 1 dense, etis-0967 (challenge, llm): expected no match; returned Conference on Empirical Methods in Natural Language Processing: System Demonstrations. The reference explicitly says Proceedings of System Demonstrations; this is the demonstrations track, not the main EACL conference.
- Pass 1 hybrid, etis-0494 (challenge, llm): expected IEEE Transactions on Smart Grids; returned no match/error. The supplied journal field says “IEEE Transactions on Smart Grid,” while the shortlist candidate is “IEEE Transactions on Smart Grids.” The titles differ, and the reference repeats the singular form, so venue identity is not clear enough to match.
- Pass 1 hybrid, etis-0480 (fresh, llm): expected no match; returned USENIX Annual Technical Conference. The supplied conference and publication title explicitly identify the IEEE Green Technologies Conference (GreenTech), not the shortlisted USENIX Annual Technical Conference; no matching candidate is provided.
- Pass 1 hybrid, etis-1141 (random, llm): expected HCI International; returned no match/error. The publication is an HCI International 2025 Late Breaking Papers proceedings volume. HCI International is a plausible candidate, but the cited late-breaking proceedings identity does not clearly establish it as the same listed venue.
- Pass 1 hybrid, etis-0130 (random, llm): expected IEEE Access; returned no match/error. The reference identifies IEEE Access, but its candidate has unknown venue type; there is no type evidence here to verify the identity as a journal.
- Pass 2 hybrid, etis-0494 (challenge, llm): expected IEEE Transactions on Smart Grids; returned no match/error. The reference names IEEE Transactions on Smart Grid; the candidate IEEE Transactions on Smart Grids has a different title, and the supplied fields do not establish them as the same venue.
- Pass 2 hybrid, etis-0223 (challenge, llm): expected Computer Human Interaction (CHI); returned no match/error. The publication title identifies the Conference on Human Factors in Computing Systems (CHI ’26), but the candidate Computer Human Interaction (CHI) is not a clearly equivalent venue identity; no matching candidate is established.
- Pass 2 hybrid, etis-1141 (random, llm): expected HCI International; returned no match/error. The publication is in HCI International 2025 Late Breaking Papers, a distinct late-breaking proceedings volume; the HCI International candidate does not clearly identify this specific publication venue.
- Pass 2 hybrid, etis-1051 (random, llm): expected Quaternary Science Reviews; returned no match/error. The reference identifies Quaternary Science Reviews, which is not among this publication’s candidates.
- Pass 2 dense, etis-0494 (challenge, llm): expected IEEE Transactions on Smart Grids; returned no match/error. The supplied journal is IEEE Transactions on Smart Grid; the candidate IEEE Transactions on Smart Grids is not the same journal title.
- Pass 2 dense, etis-0223 (challenge, llm): expected Computer Human Interaction (CHI); returned no match/error. The publication title and reference identify the Conference on Human Factors in Computing Systems (CHI ’26). The CHI candidate is an ambiguous short-form name, while the supplied full conference name is not listed; identity is not clear enough to match.
- Pass 2 dense, etis-0157 (random, llm): expected Biomass and Bioenergy; returned no match/error. The journal field and reference indicate Biomass and Bioenergy, but no candidate has that exact venue identity; the shortlist's similar names are distinct.
- Pass 2 dense, etis-1141 (random, llm): expected HCI International; returned no match/error. The publication is in HCI International 2025 Late Breaking Papers, a distinct late-breaking-papers proceeding; the candidates do not identify that venue.
- Pass 2 dense, etis-1051 (random, llm): expected Quaternary Science Reviews; returned no match/error. The journal is Quaternary Science Reviews, but the candidate list does not contain that venue; Quaternary International is a distinct journal.
- Pass 2 lexical, etis-0494 (challenge, llm): expected IEEE Transactions on Smart Grids; returned no match/error. The cited journal is IEEE Transactions on Smart Grid; the candidate IEEE Transactions on Smart Grids has a different title.
- Pass 2 lexical, etis-0223 (challenge, llm): expected Computer Human Interaction (CHI); returned no match/error. The reference identifies the main Conference on Human Factors in Computing Systems (CHI '26). The candidate Computer Human Interaction (CHI) is not clearly the same full venue identity, so no match is established.
- Pass 2 lexical, etis-1141 (random, llm): expected HCI International; returned no match/error. The reference names HCI International 2025 Late Breaking Papers proceedings. The HCI International candidate is not clearly the same publication venue or proceedings track.
- Pass 2 lexical, etis-1106 (challenge, llm): expected Computer Speech & Language; returned no match/error. The reference identifies Computer Speech & Language; that exact journal is not among this item's candidates.
- Pass 2 production, etis-1141 (random, llm): expected HCI International; returned no match/error. The reference identifies a distinct HCI International 2025 Late Breaking Papers proceedings volume, not the main HCI International conference proceedings. None of the shortlisted venues explicitly identifies the Late Breaking Papers track or proceedings.

LREC regression (hybrid): **10/10**, five plain-reference single checks and five checks in the original workbook batch.

## Decision

Best embedding arm: **hybrid**, 3.06× faster than the contemporaneous production baseline. Existing: 193/200; fresh: 99/100 (baseline 100/100).

Migration gate: **FAIL**. Requires faster processing, at least 197/200 existing decisions, fresh accuracy at least the contemporaneous baseline, and LREC 10/10. Gate results: {"faster": true, "existing_197": false, "fresh_at_least_baseline": false, "lrec_10": true}.

Keep production unchanged; the measured embedding approach has not met the agreed migration criteria.

## Reproducibility and limits

Run `python -m benchmarks.embeddings --output-dir benchmarks/results/embeddings-new`. NumPy is a development dependency. Frozen labels are in `benchmarks/fresh50.json`; selection and manually authored annotations are in `benchmarks/build_fresh.py`. Run artifacts include source/data hashes, per-request output/usage/latency, candidate lists, predictions and errors. Catalogue vectors are cached only in ignored `benchmarks/embedding_cache/`; no SQL database is used.

This is a small, mostly negative holdout from one workbook. It tests venue identity against the bundled catalogue, not catalogue completeness or reference authenticity. Existing labels include a documented earlier post-prediction audit. The best embedding arm is selected by existing-set accuracy then latency; fresh labels never select K, prompts or the winner. Report uncertainty rather than treating these results as statistical equivalence.

Production application code is unchanged. Embeddings API reference: https://developers.openai.com/api/docs/guides/embeddings
