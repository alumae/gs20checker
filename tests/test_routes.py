import base64
import json
from io import BytesIO

import httpx
import openai
import pytest
from openpyxl import load_workbook

from app import create_app
from tests.test_workbooks import small_workbook


def test_home_and_single_match(client, headers):
    assert client.get("/").status_code == 200
    result = client.post("/api/check", json={"reference": "Test Journal"}, headers=headers)
    assert result.status_code == 200
    assert result.json["matched"] is True
    assert client.post("/api/check", json={"reference": ""}, headers=headers).status_code == 400
    assert client.post("/api/check", json=[], headers=headers).status_code == 400


def test_origin_protection(client, headers):
    assert client.post("/api/check", json={"reference": "Test"}).status_code == 400
    result = client.post(
        "/api/check",
        json={"reference": "Test"},
        headers={**headers, "Origin": "https://unrelated.example"},
    )
    assert result.status_code == 403


def test_upload_stream_download(client, headers):
    response = client.post(
        "/api/workbooks/process",
        data={"file": (BytesIO(small_workbook()), "ETIS.xlsx")},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.mimetype == "application/x-ndjson"
    events = [json.loads(line) for line in response.data.splitlines()]
    assert events[0]["type"] == "started"
    assert events[-1]["type"] == "complete"
    assert events[-1]["counts"]["pending"] == 0
    content = b"".join(base64.b64decode(e["data"]) for e in events if e["type"] == "file_chunk")
    assert len(content) == events[-1]["bytes"]
    book = load_workbook(BytesIO(content))
    assert book.active["E2"].value == "No"
    assert client.get("/api/jobs/anything").status_code == 404


def test_missing_catalogue_is_not_a_nonmatch(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "GS_CATALOGUE": str(tmp_path / "missing.json"),
        }
    )
    client = app.test_client()
    assert b"Setup needed" in client.get("/").data
    result = client.post(
        "/api/check", json={"reference": "Reference"}, headers={"X-GS20-Request": "1"}
    )
    assert result.status_code == 503
    assert "matched" not in result.json


@pytest.mark.parametrize(
    "error_type,status,code,message",
    [
        (openai.AuthenticationError, 401, "invalid_api_key", "Update OPENAI_API_KEY"),
        (openai.PermissionDeniedError, 403, None, "project permissions"),
        (openai.NotFoundError, 404, "model_not_found", "Check OPENAI_MODEL"),
        (openai.RateLimitError, 429, "insufficient_quota", "billing and usage limits"),
        (openai.RateLimitError, 429, "rate_limit_exceeded", "Wait a moment"),
        (openai.BadRequestError, 400, None, "request parameters"),
        (openai.InternalServerError, 500, None, "temporarily unavailable"),
    ],
)
def test_provider_errors_are_actionable_and_private(
    client, headers, model_client, monkeypatch, caplog, error_type, status, code, message
):
    secret = "SECRET-KEY-AND-PROVIDER-PAYLOAD"
    reference = "PRIVATE-PUBLICATION-REFERENCE"
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com"))
    failure = error_type(secret, response=response, body={"code": code, "message": secret})

    def fail(**kwargs):
        raise failure

    with monkeypatch.context() as patch:
        patch.setattr(model_client.responses, "create", fail)
        result = client.post("/api/check", json={"reference": reference}, headers=headers)
    assert result.status_code == 503
    assert message in result.json["error"]
    assert "matched" not in result.json
    assert f"HTTP {status}" in caplog.text
    assert error_type.__name__ in caplog.text
    for private in (secret, reference):
        assert private not in result.text
        assert private not in caplog.text
    # A new request can recover independently.
    retry = client.post("/api/check", json={"reference": reference}, headers=headers)
    assert retry.status_code == 200
    assert retry.json["matched"] is True
