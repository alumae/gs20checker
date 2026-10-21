"""One streaming HTTP response owns all workbook processing state."""

import asyncio
import base64
import json
import logging
import time

from app.matching import MatchError
from app.workbooks import export_workbook

HEARTBEAT_SECONDS = 2
FILE_CHUNK_BYTES = 48 * 1024
logger = logging.getLogger(__name__)


def event(kind, **data):
    return json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n"


class StreamBudget:
    """Count wire bytes, reserving enough space to explain a terminal failure."""

    ERROR_RESERVE = 2048

    def __init__(self, deadline, maximum):
        self.deadline, self.maximum, self.sent = deadline, maximum, 0

    def remaining(self):
        if self.deadline is None:
            return float("inf")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise MatchError(
                "The processing time limit was reached. Split the workbook into smaller "
                "files and try again. No download was saved."
            )
        return remaining

    def ensure_size(self, size):
        if self.maximum is not None and self.sent + size > self.maximum - self.ERROR_RESERVE:
            raise MatchError(
                "The results exceed the hosted response size limit. Split the workbook "
                "into smaller files and try again. No download was saved."
            )

    def emit(self, kind, **data):
        self.remaining()
        line = event(kind, **data)
        size = len(line.encode("utf-8"))
        self.ensure_size(size)
        self.sent += size
        return line


def process_workbook(
    content,
    rows,
    sheets,
    catalogue,
    matcher_factory,
    heartbeat_seconds=HEARTBEAT_SECONDS,
    *,
    deadline=None,
    max_response_bytes=None,
):
    """Closing this generator cancels the outstanding API task, including SDK retries.

    The WSGI server must close the iterable on disconnect. Heartbeats make a lost
    connection observable while an asynchronous model request is outstanding.
    No thread, global task registry, file, or result survives this generator.
    """
    loop = None
    engine = None
    task = None
    memo = {}
    output = None
    budget = StreamBudget(deadline, max_response_bytes)
    started_at = time.monotonic()
    outcome = "cancelled"
    counts = {"matched": 0, "unmatched": 0, "error": 0, "pending": len(rows)}
    try:
        yield budget.emit("started", total=len(rows), counts=counts, snapshot=catalogue.snapshot)
        budget.remaining()
        loop = asyncio.new_event_loop()
        engine = matcher_factory()
        for offset in range(0, len(rows), 10):
            budget.remaining()
            group = rows[offset : offset + 10]
            pending, keys = {}, {}
            for index, row in enumerate(group):
                key = json.dumps(row["fields"], ensure_ascii=False, sort_keys=True)
                keys[index] = key
                if not row["fields"]:
                    memo[key] = catalogue.result(False, None, "No usable publication reference.")
                elif len(key) > 20000:
                    memo[key] = {"status": "error", "note": "Reference exceeds 20,000 characters."}
                elif key not in memo and key not in pending:
                    pending[key] = {"id": str(offset + index), "fields": row["fields"]}
            if pending:
                task = loop.create_task(engine.match_batch(list(pending.values())))
                while not task.done():
                    loop.run_until_complete(
                        asyncio.wait({task}, timeout=min(heartbeat_seconds, budget.remaining()))
                    )
                    budget.remaining()
                    if not task.done():
                        yield budget.emit("heartbeat")
                results = task.result()
                task = None
                for key, item in pending.items():
                    memo[key] = results[item["id"]]
            recent = []
            for index, row in enumerate(group):
                row["result"] = memo[keys[index]]
                counts[row["result"]["status"]] += 1
                counts["pending"] -= 1
                recent.append(
                    {
                        "sheet": row["sheet"],
                        "row": row["row"],
                        "reference": row["fields"].get("reference", ""),
                        **row["result"],
                    }
                )
            yield budget.emit("progress", total=len(rows), counts=counts, recent=recent)
        # An explicit event also gives disconnect handling a chance before CPU-bound export.
        yield budget.emit("progress", total=len(rows), counts=counts, recent=[], phase="exporting")
        budget.remaining()
        output = export_workbook(
            content,
            {
                "rows": rows,
                "sheets": sheets,
                "snapshot": catalogue.snapshot,
            },
        )
        size = output.getbuffer().nbytes
        completion = {
            "filename": "Publications_GS20.xlsx",
            "bytes": size,
            "counts": counts,
            "total": len(rows),
        }
        # FILE_CHUNK_BYTES is divisible by three, so base64 padding only occurs
        # in the last chunk. Check the entire download before sending any of it.
        chunks = (size + FILE_CHUNK_BYTES - 1) // FILE_CHUNK_BYTES
        budget.ensure_size(
            4 * ((size + 2) // 3)
            + chunks * len(event("file_chunk", data="").encode("utf-8"))
            + len(event("complete", **completion).encode("utf-8"))
        )
        while chunk := output.read(FILE_CHUNK_BYTES):
            yield budget.emit("file_chunk", data=base64.b64encode(chunk).decode("ascii"))
        complete = budget.emit("complete", **completion)
        outcome = "completed"
        yield complete
    except MatchError as exc:
        outcome = "failed"
        yield event("error", error=str(exc))
    except Exception:
        outcome = "failed"
        # Never send exception payloads, references, or credentials to logs/browser.
        yield event("error", error="The workbook could not be processed. Upload it again to retry.")
    finally:
        try:
            if loop is not None:
                try:
                    if task is not None:
                        task.cancel()
                        loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
                    if engine is not None:
                        loop.run_until_complete(engine.close())
                except Exception as exc:
                    logger.warning("Request client cleanup failed (%s)", type(exc).__name__)
                finally:
                    try:
                        loop.run_until_complete(loop.shutdown_asyncgens())
                    finally:
                        loop.close()
        finally:
            logger.info(
                "Workbook processing ended: outcome=%s model_requests=%d elapsed_seconds=%.1f",
                outcome,
                getattr(engine, "requests", 0),
                time.monotonic() - started_at,
            )
            if output is not None:
                output.close()
            memo.clear()
            rows.clear()
            content = None
