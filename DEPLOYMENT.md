# Deploying Scholar20 on Vercel Pro

Deploy through Vercel’s GitHub integration. The app remains public while its source
repository may be private. No Vercel CLI or GitHub Actions deployment token is needed.
Importing the repository, configuring secrets and firewall rules, and releasing a
deployment are dashboard operations; these files alone do not perform them.

## Runtime and build

Vercel loads `wsgi:app`, installs `requirements.txt`, and runs `python build.py`.
The build validates `data/venues.json` and refreshes `public/static/` from the local
assets. The catalogue and templates ship with the function; sample workbooks,
benchmarks, tests, development caches, and secrets are excluded. No Scholar collection
or model requests run during the build. Keep developing in the `flask` conda environment.

Python is pinned to 3.12. `vercel.json` sets the entry point's maximum duration to
1,800 seconds, using Pro's extended-duration beta. Confirm the project's function
settings show that duration and Fluid compute is enabled. If the account cannot use
this duration, do not silently deploy with the five-minute default.

Vercel supplies `VERCEL=1`, selecting these application limits:

| Limit | Hosted | Local |
| --- | --- | --- |
| XLSX file | 4,000,000 bytes | 10 MiB |
| Entire request, including multipart overhead | 4,100,000 bytes | 11 MiB |
| Complete NDJSON response | 4,000,000 bytes | No application byte budget |
| Processing deadline, including workbook parsing | 29 minutes | No application deadline |
| Publication rows / expanded workbook | 5,000 / 100 MiB | Same |

The response budget includes UTF-8 progress messages, heartbeats, base64 chunks, and
the completion event. The download is sized before sending its first chunk. A small
part of the budget is reserved for a useful error. Deadline checks cancel active
model requests and stop subsequent batches; synchronous Excel operations are checked
at their boundaries, with one minute of headroom before the platform deadline.
The row limit does not guarantee every large workbook will finish in time.

## Put the project on GitHub

Create an empty GitHub repository under the intended account or organization. For a
new local repository, initialize it and review the files before the first commit:

```bash
git init -b main
git add .gitignore .vercelignore .python-version .env.example AGENTS.md README.md DEPLOYMENT.md
git add app tests benchmarks data/venues.json sample_data/Publications.xlsx
git add requirements.txt requirements-dev.txt pyproject.toml build.py wsgi.py vercel.json
git diff --cached --stat
git diff --cached --name-only
```

The original `sample_data/Publications.xlsx` and annotated benchmark datasets are
research/test fixtures: review them before publishing the repository. Other sample
uploads/results, `.env*` (except `.env.example`), caches, local credentials, macOS
metadata, and generated `public/static/` are ignored. The full test suite needs the
original workbook; Vercel's function package excludes all sample workbooks and tests.
Keep `data/venues.json` in ordinary Git so each checkout includes the catalogue.

Once the staged files are ready (replace `OWNER/REPOSITORY` below):

```bash
git commit -m "Add Scholar20 application"
git remote add origin git@github.com:OWNER/REPOSITORY.git
git push -u origin main
```

If a repository/remote already exists, use it instead of reinitializing or replacing
it. Authenticate to GitHub using your normal Git credentials, never a token in a URL.

## Import in the Vercel dashboard

