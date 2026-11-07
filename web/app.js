// InfraFlow management console. Talks to the InfraFlow API only, never to AWS directly.
(function () {
  "use strict";
  const cfg = window.INFRAFLOW || {};
  const view = document.getElementById("view");
  let pollTimer = null;

  // ---------------- session (Cognito USER_PASSWORD_AUTH) ----------------
  const store = {
    get(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* ignore */ } },
    clear() { try { sessionStorage.clear(); } catch (e) { /* ignore */ } },
  };

  async function cognito(target, body) {
    const r = await fetch(`https://cognito-idp.${cfg.region}.amazonaws.com/`, {
      method: "POST",
      headers: { "content-type": "application/x-amz-json-1.1", "x-amz-target": `AWSCognitoIdentityProviderService.${target}` },
      body: JSON.stringify(body),
    });
    const b = await r.json();
    if (!r.ok) throw new Error(b.message || b.__type || "Sign-in failed");
    return b;
  }

  function claims() {
    const t = store.get("idToken");
    if (!t) return null;
    try {
      const c = JSON.parse(atob(t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      if (c.exp * 1000 < Date.now()) return null;
      return c;
    } catch (e) { return null; }
  }

  // ---------------- API ----------------
  async function api(method, path, body) {
    const headers = { authorization: store.get("idToken") || "" };
    if (method !== "GET") {
      headers["content-type"] = "application/json";
      headers["idempotency-key"] = crypto.randomUUID();
    }
    const r = await fetch(cfg.apiUrl + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    if (r.status === 401) { store.clear(); route(); throw new Error("Session expired"); }
    const text = await r.text();
    const b = text ? JSON.parse(text) : null;
    if (!r.ok) throw new Error((b && b.error && `${b.error.code}: ${b.error.message}`) || r.statusText);
    return b;
  }

  // ---------------- helpers ----------------
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (iso) => (iso ? new Date(iso).toLocaleString("en-GB") : "-");
  const badge = (a) => {
    const k = String(a || "").split(":")[0];
    return `<span class="badge b-${esc(k)}">${esc(a || "-")}</span>`;
  };
  const CLASS = { network: "free", egress: "hourly_no_data", database: "data", app: "stoppable", entry: "hourly_no_data" };
  const insts = (m) => Object.entries(m || {}).map(([k, v]) => `<span class="inst c-${CLASS[k] || ""}">${esc(k)}: ${esc(v)}</span>`).join("");
  const toLocalInput = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  function fail(e) { view.insertAdjacentHTML("afterbegin", `<div class="panel err">${esc(e.message || e)}</div>`); }

  // ---------------- views ----------------
  function loginView() {
    view.innerHTML = `
      <div class="panel" style="max-width:380px;margin:8vh auto">
        <h2>Sign in</h2>
        <label>Email</label><input id="u" type="email" style="width:100%">
        <label>Password</label><input id="p" type="password" style="width:100%">
        <div id="np" hidden><label>New password (first sign-in)</label><input id="p2" type="password" style="width:100%"></div>
        <p class="row"><button class="primary" id="go">Sign in</button></p>
        <p id="msg" class="err"></p>
      </div>`;
    let session = null;
    document.getElementById("go").onclick = async () => {
      const u = document.getElementById("u").value.trim();
      const p = document.getElementById("p").value;
      try {
        let r;
        if (session) {
          r = await cognito("RespondToAuthChallenge", { ClientId: cfg.clientId, ChallengeName: "NEW_PASSWORD_REQUIRED", Session: session,
            ChallengeResponses: { USERNAME: u, NEW_PASSWORD: document.getElementById("p2").value } });
        } else {
          r = await cognito("InitiateAuth", { ClientId: cfg.clientId, AuthFlow: "USER_PASSWORD_AUTH", AuthParameters: { USERNAME: u, PASSWORD: p } });
        }
        if (r.ChallengeName === "NEW_PASSWORD_REQUIRED") {
          session = r.Session; document.getElementById("np").hidden = false;
          document.getElementById("msg").textContent = "Set a new password to continue.";
          return;
        }
        store.set("idToken", r.AuthenticationResult.IdToken);
        location.hash = "#/"; route();
      } catch (e) { document.getElementById("msg").textContent = e.message; }
    };
  }

  async function dashboard() {
    view.innerHTML = `<div class="panel"><div class="row"><h2 style="margin:0">Leases</h2><span class="sp" style="flex:1"></span>
      <a class="btn" href="#/new">New Lease</a></div><div id="list" class="muted">Loading...</div></div>`;
    try {
      const r = await api("GET", "/v1/leases");
      document.getElementById("list").innerHTML = r.items.length === 0
        ? `<p class="muted">No Leases yet.</p>`
        : `<table><tr><th>Name</th><th>Blueprint</th><th>Environments</th><th>Mode</th><th>Expires</th></tr>${r.items.map((l) => `
          <tr><td><a href="#/lease/${esc(l.lease_id)}">${esc(l.name)}</a></td><td>${esc(l.blueprint_ref)}</td>
          <td>${l.environments.map((e) => `${esc(e.name)} ${badge(e.availability)}`).join("<br>")}</td>
          <td>${esc(l.mode)}</td><td>${fmt(l.expires_at)}</td></tr>`).join("")}</table>`;
    } catch (e) { fail(e); }
  }

  async function createView() {
    const now = new Date(); const later = new Date(now.getTime() + 30 * 864e5);
    view.innerHTML = `<div class="panel"><h2>New Lease</h2>
      <div class="grid">
        <div><label>Lease name (lowercase letters and digits)</label><input id="name" placeholder="acme"></div>
        <div><label>Blueprint</label><select id="bp"></select></div>
        <div><label>Size</label><select id="size"><option>small</option><option>medium</option></select></div>
        <div><label>Environments (comma-separated)</label><input id="envs" value="dev,qa"></div>
        <div><label>Starts</label><input id="start" type="datetime-local" value="${toLocalInput(now)}"></div>
        <div><label>Expires</label><input id="end" type="datetime-local" value="${toLocalInput(later)}"></div>
      </div>
      <h3>Application (Docker image, linux/amd64)</h3>
      <div class="grid">
        <div><label>Image</label><input id="image" value="ghcr.io/kerafeng-cs/infraflow-demo-app:1" style="width:100%"></div>
        <div><label>Port</label><input id="port" type="number" value="8080"></div>
        <div><label>Health path</label><input id="health" value="/healthz"></div>
      </div>
      <h3>Activity policy</h3>
      <div class="grid">
        <div><label>Mode</label><select id="mode"><option value="schedule">Schedule</option><option value="on_demand">On demand</option></select></div>
        <div><label>Awake hours (UTC+7)</label><input id="from" value="08:00" size="5"> to <input id="to" value="19:00" size="5"></div>
        <div><label>Days (1 = Monday to 7 = Sunday)</label><input id="days" value="1,2,3,4,5"></div>
        <div><label>Sleep when idle after (minutes, empty = off)</label><input id="idle" type="number" placeholder="for example 90"></div>
      </div>
      <h3>Data at expiry</h3>
      <label><input type="checkbox" id="keep" checked> Keep a final backup (database snapshot)</label>
      <p class="row"><button class="primary" id="create">Create</button><span id="msg" class="err"></span></p></div>`;
    try {
      const c = await api("GET", "/v1/catalog/blueprints");
      document.getElementById("bp").innerHTML = c.items.map((b) => `<option value="${esc(b.ref)}">${esc(b.ref)}</option>`).join("");
    } catch (e) { fail(e); }
    document.getElementById("create").onclick = async () => {
      const v = (id) => document.getElementById(id).value;
      const idle = parseInt(v("idle"), 10);
      const policy = { mode: v("mode"), utc_offset_minutes: 420,
        schedule: { days: v("days").split(",").map((x) => parseInt(x, 10)).filter(Boolean), start: v("from"), end: v("to") } };
      if (idle) policy.idle_timeout_minutes = idle;
      const body = { name: v("name").trim(), blueprint_ref: v("bp"), parameters: { size: v("size") },
        environments: v("envs").split(",").map((x) => x.trim()).filter(Boolean),
        starts_at: new Date(v("start")).toISOString(), expires_at: new Date(v("end")).toISOString(),
        app: { image: v("image").trim(), port: parseInt(v("port"), 10), health_path: v("health") },
        activity_policy: policy, data_policy: { keep_final_backup: document.getElementById("keep").checked } };
      try { const r = await api("POST", "/v1/leases", body); location.hash = `#/lease/${r.lease_id}`; }
      catch (e) { document.getElementById("msg").textContent = e.message; }
    };
  }

  async function leaseView(id) {
    const draw = async () => {
      let l, cost = null;
      try { l = await api("GET", `/v1/leases/${id}`); } catch (e) { fail(e); return; }
      try { cost = await api("GET", `/v1/leases/${id}/cost`); } catch (e) { cost = null; }
      const p = l.activity_policy || {};
      view.innerHTML = `
        <div class="panel"><div class="row"><h2 style="margin:0">${esc(l.name)}</h2><span class="muted">${esc(l.blueprint_ref)}, ${esc((l.parameters || {}).size)}</span>
          <span style="flex:1"></span><button class="danger" id="reclaim">Reclaim now</button></div>
          <p class="muted">Valid ${fmt(l.starts_at)} to ${fmt(l.expires_at)}. Mode <b>${esc(p.mode)}</b>
          ${p.mode === "schedule" ? `${esc((p.schedule || {}).start)}-${esc((p.schedule || {}).end)}` : ""}
          ${p.idle_timeout_minutes ? `, sleeps after ${esc(p.idle_timeout_minutes)} idle minutes` : ""}
          . Image <code>${esc((l.app || {}).image)}</code></p>
          <div class="row"><label style="margin:0">Extend to</label><input type="datetime-local" id="ext">
            <button id="extend">Extend</button>
            <button id="switch">Switch to ${p.mode === "schedule" ? "on demand" : "schedule"}</button></div>
        </div>
        <div class="panel"><h2>Environments</h2><table>
          <tr><th>Name</th><th>State</th><th>URL</th><th>Instances</th><th></th></tr>
          ${l.environments.map((e) => `<tr>
            <td><b>${esc(e.name)}</b><br><span class="muted">${esc(e.environment_id)}</span></td>
            <td>${badge(e.availability)}<br><span class="muted">desired: ${esc(e.desired || "-")}</span>
              ${e.blocked_reason ? `<div class="err">${esc(e.blocked_reason.code)}: ${esc(String(e.blocked_reason.detail || "").slice(0, 200))}</div>` : ""}</td>
            <td><a href="${esc(e.url)}" target="_blank">open</a>${e.app_url ? `<br><a href="${esc(e.app_url)}" target="_blank" class="muted">application</a>` : ""}</td>
            <td>${insts(e.instances)}<br><span class="muted">observed ${fmt(e.observed_at)}</span></td>
            <td class="row"><button data-wake="${esc(e.environment_id)}">Wake now</button><button data-sleep="${esc(e.environment_id)}">Sleep</button>
              <button data-ops="${esc(e.environment_id)}">History</button></td></tr>`).join("")}
        </table><div id="ops"></div></div>
        ${cost ? `<div class="panel"><h2>Estimated cost <span class="muted" style="font-size:13px">(${fmt(cost.from)} to ${fmt(cost.to)}, USD)</span></h2>
          <div class="grid"><div><div class="muted">Always on</div><div class="kpi">${cost.totals.always_on.toFixed(2)}</div></div>
          <div><div class="muted">Scheduled EC2/RDS stop only</div><div class="kpi">${cost.totals.stop_only.toFixed(2)}</div></div>
          <div><div class="muted">InfraFlow (actual, from the transition log)</div><div class="kpi">${cost.totals.infraflow.toFixed(2)}</div></div></div></div>` : ""}`;
      bind(l);
    };
    const bind = (l) => {
      view.querySelectorAll("[data-wake]").forEach((b) => (b.onclick = () => act("POST", `/v1/environments/${b.dataset.wake}/wake`, {})));
      view.querySelectorAll("[data-sleep]").forEach((b) => (b.onclick = () => act("POST", `/v1/environments/${b.dataset.sleep}/sleep`, {})));
      view.querySelectorAll("[data-ops]").forEach((b) => (b.onclick = () => showOps(b.dataset.ops)));
      document.getElementById("reclaim").onclick = () => {
        if (confirm(`Reclaim the whole Lease ${l.name}? Its infrastructure will be deleted according to the selected data policy.`)) act("POST", `/v1/leases/${id}/reclaim`, { confirm: true });
      };
      document.getElementById("extend").onclick = () => {
        const v = document.getElementById("ext").value;
        if (v) act("POST", `/v1/leases/${id}/extend`, { expires_at: new Date(v).toISOString(), version: l.version });
      };
      document.getElementById("switch").onclick = () => {
        const p = Object.assign({}, l.activity_policy);
        if (p.mode === "schedule") { p.mode = "on_demand"; p.idle_timeout_minutes = p.idle_timeout_minutes || 90; } else { p.mode = "schedule"; }
        act("PUT", `/v1/leases/${id}/activity-policy`, { activity_policy: p, version: l.version });
      };
    };
    const act = async (m, path, body) => { try { await api(m, path, body); await draw(); } catch (e) { fail(e); } };
    const showOps = async (envId) => {
      try {
        const r = await api("GET", `/v1/environments/${envId}/operations`);
        document.getElementById("ops").innerHTML = `<h3>Operation history: ${esc(envId)}</h3><table>
          <tr><th>Time</th><th>Action</th><th>Source</th><th>Result</th><th>Plan</th></tr>
          ${r.items.map((o) => `<tr><td>${fmt(o.requested_at)}</td><td>${esc(o.action)} to ${esc(o.target_level || "")}</td><td>${esc(o.source)}</td>
            <td>${badge(o.status)}${o.error ? `<div class="err">${esc(o.error.code)}</div>` : ""}</td>
            <td>${o.plan ? o.plan.stages.map((s) => `<div><code>${esc(s.name)}</code> ${s.terraform ? esc(JSON.stringify(s.terraform)) : ""} ${esc(s.drivers.join(", "))}</div>`).join("") +
              (o.plan.model_check ? `<div class="muted">model check: ${o.plan.model_check.passed ? "pass" : "fail"}, ${o.plan.model_check.states_explored} states</div>` : "") : ""}</td></tr>`).join("")}</table>`;
      } catch (e) { fail(e); }
    };
    await draw();
    pollTimer = setInterval(draw, 10000);
  }

  const SAMPLE = {
    ics_version: "0.1",
    blueprint: { name: "web-db-custom", version: "1.0.0", owner: "org", summary: "Compose example" },
    parameters: { size: { type: "string", enum: ["small", "medium"], default: "small" } },
    instances: { network: { component: "aws-network-basic@1.0.0" }, egress: { component: "aws-nat-egress@1.0.0" },
      database: { component: "aws-rds-postgres@1.0.0", parameters: { size: "${param.size}" } },
      app: { component: "aws-ec2-docker-app@1.0.0", parameters: { size: "${param.size}" } },
      entry: { component: "aws-alb-https-entry@1.0.0" } },
    bindings: [{ from: "egress.net", to: "network.net" }, { from: "database.net", to: "network.net" }, { from: "app.net", to: "network.net" },
      { from: "app.egress", to: "egress.egress" }, { from: "app.db", to: "database.db" }, { from: "app.workload", to: "sys.lease_app" },
      { from: "entry.net", to: "network.net" }, { from: "entry.backend", to: "app.http" }, { from: "sys.dns", to: "entry.public" }],
    supported_levels: ["awake", "deep", "hibernate"],
  };

  function composeView() {
    view.innerHTML = `<div class="panel"><h2>Compose: check a Blueprint</h2>
      <p class="muted">Composition checks C1-C6 and model checking over every interleaving of every level transition plan. Try removing the <code>app.db</code> binding or adding the <code>shallow</code> level.</p>
      <textarea id="bp" rows="18" style="width:100%;font:12px ui-monospace,monospace">${esc(JSON.stringify(SAMPLE, null, 2))}</textarea>
      <p class="row"><button class="primary" id="check">Check</button></p><div id="out"></div></div>`;
    document.getElementById("check").onclick = async () => {
      try {
        const r = await api("POST", "/v1/blueprints/validate", JSON.parse(document.getElementById("bp").value));
        const rows = (r.composition || []).map((c) => `<tr><td>${esc(c.code)}</td><td class="err">${esc(c.message)}</td></tr>`)
          .concat((r.checks || []).map((c) => `<tr><td>${esc(c.code)}</td><td>${c.passed ? "pass" : `<span class="err">fail</span>`}, ${esc(c.name)}
            ${c.detail ? `<pre class="err">${esc(c.detail.rule)}: ${esc(c.detail.message)}\n${esc((c.detail.trace || []).join("\n"))}</pre>` : ""}</td></tr>`));
        document.getElementById("out").innerHTML = `<h3>${r.passed ? "PASS" : "FAIL"} ${r.states_explored ? `(${r.states_explored} states)` : ""}</h3><table>${rows.join("")}</table>`;
      } catch (e) { fail(e); }
    };
  }

  async function adminView() {
    view.innerHTML = `<div class="panel"><h2>Environment BLOCKED</h2><div id="blk">Loading...</div></div><div class="panel"><h2>Orphaned resources</h2><div id="orp"></div></div>`;
    try {
      const b = await api("GET", "/v1/admin/blocked");
      document.getElementById("blk").innerHTML = b.items.length ? `<table>${b.items.map((e) => `<tr><td>${esc(e.environment_id)}</td>
        <td class="err">${esc(e.blocked_reason && e.blocked_reason.code)}: ${esc(e.blocked_reason && String(e.blocked_reason.detail).slice(0, 300))}</td>
        <td><button data-r="${esc(e.environment_id)}">Unblock (retry)</button></td></tr>`).join("")}</table>` : `<p class="muted">None.</p>`;
      view.querySelectorAll("[data-r]").forEach((x) => (x.onclick = async () => {
        const note = prompt("Note: what was fixed?"); if (!note) return;
        try { await api("POST", `/v1/admin/environments/${x.dataset.r}/resolve`, { action: "retry", note }); adminView(); } catch (e) { fail(e); }
      }));
      const o = await api("GET", "/v1/admin/orphans");
      document.getElementById("orp").innerHTML = o.items.length ? `<table>${o.items.map((r) => `<tr><td><code>${esc(r.resource_arn)}</code></td><td>${esc(r.env_id_tag)}</td><td>${fmt(r.first_seen)}</td></tr>`).join("")}</table>` : `<p class="muted">None.</p>`;
    } catch (e) { fail(e); }
  }

  // ---------------- routing ----------------
  function route() {
    clearInterval(pollTimer);
    const c = claims();
    document.getElementById("who").textContent = c ? `${c.email || ""} (${c["custom:org_id"] || "org_default"})` : "";
    document.getElementById("logout").hidden = !c;
    if (!c) return loginView();
    const h = location.hash || "#/";
    let m;
    if (h === "#/new") return createView();
    if (h === "#/compose") return composeView();
    if (h === "#/admin") return adminView();
    if ((m = h.match(/^#\/lease\/(.+)$/))) return leaseView(m[1]);
    return dashboard();
  }
  document.getElementById("logout").onclick = () => { store.clear(); route(); };
  window.addEventListener("hashchange", route);
  route();
})();
