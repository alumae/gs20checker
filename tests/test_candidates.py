import asyncio
import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest
from openpyxl import load_workbook

from app.candidates import CandidateIndex, explicit_kind, normalize
from app.catalogue import Catalogue
from app.matching import AsyncMatcher, Matcher, MatchError
from app.processing import process_workbook
from app.workbooks import extract_rows
from tests.test_processing import FakeClient, negative, reply, workbook


@pytest.fixture(scope="module")
def real_catalogue():
    return Catalogue.load("data/venues.json")


@pytest.fixture(scope="module")
def regression():
    return json.loads(Path("benchmarks/regressions/lillepalu-lrec.json").read_text())


def positive(catalogue, venue_id, item_id=None):
    result = {
        "matched": True,
        "venue_id": venue_id,
        "venue_name": catalogue.venues[venue_id]["name"],
        "note": "Verified venue identity",
    }
    if item_id is not None:
        result["id"] = item_id
    return result


def test_lrec_fixture_tracks_original_workbook(regression):
    content = Path(regression["source"]).read_bytes()
    assert hashlib.sha256(content).hexdigest() == regression["source_sha256"]
    rows, _ = extract_rows(content)
    row = next(
        r for r in rows if r["row"] == regression["row"] and r["sheet"] == regression["sheet"]
    )
    assert row["fields"] == {"reference": regression["fields"]["reference"]}


def test_lrec_candidates_and_reviewed_types(real_catalogue, regression):
    for reference in (regression["fields"], regression["plain_reference"]):
        entries = real_catalogue.candidates.verification_candidates(reference, negative())
        entries = {e["venue_id"]: e for e in entries}
        assert entries[regression["expected_venue_id"]]["kind"] == "conference"
        assert entries[regression["confusable_venue_id"]]["kind"] == "journal"
        assert entries[regression["confusable_venue_id"]]["type_source"].startswith("https://")


def test_retrieval_normalization_threshold_and_boundaries():
    index = CandidateIndex(
        {
            "a": {"name": "International Conference on Alpha Beta Gamma Delta Epsilon (ABG)"},
            "b": {"name": "Journal of Red Green Blue Yellow Violet"},
            "c": {"name": "Nature"},
        }
    )
    assert normalize("<i>Ａlpha&nbsp; BETA</i>") == "alpha beta"
    assert [e.venue_id for e in index.retrieve({"conference": "ABG 2026"})] == ["a"]
    assert not index.retrieve({"reference": "ABGadget"})
    assert not index.retrieve({"title": "Nature and ABG", "year": "2026"})
    assert [e.venue_id for e in index.retrieve({"journal": "red, green; blue! yellow"})] == ["b"]
    assert not index.retrieve({"journal": "red green blue"})
    assert not index.retrieve({"reference": "denatured"})
    assert explicit_kind("Proceedings of the National Academy of Sciences") == "unknown"
    assert explicit_kind("Transactions on Testing") == "unknown"
    with pytest.raises(TypeError):
        index.entries["new"] = None


def test_shortlist_cap_ties_and_selected_retention():
    index = CandidateIndex(
        {str(i): {"name": f"Journal of Shared Alpha Beta {i}"} for i in range(12)}
    )
    fields = {"reference": "Shared Alpha Beta 0 1 2 3 4 5 6 7 8 9 10 11"}
    entries = index.verification_candidates(fields, {"venue_id": "9"})
    assert len(entries) == 8
    assert entries[-1]["venue_id"] == "9"
    assert [e["venue_id"] for e in entries[:-1]] == sorted(index.entries)[:7]


def test_type_conflict_triggers_without_lexical_candidates():
    index = CandidateIndex({"j": {"name": "Journal of Alpha"}, "u": {"name": "Unknown Venue"}})
    fields = {"ENTRYTYPE": "inproceedings", "booktitle": "ZZZ 2026"}
    assert index.verification_candidates(fields, {"venue_id": "j"})
    assert not index.verification_candidates({"reference": "Conference ZZZ"}, {"venue_id": "u"})
    assert not index.verification_candidates({"journal": "Journal of Alpha"}, {"venue_id": "j"})


def test_unsupported_positive_with_structured_venue_gets_verified():
    index = CandidateIndex({"v": {"name": "IEEE Transactions on Industrial Electronics"}})
    fields = {"journal": "IEEE Transactions on Industry Applications"}
    assert not index.retrieve(fields)
    candidates = index.verification_candidates(fields, {"venue_id": "v"})
    assert [c["venue_id"] for c in candidates] == ["v"]
    assert not index.verification_candidates(fields, negative())


def test_missing_conjunction_in_complete_venue_field():
    index = CandidateIndex({"v": {"name": "Biomass and Bioenergy"}})
    assert [v.venue_id for v in index.retrieve({"journal": "Biomass  Bioenergy"})] == ["v"]
    assert not index.retrieve({"reference": "Biomass was studied. Other topics include bioenergy."})


