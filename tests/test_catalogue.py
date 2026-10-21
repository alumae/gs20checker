from copy import deepcopy
from pathlib import Path

import pytest

from app.catalogue import Catalogue, CatalogueError
from app.collector import collect, parse_page


def test_live_root_navigation_and_rankings(pages):
    html = Path("tests/fixtures/scholar_root.html").read_text()
    links, entries = parse_page(html)
    assert set(links) == {"bio", "bus", "chm", "eng", "hum", "med", "phy", "soc"}
    assert links["bio"] == "Life Sciences & Earth Sciences"
    assert len(entries) == 20
    assert entries[0] == (1, "Nature")
    pages[""] = html
    assert collect(pages.__getitem__)["complete"] is True


def test_live_subcategory_navigation():
    links, entries = parse_page(Path("tests/fixtures/scholar_eng.html").read_text())
    assert links["eng_artificialintelligence"] == "Artificial Intelligence"
    assert len(links) == 56
    assert "eng" not in links  # The selected "Subcategories" menu item is navigation.
    assert len(entries) == 20
    assert entries[0][1] == "IEEE/CVF Conference on Computer Vision and Pattern Recognition"


def test_ranking_headers_are_not_publication_rows():
    html = """
    <table id="gsc_mvt_table">
      <tr><th class="gsc_mvt_p"></th><th class="gsc_mvt_t">Publication</th></tr>
      <tr><td class="gsc_mvt_p">1.</td><td class="gsc_mvt_t">Test Journal</td></tr>
    </table>
    """
    assert parse_page(html)[1] == [(1, "Test Journal")]


@pytest.mark.parametrize("rank", ["", "unknown", "1st"])
def test_invalid_data_rank_still_fails(rank):
    html = (
        f'<table><tr><td class="gsc_mvt_p">{rank}</td>'
        '<td class="gsc_mvt_t">Test Journal</td></tr></table>'
    )
    with pytest.raises(CatalogueError, match="Unrecognized Scholar rank"):
        parse_page(html)


def test_collects_and_deduplicates(pages):
    data = collect(pages.__getitem__)
    assert len(data["categories"]) == 16
    assert len(data["venues"]) == 20
    assert all(len(v["memberships"]) == 16 for v in data["venues"])
    Catalogue(data)


def test_challenge_and_truncated_pages_fail(pages):
    with pytest.raises(CatalogueError, match="challenge"):
        parse_page("Our systems have detected unusual traffic")
    pages["eng_test"] = "<html>Missing rankings</html>"
    with pytest.raises(CatalogueError, match="ranks"):
        collect(pages.__getitem__)


def test_missing_category_page_fails(pages):
    del pages["eng_test"]
    with pytest.raises(KeyError):
        collect(pages.__getitem__)


@pytest.mark.parametrize("change", ["missing", "duplicate", "rank", "url", "partial"])
def test_snapshot_validation(catalogue, change):
    data = deepcopy(catalogue.data)
    if change == "missing":
        data["categories"].pop()
    elif change == "duplicate":
        data["venues"].append(data["venues"][0])
    elif change == "rank":
        data["venues"][0]["memberships"][0]["rank"] = 21
    elif change == "url":
        data["venues"][0]["memberships"][0]["source_url"] = "javascript:alert(1)"
    else:
        data["complete"] = False
    with pytest.raises(CatalogueError):
        Catalogue(data)


def test_offline_import_preserves_previous_snapshot_on_failure(tmp_path, pages, monkeypatch):
    from app.collector import main

    saved = tmp_path / "pages"
    saved.mkdir()
    for code, html in pages.items():
        (saved / f"{code or 'root'}.html").write_text(html)
    output = tmp_path / "catalogue.json"
    monkeypatch.setattr("sys.argv", ["collector", "--pages", str(saved), "--output", str(output)])
    main()
    Catalogue.load(output)
    previous = output.read_bytes()
    (saved / "eng_test.html").unlink()
    with pytest.raises(SystemExit):
        main()
    assert output.read_bytes() == previous
