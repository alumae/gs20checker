# Scholar20

A small Flask application that checks whether a publication's venue appears in the
top 20 of any English Google Scholar Metrics category or subcategory. Paste one
BibTeX entry/free-form reference, or enrich an ETIS Excel export.

## Current status

The local application includes a validated catalogue of **4,652 venues across 306
English categories and subcategories**, collected from Scholar on 16 October 2026.
Scholar's official methodology page identifies the edition as July 2025, covering
publications from 2020–2024. The snapshot is stored in `data/venues.json`.

An OpenAI API key is required for real matching. Automated matching tests use
synthetic rankings and mocked model responses; collector regression tests also use
navigation and table HTML extracted from live Scholar pages. These test fixtures
are never loaded by the application. A missing or invalid catalogue produces an
explicit setup message and HTTP 503 rather than a misleading nonmatch.

## Local development

Use Python 3.12 in the existing conda environment:

```bash
conda activate flask
python -m pip install -r requirements-dev.txt
cp .env.example .env
# Set OPENAI_API_KEY in .env. A validated catalogue is already bundled.
flask --app app run --debug --with-threads
```

Open http://127.0.0.1:5000. The Flask CLI loads `.env` using python-dotenv.
`create_app()` reads environment variables; callers outside the CLI must load their
own environment. Keep debug mode local.

For deployment, push the repository to GitHub and import it in Vercel's dashboard.
Use the repository root, the Flask preset, and the committed `vercel.json` settings.
Follow [DEPLOYMENT.md](DEPLOYMENT.md) for the first import, environment variables,
preview validation, and public API rate limits; no Vercel CLI is required.
`python build.py` validates the bundled catalogue and
copies assets to `public/static/`; ordinary local Flask development needs no build.

If matching reports that OpenAI rejected the API key, replace `OPENAI_API_KEY`
locally and restart Flask. An existing shell environment variable takes precedence
over `.env`; update it or run `unset OPENAI_API_KEY` before restarting to use the
file's value. Authentication failures cannot be resolved by retrying a reference.
Server logs record the failure type and HTTP status without provider payloads,
credentials, or publication references.

| Setting | Default / purpose |
| --- | --- |
| `OPENAI_API_KEY` | Required server-side API key; never sent to the browser |
| `OPENAI_MODEL` | `gpt-6-luna` |
| `GS_CATALOGUE` | `data/venues.json`, relative to the repository by default |

Each uploaded workbook is processed in one streaming request, using batches of ten
publications. Progress updates arrive after each batch. Independent uploads and
single-reference checks run concurrently; batches within one upload are sequential.
Keep the page open. Cancel, refresh, or close it to discard processing and results.
There is no pause, resume, cross-request cache, or partial download. A completed
workbook is held as a download Blob in browser memory until you leave or start again.

## Streaming API and cancellation

- `POST /api/check`: a single reference; returns the existing JSON match result.
- `POST /api/workbooks/process`: multipart `file`; returns `application/x-ndjson`.
  Events are `started`, `progress`, `heartbeat`, `file_chunk`, `complete`, and `error`.
  Progress includes counts and recent rows. File chunks are base64-encoded; only a
  `complete` event confirms the finished XLSX. Validate its byte count before download.
- Invalid uploads receive ordinary JSON HTTP errors before streaming starts. Provider
  errors after streaming starts produce a terminal `error` event, without a download.
  Stream termination without `complete` also means failure; upload again to retry.
- The old `/api/jobs` endpoints are removed. No upload identifier or server download
  endpoint exists.

The server sends heartbeats every two seconds while waiting for OpenAI. When the WSGI
server detects a closed connection, it closes the response iterator, cancels the
outstanding async API operation (including retry waits), and releases request data.
An already accepted OpenAI call may still complete and incur a charge. Disconnect
detection depends on the server/network; workbook parsing and serialization are
synchronous bounded steps, so cancellation is observed after those steps finish.

