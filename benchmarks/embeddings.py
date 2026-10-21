"""Paired embedding-shortlist experiment; never changes the production matcher."""

import argparse
import asyncio
import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from app.catalogue import Catalogue
from app.matching import AsyncMatcher
from app.workbooks import extract_rows
from benchmarks.embedding_retrieval import Embeddings, Retrieval, ShortlistMatcher, query_text
from benchmarks.policy import load_current_dataset
from benchmarks.streaming import RecordingClient
from benchmarks.venue_matching import score, write_json

METHODS = ["production", "lexical", "dense", "hybrid"]
SEED = 20261021


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def retrieval_scores(items, rankings):
    positives = [i for i in items if i["expected_venue_id"] is not None]
    misses = [i["id"] for i in positives if i["expected_venue_id"] not in rankings[i["id"]]]
    return {
        "positives": len(positives),
        "hits": len(positives) - len(misses),
        "recall": 1 - len(misses) / len(positives) if positives else None,
        "misses": misses,
    }


def retrieval_evaluation(retrieval, items, vectors):
    results = {}
    for method in ("dense", "hybrid", "lexical"):
        results[method] = {}
        for k in (5, 10, 20):
            rankings = {}
            for item, vector in zip(items, vectors, strict=True):
                ids = (
                    retrieval.lexical(item["fields"], k)
                    if method == "lexical"
                    else retrieval.dense(vector, k)
                )
                if method == "hybrid":
                    ids = list(dict.fromkeys(ids + retrieval.exact(item["fields"])))
                rankings[item["id"]] = ids
            results[method][str(k)] = {**retrieval_scores(items, rankings), "rankings": rankings}
    return results


def token_totals(calls, embedding_calls):
    usages = [c.get("usage") or {} for c in calls]
    return {
        "input": sum(u.get("input_tokens", 0) for u in usages),
        "cached_input": sum(
            (u.get("input_tokens_details") or {}).get("cached_tokens", 0) for u in usages
        ),
        "output": sum(u.get("output_tokens", 0) for u in usages),
        "embedding": sum((c.get("usage") or {}).get("total_tokens", 0) for c in embedding_calls),
    }


def summarize(
    method, pass_number, items, predictions, shortlists, seconds, client, embeddings, matcher
):
    groups = {
        "existing": [i for i in items if i["subset"] != "fresh"],
        "fresh": [i for i in items if i["subset"] == "fresh"],
    }
    failures = []
    for item in items:
        result = predictions.get(item["id"], {"status": "error"})
        if result["status"] != "error" and result.get("venue_id") == item["expected_venue_id"]:
            continue
        retrieval_miss = (
            method != "production"
            and item["expected_venue_id"] is not None
            and item["expected_venue_id"] not in shortlists.get(item["id"], [])
        )
        failures.append(
            {
                "id": item["id"],
                "subset": item["subset"],
                "expected": item["expected_venue"],
                "predicted": result.get("venue"),
                "stage": "retrieval"
                if retrieval_miss
                else "service"
                if result["status"] == "error"
                else "llm",
                "note": result.get("note", ""),
            }
        )
    calls = client.calls
    return {
        "method": method,
        "pass": pass_number,
        "seconds": seconds,
        "order": [i["id"] for i in items],
        "predictions": predictions,
        "shortlists": shortlists,
        "scores": {group: score(selected, predictions) for group, selected in groups.items()},
        "retrieval": {
            group: retrieval_scores(selected, shortlists) for group, selected in groups.items()
        }
        if shortlists
        else None,
        "failures": failures,
        "calls": calls,
        "embedding_calls": embeddings.calls,
        "requests": len(calls) + len(embeddings.calls),
        "http_attempts": sum(c["http_attempts"] for c in calls + embeddings.calls),
        "fallbacks": matcher.fallbacks,
        "verifications": getattr(matcher, "verifications", 0),
        "tokens": token_totals(calls, embeddings.calls),
    }


