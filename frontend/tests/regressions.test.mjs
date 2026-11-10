import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

let instance = 0;
async function loadSource(path) {
  const source = (await readFile(new URL(`../src/${path}`, import.meta.url), "utf8"))
    .replaceAll("import.meta.env.VITE_API_BASE_URL", '"/api/"');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}#${instance++}`);
}

test("calendar inputs keep the local day and first day of month", async () => {
  process.env.TZ = "Europe/Istanbul";
  const { localDate } = await loadSource("lib/dates.ts");
  const midnight = new Date(2026, 10, 1, 0, 15);
  assert.equal(midnight.toISOString().slice(0, 10), "2026-10-31");
  assert.equal(localDate(midnight), "2026-11-01");
  assert.equal(localDate(new Date(2026, 0, 1)), "2026-01-01");
});

test("queue links restore the dashboard scope and reject invalid IDs/enums", async () => {
  const { readTicketFilters } = await loadSource("lib/ticketFilters.ts");
  const parsed = readTicketFilters(new URLSearchParams("overdue=1&organization_id=42&priority=P1&status_filter=new"));
  assert.equal(parsed.openOnly, true);
  assert.equal(parsed.overdue, true);
  assert.equal(parsed.organization, 42);
  assert.equal(parsed.priority, "P1");
  for (const value of ["NaN", "-1", "0", "1.5", "Infinity"]) {
    assert.equal(readTicketFilters(new URLSearchParams({ organization_id: value })).organization, "");
  }
  const invalid = readTicketFilters(new URLSearchParams("status_filter=oops&priority=urgent&sla_risk=wrong"));
  assert.equal(invalid.status, "");
  assert.equal(invalid.priority, "");
  assert.equal(invalid.risk, "");
});

function browserState() {
  const data = new Map();
  globalThis.localStorage = { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, v), removeItem: (k) => data.delete(k) };
  const events = new EventTarget();
  globalThis.window = { location: { origin: "https://desk.test" }, dispatchEvent: (e) => events.dispatchEvent(e) };
  return events;
}

test("parallel 401s share one refresh and preserve relative API paths", async () => {
  browserState();
  const client = await loadSource("api/client.ts");
  client.setTokens("expired", "refresh");
  let refreshes = 0;
  let attempts = 0;
  globalThis.fetch = async (url, options) => {
    if (url === "/api/auth/refresh") {
      refreshes++;
      await new Promise((resolve) => setTimeout(resolve, 10));
      return Response.json({ access_token: "new", refresh_token: "rotated" });
    }
    assert.equal(new URL(url).pathname, "/api/tickets");
    attempts++;
    return options.headers.Authorization === "Bearer new"
      ? Response.json({ ok: true })
      : new Response(null, { status: 401 });
  };
  const result = await Promise.all([client.apiRequest("/tickets"), client.apiRequest("/tickets")]);
  assert.deepEqual(result, [{ ok: true }, { ok: true }]);
  assert.equal(refreshes, 1);
  assert.equal(attempts, 4);
});

test("a rejected refreshed token ends the UI session and clears stored credentials", async () => {
  const events = browserState();
  const client = await loadSource("api/client.ts");
  client.setTokens("expired", "refresh");
  let ended = 0;
  events.addEventListener("sd:session-ended", () => ended++);
  globalThis.fetch = async (url) => url === "/api/auth/refresh"
    ? Response.json({ access_token: "still-invalid", refresh_token: "rotated" })
    : new Response(null, { status: 401 });
  await assert.rejects(client.apiRequest("/tickets"), (error) => error.status === 401);
  assert.equal(client.getAccessToken(), null);
  assert.equal(client.getRefreshToken(), null);
  assert.equal(localStorage.getItem("sd_access_token"), null);
  assert.equal(ended, 1);
});

test("logout during a refresh cannot restore or erase a newer login", async () => {
  browserState();
  const client = await loadSource("api/client.ts");
  client.setTokens("expired", "refresh");
  let finishRefresh;
  globalThis.fetch = async (url) => url === "/api/auth/refresh"
    ? new Promise((resolve) => { finishRefresh = () => resolve(Response.json({ access_token: "old-session", refresh_token: "old-refresh" })); })
    : new Response(null, { status: 401 });
  const request = client.apiRequest("/tickets");
  await new Promise((resolve) => setImmediate(resolve));
  client.setTokens(null, null);
  client.setTokens("different-user", "different-refresh");
  finishRefresh();
  await assert.rejects(request, (error) => error.status === 401);
  assert.equal(client.getAccessToken(), "different-user");
  assert.equal(client.getRefreshToken(), "different-refresh");
});


test("multipart upload survives token refresh with the same request identity and files", async () => {
  browserState();
  const client = await loadSource("api/client.ts");
  client.setTokens("expired", "refresh");
  const form = new FormData();
  const payload = { direction: "outbound", body: "reply", request_id: "2a86c85e-9519-4b09-990c-e37bab2f067f" };
  form.append("payload", JSON.stringify(payload));
  form.append("files", new Blob(["file bytes"], { type: "text/plain" }), "private.txt");
  let uploads = 0;
  globalThis.fetch = async (url, options) => {
    if (url === "/api/auth/refresh") return Response.json({ access_token: "fresh", refresh_token: "rotated" });
    uploads++;
    assert.equal(options.body, form);
    assert.deepEqual(JSON.parse(form.get("payload")), payload);
    assert.equal(form.get("files").name, "private.txt");
    assert.equal(await form.get("files").text(), "file bytes");
    assert.equal(options.headers.has("Content-Type"), false);
    return options.headers.get("Authorization") === "Bearer fresh"
      ? Response.json({ id: 123 }) : new Response(null, { status: 401 });
  };
  assert.deepEqual(await client.apiForm("/tickets/1/messages/send", form), { id: 123 });
  assert.equal(uploads, 2);
});

