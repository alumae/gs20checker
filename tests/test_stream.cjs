const {test} = require("node:test");
const assert = require("node:assert/strict");
const {readEvents, responseError} = require("../app/static/stream.js");

function response(parts) {
  return new Response(new ReadableStream({start(controller) {
    parts.forEach(part => controller.enqueue(part));
    controller.close();
  }}));
}
const encode = value => new TextEncoder().encode(value);

test("parses arbitrary byte and UTF-8 boundaries", async () => {
  const bytes = encode('{"type":"progress","note":"Jörgen"}\n{"type":"complete"}\n');
  const events = [];
  await readEvents(response([...bytes].map(byte => new Uint8Array([byte]))), e => events.push(e));
  assert.equal(events[0].note, "Jörgen");
  assert.equal(events[1].type, "complete");
});
test("rejects truncation, missing completion and terminal errors", async () => {
  for (const data of ['{"type":"heartbeat"}\n', '{"type":"complete"}',
    '{"type":"error","error":"Quota exhausted"}\n']) {
    await assert.rejects(readEvents(response([encode(data)]), () => {}));
  }
});
test("does not accept completion after cancellation", async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(readEvents(response([encode('{"type":"complete"}\n')]),
    () => {}, controller.signal), {name: "AbortError"});
});

test("explains non-JSON firewall and platform errors", async () => {
  const rate = await responseError(new Response("<html>rate limited</html>", {
    status: 429, headers: {"Retry-After": "600"},
  }));
  assert.match(rate.message, /Too many requests.*600 seconds/);
  for (const [status, message] of [[413, /too large/], [504, /timed out/], [502, /server/]]) {
    assert.match((await responseError(new Response("platform error", {status}))).message, message);
  }
  const api = await responseError(new Response('{"error":"Upload the original workbook."}', {status: 400}));
  assert.equal(api.message, "Upload the original workbook.");
});
