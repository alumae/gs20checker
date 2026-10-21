"""Evaluate the production streaming processor using the current venue policy."""

import argparse
import hashlib
import json
import math
import os
import random
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import httpx
import openai
from dotenv import load_dotenv

from app.catalogue import Catalogue
from app.matching import PROMPT_VERSION, AsyncMatcher, service_error_message
from app.processing import process_workbook
from app.workbooks import extract_rows
from benchmarks.policy import POLICY_PATH, load_current_dataset
from benchmarks.venue_matching import score, write_json


class RecordingClient:
    def __init__(self, api_key):
        self.attempts = 0
        self.calls = []
        self.responses = self
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            timeout=45,
            max_retries=2,
            http_client=httpx.AsyncClient(event_hooks={"request": [self.on_request]}),
        )

    async def on_request(self, request):
        self.attempts += 1

    async def create(self, **kwargs):
        started = time.perf_counter()
        previous_attempts = self.attempts
        record = {
            "batch": kwargs["text"]["format"]["name"] == "venue_matches",
            "verification": kwargs["text"]["format"]["name"] == "venue_verification",
        }
        try:
            result = await self.client.responses.create(**kwargs)
            record.update(
                usage=result.usage.model_dump() if result.usage else None,
                output_text=result.output_text,
                model=result.model,
            )
            return result
        except Exception as exc:
            record["error"] = type(exc).__name__
            raise
        finally:
            record.update(
                seconds=time.perf_counter() - started,
                http_attempts=self.attempts - previous_attempts,
            )
            self.calls.append(record)

    async def close(self):
        await self.client.close()


def workbook_inputs(dataset, content):
    """Use current XLSX extraction with frozen labels, never historical input fields."""
    if hashlib.sha256(content).hexdigest() != dataset["source_sha256"]:
        raise ValueError("Source workbook has changed")
    rows, sheets = extract_rows(content)
    by_row = {(row["sheet"], row["row"]): row["fields"] for row in rows}
    current = deepcopy(dataset)
    for item in current["items"]:
        item["fields"] = deepcopy(by_row[(item["sheet"], item["row"])])
    return current, sheets


def run(output, testset=Path("benchmarks/testset.json"), baseline=None):
    load_dotenv(".env")
    key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-6-luna")
    catalogue = Catalogue.load("data/venues.json")
    dataset, source_hash = load_current_dataset(testset, catalogue)
    count = len(dataset["items"])
    content = Path(dataset["source"]).read_bytes()
    dataset, sheets = workbook_inputs(dataset, content)
    if output.exists():
        raise ValueError(
            "Choose a new output directory; historical results will not be overwritten"
        )
    # Read-only preflight; no predictions before confirming access.
    with openai.OpenAI(api_key=key, timeout=30, max_retries=0) as preflight:
        preflight.models.retrieve(model)
    output.mkdir(parents=True)
    state = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "candidate_verification": False,
        "input_source": "Current XLSX extraction: unchanged Lühikirje text only",
        "status": "running",
        "rounds": [],
        "frozen_testset_sha256": source_hash,
        "catalogue_version": catalogue.version,
        "annotation_audit": dataset.get("post_prediction_audit"),
        "venue_policy": dataset["venue_policy"],
        "policy_sha256": hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest(),
        "testset": str(testset),
        "code_sha256": {
            name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
            for name in (
                "app/matching.py",
                "app/processing.py",
                "app/workbooks.py",
                "app/candidates.py",
                "benchmarks/streaming.py",
            )
        },
    }
    write_json(output / "labels.json", dataset)
    by_row = {(i["sheet"], i["row"]): i["id"] for i in dataset["items"]}
    for pass_index in range(2):
        items = deepcopy(dataset["items"])
        random.Random(20261019 + pass_index).shuffle(items)
        rows = [
            {"sheet": i["sheet"], "row": i["row"], "fields": i["fields"], "result": None}
            for i in items
        ]
        recorder = RecordingClient(key)
        matcher = AsyncMatcher(catalogue, model, client=recorder)
        predictions = {}
        started = time.perf_counter()
        result = {
            "pass": pass_index + 1,
            "order": [i["id"] for i in items],
            "predictions": predictions,
            "requests": recorder.calls,
            "complete": False,
        }
        stream = process_workbook(content, rows, sheets, catalogue, lambda: matcher)
        try:
            for line in stream:
                event = json.loads(line)
                if event["type"] == "progress":
                    for recent in event["recent"]:
                        predictions[by_row[(recent["sheet"], recent["row"])]] = recent
                    if event.get("phase") == "exporting":
                        result["matching_seconds"] = time.perf_counter() - started
                    else:
                        print(
                            f"Pass {pass_index + 1}: {len(predictions)}/{count}; "
                            f"fallbacks={matcher.fallbacks}; verifications={matcher.verifications}",
                            flush=True,
                        )
                elif event["type"] == "complete":
                    result["complete"] = True
                elif event["type"] == "error":
                    result["error"] = event["error"]
                    break
        finally:
            stream.close()
        result.update(
            total_seconds=time.perf_counter() - started,
            fallbacks=matcher.fallbacks,
            verifications=matcher.verifications,
            request_count=matcher.requests,
        )
        result["scores"] = {
            subset: score(
                [i for i in dataset["items"] if subset == "all" or i["subset"] == subset],
                predictions,
            )
            for subset in ("all", *sorted({i["subset"] for i in dataset["items"]}))
        }
        state["rounds"].append(result)
        write_json(output / "run.json", state)
        if not result["complete"]:
            state["status"] = "failed"
            break
    else:
        state["status"] = "complete"
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    correct = sum(r["scores"]["all"]["correct"] for r in state["rounds"])
    state["acceptance"] = {
        "minimum_exact_matches": math.ceil(2 * count * 0.98),
        "exact_matches": correct,
        "passed": state["status"] == "complete" and correct >= math.ceil(2 * count * 0.98),
    }
    write_json(output / "run.json", state)
    if baseline is not None:
        previous = json.loads(Path(baseline).read_text())
        for r in previous["rounds"]:
            if set(r["predictions"]) != {i["id"] for i in dataset["items"]}:
                raise ValueError("Baseline predictions do not cover this dataset")
        state["baseline_rescored"] = {
            "path": str(baseline),
            "sha256": hashlib.sha256(Path(baseline).read_bytes()).hexdigest(),
            "rounds": [
                {"pass": r["pass"], "scores": score(dataset["items"], r["predictions"])}
                for r in previous["rounds"]
            ],
        }
        write_json(output / "run.json", state)
    write_report(output, state, dataset)


