"""Read-only lexical venue candidates; retrieval is evidence for review, not a verdict."""

import html
import json
import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType

STOP_WORDS = frozenset(
    "a an and at by for from in of on the to with international annual conference "
    "conferences proceedings journal journals symposium workshop workshops".split()
)
VENUE_FIELDS = ("reference", "journal", "conference", "publication_title", "booktitle")
# Reviewed identities, not aliases or matching rules. Check both ID and name so a
# different catalogue cannot silently inherit metadata intended for these entries.
REVIEWED_TYPES = {
    "573bb406d9c234d2dcbc": (
        "International Conference on Language Resources and Evaluation (LREC)",
        "conference",
        "https://lrec2026.info/",
    ),
    "8f05d8fd5315cc52b8d8": (
        "Language Resources and Evaluation",
        "journal",
        "https://link.springer.com/journal/10579",
    ),
}


def normalize(value):
    text = unicodedata.normalize("NFKC", html.unescape(str(value)))
    text = re.sub(r"<[^>]*>", " ", text)
    return " ".join(re.findall(r"[^\W_]+", text.casefold()))


def publication_fields(reference):
    """Single checks may contain plain text or the JSON produced by prepare_reference."""
    if isinstance(reference, dict):
        return reference
    try:
        fields = json.loads(reference)
        if isinstance(fields, dict):
            return fields
    except (ValueError, TypeError):
        pass
    return {"reference": reference}


def journal_key(value):
    """Whole-name equality allowing ETIS punctuation/connector damage only."""
    # Preserve word order and every substantive word (including A/B, Science,
    # Research, etc.). This is deliberately stricter than candidate retrieval.
    return tuple(word for word in normalize(value).split() if word not in {"and", "amp"})


def explicit_kind(text):
    tokens = set(normalize(text).split())
    if tokens & {"workshop", "workshops"}:
        return "workshop"
    if tokens & {"journal", "journals"}:
        return "journal"
    if tokens & {"conference", "conferences", "symposium"}:
        return "conference"
    return "unknown"


def reference_kinds(fields):
    kinds = set()
    entry_type = str(fields.get("ENTRYTYPE", "")).casefold()
    if fields.get("journal") or entry_type == "article":
        kinds.add("journal")
    if fields.get("conference") or entry_type in {"inproceedings", "conference"}:
        kinds.add("conference")
    for key in VENUE_FIELDS:
        kind = explicit_kind(fields.get(key, ""))
        if kind != "unknown":
            kinds.add(kind)
        elif "proceedings" in normalize(fields.get(key, "")).split():
            kinds.add("conference")
    # Mentioning the host conference does not turn a workshop into its main venue.
    return {"workshop"} if "workshop" in kinds else kinds


@dataclass(frozen=True)
class Candidate:
    venue_id: str
    name: str
    phrases: tuple
    acronyms: frozenset
    tokens: frozenset
    kind: str
    type_source: str

    def prompt_entry(self):
        return {
            "venue_id": self.venue_id,
            "name": self.name,
            "kind": self.kind,
            "type_source": self.type_source,
        }


class CandidateIndex:
    def __init__(self, venues):
        entries = {}
        for venue_id, venue in venues.items():
            name = venue["name"]
            base = re.sub(r"\([^)]*\)", " ", name)
            phrases = tuple(sorted({normalize(name), normalize(base)} - {""}))
            acronyms = frozenset(
                normalize(a) for a in re.findall(r"\(([A-Z][A-Z0-9-]{2,})\)", name)
            )
            kind, source = explicit_kind(name), "name marker"
            reviewed = REVIEWED_TYPES.get(venue_id)
            if reviewed and reviewed[0] == name:
                _, kind, source = reviewed
            if kind == "unknown":
                source = "unknown"
            entries[venue_id] = Candidate(
                venue_id,
                name,
                phrases,
                acronyms,
                frozenset(normalize(base).split()) - STOP_WORDS,
                kind,
                source,
            )
        self.entries = MappingProxyType(entries)
        journals = {}
        for entry in entries.values():
            key = journal_key(entry.name)
            # Keep collisions, including non-journal names, ambiguous.
            journals[key] = None if key in journals else entry
        self.journals = MappingProxyType(journals)

    def exact_journal(self, reference):
        """Resolve a complete structured journal field, never a citation substring."""
        journal = publication_fields(reference).get("journal")
        if not isinstance(journal, str) or not journal.strip():
            return None
        entry = self.journals.get(journal_key(journal))
        if entry and entry.kind in {"journal", "unknown"}:
            return entry.venue_id
        return None

    def retrieve(self, fields):
        texts = [normalize(fields[k]) for k in VENUE_FIELDS if fields.get(k)]
        words = [frozenset(text.split()) for text in texts]
        # ETIS may lose an ampersand/conjunction in a venue field (e.g. "Biomass
        # Bioenergy"). Whole-field identity can support even a two-token name;
        # do not apply this relaxation to words scattered across a full citation.
        venue_words = [
            frozenset(normalize(fields[k]).split()) - STOP_WORDS
            for k in VENUE_FIELDS
            if k != "reference" and fields.get(k)
        ]
        found = []
        for entry in self.entries.values():
            phrase = any(f" {p} " in f" {text} " for p in entry.phrases for text in texts)
            phrase = phrase or bool(entry.tokens and entry.tokens in venue_words)
            acronym = any(f" {a} " in f" {text} " for a in entry.acronyms for text in texts)
            overlaps = [len(entry.tokens & tokens) for tokens in words]
            overlap = max(overlaps, default=0)
            ratio = overlap / len(entry.tokens) if entry.tokens else 0
            if phrase or acronym or (overlap >= 3 and ratio >= 0.8):
                tier = 3 if phrase else 2 if acronym else 1
                found.append((tier, entry))
        return [entry for _, entry in sorted(found, key=lambda x: (-x[0], x[1].venue_id))]

    def verification_candidates(self, reference, result):
        fields = publication_fields(reference)
        found = self.retrieve(fields)
        selected = self.entries.get(result.get("venue_id"))
        kinds = reference_kinds(fields)
        conflict = selected and selected.kind != "unknown" and kinds and selected.kind not in kinds
        competing = any(entry != selected for entry in found)
        # An unsupported positive is also ambiguous when the source supplies a venue
        # field. This catches a different, unlisted journal even when retrieval finds
        # no competing catalogue candidate. It is a review trigger, never a rejection.
        unsupported = (
            selected
            and selected not in found
            and any(fields.get(key) for key in VENUE_FIELDS if key != "reference")
        )
        if not competing and not conflict and not unsupported:
            return []
        shortlist = found[:8]
        if selected and selected not in shortlist:
            shortlist = shortlist[:7] + [selected]
        return [entry.prompt_entry() for entry in shortlist]
