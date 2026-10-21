"""Materialize manually authored annotations against the original ETIS fields."""

import csv
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from app.catalogue import Catalogue
from app.workbooks import extract_rows

SEED = 20261018
CHALLENGE_ROWS = [
    11,
    32,
    35,
    75,
    147,
    181,
    223,
    256,
    280,
    284,
    301,
    408,
    494,
    528,
    658,
    811,
    967,
    1088,
    1106,
    1152,
]
EVIDENCE = {
    11: ["https://shop.elsevier.com/journals/water-research/0043-1354"],
    63: ["https://www.jmst.org/article/2020/1005-0302/1005-0302-57-0-113.shtml"],
    75: ["https://www.rsc.org/publishing/journals/journal-of-materials-chemistry-c"],
    147: ["https://www.ieee-ies.org/pubs/industrial-electronics-magazine/35-publications/jestie"],
    181: ["https://aclanthology.org/2026.conll-main.19/"],
    223: ["https://doi.org/10.1145/3772318.3791105"],
    494: ["https://ieee-pes.org/publications/transactions-on-smart-grid/"],
    658: ["https://msfp-workshop.github.io/msfp2026/"],
    967: ["https://aclanthology.org/2026.eacl-demo.40/"],
    1088: ["https://www.ieeecss.org/conferences/general-information"],
}


def build():
    source = Path("sample_data/Publications.xlsx")
    content = source.read_bytes()
    catalogue = Catalogue.load("data/venues.json")
    rows, _ = extract_rows(content)
    random_rows = random.Random(SEED).sample(rows, 80)
    chosen = {row["row"]: "random" for row in random_rows}
    assert not set(CHALLENGE_ROWS) & chosen.keys()
    chosen.update({row: "challenge" for row in CHALLENGE_ROWS})
    with Path("benchmarks/annotations.tsv").open() as handle:
        annotations = list(csv.DictReader(handle, delimiter="\t"))
    assert len(annotations) == len({int(a["row"]) for a in annotations}) == 100
    assert {int(a["row"]) for a in annotations} == chosen.keys()
    by_row = {r["row"]: r for r in rows}
    by_name = {v["name"]: v for v in catalogue.venues.values()}
    items = []
    for annotation in annotations:
        number = int(annotation["row"])
        row = by_row[number]
        name = annotation["catalogue_name"]
        venue = by_name[name] if name else None
        sources = [f"{source}#{row['sheet']}!row={number}", "data/venues.json"]
        if venue:
            sources += [member["source_url"] for member in venue["memberships"]]
        sources += EVIDENCE.get(number, [])
        items.append(
            {
                "id": f"etis-{number:04d}",
                "subset": chosen[number],
                "sheet": row["sheet"],
                "row": number,
                "fields": row["fields"],
                "expected_venue_id": venue["id"] if venue else None,
                "expected_venue": name or None,
                "resolved_venue": annotation["resolved_venue"],
                "rationale": annotation["rationale"],
                "evidence": sources,
                "policy_sensitive": number == 967,
            }
        )
    return {
        "schema_version": 1,
        "annotation_author": "Codex assistant; not independently human-reviewed",
        "annotation_method": "Manual venue review before benchmark predictions; no matcher labels",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "catalogue_version": catalogue.version,
        "catalogue_snapshot": catalogue.snapshot,
        "selection_seed": SEED,
        "population_rows": len(rows),
        "policy": (
            "Match venue identity against the frozen catalogue, not publication-year rankings. "
            "Forthcoming entries count by named venue. Do not infer journals from preprints or "
            "merge companion proceedings with main conferences without clear evidence. "
            "Unresolved identity is no match. Policy-sensitive cases are reported separately."
        ),
        "items": sorted(items, key=lambda item: item["row"]),
    }


if __name__ == "__main__":
    # Never accidentally replace labels after seeing predictions.
    dataset = build()
    with Path("benchmarks/testset.json").open("x") as output:
        json.dump(dataset, output, ensure_ascii=False, indent=2)
        output.write("\n")