async def run_round(catalogue, retrieval, items, method, k, model, key, pass_number):
    client = RecordingClient(key)
    embeddings = Embeddings(client)
    matcher = (
        AsyncMatcher(catalogue, model, client=client, verify_candidates=True)
        if method == "production"
        else ShortlistMatcher(catalogue, model, client)
    )
    predictions, shortlists = {}, {}
    started = time.perf_counter()
    try:
        vectors = (
            await embeddings.encode([query_text(i["fields"]) for i in items])
            if method in ("dense", "hybrid")
            else [None] * len(items)
        )
        if method != "production":
            shortlists = {
                item["id"]: retrieval.shortlist(item["fields"], method, k, vector)
                for item, vector in zip(items, vectors, strict=True)
            }
        for offset in range(0, len(items), 10):
            group = items[offset : offset + 10]
            results = (
                await matcher.match_batch(group)
                if method == "production"
                else await matcher.match_batch(group, shortlists)
            )
            predictions.update(results)
            print(f"Pass {pass_number} {method}: {offset + len(group)}/{len(items)}", flush=True)
        seconds = time.perf_counter() - started
        result = summarize(
            method,
            pass_number,
            items,
            predictions,
            shortlists,
            seconds,
            client,
            embeddings,
            matcher,
        )
        # Fresh recall is first examined only after K was frozen using the existing set.
        if method == "dense" and pass_number == 1:
            indexes = [n for n, i in enumerate(items) if i["subset"] == "fresh"]
            result["fresh_retrieval_grid"] = retrieval_evaluation(
                retrieval, [items[n] for n in indexes], vectors[indexes]
            )
        return result
    finally:
        await client.close()


