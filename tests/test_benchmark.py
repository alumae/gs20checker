import hashlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.catalogue import Catalogue
from benchmarks.build_testset import build
from benchmarks.report import apply_audit, generate
from benchmarks.venue_matching import batch_request, make_schedule, score, validate_batch


def response(results, status="completed"):
    return SimpleNamespace(status=status, output_text=json.dumps({"results": results}))


def test_batch_maps_ids_not_positions(catalogue):
    venue = next(iter(catalogue.venues))
    items = [{"id": "a"}, {"id": "b"}]
    results = [
        {"id": "b", "matched": False, "venue_id": None, "venue_name": None, "note": "Not listed"},
        {
            "id": "a",
            "matched": True,
            "venue_id": venue,
            "venue_name": catalogue.venues[venue]["name"],
            "note": "Recognized",
        },
    ]
    parsed = validate_batch(response(results), items, catalogue)
    assert parsed["a"]["venue_id"] == venue
    assert parsed["b"]["matched"] is False


@pytest.mark.parametrize("problem", ["missing", "duplicate", "unknown", "venue", "type", "extra"])
def test_invalid_batch_rejects_whole_request(catalogue, problem):
    results = [
        {"id": "a", "matched": False, "venue_id": None, "venue_name": None, "note": "Not listed"},
        {"id": "b", "matched": False, "venue_id": None, "venue_name": None, "note": "Not listed"},
    ]
    if problem == "missing":
        results.pop()
    elif problem == "duplicate":
        results[1]["id"] = "a"
    elif problem == "unknown":
        results[1]["id"] = "invented"
    elif problem == "venue":
        results[1].update(matched=True, venue_id="invented")
    elif problem == "type":
        results[1]["matched"] = "false"
    else:
        results[1]["rank"] = 1
    with pytest.raises(ValueError):
        validate_batch(response(results), [{"id": "a"}, {"id": "b"}], catalogue)


@pytest.mark.parametrize(
    "status,output",
    [
        ("incomplete", "{}"),
        ("completed", ""),
        ("completed", "[]"),
        ("completed", '{"results":{}}'),
    ],
)
def test_invalid_batch_envelope(catalogue, status, output):
    with pytest.raises(ValueError):
        validate_batch(SimpleNamespace(status=status, output_text=output), [{"id": "a"}], catalogue)


def test_batch_never_sends_annotations(catalogue):
    def create(**kwargs):
        inputs = kwargs["input"]
        assert catalogue.prompt in inputs[0]["content"]
        assert json.loads(inputs[-1]["content"]) == [{"id": "a", "fields": {"journal": "Test"}}]
        assert "SECRET-GOLD" not in json.dumps(kwargs)
        assert kwargs["store"] is False
        assert kwargs["max_output_tokens"] == 2000
        return response(
            [{"id": "a", "matched": False, "venue_id": None, "venue_name": None, "note": "Absent"}]
        )

    items = [{"id": "a", "fields": {"journal": "Test"}, "rationale": "SECRET-GOLD"}]
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    assert batch_request(client, catalogue, "test", items)["a"]["matched"] is False


def test_paired_schedule():
    items = [{"id": str(i)} for i in range(100)]
    schedule = make_schedule(items, seed=42)
    assert [r["method"] for r in schedule] == ["single", "batch", "batch", "single"]
    assert [len(r["groups"]) for r in schedule] == [100, 10, 10, 100]
    orders = [[i["id"] for group in r["groups"] for i in group] for r in schedule]
    assert orders[0] == orders[1]
    assert orders[2] == orders[3]
    assert orders[0] != orders[2]
    assert all(sorted(order) == sorted(i["id"] for i in items) for order in orders)


def test_scores_do_not_drop_errors_or_confuse_wrong_venues():
    expected = [None, "v", None, "v", "v", None, "v", None]
    items = [{"id": str(i), "expected_venue_id": v} for i, v in enumerate(expected)]
    actual = [None, "v", "v", None, "other"]
    predictions = {str(i): {"status": "matched", "venue_id": v} for i, v in enumerate(actual)}
    predictions.update({"5": {"status": "error"}, "6": {"status": "error"}})
    result = score(items, predictions)
    assert result["exact_accuracy"] == 2 / 8
    assert result["wrong_venue"] == result["false_positive"] == result["false_negative"] == 1
    assert result["errors"] == 2
    assert result["missing"] == 1
    assert result["match_precision"] == result["match_recall"] == 2 / 3


