"""Materialize the independently annotated, seeded 50-row embedding holdout."""

import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from app.candidates import normalize
from app.catalogue import Catalogue
from app.workbooks import extract_rows
from benchmarks.venue_matching import write_json

SEED = 20261020
# Reviewed against all catalogue names before any embedding or LLM predictions.
POSITIVE = {
    108: "Atmosphere",
    118: "ACS Omega",
    153: "IEEE Transactions on Transportation Electrification",
    213: "IEEE Access",
    224: "Logical Methods in Computer Science",
    345: "Electric Power Systems Research",
    497: "Journal of University Teaching and Learning Practice",
    501: "Energy and Buildings",
    629: "Nature Climate Change",
    722: "IEEE Transactions on Energy Conversion",
    1143: "Journal of Thermal Analysis and Calorimetry",
}
NEGATIVE = {
    17: (
        "Nordic Conference in Law and IT / Nordic Yearbook of Law and Informatics",
        "Neither the conference nor its edited yearbook is listed.",
    ),
    76: (
        "IEEE Open Journal of Power Electronics",
        (
            "Not IEEE Transactions on Power Electronics or IEEE Journal of "
            "Emerging and Selected Topics in Power Electronics."
        ),
    ),
    92: ("EVS-EN IEC 55012:2025", "A technical standard, with no listed publication venue."),
    115: (
        "New Political Economy",
        "Distinct from Journal of Political Economy and Review of International Political Economy.",
    ),
    145: ("Novaator", "Estonian news outlet; absent from the catalogue."),
    193: (
        "Processes",
        "Distinct from Hydrological Processes, Behavioural Processes and other longer titles.",
    ),
    214: ("ChemPlusChem", "Distinct from ChemSusChem, ChemCatChem and ChemElectroChem."),
    217: (
        "ACM/SIGAPP Symposium on Applied Computing (SAC)",
        "Not listed; do not substitute ACM Symposium on Theory of Computing.",
    ),
    219: (
        "Nordic Geological Winter Meeting / Bulletin of the Geological Society of Finland",
        "Neither named meeting nor bulletin is listed.",
    ),
    270: (
        "Materials & Design",
        (
            "ETIS drops the ampersand. This journal is absent; Materials and "
            "Journal of Materials: Design and Applications are different venues."
        ),
    ),
    325: ("Geodeet", "Local surveying journal, absent; not Geoderma."),
    357: (
        "Public Policy and Administration",
        "Distinct from Public Administration and Social Policy & Administration.",
    ),
    369: (
        "Mathematical Research for Blockchain Economy (MARBLE)",
        "Conference absent; the Springer series is not a substitute venue.",
    ),
    395: ("World economic forum / European sting", "Web article, no listed venue."),
    444: (
        "International Symposium on Ecohydraulics (ISE)",
        "Full conference name absent; acronym alone is insufficient.",
    ),
    445: ("Future Law", "Legal technology conference absent."),
    473: (
        "Electronic Government and the Information Systems Perspective (EGOVIS)",
        "Conference absent; LNCS is a publishing series, not the conference.",
    ),
    475: (
        "Journal of International Consumer Marketing",
        "Full journal absent; other international marketing journals are different identities.",
    ),
    480: (
        "IEEE Green Technologies Conference (GreenTech)",
        "Conference absent; not a general IEEE or green technology journal.",
    ),
    481: ("ChemRxiv", "DOI identifies a preprint, with no evidence of a listed published venue."),
    495: (
        "International Conference on Education and New Learning Technologies (EDULEARN)",
        "Neither full conference name nor EDULEARN is listed.",
    ),
    515: (
        "International Economics and Economic Policy",
        "Distinct from International Economics and American Economic Journal: Economic Policy.",
    ),
    567: ("Geodeet", "Local surveying journal, absent; not Geoderma."),
    616: (
        "Next Generation Information Systems Engineering (NGISE)",
        "Conference absent; CCIS is a publishing series, not this conference.",
    ),
    707: (
        "Proceedings of the Estonian Academy of Sciences",
        "Not Proceedings of the National Academy of Sciences.",
    ),
    711: (
        "Białostockie Studia Prawnicze",
        "Neither accented nor unaccented journal name is listed.",
    ),
    725: (
        "Smart Cities: A System-of-Systems Perspective",
        "Edited book chapter; book absent, no evidence of journal or conference publication.",
    ),
    729: (
        "Journal of Alloys and Compounds Communications",
        "Journal absent; do not remove Communications from its identity.",
    ),
    825: ("Zenodo", "Dataset repository, not a listed journal or conference."),
    890: (
        "Journal of Chemical & Engineering Data",
        (
            "ETIS drops the ampersand. Full journal absent; other chemical "
            "engineering journals differ."
        ),
    ),
    910: (
        "Haemophilia",
        "Journal supplement; Haemophilia and the named congress are absent. Not Haematologica.",
    ),
    956: ("Estonian Journal of Earth Sciences", "Distinct from Journal of Asian Earth Sciences."),
    994: ("Estonian Journal of Earth Sciences", "Distinct from Journal of Asian Earth Sciences."),
    1024: ("Vojnosanitetski pregled", "Journal absent."),
    1029: (
        "International Baltic Conference on Databases and Information Systems (Baltic DB&IS)",
        "Edited conference proceedings; neither full name nor Baltic DB&IS is listed.",
    ),
    1044: (
        "International Conference on Mechatronics and Robotics Engineering (ICMRE)",
        "Conference absent; not IEEE/ASME Transactions on Mechatronics.",
    ),
    1081: ("Postimees", "News outlet absent."),
    1113: (
        "SSRN Working Paper Series",
        "Working paper/preprint; no listed published venue supplied.",
    ),
    1137: (
        "Nordic Symposium on Building Physics / Journal of Physics: Conference Series",
        "Neither conference nor proceedings series is listed.",
    ),
}


