"""Evaluate the frozen fresh50 set through the current production streaming path."""

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
from app.processing import process_workbook
from app.workbooks import extract_rows
from benchmarks.streaming import RecordingClient
from benchmarks.venue_matching import score, write_json


def run():
    output = Path("benchmarks/results/batching-no-verification/fresh50.json")
    if output.exists():
        raise ValueError("Refusing to overwrite existing results")
    load_dotenv(".env")
    catalogue = Catalogue.load("data/venues.json")
    dataset_path = Path("benchmarks/fresh50.json")
    dataset = json.loads(dataset_path.read_text())
    content = Path(dataset["source"]).read_bytes()
    assert hashlib.sha256(content).hexdigest() == dataset["source_sha256"]
    assert catalogue.version == dataset["catalogue_version"]
    _, sheets = extract_rows(content)
    model = os.getenv("OPENAI_MODEL", "gpt-6-luna")
    state = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "candidate_verification": False,
        "status": "running",
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "catalogue_version": catalogue.version,
        "protocol": (
            "Two shuffled passes over the frozen 50 rows, batches of ten. "
            "Current production streaming path. Independent of the original 100-row run; "
            "historical embedding benchmark mixed all 150 rows."
        ),
        "code_sha256": {
            p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
            for p in ["app/matching.py", "app/processing.py", "app/workbooks.py"]
        },
        "rounds": [],
    }
    for n in range(2):
        items = list(dataset["items"])
        random.Random(20261019 + n).shuffle(items)
        by_row = {(i["sheet"], i["row"]): i["id"] for i in items}
        rows = [
            {"sheet": i["sheet"], "row": i["row"], "fields": i["fields"], "result": None}
            for i in items
        ]
        client = RecordingClient(os.environ["OPENAI_API_KEY"])
        matcher = AsyncMatcher(catalogue, model, client=client)
        result = {
            "pass": n + 1,
            "order": [i["id"] for i in items],
            "predictions": {},
            "requests": client.calls,
            "complete": False,
        }
        started = time.perf_counter()
        stream = process_workbook(content, rows, sheets, catalogue, lambda: matcher)
        try:
            for line in stream:
                event = json.loads(line)
                if event["type"] == "progress":
                    for recent in event["recent"]:
                        result["predictions"][by_row[(recent["sheet"], recent["row"])]] = recent
                    if event.get("phase") == "exporting":
                        result["matching_seconds"] = time.perf_counter() - started
                    else:
                        print(f"Fresh pass {n + 1}: {len(result['predictions'])}/50", flush=True)
                elif event["type"] == "complete":
                    result["complete"] = True
                elif event["type"] == "error":
                    result["error"] = event["error"]
                    break
        finally:
            stream.close()
        result.update(
            total_seconds=time.perf_counter() - started,
            request_count=matcher.requests,
            verifications=matcher.verifications,
            fallbacks=matcher.fallbacks,
            scores=score(items, result["predictions"]),
        )
        state["rounds"].append(result)
        write_json(output, state)
        if not result["complete"]:
            state["status"] = "failed"
            break
    else:
        state["status"] = "complete"
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(output, state)


if __name__ == "__main__":
    run()
