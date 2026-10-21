"""Repeat the reported LREC case through production single and batched matching."""

import argparse
import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import openai
from dotenv import load_dotenv

from app.catalogue import Catalogue
from app.matching import PROMPT_VERSION, AsyncMatcher, Matcher
from app.workbooks import extract_rows
from benchmarks.streaming import RecordingClient
from benchmarks.venue_matching import write_json


def run(output):
    load_dotenv(".env")
    case = json.loads(Path("benchmarks/regressions/lillepalu-lrec.json").read_text())
    content = Path(case["source"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != case["source_sha256"]:
        raise ValueError("Regression source workbook has changed")
    rows, _ = extract_rows(content)
    position = next(
        i
        for i, row in enumerate(rows)
        if row["sheet"] == case["sheet"] and row["row"] == case["row"]
    )
    if rows[position]["fields"] != {"reference": case["fields"]["reference"]}:
        raise ValueError("Regression extraction has changed")
    offset = position // 10 * 10
    items = [
        {"id": str(offset + i), "fields": row["fields"]}
        for i, row in enumerate(rows[offset : offset + 10])
    ]
    catalogue = Catalogue.load("data/venues.json")
    model = os.getenv("OPENAI_MODEL", "gpt-6-luna")
    key = os.environ["OPENAI_API_KEY"]
    if output.exists():
        raise ValueError("Choose a new report path; existing results are preserved")
    output.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "candidate_verification": False,
        "workbook_input_fields": ["reference"],
        "status": "running",
        "case": case,
        "original_batch": items,
        "runs": [],
        "code_sha256": {
            name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
            for name in ("app/matching.py", "app/candidates.py", "app/workbooks.py")
        },
    }
    with openai.OpenAI(api_key=key, timeout=30, max_retries=0) as client:
        client.models.retrieve(model)
    for repetition in range(1, 6):
        for method in ("single", "batch"):
            started = time.perf_counter()
            if method == "single":
                matcher = Matcher(catalogue, model, api_key=key)
                try:
                    result = matcher.match(case["plain_reference"])
                finally:
                    matcher.close()
                fallbacks = 0
            else:

                async def batch():
                    recorder = RecordingClient(key)
                    engine = AsyncMatcher(catalogue, model, client=recorder)
                    try:
                        results = await engine.match_batch(items)
                        return results[str(position)], engine
                    finally:
                        await engine.close()

                result, matcher = asyncio.run(batch())
                fallbacks = matcher.fallbacks
            record = {
                "repetition": repetition,
                "method": method,
                "result": result,
                "correct": result.get("venue_id") == case["expected_venue_id"],
                "seconds": time.perf_counter() - started,
                "requests": matcher.requests,
                "verifications": matcher.verifications,
                "fallbacks": fallbacks,
            }
            state["runs"].append(record)
            write_json(output, state)
            print(
                f"LREC {method} {repetition}/5: "
                f"{'correct' if record['correct'] else 'INCORRECT'}; "
                f"requests={matcher.requests}; verifications={matcher.verifications}",
                flush=True,
            )
    state["status"] = "passed" if all(r["correct"] for r in state["runs"]) else "failed"
    state["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(output, state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