def test_ambiguous_acronym_keeps_both_candidates():
    index = CandidateIndex(
        {
            "a": {"name": "Conference on Alpha Beta Computing (ABC)"},
            "b": {"name": "Journal of Applied Biological Chemistry (ABC)"},
        }
    )
    entries = index.verification_candidates("Smith (2026). Example paper. ABC.", {"venue_id": "a"})
    assert {entry["kind"] for entry in entries} == {"journal", "conference"}
    assert {entry["venue_id"] for entry in entries} == {"a", "b"}


def test_unambiguous_match_uses_no_additional_request(catalogue, model_client):
    venue_id = next(iter(catalogue.venues))
    reference = json.dumps({"journal": catalogue.venues[venue_id]["name"]})
    matcher = Matcher(catalogue, "test", client=model_client)
    assert matcher.match(reference)["venue_id"] == venue_id
    assert matcher.requests == 0 and matcher.verifications == 0


@pytest.mark.parametrize("matched", [False, True])
def test_default_single_skips_verification_for_ambiguous_venue(real_catalogue, regression, matched):
    result = positive(real_catalogue, regression["confusable_venue_id"]) if matched else negative()
    # This reference/result pair used to trigger a follow-up conference/journal check.
    assert real_catalogue.candidates.verification_candidates(regression["fields"], result)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return reply(result, batch=False)

    matcher = Matcher(
        real_catalogue, "test", client=SimpleNamespace(responses=SimpleNamespace(create=create))
    )
    actual = matcher.match(json.dumps(regression["fields"]))
    assert actual["matched"] is matched
    assert actual["venue_id"] == result["venue_id"]
    assert len(calls) == matcher.requests == 1
    assert matcher.verifications == 0
    assert real_catalogue.prompt in calls[0]["input"][0]["content"]


@pytest.mark.parametrize("malformed", [False, True])
def test_default_batch_skips_verification_including_after_fallback(
    real_catalogue, regression, malformed
):
    async def handler(kwargs):
        if kwargs["text"]["format"]["name"] == "venue_matches":
            items = json.loads(kwargs["input"][-1]["content"])
            assert len(items) == 10
            results = [negative(item["id"]) for item in items]
            if malformed:
                results[0]["venue_name"] = "Invalid name for a nonmatch"
            return reply(results)
        assert malformed and kwargs["text"]["format"]["name"] == "venue_match"
        return reply(negative(), batch=False)

    client = FakeClient(handler)
    matcher = AsyncMatcher(real_catalogue, "test", client=client)
    items = [{"id": str(i), "fields": regression["fields"]} for i in range(10)]
    results = asyncio.run(matcher.match_batch(items))
    assert len(results) == 10 and all(r["status"] == "unmatched" for r in results.values())
    assert matcher.requests == len(client.calls) == 1 + malformed
    assert matcher.fallbacks == malformed and matcher.verifications == 0
    assert all(real_catalogue.prompt in c["input"][0]["content"] for c in client.calls)


@pytest.mark.parametrize("first", ["nonmatch", "journal", "conference", "malformed"])
def test_batch_semantic_verification_corrects_lrec(real_catalogue, regression, first):
    expected = regression["expected_venue_id"]

    async def handler(kwargs):
        name = kwargs["text"]["format"]["name"]
        if name == "venue_matches":
            if first == "malformed":
                return reply([])
            if first == "nonmatch":
                result = negative("target")
                result["note"] = regression["observed_note"]
            else:
                venue = expected if first == "conference" else regression["confusable_venue_id"]
                result = positive(real_catalogue, venue, "target")
            return reply([result])
        if name == "venue_match":
            return reply(negative(), batch=False)
        assert name == "venue_verification"
        assert json.loads(kwargs["input"][-1]["content"]) == regression["fields"]
        assert regression["observed_note"] not in json.dumps(kwargs)
        assert real_catalogue.prompt not in kwargs["input"][0]["content"]
        enum = kwargs["text"]["format"]["schema"]["properties"]["venue_id"]["enum"]
        assert expected in enum and regression["confusable_venue_id"] in enum and None in enum
        return reply(positive(real_catalogue, expected), batch=False)

    client = FakeClient(handler)
    matcher = AsyncMatcher(real_catalogue, "test", client=client, verify_candidates=True)
    results = asyncio.run(matcher.match_batch([{"id": "target", "fields": regression["fields"]}]))
    assert results["target"]["venue_id"] == expected
    assert results["target"]["memberships"][0]["rank"] == regression["expected_rank"]
    assert matcher.verifications == 1
    assert matcher.fallbacks == (first == "malformed")
    assert matcher.requests == 2 + (first == "malformed")


