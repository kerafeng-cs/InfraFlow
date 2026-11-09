# Theme

## Compact token summary

Current framework: vanilla HTML, CSS and JavaScript; no npm frontend dependency or UI library. Base font: self-hosted IBM Plex Sans Latin/Vietnamese, 15px/1.5. Canvas #f8f9fa, surface #fff, rail #f3f5f6, text #1d2733, muted #576472, blue action #2156a0. Status colors: green #126445, amber #8b510d, red #a62d2d. Panel/control radius 3px. Desktop rail width 228px. Breakpoints 900px, 640px, 520px. Reusable tokens are CSS variables in :root.

## Full source — web/style.css

```css
@font-face { font-family:"IBM Plex Sans"; src:url("fonts/ibm-plex-sans-latin.woff2") format("woff2"); font-style:normal; font-weight:100 700; font-display:swap; unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD; }
@font-face { font-family:"IBM Plex Sans"; src:url("fonts/ibm-plex-sans-vietnamese.woff2") format("woff2"); font-style:normal; font-weight:100 700; font-display:swap; unicode-range:U+0102-0103,U+0110-0111,U+0128-0129,U+0168-0169,U+01A0-01A1,U+01AF-01B0,U+0300-0301,U+0303-0304,U+0308-0309,U+0323,U+0329,U+1EA0-1EF9,U+20AB; }
:root { color-scheme:light; --bg:#f8f9fa; --panel:#fff; --ink:#1d2733; --muted:#576472; --line:#dce2e8; --accent:#2156a0; --ok:#126445; --warn:#8b510d; --bad:#a62d2d; --sleep:#435b79; --free:#e4f3e9; --stop:#e3edfa; --hour:#fff0d9; --data:#f5e8f3; }
* { box-sizing: border-box; }
[hidden] { display:none !important; }
body { margin:0; font:15px/1.5 "IBM Plex Sans","Segoe UI",system-ui,sans-serif; background:var(--bg); color:var(--ink); }
a { color:var(--accent); text-underline-offset:3px; }
.skip-link { position:absolute; top:-60px; left:20px; z-index:10; padding:10px 14px; background:var(--ink); color:#fff; border-radius:8px; }
.skip-link:focus { top:12px; }
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible { outline:3px solid #f2a900; outline-offset:2px; }
.app-header { position:fixed; inset:0 auto 0 0; z-index:5; display:flex; flex-direction:column; align-items:stretch; width:228px; padding:30px 14px 20px; background:#f3f5f6; border-right:1px solid var(--line); }
.brand { display:flex; align-items:center; gap:11px; margin:0 12px; color:var(--ink); text-decoration:none; font-size:20px; font-weight:650; letter-spacing:-.02em; white-space:nowrap; }
.brand-mark { display:block; width:3px; height:24px; border-radius:0; background:var(--accent); color:transparent; font-size:0; }
.primary-nav { display:flex; flex-direction:column; align-items:stretch; gap:2px; margin-top:38px; }
.primary-nav a { display:flex; align-items:center; min-height:42px; padding:9px 12px; border-left:2px solid transparent; color:#435162; text-decoration:none; font-size:14px; font-weight:550; }
.primary-nav a:hover,.primary-nav a[aria-current="page"] { color:#173f77; background:#e6edf5; border-left-color:var(--accent); }
.header-user { display:flex; flex-direction:column; align-items:stretch; gap:10px; margin-top:auto; min-width:0; padding:14px 12px 0; border-top:1px solid var(--line); }
.header-user #logout { align-self:flex-start; background:transparent; color:var(--ink); border-color:#b8c4d0; }
.header-user #logout:hover { background:#e6edf5; }
.header-user #who { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:180px; color:var(--muted); font-size:13px; }
main { max-width:none; margin:0 0 0 228px; padding:44px clamp(24px,4vw,64px) 80px; }
.signed-out .app-header { position:static; width:auto; min-height:72px; flex-direction:row; align-items:center; padding:0 32px; border-right:0; border-bottom:1px solid var(--line); }
.signed-out .brand { margin:0; }
.signed-out .header-user { display:none; }
.signed-out main { max-width:640px; margin:0 auto; padding:48px 16px 80px; }
.page-intro { margin-bottom:28px; } main:not(.sleep-page) .eyebrow { display:none; } .eyebrow { margin:0 0 10px; color:var(--muted); font-size:13px; font-weight:600; }
.page-intro.with-action { display:flex; align-items:flex-end; justify-content:space-between; gap:24px; }
.page-intro.with-action > .btn { flex:none; }
.page-title { margin:0; font-size:clamp(28px,2.7vw,34px); font-weight:600; letter-spacing:-.025em; line-height:1.15; text-wrap:balance; } .page-summary { margin:10px 0 0; color:var(--muted); max-width:68ch; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:3px; padding:24px; margin-bottom:16px; }
.panel-head { display:flex; align-items:flex-start; gap:16px; justify-content:space-between; margin-bottom:18px; } .panel-head h2 { margin-bottom:2px; } .panel-subtitle { margin:0; color:var(--muted); font-size:13px; }
.row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; } .sp { flex:1; } .muted { color:var(--muted); }
h2 { font-size:19px; letter-spacing:-.025em; margin:0 0 14px; } h3 { font-size:15px; margin:22px 0 9px; } p { margin-top:0; }
.table-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:3px; } table { width:100%; border-collapse:collapse; min-width:680px; font-variant-numeric:tabular-nums; }
th,td { text-align:left; padding:12px 14px; border-bottom:1px solid var(--line); vertical-align:top; } tr:last-child td { border-bottom:0; }
th { background:#f7f9fc; font-weight:750; color:var(--muted); font-size:11px; letter-spacing:.07em; text-transform:uppercase; } tbody tr:hover { background:#f7faff; }
button,.btn { display:inline-flex; align-items:center; justify-content:center; gap:7px; font:inherit; font-weight:600; text-decoration:none; border:1px solid #b8c4d0; background:var(--panel); color:var(--ink); padding:9px 13px; min-height:44px; border-radius:3px; cursor:pointer; touch-action:manipulation; }
button:hover,.btn:hover { background:#edf3fc; text-decoration:none; } button.primary,.btn.primary { background:var(--accent); border-color:var(--accent); color:#fff; } button.primary:hover,.btn.primary:hover { background:#1747b4; }
button.danger { color:var(--bad); border-color:#edc9c9; } button.danger:hover { background:#fff2f1; } button:disabled { opacity:.55; cursor:default; }
input,select,textarea { font:inherit; padding:9px 11px; border:1px solid #b8c4d0; border-radius:3px; background:var(--panel); color:var(--ink); max-width:100%; min-height:44px; }
input[type="checkbox"] { min-height:auto; accent-color:var(--accent); } label { display:block; font-size:13px; font-weight:650; color:var(--ink); margin:12px 0 5px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px 18px; }
.grid input:not([type="checkbox"]),.grid select { width:100%; }
label textarea { font-weight:400; }
.badge { display:inline-block; padding:3px 8px; border-radius:3px; font-size:11px; font-weight:700; letter-spacing:.035em; border:1px solid currentColor; white-space:nowrap; }
.b-AWAKE,.b-SUCCEEDED { color:var(--ok); background:#e7f5ee; } .b-ASLEEP,.b-PREPARED { color:var(--sleep); background:#edf1f7; }
.b-CHANGING,.b-WAKING,.b-SLEEPING,.b-RUNNING,.b-ACCEPTED { color:var(--warn); background:#fff5e4; } .b-BLOCKED,.b-FAILED { color:var(--bad); background:#fff0ef; }
.b-REQUESTED,.b-MIXED,.b-ABSENT { color:var(--muted); background:#f2f4f7; }
.inst { display:inline-block; padding:2px 8px; border-radius:6px; margin:2px 4px 2px 0; font-size:12px; } .c-free { background:var(--free); } .c-stoppable { background:var(--stop); } .c-hourly_no_data { background:var(--hour); } .c-data { background:var(--data); }
.err { color:var(--bad); white-space:pre-wrap; } .alert { padding:13px 16px; border:1px solid #edc9c9; border-left:4px solid var(--bad); border-radius:8px; background:#fff7f6; margin:12px 0; } .alert p { margin:4px 0 0; }
.status-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin:16px 0; } .status-item { border:1px solid var(--line); border-radius:3px; padding:12px 14px; min-width:0; } .status-item small { display:block; color:var(--muted); font-weight:600; margin-bottom:4px; } .status-item strong { overflow-wrap:anywhere; }
.state-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); column-gap:28px; margin:16px 0; border-top:1px solid var(--line); } .state-grid .status-item { border:0; border-bottom:1px solid var(--line); border-radius:0; padding:13px 0; } .field-note { color:var(--muted); font-size:13px; margin:8px 0 0; overflow-wrap:anywhere; }
.operation-banner { display:flex; align-items:center; flex-wrap:wrap; gap:10px; padding:14px; border:0; border-left:3px solid #b38b48; border-radius:0; background:#faf7ef; } .operation-banner code { margin-left:auto; }
.resource-list { display:block; margin-top:14px; } .resource-item { display:flex; justify-content:space-between; gap:12px; border-top:1px solid var(--line); padding:11px 0; overflow-wrap:anywhere; }
.operation-list { list-style:none; padding:0; margin:12px 0 0; } .operation-list li { padding:14px 0; border-top:1px solid var(--line); overflow-wrap:anywhere; } .operation-list li:first-child { border-top:0; }
.admin-case { border-top:1px solid var(--line); padding:16px 0; } .admin-case:first-child { margin-top:16px; } .admin-case h3 { margin:0 0 8px; } .admin-case textarea { display:block; width:min(100%,620px); margin:6px 0 10px; }
.review-box { border:1px solid #e7cf9b; border-radius:9px; background:#fffaf0; padding:16px; margin:18px 0 0; } .review-box h3 { margin:0 0 8px; } .check-line { display:flex; align-items:flex-start; gap:8px; margin:14px 0; max-width:68ch; } .check-line input { margin-top:3px; flex:none; }
.review-box + .row { margin-top:16px; }
.environment-panel { padding:0; overflow:visible; background:transparent; border:0; } .environment-panel > .panel-head { padding:0 0 16px; margin:0; border-bottom:1px solid var(--line); }
.env-filters { padding:18px 0; gap:16px; background:transparent; border:0; }
.env-filters > div:first-child { flex:1 1 350px; } .env-filters > div:last-child { flex:0 1 220px; }
.env-filters label { margin:0 0 6px; } .env-filters input,.env-filters select { width:100%; }
.environment-panel #env-list { padding:0; } .environment-panel #env-list > .field-note { margin:12px 0; }
.environment-panel tr.attention-blocked td:first-child { box-shadow:inset 4px 0 var(--bad); } .environment-panel tr.attention-changing td:first-child { box-shadow:inset 4px 0 #b98b3b; }
.kpi { font-size:25px; font-weight:750; letter-spacing:-.035em; font-variant-numeric:tabular-nums; } .cost-note { color:var(--muted); font-size:13px; margin:14px 0 0; }
.empty { padding:30px 18px; text-align:center; color:var(--muted); } .empty strong { display:block; font-size:16px; color:var(--ink); }
.login-panel { max-width:430px; margin:8vh auto; } .login-panel input { width:100%; }
.login-panel #login-form > .row { margin:20px 0 0; }
.login-panel #msg { margin:16px 0 0; }
.sleep-page { max-width:620px; margin:0 auto; padding-top:min(12vh,100px); } .sleep-panel { padding:32px; } .sleep-steps { padding-left:24px; margin:18px 0; } .sleep-steps li { margin:8px 0; } .sleep-icon { display:none; }
code { font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace; background:var(--bg); padding:2px 5px; border-radius:4px; overflow-wrap:anywhere; }
@media(max-width:900px) {
  .app-header { position:static; width:auto; min-height:0; flex-direction:row; align-items:center; flex-wrap:wrap; gap:12px; padding:14px 16px 0; border-right:0; border-bottom:1px solid var(--line); }
  .brand { margin:0; }
  .primary-nav { order:3; flex-direction:row; align-items:stretch; gap:18px; width:100%; min-height:46px; margin:2px 0 0; overflow-x:auto; }
  .primary-nav a { flex:none; min-height:44px; padding:8px 0; border-left:0; border-bottom:2px solid transparent; }
  .primary-nav a:hover,.primary-nav a[aria-current="page"] { background:transparent; border-left-color:transparent; border-bottom-color:var(--accent); }
  .header-user { flex-direction:row; align-items:center; margin:0 0 0 auto; padding:0; border:0; }
  .header-user #who { display:none; }
  main { margin:0; padding:30px 16px 60px; }
  .status-grid { grid-template-columns:1fr; } .state-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
}
@media(max-width:520px) { .state-grid { grid-template-columns:1fr; } }
@media(max-width:520px) { .panel { padding:18px 16px; } .panel-head { flex-direction:column; } .page-intro.with-action { align-items:flex-start; flex-direction:column; } .environment-panel { padding:0; } .environment-panel > .panel-head { padding:0 0 14px; } .env-filters { padding:14px 0; } .env-filters > div { flex:1 1 100% !important; } .environment-panel #env-list { padding:0; } .sleep-panel { padding:24px 18px; } }
@media(max-width:640px) {
  .environment-table { overflow:visible; border:0; }
  .environment-table table,.environment-table tbody,.environment-table tr,.environment-table td { display:block; min-width:0; width:100%; }
  .environment-table tr:first-child { display:none; }
  .environment-table tr:not(:first-child) { border:0; border-bottom:1px solid var(--line); border-radius:0; margin:0; padding:12px 0; }
  .environment-panel tr.attention-blocked { border-left:3px solid var(--bad); padding-left:10px; }
  .environment-panel tr.attention-changing { border-left:3px solid #b98b3b; padding-left:10px; }
  .environment-panel tr.attention-blocked td:first-child,.environment-panel tr.attention-changing td:first-child { box-shadow:none; }
  .environment-table td { border:0; padding:7px 0; overflow-wrap:anywhere; }
  .environment-table td::before { content:attr(data-label); display:block; color:var(--muted); font-size:12px; font-weight:700; margin-bottom:3px; }
  .environment-table td.row { display:flex; flex-wrap:wrap; }
  .environment-table td.row::before { flex-basis:100%; }
}

```