async def lrec_trials(catalogue, retrieval, method, k, model, key):
    case = json.loads(Path("benchmarks/regressions/lillepalu-lrec.json").read_text())
    rows, _ = extract_rows(Path("sample_data/Publications.xlsx").read_bytes())
    index = next(n for n, row in enumerate(rows) if row["row"] == 361)
    batch = rows[(index // 10) * 10 : (index // 10 + 1) * 10]
    cases = [("single", [{"id": "lrec", "fields": {"reference": case["plain_reference"]}}])]
    cases.append(
        ("original_batch", [{"id": f"etis-{r['row']:04d}", "fields": r["fields"]} for r in batch])
    )
    trials = []
    for mode, items in cases:
        for repetition in range(5):
            client = RecordingClient(key)
            embeddings = Embeddings(client)
            started = time.perf_counter()
            try:
                vectors = await embeddings.encode([query_text(i["fields"]) for i in items])
                shortlists = {
                    item["id"]: retrieval.shortlist(item["fields"], method, k, v)
                    for item, v in zip(items, vectors, strict=True)
                }
                matcher = ShortlistMatcher(catalogue, model, client)
                predictions = await matcher.match_batch(items, shortlists)
                result = predictions["lrec" if mode == "single" else "etis-0361"]
                trials.append(
                    {
                        "mode": mode,
                        "repetition": repetition + 1,
                        "correct": result.get("venue_id") == case["expected_venue_id"],
                        "result": result,
                        "seconds": time.perf_counter() - started,
                        "shortlists": shortlists,
                        "calls": client.calls,
                        "embedding_calls": embeddings.calls,
                    }
                )
                print(f"LREC {mode} {repetition + 1}: {trials[-1]['correct']}", flush=True)
            finally:
                await client.close()
    return {
        "method": method,
        "correct": sum(t["correct"] for t in trials),
        "n": 10,
        "trials": trials,
    }


def totals(state, method):
    rounds = [r for r in state["rounds"] if r["method"] == method]
    return {
        "seconds": sum(r["seconds"] for r in rounds),
        **{
            subset: sum(r["scores"][subset]["correct"] for r in rounds)
            for subset in ("existing", "fresh")
        },
    }


def report(state, output):
    lines = [
        "# Embedding shortlist benchmark",
        "",
        (
            f"Status: **{state['status']}**. Model: `{state['model']}`. Embeddings: "
            f"`text-embedding-3-small`, 1536 dimensions."
        ),
        "",
        "## Protocol",
        "",
        (
            "The existing 100-item set is development data, scored under the current venue policy. "
            "The fresh seeded 50-item holdout (11 positive) was annotated by the "
            "Codex assistant against the catalogue before predictions; it has not "
            "been independently human-reviewed. Two passes reuse the same items; "
            "totals are repeated decisions, not independent samples."
        ),
        "",
        (
            "Four arms run sequentially in batches of ten. Each pass shuffles all "
            "150 items once; all arms share that order and batch composition. The "
            "second pass reverses arm order. The historical production baseline "
            "explicitly enables selective verification. Lexical uses "
            "IDF-weighted token overlap with exact-name/acronym priority, capped "
            "at 20. Dense uses cosine similarity; hybrid unions dense results with "
            "exact names/acronyms without truncating the union."
        ),
        "",
        (
            "Catalogue vectors contain venue names, parenthetical acronyms and "
            "known types, never categories or ranks. Queries combine populated "
            "journal/conference/proceedings fields, falling back to the reference. "
            "The LLM sees original fields and each item’s own shortlist. IDs and "
            "canonical names are validated per item; invalid output receives at "
            "most one individual retry with the same shortlist. There is no "
            "full-catalogue fallback."
        ),
        "",
        (
            f"K = **{state.get('k', 'pending')}**, selected using positive recall "
            f"on the existing set only. The smallest of 5/10/20 covering every "
            f"positive is chosen for each embedding arm; the shared K is the larger "
            f"requirement. If recall is incomplete at 20, K remains 20 and misses "
            f"are reported. Prompts and K are not tuned on fresh predictions."
        ),
        "",
        (
            "Timings include query embedding calls, retrieval, matching, "
            "validation and SDK retries. Each arm/pass has a new client and no "
            "local query/result cache; duplicate query strings are embedded once "
            "per simulated upload. Catalogue indexing and recall calibration are "
            "excluded and reported separately. This is matcher throughput, "
            "excluding XLSX parsing/export and browser transfer. Provider caching "
            "and load are uncontrolled."
        ),
        "",
        "## Positive retrieval recall",
        "",
        "| Set | Retrieval | K | Hits / positives | Misses |",
        "| --- | --- | --- | --- | --- |",
    ]
    grids = {"existing": state.get("retrieval_calibration", {})}
    for r in state["rounds"]:
        if "fresh_retrieval_grid" in r:
            grids["fresh"] = r["fresh_retrieval_grid"]
    for subset, grid in grids.items():
        for method, entries in grid.items():
            for k, entry in entries.items():
                lines.append(
                    (
                        f"| {subset} | {method} | {k} | {entry['hits']}/{entry['positives']} | "
                        f"{', '.join(entry['misses']) or '—'} |"
                    )
                )
    lines += [
        "",
        "## Accuracy and speed",
        "",
        (
            "| Pass | Method | Existing exact | Fresh exact | FP / FN / wrong ID / "
            "errors | Seconds (150 items) | API calls | Fallbacks |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in state["rounds"]:
        s = r["scores"]
        counts = [
            sum(v[key] for v in s.values())
            for key in ("false_positive", "false_negative", "wrong_venue", "errors")
        ]
        lines.append(
            (
                f"| {r['pass']} | {r['method']} | {s['existing']['correct']}/100 | "
                f"{s['fresh']['correct']}/50 | {' / '.join(map(str, counts))} | "
                f"{r['seconds']:.2f} | {r['requests']} | {r['fallbacks']} |"
            )
        )
    lines += [
        "",
        "## Usage",
        "",
        "| Pass | Method | Input | Cached input | Output | Embedding tokens | HTTP attempts |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in state["rounds"]:
        t = r["tokens"]
        lines.append(
            (
                f"| {r['pass']} | {r['method']} | {t['input']} | {t['cached_input']} | "
                f"{t['output']} | {t['embedding']} | {r['http_attempts']} |"
            )
        )
    if "index" in state:
        idx = state["index"]
        lines += [
            "",
            (
                f"Catalogue index: {idx['seconds']:.2f}s, cache hit: "
                f"{idx['cache_hit']}, {len(idx['calls'])} embedding requests, "
                f"{sum(c.get('usage', {}).get('total_tokens', 0) for c in idx['calls'])} "
                f"embedding tokens. Float32 vector data: "
                f"{4652 * 1536 * 4 / 1024**2:.1f} MiB before compression. Index "
                f"fingerprint: `{idx['fingerprint']}`."
            ),
        ]
    lines += ["", "## Disagreements", ""]
    for r in state["rounds"]:
        for failure in r["failures"]:
            note = failure["note"].replace("\n", " ")
            lines.append(
                (
                    f"- Pass {r['pass']} {r['method']}, {failure['id']} "
                    f"({failure['subset']}, {failure['stage']}): expected "
                    f"{failure['expected'] or 'no match'}; returned "
                    f"{failure['predicted'] or 'no match/error'}. {note}"
                )
            )
    if state.get("lrec"):
        trial = state["lrec"]
        lines += [
            "",
            (
                f"LREC regression ({trial['method']}): "
                f"**{trial['correct']}/{trial['n']}**, five plain-reference single "
                f"checks and five checks in the original workbook batch."
            ),
        ]
    if state.get("decision"):
        d = state["decision"]
        lines += [
            "",
            "## Decision",
            "",
            (
                f"Best embedding arm: **{d['method']}**, {d['speedup']:.2f}× faster "
                f"than the contemporaneous production baseline. Existing: "
                f"{d['existing']}/200; fresh: {d['fresh']}/100 (baseline "
                f"{d['baseline_fresh']}/100)."
            ),
            "",
            (
                f"Migration gate: **{'PASS' if d['passed'] else 'FAIL'}**. Requires "
                f"faster processing, at least 197/200 existing decisions, fresh "
                f"accuracy at least the contemporaneous baseline, and LREC 10/10. Gate "
                f"results: {json.dumps(d['gates'])}."
            ),
            "",
            "Recommend a separately reviewed integration trial."
            if d["passed"]
            else (
                "Keep production unchanged; the measured embedding approach has not "
                "met the agreed migration criteria."
            ),
        ]
    lines += [
        "",
        "## Reproducibility and limits",
        "",
        (
            "Run `python -m benchmarks.embeddings --output-dir "
            "benchmarks/results/embeddings-new`. NumPy is a development "
            "dependency. Frozen labels are in `benchmarks/fresh50.json`; selection "
            "and manually authored annotations are in `benchmarks/build_fresh.py`. "
            "Run artifacts include source/data hashes, per-request "
            "output/usage/latency, candidate lists, predictions and errors. "
            "Catalogue vectors are cached only in ignored "
            "`benchmarks/embedding_cache/`; no SQL database is used."
        ),
        "",
        (
            "This is a small, mostly negative holdout from one workbook. It tests "
            "venue identity against the bundled catalogue, not catalogue "
            "completeness or reference authenticity. Existing labels include a "
            "documented earlier post-prediction audit. The best embedding arm is "
            "selected by existing-set accuracy then latency; fresh labels never "
            "select K, prompts or the winner. Report uncertainty rather than "
            "treating these results as statistical equivalence."
        ),
        "",
        (
            "Production application code is unchanged. Embeddings API reference: "
            "https://developers.openai.com/api/docs/guides/embeddings"
        ),
        "",
    ]
    (output / "report.md").write_text("\n".join(lines))


async def run(output):
    if output.exists():
        raise ValueError("Choose a new output directory; historical results are never overwritten")
    load_dotenv(".env")
    key, model = os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL", "gpt-6-luna")
    catalogue = Catalogue.load("data/venues.json")
    old, _ = load_current_dataset("benchmarks/testset.json", catalogue)
    fresh, _ = load_current_dataset("benchmarks/fresh50.json", catalogue)
    for data in (old, fresh):
        if (
            data["catalogue_version"] != catalogue.version
            or sha(data["source"]) != data["source_sha256"]
        ):
            raise ValueError("Annotated input or catalogue has changed")
    if {i["id"] for i in old["items"]} & {i["id"] for i in fresh["items"]}:
        raise ValueError("Holdout overlaps original set")
    paths = [
        "benchmarks/testset.json",
        "benchmarks/annotation_audit.json",
        "benchmarks/venue_policy.json",
        "benchmarks/policy.py",
        "benchmarks/fresh50.json",
        "benchmarks/build_fresh.py",
        "benchmarks/embedding_retrieval.py",
        __file__,
        "benchmarks/streaming.py",
        "app/matching.py",
        "app/candidates.py",
        "data/venues.json",
        "benchmarks/regressions/lillepalu-lrec.json",
    ]
    state = {
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "seed": SEED,
        "batch_size": 10,
        "rounds": [],
        "hashes": {p: sha(p) for p in paths},
    }
    output.mkdir(parents=True)
    write_json(output / "labels.json", {"existing": old, "fresh": fresh})
    write_json(output / "run.json", state)
    retrieval = Retrieval(catalogue)
    try:
        client = RecordingClient(key)
        try:
            await client.client.models.retrieve(model)
            embeddings = Embeddings(client)
            state["index"] = await retrieval.build(embeddings, "benchmarks/embedding_cache")
            embeddings.calls.clear()
            vectors = await embeddings.encode([query_text(i["fields"]) for i in old["items"]])
            calibration = retrieval_evaluation(retrieval, old["items"], vectors)
            state["retrieval_calibration"] = calibration
            state["calibration_embedding_calls"] = embeddings.calls
            state["k_by_method"] = {
                method: next(
                    (k for k in (5, 10, 20) if not calibration[method][str(k)]["misses"]), 20
                )
                for method in ("dense", "hybrid")
            }
            state["k"] = max(state["k_by_method"].values())
            state["k_frozen_at"] = datetime.now(timezone.utc).isoformat()
            write_json(output / "run.json", state)
            report(state, output)
            print(f"Index ready. Frozen K={state['k']}; running paired passes.", flush=True)
        finally:
            await client.close()
        for pass_number in (1, 2):
            ordered = old["items"] + fresh["items"]
            random.Random(SEED + pass_number).shuffle(ordered)
            for method in METHODS if pass_number == 1 else reversed(METHODS):
                result = await run_round(
                    catalogue, retrieval, ordered, method, state["k"], model, key, pass_number
                )
                state["rounds"].append(result)
                write_json(output / "run.json", state)
                report(state, output)
        best = min(
            ("dense", "hybrid"),
            key=lambda m: (-totals(state, m)["existing"], totals(state, m)["seconds"]),
        )
        state["lrec"] = await lrec_trials(catalogue, retrieval, best, state["k"], model, key)
        baseline, chosen = totals(state, "production"), totals(state, best)
        gates = {
            "faster": chosen["seconds"] < baseline["seconds"],
            "existing_197": chosen["existing"] >= 197,
            "fresh_at_least_baseline": chosen["fresh"] >= baseline["fresh"],
            "lrec_10": state["lrec"]["correct"] == 10,
        }
        state["decision"] = {
            "method": best,
            **chosen,
            "baseline_fresh": baseline["fresh"],
            "speedup": baseline["seconds"] / chosen["seconds"],
            "gates": gates,
            "passed": all(gates.values()),
        }
        state.update(status="complete", finished_at=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        state.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        write_json(output / "run.json", state)
        report(state, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("benchmarks/results/embeddings"))
    args = parser.parse_args()
    asyncio.run(run(args.output_dir))
