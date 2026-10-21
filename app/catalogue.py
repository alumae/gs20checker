"""Validated, immutable Scholar ranking snapshots."""

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BROAD_AREAS = frozenset({"bus", "chm", "eng", "hum", "bio", "med", "phy", "soc"})


class CatalogueError(ValueError):
    pass


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def source_url(code):
    return f"https://scholar.google.com/citations?view_op=top_venues&hl=en&vq={code}"


class Catalogue:
    def __init__(self, data):
        try:
            self._validate(data)
        except (KeyError, TypeError, AttributeError) as exc:
            raise CatalogueError("Invalid catalogue structure; collect a new snapshot.") from exc
        self.data = data
        self.version = digest(data)
        self.venues = {v["id"]: v for v in data["venues"]}
        self.categories = {c["id"]: c for c in data["categories"]}
        self.snapshot = data["retrieved_at"]
        from app.candidates import CandidateIndex

        self.candidates = CandidateIndex(self.venues)
        # Include every venue, but keep ranking metadata server-side to reduce input cost.
        self.prompt = canonical_json(
            [
                {"venue_id": venue["id"], "name": venue["name"]}
                for venue in sorted(data["venues"], key=lambda v: v["id"])
            ]
        )

    @staticmethod
    def _validate(data):
        if data.get("schema_version") != 1 or data.get("complete") is not True:
            raise CatalogueError("A complete, validated Scholar snapshot is required.")
        if not data.get("retrieved_at") or not data.get("venues"):
            raise CatalogueError("The catalogue is empty or lacks a retrieval date.")
        categories = {c["id"]: c for c in data["categories"]}
        if len(categories) != len(data["categories"]):
            raise CatalogueError("Duplicate category IDs.")
        expected = set(data["discovered_categories"])
        if expected != set(categories):
            raise CatalogueError("Not all discovered categories were collected.")
        broad = BROAD_AREAS
        if not broad.issubset(categories):
            raise CatalogueError("Missing broad research areas.")
        for code in broad:
            if not any(c.startswith(code + "_") for c in categories):
                raise CatalogueError(f"No subcategories discovered for {code}.")
        ranks = {code: [] for code in categories}
        ids, names = set(), set()
        for venue in data["venues"]:
            if (
                not venue["id"]
                or not isinstance(venue["name"], str)
                or not venue["name"].strip()
                or venue["id"] in ids
                or venue["name"] in names
            ):
                raise CatalogueError("Duplicate or empty venue identity.")
            ids.add(venue["id"])
            names.add(venue["name"])
            if not venue["memberships"]:
                raise CatalogueError("A venue has no rankings.")
            for member in venue["memberships"]:
                code = member["category_id"]
                if code not in categories or type(member["rank"]) is not int:
                    raise CatalogueError("Invalid category membership.")
                if member["category"] != categories[code]["name"]:
                    raise CatalogueError("Conflicting category labels.")
                parsed = urlparse(member["source_url"])
                if (
                    parsed.scheme != "https"
                    or parsed.netloc != "scholar.google.com"
                    or parse_qs(parsed.query).get("vq") != [code]
                ):
                    raise CatalogueError("Invalid Scholar source URL.")
                ranks[code].append(member["rank"])
        if any(sorted(values) != list(range(1, 21)) for values in ranks.values()):
            raise CatalogueError("Every category must contain exactly ranks 1–20.")

    @classmethod
    def load(cls, path):
        try:
            return cls(json.loads(Path(path).read_text()))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogueError(
                "The verified venue catalogue is not installed. Run the catalogue collector "
                "or import saved Scholar pages; see README.md."
            ) from exc

    def result(self, matched, venue_id, note):
        if type(matched) is not bool or not isinstance(note, str) or not note.strip():
            raise ValueError("Invalid matching response.")
        if (matched and venue_id not in self.venues) or (not matched and venue_id is not None):
            raise ValueError("The model returned an invalid venue identity.")
        venue = self.venues[venue_id] if matched else None
        return {
            "status": "matched" if matched else "unmatched",
            "matched": matched,
            "venue_id": venue_id,
            "venue": venue["name"] if venue else "",
            "memberships": sorted(venue["memberships"], key=lambda m: m["category"])
            if venue
            else [],
            "note": note[:1500],
            "snapshot": self.snapshot,
        }
