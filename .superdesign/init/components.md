# Components

InfraFlow is a vanilla JavaScript app. There is no component library. Reusable primitives are CSS selectors in `web/style.css`; shared DOM builders are in `web/app.js`. Full source follows.

## Shared helpers — web/app.js

```javascript
  // ---------------- helpers ----------------
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const dateTime = new Intl.DateTimeFormat(navigator.language || "en", { dateStyle: "medium", timeStyle: "short" });
  const number = new Intl.NumberFormat(navigator.language || "en", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmt = (iso) => (iso ? dateTime.format(new Date(iso)) : "-");
  const badge = (a) => {
    const k = String(a || "").split(":")[0];
    return `<span class="badge b-${esc(k)}">${esc(a || "-")}</span>`;
  };
  const CLASS = { network: "free", egress: "hourly_no_data", database: "data", app: "stoppable", entry: "hourly_no_data" };
  const insts = (m) => Object.entries(m || {}).map(([k, v]) => `<span class="inst c-${CLASS[k] || ""}">${esc(k)}: ${esc(v)}</span>`).join("");
  const toLocalInput = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  function fail(e) { view.insertAdjacentHTML("afterbegin", `<div class="alert" role="alert"><strong>Could not complete the request</strong><p>${esc(e.message || e)}</p></div>`); }

```

## Shared visual primitives — web/style.css