def test_single_plain_and_bibtex_use_same_verification(real_catalogue, regression):
    for reference in (
        regression["plain_reference"],
        json.dumps({"ENTRYTYPE": "inproceedings", "booktitle": "LREC 2026"}),
    ):
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            return reply(
                negative()
                if len(calls) == 1
                else positive(real_catalogue, regression["expected_venue_id"]),
                batch=False,
            )

        matcher = Matcher(
            real_catalogue,
            "test",
            client=SimpleNamespace(responses=SimpleNamespace(create=create)),
            verify_candidates=True,
        )
        assert matcher.match(reference)["venue_id"] == regression["expected_venue_id"]
        assert matcher.requests == 2 and matcher.verifications == 1


@pytest.mark.parametrize("case", ["journal", "workshop", "uncertain"])
def test_verification_does_not_force_a_conference_match(real_catalogue, regression, case):
    fields = {
        "journal": {
            "ENTRYTYPE": "article",
            "journal": "Language Resources and Evaluation",
            "reference": "Example article. Language Resources and Evaluation, volume 58.",
        },
        "workshop": {
            "reference": "Example paper. Unlisted Workshop on Test Resources, held at LREC 2026."
        },
        "uncertain": {
            "reference": "Example paper. LREC or Language Resources and Evaluation; venue unclear."
        },
    }[case]

    async def handler(kwargs):
        if kwargs["text"]["format"]["name"] == "venue_matches":
            return reply([positive(real_catalogue, regression["expected_venue_id"], "a")])
        result = (
            positive(real_catalogue, regression["confusable_venue_id"])
            if case == "journal"
            else negative()
        )
        result["note"] = "Ambiguous venue" if case == "uncertain" else "Checked publication venue"
        return reply(result, batch=False)

    matcher = AsyncMatcher(
        real_catalogue, "test", client=FakeClient(handler), verify_candidates=True
    )
    result = asyncio.run(matcher.match_batch([{"id": "a", "fields": fields}]))["a"]
    assert matcher.verifications == 1
    assert result["venue_id"] == (regression["confusable_venue_id"] if case == "journal" else None)
    assert result["status"] != "error"


@pytest.mark.parametrize("problem", ["outside", "malformed", "provider"])
def test_failed_verification_is_not_silently_a_nonmatch(real_catalogue, regression, problem):
    async def handler(kwargs):
        if kwargs["text"]["format"]["name"] == "venue_matches":
            return reply([negative("a")])
        if problem == "provider":
            raise openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))
        if problem == "malformed":
            return reply({}, batch=False)
        outside = next(
            v
            for v in real_catalogue.venues
            if v not in kwargs["text"]["format"]["schema"]["properties"]["venue_id"]["enum"]
        )
        return reply(positive(real_catalogue, outside), batch=False)

    client = FakeClient(handler)
    matcher = AsyncMatcher(real_catalogue, "test", client=client, verify_candidates=True)
    operation = matcher.match_batch([{"id": "a", "fields": regression["fields"]}])
    if problem == "provider":
        with pytest.raises(MatchError):
            asyncio.run(operation)
    else:
        assert asyncio.run(operation)["a"]["status"] == "error"
    assert matcher.requests == 2 and matcher.fallbacks == 0 and matcher.verifications == 1


def test_cancellation_during_verification_releases_client(real_catalogue, regression):
    cancelled = []

    async def handler(kwargs):
        if kwargs["text"]["format"]["name"] == "venue_matches":
            return reply([negative("0")])
        try:
            await asyncio.sleep(3600)
        finally:
            cancelled.append(True)

    client = FakeClient(handler)
    engine = AsyncMatcher(real_catalogue, "test", client=client, verify_candidates=True)
    content = workbook([regression["plain_reference"]])
    rows, sheets = extract_rows(content)
    stream = process_workbook(content, rows, sheets, real_catalogue, lambda: engine, 0.001)
    next(stream)
    next(stream)
    stream.close()
    assert engine.verifications == 1 and cancelled == [True]
    assert client.closed and not rows


def test_verification_result_deduplicated_only_within_upload(real_catalogue, regression):
    async def handler(kwargs):
        if kwargs["text"]["format"]["name"] == "venue_matches":
            return reply([negative("0")])
        return reply(positive(real_catalogue, regression["expected_venue_id"]), batch=False)

    content = workbook([regression["plain_reference"]] * 12)
    for _ in range(2):
        client = FakeClient(handler)
        engine = AsyncMatcher(real_catalogue, "test", client=client, verify_candidates=True)
        rows, sheets = extract_rows(content)
        events = [
            json.loads(line)
            for line in process_workbook(content, rows, sheets, real_catalogue, lambda: engine)
        ]
        assert events[-1]["counts"]["matched"] == 12
        assert engine.requests == 2 and engine.verifications == 1 and client.closed
        exported = b"".join(
            base64.b64decode(e["data"]) for e in events if e["type"] == "file_chunk"
        )
        book = load_workbook(BytesIO(exported))
        try:
            assert book.active["B2"].value == "Yes"
            assert book.active["C2"].value == regression["expected_venue"]
            assert book.active["E2"].value == str(regression["expected_rank"])
        finally:
            book.close()
