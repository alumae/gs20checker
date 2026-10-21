"""Apply explicit venue policy changes without rewriting frozen annotations."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from benchmarks.report import apply_audit

POLICY_PATH = Path("benchmarks/venue_policy.json")


def apply_policy(dataset, source_hash, policy):
    if source_hash not in policy["dataset_sha256"].values():
        raise ValueError("Policy belongs to different frozen datasets")
    if dataset["catalogue_version"] != policy["catalogue_version"]:
        raise ValueError("Policy catalogue differs from the annotated snapshot")
    reviewed = deepcopy(dataset)
    by_id = {i["id"]: i for i in reviewed["items"]}
    seen = set()
    for change in policy["changes"]:
        if change["id"] in seen:
            raise ValueError("Duplicate policy change")
        seen.add(change["id"])
        if change["id"] not in by_id:
            continue
        item = by_id[change["id"]]
        if item["expected_venue_id"] != change["previous_expected_venue_id"]:
            raise ValueError("Policy change has an unexpected original label")
        for key in ("expected_venue_id", "expected_venue", "resolved_venue", "rationale"):
            item[key] = change[key]
        item["evidence"] += change["evidence"]
        item["policy_sensitive"] = False  # The user has now resolved this policy question.
    reviewed["venue_policy"] = policy
    reviewed["policy"] = " ".join(policy["rules"])
    return reviewed


def load_current_dataset(path, catalogue):
    raw = Path(path).read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    dataset = json.loads(raw)
    audit = json.loads(Path("benchmarks/annotation_audit.json").read_text())
    if source_hash == audit["original_testset_sha256"]:
        dataset = apply_audit(dataset, source_hash, audit)
    policy = json.loads(POLICY_PATH.read_text())
    dataset = apply_policy(dataset, source_hash, policy)
    if dataset["catalogue_version"] != catalogue.version:
        raise ValueError("Dataset catalogue differs from the requested catalogue")
    for item in dataset["items"]:
        venue_id = item["expected_venue_id"]
        if venue_id is not None and catalogue.venues[venue_id]["name"] != item["expected_venue"]:
            raise ValueError("Policy venue ID/name disagree")
    return dataset, source_hash
