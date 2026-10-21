"""Application factory for the Scholar Top 20 checker."""

import logging
import os
from io import BytesIO
from pathlib import Path

from flask import Flask, Request


class MemoryRequest(Request):
    """Keep multipart uploads in RAM instead of Werkzeug's spooled temp files."""

    def _get_file_stream(
        self, total_content_length, content_type, filename=None, content_length=None
    ):
        return BytesIO()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.request_class = MemoryRequest
    root = Path(app.root_path).parent
    hosted = os.getenv("VERCEL") == "1"
    app.config.from_mapping(
        MAX_CONTENT_LENGTH=4_100_000 if hosted else 11 * 1024 * 1024,
        GS_MAX_UPLOAD_BYTES=4_000_000 if hosted else 10 * 1024 * 1024,
        GS_UPLOAD_LIMIT_LABEL="4 MB" if hosted else "10 MB",
        GS_MAX_RESPONSE_BYTES=4_000_000 if hosted else None,
        GS_PROCESSING_SECONDS=29 * 60 if hosted else None,
        GS_CATALOGUE=os.getenv("GS_CATALOGUE", str(root / "data/venues.json")),
        OPENAI_API_KEY=os.getenv("OPENAI_API_KEY"),
        OPENAI_MODEL=os.getenv("OPENAI_MODEL", "gpt-6-luna"),
    )
    if test_config:
        app.config.update(test_config)
    if hosted:
        app.logger.setLevel(logging.INFO)
    # Imports are lazy so the standalone catalogue collector needs no Excel dependencies.
    from app.catalogue import Catalogue, CatalogueError
    from app.routes import bp

    try:
        catalogue = Catalogue.load(app.config["GS_CATALOGUE"])
        app.extensions["catalogue"] = catalogue
    except CatalogueError as exc:
        app.extensions["catalogue_error"] = str(exc)
    app.register_blueprint(bp)
    return app