Use a threaded WSGI server with enough workers/threads for simultaneous streams.
Disable proxy response buffering and allow sufficiently long request timeouts for
large sheets. `X-Accel-Buffering: no` is sent, but intermediaries must honor it.
The development command above enables threads. Avoid middleware that buffers the
entire response. Vercel proxy behavior must pass the preview checks in
[DEPLOYMENT.md](DEPLOYMENT.md) before production promotion.

## Build the venue catalogue

Run from a network where Scholar Metrics is accessible:

```bash
python -m app.collector --output data/venues.json
```

The collector follows the English root page's research-area and subcategory links,
extracts ranks 1–20, deduplicates venue names, and retains all memberships. It stores
source HTML in ignored `data/scholar-pages/`. Requests are spaced three seconds apart;
HTTP failures and challenge pages stop collection without replacing the previous
snapshot. Do not bypass Scholar access challenges.

Alternatively, save the original Scholar HTML in a directory and import it:

```bash
python -m app.collector --pages data/scholar-pages --output data/venues.json
```

The import expects `root.html` for
<https://scholar.google.com/citations?view_op=top_venues&hl=en>, and `<vq>.html` for
each linked page, e.g. `eng.html` and `eng_artificialintelligence.html`. Preserve the
complete HTML, including category navigation. Missing pages cause an explicit error.
The saved pages must belong to the same Scholar edition. Use `--edition "LABEL"`
only when you have verified that edition; retrieval time is recorded separately.

Validation requires all eight broad areas, subcategory navigation for each, every
discovered category, unique venue identities, and ranks 1–20 in each category.
The parser deliberately fails closed if Scholar changes its markup. Review the
discovered category inventory and source pages when refreshing; software validation
cannot detect links that Scholar has removed from the source HTML itself.

After a successful collection, review and commit `data/venues.json`, then restart
the app. Each request uses one fixed catalogue snapshot; restarting cancels active uploads.

## Matching and Excel output

Complete structured journal names are first looked up locally in the catalogue,
ignoring case, punctuation, spacing, and `&` / `and` / missing connectors. A unique
whole-name match needs no API call. Word order and substantive words are preserved;
collisions, abbreviations, conference names, and unknown names continue to the model.
This applies to ETIS journal fields and BibTeX journal fields, not substrings of paper
titles or free-form references. A missing exact match does not mean the venue is absent.

The model receives every catalogue venue's ID and name in a stable developer-message
prefix, followed by up to ten independently identified unresolved publications. Rankings and
source links stay server-side. OpenAI prompt caching can reuse the prefix; cache hits
are provider-controlled. Identical references within one upload share an in-memory
result, discarded at request completion. Single checks and separate uploads never
share result caches.

Strict JSON output contains `note`, `matched`, `venue_name`, and `venue_id`, plus an
input ID for batched results. The name must exactly match the catalogue entry for the
ID; both must be null for an unmatched result. Missing/duplicate/unknown input IDs
invalidate batch association. Invalid individual outputs get one single-publication
retry; an unusable batch envelope retries its items individually. Still-invalid
outputs become explicit Error rows. Provider failures after the SDK's normal retries
stop the upload, without triggering individual fallback or continuing to spend on
later batches. Names, categories and ranks in downloads come from the catalogue.
Uncertain identities return **No match**. This checks snapshot membership, not an
article's quality, authenticity, or ranking in its publication year.

The schema emits the brief venue-identity explanation first, then the verdict and
canonical venue name, then its opaque ID. This addresses observed results whose
positive verdict contradicted a later negative explanation, or whose copied ID led
to an unrelated name. Structured output still cannot guarantee semantic accuracy;
local exact matching removes model uncertainty for identifiable full journal names.

Official companion proceedings and tracks—including Demo/System Demonstrations,
Challenge, Findings, and Late Breaking Papers—count as their parent conference.
Prefer the main conference's catalogue entry when listed; otherwise an explicitly
listed track can match its own entry. Workshops remain separate, even inside a
companion volume: they match only if the workshop itself is listed. A challenge
mentioned only in a paper title does not change its publication venue.