def select_rows(rows, old_items):
    seen = {normalize(i["fields"].get("reference", "")) for i in old_items}
    pool = []
    for row in rows:
        key = normalize(
            row["fields"].get("reference", "") or json.dumps(row["fields"], sort_keys=True)
        )
        if row["row"] == 361 or key in seen:
            continue
        seen.add(key)
        pool.append(row)
    return sorted(random.Random(SEED).sample(pool, 50), key=lambda r: r["row"])


def main():
    target = Path("benchmarks/fresh50.json")
    if target.exists():
        raise ValueError("Frozen holdout already exists; refusing to overwrite")
    source = Path("sample_data/Publications.xlsx")
    content = source.read_bytes()
    old = json.loads(Path("benchmarks/testset.json").read_text())
    rows, _ = extract_rows(content)
    selected = select_rows(rows, old["items"])
    assert {r["row"] for r in selected} == set(POSITIVE) | set(NEGATIVE)
    catalogue = Catalogue.load("data/venues.json")
    by_name = {v["name"]: v for v in catalogue.venues.values()}
    items = []
    for r in selected:
        name = POSITIVE.get(r["row"])
        resolved, rationale = (
            (
                name,
                "Exact journal identity in structured field and reference; catalogue name agrees.",
            )
            if name
            else NEGATIVE[r["row"]]
        )
        venue = by_name[name] if name else None
        items.append(
            {
                "id": f"etis-{r['row']:04d}",
                "subset": "fresh",
                "sheet": r["sheet"],
                "row": r["row"],
                "fields": r["fields"],
                "expected_venue_id": venue["id"] if venue else None,
                "expected_venue": name,
                "resolved_venue": resolved,
                "rationale": rationale,
                "evidence": [
                    f"{source}#{r['sheet']}!row{r['row']}",
                    (
                        f"data/venues.json (catalogue {catalogue.version}); name/acronym "
                        f"inventory reviewed"
                    ),
                ],
                "policy_sensitive": False,
            }
        )
    write_json(
        target,
        {
            "seed": SEED,
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "annotation_method": (
                "Codex assistant manually reviewed references and catalogue names "
                "before model predictions. Not independently human-reviewed."
            ),
            "selection": (
                "50 random rows without replacement, excluding original 100, LREC row "
                "361, and normalized duplicate references."
            ),
            "source": str(source),
            "source_sha256": hashlib.sha256(content).hexdigest(),
            "catalogue_version": catalogue.version,
            "items": items,
        },
    )
    print(f"Frozen {len(items)} rows, {len(POSITIVE)} positives, {len(NEGATIVE)} negatives.")


if __name__ == "__main__":
    main()