```css
:root { color-scheme: light; --bg:#f6f8fb; --panel:#fff; --nav:#10233e; --ink:#14243a; --muted:#51647c; --line:#d8e1ec; --accent:#2458d3; --ok:#126445; --warn:#8b510d; --bad:#aa2828; --sleep:#435b79; --free:#e4f3e9; --stop:#e3edfa; --hour:#fff0d9; --data:#f5e8f3; }
* { box-sizing: border-box; }
[hidden] { display:none !important; }
body { margin:0; font:15px/1.55 "Segoe UI",system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--ink); }
a { color:var(--accent); text-underline-offset:3px; }
.skip-link { position:absolute; top:-60px; left:20px; z-index:10; padding:10px 14px; background:var(--ink); color:#fff; border-radius:8px; }
.skip-link:focus { top:12px; }
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible { outline:3px solid #f2a900; outline-offset:2px; }
.app-header { display:flex; align-items:center; gap:38px; min-height:74px; padding:0 max(24px,calc((100vw - 1240px)/2)); background:var(--nav); color:#fff; }
.brand { display:flex; align-items:center; gap:12px; color:#fff; text-decoration:none; font-size:19px; font-weight:750; letter-spacing:-.035em; white-space:nowrap; }
.brand-mark { display:inline-grid; place-items:center; width:36px; height:36px; border-radius:6px; background:#3f75e8; color:#fff; font-size:19px; }
.primary-nav { display:flex; align-self:stretch; align-items:center; gap:24px; flex-wrap:nowrap; }
.primary-nav a { display:inline-flex; align-items:center; align-self:stretch; color:#b6c8e0; text-decoration:none; padding:3px 0 0; border-bottom:3px solid transparent; font-size:14px; font-weight:650; white-space:nowrap; }
.primary-nav a:hover,.primary-nav a[aria-current="page"] { color:#fff; border-bottom-color:#76a0ff; }
.header-user { display:flex; align-items:center; gap:12px; margin-left:auto; min-width:0; }
.header-user #logout { background:transparent; color:#fff; border-color:#57708f; }
.header-user #logout:hover { background:#1b385d; }
.header-user #who { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:190px; color:#b6c8e0; font-size:13px; }
main { max-width:1240px; margin:0 auto; padding:44px 24px 80px; }
.page-intro { margin-bottom:30px; } .eyebrow { margin:0 0 10px; color:var(--muted); font-size:13px; font-weight:650; }
.page-intro.with-action { display:flex; align-items:flex-end; justify-content:space-between; gap:24px; }
.page-intro.with-action > .btn { flex:none; }
.page-title { margin:0; font-size:clamp(28px,3vw,38px); letter-spacing:-.04em; line-height:1.12; text-wrap:balance; } .page-summary { margin:12px 0 0; color:var(--muted); max-width:68ch; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:24px; margin-bottom:18px; }
.panel-head { display:flex; align-items:flex-start; gap:16px; justify-content:space-between; margin-bottom:18px; } .panel-head h2 { margin-bottom:2px; } .panel-subtitle { margin:0; color:var(--muted); font-size:13px; }
.row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; } .sp { flex:1; } .muted { color:var(--muted); }
h2 { font-size:19px; letter-spacing:-.025em; margin:0 0 14px; } h3 { font-size:15px; margin:22px 0 9px; } p { margin-top:0; }
.table-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:6px; } table { width:100%; border-collapse:collapse; min-width:680px; }
th,td { text-align:left; padding:12px 14px; border-bottom:1px solid var(--line); vertical-align:top; } tr:last-child td { border-bottom:0; }
th { background:#f7f9fc; font-weight:750; color:var(--muted); font-size:11px; letter-spacing:.07em; text-transform:uppercase; } tbody tr:hover { background:#f7faff; }
button,.btn { display:inline-flex; align-items:center; justify-content:center; gap:7px; font:inherit; font-weight:650; text-decoration:none; border:1px solid #bccadd; background:var(--panel); color:var(--ink); padding:9px 13px; min-height:44px; border-radius:6px; cursor:pointer; touch-action:manipulation; }
button:hover,.btn:hover { background:#edf3fc; text-decoration:none; } button.primary,.btn.primary { background:var(--accent); border-color:var(--accent); color:#fff; } button.primary:hover,.btn.primary:hover { background:#1747b4; }
button.danger { color:var(--bad); border-color:#edc9c9; } button.danger:hover { background:#fff2f1; } button:disabled { opacity:.55; cursor:default; }
input,select,textarea { font:inherit; padding:9px 11px; border:1px solid #bccadd; border-radius:6px; background:var(--panel); color:var(--ink); max-width:100%; min-height:44px; }
input[type="checkbox"] { min-height:auto; accent-color:var(--accent); } label { display:block; font-size:13px; font-weight:650; color:var(--ink); margin:12px 0 5px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px 18px; }
.grid input:not([type="checkbox"]),.grid select { width:100%; }
label textarea { font-weight:400; }
.badge { display:inline-block; padding:3px 9px; border-radius:999px; font-size:12px; font-weight:750; border:1px solid currentColor; white-space:nowrap; }
.b-AWAKE,.b-SUCCEEDED { color:var(--ok); background:#e7f5ee; } .b-ASLEEP,.b-PREPARED { color:var(--sleep); background:#edf1f7; }
.b-CHANGING,.b-WAKING,.b-SLEEPING,.b-RUNNING,.b-ACCEPTED { color:var(--warn); background:#fff5e4; } .b-BLOCKED,.b-FAILED { color:var(--bad); background:#fff0ef; }
.b-REQUESTED,.b-MIXED,.b-ABSENT { color:var(--muted); background:#f2f4f7; }
.inst { display:inline-block; padding:2px 8px; border-radius:6px; margin:2px 4px 2px 0; font-size:12px; } .c-free { background:var(--free); } .c-stoppable { background:var(--stop); } .c-hourly_no_data { background:var(--hour); } .c-data { background:var(--data); }
.err { color:var(--bad); white-space:pre-wrap; } .alert { padding:13px 16px; border:1px solid #edc9c9; border-left:4px solid var(--bad); border-radius:8px; background:#fff7f6; margin:12px 0; } .alert p { margin:4px 0 0; }
.status-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin:16px 0; } .status-item { border:1px solid var(--line); border-radius:9px; padding:12px 14px; min-width:0; } .status-item small { display:block; color:var(--muted); font-weight:700; margin-bottom:4px; } .status-item strong { overflow-wrap:anywhere; }
.state-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:16px 0; } .field-note { color:var(--muted); font-size:13px; margin:8px 0 0; overflow-wrap:anywhere; }
.operation-banner { display:flex; align-items:center; flex-wrap:wrap; gap:10px; padding:14px; border:1px solid #e7cf9b; border-radius:9px; background:#fffaf0; } .operation-banner code { margin-left:auto; }
.resource-list { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; margin-top:14px; } .resource-item { display:flex; flex-direction:column; gap:3px; border:1px solid var(--line); border-radius:8px; padding:12px; overflow-wrap:anywhere; }
.operation-list { list-style:none; padding:0; margin:12px 0 0; } .operation-list li { padding:14px 0; border-top:1px solid var(--line); overflow-wrap:anywhere; } .operation-list li:first-child { border-top:0; }
.admin-case { border-top:1px solid var(--line); padding:16px 0; } .admin-case:first-child { margin-top:16px; } .admin-case h3 { margin:0 0 8px; } .admin-case textarea { display:block; width:min(100%,620px); margin:6px 0 10px; }
.review-box { border:1px solid #e7cf9b; border-radius:9px; background:#fffaf0; padding:16px; margin:18px 0 0; } .review-box h3 { margin:0 0 8px; } .check-line { display:flex; align-items:flex-start; gap:8px; margin:14px 0; max-width:68ch; } .check-line input { margin-top:3px; flex:none; }
.review-box + .row { margin-top:16px; }
.environment-panel { padding:0; overflow:hidden; } .environment-panel > .panel-head { padding:23px 24px 18px; margin:0; }
.env-filters { padding:14px 24px 18px; gap:16px; background:#fbfcfe; border-top:1px solid var(--line); }
.env-filters > div:first-child { flex:1 1 350px; } .env-filters > div:last-child { flex:0 1 220px; }
.env-filters label { margin:0 0 6px; } .env-filters input,.env-filters select { width:100%; }
.environment-panel #env-list { padding:0 24px 20px; } .environment-panel #env-list > .field-note { margin:12px 0; }
.environment-panel tr.attention-blocked td:first-child { box-shadow:inset 4px 0 var(--bad); } .environment-panel tr.attention-changing td:first-child { box-shadow:inset 4px 0 #b98b3b; }
.kpi { font-size:25px; font-weight:750; letter-spacing:-.035em; font-variant-numeric:tabular-nums; } .cost-note { color:var(--muted); font-size:13px; margin:14px 0 0; }
.empty { padding:30px 18px; text-align:center; color:var(--muted); } .empty strong { display:block; font-size:16px; color:var(--ink); }
.login-panel { max-width:430px; margin:8vh auto; box-shadow:0 20px 50px rgba(16,35,62,.08); } .login-panel input { width:100%; }
.login-panel #login-form > .row { margin:20px 0 0; }
.login-panel #msg { margin:16px 0 0; }
.sleep-page { max-width:620px; padding-top:min(12vh,100px); } .sleep-panel { padding:32px; } .sleep-steps { padding-left:24px; margin:18px 0; } .sleep-steps li { margin:8px 0; } .sleep-icon { display:inline-grid; place-items:center; width:42px; height:42px; margin-bottom:18px; border-radius:12px; color:var(--accent); background:#eaf0fe; font-size:22px; }
code { font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace; background:var(--bg); padding:2px 5px; border-radius:4px; overflow-wrap:anywhere; }
@media(max-width:1000px) { .app-header { gap:18px; } .primary-nav { gap:15px; } .header-user #who { display:none; } }
@media(max-width:800px) { .app-header { padding:12px 20px 0; gap:12px; flex-wrap:wrap; } .primary-nav { order:3; width:100%; min-height:48px; overflow-x:auto; gap:22px; } .primary-nav a { flex:none; } main { padding:30px 16px 60px; } .status-grid { grid-template-columns:1fr; } .state-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(max-width:520px) { .state-grid { grid-template-columns:1fr; } }
@media(max-width:520px) { .panel { padding:18px 16px; } .panel-head { flex-direction:column; } .page-intro.with-action { align-items:flex-start; flex-direction:column; } .environment-panel { padding:0; } .environment-panel > .panel-head { padding:18px 16px; } .env-filters { padding:14px 16px; } .env-filters > div { flex:1 1 100% !important; } .environment-panel #env-list { padding:0 16px 18px; } .header-user #who { max-width:120px; } .sleep-panel { padding:24px 18px; } }
@media(max-width:640px) {
  .environment-table { overflow:visible; border:0; }
  .environment-table table,.environment-table tbody,.environment-table tr,.environment-table td { display:block; min-width:0; width:100%; }
  .environment-table tr:first-child { display:none; }
  .environment-table tr:not(:first-child) { border:1px solid var(--line); border-radius:9px; margin:0 0 12px; padding:10px 14px; }
  .environment-panel tr.attention-blocked { border-left:4px solid var(--bad); }
  .environment-panel tr.attention-changing { border-left:4px solid #b98b3b; }
  .environment-panel tr.attention-blocked td:first-child,.environment-panel tr.attention-changing td:first-child { box-shadow:none; }
  .environment-table td { border:0; padding:7px 0; overflow-wrap:anywhere; }
  .environment-table td::before { content:attr(data-label); display:block; color:var(--muted); font-size:12px; font-weight:700; margin-bottom:3px; }
  .environment-table td.row { display:flex; flex-wrap:wrap; }
  .environment-table td.row::before { flex-basis:100%; }
}

```