ETIS references may lose special characters or contain damaged HTML entities.
Missing punctuation, extra spaces, and `&` / `and` / a missing connector are tolerated
when the remaining venue identity is clear. For example, `Computer Speech  Language`
can match `Computer Speech & Language`. Substantive differences such as Science versus
Research still distinguish journals. Returned venue names and IDs remain exact
catalogue values; exported source cells are not rewritten.

Unresolved single checks and workbook batches use the full catalogue directly, without a
follow-up candidate-verification step or embedding shortlist. A valid batch normally
uses one model request for up to ten publications; individual retries occur only
for invalid output, as described above. Valid match and no-match decisions are accepted
without additional model calls.

Candidate verification remains available only as an explicit Python opt-in for
historical experiments (`verify_candidates=True`). The web app does not enable it.
The earlier LREC regression and verification reports are retained as historical
results; their accuracy measurements do not describe the current unverified workflow.

ETIS sheets are identified by the `Lühikirje` header in row 1. The reference is
supplemented with journal, conference, publication title, paper title, and year.
Abstracts and unrelated fields are excluded from model requests. Files are limited
to 10 MB locally or 4 MB on Vercel, 5,000 nonempty publication rows, and 100 MB expanded
ZIP contents. Hosted requests have a 29-minute application deadline and a 4 MB total
streamed-response budget, including progress, base64 download chunks, and completion.
Timeouts cancel active matching; oversized exports are rejected before file chunks
are sent. Either failure asks the user to split the workbook and retry. The 5,000-row
validation limit does not guarantee that every workbook finishes within the deadline.

Downloads retain original sheets and rows and append:

| Column | Meaning |
| --- | --- |
| `GS Match` | Yes, No, or Error |
| `GS Venue` | Canonical Scholar venue name |
| `GS Category` | All matching category paths, one per line |
| `GS Rank` | Corresponding ranks in the same line order |
| `GS Note` | Match explanation or processing error |
| `GS Snapshot` | Catalogue retrieval timestamp |

Blank rows remain blank. Original formulas and ordinary formatting are retained;
advanced Excel features unsupported by openpyxl are not guaranteed. Already-enriched
workbooks are rejected to avoid silently overwriting previous GS results.

## Tests and checks

```bash
pytest
ruff check .
ruff format --check .
node --check app/static/app.js
node --check app/static/stream.js
node tests/test_stream.cjs
```

Tests cover catalogue validation, strict batch identities, upload-local deduplication,
concurrent requests, cancellation, disk-free uploads/export, API failures, stream
parsing, fallback behavior, and the complete supplied
1,161-row workbook with mocked responses. They make no paid API calls. For a live smoke
test, configure a key and catalogue and check a few known venue abbreviations and
negative examples through the single-reference form before processing a full workbook.

## Accuracy and speed benchmark

The historical benchmark compares the initial single-reference request with ten
publications in one structured-output request. It does not change the Flask app.
`benchmarks/testset.json` contains 80 seeded random ETIS rows and 20 selected difficult
rows, with assistant-authored annotations, rationales, and evidence frozen before
predictions. They have not been independently human-reviewed. See
`benchmarks/results/report.md` for the historical results and limitations. Its original
artifacts are preserved; the legacy benchmark command now uses the stricter output
schema and has no SQLite dependency. It excludes candidate verification in both arms;
use the production benchmark below to measure the complete current matching path.

Run from the repository root in the `flask` conda environment with a valid API key:

```bash
python -m benchmarks.venue_matching --output benchmarks/results/new-run.json
python -m benchmarks.report --results benchmarks/results/new-run.json --output-dir benchmarks/results/new-run
```

