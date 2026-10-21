import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.matching import Matcher, MatchError, prepare_reference


def test_bibtex_and_plain_references():
    data = json.loads(
        prepare_reference(
            "@article{a, title={A title}, journal={J. Testing}, year={2025}, abstract={PRIVATE}}"
        )
    )
    assert data["journal"] == "J. Testing"
    assert "abstract" not in data
    assert prepare_reference("  A (2025). Test. Journal.  ") == "A (2025). Test. Journal."
    for value in ["", None, "@broken", "x" * 20001, "@article{a,title={A}}\n@article{b,title={B}}"]:
        with pytest.raises(ValueError):
            prepare_reference(value)


def test_no_cross_request_cache_and_stable_prefix(catalogue, model_client):
    matcher = Matcher(catalogue, "test", client=model_client)
    matcher.match("Reference one")
    matcher.match("Reference one")
    Matcher(catalogue, "test", client=model_client).match("Reference two")
    calls = model_client.responses.calls
    assert len(calls) == 3
    assert calls[0]["input"][0] == calls[2]["input"][0]
    assert catalogue.prompt in calls[0]["input"][0]["content"]
    assert calls[0]["text"]["format"]["strict"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"matched": True, "venue_id": "invented", "note": "Wrong identity"},
        {"matched": False, "venue_id": "invented", "note": "Contradiction"},
        {"matched": "yes", "venue_id": None, "note": "Wrong type"},
        {"matched": False, "venue_id": None, "note": ""},
        {"matched": False, "venue_id": None, "note": "No match", "rank": 1},
    ],
)
def test_invalid_model_output_is_rejected(catalogue, payload):
    payload = {"venue_name": None, **payload}
    responses = SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(status="completed", output_text=json.dumps(payload))
    )
    matcher = Matcher(catalogue, "test", client=SimpleNamespace(responses=responses))
    with pytest.raises(MatchError):
        matcher.match("Some reference")


def test_uncertain_is_no_match(tmp_path, catalogue):
    responses = SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(
            status="completed",
            output_text=json.dumps(
                {
                    "matched": False,
                    "venue_id": None,
                    "venue_name": None,
                    "note": "Ambiguous conference acronym.",
                }
            ),
        )
    )
    result = Matcher(catalogue, "test", client=SimpleNamespace(responses=responses)).match(
        "Acronym only"
    )
    assert result["status"] == "unmatched"
    assert not result["memberships"]


def test_provider_failure_is_error(tmp_path, catalogue):
    def fail(**kwargs):
        raise RuntimeError("Secret provider diagnostics")

    matcher = Matcher(
        catalogue,
        "test",
        client=SimpleNamespace(responses=SimpleNamespace(create=fail)),
    )
    with pytest.raises(MatchError, match="could not return") as error:
        matcher.match("Reference")
    assert "Secret" not in str(error.value)


@pytest.mark.parametrize(
    "error_type,message",
    [(openai.APITimeoutError, "timed out"), (openai.APIConnectionError, "network access")],
)
def test_network_errors(tmp_path, catalogue, error_type, message):
    def fail(**kwargs):
        raise error_type(request=httpx.Request("POST", "https://api.openai.com"))

    matcher = Matcher(
        catalogue,
        "test",
        client=SimpleNamespace(responses=SimpleNamespace(create=fail)),
    )
    with pytest.raises(MatchError, match=message):
        matcher.match("Reference")


@pytest.mark.parametrize("status,output", [("incomplete", "{}"), ("completed", "")])
def test_refusal_or_truncation_is_error(tmp_path, catalogue, status, output):
    responses = SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(status=status, output_text=output)
    )
    matcher = Matcher(catalogue, "test", client=SimpleNamespace(responses=responses))
    with pytest.raises(MatchError):
        matcher.match("Reference")
