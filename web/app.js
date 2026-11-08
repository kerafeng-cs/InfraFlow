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

  // ---------------- views ----------------
  function loginView() {
    view.innerHTML = `
      <div class="panel login-panel">
        <h1 class="page-title">Sign in</h1>
        <p class="muted">Manage your staging environments and review each operation.</p>
        <form id="login-form">
        <label for="u">Email</label><input id="u" name="username" type="email" autocomplete="username" required spellcheck="false">
        <label for="p">Password</label><input id="p" name="password" type="password" autocomplete="current-password" required>
        <div id="np" hidden><label for="p2">New password (first sign-in)</label><input id="p2" name="new-password" type="password" autocomplete="new-password"></div>
        <p class="row"><button class="primary" id="go" type="submit">Sign in</button></p>
        </form>
        <p id="msg" class="err" role="alert"></p>
      </div>`;
    let session = null;
    document.getElementById("login-form").onsubmit = async (event) => {
      event.preventDefault();
      const submit = document.getElementById("go");
      submit.disabled = true;
      submit.textContent = "Signing in…";
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
          document.getElementById("p2").required = true;
          document.getElementById("p2").focus();
          document.getElementById("msg").textContent = "Set a new password to continue.";
          return;
        }
        store.set("idToken", r.AuthenticationResult.IdToken);
        location.hash = "#/"; route();
      } catch (e) { document.getElementById("msg").textContent = e.message; }
      finally { submit.disabled = false; submit.textContent = session ? "Set new password" : "Sign in"; }
    };
  }

  async function dashboard() {
    view.innerHTML = `<div class="page-intro"><p class="eyebrow">Operations workspace</p><h1 class="page-title">Leases</h1>
      <p class="page-summary">Find an environment, check its observed state, and follow work in progress.</p></div>
      <div class="panel"><div class="panel-head"><div><h2>Your Leases</h2><p class="panel-subtitle">Each Lease can contain multiple environments.</p></div>
      <a class="btn primary" href="#/new">Create Lease</a></div><div id="list" class="muted" role="status">Loading leases…</div></div>`;
    try {
      const r = await api("GET", "/v1/leases");
      document.getElementById("list").innerHTML = r.items.length === 0
        ? `<div class="empty"><strong>No Leases yet</strong><p>Create a Lease to set up your first environment.</p><a class="btn primary" href="#/new">Create Lease</a></div>`
        : `<div class="table-wrap"><table><tr><th>Name</th><th>Blueprint</th><th>Environments</th><th>Mode</th><th>Expires</th></tr>${r.items.map((l) => `
          <tr><td><a href="#/lease/${esc(l.lease_id)}">${esc(l.name)}</a></td><td>${esc(l.blueprint_ref)}</td>
          <td>${l.environments.map((e) => `<a href="#/environment/${encodeURIComponent(e.environment_id)}">${esc(e.name)}</a> ${badge(e.availability)}`).join("<br>")}</td>
          <td>${esc(l.mode)}</td><td>${fmt(l.expires_at)}</td></tr>`).join("")}</table></div>`;
    } catch (e) { fail(e); }
  }

  async function createView() {
    const now = new Date(); const later = new Date(now.getTime() + 30 * 864e5);
    view.innerHTML = `<div class="page-intro"><p class="eyebrow">Create</p><h1 class="page-title">New Lease</h1>
      <p class="page-summary">Define the environments, lifetime, and data policy before provisioning begins.</p></div><div class="panel"><h2>Lease details</h2><form id="create-form">
      <div class="grid">
        <div><label for="name">Lease name (lowercase letters and digits)</label><input id="name" placeholder="acme"></div>
        <div><label for="bp">Blueprint</label><select id="bp"></select></div>
        <div><label for="size">Size</label><select id="size"><option>small</option><option>medium</option></select></div>
        <div><label for="envs">Environments (comma-separated)</label><input id="envs" value="dev,qa"></div>
        <div><label for="start">Starts</label><input id="start" type="datetime-local" value="${toLocalInput(now)}"></div>
        <div><label for="end">Expires</label><input id="end" type="datetime-local" value="${toLocalInput(later)}"></div>
      </div>
      <h3>Application (Docker image, linux/amd64)</h3>
      <div class="grid">
        <div><label for="image">Image</label><input id="image" value="ghcr.io/kerafeng-cs/infraflow-demo-app:1" style="width:100%"></div>
        <div><label for="port">Port</label><input id="port" type="number" value="8080"></div>
        <div><label for="health">Health path</label><input id="health" value="/healthz"></div>
      </div>
      <h3>Activity policy</h3>
      <div class="grid">
        <div><label for="mode">Mode</label><select id="mode"><option value="schedule">Schedule</option><option value="on_demand">On demand</option></select></div>
        <div><label for="from">Awake from (UTC+7)</label><input id="from" value="08:00" size="5"><label for="to">Awake until (UTC+7)</label><input id="to" value="19:00" size="5"></div>
        <div><label for="days">Days (1 = Monday to 7 = Sunday)</label><input id="days" value="1,2,3,4,5"></div>
        <div><label for="idle">Sleep when idle after (minutes, empty = off)</label><input id="idle" type="number" placeholder="for example 90"></div>
      </div>
      <h3>Data at expiry</h3>
      <label><input type="checkbox" id="keep" checked> Keep a final backup (database snapshot)</label>
      <p class="row"><button class="primary" id="create" type="submit">Create Lease</button><span id="msg" class="err" role="alert"></span></p></form></div>`;
    try {
      const c = await api("GET", "/v1/catalog/blueprints");
      document.getElementById("bp").innerHTML = c.items.map((b) => `<option value="${esc(b.ref)}">${esc(b.ref)}</option>`).join("");
    } catch (e) { fail(e); }
    view.querySelectorAll("#create-form input, #create-form select").forEach((control) => { if (!control.name) control.name = control.id; });
    document.getElementById("create-form").onsubmit = async (event) => {
      event.preventDefault();
      const submit = document.getElementById("create");
      submit.disabled = true;
      submit.textContent = "Creating Lease…";
      const v = (id) => document.getElementById(id).value;
      try {
      const idle = parseInt(v("idle"), 10);
      const policy = { mode: v("mode"), utc_offset_minutes: 420,
        schedule: { days: v("days").split(",").map((x) => parseInt(x, 10)).filter(Boolean), start: v("from"), end: v("to") } };
      if (idle) policy.idle_timeout_minutes = idle;
      const body = { name: v("name").trim(), blueprint_ref: v("bp"), parameters: { size: v("size") },
        environments: v("envs").split(",").map((x) => x.trim()).filter(Boolean),
        starts_at: new Date(v("start")).toISOString(), expires_at: new Date(v("end")).toISOString(),
        app: { image: v("image").trim(), port: parseInt(v("port"), 10), health_path: v("health") },
        activity_policy: policy, data_policy: { keep_final_backup: document.getElementById("keep").checked } };
      const r = await api("POST", "/v1/leases", body); location.hash = `#/lease/${r.lease_id}`;
      }
      catch (e) { document.getElementById("msg").textContent = e.message; }
      finally { submit.disabled = false; submit.textContent = "Create Lease"; }
    };
  }

  async function leaseView(id) {
    const draw = async () => {
      let l, cost = null;
      try { l = await api("GET", `/v1/leases/${id}`); } catch (e) { fail(e); return; }
      try { cost = await api("GET", `/v1/leases/${id}/cost`); } catch (e) { cost = null; }
      const p = l.activity_policy || {};
      view.innerHTML = `
        <div class="page-intro"><p class="eyebrow"><a href="#/">Leases</a> / ${esc(l.name)}</p><h1 class="page-title">${esc(l.name)}</h1>
          <p class="page-summary">${esc(l.blueprint_ref)} · ${esc((l.parameters || {}).size)} · ${l.environments.length} environment${l.environments.length === 1 ? "" : "s"}</p></div>
        <div class="panel"><div class="panel-head"><div><h2>Lease settings</h2><p class="panel-subtitle">Schedule, expiry, and data policy apply to this Lease.</p></div></div>
          <p class="muted">Valid ${fmt(l.starts_at)} to ${fmt(l.expires_at)}. Mode <b>${esc(p.mode)}</b>
          ${p.mode === "schedule" ? `${esc((p.schedule || {}).start)}-${esc((p.schedule || {}).end)}` : ""}
          ${p.idle_timeout_minutes ? `, sleeps after ${esc(p.idle_timeout_minutes)} idle minutes` : ""}
          . Image <code>${esc((l.app || {}).image)}</code></p>
          <div class="row"><label for="ext">Extend to</label><input type="datetime-local" id="ext">
            <button id="extend">Extend</button>
            <button id="switch">Switch to ${p.mode === "schedule" ? "on demand" : "schedule"}</button></div>
        </div>
        <div class="panel"><div class="panel-head"><div><h2>Environments</h2><p class="panel-subtitle">Observed state and requested state are shown separately.</p></div></div><div class="table-wrap environment-table"><table>
          <tr><th>Name</th><th>Observed / desired</th><th>URL</th><th>Resources / last check</th><th>Actions</th></tr>
          ${l.environments.map((e) => `<tr>
            <td data-label="Environment"><a href="#/environment/${encodeURIComponent(e.environment_id)}"><b>${esc(e.name)}</b></a><br><code>${esc(e.environment_id)}</code></td>
            <td data-label="Observed / desired">${badge(e.availability)}<br><span class="muted">Desired: ${esc(e.desired || "Not set")}</span>
              ${e.blocked_reason ? `<div class="err">${esc(e.blocked_reason.code)}: ${esc(String(e.blocked_reason.detail || "").slice(0, 200))}</div>` : ""}</td>
            <td data-label="URL"><a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">Public URL</a>${e.app_url ? `<br><a href="${esc(e.app_url)}" target="_blank" rel="noopener noreferrer" class="muted">Application URL</a>` : ""}</td>
            <td data-label="Resources / last check">${insts(e.instances)}<br><span class="muted">Observed: ${fmt(e.observed_at)}</span></td>
            <td data-label="Actions" class="row"><button data-wake="${esc(e.environment_id)}" ${e.blocked_reason ? "disabled title=\"Blocked environment\"" : ""}>Wake</button><button data-sleep="${esc(e.environment_id)}" ${e.blocked_reason ? "disabled title=\"Blocked environment\"" : ""}>Sleep</button>
              <button data-ops="${esc(e.environment_id)}">History</button></td></tr>`).join("")}
        </table></div><div id="ops"></div></div>
        ${cost ? `<div class="panel"><h2>Estimated cost</h2><p class="panel-subtitle">${fmt(cost.from)} to ${fmt(cost.to)} · USD · unit-price estimate</p>
          <div class="grid"><div><div class="muted">Always on</div><div class="kpi">${number.format(cost.totals.always_on)}</div></div>
          <div><div class="muted">Scheduled EC2/RDS stop only</div><div class="kpi">${number.format(cost.totals.stop_only)}</div></div>
          <div><div class="muted">InfraFlow estimate from transition log</div><div class="kpi">${number.format(cost.totals.infraflow)}</div></div></div>
          <p class="cost-note">These are estimates, not AWS billed charges. Storage and other residual costs may continue while asleep.</p></div>` : ""}
        <div class="panel"><h2>Reclaim this Lease</h2><p class="muted">Reclaim can remove infrastructure for every environment in this Lease. Review your data policy and operation status first.</p><button class="danger" id="reclaim">Review reclaim</button></div>`;
      bind(l);
    };
    const bind = (l) => {
      view.querySelectorAll("[data-wake]").forEach((b) => (b.onclick = () => act("POST", `/v1/environments/${b.dataset.wake}/wake`, {})));
      view.querySelectorAll("[data-sleep]").forEach((b) => (b.onclick = () => act("POST", `/v1/environments/${b.dataset.sleep}/sleep`, {})));
      view.querySelectorAll("[data-ops]").forEach((b) => (b.onclick = () => showOps(b.dataset.ops)));
      document.getElementById("reclaim").onclick = () => {
        const names = l.environments.map((e) => e.name).join(", ");
        if (confirm(`Reclaim Lease ${l.name} and its environments (${names})? Infrastructure may be removed. Final database backup: ${(l.data_policy || {}).keep_final_backup ? "keep" : "do not keep"}. Confirm to submit the request; completion must be verified separately.`)) act("POST", `/v1/leases/${id}/reclaim`, { confirm: true });
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
    const act = async (m, path, body) => { try { await api(m, path, body); await draw(); view.insertAdjacentHTML("afterbegin", `<div class="panel" role="status">Request accepted. Follow the operation history and observed state for the verified outcome.</div>`); } catch (e) { fail(e); } };
    const showOps = async (envId) => {
      try {
        const r = await api("GET", `/v1/environments/${envId}/operations`);
        document.getElementById("ops").innerHTML = `<h3>Operation history: ${esc(envId)}</h3><div class="table-wrap"><table>
          <tr><th>Time</th><th>Action</th><th>Source</th><th>Result</th><th>Plan</th></tr>
          ${r.items.map((o) => `<tr><td>${fmt(o.requested_at)}</td><td>${esc(o.action)} to ${esc(o.target_level || "")}</td><td>${esc(o.source)}</td>
            <td>${badge(o.status)}${o.error ? `<div class="err">${esc(o.error.code)}</div>` : ""}</td>
            <td>${o.plan ? o.plan.stages.map((s) => `<div><code>${esc(s.name)}</code> ${s.terraform ? esc(JSON.stringify(s.terraform)) : ""} ${esc(s.drivers.join(", "))}</div>`).join("") +
              (o.plan.model_check ? `<div class="muted">model check: ${o.plan.model_check.passed ? "pass" : "fail"}, ${o.plan.model_check.states_explored} states</div>` : "") : ""}</td></tr>`).join("")}</table></div>`;
      } catch (e) { fail(e); }
    };
    await draw();
    pollTimer = setInterval(() => { if (document.visibilityState === "visible" && !view.contains(document.activeElement)) draw(); }, 10000);
  }

  async function environmentView(id) {
    const path = `/v1/environments/${encodeURIComponent(id)}`;
    const draw = async () => {
      let e, operations;
      try { [e, operations] = await Promise.all([api("GET", path), api("GET", `${path}/operations`)]); }
      catch (error) { view.innerHTML = ""; fail(error); return; }
      const items = operations.items || [];
      const active = items.find((o) => o.operation_id === e.active_operation_id);
      const blocked = Boolean(e.blocked || e.blocked_reason || e.availability === "BLOCKED");
      const terminal = e.status === "RECLAIMED";
      view.innerHTML = `
        <div class="page-intro"><p class="eyebrow"><a href="#/">Leases</a> / <a href="#/lease/${encodeURIComponent(e.lease_id)}">Lease</a> / Environment</p>
          <h1 class="page-title">${esc(e.name)}</h1><p class="page-summary">${esc(e.environment_id)} · Checked ${fmt(e.observed_at)}</p></div>
        ${blocked ? `<div class="alert" role="alert"><strong>Environment blocked</strong><p>${esc(e.blocked_reason && e.blocked_reason.code || "Investigation required")}: ${esc(e.blocked_reason && e.blocked_reason.detail || "Check the operation history and contact an administrator.")}</p></div>` : ""}
        <div class="panel"><div class="panel-head"><div><h2>Current state</h2><p class="panel-subtitle">Management, observation, and requested state can differ while work is running.</p></div><button id="refresh" type="button">Refresh status</button></div>
          <div class="state-grid">
            <div class="status-item"><small>Management</small>${badge(e.status)}<p class="field-note">Current lifecycle record</p></div>
            <div class="status-item"><small>Observed availability</small>${badge(e.availability)}<p class="field-note">Resources checked ${fmt(e.observed_at)}</p></div>
            <div class="status-item"><small>Observed level</small><strong>${esc(e.actual || "Unavailable")}</strong><p class="field-note">From last resource observation</p></div>
            <div class="status-item"><small>Desired level</small><strong>${esc(e.desired || "Not set")}</strong><p class="field-note">Source: ${esc(e.desired_source || "Unavailable")}</p></div>
          </div>
          ${active ? `<div class="operation-banner" role="status"><strong>Operation ${badge(active.status)}</strong><span>${esc(active.action || "Change")} ${active.target_level ? `→ ${esc(active.target_level)}` : ""} · Requested ${fmt(active.requested_at)}</span><code>${esc(active.operation_id)}</code></div>` : e.active_operation_id ? `<div class="operation-banner" role="status">Operation ${esc(e.active_operation_id)} is active. Refresh to check its outcome.</div>` : ""}
        </div>
        <div class="panel"><h2>Access and actions</h2><p class="panel-subtitle">A submitted action starts an operation. Check observed state and history for completion.</p>
          <p class="row"><a class="btn" href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">Open public URL</a>${e.app_url ? `<a class="btn" href="${esc(e.app_url)}" target="_blank" rel="noopener noreferrer">Open application</a>` : ""}</p>
          ${blocked || terminal ? `<p class="muted">${blocked ? "Actions are unavailable while this environment is blocked." : "This environment has been reclaimed."}</p>` : `<div class="row"><button id="wake" type="button" ${e.active_operation_id ? "disabled" : ""}>Wake environment</button><button id="sleep" type="button" ${e.active_operation_id ? "disabled" : ""}>Sleep environment</button></div>`}
          <div id="action-result" role="status" aria-live="polite"></div>
        </div>
        <div class="panel"><h2>Resources</h2><p class="panel-subtitle">Last observed state; it may lag behind a requested change.</p>
          <div class="resource-list">${Object.entries(e.instances || {}).length ? Object.entries(e.instances).map(([name, state]) => `<div class="resource-item"><strong>${esc(name)}</strong><span>${esc(state)}</span></div>`).join("") : `<p class="muted">No resource observation available.</p>`}</div>
          <p class="field-note">Last activity: ${fmt(e.last_activity_at)} · Awake since: ${fmt(e.awake_since)}</p></div>
        <div class="panel"><h2>Operation history</h2>${items.length ? `<ol class="operation-list">${items.map((o) => `<li><div class="row"><strong>${esc(o.action || "Change")} ${o.target_level ? `→ ${esc(o.target_level)}` : ""}</strong>${badge(o.status)}</div><p class="field-note">Requested ${fmt(o.requested_at)} · Started ${fmt(o.started_at)} · Finished ${fmt(o.finished_at)} · Source ${esc(o.source || "Unavailable")}</p>${o.error ? `<p class="err">${esc(o.error.code || "Operation error")}: ${esc(o.error.message || o.error.detail || "Review required")}</p>` : ""}<code>${esc(o.operation_id)}</code></li>`).join("")}</ol>` : `<p class="muted">No operations recorded for this environment.</p>`}</div>`;
      document.getElementById("refresh").onclick = draw;
      for (const action of ["wake", "sleep"]) {
        const button = document.getElementById(action);
        if (!button) continue;
        button.onclick = async () => {
          button.disabled = true;
          try {
            const result = await api("POST", `${path}/${action}`, {});
            document.getElementById("action-result").textContent = `Request accepted${result && result.operation_id ? `: operation ${result.operation_id}` : ""}. Refresh status to verify completion.`;
          } catch (error) { fail(error); button.disabled = false; }
        };
      }
    };
    await draw();
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
    view.innerHTML = `<div class="page-intro"><h1 class="page-title">Blueprint Check</h1><p class="page-summary">Check composition and lifecycle safety before using a blueprint.</p></div>
      <div class="panel"><h2>Blueprint definition</h2>
      <p class="muted">Checks C1–C6 and every level transition. Try removing the <code>app.db</code> binding or adding the <code>shallow</code> level.</p>
      <label for="bp">Blueprint JSON</label><textarea id="bp" name="blueprint" rows="18" style="width:100%;font:12px ui-monospace,monospace">${esc(JSON.stringify(SAMPLE, null, 2))}</textarea>
      <p class="row"><button class="primary" id="check">Check Blueprint</button></p><div id="out" role="status" aria-live="polite"></div></div>`;
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
    view.innerHTML = `<div class="page-intro"><h1 class="page-title">Admin Workbench</h1><p class="page-summary">Review blocked environments and resources that need investigation.</p></div>
      <div class="panel"><h2>Blocked Environments</h2><p class="panel-subtitle">Investigate the cause before requesting a retry. A retry request does not verify recovery.</p><div id="blk" role="status">Loading…</div></div><div class="panel"><h2>Orphaned Resources</h2><p class="panel-subtitle">Review resource ownership before any cleanup.</p><div id="orp" role="status">Loading…</div></div>`;
    try {
      const b = await api("GET", "/v1/admin/blocked");
      document.getElementById("blk").innerHTML = b.items.length ? b.items.map((e) => `<section class="admin-case"><h3><a href="#/environment/${encodeURIComponent(e.environment_id)}">${esc(e.name || e.environment_id)}</a></h3>
        <p class="err">${esc(e.blocked_reason && e.blocked_reason.code || "Blocked")}: ${esc(e.blocked_reason && String(e.blocked_reason.detail || "Investigation required").slice(0, 300))}</p>
        <p class="field-note">Last observed: ${fmt(e.observed_at)} · Environment ID: <code>${esc(e.environment_id)}</code></p>
        <form data-retry="${esc(e.environment_id)}"><label>What was fixed before retry?<textarea name="note" rows="2" required minlength="4" placeholder="Record the investigation and fix"></textarea></label><button type="submit">Request retry</button><p class="field-note" role="status" aria-live="polite"></p></form></section>`).join("") : `<p class="muted">No blocked environments.</p>`;
      view.querySelectorAll("[data-retry]").forEach((form) => (form.onsubmit = async (event) => {
        event.preventDefault();
        const button = form.querySelector("button");
        button.disabled = true;
        try {
          await api("POST", `/v1/admin/environments/${encodeURIComponent(form.dataset.retry)}/resolve`, { action: "retry", note: form.elements.note.value.trim() });
          form.querySelector('[role="status"]').textContent = "Retry requested. Open the environment to verify its outcome.";
        } catch (error) { form.querySelector('[role="status"]').textContent = `Request failed: ${error.message}`; button.disabled = false; }
      }));
      const o = await api("GET", "/v1/admin/orphans");
      document.getElementById("orp").innerHTML = o.items.length ? `<div class="table-wrap"><table><tr><th>Resource</th><th>Environment tag</th><th>First seen</th></tr>${o.items.map((r) => `<tr><td><code>${esc(r.resource_arn)}</code></td><td>${esc(r.env_id_tag)}</td><td>${fmt(r.first_seen)}</td></tr>`).join("")}</table></div>` : `<p class="muted">No orphaned resources recorded.</p>`;
    } catch (e) { fail(e); }
  }

  // ---------------- routing ----------------
  function route() {
    clearInterval(pollTimer);
    const c = claims();
    document.getElementById("who").textContent = c ? `${c.email || ""} (${c["custom:org_id"] || "org_default"})` : "";
    document.getElementById("logout").hidden = !c;
    document.querySelector(".primary-nav").hidden = !c;
    if (!c) { document.title = "Sign in · InfraFlow"; return loginView(); }
    const h = location.hash || "#/";
    document.querySelectorAll(".primary-nav a").forEach((a) => {
      const selected = h === a.getAttribute("href") || ((h.startsWith("#/lease/") || h.startsWith("#/environment/")) && a.getAttribute("href") === "#/");
      if (selected) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.title = h.startsWith("#/lease/") ? "Lease · InfraFlow" : h.startsWith("#/environment/") ? "Environment · InfraFlow" : `${h === "#/new" ? "Create Lease" : h === "#/admin" ? "Admin" : h === "#/compose" ? "Blueprint check" : "Leases"} · InfraFlow`;
    let m;
    if (h === "#/new") return createView();
    if (h === "#/compose") return composeView();
    if (h === "#/admin") return adminView();
    if ((m = h.match(/^#\/environment\/(.+)$/))) return environmentView(decodeURIComponent(m[1]));
    if ((m = h.match(/^#\/lease\/(.+)$/))) return leaseView(m[1]);
    return dashboard();
  }
  document.getElementById("logout").onclick = () => { store.clear(); route(); };
  window.addEventListener("hashchange", route);
  route();
})();
