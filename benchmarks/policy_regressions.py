"""Run explicit venue-policy cases through single and batched production matching."""

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
from app.matching import (
    PROMPT_VERSION,
    AsyncMatcher,
    exact_journal_result,
    payload,
    validate_result,
)
from benchmarks.policy import POLICY_PATH
from benchmarks.streaming import RecordingClient
from benchmarks.venue_matching import score, write_json


async def run(
    output,
    path=Path("benchmarks/regressions/venue-policy.json"),
    modes=("single", "batch"),
    passes=1,
):
    if output.exists():
        raise ValueError("Choose a new output; historical results are preserved")
    load_dotenv(".env")
    catalogue = Catalogue.load("data/venues.json")
    dataset = json.loads(path.read_text())
    policy = json.loads(POLICY_PATH.read_text())
    if (
        dataset["catalogue_version"] != catalogue.version
        or dataset.get("policy_version", policy["version"]) != policy["version"]
    ):
        raise ValueError("Policy cases belong to another catalogue or venue policy")
    model = os.getenv("OPENAI_MODEL", "gpt-6-luna")
    state = {
        "status": "running",
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "dataset": dataset,
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "code_sha256": {
            name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
            for name in ("app/matching.py", "app/candidates.py", "benchmarks/policy_regressions.py")
        },
        "started_at": datetime.now(timezone.utc).isoformat(),
        "rounds": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    for pass_index, mode in ((p, m) for p in range(passes) for m in modes):
        client = RecordingClient(os.environ["OPENAI_API_KEY"])
        engine = AsyncMatcher(catalogue, model, client=client)
        items = list(dataset["items"])
        random.Random(20261022 + pass_index).shuffle(items)
        predictions = {}
        started = time.perf_counter()
        try:
            size = 1 if mode == "single" else 10
            for offset in range(0, len(items), size):
                group = items[offset : offset + size]
                if mode == "single":
                    # Same request construction and validation as synchronous Matcher.match;
                    # verification stays disabled, and no annotations enter the prompt.
                    exact = exact_journal_result(catalogue, group[0]["fields"])
                    if exact is not None:
                        predictions[group[0]["id"]] = exact
                        continue
                    response = await engine.request(reference=json.dumps(group[0]["fields"]))
                    try:
                        predictions[group[0]["id"]] = validate_result(payload(response), catalogue)
                    except (TypeError, ValueError):
                        predictions[group[0]["id"]] = {
                            "status": "error",
                            "note": "Invalid response",
                        }
                else:
                    predictions.update(await engine.match_batch(group))
                print(f"Policy {mode}: {len(predictions)}/{len(items)}", flush=True)
        finally:
            await client.close()
        state["rounds"].append(
            {
                "method": mode,
                "pass": pass_index + 1,
                "seconds": time.perf_counter() - started,
                "scores": score(items, predictions),
                "predictions": predictions,
                "requests": client.calls,
                "fallbacks": engine.fallbacks,
                "verifications": engine.verifications,
            }
        )
        write_json(output, state)
    state["status"] = "complete"
    write_json(output, state)
    lines = [
        "# Venue matching regression results",
        "",
        "Assistant-authored policy checks; synthetic examples are marked in the dataset. "
        "These are targeted regressions, not an independent accuracy sample.",
        "",
    ]
    for r in state["rounds"]:
        s = r["scores"]
        lines += [
            f"{r['method']}: **{s['correct']}/{s['n']}** correct; "
            f"{r['verifications']} verification calls.",
            "",
        ]
        for item in dataset["items"]:
            p = r["predictions"][item["id"]]
            if p["status"] == "error" or p.get("venue_id") != item["expected_venue_id"]:
                lines.append(
                    f"- {item['id']}: expected {item['expected_venue'] or 'no match'}; "
                    f"returned {p.get('venue') or 'no match/error'}. {p.get('note', '')}"
                )
    output.with_suffix(".md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--testset", type=Path, default=Path("benchmarks/regressions/venue-policy.json")
    )
    parser.add_argument("--mode", choices=("single", "batch", "both"), default="both")
    parser.add_argument("--passes", type=int, choices=range(1, 6), default=1)
    args = parser.parse_args()
    modes = ("single", "batch") if args.mode == "both" else (args.mode,)
    asyncio.run(run(args.output, args.testset, modes, args.passes))
