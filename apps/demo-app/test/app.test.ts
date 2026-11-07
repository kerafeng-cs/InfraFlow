import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { after, before, beforeEach, describe, it } from "node:test";

import { createHandler, validateNote } from "../src/app.ts";
import { escapeHtml } from "../src/html.ts";
import { FakeRepository } from "./fake-repository.ts";

const repo = new FakeRepository();
let ready = true;
let server: Server;
let base: string;

before(async () => {
  server = createServer(
    createHandler({
      repo,
      environmentId: "env-test",
      hostname: "host-a",
      processStartedAt: new Date("2026-01-01T00:00:00Z"),
      healthTimeoutMs: 50,
      isReady: () => ready,
      log: () => {},
    }),
  );
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

after(() => new Promise<void>((r) => server.close(() => r())));

beforeEach(() => {
  repo.notes = [];
  repo.boots = [{ id: 1, hostname: "host-a", startedAt: new Date("2026-01-01T00:00:00Z") }];
  repo.failing = false;
  repo.pingDelayMs = 0;
  ready = true;
});

describe("health check", () => {
  it("returns 200 when the database answers", async () => {
    const r = await fetch(`${base}/healthz`);
    assert.equal(r.status, 200);
    assert.deepEqual(await r.json(), { status: "ok" });
  });

  it("returns 503 before the schema is applied", async () => {
    ready = false;
    const r = await fetch(`${base}/healthz`);
    assert.equal(r.status, 503);
    assert.deepEqual(await r.json(), { status: "starting" });
  });

  it("returns 503 when the database is down", async () => {
    repo.failing = true;
    assert.equal((await fetch(`${base}/healthz`)).status, 503);
  });

  it("returns 503 when the database does not answer in time", async () => {
    repo.pingDelayMs = 200;
    assert.equal((await fetch(`${base}/healthz`)).status, 503);
  });
});

describe("home page", () => {
  it("renders environment, notes and boots with escaping", async () => {
    await repo.addNote("<script>alert(1)</script>");
    const r = await fetch(`${base}/`);
    assert.equal(r.status, 200);
    assert.match(r.headers.get("content-type") ?? "", /text\/html/);
    const body = await r.text();
    assert.match(body, /env-test/);
    assert.match(body, /host-a/);
    assert.ok(body.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
    assert.ok(!body.includes("<script>alert(1)"));
  });

  it("serves an HTML error page when the database is down", async () => {
    repo.failing = true;
    const r = await fetch(`${base}/`, { headers: { accept: "text/html" } });
    assert.equal(r.status, 503);
    assert.match(await r.text(), /Database unavailable/);
  });
});

describe("form submission", () => {
  it("stores the note and redirects to the home page", async () => {
    const r = await fetch(`${base}/notes`, {
      method: "POST",
      body: new URLSearchParams({ body: "  first   note " }),
      redirect: "manual",
    });
    assert.equal(r.status, 303);
    assert.equal(r.headers.get("location"), "/");
    assert.deepEqual(repo.notes.map((n) => n.body), ["first note"]);
  });

  it("rejects an empty note with 400 and stores nothing", async () => {
    const r = await fetch(`${base}/notes`, { method: "POST", body: new URLSearchParams({ body: "   " }) });
    assert.equal(r.status, 400);
    assert.match(await r.text(), /must not be empty/);
    assert.equal(repo.notes.length, 0);
  });
});

describe("JSON API", () => {
  it("creates and lists notes", async () => {
    const created = await fetch(`${base}/api/notes`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ body: "from api" }),
    });
    assert.equal(created.status, 201);
    const list = (await (await fetch(`${base}/api/notes`)).json()) as { notes: { body: string }[] };
    assert.deepEqual(list.notes.map((n) => n.body), ["from api"]);
  });

  it("rejects malformed JSON", async () => {
    const r = await fetch(`${base}/api/notes`, { method: "POST", body: "{" });
    assert.equal(r.status, 400);
  });

  it("rejects a body larger than the limit", async () => {
    const r = await fetch(`${base}/api/notes`, { method: "POST", body: JSON.stringify({ body: "x".repeat(20_000) }) });
    assert.equal(r.status, 413);
  });

  it("reports status", async () => {
    const s = (await (await fetch(`${base}/api/status`)).json()) as Record<string, unknown>;
    assert.equal(s.environmentId, "env-test");
    assert.equal(s.bootCount, 1);
  });
});

describe("routing", () => {
  it("returns 404 for unknown paths and 405 for wrong methods", async () => {
    assert.equal((await fetch(`${base}/missing`)).status, 404);
    assert.equal((await fetch(`${base}/notes`)).status, 405);
  });
});

describe("validateNote", () => {
  it("accepts up to the limit, counted in code points", () => {
    assert.deepEqual(validateNote("a".repeat(500)), { body: "a".repeat(500) });
    assert.ok("error" in validateNote("a".repeat(501)));
    assert.ok(!("error" in validateNote("\u{1F600}".repeat(500))));
  });

  it("rejects non-strings", () => {
    assert.ok("error" in validateNote(42));
    assert.ok("error" in validateNote(undefined));
  });
});

describe("escapeHtml", () => {
  it("escapes all five special characters", () => {
    assert.equal(escapeHtml(`<a href="x">'&'</a>`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;");
  });
});
