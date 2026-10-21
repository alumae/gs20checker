"use strict";

// Edge/platform failures may be HTML or plain text rather than Flask JSON.
async function responseError(response, fallback = "The server could not complete this request.") {
  if (response.status === 429) {
    const seconds = Number(response.headers.get("Retry-After"));
    const wait = Number.isFinite(seconds) && seconds > 0
      ? ` Try again in ${Math.ceil(seconds)} seconds.`
      : " Please wait before trying again.";
    return new Error("Too many requests from your network." + wait);
  }
  if (response.status === 413) return new Error("This upload is too large. Choose a smaller workbook.");
  if (response.status === 504) return new Error("Processing timed out. Try a smaller workbook.");
  try {
    const data = await response.json();
    if (typeof data.error === "string") return new Error(data.error);
  } catch { /* Non-JSON platform errors must not mask the HTTP failure. */ }
  return new Error(fallback);
}

// Also exported for dependency-free Node tests of network chunk boundaries.
async function readEvents(response, onEvent, signal) {
  if (!response.body) throw new Error("Streaming is unavailable in this browser.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let completed = false;
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
      const {value, done} = await reader.read();
      pending += decoder.decode(value, {stream: !done});
      let newline;
      while ((newline = pending.indexOf("\n")) >= 0) {
        const line = pending.slice(0, newline);
        pending = pending.slice(newline + 1);
        if (!line.trim()) continue;
        if (completed) throw new Error("Unexpected data after completion.");
        const event = JSON.parse(line);
        if (event.type === "error") throw new Error(event.error || "Processing failed.");
        onEvent(event);
        completed = event.type === "complete";
      }
      if (pending.length > 1024 * 1024) throw new Error("Invalid response from the server.");
      if (done) break;
    }
    if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
    if (pending.trim() || !completed) throw new Error("Connection interrupted. Upload again to retry.");
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

if (typeof module !== "undefined") module.exports = {readEvents, responseError};
