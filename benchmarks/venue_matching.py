"""Run a reproducible, sequential single-vs-batched Responses API benchmark."""

import argparse
import hashlib
import json
import os
import platform
import random
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import httpx
import openai
from dotenv import load_dotenv

from app.catalogue import Catalogue, digest
from app.matching import (
    INSTRUCTIONS,
    PROMPT_VERSION,
    SCHEMA,
    Matcher,
    service_error_message,
    validate_result,
)

BATCH_INSTRUCTIONS = """The user supplies a JSON array of independent publications, each with
an id and fields. Apply the venue-matching rules independently to every publication.
Return a results array with exactly one result per supplied id. Copy each id exactly.
Never transfer evidence or a venue from one publication to another. Include every id,
including publications with no match.
Each result contains id, matched, venue_id, venue_name, note."""
BATCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"id": {"type": "string"}, **SCHEMA["properties"]},
                "required": ["id", *SCHEMA["required"]],
            },
        },
    },
    "required": ["results"],
}


def validate_batch(response, items, catalogue):
    if response.status != "completed":
        raise ValueError("Incomplete batch response")
    payload = json.loads(response.output_text)
    if not isinstance(payload, dict) or set(payload) != {"results"}:
        raise ValueError("Unexpected batch fields")
    if not isinstance(payload["results"], list):
        raise ValueError("Batch results must be an array")
    expected = {item["id"] for item in items}
    if len(expected) != len(items):
        raise ValueError("Duplicate input IDs")
    results = {}
    for result in payload["results"]:
        if not isinstance(result, dict) or set(result) != {"id", *SCHEMA["required"]}:
            raise ValueError("Unexpected result fields")
        item_id = result["id"]
        if not isinstance(item_id, str) or item_id not in expected or item_id in results:
            raise ValueError("Unknown or duplicate result ID")
        results[item_id] = validate_result(
            {k: v for k, v in result.items() if k != "id"}, catalogue
        )
    if set(results) != expected:
        raise ValueError("Missing result IDs")
    return results


