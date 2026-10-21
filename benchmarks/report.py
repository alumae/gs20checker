"""Generate accuracy, latency, token, and item-level reports without API calls."""

import argparse
import csv
import hashlib
import json
import statistics
from copy import deepcopy
from pathlib import Path

from benchmarks.venue_matching import score, write_json


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def summarize_round(result, items):
    records = result["records"]
    predictions = {key: value for record in records for key, value in record["predictions"].items()}
    seconds = result["active_elapsed_seconds"]
    usages = [record.get("usage") or {} for record in records]
    tokens = {
        "input": sum(u.get("input_tokens", 0) for u in usages),
        "cached_input": sum(
            (u.get("input_tokens_details") or {}).get("cached_tokens", 0) for u in usages
        ),
        "cache_write": sum(
            (u.get("input_tokens_details") or {}).get("cache_write_tokens", 0) for u in usages
        ),
        "output": sum(u.get("output_tokens", 0) for u in usages),
        "reasoning": sum(
            (u.get("output_tokens_details") or {}).get("reasoning_tokens", 0) for u in usages
        ),
        "requests_without_usage": sum(not record.get("usage") for record in records),
    }
    request_seconds = [record["seconds"] for record in records]
    attempts = sum(record["http_attempts"] for record in records)
    return {
        "pass": result["pass"],
        "method": result["method"],
        "complete": result.get("complete", False),
        "segments": result["segments"],
        "attempted_items": len(predictions),
        "requests": len(records),
        "http_attempts": attempts,
        "retries": attempts - len(records),
        "seconds": seconds,
        "seconds_per_publication": seconds / len(predictions) if predictions else None,
        "publications_per_minute": len(predictions) * 60 / seconds if seconds else None,
        "request_median_seconds": statistics.median(request_seconds) if request_seconds else None,
        "request_p95_seconds": percentile(request_seconds, 0.95),
        "first_request_seconds": request_seconds[0] if request_seconds else None,
        "tokens": tokens,
        "scores": {
            "all": score(items, predictions),
            "random": score([i for i in items if i["subset"] == "random"], predictions),
            "challenge": score([i for i in items if i["subset"] == "challenge"], predictions),
            "excluding_policy_sensitive": score(
                [i for i in items if not i["policy_sensitive"]], predictions
            ),
        },
        "predictions": predictions,
    }


def percent(value):
    return "n/a" if value is None else f"{100 * value:.1f}%"


def number(value):
    return "n/a" if value is None else f"{value:.2f}"


