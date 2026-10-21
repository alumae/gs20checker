"""Synthetic rankings are test fixtures only; never a production catalogue."""

import json
from types import SimpleNamespace

import pytest

from app import create_app
from app.catalogue import Catalogue
from app.collector import collect
from app.matching import AsyncMatcher, Matcher

AREAS = {
    "bus": "Business",
    "chm": "Chemistry",
    "eng": "Engineering",
    "hum": "Humanities",
    "bio": "Life Sciences",
    "med": "Medicine",
    "phy": "Physics",
    "soc": "Social Sciences",
}


@pytest.fixture
def pages():
    def links(items):
        return "".join(
            f'<a href="/citations?view_op=top_venues&amp;hl=en&amp;vq={code}">{name}</a>'
            for code, name in items.items()
        )

    result = {"": links(AREAS)}
    table = (
        '<table><tr><th class="gsc_mvt_p"></th>'
        '<th class="gsc_mvt_t">Publication</th></tr>'
        + "".join(
            f'<tr><td class="gsc_mvt_p">{rank}.</td>'
            f'<td class="gsc_mvt_t">Test Journal {rank}</td></tr>'
            for rank in range(1, 21)
        )
        + "</table>"
    )
    result[""] += table
    for code, name in AREAS.items():
        result[code] = links({**AREAS, code + "_test": name + " Subfield"}) + table
        result[code + "_test"] = links(AREAS) + table
    return result


@pytest.fixture
def catalogue(pages):
    return Catalogue(collect(pages.__getitem__, edition="SYNTHETIC TEST DATA"))


@pytest.fixture
def model_client(catalogue):
    class Responses:
        calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            output = {
                "matched": True,
                "venue_id": next(iter(catalogue.venues)),
                "venue_name": next(iter(catalogue.venues.values()))["name"],
                "note": "Recognized the test venue abbreviation.",
            }
            return SimpleNamespace(status="completed", output_text=json.dumps(output))

    return SimpleNamespace(responses=Responses())


@pytest.fixture
def application(tmp_path, catalogue, model_client):
    path = tmp_path / "venues.json"
    path.write_text(json.dumps(catalogue.data))
    app = create_app(
        {
            "TESTING": True,
            "GS_CATALOGUE": str(path),
            "OPENAI_API_KEY": "test-only",
        }
    )
    app.config["MATCHER_FACTORY"] = lambda: Matcher(catalogue, "test", client=model_client)

    def async_factory():
        class Client:
            async def create(self, **kwargs):
                entries = json.loads(kwargs["input"][-1]["content"])
                if isinstance(entries, list):
                    output = {
                        "results": [
                            {
                                "id": item["id"],
                                "matched": False,
                                "venue_id": None,
                                "venue_name": None,
                                "note": "Not listed",
                            }
                            for item in entries
                        ]
                    }
                else:
                    output = {
                        "matched": False,
                        "venue_id": None,
                        "venue_name": None,
                        "note": "Not listed",
                    }
                return SimpleNamespace(status="completed", output_text=json.dumps(output))

            async def close(self):
                pass

        instance = Client()
        instance.responses = instance
        return AsyncMatcher(catalogue, "test", client=instance)

    app.config["ASYNC_MATCHER_FACTORY"] = async_factory
    return app


@pytest.fixture
def client(application):
    return application.test_client()


@pytest.fixture
def headers():
    return {"X-GS20-Request": "1"}
