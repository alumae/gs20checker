"""Collect Scholar's English ranking graph, or parse locally saved HTML pages."""

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.catalogue import BROAD_AREAS, Catalogue, CatalogueError, digest, source_url

ROOT_URL = "https://scholar.google.com/citations?view_op=top_venues&hl=en"


def parse_page(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).lower()
    if any(marker in text for marker in ("unusual traffic", "not a robot", "automated queries")):
        raise CatalogueError("Scholar returned a challenge page; collection stopped.")
    links = {}
    for a in soup.select("a[href]"):
        url = urlparse(urljoin(ROOT_URL, a["href"]))
        query = parse_qs(url.query)
        code = query.get("vq", [""])[0]
        if (
            url.netloc == "scholar.google.com"
            and url.path == "/citations"
            and query.get("view_op") == ["top_venues"]
            and re.fullmatch(r"[a-z]{3}(?:_[a-z0-9]+)?", code)
        ):
            name = a.get_text(" ", strip=True)
            if name and name.lower() not in {"all", "all subcategories", "subcategories"}:
                links[code] = name
    entries = []
    for row in soup.select("tr"):
        # Scholar uses the same classes on column headers and publication cells.
        name = row.select_one("td.gsc_mvt_t")
        rank = row.select_one("td.gsc_mvt_p")
        if name and rank:
            rank_text = rank.get_text(strip=True)
            match = re.fullmatch(r"(\d+)\.?", rank_text)
            if not match:
                raise CatalogueError(
                    f"Unrecognized Scholar rank {rank_text!r} "
                    f"for publication {name.get_text(' ', strip=True)!r}."
                )
            number = int(match[1])
            if number <= 20:
                entries.append((number, name.get_text(" ", strip=True)))
    return links, entries


def collect(page_loader, edition=None):
    """Loader takes a category code (empty for the English root) and returns HTML."""
    root_links, _ = parse_page(page_loader(""))
    broad = BROAD_AREAS
    if not broad.issubset(root_links):
        raise CatalogueError("English root page is missing research-area navigation.")
    discovered = dict(root_links)
    pages = {}
    while set(discovered) - set(pages):
        code = sorted(set(discovered) - set(pages))[0]
        links, entries = parse_page(page_loader(code))
        if sorted(r for r, _ in entries) != list(range(1, 21)):
            raise CatalogueError(f"{code}: expected exactly ranks 1–20.")
        pages[code] = entries
        for linked, name in links.items():
            if linked not in discovered:
                discovered[linked] = name
    categories = []
    venues = {}
    for code in sorted(pages):
        name = discovered[code]
        if "_" in code:
            parent = code.split("_", 1)[0]
            name = f"{discovered[parent]} / {name}"
        categories.append({"id": code, "name": name})
        for rank, title in pages[code]:
            key = " ".join(title.split())
            if not key:
                raise CatalogueError(f"{code}: empty venue name at rank {rank}.")
            venue = venues.setdefault(key, {"id": digest(key)[:20], "name": key, "memberships": []})
            venue["memberships"].append(
                {
                    "category_id": code,
                    "category": name,
                    "rank": rank,
                    "source_url": source_url(code),
                }
            )
    data = {
        "schema_version": 1,
        "complete": True,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "edition": edition,
        "discovered_categories": sorted(discovered),
        "categories": categories,
        "venues": sorted(venues.values(), key=lambda v: v["id"]),
    }
    Catalogue(data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=Path, help="Import root.html and <vq>.html files")
    parser.add_argument("--save-pages", type=Path, default=Path("data/scholar-pages"))
    parser.add_argument("--output", type=Path, default=Path("data/venues.json"))
    parser.add_argument("--edition", help="Verified edition label, if known")
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()
    session = requests.Session()
    session.headers["User-Agent"] = "GS20-Checker/0.1 (research venue catalogue collection)"

    def load(code):
        filename = f"{code or 'root'}.html"
        if args.pages:
            return (args.pages / filename).read_text(encoding="utf-8-sig")
        print(f"Fetching {code or 'English root'}", flush=True)
        time.sleep(max(0, args.delay))
        response = session.get(source_url(code) if code else ROOT_URL, timeout=30)
        response.raise_for_status()
        parse_page(response.text)  # Never save challenge pages as usable input.
        args.save_pages.mkdir(parents=True, exist_ok=True)
        (args.save_pages / filename).write_text(response.text)
        return response.text

    try:
        data = collect(load, edition=args.edition)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(args.output)
    except (CatalogueError, OSError, requests.RequestException) as exc:
        parser.exit(1, f"Collection failed; existing catalogue unchanged: {exc}\n")
    print(f"Validated {len(data['venues'])} venues across {len(data['categories'])} categories.")


if __name__ == "__main__":
    main()
