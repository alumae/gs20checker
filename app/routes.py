"""Single checks and request-owned streaming workbook processing."""

import time

from flask import Blueprint, Response, current_app, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from app.matching import AsyncMatcher, Matcher, MatchError, prepare_reference
from app.processing import process_workbook
from app.workbooks import extract_rows

bp = Blueprint("checker", __name__)


def matcher_factory(asynchronous=False):
    catalogue = current_app.extensions.get("catalogue")
    if catalogue is None:
        raise MatchError(current_app.extensions.get("catalogue_error", "Catalogue unavailable."))
    factory = current_app.config.get("ASYNC_MATCHER_FACTORY" if asynchronous else "MATCHER_FACTORY")
    if factory is not None:
        return factory
    key = current_app.config["OPENAI_API_KEY"]
    model = current_app.config["OPENAI_MODEL"]
    if not key:
        raise MatchError("Matching is unavailable: OPENAI_API_KEY is not configured.")
    cls = AsyncMatcher if asynchronous else Matcher
    return lambda: cls(catalogue, model, api_key=key)


@bp.before_request
def local_origin_check():
    # Prevent another website from spending the local server's API budget via a browser.
    if request.method == "POST":
        if request.headers.get("Origin") not in (None, request.host_url.rstrip("/")):
            return jsonify(error="Cross-origin requests are not accepted."), 403
        if request.headers.get("X-GS20-Request") != "1":
            return jsonify(error="Missing request header."), 400


@bp.after_request
def response_headers(response):
    response.headers["Cache-Control"] = "no-store, no-transform"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; "
        "img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    return response


@bp.get("/")
def index():
    catalogue = current_app.extensions.get("catalogue")
    error = current_app.extensions.get("catalogue_error")
    if not error and not current_app.config["OPENAI_API_KEY"]:
        error = "Matching is unavailable until the server's OpenAI API key is configured."
    return render_template("index.html", catalogue=catalogue, setup_error=error)


@bp.post("/api/check")
def check():
    payload = request.get_json()
    if not isinstance(payload, dict):
        raise ValueError("Send a JSON object containing reference.")
    reference = prepare_reference(payload.get("reference"))
    engine = matcher_factory()()
    try:
        return jsonify(engine.match(reference))
    finally:
        engine.close()


@bp.post("/api/workbooks/process")
def upload():
    seconds = current_app.config["GS_PROCESSING_SECONDS"]
    deadline = time.monotonic() + seconds if seconds is not None else None
    factory = matcher_factory(asynchronous=True)
    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".xlsx"):
        raise ValueError("Choose an ETIS .xlsx file.")
    limit = current_app.config["GS_MAX_UPLOAD_BYTES"]
    content = file.read(limit + 1)
    file.close()
    if len(content) > limit:
        label = current_app.config["GS_UPLOAD_LIMIT_LABEL"]
        return jsonify(error=f"Upload a workbook no larger than {label}."), 413
    rows, sheets = extract_rows(content)
    stream = process_workbook(
        content,
        rows,
        sheets,
        current_app.extensions["catalogue"],
        factory,
        heartbeat_seconds=current_app.config.get("STREAM_HEARTBEAT_SECONDS", 2),
        deadline=deadline,
        max_response_bytes=current_app.config["GS_MAX_RESPONSE_BYTES"],
    )
    return Response(stream, mimetype="application/x-ndjson", headers={"X-Accel-Buffering": "no"})


@bp.app_errorhandler(ValueError)
def invalid_input(error):
    return jsonify(error=str(error)), 400


@bp.app_errorhandler(MatchError)
def matching_failure(error):
    return jsonify(error=str(error)), 503


@bp.app_errorhandler(HTTPException)
def http_error(error):
    if error.code == 413:
        label = current_app.config["GS_UPLOAD_LIMIT_LABEL"]
        return jsonify(error=f"Upload a workbook no larger than {label}."), 413
    return jsonify(error=error.description), error.code