1. Open [New Project](https://vercel.com/new) in the intended **Pro** team. Connect
   GitHub, grant the Vercel GitHub App access to this repository, and select **Import**.
2. Use the following build settings. The committed configuration supplies the build
   command and runtime entry point; avoid conflicting dashboard overrides.

   | Setting | Value |
   | --- | --- |
   | Root Directory | Repository root (`./`) |
   | Framework Preset | Flask |
   | Build Command | `python build.py` (from `vercel.json`) |
   | Install Command | Default; installs `requirements.txt` |
   | Output Directory | Default for Flask; do not override |
   | Production Branch | `main` |

3. For the first import, leave `OPENAI_API_KEY` unset and deploy the initial build.
   This lets you configure protection before enabling paid matching on the public
   domain. Matching is unavailable until the key is added to a subsequent deployment.
4. Enable **Standard Protection** in Deployment Protection. Deployment-specific and
   preview URLs require Vercel authentication; the production domain stays public.
5. In **Settings → Environments → Production → Branch Tracking**, disable
   **Auto-assign Custom Production Domains**. Subsequent production builds can then
   be tested at their protected deployment URLs before release.
6. In **Settings → Environment Variables**, add `OPENAI_API_KEY` and set
   `OPENAI_MODEL=gpt-6-luna` for both **Preview** and **Production**. Leave
   `GS_CATALOGUE` unset. Keep `FLASK_DEBUG` unset; Vercel supplies `VERCEL=1` itself.
   Changes to variables require a new deployment.
7. Configure the firewall below, then redeploy `main` from the Deployments dashboard
   to create a staged production build with the new variables. Confirm Python 3.12,
   the successful static-asset build, Fluid compute, and the 1,800-second duration.

See Vercel's [GitHub integration](https://vercel.com/docs/git/vercel-for-github) and
[staged deployment guide](https://vercel.com/docs/deployments/promoting-a-deployment).

## Validate a branch preview

Run the local checks before pushing changes:

```bash
conda activate flask
python -m pip install -r requirements-dev.txt
pytest
ruff check .
ruff format --check .
node tests/test_stream.cjs
python build.py
```

Push a feature branch and open a pull request. Vercel creates a preview deployment;
use its URL from the pull request or Vercel dashboard. Keep Git Fork Protection
enabled: only authorize fork deployments after reviewing their code, because a
preview runs with project credentials. Local checks are not automatically enforced
by the Vercel build; run them before merging.

## Preview acceptance tests

Record the preview URL, test time, duration, and outcome before promoting it:

1. Load the page and inspect `/static/style.css`, `/static/stream.js`, and
   `/static/app.js`. Confirm no setup error, failed resource, or CSP error.
2. Check a free-form reference and a BibTeX entry. Confirm successful same-origin
   POST requests over HTTPS and correct snapshot/category/rank output.
3. Upload the original 1,161-row sample. Watch progress arrive before completion;
   download and reopen the result, checking all rows and six added columns.
   Confirm it completes before the application deadline with a response below 4 MB.
4. Cancel a second upload while a model request is active, then separately close a
   tab during processing. Inspect the corresponding function invocation logs for
   `outcome=cancelled` and its final model-request count. Verify the invocation ends
   promptly and does not continue through later batches. A browser abort alone is
   not proof that the hosted Python runtime stopped processing.
5. Start two uploads simultaneously; cancel one and let the other finish. Perform
   this before publishing the one-upload-per-IP rule below, or from two source IPs.
6. Exercise oversized uploads, truncated streams, and rate-limit responses. Automated
   tests cover deadline cancellation and response-budget boundaries; do not shorten
   the production timeout merely to test them. No failed operation may expose a
   download link or retain a partial result.

Vercel logs contain an end-of-processing summary with outcome, model-request count,
and elapsed seconds, without publication references or credentials. Streaming and
disconnect propagation must be confirmed on Vercel itself; local tests cannot prove
proxy behavior. Do not promote if these checks fail.

## Public API rate limits

Use the linked project's firewall, not team-wide rules or Python process-local
counters. Initially permit ten single checks per minute and one workbook submission
per ten minutes per IP. These controls do not impose a global OpenAI spending cap;
shared institutional IPs share the allowance, and Vercel counts limits per region.

In the project's **Firewall → Configure**, add these rules (or edit them if they
already exist). Match both conditions with AND; choose **Rate Limit**, **Fixed
Window**, the **IP** counting key, and the default **429** response.

| Rule | Path equals | Method equals | Requests | Window |
| --- | --- | --- | --- | --- |
| GS20 single checks | `/api/check` | POST | 10 | 60 seconds |
| GS20 workbook uploads | `/api/workbooks/process` | POST | 1 | 600 seconds |

Save both rules, select **Review Changes**, check that unrelated rules are preserved,
and **Publish** the intended changes. For the concurrent-upload acceptance test,
use two source IPs or test before publishing the workbook limit.

Confirm both rules are active and return 429 when exceeded. Send invalid/empty
requests to test the limit without making paid matching calls. Firewall failures
may be plain text or HTML; the UI handles these without attempting to parse JSON.
No rate limits are active merely because these settings are documented here.

## Release and observe

After branch preview checks pass, merge the pull request into `main`. With domain
auto-assignment disabled, Vercel builds a **staged production** deployment. Repeat
the acceptance checks on that deployment's protected URL using Production settings.
Then select its **Promote** action in Deployments to release that tested build.
Staged production promotion does not rebuild it. Promoting a Preview deployment
through the dashboard instead rebuilds with Production variables, so it is a different
workflow. See [Vercel's promotion guide](https://vercel.com/docs/deployments/promoting-a-deployment).

Verify the production domain in a signed-out browser. Keep the successful deployment
as a rollback target, and observe duration, memory, cancellation summaries, 429s, and
OpenAI usage. No uploads, results, or jobs are stored between requests.

Official references: [Flask](https://vercel.com/docs/frameworks/backend/flask),
[Python](https://vercel.com/docs/functions/runtimes/python),
[duration](https://vercel.com/docs/functions/configuring-functions/duration),
[payload limits](https://vercel.com/docs/functions/limitations),
[deployment protection](https://vercel.com/docs/deployment-protection), and
[firewall rate limits](https://vercel.com/docs/vercel-firewall/vercel-waf/rate-limiting).
