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
  async function api(method, path, body, requestKey) {
    const headers = { authorization: store.get("idToken") || "" };
    if (method !== "GET") {
      headers["content-type"] = "application/json";
      headers["idempotency-key"] = requestKey || crypto.randomUUID();
    }
    const r = await fetch(cfg.apiUrl + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    if (r.status === 401) { store.clear(); setTimeout(route, 0); throw new Error("Session expired. Sign in again."); }
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
  const badge = (a, context = "") => {
    const k = String(a || "").split(":")[0];
    return `<span class="badge b-${esc(k)}${context ? ` b-${esc(context)}-${esc(k)}` : ""}">${esc(a || "-")}</span>`;
  };
  const icon = (name, extraClass = "button-icon") => `<svg class="${extraClass}" aria-hidden="true"><use href="#icon-${name}"/></svg>`;
  const brand = `<div class="login-brand"><span class="brand-mark">${icon("cube")}</span>InfraFlow</div>`;
  const CLASS = { network: "free", egress: "hourly_no_data", database: "data", app: "stoppable", entry: "hourly_no_data" };
  const insts = (m) => Object.entries(m || {}).map(([k, v]) => `<span class="inst c-${CLASS[k] || ""}">${esc(k)}: ${esc(v)}</span>`).join("");
  const toLocalInput = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  function fail(e) { view.insertAdjacentHTML("afterbegin", `<div class="alert" role="alert"><strong>Could not complete the request</strong><p>${esc(e.message || e)}</p></div>`); }

  // ---------------- views ----------------
  async function overviewView() {
    view.innerHTML = `<div class="page-intro with-action"><div><h1 class="page-title">Overview</h1>
      <p class="page-summary">Your Leases and Environments at a glance. Open a Lease to review its resources and operations.</p></div>
      <a class="btn primary" href="#/new">Create Lease</a></div>
      <div id="overview-content"><p role="status">Loading overview…</p></div>`;
    try {
      const leases = (await api("GET", "/v1/leases")).items || [];
      const environments = leases.flatMap((lease) => (lease.environments || []).map((env) => ({ ...env, lease })));
      const asleep = (state) => state === "SLEEPING" || String(state || "").startsWith("ASLEEP");
      const attention = environments.filter((env) => ["BLOCKED", "UNKNOWN"].includes(env.availability));
      const groups = [
        ["Awake", environments.filter((env) => env.availability === "AWAKE").length, "awake"],
        ["Sleeping", environments.filter((env) => asleep(env.availability)).length, "sleeping"],
        ["Changing", environments.filter((env) => env.availability === "CHANGING").length, "changing"],
        ["Needs attention", attention.length, "attention"],
      ];
      const other = environments.length - groups.reduce((sum, group) => sum + group[1], 0);
      if (other) groups.push(["Other states", other, "other"]);
      const metrics = [
        ["Total Leases", leases.length, "total", "list", "#/leases"],
        ["Environments", environments.length, "total", "cube", "#/environments"],
        ["Awake", groups[0][1], "awake", "check", "#/environments?state=AWAKE"],
        ["Needs attention", attention.length, "attention", "settings", "#/environments?state=ATTENTION"],
      ];
      const ordered = [...leases].sort((a, b) => {
        const count = (lease) => (lease.environments || []).filter((env) => ["BLOCKED", "UNKNOWN"].includes(env.availability)).length;
        return count(b) - count(a) || new Date(a.expires_at) - new Date(b.expires_at);
      });
      document.getElementById("overview-content").innerHTML = `<div class="summary-grid" aria-label="Deployment summary">${metrics.map(([label, value, type, symbol, href]) => `<a class="summary-card overview-metric ${type}" href="${href}" aria-label="${label}: ${value}. View details"><span class="summary-icon">${icon(symbol, "")}</span><small>${label}</small><strong>${value}</strong></a>`).join("")}</div>
        <div class="overview-panels">
          <section class="panel"><div class="panel-head"><div><h2>Environment status</h2><p class="panel-subtitle">Based on the current Lease list. Requested state is not a completed operation.</p></div></div>
            ${environments.length ? `<div class="status-distribution" role="img" aria-label="${groups.map(([label, value]) => `${label}: ${value}`).join(", ")}">${groups.filter(([, value]) => value).map(([, value, type]) => `<span class="distribution-${type}" style="flex:${value}"></span>`).join("")}</div><div class="status-legend">${groups.map(([label, value, type]) => `<span><i class="legend-dot distribution-${type}" aria-hidden="true"></i>${label}<strong>${value}</strong></span>`).join("")}</div>` : `<p class="muted">No Environments yet. Create a Lease to begin.</p>`}
            <a class="row-action" href="#/environments">View all Environments →</a></section>
          <section class="panel"><div class="panel-head"><div><h2>Needs attention</h2><p class="panel-subtitle">Blocked and unknown states from the Lease list.</p></div></div>
            ${attention.length ? `<ul class="attention-list">${attention.slice(0, 4).map((env) => `<li><div><strong>${esc(env.name)}</strong><span>${esc(env.lease.name)}</span></div>${badge(env.availability)}<a class="row-action" href="#/lease/${encodeURIComponent(env.lease.lease_id)}">Open Lease</a></li>`).join("")}</ul>${attention.length > 4 ? `<p class="field-note">Showing 4 of ${attention.length}. Open Environments for the full list.</p>` : ""}` : `<div class="overview-clear"><span class="clear-icon">${icon("check", "")}</span><strong>No blocked or unknown Environments</strong><p>Other states may still need time to finish. Check each Environment for its observed result.</p></div>`}
          </section>
        </div>
        <section class="panel overview-deployments"><div class="panel-head"><div><h2>Your deployments</h2><p class="panel-subtitle">Each deployment is a Lease. Attention first, then by expiry.</p></div><a class="row-action" href="#/leases">View all Leases →</a></div>
          ${ordered.length ? `<div class="table-wrap environment-table"><table><thead><tr><th>Lease</th><th>Blueprint</th><th>Environments</th><th>Mode</th><th>Expires</th><th>Action</th></tr></thead><tbody>${ordered.slice(0, 6).map((lease) => `<tr><td data-label="Lease"><a class="table-name" href="#/lease/${encodeURIComponent(lease.lease_id)}">${esc(lease.name)}</a></td><td data-label="Blueprint">${esc(lease.blueprint_ref)}</td><td data-label="Environments"><div class="overview-environments">${(lease.environments || []).map((env) => `<span><strong>${esc(env.name)}</strong>${badge(env.availability)}</span>`).join("") || `<span class="muted">None</span>`}</div></td><td data-label="Mode">${esc(lease.mode || "Not set")}</td><td data-label="Expires">${fmt(lease.expires_at)}</td><td data-label="Action"><a class="row-action" href="#/lease/${encodeURIComponent(lease.lease_id)}">Open Lease →</a></td></tr>`).join("")}</tbody></table></div>${ordered.length > 6 ? `<p class="field-note">Showing 6 of ${ordered.length} Leases.</p>` : ""}` : `<div class="empty"><strong>No Leases yet</strong><p>Create a Lease to set up your first Environment.</p><a class="btn primary" href="#/new">Create Lease</a></div>`}
        </section>`;
    } catch (error) { document.getElementById("overview-content").innerHTML = ""; fail(error); }
  }

  async function environmentsView() {
    view.innerHTML = `<div class="page-intro with-action"><div><p class="eyebrow">Operations workspace</p><h1 class="page-title">Environments</h1>
      <p class="page-summary">Find environments that need attention, check the last observation, and open details before changing state.</p></div><a class="btn primary" href="#/new">Create Lease</a></div>
      <div id="env-summary" class="summary-grid" aria-label="Environment summary"></div><p id="env-summary-note" class="summary-note" hidden></p>
      <div class="panel environment-panel"><div class="panel-head"><div><h2>Your Environments</h2><p class="panel-subtitle">Blocked and unknown states appear first.</p></div></div>
        <div id="env-filters" class="row env-filters" hidden><div><label for="env-search">Search Environment or Lease</label><div class="search-control">${icon("search", "search-icon")}<input id="env-search" name="search" type="search" autocomplete="off" placeholder="Search by name…"></div></div>
          <div><label for="env-filter">Observed state</label><select id="env-filter" name="state"><option value="">All states</option><option value="ATTENTION">Needs attention</option><option value="BLOCKED">Blocked</option><option value="UNKNOWN">Unknown</option><option value="CHANGING">Changing</option><option value="AWAKE">Awake</option><option value="SLEEPING">Sleeping</option></select></div></div>
        <div id="env-list" role="status">Loading Environments…</div></div>`;
    const renderSummary = (rows, failures = 0) => {
      const count = (predicate) => rows.filter(predicate).length;
      const cards = [
        ["Total Environments", rows.length, "total", "grid"],
        ["Awake", count((e) => e.availability === "AWAKE"), "awake", "check"],
        ["Sleeping", count((e) => e.availability === "SLEEPING" || String(e.availability || "").startsWith("ASLEEP")), "sleeping", "cube"],
        ["Needs Attention / Blocked", count((e) => ["BLOCKED", "UNKNOWN"].includes(e.availability)), "attention", "settings"],
      ];
      document.getElementById("env-summary").innerHTML = cards.map(([label, value, type, symbol]) => `<div class="summary-card ${type}"><span class="summary-icon">${icon(symbol, "")}</span><small>${label}</small><strong>${value}</strong></div>`).join("");
      if (failures) { const note = document.getElementById("env-summary-note"); note.hidden = false; note.textContent = `Counts include loaded Environments only. ${failures} Lease${failures === 1 ? "" : "s"} could not be loaded.`; }
    };
    try {
      const leases = (await api("GET", "/v1/leases")).items || [];
      if (!leases.length) { renderSummary([]); document.getElementById("env-list").innerHTML = `<div class="empty"><strong>No Environments yet</strong><p>Create a Lease to set up your first Environment.</p><a class="btn primary" href="#/new">Create Lease</a></div>`; return; }
      const results = await Promise.allSettled(leases.map((lease) => api("GET", `/v1/leases/${encodeURIComponent(lease.lease_id)}`)));
      const rows = results.flatMap((result) => result.status === "fulfilled" ? result.value.environments.map((env) => ({ ...env, lease: result.value })) : []);
      const failures = results.filter((result) => result.status === "rejected").length;
      renderSummary(rows, failures);
      const priority = (e) => e.availability === "BLOCKED" ? 0 : e.availability === "UNKNOWN" || !e.observed_at ? 1 : e.active_operation_id ? 2 : 3;
      rows.sort((a, b) => priority(a) - priority(b) || new Date(a.lease.expires_at) - new Date(b.lease.expires_at) || a.name.localeCompare(b.name));
      const container = document.getElementById("env-list");
      if (failures) container.insertAdjacentHTML("beforebegin", `<div class="alert" role="alert">Could not load ${failures} Lease${failures === 1 ? "" : "s"}. Refresh the page to see the full list.</div>`);
      if (!rows.length) { container.innerHTML = `<p class="muted">No Environments could be loaded. Refresh the page or open a Lease directly.</p>`; return; }
      document.getElementById("env-filters").hidden = false;
      const params = new URLSearchParams((location.hash.split("?")[1] || ""));
      document.getElementById("env-search").value = params.get("search") || "";
      if ([...document.getElementById("env-filter").options].some((option) => option.value === params.get("state"))) document.getElementById("env-filter").value = params.get("state") || "";
      const render = () => {
        const search = document.getElementById("env-search").value.trim().toLowerCase();
        const state = document.getElementById("env-filter").value;
        const nextParams = new URLSearchParams();
        if (search) nextParams.set("search", search);
        if (state) nextParams.set("state", state);
        history.replaceState(null, "", `${location.pathname}${location.search}#/environments${nextParams.size ? `?${nextParams}` : ""}`);
        const filtered = rows.filter((e) => (!search || `${e.name} ${e.environment_id} ${e.lease.name}`.toLowerCase().includes(search)) && (!state || (state === "ATTENTION" ? ["BLOCKED", "UNKNOWN"].includes(e.availability) : state === "SLEEPING" ? e.availability === "SLEEPING" || String(e.availability || "").startsWith("ASLEEP") : e.availability === state)));
        container.innerHTML = filtered.length ? `<p class="field-note">${filtered.length} of ${rows.length} Environments</p><div class="table-wrap environment-table"><table>
          <tr><th>Environment</th><th>Lease</th><th>Observed / desired</th><th>Operation</th><th>Last check</th><th>Action</th></tr>${filtered.map((e) => `<tr class="${e.availability === "BLOCKED" ? "attention-blocked" : e.active_operation_id ? "attention-changing" : ""}">
            <td data-label="Environment"><a class="table-name" href="#/environment/${encodeURIComponent(e.environment_id)}">${esc(e.name)}</a><br><code>${esc(e.environment_id)}</code></td>
            <td data-label="Lease"><a class="table-name" href="#/lease/${encodeURIComponent(e.lease.lease_id)}">${esc(e.lease.name)}</a><br><span class="field-note">Expires ${fmt(e.lease.expires_at)}</span></td>
            <td data-label="Observed / desired">${badge(e.availability)}<br><span class="field-note">Desired: ${esc(e.desired || "Not set")}</span></td>
            <td data-label="Operation">${e.active_operation_id ? `<code>${esc(e.active_operation_id)}</code>` : `<span class="muted">None running</span>`}</td>
            <td data-label="Last check">${fmt(e.observed_at)}</td><td data-label="Action"><a class="row-action" href="#/environment/${encodeURIComponent(e.environment_id)}">View details →</a></td></tr>`).join("")}</table></div><p class="field-note">Observation time comes from the last resource check. Desired state is not proof of completion.</p>` : `<div class="empty"><strong>No matching Environments</strong><p>Try a different name or state.</p></div>`;
      };
      document.getElementById("env-search").oninput = render;
      document.getElementById("env-filter").onchange = render;
      render();
    } catch (error) { document.getElementById("env-list").innerHTML = ""; fail(error); }
  }

  function loginView() {
    if (!cfg.apiUrl || !cfg.region || !cfg.clientId) {
      document.title = "Connection unavailable · InfraFlow";
      view.innerHTML = `${brand}<div class="panel login-panel" role="status">
        <h1 class="page-title">Console unavailable</h1>
        <p class="muted">This preview is not connected to an InfraFlow environment. Open the deployed console URL to sign in.</p>
      </div>`;
      return;
    }
    view.innerHTML = `${brand}
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
          <tr><td><a class="table-name" href="#/lease/${esc(l.lease_id)}">${esc(l.name)}</a></td><td>${esc(l.blueprint_ref)}</td>
          <td>${l.environments.map((e) => `${esc(e.name)} ${badge(e.availability)}`).join("<br>")}</td>
          <td>${esc(l.mode)}</td><td>${fmt(l.expires_at)}</td></tr>`).join("")}</table></div>`;
    } catch (e) { fail(e); }
  }

  async function createView() {
    const now = new Date(); const later = new Date(now.getTime() + 30 * 864e5);
    view.innerHTML = `<div class="page-intro"><p class="eyebrow">Create</p><h1 class="page-title">New Lease</h1>
      <p class="page-summary">Define the environments, lifetime, and data policy before provisioning begins.</p></div><div class="panel create-panel"><h2>Lease details</h2><form id="create-form">
      <section class="form-section"><h3>General &amp; Blueprint</h3><div class="form-grid">
        <div class="span-full"><label for="name">Lease name (2–16 lowercase letters or digits)</label><input id="name" placeholder="acme" required pattern="[a-z][a-z0-9]{1,15}" autocomplete="off"></div>
        <div><label for="bp">Blueprint</label><select id="bp"></select></div>
        <div><label for="size">Size</label><select id="size"><option>small</option><option>medium</option></select></div>
        <div class="span-full"><label for="envs">Environments (1–5 distinct names, up to 8 letters or digits each)</label><input id="envs" value="dev,qa" required autocomplete="off" aria-describedby="msg"></div>
      </div></section>
      <section class="form-section"><h3>Lifecycle Window</h3><div class="form-grid lifecycle-grid">
        <div><label for="start">Starts</label><input id="start" type="datetime-local" value="${toLocalInput(now)}" required></div>
        <div><label for="end">Expires</label><input id="end" type="datetime-local" value="${toLocalInput(later)}" required aria-describedby="msg"></div>
      </div></section>
      <section class="form-section"><h3>Application Workload</h3><p class="panel-subtitle">Docker image, linux/amd64</p><div class="form-grid">
        <div class="span-full"><label for="image">Image</label><input id="image" value="ghcr.io/kerafeng-cs/infraflow-demo-app:1"></div>
        <div><label for="port">Port</label><input id="port" type="number" min="1" max="65535" value="8080" required></div>
        <div><label for="health">Health path</label><input id="health" value="/healthz" required pattern="/.*"></div>
      </div></section>
      <section class="form-section"><h3>Activity policy</h3><div class="form-grid">
        <div><label for="mode">Mode</label><select id="mode"><option value="schedule">Schedule</option><option value="on_demand">On demand</option></select></div>
        <div><label for="idle" id="idle-label">Sleep when idle after (minutes; optional)</label><input id="idle" type="number" min="1" placeholder="For example, 90…" aria-describedby="msg"></div>
      </div>
      <div id="schedule-fields" class="activity-schedule"><div class="form-grid">
        <div><label for="from">Awake from (UTC+7)</label><input id="from" type="time" value="08:00"></div>
        <div><label for="to">Awake until (UTC+7)</label><input id="to" type="time" value="19:00" aria-describedby="msg"></div>
        <div class="span-full"><span id="days-label" class="field-label">Awake days (1 = Monday to 7 = Sunday)</span><input id="days" type="hidden" value="1,2,3,4,5"><div id="day-pills" class="day-selector" role="group" aria-labelledby="days-label" aria-describedby="msg" tabindex="-1">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((day, index) => `<button type="button" data-day="${index + 1}" aria-label="${["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][index]}" aria-pressed="${index < 5}">${day}</button>`).join("")}</div></div>
      </div></div></section>
      <section class="form-section"><h3>Data at expiry</h3><label class="check-line"><input type="checkbox" id="keep" checked> Keep a final backup (database snapshot)</label></section>
      <div id="create-review" class="review-box" hidden></div>
      <button class="primary create-submit" id="create" type="submit">Review Lease</button><p id="msg" class="err" role="alert" tabindex="-1"></p></form></div>`;
    try {
      const c = await api("GET", "/v1/catalog/blueprints");
      document.getElementById("bp").innerHTML = c.items.map((b) => `<option value="${esc(b.ref)}">${esc(b.ref)}</option>`).join("");
      if (!c.items.length) { document.getElementById("create").disabled = true; document.getElementById("msg").textContent = "No certified blueprints are available. Ask an administrator to check the catalog."; }
    } catch (e) { document.getElementById("create").disabled = true; fail(e); }
    view.querySelectorAll("#create-form input, #create-form select").forEach((control) => { if (!control.name) control.name = control.id; });
    const form = document.getElementById("create-form");
    const syncMode = () => {
      const onDemand = document.getElementById("mode").value === "on_demand";
      document.getElementById("schedule-fields").hidden = onDemand;
      document.getElementById("idle").required = onDemand;
      document.getElementById("idle-label").textContent = `Sleep when idle after (minutes; ${onDemand ? "required" : "optional"})`;
    };
    document.getElementById("mode").addEventListener("change", syncMode);
    syncMode();
    document.querySelectorAll("#day-pills button").forEach((button) => { button.onclick = () => {
      button.setAttribute("aria-pressed", String(button.getAttribute("aria-pressed") !== "true"));
      const days = [...document.querySelectorAll("#day-pills button[aria-pressed='true']")].map((selected) => selected.dataset.day);
      const field = document.getElementById("days"); field.value = days.join(","); field.dispatchEvent(new Event("input", { bubbles: true }));
    }; });
    let reviewed = false; let createKey = null;
    form.addEventListener("input", () => { reviewed = false; createKey = null; document.getElementById("create-review").hidden = true; document.getElementById("create").textContent = "Review Lease"; document.getElementById("msg").textContent = ""; });
    document.getElementById("create-form").onsubmit = async (event) => {
      event.preventDefault();
      const submit = document.getElementById("create");
      const v = (id) => document.getElementById(id).value;
      let invalidField = null;
      try {
      const names = v("envs").split(",").map((x) => x.trim());
      if (names.length > 5 || names.some((x) => !/^[a-z][a-z0-9]{0,7}$/.test(x)) || new Set(names).size !== names.length) { invalidField = "envs"; throw new Error("Enter 1–5 different environment names, each up to 8 lowercase letters or digits."); }
      const start = new Date(v("start")); const end = new Date(v("end"));
      if (start >= end || end - start > 120 * 864e5) { invalidField = "end"; throw new Error("Expiry must be after the start and within 120 days."); }
      const idle = v("idle") ? parseInt(v("idle"), 10) : null;
      if (v("mode") === "on_demand" && !idle) { invalidField = "idle"; throw new Error("On demand mode requires an idle sleep time in minutes."); }
      const policy = { mode: v("mode"), utc_offset_minutes: 420 };
      if (policy.mode === "schedule") {
        const days = v("days").split(",").map((x) => x.trim());
        if (days.length > 7 || days.some((x) => !/^[1-7]$/.test(x)) || new Set(days).size !== days.length) { invalidField = "day-pills"; throw new Error("Select at least one awake day."); }
        if (v("from") >= v("to")) { invalidField = "to"; throw new Error("The scheduled awake end time must be after the start time."); }
        policy.schedule = { days: days.map(Number), start: v("from"), end: v("to") };
      }
      if (idle) policy.idle_timeout_minutes = idle;
      const body = { name: v("name").trim(), blueprint_ref: v("bp"), parameters: { size: v("size") },
        environments: names,
        starts_at: start.toISOString(), expires_at: end.toISOString(),
        app: { image: v("image").trim(), port: parseInt(v("port"), 10), health_path: v("health") },
        activity_policy: policy, data_policy: { keep_final_backup: document.getElementById("keep").checked } };
      document.getElementById("msg").textContent = "";
      if (!reviewed) {
        const review = document.getElementById("create-review");
        const receipt = [
          ["Lease", body.name], ["Blueprint", body.blueprint_ref], ["Size", body.parameters.size], ["Environments", names.join(", ")],
          ["Starts", fmt(body.starts_at)], ["Expires", fmt(body.expires_at)], ["Mode", policy.mode === "schedule" ? "Schedule" : "On demand"],
          ...(policy.mode === "schedule" ? [["Awake window", `${policy.schedule.start}–${policy.schedule.end} (UTC+7)`], ["Awake days", policy.schedule.days.map((day) => ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day - 1]).join(", ")]] : []),
          ["Idle sleep", policy.idle_timeout_minutes ? `${policy.idle_timeout_minutes} minutes` : "Off"], ["Final backup", body.data_policy.keep_final_backup ? "Keep" : "Do not keep"],
          ["Image", body.app.image, true], ["Port", body.app.port, true], ["Health path", body.app.health_path, true],
        ];
        review.innerHTML = `<h3 tabindex="-1">Review Before Creating</h3><dl class="review-grid">${receipt.map(([label, value, code]) => `<div><dt>${esc(label)}</dt><dd>${code ? `<code>${esc(value)}</code>` : esc(value)}</dd></div>`).join("")}</dl><p class="muted">Submitting creates the Lease and starts provisioning operations. Check their outcomes on each Environment.</p>`;
        review.hidden = false; reviewed = true; createKey = crypto.randomUUID(); submit.textContent = "Create Lease and Start Provisioning"; review.scrollIntoView({ block: "nearest" }); review.querySelector("h3").focus({ preventScroll: true }); return;
      }
      submit.disabled = true; submit.textContent = "Submitting Request…";
      const r = await api("POST", "/v1/leases", body, createKey); location.hash = `#/lease/${encodeURIComponent(r.lease_id)}`;
      }
      catch (e) { const message = document.getElementById("msg"); message.textContent = e.message; (invalidField ? document.getElementById(invalidField) : message).focus(); }
      finally { submit.disabled = false; submit.textContent = reviewed ? "Create Lease and Start Provisioning" : "Review Lease"; }
    };
  }

  async function leaseView(id) {
    const draw = async () => {
      let l, cost = null;
      try { l = await api("GET", `/v1/leases/${id}`); } catch (e) { fail(e); return; }
      try { cost = await api("GET", `/v1/leases/${id}/cost`); } catch (e) { cost = null; }
      const p = l.activity_policy || {};
      view.innerHTML = `
        <div class="page-intro"><p class="eyebrow"><a href="#/leases">Leases</a> / ${esc(l.name)}</p><h1 class="page-title">${esc(l.name)}</h1>
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
            <td data-label="Environment"><a class="table-name" href="#/environment/${encodeURIComponent(e.environment_id)}">${esc(e.name)}</a><br><code>${esc(e.environment_id)}</code></td>
            <td data-label="Observed / desired">${badge(e.availability)}<br><span class="muted">Desired: ${esc(e.desired || "Not set")}</span>
              ${e.blocked_reason ? `<div class="err">${esc(e.blocked_reason.code)}: ${esc(String(e.blocked_reason.detail || "").slice(0, 200))}</div>` : ""}</td>
            <td data-label="URL"><a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">Public URL</a>${e.app_url ? `<br><a href="${esc(e.app_url)}" target="_blank" rel="noopener noreferrer" class="muted">Application URL</a>` : ""}</td>
            <td data-label="Resources / last check">${insts(e.instances)}<br><span class="muted">Observed: ${fmt(e.observed_at)}</span></td>
            <td data-label="Actions"><a class="btn" href="#/environment/${encodeURIComponent(e.environment_id)}">View details</a></td></tr>`).join("")}
        </table></div></div>
        ${cost ? `<div class="panel"><h2>Estimated cost</h2><p class="panel-subtitle">${fmt(cost.from)} to ${fmt(cost.to)} · USD · unit-price estimate</p>
          <div class="grid"><div><div class="muted">Always on</div><div class="kpi">${number.format(cost.totals.always_on)}</div></div>
          <div><div class="muted">Scheduled EC2/RDS stop only</div><div class="kpi">${number.format(cost.totals.stop_only)}</div></div>
          <div><div class="muted">InfraFlow estimate from transition log</div><div class="kpi">${number.format(cost.totals.infraflow)}</div></div></div>
          <p class="cost-note">These are estimates, not AWS billed charges. Storage and other residual costs may continue while asleep.</p></div>` : ""}
        <div class="panel"><h2>Reclaim this Lease</h2><p class="muted">Reclaim can remove infrastructure for every environment in this Lease. Review your data policy and operation status first.</p><button class="danger" id="reclaim" type="button">Review reclaim</button>
          <div id="reclaim-review" class="review-box" hidden><h3>Review Reclaim Request</h3><p>Environments: ${l.environments.map((e) => esc(e.name)).join(", ")}. Final database backup: ${(l.data_policy || {}).keep_final_backup ? "keep" : "do not keep"}.</p>
            <p class="muted">The current API does not provide a verified exclusive/retained/shared resource inventory or backup result before this request. Check each Environment and your data policy.</p>
            <label class="check-line"><input id="reclaim-ack" type="checkbox"> I understand this request can remove infrastructure for every Environment in this Lease.</label>
            <div class="row"><button class="danger" id="reclaim-submit" type="button" disabled>Submit Reclaim Request</button><button id="reclaim-cancel" type="button">Cancel</button></div></div></div>`;
      bind(l);
    };
    const bind = (l) => {
      document.getElementById("reclaim").onclick = () => { document.getElementById("reclaim-review").hidden = false; document.getElementById("reclaim-ack").focus(); };
      document.getElementById("reclaim-ack").onchange = (event) => { document.getElementById("reclaim-submit").disabled = !event.target.checked; };
      document.getElementById("reclaim-cancel").onclick = () => { document.getElementById("reclaim-review").hidden = true; document.getElementById("reclaim-ack").checked = false; document.getElementById("reclaim-submit").disabled = true; document.getElementById("reclaim").focus(); };
      document.getElementById("reclaim-submit").onclick = async () => { document.getElementById("reclaim-submit").disabled = true; await act("POST", `/v1/leases/${id}/reclaim`, { confirm: true }); };
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
        <div class="page-intro"><p class="eyebrow"><a href="#/environments">Environments</a> / <a href="#/lease/${encodeURIComponent(e.lease_id)}">Lease</a> / Environment</p>
          <h1 class="page-title">${esc(e.name)}</h1><p class="page-summary">${esc(e.environment_id)} · Checked ${fmt(e.observed_at)}</p></div>
        ${blocked ? `<div class="alert" role="alert"><strong>Environment blocked</strong><p>${esc(e.blocked_reason && e.blocked_reason.code || "Investigation required")}: ${esc(e.blocked_reason && e.blocked_reason.detail || "Check the operation history and contact an administrator.")}</p></div>` : ""}
        <div class="panel"><div class="panel-head state-panel-head"><h2>Current state</h2><button id="refresh" type="button" aria-label="Refresh status">${icon("refresh")}<span class="refresh-label">Refresh status</span></button></div><p class="panel-subtitle">Management, observation, and requested state can differ while work is running.</p>
          <div class="state-grid">
            <div class="status-item"><small>Management</small>${badge(e.status)}<p class="field-note">Current lifecycle record</p></div>
            <div class="status-item"><small>Observed availability</small>${badge(e.availability)}<p class="field-note">Resources checked ${fmt(e.observed_at)}</p></div>
            <div class="status-item"><small>Observed level</small><strong>${esc(e.actual || "Unavailable")}</strong><p class="field-note">From last resource observation</p></div>
            <div class="status-item"><small>Desired level</small><strong>${esc(e.desired || "Not set")}</strong><p class="field-note">Source: ${esc(e.desired_source || "Unavailable")}</p></div>
          </div>
          ${active ? `<div class="operation-banner" role="status"><strong>Operation ${badge(active.status, "operation")}</strong><span>${esc(active.action || "Change")} ${active.target_level ? `→ ${esc(active.target_level)}` : ""} · Requested ${fmt(active.requested_at)}</span><code>${esc(active.operation_id)}</code></div>` : e.active_operation_id ? `<div class="operation-banner" role="status">Operation ${esc(e.active_operation_id)} is active. Refresh to check its outcome.</div>` : ""}
        </div>
        <div class="panel"><h2>Access and actions</h2><p class="panel-subtitle">A submitted action starts an operation. Check observed state and history for completion.</p>
          <p class="row"><a class="btn public-link" href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${icon("external")}Open public URL</a>${e.app_url ? `<a class="btn" href="${esc(e.app_url)}" target="_blank" rel="noopener noreferrer">${icon("external")}Open application</a>` : ""}</p>
          ${blocked || terminal ? `<p class="muted">${blocked ? "Actions are unavailable while this environment is blocked." : "This environment has been reclaimed."}</p>` : `<div class="action-grid"><button id="wake" type="button" ${e.active_operation_id ? "disabled" : ""}>Wake environment</button><button id="sleep" type="button" ${e.active_operation_id ? "disabled" : ""}>Sleep environment</button></div>`}
          <div id="action-result" role="status" aria-live="polite"></div>
        </div>
        <div class="panel"><h2>Resources</h2><p class="panel-subtitle">Last observed state; it may lag behind a requested change.</p>
          <div class="resource-list">${Object.entries(e.instances || {}).length ? Object.entries(e.instances).map(([name, state]) => `<div class="resource-item"><strong>${icon("cube")}${esc(name)}</strong>${badge(state, "resource")}</div>`).join("") : `<p class="muted">No resource observation available.</p>`}</div>
          <p class="field-note">Last activity: ${fmt(e.last_activity_at)} · Awake since: ${fmt(e.awake_since)}</p></div>
        <div class="panel"><h2>Operation history</h2>${items.length ? `<ol class="operation-list">${items.map((o) => `<li><div class="row"><strong>${esc(o.action || "Change")} ${o.target_level ? `→ ${esc(o.target_level)}` : ""}</strong>${badge(o.status, "operation")}</div><p class="field-note">Requested ${fmt(o.requested_at)} · Started ${fmt(o.started_at)} · Finished ${fmt(o.finished_at)} · Source ${esc(o.source || "Unavailable")}</p>${o.error ? `<p class="err">${esc(o.error.code || "Operation error")}: ${esc(o.error.message || o.error.detail || "Review required")}</p>` : ""}<code>${esc(o.operation_id)}</code></li>`).join("")}</ol>` : `<p class="muted">No operations recorded for this environment.</p>`}</div>`;
      document.getElementById("refresh").onclick = draw;
      for (const action of ["wake", "sleep"]) {
        const button = document.getElementById(action);
        if (!button) continue;
        const requestKey = crypto.randomUUID();
        button.onclick = async () => {
          document.querySelectorAll("#wake, #sleep").forEach((control) => { control.disabled = true; });
          try {
            const result = await api("POST", `${path}/${action}`, {}, requestKey);
            document.getElementById("action-result").textContent = `Request accepted${result && result.operation_id ? `: operation ${result.operation_id}` : ""}. Refresh status to verify completion.`;
          } catch (error) { document.getElementById("action-result").textContent = `The request outcome is unclear: ${error.message}. Refresh status and check operation history before trying again.`; }
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
    document.body.classList.toggle("signed-out", !c);
    document.getElementById("who").textContent = c ? `${c.email || ""} (${c["custom:org_id"] || "org_default"})` : "";
    document.getElementById("logout").hidden = !c;
    document.querySelector(".primary-nav").hidden = !c;
    if (!c) { document.title = "Sign in · InfraFlow"; return loginView(); }
    let h = location.hash || "#/";
    if (h.startsWith("#/?")) {
      h = `#/environments?${h.slice(3)}`;
      history.replaceState(null, "", `${location.pathname}${location.search}${h}`);
    }
    document.querySelectorAll(".primary-nav a").forEach((a) => {
      const selected = h === a.getAttribute("href") || (h.startsWith("#/environments?") && a.getAttribute("href") === "#/environments") || (h.startsWith("#/lease/") && a.getAttribute("href") === "#/leases") || (h.startsWith("#/environment/") && a.getAttribute("href") === "#/environments");
      if (selected) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    if (window.matchMedia("(max-width: 900px)").matches) document.querySelector('.primary-nav a[aria-current="page"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
    document.title = h.startsWith("#/lease/") ? "Lease · InfraFlow" : h.startsWith("#/environment/") ? "Environment · InfraFlow" : `${h === "#/new" ? "Create Lease" : h === "#/admin" ? "Admin" : h === "#/compose" ? "Blueprint check" : h === "#/leases" ? "Leases" : h.startsWith("#/environments") ? "Environments" : "Overview"} · InfraFlow`;
    let m;
    if (h === "#/new") return createView();
    if (h === "#/leases") return dashboard();
    if (h === "#/environments" || h.startsWith("#/environments?")) return environmentsView();
    if (h === "#/compose") return composeView();
    if (h === "#/admin") return adminView();
    if ((m = h.match(/^#\/environment\/(.+)$/))) return environmentView(decodeURIComponent(m[1]));
    if ((m = h.match(/^#\/lease\/(.+)$/))) return leaseView(m[1]);
    return overviewView();
  }
  document.getElementById("logout").onclick = () => { store.clear(); route(); };
  window.addEventListener("hashchange", route);
  route();
})();