def escaped(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def apply_audit(dataset, dataset_hash, audit):
    if audit["original_testset_sha256"] != dataset_hash:
        raise ValueError("Annotation audit belongs to a different frozen test set")
    reviewed = deepcopy(dataset)
    by_id = {item["id"]: item for item in reviewed["items"]}
    seen = set()
    for correction in audit["corrections"]:
        item = by_id[correction["id"]]
        if correction["id"] in seen:
            raise ValueError("Duplicate annotation correction")
        seen.add(correction["id"])
        if item["expected_venue_id"] != correction["previous_expected_venue_id"]:
            raise ValueError("Annotation audit has an unexpected original label")
        for key in ("expected_venue_id", "expected_venue", "resolved_venue", "rationale"):
            item[key] = correction[key]
        item["evidence"] += correction["evidence"]
    reviewed["post_prediction_audit"] = audit
    return reviewed


def generate(results_path, dataset_path, output_dir, audit_path=None):
    state = json.loads(Path(results_path).read_text())
    raw_dataset = Path(dataset_path).read_bytes()
    if hashlib.sha256(raw_dataset).hexdigest() != state["config"]["testset_sha256"]:
        raise ValueError("Test-set hash does not match benchmark results")
    dataset = json.loads(raw_dataset)
    batch_size = state["config"].get("batch_size", 10)
    passes = state["config"].get("passes", 2)
    items = dataset["items"]
    rounds = [summarize_round(r, items) for r in state["rounds"]]
    audit = json.loads(Path(audit_path).read_text()) if audit_path else None
    reviewed = apply_audit(dataset, state["config"]["testset_sha256"], audit) if audit else dataset
    reviewed_map = {i["id"]: i for i in reviewed["items"]}
    if audit:
        for result, raw_round in zip(rounds, state["rounds"]):
            result["audited_scores"] = summarize_round(raw_round, reviewed["items"])["scores"]
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if audit:
        write_json(output / "testset-audited.json", reviewed)
    write_json(
        output / "summary.json",
        {
            "status": state["status"],
            "config": state["config"],
            "rounds": rounds,
            "annotation_audit": audit,
        },
    )
    item_map = {i["id"]: i for i in items}
    columns = [
        "pass",
        "method",
        "id",
        "subset",
        "row",
        "reference",
        "expected_venue_id",
        "expected_venue",
        "predicted_venue_id",
        "predicted_venue",
        "status",
        "correct",
        "audited_expected_venue_id",
        "audited_expected_venue",
        "audited_correct",
        "note",
        "policy_sensitive",
    ]
    with (output / "predictions.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for result in rounds:
            for item_id, prediction in result["predictions"].items():
                item = item_map[item_id]
                writer.writerow(
                    {
                        "pass": result["pass"],
                        "method": result["method"],
                        "id": item_id,
                        "subset": item["subset"],
                        "row": item["row"],
                        "reference": item["fields"].get("reference", ""),
                        "expected_venue_id": item["expected_venue_id"],
                        "expected_venue": item["expected_venue"],
                        "predicted_venue_id": prediction.get("venue_id"),
                        "predicted_venue": prediction.get("venue"),
                        "status": prediction["status"],
                        "correct": prediction["status"] != "error"
                        and prediction.get("venue_id") == item["expected_venue_id"],
                        "audited_expected_venue_id": reviewed_map[item_id]["expected_venue_id"],
                        "audited_expected_venue": reviewed_map[item_id]["expected_venue"],
                        "audited_correct": prediction["status"] != "error"
                        and prediction.get("venue_id")
                        == reviewed_map[item_id]["expected_venue_id"],
                        "note": prediction.get(
                            "note", prediction.get("error", {}).get("message", "")
                        ),
                        "policy_sensitive": item["policy_sensitive"],
                    }
                )
    lines = [
        "# Single-request versus batching benchmark",
        "",
        f"Run status: **{state['status']}**. Model: `{state['config']['model']}`. "
        f"Started: {state['started_at']}.",
        "",
        "## Protocol",
        "",
        "100 original ETIS rows: 80 sampled without replacement (seed 20261018) and 20 "
        "deliberately difficult rows. Labels were manually authored by the Codex assistant "
        "before either method ran; they are not independently human-reviewed. "
        "The test contains 34 positive and 66 negative venue labels. "
        "Use the random subset to assess typical workbook performance; the combined score "
        "is deliberately enriched with difficult cases.",
        "",
        f"Catalogue snapshot: {dataset['catalogue_snapshot']}. "
        f"Frozen labels: {dataset['frozen_at']}. "
        f"Test-set SHA-256: `{state['config']['testset_sha256']}`.",
        "",
        "Both methods use the same model, catalogue, matching rules, low reasoning effort, "
        "45-second request timeout, and up to two SDK retries. Baseline invokes the production "
        "request and validation directly, bypassing SQLite. "
        f"Batches contain {batch_size} independent "
        f"publications and receive {batch_size} times the output-token ceiling. No gold labels or "
        "annotation rationales are sent. All requests are sequential with store=False.",
        "",
        f"The run schedules {passes} paired passes. Odd passes run single then batch; even passes "
        "run batch then single. Each pass uses a new shuffle; each pair uses identical item order. "
        "Provider prompt caching stays "
        "enabled: cache state is not controlled, and these are not cold-cache comparisons. "
        "Timings include SDK retries, validation, and per-round checkpoint overhead, but exclude "
        "model-access preflight, annotation, startup, and report generation. Interrupted runs "
        "report active segments rather than uninterrupted wall time.",
        "",
        "## Accuracy against original frozen annotations",
        "",
        "Exact accuracy requires the correct catalogue ID or a correct no-match. Errors and "
        "unattempted items count against accuracy. Match precision/recall describe the binary "
        "listed/unlisted decision among valid responses; wrong venue IDs are counted separately. "
        "Service errors remain explicit, rather than being converted into nonmatches.",
        "",
        "| Pass | Method | All exact | Random exact | Challenge exact | Precision | Recall | "
        "False + | False − | Wrong venue | Errors / missing |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in rounds:
        scores = result["scores"]
        all_scores = scores["all"]
        exact = [f"{scores[k]['correct']}/{scores[k]['n']}" for k in ("all", "random", "challenge")]
        lines.append(
            f"| {result['pass']} | {result['method']} | {' | '.join(exact)} | "
            f"{percent(all_scores['match_precision'])} | {percent(all_scores['match_recall'])} | "
            f"{all_scores['false_positive']} | {all_scores['false_negative']} | "
            f"{all_scores['wrong_venue']} | {all_scores['errors']} / {all_scores['missing']} |"
        )
    if audit:
        lines += [
            "",
            "### Documented annotation correction",
            "",
            "Error review after predictions began identified a mistake in the original row-1141 "
            "annotation. HCI International **is** in the catalogue, and its official proceedings "
            "inventory includes the paper's Late Breaking Papers volume. The correct venue is "
            "HCI International. This is supported by the "
            "[conference proceedings inventory](https://2025.hci.international/proceedings.html) "
            "and the [Springer chapter](https://link.springer.com/chapter/10.1007/978-3-032-12660-3_9).",
            "",
            "The original test set is preserved above. The separately versioned "
            "`testset-audited.json` applies the evidence-backed correction (35 positives, "
            "65 negatives); no model requests were changed or rerun. This audit was informed "
            "by a disagreement, so corrected scores are explicitly post hoc. "
            "The following table uses the audited labels:",
            "",
            "| Pass | Method | All exact | Random exact | Challenge exact | Precision | Recall | "
            "False + | False − | Wrong venue |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in rounds:
            scores = r["audited_scores"]
            s = scores["all"]
            exact = [
                f"{scores[k]['correct']}/{scores[k]['n']}" for k in ("all", "random", "challenge")
            ]
            lines.append(
                f"| {r['pass']} | {r['method']} | {' | '.join(exact)} | "
                f"{percent(s['match_precision'])} | {percent(s['match_recall'])} | "
                f"{s['false_positive']} | {s['false_negative']} | {s['wrong_venue']} |"
            )
    lines += [
        "",
        "## Speed and tokens",
        "",
        "| Pass | Method | Elapsed s | s/publication | Publications/min | Requests | "
        "Retries | Request median s | Request p95 s |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rounds:
        lines.append(
            f"| {r['pass']} | {r['method']} | {number(r['seconds'])} | "
            f"{number(r['seconds_per_publication'])} | "
            f"{number(r['publications_per_minute'])} | {r['requests']} | {r['retries']} | "
            f"{number(r['request_median_seconds'])} | {number(r['request_p95_seconds'])} |"
        )
    for pass_number in sorted({r["pass"] for r in rounds}):
        pair = {r["method"]: r for r in rounds if r["pass"] == pass_number and r["complete"]}
        if set(pair) == {"single", "batch"}:
            speedup = pair["single"]["seconds"] / pair["batch"]["seconds"]
            lines += ["", f"Pass {pass_number}: **{speedup:.2f}× speedup** from batching."]
    lines += [
        "",
        "| Pass | Method | Input tokens | Cached input | Cache writes | Output | "
        "Reasoning (part of output) | Missing usage |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rounds:
        t = r["tokens"]
        lines.append(
            f"| {r['pass']} | {r['method']} | {t['input']:,} | {t['cached_input']:,} | "
            f"{t['cache_write']:,} | {t['output']:,} | {t['reasoning']:,} | "
            f"{t['requests_without_usage']} |"
        )
    lines += [
        "",
        "Token counts are provider-reported usage for returned responses. Failed "
        "attempts without usage cannot be assigned a token cost. Prices are not inferred "
        "from token totals; caching and account-specific pricing affect actual charges.",
        "",
        "## Error analysis (audited labels when available)",
        "",
    ]
    names = [f"{r['method']} pass {r['pass']}" for r in rounds]
    lines += [
        "| Item / subset | Annotated venue | " + " | ".join(names) + " | Rationale |",
        "| --- | --- | " + " | ".join("---" for _ in names) + " | --- |",
    ]
    disagreements = 0
    for item in reviewed["items"]:
        predictions = [r["predictions"].get(item["id"]) for r in rounds]
        if not any(
            p and (p["status"] == "error" or p.get("venue_id") != item["expected_venue_id"])
            for p in predictions
        ):
            continue
        disagreements += 1
        cells = [
            "Not run"
            if p is None
            else "ERROR"
            if p["status"] == "error"
            else p.get("venue") or "No match"
            for p in predictions
        ]
        lines.append(
            f"| {item['id']} / {item['subset']} | "
            f"{escaped(item['expected_venue'] or 'No match')} | "
            + " | ".join(escaped(cell) for cell in cells)
            + f" | {escaped(item['rationale'])} |"
        )
    if not disagreements:
        lines += ["", "No scored disagreements in the completed requests."]
    failures = [
        (r, record) for r in state["rounds"] for record in r["records"] if record.get("error")
    ]
    if failures:
        lines += [
            "",
            "### Rejected responses",
            "",
            "These failed requests remain errors in accuracy and throughput metrics; "
            "they were not silently retried as new model predictions.",
            "",
            "| Pass / method | Items | Failure | Model output |",
            "| --- | --- | --- | --- |",
        ]
        for r, record in failures:
            lines.append(
                f"| {r['pass']} / {r['method']} | {', '.join(record['ids'])} | "
                f"{record['error']['type']} | "
                f"{escaped(record.get('output_text', 'No model output'))} |"
            )
    lines += [
        "",
        "### Policy sensitivity and order stability",
        "",
        "Row 967 is an EACL System Demonstrations paper. The frozen annotation applies "
        "the app's conservative companion-proceedings rule and returns no match. "
        "Scholar's aggregation of that track has not been verified. The main EACL venue "
        "is listed; human review of this policy is warranted. Accuracy excluding this item:",
        "",
    ]
    for r in rounds:
        s = r.get("audited_scores", r["scores"])["excluding_policy_sensitive"]
        lines.append(f"- {r['method']} pass {r['pass']}: {s['correct']}/{s['n']}.")
    for method in ("single", "batch"):
        pair = [r for r in rounds if r["method"] == method and r["complete"]]
        if len(pair) >= 2:
            changed = []
            for item in items:
                a, b = (r["predictions"][item["id"]] for r in pair[:2])
                if (a["status"], a.get("venue_id")) != (b["status"], b.get("venue_id")):
                    changed.append(item["id"])
            lines += [
                "",
                f"{method}: {len(changed)} labels changed between passes"
                + (f" ({', '.join(changed)})." if changed else "."),
            ]
    if state["status"] == "complete":
        totals = {}
        for method in ("single", "batch"):
            selected = [r for r in rounds if r["method"] == method]
            totals[method] = {
                "seconds": sum(r["seconds"] for r in selected),
                "correct": sum(
                    r.get("audited_scores", r["scores"])["all"]["correct"] for r in selected
                ),
                "n": sum(r["scores"]["all"]["n"] for r in selected),
            }
        single, batch = totals["single"], totals["batch"]
        speedup = single["seconds"] / batch["seconds"]
        lines += [
            "",
            "## Recommendation",
            "",
            f"Across both methods' completed passes, batching took {batch['seconds']:.1f}s "
            f"versus {single['seconds']:.1f}s for single requests: **{speedup:.2f}× faster**. "
            f"{'Audited' if audit else 'Frozen-label'} exact scores were "
            f"**{batch['correct']}/{batch['n']} batched** and "
            f"**{single['correct']}/{single['n']} single**. These totals contain repeated "
            "predictions on the same publications.",
            "",
            "Batching merits a follow-up integration trial if this speed advantage is useful, "
            "but aggregate accuracy alone does not establish equivalent reliability. "
            "Review false positives, wrong IDs, and order-sensitive cases above before changing "
            "the production default. In particular, a syntactically valid catalogue ID can "
            "contradict the venue named in the model's explanation. A useful next experiment "
            "is to require both canonical venue name and ID, validate their agreement, and "
            "retry inconsistent items individually. That safeguard has not been tested here.",
        ]
    lines += [
        "",
        "## Interpretation limits",
        "",
        f"These are {passes} passes over the same 100 publications, "
        f"not {passes * 100} independent test "
        "examples. Model randomness, server load, and cache state can affect both speed "
        "and labels. Order changes also change batch composition, so this experiment "
        "cannot attribute an individual change exclusively to batching. The benchmark "
        "tests matching against the bundled catalogue, not completeness of Scholar "
        "collection or the authenticity/publication status of each ETIS reference.",
        "",
        "The production application is unchanged. Review item-level errors and any "
        "false positives before adopting batching; this small evaluation does not establish "
        "statistical equivalence of accuracy.",
        "",
        "Artifacts: `predictions.csv` contains all attempted item-level decisions and "
        "notes; `summary.json` contains metrics; `run.json` contains request timings, usage, "
        "outputs, ordering, configuration, and reproducibility hashes.",
        "",
    ]
    (output / "report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="benchmarks/results/run.json")
    parser.add_argument("--testset", default="benchmarks/testset.json")
    parser.add_argument("--output-dir", default="benchmarks/results")
    parser.add_argument("--audit", default="benchmarks/annotation_audit.json")
    args = parser.parse_args()
    generate(args.results, args.testset, args.output_dir, args.audit)
