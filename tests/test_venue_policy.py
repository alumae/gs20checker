import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.catalogue import Catalogue
from app.matching import VENUE_IDENTITY_RULES, request_kwargs, validate_result
from benchmarks.policy import POLICY_PATH, apply_policy, load_current_dataset
from benchmarks.report import apply_audit
from benchmarks.streaming import workbook_inputs
from benchmarks.venue_matching import score


def test_streaming_benchmark_uses_current_xlsx_inputs_without_changing_labels():
    catalogue = Catalogue.load("data/venues.json")
    dataset, _ = load_current_dataset("benchmarks/testset.json", catalogue)
    original = deepcopy(dataset)
    content = Path(dataset["source"]).read_bytes()
    current, sheets = workbook_inputs(dataset, content)
    assert dataset == original
    assert len(current["items"]) == 100
    for old, new in zip(original["items"], current["items"], strict=True):
        assert new["sheet"] in sheets
        assert new["fields"] == {"reference": old["fields"]["reference"]}
        assert {k: v for k, v in new.items() if k != "fields"} == {
            k: v for k, v in old.items() if k != "fields"
        }
    with pytest.raises(ValueError, match="Source workbook has changed"):
        workbook_inputs(dataset, b"changed")


def test_policy_overlay_changes_demo_only_after_hci_audit():
    catalogue = Catalogue.load("data/venues.json")
    raw = Path("benchmarks/testset.json").read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    audited = apply_audit(
        json.loads(raw),
        source_hash,
        json.loads(Path("benchmarks/annotation_audit.json").read_text()),
    )
    untouched = deepcopy(audited)
    current, _ = load_current_dataset("benchmarks/testset.json", catalogue)
    old_ids = {i["id"]: i["expected_venue_id"] for i in audited["items"]}
    new_ids = {i["id"]: i["expected_venue_id"] for i in current["items"]}
    assert {key for key in old_ids if old_ids[key] != new_ids[key]} == {"etis-0967"}
    assert new_ids["etis-0967"] == "06d3be002d15cce64615"
    assert new_ids["etis-1141"] == "df767d1ca593ed3a4c98"
    assert sum(v is not None for v in new_ids.values()) == 36
    for item in current["items"]:
        assert item["fields"] == next(
            i["fields"] for i in audited["items"] if i["id"] == item["id"]
        )
    assert audited == untouched
    predictions = {
        key: {"status": "matched" if value else "unmatched", "venue_id": value}
        for key, value in old_ids.items()
    }
    assert score(audited["items"], predictions)["correct"] == 100
    assert score(current["items"], predictions)["correct"] == 99
    assert old_ids["etis-0116"] is new_ids["etis-0116"] is None  # Workshop exclusion preserved.


def test_punctuation_tolerance_does_not_relabel_absent_journals():
    catalogue = Catalogue.load("data/venues.json")
    current, _ = load_current_dataset("benchmarks/fresh50.json", catalogue)
    original = json.loads(Path("benchmarks/fresh50.json").read_text())
    assert current["items"] == original["items"]
    cases = json.loads(Path("benchmarks/regressions/venue-policy.json").read_text())["items"]
    by_id = {i["id"]: i for i in cases}
    for key in ("speech-missing", "speech-entity", "biomass-missing", "security-missing"):
        assert by_id[key]["expected_venue_id"] in catalogue.venues
    for key in ("materials-science", "materials-design", "unlisted-workshop", "companion-workshop"):
        assert by_id[key]["expected_venue_id"] is None
    assert by_id["listed-workshop"]["expected_venue_id"] in catalogue.venues


def test_policy_rejects_stale_sources_and_unexpected_labels():
    raw = Path("benchmarks/testset.json").read_bytes()
    dataset = json.loads(raw)
    policy = json.loads(POLICY_PATH.read_text())
    with pytest.raises(ValueError, match="different frozen"):
        apply_policy(dataset, "changed", policy)
    source_hash = hashlib.sha256(raw).hexdigest()
    stale = deepcopy(dataset)
    stale["catalogue_version"] = "changed"
    with pytest.raises(ValueError, match="catalogue"):
        apply_policy(stale, source_hash, policy)
    next(i for i in dataset["items"] if i["id"] == "etis-0967")["expected_venue_id"] = "unexpected"
    with pytest.raises(ValueError, match="unexpected original label"):
        apply_policy(dataset, source_hash, policy)


def test_all_request_modes_share_policy_without_weakening_output_validation(catalogue):
    fields = {"journal": "Computer Speech amp; Language"}
    first = next(iter(catalogue.venues))
    candidate = catalogue.candidates.entries[first].prompt_entry()
    requests = [
        request_kwargs(catalogue, "test", reference=json.dumps(fields)),
        request_kwargs(catalogue, "test", items=[{"id": "a", "fields": fields}]),
        request_kwargs(catalogue, "test", reference=json.dumps(fields), candidates=[candidate]),
    ]
    for request in requests:
        assert VENUE_IDENTITY_RULES in request["input"][0]["content"]
        assert "Computer Speech amp; Language" in request["input"][-1]["content"]
        assert request["text"]["format"]["strict"] is True
    with pytest.raises(ValueError, match="name and ID disagree"):
        validate_result(
            {
                "matched": True,
                "venue_id": first,
                "venue_name": "Wrong punctuation",
                "note": "Approximate title",
            },
            catalogue,
        )
