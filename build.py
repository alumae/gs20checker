"""Validate the shipped catalogue and generate Vercel's CDN assets."""

from pathlib import Path
from shutil import copytree, rmtree

from app.catalogue import Catalogue


def build(root=Path(__file__).resolve().parent):
    Catalogue.load(root / "data/venues.json")
    destination = root / "public/static"
    if destination.exists():
        rmtree(destination)
    copytree(
        root / "app/static",
        destination,
        ignore=lambda _, names: [n for n in names if n.startswith("._")],
    )


if __name__ == "__main__":
    build()