The default live run makes 220 model requests: two passes over the same 100 items,
using 100 single requests and ten batches per pass. It incurs API charges. Both
methods run sequentially, use no local result cache, retain provider prompt
caching, and use the configured `OPENAI_MODEL`. Pass two reverses method order and
reshuffles items. Results checkpoint after every request. Add `--resume` to continue
an interrupted run with identical code/configuration; completed requests, including
errors, remain recorded. Reports expose missing items, failures, and resumed timing
segments. Use a new output file for a fresh uninterrupted speed measurement.

Reports include exact venue accuracy, binary match precision/recall, error analysis,
latency, throughput, token usage, and item-level CSV predictions. The historical EACL
demo-track label was policy-sensitive; the current policy explicitly counts it as EACL.
This legacy benchmark uses its original labels; use the production evaluation below
for the current policy. Annotation provenance
is in `benchmarks/annotations.tsv`; `python -m benchmarks.build_testset` reproduces
the dataset from the original workbook and refuses to overwrite existing labels.
Do not revise frozen labels based on model predictions; document any later audit
as a separately versioned test set.

The initial run uncovered one annotation mistake: the HCI International late-breaking
paper is in a listed venue. `benchmarks/annotation_audit.json` documents the correction
and primary sources; reports preserve the original scores alongside corrected scores
and write `testset-audited.json`. The original frozen test set remains unchanged.

## Production batching validation

The streaming path, including strict name/ID checks and malformed-output fallback, is evaluated
separately without overwriting the historical benchmark:

```bash
python -m benchmarks.streaming --output-dir benchmarks/results/streaming-new
python -m benchmarks.streaming --testset benchmarks/fresh50.json --output-dir benchmarks/results/fresh-new
python -m benchmarks.policy_regressions --output benchmarks/results/policy-cases-new.json
```

Current evaluations apply `benchmarks/venue_policy.json` after the earlier HCI audit.
This versioned overlay changes the EACL demo label to the main EACL conference.
Existing positive labels for punctuation-damaged venue names already allow missing
ampersands; absent journals and workshops remain negative. Frozen source labels and
historical reports stay intact. Each new run saves its effective labels and policy hash.
Use `--baseline path/to/old/run.json` to rescore saved predictions under the same new
policy, rather than comparing scores computed under different definitions.
The policy regression command checks both single and batched requests on 19 focused
cases, including synthetic companion tracks and corrupted punctuation; it is a
development regression suite, not an independent accuracy sample.

The earlier prompt-6 policy evaluation is
`benchmarks/results/venue-policy-v2-final/evaluation.md`: prompt 6 scored 197/200 on
the original set and 98/100 on the additional set, using two passes each. Focused
policy checks scored 19/19 individually and 18/19 batched; an `and`/`&` variant still
failed in one batch. The report preserves the initial prompt-5 attempt and rescores
prior predictions under the new policy. These are development results, not proof
that every punctuation or companion-track reference will be recognized correctly.

This makes two shuffled passes over the audited 100-item set (normally 20 batched API
calls, plus individual fallbacks; candidate verification is disabled). The earlier baseline is
`benchmarks/results/streaming/report.md`. The historical verified evaluation is
`benchmarks/results/verified/report.md`, with accuracy, speed, and separate counts
for structural fallbacks and semantic verification. Benchmark commands
explicitly save reports; these artifacts are separate from application request data.
Verification rules were refined after inspecting failures on this same set, so these
are development/regression results rather than an independent holdout evaluation.

The user-reported Lillepalu & Alumäe LREC case is kept separately in
`benchmarks/regressions/lillepalu-lrec.json`, without changing the frozen 100-item set.
Repeat five single checks and five checks in its original ten-row batch using:

```bash
python -m benchmarks.regressions --output benchmarks/results/lrec-new.json
```

This calls the live API and records all ten verdicts, request counts, and timings.
The checked-in run is `benchmarks/results/verified/lrec.json` and used the former
verification-enabled workflow. New runs exercise the current default without verification.

The Excel venue-identity regressions are in `benchmarks/regressions/excel-identity.json`:
23 contradictory positives from the supplied result workbook, two missed exact
journals, and seven valid journal aliases. Repeat two shuffled batch passes with:

