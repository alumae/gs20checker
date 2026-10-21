import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.workbooks import extract_rows
from benchmarks.build_fresh import select_rows
from benchmarks.embedding_retrieval import (
    Embeddings,
    Retrieval,
    ShortlistMatcher,
    query_text,
    response_vectors,
    unit_rows,
    validate_shortlist,
)
from tests.test_candidates import positive
from tests.test_processing import FakeClient, negative, reply


def test_embedding_rows_are_reordered_and_normalized():
    response = SimpleNamespace(
        data=[
            SimpleNamespace(index=1, embedding=[0, 5]),
            SimpleNamespace(index=0, embedding=[3, 4]),
        ]
    )
    assert np.allclose(response_vectors(response, 2, 2), [[0.6, 0.8], [0, 1]])
    response.data[1].index = 1
    with pytest.raises(ValueError, match="Duplicate"):
        response_vectors(response, 2, 2)
    with pytest.raises(ValueError, match="Missing"):
        response_vectors(SimpleNamespace(data=[]), 1, 2)


@pytest.mark.parametrize("rows", [[[0, 0]], [[float("nan"), 1]], [[1, 2, 3]]])
def test_bad_vectors_rejected(rows):
    with pytest.raises(ValueError):
        unit_rows(rows, 2)


def test_query_uses_all_venue_fields_and_no_gold():
    fields = {
        "journal": "Alpha",
        "conference": "Beta",
        "publication_title": "Proceedings",
        "reference": "full reference",
        "expected_venue": "SECRET",
    }
    text = query_text(fields)
    assert all(v in text for v in ("Alpha", "Beta", "Proceedings"))
    assert "SECRET" not in text and "full reference" not in text
    assert query_text({"reference": "full reference"}) == "full reference"


def test_cache_fingerprint_and_tie_order(catalogue, tmp_path):
    retrieval = Retrieval(catalogue)
    calls = []

    class Encoder:
        model = "fake"
        dimensions = 2

        def __init__(self):
            self.calls = []

        async def encode(self, texts):
            calls.append(texts)
            return np.array([[1.0, 0.0]] * len(texts), dtype=np.float32)

    encoder = Encoder()
    first = asyncio.run(retrieval.build(encoder, tmp_path))
    second = asyncio.run(retrieval.build(encoder, tmp_path))
    assert not first["cache_hit"] and second["cache_hit"] and len(calls) == 1
    assert retrieval.dense(np.array([1.0, 0.0]), 5) == sorted(catalogue.venues)[:5]
    encoder.model = "other"
    third = asyncio.run(retrieval.build(encoder, tmp_path))
    assert third["fingerprint"] != first["fingerprint"] and len(calls) == 2
    retrieval.texts[0] += " changed"
    fourth = asyncio.run(retrieval.build(encoder, tmp_path))
    assert fourth["fingerprint"] != third["fingerprint"]
    encoder.dimensions = 3
    assert retrieval.manifest(encoder)["dimensions"] == 3


def test_queries_deduplicate_only_within_invocation():
    requests = []

    async def create(**kwargs):
        requests.append(kwargs["input"])
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=i, embedding=[1, i + 1]) for i in range(len(kwargs["input"]))
            ],
            usage=SimpleNamespace(model_dump=lambda: {"total_tokens": 4}),
        )

    recorder = SimpleNamespace(
        attempts=0, client=SimpleNamespace(embeddings=SimpleNamespace(create=create))
    )
    encoder = Embeddings(recorder, dimensions=2)
    a = asyncio.run(encoder.encode(["same", "other", "same"]))
    asyncio.run(encoder.encode(["same"]))
    assert requests == [["same", "other"], ["same"]]
    assert np.allclose(a[0], a[2])


def test_shortlist_id_name_and_per_item_boundaries(catalogue):
    ids = sorted(catalogue.venues)
    with pytest.raises(ValueError, match="outside"):
        validate_shortlist(positive(catalogue, ids[1]), catalogue, [ids[0]])
    bad_name = positive(catalogue, ids[0])
    bad_name["venue_name"] = catalogue.venues[ids[1]]["name"]
    with pytest.raises(ValueError, match="disagree"):
        validate_shortlist(bad_name, catalogue, [ids[0]])
    assert validate_shortlist(negative(), catalogue, [ids[0]])["matched"] is False


def test_invalid_item_retries_once_with_unchanged_shortlist(catalogue):
    ids = sorted(catalogue.venues)
    items = [
        {"id": "a", "fields": {"reference": "a"}, "expected_venue": "SECRET"},
        {"id": "b", "fields": {"reference": "b"}},
    ]
    candidates = {"a": [ids[0]], "b": [ids[1]]}

    async def handler(kwargs):
        inputs = json.loads(kwargs["input"][-1]["content"])
        assert "SECRET" not in kwargs["input"][-1]["content"]
        # Invalid a borrows b's candidate in both the batch and individual retry.
        outputs = [positive(catalogue, ids[1], item["id"]) for item in inputs]
        return reply(outputs)

    client = FakeClient(handler)
    matcher = ShortlistMatcher(catalogue, "test", client)
    results = asyncio.run(matcher.match_batch(items, candidates))
    assert results["a"]["status"] == "error"
    assert results["b"]["venue_id"] == ids[1]
    assert matcher.fallbacks == 1 and len(client.calls) == 2
    before = json.loads(client.calls[0]["input"][-1]["content"])[0]["candidates"]
    after = json.loads(client.calls[1]["input"][-1]["content"])[0]["candidates"]
    assert before == after


def test_hybrid_union_preserves_exact_matches_beyond_k(catalogue):
    retrieval = Retrieval(catalogue)
    retrieval.matrix = np.array([[1.0, 0.0]] * len(retrieval.ids))
    final = retrieval.ids[-1]
    fields = {"journal": catalogue.venues[final]["name"]}
    shortlist = retrieval.shortlist(fields, "hybrid", 1, np.array([1.0, 0.0]))
    assert final in shortlist and retrieval.ids[0] in shortlist
    assert len(shortlist) == len(set(shortlist))


def test_fresh_holdout_is_reproducible_and_disjoint():
    old = json.loads(Path("benchmarks/testset.json").read_text())["items"]
    fresh = json.loads(Path("benchmarks/fresh50.json").read_text())["items"]
    rows, _ = extract_rows(Path("sample_data/Publications.xlsx").read_bytes())
    selected = select_rows(rows, old)
    assert [r["row"] for r in selected] == [i["row"] for i in fresh]
    assert not {i["id"] for i in old} & {i["id"] for i in fresh}
    assert 361 not in {i["row"] for i in fresh}
    assert len(fresh) == 50 and sum(i["expected_venue_id"] is not None for i in fresh) == 11
    # Frozen historical datasets retain extra ETIS fields; current uploads use only the citation.
    assert all(
        r["fields"] == {"reference": i["fields"]["reference"]}
        for r, i in zip(selected, fresh, strict=True)
    )
