"use strict";

const $ = (id) => document.getElementById(id);
const tabs = [$("single-tab"), $("workbook-tab")];
function selectTab(tab) {
  tabs.forEach((item) => {
    const active = item === tab;
    item.setAttribute("aria-selected", String(active));
    item.tabIndex = active ? 0 : -1;
    item.classList.toggle("active", active);
    $(item.getAttribute("aria-controls")).hidden = !active;
  });
}
tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectTab(tab));
  tab.addEventListener("keydown", (event) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[1] : tabs[1 - index];
      selectTab(next);
      next.focus();
    }
  });
});

function message(id, text, error = false) {
  $(id).textContent = text;
  $(id).classList.toggle("error", error);
}
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: {"X-GS20-Request": "1", ...options.headers} });
  if (!response.ok) throw await responseError(response);
  let data;
  try { data = await response.json(); }
  catch { throw new Error("The server could not complete this request. Please try again."); }
  return data;
}
function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}
$("reference-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("check-button").disabled = true;
  $("single-result").hidden = true;
  message("single-message", "Checking the publication venue…");
  try {
    const result = await api("/api/check", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({reference: $("reference").value})});
    const panel = $("single-result");
    panel.replaceChildren(element("span", result.matched ? "Top 20 match" : "No match", result.matched ? "badge" : "badge no"));
    if (result.matched) panel.append(element("h2", result.venue));
    panel.append(element("p", result.note));
    const list = document.createElement("ul");
    list.className = "rank-list";
    result.memberships.forEach((membership) => {
      const row = document.createElement("li");
      const link = element("a", membership.category + " ↗");
      link.href = membership.source_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      row.append(link, element("strong", "#" + membership.rank));
      list.append(row);
    });
    panel.append(list, element("p", "Scholar snapshot: " + result.snapshot.slice(0, 10), "muted"));
    panel.hidden = false;
    message("single-message", "");
  } catch (error) { message("single-message", error.message, true); }
  finally { $("check-button").disabled = false; }
});

let activeUpload = null;
let downloadUrl = null;
function clearDownload() {
  if (downloadUrl) URL.revokeObjectURL(downloadUrl);
  downloadUrl = null;
  $("download-link").hidden = true;
  $("download-link").removeAttribute("href");
}
function renderProgress(data) {
  $("job-panel").hidden = false;
  const completed = data.total - data.counts.pending;
  $("progress").max = data.total;
  $("progress").value = completed;
  $("progress-count").textContent = `${completed.toLocaleString()} / ${data.total.toLocaleString()}`;
  $("progress-label").textContent = data.phase === "exporting" ? "Preparing download" : "Checking publications";
  ["matched", "unmatched", "error"].forEach((key) => $(key + "-count").textContent = data.counts[key]);
  (data.recent || []).forEach((result) => {
    const tr = document.createElement("tr");
    if (result.status === "error") tr.className = "error-row";
    const verdict = result.status === "matched" ? result.venue : result.status === "error" ? "Error" : "No match";
    tr.append(element("td", result.row), element("td", result.reference || "Missing reference"), element("td", verdict));
    tr.title = result.note;
    $("recent-results").prepend(tr);
  });
  while ($("recent-results").children.length > 50) $("recent-results").lastChild.remove();
}
function cancelUpload() {
  if (!activeUpload) return;
  activeUpload.controller.abort();
  activeUpload.chunks.length = 0;
  $("job-panel").hidden = true;
  $("recent-results").replaceChildren();
  clearDownload();
  message("batch-message", "Cancelled. Upload the workbook again to start over.");
}
$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (activeUpload) return;
  const file = $("workbook").files[0];
  const maxBytes = Number($("workbook").dataset.maxBytes);
  const limitLabel = $("workbook").dataset.limitLabel;
  if (!file || file.size > maxBytes) return message("batch-message", `Choose an .xlsx file no larger than ${limitLabel}.`, true);
  const operation = {controller: new AbortController(), chunks: [], bytes: 0, complete: null};
  activeUpload = operation;
  clearDownload();
  $("job-panel").hidden = true;
  $("recent-results").replaceChildren();
  $("upload-button").disabled = true;
  $("workbook").disabled = true;
  $("cancel-button").hidden = false;
  message("batch-message", "Reading your workbook…");
  const body = new FormData();
  body.append("file", file);
  try {
    const response = await fetch("/api/workbooks/process", {
      method: "POST", headers: {"X-GS20-Request": "1"}, body,
      signal: operation.controller.signal,
    });
    if (!response.ok) {
      throw await responseError(response, "Upload failed.");
    }
    message("batch-message", "Processing batches of 10. Closing this page cancels the upload.");
    await readEvents(response, (data) => {
      if (operation.controller.signal.aborted) throw new DOMException("Cancelled", "AbortError");
      switch (data.type) {
        case "started":
        case "progress": renderProgress(data); break;
        case "heartbeat": break;
        case "file_chunk": {
          const bytes = Uint8Array.from(atob(data.data), (c) => c.charCodeAt(0));
          operation.bytes += bytes.length;
          operation.chunks.push(bytes);
          break;
        }
        case "complete":
          if (data.bytes !== operation.bytes) throw new Error("Incomplete workbook download.");
          operation.complete = data;
          break;
        default: throw new Error("Unexpected response from the server.");
      }
    }, operation.controller.signal);
    const blob = new Blob(operation.chunks, {type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"});
    downloadUrl = URL.createObjectURL(blob);
    $("download-link").href = downloadUrl;
    $("download-link").download = operation.complete.filename;
    $("download-link").hidden = false;
    $("progress-label").textContent = "Processing complete";
    message("batch-message", operation.complete.counts.error
      ? "Finished with some row errors. Download the workbook to review them."
      : "Finished. Your enriched workbook is ready to download.");
  } catch (error) {
    operation.controller.abort();
    clearDownload();
    $("job-panel").hidden = true;
    $("recent-results").replaceChildren();
    message("batch-message", error.name === "AbortError"
      ? "Cancelled. Upload the workbook again to start over."
      : error.message + " No results were saved. Upload again to retry.", error.name !== "AbortError");
  } finally {
    operation.chunks.length = 0;
    activeUpload = null;
    $("cancel-button").hidden = true;
    $("upload-button").disabled = false;
    $("workbook").disabled = false;
  }
});
$("cancel-button").addEventListener("click", cancelUpload);
window.addEventListener("pagehide", () => {cancelUpload(); clearDownload();});