def batch_request(client, catalogue, model, items):
    response = client.responses.create(
        model=model,
        input=[
            {"role": "developer", "content": INSTRUCTIONS + catalogue.prompt},
            {"role": "developer", "content": BATCH_INSTRUCTIONS},
            {
                "role": "user",
                "content": json.dumps(
                    [{"id": item["id"], "fields": item["fields"]} for item in items],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "venue_matches",
                "strict": True,
                "schema": BATCH_SCHEMA,
            }
        },
        reasoning={"effort": "low"},
        max_output_tokens=2000 * len(items),
        store=False,
    )
    return validate_batch(response, items, catalogue)


class Recorder:
    """Capture model usage and SDK HTTP attempts without logging requests/secrets."""

    def __init__(self):
        self.client = None
        self.responses = self
        self.attempts = 0
        self.last = {}

    def on_request(self, request):
        self.attempts += 1

    def create(self, **kwargs):
        self.attempts = 0
        self.last = {}
        started = time.perf_counter()
        try:
            response = self.client.responses.create(**kwargs)
            self.last.update(
                {
                    "usage": response.usage.model_dump() if response.usage else None,
                    "response_model": response.model,
                    "response_status": response.status,
                    "output_text": response.output_text,
                }
            )
            return response
        finally:
            self.last.update(
                {
                    "api_seconds": time.perf_counter() - started,
                    "http_attempts": self.attempts,
                }
            )


def failure_details(exc):
    cause = exc.__cause__ or exc
    fatal = isinstance(
        cause,
        (
            openai.AuthenticationError,
            openai.PermissionDeniedError,
            openai.NotFoundError,
            openai.BadRequestError,
        ),
    ) or (isinstance(cause, openai.RateLimitError) and cause.code == "insufficient_quota")
    return {
        "type": type(cause).__name__,
        "http_status": cause.status_code if isinstance(cause, openai.APIStatusError) else None,
        "message": service_error_message(cause),
        "fatal": fatal,
    }


def load_testset(path, catalogue):
    content = Path(path).read_bytes()
    data = json.loads(content)
    if data["catalogue_version"] != catalogue.version:
        raise ValueError("Test-set catalogue differs from the requested catalogue")
    items = data["items"]
    if len(items) != 100 or len({item["id"] for item in items}) != 100:
        raise ValueError("Expected 100 distinct test items")
    for item in items:
        venue_id = item["expected_venue_id"]
        if venue_id is not None and venue_id not in catalogue.venues:
            raise ValueError("Annotation references an unknown venue")
        if not item["rationale"] or not item["evidence"] or not item["fields"]:
            raise ValueError("Missing annotation evidence or input")
    return data, hashlib.sha256(content).hexdigest()


def make_schedule(items, seed, passes=2, batch_size=10):
    schedule = []
    for pass_index in range(passes):
        ordered = list(items)
        random.Random(seed + pass_index).shuffle(ordered)
        methods = ["single", "batch"] if pass_index % 2 == 0 else ["batch", "single"]
        for method in methods:
            size = 1 if method == "single" else batch_size
            schedule.append(
                {
                    "pass": pass_index + 1,
                    "method": method,
                    "groups": [ordered[i : i + size] for i in range(0, len(ordered), size)],
                }
            )
    return schedule


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def score(items, predictions):
    counts = {
        key: 0
        for key in (
            "correct",
            "true_positive",
            "true_negative",
            "false_positive",
            "false_negative",
            "wrong_venue",
            "errors",
            "missing",
            "positive_errors",
            "negative_errors",
        )
    }
    for item in items:
        expected = item["expected_venue_id"]
        result = predictions.get(item["id"])
        if result is None:
            counts["missing"] += 1
            continue
        if result["status"] == "error":
            counts["errors"] += 1
            counts["positive_errors" if expected is not None else "negative_errors"] += 1
            continue
        actual = result["venue_id"]
        counts["correct"] += actual == expected
        if expected is None:
            counts["true_negative" if actual is None else "false_positive"] += 1
        elif actual is None:
            counts["false_negative"] += 1
        else:
            counts["true_positive"] += 1
            counts["wrong_venue"] += actual != expected
    tp, fp, fn = (counts[key] for key in ("true_positive", "false_positive", "false_negative"))
    return {
        "n": len(items),
        **counts,
        "exact_accuracy": counts["correct"] / len(items) if items else None,
        "match_precision": tp / (tp + fp) if tp + fp else None,
        "match_recall": tp / (tp + fn) if tp + fn else None,
    }


def run(args):
    load_dotenv(".env")
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-6-luna")
    catalogue = Catalogue.load(args.catalogue)
    dataset, dataset_hash = load_testset(args.testset, catalogue)
    source = Path(dataset["source"])
    if (
        source.exists()
        and hashlib.sha256(source.read_bytes()).hexdigest() != dataset["source_sha256"]
    ):
        raise ValueError("Source workbook changed after annotation")
    config = {
        "model": model,
        "catalogue_version": catalogue.version,
        "testset_sha256": dataset_hash,
        "prompt_version": PROMPT_VERSION,
        "request_definition_hash": digest([INSTRUCTIONS, SCHEMA, BATCH_INSTRUCTIONS, BATCH_SCHEMA]),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "matcher_sha256": hashlib.sha256(Path("app/matching.py").read_bytes()).hexdigest(),
        "passes": args.passes,
        "batch_size": args.batch_size,
        "order_seed": args.seed,
        "timeout_seconds": 45,
        "max_retries": 2,
        "reasoning_effort": "low",
        "output_tokens_per_item": 2000,
        "store": False,
        "concurrency": 1,
        "local_result_cache": False,
        "python": platform.python_version(),
        "openai_version": openai.__version__,
    }
    output = Path(args.output)
    if output.exists():
        if not args.resume:
            raise ValueError("Results already exist; choose a new output or use --resume")
        state = json.loads(output.read_text())
        if state["config"] != config:
            raise ValueError("Cannot resume: benchmark configuration or code changed")
        if state.get("status") == "complete":
            print("Already complete; no API requests made.")
            return
    else:
        state = {
            "config": config,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
            "rounds": [],
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    recorder = Recorder()
    with httpx.Client(event_hooks={"request": [recorder.on_request]}) as http_client:
        with openai.OpenAI(timeout=45, max_retries=2, http_client=http_client) as client:
            recorder.client = client
            try:
                client.models.retrieve(model)
            except openai.OpenAIError as exc:
                state.update(status="blocked", preflight_error=failure_details(exc))
                write_json(output, state)
                print(state["preflight_error"]["message"], flush=True)
                return
            state.pop("preflight_error", None)
            state["status"] = "running"
            with closing(Matcher(catalogue, model, client=recorder)) as matcher:
                schedule = make_schedule(dataset["items"], args.seed, args.passes, args.batch_size)
                for index, entry in enumerate(schedule):
                    if len(state["rounds"]) <= index:
                        state["rounds"].append(
                            {
                                "pass": entry["pass"],
                                "method": entry["method"],
                                "order": [
                                    item["id"] for group in entry["groups"] for item in group
                                ],
                                "records": [],
                                "active_elapsed_seconds": 0,
                                "segments": 0,
                            }
                        )
                    result = state["rounds"][index]
                    completed = len(result["records"])
                    if completed == len(entry["groups"]):
                        continue
                    result["segments"] += 1
                    started = time.perf_counter()
                    prior_elapsed = result["active_elapsed_seconds"]
                    for group in entry["groups"][completed:]:
                        call_started = time.perf_counter()
                        error = None
                        try:
                            if entry["method"] == "single":
                                item = group[0]
                                reference = json.dumps(
                                    item["fields"], ensure_ascii=False, sort_keys=True
                                )
                                # Initial request only, before candidate verification.
                                predictions = {item["id"]: matcher._request(reference)}
                            else:
                                predictions = batch_request(recorder, catalogue, model, group)
                        except Exception as exc:
                            error = failure_details(exc)
                            predictions = {
                                item["id"]: {"status": "error", "error": error} for item in group
                            }
                        result["records"].append(
                            {
                                "ids": [item["id"] for item in group],
                                "predictions": predictions,
                                "seconds": time.perf_counter() - call_started,
                                "error": error,
                                **recorder.last,
                            }
                        )
                        result["active_elapsed_seconds"] = (
                            prior_elapsed + time.perf_counter() - started
                        )
                        write_json(output, state)
                        print(
                            f"Pass {entry['pass']} {entry['method']}: "
                            f"{len(result['records'])}/{len(entry['groups'])} requests; "
                            f"{result['records'][-1]['seconds']:.2f}s; "
                            f"{'ERROR' if error else 'OK'}",
                            flush=True,
                        )
                        if error and error["fatal"]:
                            state["status"] = "blocked"
                            write_json(output, state)
                            print(error["message"], flush=True)
                            return
                    result["active_elapsed_seconds"] = prior_elapsed + time.perf_counter() - started
                    result["complete"] = True
                    write_json(output, state)
    state.update(status="complete", finished_at=datetime.now(timezone.utc).isoformat())
    write_json(output, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--testset", default="benchmarks/testset.json")
    parser.add_argument("--catalogue", default="data/venues.json")
    parser.add_argument("--output", default="benchmarks/results/run.json")
    parser.add_argument("--model")
    parser.add_argument("--passes", type=int, default=2, choices=range(1, 5))
    parser.add_argument("--batch-size", type=int, default=10, choices=range(2, 21))
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        run(args)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Benchmark could not start: {exc}\n")


if __name__ == "__main__":
    main()