def write_report(output, state, dataset):
    lines = [
        "# Current production batching validation",
        "",
        f"Model: `{state['model']}`; prompt {state['prompt_version']}; "
        f"venue policy {state['venue_policy']['version']}; status: **{state['status']}**.",
        "",
        f"Inputs: {state['input_source']}. Expected labels retain the reviewed venue identity; "
        "removing other source fields may remove evidence available to the model.",
        "",
        "Two shuffled passes through the production streaming processor, batches of ten, "
        "strict name/ID validation and malformed-output fallback. No candidate verification. "
        "Each pass exports the original workbook in memory. Matching times exclude export "
        "and browser transport; provider caching and load are uncontrolled.",
        "",
        "Companion tracks count as the main conference; workshops do not. Missing ETIS "
        "punctuation does not change venue identity. The policy overlay and earlier HCI "
        "audit are recorded in labels.json; original annotations and reports are preserved. "
        "These are repeated decisions, not independent samples. Labels are assistant-authored "
        "and not independently human-reviewed.",
        "",
        "| Pass | Correct | False + | False − | Wrong ID | Errors | "
        "Matching s | Calls | Fallbacks |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in state["rounds"]:
        s = r["scores"]["all"]
        lines.append(
            f"| {r['pass']} | {s['correct']}/{s['n']} | {s['false_positive']} | "
            f"{s['false_negative']} | {s['wrong_venue']} | {s['errors']} | "
            f"{r.get('matching_seconds', 0):.2f} | {r['request_count']} | {r['fallbacks']} |"
        )
    total = sum(r["scores"]["all"]["n"] for r in state["rounds"])
    correct = state["acceptance"]["exact_matches"]
    lines += [
        "",
        f"Combined: **{correct}/{total}**. "
        "Configured 98% accuracy threshold: "
        f"**{'passed' if state['acceptance']['passed'] else 'not met'}**.",
    ]
    if state.get("baseline_rescored"):
        prior = state["baseline_rescored"]
        scores = [r["scores"] for r in prior["rounds"]]
        lines += [
            "",
            f"Prior saved predictions from `{prior['path']}`, rescored under the "
            f"same NEW policy: **{sum(s['correct'] for s in scores)}/"
            f"{sum(s['n'] for s in scores)}**. This is a label-policy rescore, "
            "not a new run of the old model prompt. "
            "Historical reports retain their original scores.",
        ]
    lines += ["", "## Disagreements", ""]
    for r in state["rounds"]:
        for item in dataset["items"]:
            p = r["predictions"].get(item["id"])
            if not p or p["status"] == "error" or p.get("venue_id") != item["expected_venue_id"]:
                lines.append(
                    f"- Pass {r['pass']}, {item['id']}: expected "
                    f"{item['expected_venue'] or 'no match'}; returned "
                    f"{(p or {}).get('venue') or 'no match/error'}. "
                    f"{(p or {}).get('note', '')}"
                )
    (output / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("benchmarks/results/streaming"))
    parser.add_argument("--testset", type=Path, default=Path("benchmarks/testset.json"))
    parser.add_argument(
        "--baseline", type=Path, help="Rescore saved predictions under current policy"
    )
    args = parser.parse_args()
    try:
        run(args.output_dir, args.testset, args.baseline)
    except openai.OpenAIError as exc:
        parser.exit(1, service_error_message(exc) + "\n")
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")