test('project board gates execution on approval and dependencies, and acceptance on ownership', async () => {
  const {taskTargets} = await loadSource('lib/work.ts');
  assert.deepEqual(taskTargets('backlog', 'planning', true, false), ['ready', 'cancelled']);
  assert.deepEqual(taskTargets('ready', 'approval', true, false), []);
  assert.deepEqual(taskTargets('ready', 'approved', true, false), []);
  assert.deepEqual(taskTargets('in_progress', 'paused', true, false), []);
  assert.equal(taskTargets('ready', 'in_progress', false, true).includes('in_progress'), false);
  assert.equal(taskTargets('ready', 'in_progress', false, false).includes('in_progress'), true);
  assert.deepEqual(taskTargets('review', 'in_progress', false, false), ['in_progress']);
  assert.equal(taskTargets('review', 'in_progress', true, false).includes('done'), true);
  assert.deepEqual(taskTargets('done', 'in_progress', false, false), []);
});

test('replanning allows the owner to return reviewed or accepted tasks to the plan', async () => {
  const {taskTargets} = await loadSource('lib/work.ts');
  assert.deepEqual(taskTargets('review', 'planning', true, false), ['backlog', 'ready', 'cancelled']);
  assert.deepEqual(taskTargets('done', 'planning', true, false), ['backlog', 'ready', 'cancelled']);
  assert.deepEqual(taskTargets('review', 'planning', false, false), []);
});

test("image attachment previews recognize legacy files and retain original bytes", async () => {
  const { isImageAttachment, rasterImageBlob } = await loadSource("lib/imagePreview.ts");
  assert.equal(isImageAttachment({ filename: "SCREEN.PNG", mime_type: "application/octet-stream" }), true);
  assert.equal(isImageAttachment({ filename: "screenshot", mime_type: "image/jpeg" }), true);
  assert.equal(isImageAttachment({ filename: "manual.pdf", mime_type: "application/pdf" }), false);
  const bytes = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10, 0, 1, 2, 3]);
  const image = await rasterImageBlob(new Blob([bytes], { type: "application/octet-stream" }));
  assert.equal(image.type, "image/png");
  assert.deepEqual(new Uint8Array(await image.arrayBuffer()), bytes);
});

test("untrusted HTML and SVG cannot become a navigable image preview by changing their name or MIME", async () => {
  const { isImageAttachment, rasterImageBlob } = await loadSource("lib/imagePreview.ts");
  assert.equal(isImageAttachment({ filename: "image.png", mime_type: "image/svg+xml" }), false);
  assert.equal(await rasterImageBlob(new Blob(["<svg onload='alert(1)'></svg>"], { type: "image/png" })), null);
  assert.equal(await rasterImageBlob(new Blob(["<html><script>alert(1)</script></html>"], { type: "image/jpeg" })), null);
});

test("one editor document round-trips paragraphs and screenshots without adding labels or uploading blob URLs", async () => {
  const { draftToDocument, documentToDraft, messageDraftPayload } = await loadSource("lib/messageDraft.ts");
  const image = new File([new Uint8Array([137, 80, 78, 71])], "screen.png", { type: "image/png" });
  const extra = new File(["log"], "log.txt", { type: "text/plain" });
  const pool = new Map([["image-1", { file: image, url: "blob:local-only" }]]);
  const draft = { blocks: [{ id: "t1", type: "text", text: "Проверьте настройку\nв этом окне:" },
    { id: "image-1", type: "image", file: image }, { id: "t2", type: "text", text: "Затем сохраните изменения." }], files: [extra] };
  const doc = draftToDocument(draft, pool);
  const result = messageDraftPayload(documentToDraft(doc, pool, [extra]));
  assert.equal(result.body, "Проверьте настройку\nв этом окне:\nЗатем сохраните изменения.");
  assert.deepEqual(result.content_blocks, [{ type: "text", text: "Проверьте настройку\nв этом окне:" },
    { type: "image", file_index: 0 }, { type: "text", text: "Затем сохраните изменения." }]);
  assert.equal(result.files[0], image);
  assert.equal(result.files[1], extra);
  assert.equal(JSON.stringify(result.content_blocks).includes("blob:"), false);
});

test("editor keeps intentional blank lines and soft line breaks", async () => {
  const { documentToDraft, messageDraftPayload } = await loadSource("lib/messageDraft.ts");
  const draft = documentToDraft({ type: "doc", content: [
    { type: "paragraph", content: [{ type: "text", text: "Строка" }, { type: "hardBreak" }, { type: "text", text: "Продолжение" }] },
    { type: "paragraph" }, { type: "paragraph", content: [{ type: "text", text: "Абзац" }] },
  ] }, new Map(), []);
  assert.equal(messageDraftPayload(draft).body, "Строка\nПродолжение\n\nАбзац");
});