```bash
python -m benchmarks.policy_regressions --testset benchmarks/regressions/excel-identity.json --mode batch --passes 2 --output benchmarks/results/excel-new.json
```

The fix and its validation are documented in `benchmarks/results/excel-identity/report.md`.
The supplied result workbook and earlier benchmark artifacts are preserved.

## Embedding shortlist benchmark

The isolated benchmark compares the former production batching workflow with
lexical, embedding, and embedding-plus-exact-match candidate shortlists. Its baseline
explicitly enables verification to preserve the historical comparison; it does not
represent the current web app default. Install development dependencies, then run:

```bash
OPENBLAS_NUM_THREADS=1 python -m benchmarks.embeddings --output-dir benchmarks/results/embeddings-new
```

It uses `text-embedding-3-small` and the configured `OPENAI_MODEL`, with two paired
passes over the audited 100-item set and 50 freshly annotated workbook rows.
`benchmarks/fresh50.json` preserves the new labels, frozen before predictions;
`benchmarks/build_fresh.py` documents selection and manual annotation. The fresh
set is kept separate when scoring and never selects shortlist size or prompts.
The best embedding arm also receives ten LREC regression checks.

The command calls the live API. Catalogue vectors are cached as benchmark artifacts
in ignored `benchmarks/embedding_cache/`; query vectors and matching state stay in
memory. Timings include query embedding calls and retries, with index construction
reported separately. No vector database is required. NumPy is development-only.
Use a new output directory for every run; historical results are never overwritten.
Results checkpoint after each complete arm. The report, frozen-label snapshot,
candidate lists, request usage, and predictions are under the chosen output directory.
The checked-in experiment is `benchmarks/results/embeddings/report.md`.

The completed two-pass run found the hybrid method 3.06× faster (94 versus 288
seconds per 150 items), but less accurate: 193/200 existing-set decisions and
99/100 fresh-set decisions, versus production's 197/200 and 100/100. Retrieval
included every positive target at K=10, and the hybrid passed all ten LREC checks;
the remaining errors came from LLM decisions. It failed the migration criteria,
so embeddings were not adopted. Production subsequently returned to full-catalogue
batching without verification at the user’s request. These are repeated
decisions on 150 publications, not 300 independent examples. The result directory
also contains `summary.json` and an item-level `predictions.csv`.

## Data and deployment

The app creates no database, job directory, or temporary upload/worksheet files.
Multipart uploads use memory buffers; a small adapter serializes openpyxl 3.1
worksheets directly into an in-memory ZIP. Keep its supported version range and
run the export tests before upgrading openpyxl. Original workbook bytes, row results,
request-local deduplication, and API clients are released when the request ends.
Only the static Scholar catalogue and configuration are shared across requests.

References are sent to OpenAI with `store=False`; provider prompt caching and
account-level retention policies still apply. Application code does not log reference
content or provider diagnostic payloads. Files from older versions in `instance/jobs`
are neither read nor removed. Stop the old server and remove that directory manually
if those saved uploads/results are no longer needed. `GS_JOB_DIR` is obsolete.

Vercel deployment configuration is included; actual publication requires account access
and the preview acceptance checks in [DEPLOYMENT.md](DEPLOYMENT.md). Public API limits
are enforced by Vercel firewall rules configured in that guide, not by per-process
counters. Until those rules are published, no shared rate limiting is active.
This design needs no shared job storage and intentionally does not survive disconnects
or server restarts. On Vercel, completion logs contain only outcome, request count, and
elapsed time; publication content and credentials are not logged.

Sources: [Scholar Metrics](https://scholar.google.com/intl/en/scholar/metrics.html),
[Luna](https://developers.openai.com/api/docs/models/gpt-6-luna),
[prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching),
[structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[Flask on Vercel](https://vercel.com/docs/frameworks/backend/flask).
