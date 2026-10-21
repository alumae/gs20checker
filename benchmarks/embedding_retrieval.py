"""Benchmark-only exact vector search and per-publication shortlist matching."""

import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path

import numpy as np

from app.candidates import VENUE_FIELDS, normalize
from app.matching import (
    BATCH_INSTRUCTIONS,
    BATCH_SCHEMA,
    VERIFY_INSTRUCTIONS,
    batch_entries,
    validate_result,
)

EMBEDDING_MODEL = "text-embedding-3-small"
DIMENSIONS = 1536
TEXT_VERSION = "1"


def query_text(fields):
    parts = [
        f"{key}: {fields[key].strip()}"
        for key in ("journal", "conference", "publication_title", "booktitle")
        if isinstance(fields.get(key), str) and fields[key].strip()
    ]
    return (
        "\n".join(parts)
        if parts
        else fields.get("reference", "").strip() or fields.get("title", "").strip()
    )


def venue_text(candidate):
    parts = [candidate.name]
    if candidate.acronyms:
        parts.append("Acronyms: " + ", ".join(candidate.acronyms))
    if candidate.kind != "unknown":
        parts.append("Type: " + candidate.kind)
    return "\n".join(parts)


def unit_rows(vectors, dimensions):
    values = np.asarray(vectors, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != dimensions or not np.isfinite(values).all():
        raise ValueError("Invalid embedding shape or nonfinite values")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if (norms <= 0).any():
        raise ValueError("Zero embedding vector")
    return values / norms


def response_vectors(response, count, dimensions):
    rows = [None] * count
    for entry in response.data:
        if not 0 <= entry.index < count or rows[entry.index] is not None:
            raise ValueError("Duplicate or out-of-range embedding index")
        rows[entry.index] = entry.embedding
    if any(row is None for row in rows):
        raise ValueError("Missing embedding row")
    return unit_rows(rows, dimensions)


class Embeddings:
    def __init__(self, recorder, model=EMBEDDING_MODEL, dimensions=DIMENSIONS):
        self.recorder = recorder
        self.model = model
        self.dimensions = dimensions
        self.calls = []

    async def encode(self, texts):
        # Only deduplicate within this invocation/upload; never share query vectors across runs.
        unique = list(dict.fromkeys(texts))
        if not unique or any(not text.strip() for text in unique):
            raise ValueError("Embedding inputs must be nonempty")
        vectors = []
        for start in range(0, len(unique), 128):
            group = unique[start : start + 128]
            before = self.recorder.attempts
            started = time.perf_counter()
            record = {"inputs": len(group), "model": self.model}
            try:
                response = await self.recorder.client.embeddings.create(
                    model=self.model,
                    input=group,
                    dimensions=self.dimensions,
                    encoding_format="float",
                )
                record["usage"] = response.usage.model_dump()
                vectors.extend(response_vectors(response, len(group), self.dimensions))
            except Exception as exc:
                record["error"] = type(exc).__name__
                raise
            finally:
                record.update(
                    seconds=time.perf_counter() - started,
                    http_attempts=self.recorder.attempts - before,
                )
                self.calls.append(record)
        lookup = dict(zip(unique, vectors, strict=True))
        return np.stack([lookup[text] for text in texts])


class Retrieval:
    def __init__(self, catalogue):
        self.catalogue = catalogue
        self.ids = sorted(catalogue.venues)
        self.entries = [catalogue.candidates.entries[venue_id] for venue_id in self.ids]
        self.texts = [venue_text(entry) for entry in self.entries]
        self.matrix = None
        frequencies = Counter(token for entry in self.entries for token in entry.tokens)
        self.idf = {
            token: math.log(1 + len(self.ids) / count) for token, count in frequencies.items()
        }

    def manifest(self, embeddings):
        return {
            "catalogue_version": self.catalogue.version,
            "ids": self.ids,
            "model": embeddings.model,
            "dimensions": embeddings.dimensions,
            "text_version": TEXT_VERSION,
            "texts_sha256": hashlib.sha256(
                json.dumps(self.texts, ensure_ascii=False).encode()
            ).hexdigest(),
        }

    async def build(self, embeddings, directory):
        manifest = self.manifest(embeddings)
        key = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{key}.npz"
        started = time.perf_counter()
        cached = path.exists()
        if cached:
            with np.load(path, allow_pickle=False) as data:
                if json.loads(str(data["manifest"])) != manifest:
                    raise ValueError("Embedding cache manifest mismatch")
                self.matrix = unit_rows(data["vectors"], embeddings.dimensions)
        else:
            self.matrix = await embeddings.encode(self.texts)
            temporary = path.with_suffix(".tmp")
            with temporary.open("wb") as handle:
                np.savez_compressed(handle, manifest=json.dumps(manifest), vectors=self.matrix)
            temporary.replace(path)
        if len(self.matrix) != len(self.ids):
            raise ValueError("Embedding cache row count mismatch")
        return {
            "fingerprint": key,
            "cache_hit": cached,
            "seconds": time.perf_counter() - started,
            "manifest": manifest,
            "calls": list(embeddings.calls),
        }

    def dense(self, vector, k):
        similarities = self.matrix @ vector
        # ids are sorted, stable sort resolves cosine ties by ID.
        return [self.ids[int(i)] for i in np.argsort(-similarities, kind="stable")[:k]]

    def exact(self, fields):
        texts = [f" {normalize(fields[key])} " for key in VENUE_FIELDS if fields.get(key)]
        return [
            entry.venue_id
            for entry in self.entries
            if any(
                f" {phrase} " in text
                for phrase in (*entry.phrases, *entry.acronyms)
                for text in texts
            )
        ]

    def lexical(self, fields, k):
        tokens = set(normalize(query_text(fields)).split())
        exact = set(self.exact(fields))
        scores = [
            1000 * (entry.venue_id in exact)
            + sum(self.idf[t] for t in entry.tokens & tokens) / max(1, len(entry.tokens)) ** 0.5
            for entry in self.entries
        ]
        return [self.ids[int(i)] for i in np.argsort(-np.asarray(scores), kind="stable")[:k]]

    def shortlist(self, fields, method, k, vector=None):
        ids = self.lexical(fields, 20) if method == "lexical" else self.dense(vector, k)
        if method == "hybrid":
            ids = list(dict.fromkeys(ids + self.exact(fields)))
        return ids


def validate_shortlist(data, catalogue, ids):
    result = validate_result(data, catalogue)
    if result["matched"] and result["venue_id"] not in ids:
        raise ValueError("Venue is outside this publication shortlist")
    return result


class ShortlistMatcher:
    def __init__(self, catalogue, model, client):
        self.catalogue, self.model, self.client = catalogue, model, client
        self.fallbacks = 0

    async def request(self, items, candidates):
        inputs = [
            {
                "id": item["id"],
                "fields": item["fields"],
                "candidates": [
                    self.catalogue.candidates.entries[venue_id].prompt_entry()
                    for venue_id in candidates[item["id"]]
                ],
            }
            for item in items
        ]
        return await self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "developer",
                    "content": VERIFY_INSTRUCTIONS
                    + "\n"
                    + BATCH_INSTRUCTIONS
                    + "\nEach publication has its OWN candidates. Choose only from that item's "
                    "candidates, or return no match. Never borrow another item's candidates.",
                },
                {"role": "user", "content": json.dumps(inputs, ensure_ascii=False, sort_keys=True)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "venue_shortlists",
                    "strict": True,
                    "schema": BATCH_SCHEMA,
                }
            },
            reasoning={"effort": "low"},
            max_output_tokens=2000 * len(items),
            store=False,
        )

    async def match_batch(self, items, candidates):
        response = await self.request(items, candidates)
        try:
            entries = batch_entries(response, items)
        except (ValueError, TypeError):
            entries = {}
        results = {}
        for item in items:
            item_id = item["id"]
            try:
                results[item_id] = validate_shortlist(
                    entries.get(item_id), self.catalogue, candidates[item_id]
                )
            except (ValueError, TypeError):
                self.fallbacks += 1
                retry = await self.request([item], candidates)
                try:
                    entry = batch_entries(retry, [item])[item_id]
                    results[item_id] = validate_shortlist(
                        entry, self.catalogue, candidates[item_id]
                    )
                except (ValueError, TypeError):
                    results[item_id] = {
                        "status": "error",
                        "note": "Invalid result after one shortlist retry.",
                    }
        return results