def test_frozen_annotations_reproduce_source_and_selection():
    frozen = json.loads(Path("benchmarks/testset.json").read_text())
    rebuilt = build()
    rebuilt["frozen_at"] = frozen["frozen_at"]
    assert rebuilt == frozen
    assert Counter(i["subset"] for i in frozen["items"]) == {"random": 80, "challenge": 20}
    assert sum(i["policy_sensitive"] for i in frozen["items"]) == 1
    catalogue = Catalogue.load("data/venues.json")
    for item in frozen["items"]:
        if item["expected_venue_id"]:
            assert catalogue.venues[item["expected_venue_id"]]["name"] == item["expected_venue"]
    original = deepcopy(frozen["items"])
    make_schedule(frozen["items"], seed=42)
    assert frozen["items"] == original


def test_report_counts_failures_and_preserves_all_item_predictions(tmp_path):
    dataset_path = Path("benchmarks/testset.json")
    raw = dataset_path.read_bytes()
    items = json.loads(raw)["items"]
    predictions = {
        item["id"]: {
            "status": "matched" if item["expected_venue_id"] else "unmatched",
            "venue_id": item["expected_venue_id"],
            "venue": item["expected_venue"] or "",
            "note": "Test prediction",
        }
        for item in items
    }
    predictions[items[0]["id"]] = {"status": "error", "error": {"message": "Test failure"}}
    state = {
        "status": "running",
        "started_at": "test",
        "config": {"testset_sha256": hashlib.sha256(raw).hexdigest(), "model": "test"},
        "rounds": [
            {
                "pass": 1,
                "method": "batch",
                "complete": True,
                "segments": 1,
                "active_elapsed_seconds": 10,
                "records": [
                    {
                        "predictions": predictions,
                        "seconds": 9,
                        "http_attempts": 2,
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 10,
                            "input_tokens_details": {"cached_tokens": 90},
                        },
                    }
                ],
            }
        ],
    }
    result_path = tmp_path / "run.json"
    result_path.write_text(json.dumps(state))
    generate(result_path, dataset_path, tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text())["rounds"][0]
    assert summary["scores"]["all"]["correct"] == 99
    assert summary["scores"]["all"]["errors"] == 1
    assert summary["retries"] == 1
    assert summary["tokens"]["cached_input"] == 90
    assert summary["seconds_per_publication"] == 0.1
    import csv

    with (tmp_path / "predictions.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 100
    assert rows[0]["correct"] == "False"
    assert "Test failure" in rows[0]["note"]
    assert "99/100" in (tmp_path / "report.md").read_text()


def test_annotation_audit_is_explicit_and_does_not_rewrite_frozen_labels():
    raw = Path("benchmarks/testset.json").read_bytes()
    dataset = json.loads(raw)
    original = deepcopy(dataset)
    audit = json.loads(Path("benchmarks/annotation_audit.json").read_text())
    reviewed = apply_audit(dataset, hashlib.sha256(raw).hexdigest(), audit)
    original_item = next(i for i in dataset["items"] if i["id"] == "etis-1141")
    reviewed_item = next(i for i in reviewed["items"] if i["id"] == "etis-1141")
    assert original_item["expected_venue_id"] is None
    assert reviewed_item["expected_venue"] == "HCI International"
    assert reviewed["post_prediction_audit"] == audit
    assert dataset == original
    assert sum(i["expected_venue_id"] is not None for i in reviewed["items"]) == 35
    catalogue = Catalogue.load("data/venues.json")
    assert catalogue.venues[reviewed_item["expected_venue_id"]]["name"] == "HCI International"
    with pytest.raises(ValueError, match="different frozen test set"):
        apply_audit(dataset, "changed", audit)
