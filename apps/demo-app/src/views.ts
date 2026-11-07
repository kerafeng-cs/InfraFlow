import { html, raw, type SafeHtml } from "./html.ts";
import type { Boot, Note, Summary } from "./repository.ts";
import { MAX_NOTE_LENGTH } from "./repository.ts";

export interface PageModel {
  environmentId: string;
  hostname: string;
  processStartedAt: Date;
  summary: Summary;
  notes: Note[];
  boots: Boot[];
  error?: string;
}

const STYLE = `
:root { color-scheme: light dark; --fg: #1d2125; --muted: #5f6b76; --bg: #f6f7f8; --card: #ffffff; --line: #d9dee3; --accent: #1f6feb; }
@media (prefers-color-scheme: dark) { :root { --fg: #e6e8ea; --muted: #9aa5b1; --bg: #111417; --card: #1a1e22; --line: #2c3238; --accent: #4c8dff; } }
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--fg); background: var(--bg); }
main { max-width: 760px; margin: 0 auto; padding: 32px 16px 48px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 0 0 12px; }
.sub { color: var(--muted); margin: 0 0 24px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 16px; margin-bottom: 16px; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin: 0; }
dt { color: var(--muted); }
dd { margin: 0; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
form { display: flex; gap: 8px; margin-bottom: 12px; }
input[type=text] { flex: 1; min-width: 0; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); font: inherit; }
button { padding: 8px 14px; border: 0; border-radius: 6px; background: var(--accent); color: #fff; font: inherit; cursor: pointer; }
ul { list-style: none; margin: 0; padding: 0; }
li { padding: 8px 0; border-top: 1px solid var(--line); display: flex; justify-content: space-between; gap: 12px; }
li:first-child { border-top: 0; }
time, .muted { color: var(--muted); font-size: 13px; white-space: nowrap; }
.error { color: #c62828; margin: 0 0 12px; }
`;

const fmt = (d: Date | null): string => (d ? d.toISOString().replace("T", " ").slice(0, 19) + " UTC" : "-");

export function renderPage(m: PageModel): SafeHtml {
  return html`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>InfraFlow demo app</title>
<style>${raw(STYLE)}</style>
</head>
<body>
<main>
  <h1>InfraFlow demo app</h1>
  <p class="sub">Environment <strong>${m.environmentId}</strong>. Notes written here are stored in PostgreSQL and remain after the environment sleeps and wakes.</p>

  <section class="card">
    <h2>Notes</h2>
    ${m.error ? html`<p class="error">${m.error}</p>` : ""}
    <form method="post" action="/notes">
      <input type="text" name="body" maxlength="${MAX_NOTE_LENGTH}" required placeholder="Write a note" aria-label="Note">
      <button type="submit">Save</button>
    </form>
    ${m.notes.length === 0
      ? html`<p class="muted">No notes yet.</p>`
      : html`<ul>${m.notes.map((n) => html`<li><span>${n.body}</span><time datetime="${n.createdAt.toISOString()}">${fmt(n.createdAt)}</time></li>`)}</ul>`}
  </section>

  <section class="card">
    <h2>Runtime</h2>
    <dl>
      <dt>Host</dt><dd>${m.hostname}</dd>
      <dt>Process started</dt><dd>${fmt(m.processStartedAt)}</dd>
      <dt>Recorded boots</dt><dd>${m.summary.bootCount}</dd>
      <dt>First boot</dt><dd>${fmt(m.summary.firstBootAt)}</dd>
      <dt>Stored notes</dt><dd>${m.summary.noteCount}</dd>
      <dt>PostgreSQL</dt><dd>${m.summary.serverVersion}</dd>
    </dl>
  </section>

  <section class="card">
    <h2>Recent boots</h2>
    <ul>${m.boots.map((b) => html`<li><span>${b.hostname}</span><time datetime="${b.startedAt.toISOString()}">${fmt(b.startedAt)}</time></li>`)}</ul>
  </section>
</main>
</body>
</html>`;
}

export function renderUnavailable(environmentId: string): SafeHtml {
  return html`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Database unavailable</title></head>
<body style="font:15px/1.5 system-ui,sans-serif;max-width:640px;margin:48px auto;padding:0 16px">
<h1 style="font-size:20px">Database unavailable</h1>
<p>Environment <strong>${environmentId}</strong> is running, but the database did not respond. Retry in a few seconds.</p>
</body></html>`;
}
