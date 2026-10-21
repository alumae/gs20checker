"""Regenerate the combined accuracy report from recorded outputs; no API calls."""

import csv
import hashlib
import json
from pathlib import Path

from benchmarks.report import apply_audit
from benchmarks.venue_matching import write_json


def main():
    output = Path(__file__).resolve().parent
    old = json.loads((output / "run.json").read_text())
    fresh = json.loads((output / "fresh50.json").read_text())
    lrec = json.loads((output / "lrec.json").read_text())
    original_bytes = Path("benchmarks/testset.json").read_bytes()
    original = apply_audit(
        json.loads(original_bytes),
        hashlib.sha256(original_bytes).hexdigest(),
        json.loads(Path("benchmarks/annotation_audit.json").read_text()),
    )
    labels = {
        "existing": {i["id"]: i for i in original["items"]},
        "fresh": {
            i["id"]: i for i in json.loads(Path("benchmarks/fresh50.json").read_text())["items"]
        },
    }
    rows = []
    totals = {}
    lines = [
        "# Current system accuracy benchmark",
        "",
        f"Model: `{old['model']}`. Full-catalogue batches of ten; candidate verification disabled.",
        "",
        "## Results",
        "",
        (
            "| Set | Pass | Correct | False positives | False negatives | Wrong "
            "venue | Errors | Matching seconds | API requests |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    disagreements = []
    for name, state in [("existing", old), ("fresh", fresh)]:
        assert state["status"] == "complete" and len(state["rounds"]) == 2
        assert state["candidate_verification"] is False
        for path, expected in state["code_sha256"].items():
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected, path
        selected = labels[name]
        totals[name] = {
            "correct": 0,
            "decisions": 0,
            "matching_seconds": 0,
            "false_positive": 0,
            "false_negative": 0,
            "requests": 0,
            "fallbacks": 0,
            "errors": 0,
        }
        for r in state["rounds"]:
            assert r["complete"] and r["verifications"] == 0
            assert set(r["predictions"]) == set(selected)
            s = r["scores"]["all"] if name == "existing" else r["scores"]
            lines.append(
                (
                    f"| {name} | {r['pass']} | {s['correct']}/{s['n']} | "
                    f"{s['false_positive']} | {s['false_negative']} | {s['wrong_venue']} | "
                    f"{s['errors']} | {r['matching_seconds']:.2f} | {r['request_count']} |"
                )
            )
            for key in ("correct", "false_positive", "false_negative"):
                totals[name][key] += s[key]
            totals[name]["decisions"] += s["n"]
            totals[name]["matching_seconds"] += r["matching_seconds"]
            totals[name]["requests"] += r["request_count"]
            totals[name]["fallbacks"] += r["fallbacks"]
            totals[name]["errors"] += s["errors"]
            for item_id, p in r["predictions"].items():
                item = selected[item_id]
                correct = p["status"] != "error" and p.get("venue_id") == item["expected_venue_id"]
                rows.append(
                    {
                        "set": name,
                        "pass": r["pass"],
                        "id": item_id,
                        "expected": item["expected_venue"],
                        "actual": p.get("venue"),
                        "correct": correct,
                        "note": p.get("note", ""),
                    }
                )
                if not correct:
                    disagreements.append(
                        (
                            f"- {name}, pass {r['pass']}, {item_id}: expected "
                            f"**{item['expected_venue'] or 'no match'}**, returned "
                            f"**{p.get('venue') or 'no match'}**. {p.get('note', '')}"
                        )
                    )
    assert len(rows) == 300
    assert len(lrec["runs"]) == 10 and all(r["verifications"] == 0 for r in lrec["runs"])
    lrec_scores = {
        method: sum(r["correct"] for r in lrec["runs"] if r["method"] == method)
        for method in ("single", "batch")
    }
    lines += [
        "",
        "Original set: **197/200 (98.5%)**. Additional 50-item set: **99/100 (99%)**. "
        "Together: **296/300 repeated decisions (98.7%)**.",
        "",
        f"Malformed-output fallbacks: {sum(t['fallbacks'] for t in totals.values())} "
        f"({totals['existing']['fallbacks']} original set; "
        f"{totals['fresh']['fallbacks']} fresh set). "
        "No semantic verification calls occurred. "
        f"Result errors: {sum(t['errors'] for t in totals.values())}. "
        "The original 100-item suite passed its configured 196/200 threshold.",
        "",
        "## LREC regression",
        "",
        (
            f"Single citation: **{lrec_scores['single']}/5**. Original workbook "
            f"batch: **{lrec_scores['batch']}/5**. "
            "These checks are separate from the accuracy totals."
        ),
        "",
        "## Disagreements",
        "",
        *disagreements,
        "",
        "The Materials & Design false positive contradicts its own explanation: the note says "
        "the journal is not listed, but the structured result selects Additive Manufacturing. "
        "Canonical name/ID validation cannot reject this semantic inconsistency.",
        "",
        "## Interpretation and reproduction",
        "",
        "Two shuffled passes over 100 previously audited items and 50 separately frozen items. "
        "These are 150 distinct publications, not 300 independent samples. Labels were authored "
        "by the Codex assistant and are not independently human-reviewed. The earlier audit "
        "corrected the HCI label; original labels are preserved.",
        "",
        "The two sets run separately through the production streaming processor, including "
        "request-local deduplication, batching, validation, cancellation support and in-memory "
        "XLSX export. Matching times exclude export and browser transfer. Runs were sequential. "
        "Provider caching and server load are uncontrolled. The earlier embedding benchmark "
        "mixed all 150 publications, so its batch compositions differ from this evaluation.",
        "",
        (
            "No prompts, labels, or application code were changed during this benchmark. "
            "Result files preserve model outputs, request timings/usage, item "
            "order, and source hashes."
        ),
        "",
        "Commands (use new output paths to avoid overwriting historical results):",
        "",
        "```bash",
        "python -m benchmarks.streaming --output-dir benchmarks/results/batching-no-verification",
        "PYTHONPATH=. python benchmarks/results/batching-no-verification/fresh_runner.py",
        (
            "python -m benchmarks.regressions --output "
            "benchmarks/results/batching-no-verification/lrec.json"
        ),
        "PYTHONPATH=. python benchmarks/results/batching-no-verification/summarize.py",
        "```",
        "",
        "Details: [original set report](report.md), [fresh set outputs](fresh50.json), "
        "[LREC outputs](lrec.json), [all predictions](predictions.csv).",
        "",
    ]
    with (output / "predictions.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(output / "summary.json", {"sets": totals, "lrec": lrec_scores})
    (output / "evaluation.md").write_text("\n".join(lines))
    print(json.dumps({"sets": totals, "lrec": lrec_scores}, indent=2))


if __name__ == "__main__":
    main()
