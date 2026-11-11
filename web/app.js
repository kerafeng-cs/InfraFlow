// InfraFlow management console. Talks to the InfraFlow API only, never to AWS directly.
//
// The API is the source of truth for what is allowed: each Environment carries `actions`
// (wake, sleep, hibernate: allowed, or the reason why not) and `next_change`. The console
// renders those values and never decides availability on its own.
(function ()
{
  "use strict";

  const cfg = window.INFRAFLOW || {};
  const view = document.getElementById("view");

  // ---------------------------------------------------------------------------
  // HTML rendering with escaping by default
  // ---------------------------------------------------------------------------

  class Safe
  {
    constructor(value)
    {
      this.value = value;
    }
    toString()
    {
      return this.value;
    }
  }

  const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

  function escape_html(value)
  {
    return String(value).replace(/[&<>"']/g, (c) => ESCAPES[c]);
  }

  function render_value(v)
  {
    if (v instanceof Safe)
    {
      return v.value;
    }
    if (Array.isArray(v))
    {
      return v.map(render_value).join("");
    }
    if (v === null || v === undefined || v === false)
    {
      return "";
    }
    return escape_html(v);
  }

  function html(strings, ...values)
  {
    let out = strings[0];
    for (let i = 0; i < values.length; i += 1)
    {
      out += render_value(values[i]) + strings[i + 1];
    }
    return new Safe(out);
  }

  const CHECKED = new Safe("checked");
  const SELECTED = new Safe("selected");
  const DISABLED = new Safe("disabled");

  function mount(node, content)
  {
    node.innerHTML = content.value;
  }

  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------------------
  // Session (Cognito USER_PASSWORD_AUTH)
  // ---------------------------------------------------------------------------

  const session = {
    get(key)
    {
      try
      {
        return sessionStorage.getItem(key);
      }
      catch (e)
      {
        return null;
      }
    },
    set(key, value)
    {
      try
      {
        sessionStorage.setItem(key, value);
      }
      catch (e)
      {
        // Storage can be unavailable in private windows; the session then lasts for this page only.
      }
    },
    clear()
    {
      try
      {
        sessionStorage.clear();
      }
      catch (e)
      {
        // See above.
      }
    },
  };

  let session_expired = false;

  async function cognito(target, body)
  {
    const response = await fetch(`https://cognito-idp.${cfg.region}.amazonaws.com/`, {
      method: "POST",
      headers: { "content-type": "application/x-amz-json-1.1", "x-amz-target": `AWSCognitoIdentityProviderService.${target}` },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok)
    {
      throw new Error(data.message || data.__type || "Sign-in failed");
    }
    return data;
  }

  function claims()
  {
    const token = session.get("id_token");
    if (!token)
    {
      return null;
    }
    try
    {
      const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      if (payload.exp * 1000 < Date.now())
      {
        session_expired = true;
        session.clear();
        return null;
      }
      return payload;
    }
    catch (e)
    {
      return null;
    }
  }

  function is_admin(c)
  {
    const groups = String((c && c["cognito:groups"]) || "").replace(/[\[\]]/g, " ").split(/[\s,]+/);
    return groups.includes("infraflow_admins");
  }

  // ---------------------------------------------------------------------------
  // API client
  // ---------------------------------------------------------------------------

  class ApiError extends Error
  {
    constructor(status, code, message)
    {
      super(message);
      this.status = status;
      this.code = code;
    }
  }

  async function api(method, path, body, idempotency_key)
  {
    const headers = { authorization: session.get("id_token") || "" };
    if (method !== "GET")
    {
      headers["content-type"] = "application/json";
      headers["idempotency-key"] = idempotency_key || crypto.randomUUID();
    }
    let response;
    try
    {
      response = await fetch(cfg.apiUrl + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    }
    catch (e)
    {
      throw new ApiError(0, "NETWORK", "The API could not be reached. Check your connection.");
    }
    if (response.status === 401)
    {
      session.clear();
      session_expired = true;
      setTimeout(route, 0);
      throw new ApiError(401, "UNAUTHORIZED", "Your session has expired. Sign in again.");
    }
    const text = await response.text();
    let data = null;
    try
    {
      data = text ? JSON.parse(text) : null;
    }
    catch (e)
    {
      data = null;
    }
    if (!response.ok)
    {
      const err = (data && data.error) || {};
      throw new ApiError(response.status, err.code || `HTTP_${response.status}`, err.message || response.statusText);
    }
    return data;
  }

  // ---------------------------------------------------------------------------
  // Formatting and labels
  // ---------------------------------------------------------------------------

  const this_year = new Date().getFullYear();
  const fmt_short = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  const fmt_long = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
  const fmt_clock = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const fmt_usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

  function when(iso)
  {
    if (!iso)
    {
      return "-";
    }
    const d = new Date(iso);
    return (d.getFullYear() === this_year ? fmt_short : fmt_long).format(d);
  }

  function ago(iso)
  {
    if (!iso)
    {
      return "never";
    }
    const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (minutes < 1)
    {
      return "just now";
    }
    if (minutes < 60)
    {
      return `${minutes} min ago`;
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 48)
    {
      return `${hours} h ago`;
    }
    return when(iso);
  }

  function duration(from_iso, to_iso)
  {
    if (!from_iso || !to_iso)
    {
      return "-";
    }
    const seconds = Math.max(0, Math.round((new Date(to_iso) - new Date(from_iso)) / 1000));
    if (seconds < 60)
    {
      return `${seconds} s`;
    }
    return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
  }

  function tz_label()
  {
    const minutes = -new Date().getTimezoneOffset();
    const sign = minutes >= 0 ? "+" : "-";
    const abs = Math.abs(minutes);
    return `UTC${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
  }

  const LEVEL_LABEL = { AWAKE: "Awake", "ASLEEP:deep": "Deep sleep", "ASLEEP:hibernate": "Hibernating", PREPARED: "Prepared", RECLAIMED: "Reclaimed" };
  const LEVEL_TONE = { AWAKE: "ok", "ASLEEP:deep": "sleep", "ASLEEP:hibernate": "hibernate", PREPARED: "neutral", RECLAIMED: "neutral" };
  const TARGET_LABEL = { AWAKE: "Awake", "ASLEEP:deep": "Deep sleep", "ASLEEP:hibernate": "Hibernate", PREPARED: "Prepared", RECLAIMED: "Reclaim" };
  const SOURCE_LABEL = { POLICY: "activity policy", IDLE: "idle", MANUAL: "manual request", PUBLIC_URL: "sleeping page", EXPIRY: "Lease expiry" };
  const OPERATION_LABEL = { WAKE: "Waking", SLEEP: "Going to sleep", PROVISION: "Provisioning", RECLAIM: "Reclaiming" };
  const REASON_TEXT = {
    ALREADY_AT_TARGET: { wake: "Already awake", sleep: "Already asleep", hibernate: "Already hibernating" },
    OPERATION_IN_PROGRESS: "An operation is running",
    REQUEST_PENDING: "A request is about to start",
    ENVIRONMENT_BLOCKED: "Blocked; an administrator must resolve it",
    LEASE_EXPIRED: "The Lease has expired",
    ENVIRONMENT_RECLAIMED: "The Environment has been reclaimed",
  };

  function env_state(env)
  {
    if (env.status === "RECLAIMED")
    {
      return { text: "Reclaimed", tone: "neutral" };
    }
    if (env.status === "VERIFYING")
    {
      return { text: "Verifying removal", tone: "changing" };
    }
    if (env.blocked)
    {
      return { text: "Blocked", tone: "danger" };
    }
    if (env.active_operation_id)
    {
      const op = env.operation || {};
      let text = OPERATION_LABEL[op.action] || "Changing";
      if (op.action === "SLEEP" && op.target_level === "hibernate")
      {
        text = "Hibernating";
      }
      return { text, tone: "changing" };
    }
    if (env.requested)
    {
      const verb = env.requested === "AWAKE" ? "Wake" : env.requested === "ASLEEP:hibernate" ? "Hibernate" : "Sleep";
      return { text: `${verb} requested`, tone: "changing" };
    }
    if (LEVEL_LABEL[env.actual])
    {
      return { text: LEVEL_LABEL[env.actual], tone: LEVEL_TONE[env.actual] };
    }
    return { text: "Not provisioned", tone: "neutral" };
  }

  function pill(state, large)
  {
    return html`<span class="pill tone-${state.tone}${large ? " lg" : ""}">${state.text}</span>`;
  }

  function target_text(env)
  {
    if (!env.desired || env.desired === env.actual || env.status === "RECLAIMED")
    {
      return "";
    }
    if (env.desired.startsWith("ASLEEP") && env.actual === "PREPARED")
    {
      return "";
    }
    const source = SOURCE_LABEL[env.desired_source];
    return `Target: ${TARGET_LABEL[env.desired] || env.desired}${source ? ` (${source})` : ""}`;
  }

  function next_text(next)
  {
    if (!next)
    {
      return "";
    }
    if (next.reason === "request")
    {
      return "Wakes on request";
    }
    const at = when(next.at);
    if (next.reason === "expiry")
    {
      return `Reclaimed ${at} (Lease expiry)`;
    }
    if (next.reason === "manual")
    {
      return `Manual hold until ${at}`;
    }
    if (next.to === "AWAKE")
    {
      return `Wakes ${at} (schedule)`;
    }
    if (next.reason === "idle")
    {
      return `Sleeps ${at} if idle`;
    }
    return `Sleeps ${at} (schedule)`;
  }

  function reason_text(action, reason)
  {
    const entry = REASON_TEXT[reason];
    if (!entry)
    {
      return reason || "";
    }
    return typeof entry === "string" ? entry : entry[action];
  }

  const RESOURCE_ORDER = ["network", "egress", "database", "app", "entry"];
  const RESOURCE_LABEL = { PRESENT: "Present", RUNNING: "Running", STOPPED: "Stopped", ABSENT: "Absent", SNAPSHOTTED: "Snapshot" };
  const RESOURCE_TONE = { PRESENT: "ok", RUNNING: "ok", STOPPED: "sleep", ABSENT: "neutral", SNAPSHOTTED: "hibernate" };
  const CLASS_LABEL = { free: "free", stoppable: "stoppable", hourly_no_data: "hourly, no data", data: "data" };

  function resource_names(instances)
  {
    const names = Object.keys(instances || {});
    const known = RESOURCE_ORDER.filter((n) => names.includes(n));
    return known.concat(names.filter((n) => !RESOURCE_ORDER.includes(n)).sort());
  }

  // ---------------------------------------------------------------------------
  // Notices, confirmation, polling
  // ---------------------------------------------------------------------------

  function toast(message, tone)
  {
    let area = document.querySelector(".toast-area");
    if (!area)
    {
      area = document.createElement("div");
      area.className = "toast-area";
      area.setAttribute("role", "status");
      area.setAttribute("aria-live", "polite");
      document.body.appendChild(area);
    }
    const node = document.createElement("div");
    node.className = `notice tone-${tone || "neutral"}`;
    node.textContent = message;
    area.appendChild(node);
    setTimeout(() => node.remove(), 6000);
  }

  function error_notice(err)
  {
    const code = err && err.code ? `${err.code}: ` : "";
    return html`<div class="notice tone-danger" role="alert"><strong>Request failed</strong>${code}${err && err.message ? err.message : String(err)}</div>`;
  }

  function confirm_dialog(title, body, ok_label, danger)
  {
    const dialog = $("confirm");
    $("confirm-title").textContent = title;
    mount($("confirm-body"), body);
    const ok = $("confirm-ok");
    ok.textContent = ok_label;
    ok.className = danger ? "btn danger solid" : "btn primary";
    dialog.returnValue = "";
    dialog.showModal();
    return new Promise((resolve) =>
    {
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    });
  }

  // One poller for the current page: every 10 s while an operation runs, otherwise every 30 s,
  // paused while the tab is hidden and refreshed as soon as it becomes visible again.
  const poller = {
    timer: null,
    task: null,
    start(task, busy)
    {
      this.stop();
      this.task = task;
      this.schedule(busy ? 10000 : 30000);
    },
    schedule(ms)
    {
      clearTimeout(this.timer);
      const task = this.task;
      this.timer = setTimeout(async () =>
      {
        if (!task || task !== this.task)
        {
          return;
        }
        if (document.visibilityState !== "visible")
        {
          return;
        }
        let busy = false;
        try
        {
          busy = await task();
        }
        catch (e)
        {
          busy = false;
        }
        if (task === this.task)
        {
          this.schedule(busy ? 10000 : 30000);
        }
      }, ms);
    },
    stop()
    {
      clearTimeout(this.timer);
      this.task = null;
    },
  };

  document.addEventListener("visibilitychange", () =>
  {
    if (document.visibilityState === "visible" && poller.task)
    {
      poller.schedule(0);
    }
  });

  function refreshed_line(busy)
  {
    return html`<p class="refresh-line">Updated ${fmt_clock.format(new Date())}. Refreshes every ${busy ? 10 : 30} s. Times in ${tz_label()}.</p>`;
  }

  // ---------------------------------------------------------------------------
  // Shared: environment row and actions
  // ---------------------------------------------------------------------------

  // Copy for the three actions. A private Environment (exposure none) has no URL to switch.
  const ACTION_COPY = {
    wake: {
      title: "Wake",
      hint: (env) => env.exposure === "none" ? "Start every resource of the blueprint." : "Start everything and switch the URL to the application.",
      body: (name, env) => html`<p>Wake <strong>${name}</strong>. Every resource of the blueprint is created or started, and billing for it resumes.${env.exposure === "none" ? "" : " The URL switches to the application once the health check passes."}</p>`,
    },
    sleep: {
      title: "Sleep",
      hint: () => "Stop compute and remove hourly-billed resources. Persistent data is kept.",
      body: (name, env) => html`<p>Put <strong>${name}</strong> into deep sleep.${env.exposure === "none" ? "" : " The URL switches to the sleeping page first."} Hourly-billed resources such as NAT, the load balancer and caches are removed; compute and databases are stopped. Persistent data is kept; cache contents are lost.</p>`,
    },
    hibernate: {
      title: "Hibernate",
      hint: () => "Snapshot persistent data, then remove every billable resource.",
      body: (name) => html`<p>Hibernate <strong>${name}</strong>. Persistent data (databases, data volumes) is snapshotted, each snapshot is verified, and then every billable resource is removed. Waking restores from the snapshots and takes longer.</p>`,
    },
  };

  function action_button(env, name, extra_class)
  {
    const a = (env.actions || {})[name] || { allowed: false, reason: null };
    const why = a.allowed ? ACTION_COPY[name].hint(env) : reason_text(name, a.reason);
    return html`<button type="button" class="btn ${extra_class}" data-action="${name}" data-env="${env.environment_id}" data-name="${env.name}" data-exposure="${env.exposure || "public"}" title="${why}" ${a.allowed ? "" : DISABLED}>${ACTION_COPY[name].title}</button>`;
  }

  function env_row(env)
  {
    const state = env_state(env);
    const target = target_text(env);
    return html`<tr class="env-row">
      <td data-label="Environment"><a class="env-name" href="#/environment/${encodeURIComponent(env.environment_id)}">${env.name}</a><span class="env-id">${env.environment_id}</span></td>
      <td data-label="State" class="state-cell">${pill(state)}${target ? html`<span class="target">${target}</span>` : ""}${env.blocked_reason ? html`<span class="target">${env.blocked_reason.code}</span>` : ""}</td>
      <td data-label="Next change" class="small">${next_text(env.next_change) || html`<span class="muted">None scheduled</span>`}</td>
      <td data-label="Checked" class="small nowrap">${ago(env.observed_at)}</td>
      <td data-label="Links" class="small nowrap">${env.url ? html`<a href="${env.url}" target="_blank" rel="noopener noreferrer">Public URL</a>` : html`<span class="muted" title="This blueprint has no public URL">Private</span>`}${env.app_url ? html`<br><a href="${env.app_url}" target="_blank" rel="noopener noreferrer">Application</a>` : ""}</td>
      <td data-label="Actions" class="actions"><div class="btn-row">${action_button(env, "wake", "sm")}${action_button(env, "sleep", "sm")}</div></td>
    </tr>`;
  }

  const ENV_HEAD = html`<thead><tr><th>Environment</th><th>State</th><th>Next change</th><th>Checked</th><th>Links</th><th class="actions">Actions</th></tr></thead>`;

  // Delegated handler for Wake, Sleep and Hibernate buttons on every page.
  view.addEventListener("click", async (event) =>
  {
    const button = event.target.closest("button[data-action]");
    if (!button || button.disabled)
    {
      return;
    }
    const action = button.dataset.action;
    const copy = ACTION_COPY[action];
    const env_like = { exposure: button.dataset.exposure };
    const ok = await confirm_dialog(`${copy.title} ${button.dataset.name}?`, copy.body(button.dataset.name, env_like), copy.title, action !== "wake");
    if (!ok)
    {
      return;
    }
    // Disable every action of this Environment until the next refresh shows the new state.
    view.querySelectorAll(`button[data-env="${CSS.escape(button.dataset.env)}"]`).forEach((b) => { b.disabled = true; });
    const path = `/v1/environments/${encodeURIComponent(button.dataset.env)}/${action === "wake" ? "wake" : "sleep"}`;
    const body = action === "wake" ? {} : { level: action === "hibernate" ? "hibernate" : "deep" };
    try
    {
      await api("POST", path, body);
      toast(`${copy.title} requested for ${button.dataset.name}.`, "ok");
    }
    catch (err)
    {
      toast(`${err.code || "Error"}: ${err.message}`, "danger");
    }
    if (poller.task)
    {
      poller.schedule(0);
    }
  });

  // ---------------------------------------------------------------------------
  // Sign in
  // ---------------------------------------------------------------------------

  function signin_view()
  {
    if (!cfg.apiUrl || !cfg.region || !cfg.clientId)
    {
      mount(view, html`<div class="signin"><div class="panel"><h1>Console not configured</h1><p class="muted">config.js is missing. Open the console from the deployed site URL.</p></div></div>`);
      return;
    }
    mount(view, html`<div class="signin"><div class="panel">
      <h1>Sign in</h1>
      <p class="muted">InfraFlow environment console</p>
      ${session_expired ? html`<br><div class="notice tone-changing small">Your session expired. Sign in again.</div>` : ""}
      <form id="signin" class="form" novalidate>
        <div class="field"><label for="email">Email</label><input id="email" type="email" autocomplete="username" required spellcheck="false"></div>
        <div class="field"><label for="password">Password</label><input id="password" type="password" autocomplete="current-password" required></div>
        <div class="field" id="new-password-field" hidden><label for="new-password">New password</label><input id="new-password" type="password" autocomplete="new-password" minlength="8"><span class="help">At least 8 characters, with a lowercase letter and a digit.</span></div>
        <p id="signin-error" class="error-text" role="alert"></p>
        <div class="form-actions"><button class="btn primary" id="signin-submit" type="submit">Sign in</button></div>
      </form></div></div>`);
    let challenge = null;
    $("signin").onsubmit = async (event) =>
    {
      event.preventDefault();
      const submit = $("signin-submit");
      const email = $("email").value.trim();
      $("signin-error").textContent = "";
      submit.disabled = true;
      try
      {
        let result;
        if (challenge)
        {
          result = await cognito("RespondToAuthChallenge", {
            ClientId: cfg.clientId,
            ChallengeName: "NEW_PASSWORD_REQUIRED",
            Session: challenge,
            ChallengeResponses: { USERNAME: email, NEW_PASSWORD: $("new-password").value },
          });
        }
        else
        {
          result = await cognito("InitiateAuth", {
            ClientId: cfg.clientId,
            AuthFlow: "USER_PASSWORD_AUTH",
            AuthParameters: { USERNAME: email, PASSWORD: $("password").value },
          });
        }
        if (result.ChallengeName === "NEW_PASSWORD_REQUIRED")
        {
          challenge = result.Session;
          $("new-password-field").hidden = false;
          $("new-password").required = true;
          $("new-password").focus();
          submit.textContent = "Set password and sign in";
          return;
        }
        session.set("id_token", result.AuthenticationResult.IdToken);
        session_expired = false;
        location.hash = "#/";
        route();
      }
      catch (err)
      {
        $("signin-error").textContent = err.message;
      }
      finally
      {
        submit.disabled = false;
      }
    };
  }

  // ---------------------------------------------------------------------------
  // Environments (home)
  // ---------------------------------------------------------------------------

  async function home_view()
  {
    mount(view, html`<div class="page-head"><div><h1>Environments</h1><p class="sub">Every Environment in your organization, grouped by Lease.</p></div>
      <a class="btn primary" href="#/new">New Lease</a></div>
      <div id="home-body"><p class="muted">Loading...</p></div>`);
    const draw = async () =>
    {
      const leases = (await api("GET", "/v1/leases")).items || [];
      const body = $("home-body");
      if (!body)
      {
        return false;
      }
      if (!leases.length)
      {
        mount(body, html`<div class="panel empty"><strong>No Leases yet</strong><p>A Lease creates one or more Environments from a blueprint.</p><br><a class="btn primary" href="#/new">New Lease</a></div>`);
        return false;
      }
      const envs = leases.flatMap((l) => l.environments || []);
      const busy = envs.some((e) => e.active_operation_id);
      const count = (pred) => envs.filter(pred).length;
      const counters = [
        ["Awake", count((e) => env_state(e).text === "Awake"), "ok"],
        ["Asleep", count((e) => ["Deep sleep", "Hibernating", "Prepared"].includes(env_state(e).text) && env_state(e).tone !== "changing"), "sleep"],
        ["Changing", count((e) => env_state(e).tone === "changing"), "changing"],
        ["Blocked", count((e) => env_state(e).tone === "danger"), "danger"],
      ];
      mount(body, html`
        <div class="counters">${counters.map(([label, value, tone]) => html`<div class="counter tone-${tone}"><div class="label">${label}</div><div class="value">${value}</div></div>`)}</div>
        <div class="panel"><div class="table-wrap"><table class="env-table">${ENV_HEAD}<tbody>
          ${leases.map((l) => html`
            <tr class="group"><td colspan="6">
              <a class="lease-name" href="#/lease/${encodeURIComponent(l.lease_id)}">${l.name}</a>
              <span class="meta">${l.blueprint_ref}</span>
              <span class="meta">${l.mode === "on_demand" ? "On demand" : "Schedule"}</span>
              <span class="meta">Expires ${when(l.expires_at)}</span>
            </td></tr>
            ${(l.environments || []).map(env_row)}`)}
        </tbody></table></div>${refreshed_line(busy)}</div>`);
      return busy;
    };
    try
    {
      poller.start(draw, await draw());
    }
    catch (err)
    {
      mount($("home-body"), error_notice(err));
    }
  }

  // ---------------------------------------------------------------------------
  // Activity policy editor (New Lease and Lease page)
  // ---------------------------------------------------------------------------

  const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  function policy_fields(prefix, policy)
  {
    const p = policy || {};
    const mode = p.mode || "on_demand";
    const sch = p.schedule || { days: [1, 2, 3, 4, 5], start: "08:00", end: "19:00" };
    const idle = p.idle_timeout_minutes || 60;
    return html`
      <div class="field wide"><span class="label" id="${prefix}-mode-label">Mode</span>
        <div class="segmented" role="radiogroup" aria-labelledby="${prefix}-mode-label">
          <label><input type="radio" name="${prefix}-mode" value="on_demand" ${mode === "on_demand" ? CHECKED : ""}>On demand<span>Asleep until someone wakes it; sleeps again after an idle period.</span></label>
          <label><input type="radio" name="${prefix}-mode" value="schedule" ${mode === "schedule" ? CHECKED : ""}>Schedule<span>Awake during set hours on set days; asleep otherwise.</span></label>
        </div>
      </div>
      <br>
      <div class="fields" data-mode="schedule">
        <div class="field wide"><span class="label" id="${prefix}-days-label">Awake days</span>
          <div class="days" role="group" aria-labelledby="${prefix}-days-label" id="${prefix}-days" tabindex="-1">${DAY_NAMES.map((d, i) => html`<button type="button" data-day="${i + 1}" aria-pressed="${sch.days.includes(i + 1)}">${d}</button>`)}</div>
        </div>
        <div class="field"><label for="${prefix}-start">Awake from (UTC+07:00)</label><input id="${prefix}-start" type="time" value="${sch.start}" required></div>
        <div class="field"><label for="${prefix}-end">Awake until (UTC+07:00)</label><input id="${prefix}-end" type="time" value="${sch.end}" required></div>
        <div class="field"><label for="${prefix}-off">Outside the window</label>
          <select id="${prefix}-off"><option value="deep">Deep sleep</option><option value="hibernate" ${p.off_hours_level === "hibernate" ? SELECTED : ""}>Hibernate</option></select></div>
        <div class="field"><span class="label">Idle inside the window</span><label class="check"><input type="checkbox" id="${prefix}-hybrid" ${p.mode === "schedule" && p.idle_timeout_minutes ? CHECKED : ""}> Also sleep when idle</label></div>
      </div>
      <div class="fields" data-mode="idle">
        <div class="field"><label for="${prefix}-idle">Sleep after idle (minutes)</label><input id="${prefix}-idle" type="number" min="5" max="1440" step="1" value="${idle}" required><span class="help">5 to 1440. An Environment stays awake at least 60 minutes, because NAT and the load balancer bill per started hour.</span></div>
        <div class="field"><label for="${prefix}-idle-level">Idle sleep level</label>
          <select id="${prefix}-idle-level"><option value="deep">Deep sleep</option><option value="hibernate" ${p.idle_level === "hibernate" ? SELECTED : ""}>Hibernate</option></select></div>
      </div>`;
  }

  function bind_policy(root, prefix)
  {
    const sync = () =>
    {
      const mode = root.querySelector(`input[name="${prefix}-mode"]:checked`).value;
      const hybrid = root.querySelector(`#${prefix}-hybrid`).checked;
      root.querySelector('[data-mode="schedule"]').hidden = mode !== "schedule";
      root.querySelector('[data-mode="idle"]').hidden = !(mode === "on_demand" || hybrid);
    };
    root.querySelectorAll(`input[name="${prefix}-mode"], #${prefix}-hybrid`).forEach((el) => el.addEventListener("change", sync));
    root.querySelectorAll(`#${prefix}-days button`).forEach((b) =>
    {
      b.addEventListener("click", () => b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true")));
    });
    sync();
  }

  // Reads only the fields that apply to the selected mode; hidden fields are never sent.
  function read_policy(root, prefix)
  {
    const mode = root.querySelector(`input[name="${prefix}-mode"]:checked`).value;
    const value = (id) => root.querySelector(`#${prefix}-${id}`).value;
    const idle_minutes = () =>
    {
      const n = Number(value("idle"));
      if (!Number.isInteger(n) || n < 5 || n > 1440)
      {
        throw field_error(`${prefix}-idle`, "Idle time must be a whole number of minutes from 5 to 1440.");
      }
      return n;
    };
    const policy = { mode, utc_offset_minutes: 420 };
    if (mode === "on_demand")
    {
      policy.idle_timeout_minutes = idle_minutes();
      policy.idle_level = value("idle-level");
      return policy;
    }
    const days = [...root.querySelectorAll(`#${prefix}-days button[aria-pressed="true"]`)].map((b) => Number(b.dataset.day));
    if (!days.length)
    {
      throw field_error(`${prefix}-days`, "Select at least one awake day.");
    }
    const start = value("start");
    const end = value("end");
    if (!start || !end || start >= end)
    {
      throw field_error(`${prefix}-end`, "The awake window must end after it starts, on the same day.");
    }
    policy.schedule = { days, start, end };
    policy.off_hours_level = value("off");
    if (root.querySelector(`#${prefix}-hybrid`).checked)
    {
      policy.idle_timeout_minutes = idle_minutes();
      policy.idle_level = value("idle-level");
    }
    return policy;
  }

  function policy_summary(p)
  {
    if (!p)
    {
      return "-";
    }
    const level = (l) => (l === "hibernate" ? "hibernate" : "deep sleep");
    if (p.mode === "on_demand")
    {
      return `On demand. Sleeps (${level(p.idle_level)}) after ${p.idle_timeout_minutes} idle minutes.`;
    }
    const s = p.schedule || {};
    const days = (s.days || []).map((d) => DAY_NAMES[d - 1]).join(", ");
    const idle = p.idle_timeout_minutes ? ` Inside the window, sleeps after ${p.idle_timeout_minutes} idle minutes.` : "";
    return `Schedule. Awake ${s.start} to ${s.end} (UTC+07:00) on ${days}; ${level(p.off_hours_level)} otherwise.${idle}`;
  }

  function field_error(id, message)
  {
    const err = new Error(message);
    err.field = id;
    return err;
  }

  function show_form_error(form, err)
  {
    form.querySelectorAll('[aria-invalid="true"]').forEach((el) => el.removeAttribute("aria-invalid"));
    form.querySelector(".form-error").textContent = err.code ? `${err.code}: ${err.message}` : err.message;
    if (err.field)
    {
      const el = document.getElementById(err.field);
      if (el)
      {
        el.setAttribute("aria-invalid", "true");
        el.focus();
      }
    }
  }

  function clear_form_error(form)
  {
    form.querySelectorAll('[aria-invalid="true"]').forEach((el) => el.removeAttribute("aria-invalid"));
    form.querySelector(".form-error").textContent = "";
  }

  function to_local_input(date)
  {
    const d = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return d.toISOString().slice(0, 16);
  }

  // ---------------------------------------------------------------------------
  // New Lease
  // ---------------------------------------------------------------------------

  const MAX_ENVS = 5;
  const MAX_DAYS = 120;

  const CATEGORY_LABELS = { web: "Web", worker: "Worker", data: "Data", ml: "ML" };
  const DATA_LABELS = {
    persistent: ["Persistent data", "Kept across sleep; snapshotted before hibernation."],
    retained: ["Retained data", "Kept while asleep; deleted without a backup at expiry."],
    ephemeral: ["Ephemeral data", "Held in memory and lost on sleep."],
    stateless: ["Stateless", "Keeps no data of its own."],
  };
  const LEVEL_LABELS = { awake: "Awake", shallow: "Shallow", deep: "Deep sleep", hibernate: "Hibernated" };

  function usd(value)
  {
    if (value === 0)
    {
      return "$0";
    }
    return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(3)}`;
  }

  function blueprint_card(bp, size, checked)
  {
    const c = bp.classification;
    const hourly = c.hourly_usd[size] || c.hourly_usd.small;
    const [data_label, data_help] = DATA_LABELS[c.data] || [c.data, ""];
    const [name, version] = bp.ref.split("@");
    return html`<label class="bp-card">
      <input type="radio" name="lf-bp" value="${bp.ref}" ${checked ? CHECKED : ""}>
      <span class="bp-head"><strong>${name}</strong><span class="mono faint">${version}</span></span>
      <span class="bp-summary">${bp.summary || ""}</span>
      <span class="bp-tags">
        <span class="tag">${CATEGORY_LABELS[c.category] || c.category}</span>
        <span class="tag" title="${c.exposure === "public" ? "Served on a public URL with a sleeping page" : "No public URL; reachable inside its own network only"}">${c.exposure === "public" ? "Public URL" : "Private"}</span>
        <span class="tag" title="${data_help}">${data_label}</span>
      </span>
      <span class="bp-parts mono">${(bp.instance_order || Object.keys(bp.instances)).join(" / ")}</span>
      <span class="bp-cost">
        <span><span class="label">Awake</span><span class="value">${usd(hourly.awake)}/h</span></span>
        <span><span class="label">${LEVEL_LABELS[c.deepest_level] || c.deepest_level}</span><span class="value">${usd(hourly[c.deepest_level])}/h</span></span>
      </span>
    </label>`;
  }

  async function new_lease_view()
  {
    const now = new Date();
    now.setSeconds(0, 0);
    const later = new Date(now.getTime() + 30 * 864e5);
    mount(view, html`<div class="page-head"><div><h1>New Lease</h1><p class="sub">A Lease creates one Environment per name below, all from the same blueprint and settings.</p></div></div>
      <form id="lease-form" class="form" novalidate>
        <fieldset><legend>Lease</legend><div class="fields">
          <div class="field"><label for="lf-name">Name</label><input id="lf-name" required maxlength="16" autocomplete="off" spellcheck="false" placeholder="acme"><span class="help">2 to 16 lowercase letters or digits, starting with a letter.</span></div>
          <div class="field"><label for="lf-size">Size</label><select id="lf-size"><option value="small">Small</option><option value="medium">Medium</option></select></div>
        </div></fieldset>

        <fieldset id="lf-blueprint"><legend>Blueprint</legend>
          <div class="bp-filter" id="lf-bp-filter" role="group" aria-label="Filter by category"></div>
          <div class="bp-grid" id="lf-bp-list" tabindex="-1" role="radiogroup" aria-label="Blueprint"><p class="muted">Loading the catalog...</p></div>
          <p class="help bp-note">Estimated USD per hour in ap-southeast-1 at the selected size, awake and at the deepest sleep level the blueprint supports.</p>
        </fieldset>

        <fieldset><legend>Environments</legend>
          <div class="repeat-list" id="lf-envs"></div>
          <br>
          <div class="btn-row"><button type="button" class="btn sm" id="lf-add-env">Add environment</button><span class="help">Up to ${MAX_ENVS}. Each name is 1 to 8 lowercase letters or digits. Every Environment is a separate copy of the blueprint.</span></div>
        </fieldset>

        <fieldset><legend>Lifetime</legend><div class="fields">
          <div class="field"><label for="lf-start">Starts</label><input id="lf-start" type="datetime-local" value="${to_local_input(now)}" required></div>
          <div class="field"><label for="lf-end">Expires</label><input id="lf-end" type="datetime-local" value="${to_local_input(later)}" required><span class="help">At most ${MAX_DAYS} days after the start. Environments are reclaimed at expiry.</span></div>
        </div></fieldset>

        <fieldset id="lf-app"><legend>Application</legend><div class="fields">
          <div class="field wide"><label for="lf-image">Container image (linux/amd64)</label><input id="lf-image" value="ghcr.io/kerafeng-cs/infraflow-demo-app:1" spellcheck="false"></div>
          <div class="field"><label for="lf-port">Port</label><input id="lf-port" type="number" min="1" max="65535" value="8080"></div>
          <div class="field" id="lf-health-field"><label for="lf-health">Health check path</label><input id="lf-health" value="/healthz" spellcheck="false"></div>
        </div>
        <p class="help" id="lf-private-help" hidden>This blueprint has no public URL. Reach the container or the private services with SSM Session Manager port forwarding.</p>
        </fieldset>

        <fieldset id="lf-policy"><legend>Activity</legend>${policy_fields("lf", { mode: "on_demand", idle_timeout_minutes: 60 })}</fieldset>

        <fieldset id="lf-data"><legend>Data at expiry</legend>
          <label class="check"><input type="checkbox" id="lf-keep" checked> Keep a final snapshot of the persistent data when the Lease is reclaimed</label>
          <p class="help" id="lf-keep-none" hidden>This blueprint keeps no data that survives sleep, so there is nothing to back up at expiry.</p>
        </fieldset>

        <p class="error-text form-error" role="alert"></p>
        <div class="form-actions"><button type="submit" class="btn primary" id="lf-submit">Review and create</button><a class="btn ghost" href="#/">Cancel</a></div>
      </form>`);

    const form = $("lease-form");
    const env_list = $("lf-envs");
    const sync_envs = () =>
    {
      const rows = [...env_list.children];
      $("lf-add-env").disabled = rows.length >= MAX_ENVS;
      rows.forEach((r, i) =>
      {
        r.querySelector("button").disabled = rows.length === 1;
        r.querySelector("input").setAttribute("aria-label", `Environment name ${i + 1}`);
      });
    };
    const add_env = (value) =>
    {
      const row = document.createElement("div");
      row.className = "repeat-row";
      mount(row, html`<input id="lf-env-${crypto.randomUUID().slice(0, 8)}" maxlength="8" spellcheck="false" autocomplete="off" value="${value}" placeholder="qa"><button type="button" class="btn sm ghost">Remove</button>`);
      row.querySelector("button").onclick = () =>
      {
        row.remove();
        sync_envs();
      };
      env_list.appendChild(row);
      sync_envs();
      return row.querySelector("input");
    };
    $("lf-add-env").onclick = () => add_env("").focus();
    add_env("qa");
    bind_policy($("lf-policy"), "lf");
    form.addEventListener("input", () => clear_form_error(form));

    const start_input = $("lf-start");
    const end_input = $("lf-end");
    const sync_dates = () =>
    {
      const start = new Date(start_input.value);
      if (!isNaN(start))
      {
        end_input.min = to_local_input(new Date(start.getTime() + 3600000));
        end_input.max = to_local_input(new Date(start.getTime() + MAX_DAYS * 864e5));
      }
    };
    start_input.addEventListener("change", sync_dates);
    sync_dates();

    let blueprints = [];
    let category = "all";
    const selected_blueprint = () => blueprints.find((b) => b.ref === form.querySelector("input[name=lf-bp]:checked")?.value);
    const sync_blueprint = () =>
    {
      const bp = selected_blueprint();
      const persistent = !bp || bp.classification.data === "persistent";
      $("lf-keep").closest("label").hidden = !persistent;
      $("lf-keep-none").hidden = persistent;
      $("lf-app").hidden = Boolean(bp) && !bp.classification.workload;
      $("lf-health-field").hidden = Boolean(bp) && bp.classification.exposure !== "public";
      $("lf-private-help").hidden = !bp || bp.classification.exposure === "public";
    };
    const render_blueprints = () =>
    {
      const size = $("lf-size").value;
      const current = form.querySelector("input[name=lf-bp]:checked")?.value;
      const shown = blueprints.filter((b) => category === "all" || b.classification.category === category);
      mount($("lf-bp-list"), shown.length ? html`${shown.map((b) => blueprint_card(b, size, b.ref === current))}` : html`<p class="muted">No blueprint in this category yet.</p>`);
      if (!form.querySelector("input[name=lf-bp]:checked") && shown.length)
      {
        form.querySelector("input[name=lf-bp]").checked = true;
      }
      sync_blueprint();
    };
    $("lf-bp-list").addEventListener("change", sync_blueprint);
    $("lf-size").addEventListener("change", render_blueprints);

    try
    {
      const catalog = await api("GET", "/v1/catalog/blueprints");
      // Web first, ML last; by name within a category
      const rank = (c) => Object.keys(CATEGORY_LABELS).indexOf(c);
      blueprints = (catalog.items || []).sort((a, b) => rank(a.classification.category) - rank(b.classification.category) || a.ref.localeCompare(b.ref));
      const counts = {};
      for (const b of blueprints)
      {
        counts[b.classification.category] = (counts[b.classification.category] || 0) + 1;
      }
      // Fixed order; categories without a blueprint yet are not offered as filters.
      const categories = Object.keys(CATEGORY_LABELS).filter((c) => counts[c]);
      const filter = $("lf-bp-filter");
      mount(filter, html`<button type="button" aria-pressed="true" data-category="all">All <span>${blueprints.length}</span></button>${categories.map((c) => html`<button type="button" aria-pressed="false" data-category="${c}" title="${(catalog.categories || {})[c] || ""}">${CATEGORY_LABELS[c]} <span>${counts[c]}</span></button>`)}`);
      filter.onclick = (event) =>
      {
        const button = event.target.closest("button");
        if (!button)
        {
          return;
        }
        category = button.dataset.category;
        for (const b of filter.querySelectorAll("button"))
        {
          b.setAttribute("aria-pressed", String(b === button));
        }
        render_blueprints();
      };
      render_blueprints();
    }
    catch (err)
    {
      mount($("lf-bp-list"), html``);
      show_form_error(form, err);
    }

    const read_form = () =>
    {
      const name = $("lf-name").value.trim();
      if (!/^[a-z][a-z0-9]{1,15}$/.test(name))
      {
        throw field_error("lf-name", "Name must be 2 to 16 lowercase letters or digits, starting with a letter.");
      }
      const inputs = [...env_list.querySelectorAll("input")];
      const names = inputs.map((i) => i.value.trim());
      for (let i = 0; i < names.length; i += 1)
      {
        if (!/^[a-z][a-z0-9]{0,7}$/.test(names[i]))
        {
          throw field_error(inputs[i].id, "Environment names are 1 to 8 lowercase letters or digits, starting with a letter.");
        }
        if (names.indexOf(names[i]) !== i)
        {
          throw field_error(inputs[i].id, `The name "${names[i]}" is used twice.`);
        }
      }
      const bp = selected_blueprint();
      if (!bp)
      {
        throw field_error("lf-bp-list", "Choose a blueprint.");
      }
      const blueprint = bp.ref;
      const start = new Date(start_input.value);
      const end = new Date(end_input.value);
      if (isNaN(start) || isNaN(end) || end <= start)
      {
        throw field_error("lf-end", "Expiry must be after the start.");
      }
      if (end - start > MAX_DAYS * 864e5)
      {
        throw field_error("lf-end", `A Lease lasts at most ${MAX_DAYS} days.`);
      }
      const body = {
        name,
        blueprint_ref: blueprint,
        parameters: { size: $("lf-size").value },
        environments: names,
        starts_at: start.toISOString(),
        expires_at: end.toISOString(),
        activity_policy: read_policy($("lf-policy"), "lf"),
        data_policy: { keep_final_backup: bp.classification.data === "persistent" && $("lf-keep").checked },
      };
      // Blueprints that run no container of the Lease (a database or search sandbox) take no app settings.
      if (bp.classification.workload)
      {
        body.app = read_app(bp.classification.exposure === "public");
      }
      return body;
    };

    const read_app = (public_url) =>
    {
      const image = $("lf-image").value.trim();
      if (!image)
      {
        throw field_error("lf-image", "Enter a container image.");
      }
      const port = Number($("lf-port").value);
      if (!Number.isInteger(port) || port < 1 || port > 65535)
      {
        throw field_error("lf-port", "Port must be a whole number from 1 to 65535.");
      }
      const health = $("lf-health").value.trim();
      if (public_url && !health.startsWith("/"))
      {
        throw field_error("lf-health", "The health check path must start with /.");
      }
      return { image, port, health_path: public_url ? health : "/" };
    };

    const create_key = crypto.randomUUID();
    form.onsubmit = async (event) =>
    {
      event.preventDefault();
      let body;
      try
      {
        body = read_form();
      }
      catch (err)
      {
        show_form_error(form, err);
        return;
      }
      const ok = await confirm_dialog("Create this Lease?", html`<dl class="facts">
        <dt>Name</dt><dd>${body.name}</dd>
        <dt>Blueprint</dt><dd>${body.blueprint_ref}, ${body.parameters.size}</dd>
        <dt>Environments</dt><dd>${body.environments.join(", ")}</dd>
        <dt>Lifetime</dt><dd>${when(body.starts_at)} to ${when(body.expires_at)}</dd>
        ${body.app ? html`<dt>Application</dt><dd><code>${body.app.image}</code>, port ${body.app.port}${selected_blueprint().classification.exposure === "public" ? html`, health <code>${body.app.health_path}</code>` : ""}</dd>` : ""}
        <dt>Activity</dt><dd>${policy_summary(body.activity_policy)}</dd>
        <dt>At expiry</dt><dd>${selected_blueprint().classification.data !== "persistent" ? "Nothing to keep" : body.data_policy.keep_final_backup ? "Keep a final snapshot" : "Delete the data without a snapshot"}</dd>
      </dl>`, "Create Lease", false);
      if (!ok)
      {
        return;
      }
      $("lf-submit").disabled = true;
      try
      {
        const result = await api("POST", "/v1/leases", body, create_key);
        toast(`Lease ${body.name} created.`, "ok");
        location.hash = `#/lease/${encodeURIComponent(result.lease_id)}`;
      }
      catch (err)
      {
        show_form_error(form, err);
        $("lf-submit").disabled = false;
      }
    };
  }

  // ---------------------------------------------------------------------------
  // Lease
  // ---------------------------------------------------------------------------

  async function lease_view(lease_id)
  {
    const path = `/v1/leases/${encodeURIComponent(lease_id)}`;
    let lease;
    try
    {
      lease = await api("GET", path);
    }
    catch (err)
    {
      mount(view, error_notice(err));
      return;
    }
    const expired = lease.reclaim_requested || new Date(lease.expires_at) <= new Date();
    const keep = (lease.data_policy || {}).keep_final_backup;
    const app = lease.app || {};
    mount(view, html`<div class="crumbs"><a href="#/">Environments</a> / Lease</div>
      <div class="page-head"><div><h1>${lease.name}</h1><p class="sub">${lease.blueprint_ref}, ${(lease.parameters || {}).size}. ${lease.environments.length} Environment${lease.environments.length === 1 ? "" : "s"}.</p></div></div>
      <div class="panel"><div class="panel-head"><h2>Environments</h2></div><div id="lease-envs"></div></div>
      <div class="grid-2">
        <div class="panel"><div class="panel-head"><h2>Settings</h2></div>
          <dl class="facts">
            <dt>Starts</dt><dd>${when(lease.starts_at)}</dd>
            <dt>Expires</dt><dd id="lease-expires">${when(lease.expires_at)}</dd>
            <dt>Activity</dt><dd id="lease-policy">${policy_summary(lease.activity_policy)}</dd>
            <dt>Image</dt><dd><code>${app.image}</code></dd>
            <dt>Port, health</dt><dd>${app.port}, <code>${app.health_path}</code></dd>
            <dt>At expiry</dt><dd>${keep ? "Keep a final snapshot" : "Delete without a snapshot"}</dd>
          </dl>
        </div>
        <div class="panel cost"><div class="panel-head"><h2>Estimated cost</h2><span class="hint" id="cost-period"></span></div><div id="lease-cost" class="muted">Loading...</div></div>
      </div>
      ${expired ? html`<div class="notice tone-danger"><strong>Expired</strong>This Lease has expired or is being reclaimed. Its settings can no longer change.</div>` : html`
      <div class="grid-2">
        <div class="panel"><div class="panel-head"><h2>Activity policy</h2></div>
          <form id="policy-form" class="form" novalidate><div id="policy-fields">${policy_fields("pf", lease.activity_policy)}</div>
            <p class="error-text form-error" role="alert"></p>
            <div class="form-actions"><button class="btn" type="submit">Save policy</button></div>
          </form>
        </div>
        <div>
          <div class="panel"><div class="panel-head"><h2>Extend</h2></div>
            <form id="extend-form" class="form" novalidate>
              <div class="field"><label for="ext-at">New expiry</label><input id="ext-at" type="datetime-local" required><span class="help" id="ext-help"></span></div>
              <p class="error-text form-error" role="alert"></p>
              <div class="form-actions"><button class="btn" id="ext-submit" type="submit">Extend</button></div>
            </form>
          </div>
          <div class="panel"><div class="panel-head"><h2>Reclaim</h2></div>
            <p class="muted">Removes the infrastructure of every Environment in this Lease. ${keep ? "A final database snapshot is kept." : "Databases are deleted without a snapshot."}</p><br>
            <form id="reclaim-form" class="form" novalidate>
              <div class="field"><label for="reclaim-name">Type <code>${lease.name}</code> to confirm</label><input id="reclaim-name" autocomplete="off" spellcheck="false"></div>
              <p class="error-text form-error" role="alert"></p>
              <div class="form-actions"><button class="btn danger" id="reclaim-submit" type="submit" disabled>Reclaim Lease</button></div>
            </form>
          </div>
        </div>
      </div>`}`);

    let version = lease.version;
    const draw_envs = async (fresh) =>
    {
      const l = fresh || await api("GET", path);
      const node = $("lease-envs");
      if (!node)
      {
        return false;
      }
      version = l.version;
      const busy = l.environments.some((e) => e.active_operation_id);
      mount(node, html`<div class="table-wrap"><table class="env-table">${ENV_HEAD}<tbody>${l.environments.map(env_row)}</tbody></table></div>${refreshed_line(busy)}`);
      $("lease-expires").textContent = when(l.expires_at);
      $("lease-policy").textContent = policy_summary(l.activity_policy);
      return busy;
    };
    poller.start(draw_envs, await draw_envs(lease));

    api("GET", `${path}/cost`).then((c) =>
    {
      const node = $("lease-cost");
      if (!node)
      {
        return;
      }
      const values = [["Always on", c.totals.always_on, "danger"], ["Stop on schedule", c.totals.stop_only, "changing"], ["InfraFlow", c.totals.infraflow, "ok"]];
      const max = Math.max(...values.map((v) => v[1]), 0.01);
      $("cost-period").textContent = `${when(c.from)} to ${when(c.to)}`;
      mount(node, html`<div class="grid-3">${values.map(([label, value, tone]) => html`<div class="tone-${tone}"><div class="label">${label}</div><div class="value">${fmt_usd.format(value)}</div><div class="bar"><i data-w="${(value / max * 100).toFixed(1)}"></i></div></div>`)}</div>
        <br><p class="help">Estimates from ap-southeast-1 unit prices over the same period, not billed charges. Always on: every resource running. Stop on schedule: EC2 and RDS stopped outside working hours while NAT and the load balancer keep billing. InfraFlow: the transitions this Lease actually made.</p>`);
      node.classList.remove("muted");
      node.querySelectorAll("i[data-w]").forEach((i) => i.style.setProperty("--w", `${i.dataset.w}%`));
    }).catch(() =>
    {
      const node = $("lease-cost");
      if (node)
      {
        node.textContent = "Cost estimate unavailable.";
      }
    });

    if (expired)
    {
      return;
    }

    bind_policy($("policy-fields"), "pf");
    const policy_form = $("policy-form");
    policy_form.addEventListener("input", () => clear_form_error(policy_form));
    policy_form.onsubmit = async (event) =>
    {
      event.preventDefault();
      try
      {
        const policy = read_policy($("policy-fields"), "pf");
        await api("PUT", `${path}/activity-policy`, { activity_policy: policy, version });
        toast("Activity policy saved.", "ok");
        await draw_envs();
      }
      catch (err)
      {
        show_form_error(policy_form, err);
      }
    };

    // Extend: only to a time later than both now and the current expiry, within the maximum duration.
    const ext = $("ext-at");
    const extend_form = $("extend-form");
    const current_expiry = new Date(lease.expires_at);
    const min_expiry = new Date(Math.max(current_expiry.getTime(), Date.now()) + 60000);
    const max_expiry = new Date(new Date(lease.starts_at).getTime() + MAX_DAYS * 864e5);
    if (max_expiry <= min_expiry)
    {
      ext.disabled = true;
      $("ext-submit").disabled = true;
      $("ext-help").textContent = `This Lease already has the maximum duration of ${MAX_DAYS} days.`;
    }
    else
    {
      ext.min = to_local_input(min_expiry);
      ext.max = to_local_input(max_expiry);
      ext.value = to_local_input(new Date(Math.min(current_expiry.getTime() + 7 * 864e5, max_expiry.getTime())));
      $("ext-help").textContent = `Later than ${when(current_expiry.toISOString())}, at most ${when(max_expiry.toISOString())}.`;
    }
    extend_form.addEventListener("input", () => clear_form_error(extend_form));
    extend_form.onsubmit = async (event) =>
    {
      event.preventDefault();
      const value = new Date(ext.value);
      try
      {
        if (isNaN(value) || value < min_expiry)
        {
          throw field_error("ext-at", "The new expiry must be in the future and later than the current expiry.");
        }
        if (value > max_expiry)
        {
          throw field_error("ext-at", `A Lease lasts at most ${MAX_DAYS} days from its start.`);
        }
        await api("POST", `${path}/extend`, { expires_at: value.toISOString(), version });
        toast("Lease extended.", "ok");
        route();
      }
      catch (err)
      {
        show_form_error(extend_form, err);
      }
    };

    const reclaim_form = $("reclaim-form");
    $("reclaim-name").addEventListener("input", (event) =>
    {
      $("reclaim-submit").disabled = event.target.value !== lease.name;
    });
    reclaim_form.onsubmit = async (event) =>
    {
      event.preventDefault();
      if ($("reclaim-name").value !== lease.name)
      {
        return;
      }
      $("reclaim-submit").disabled = true;
      try
      {
        await api("POST", `${path}/reclaim`, { confirm: true });
        toast("Reclaim requested.", "ok");
        route();
      }
      catch (err)
      {
        show_form_error(reclaim_form, err);
      }
    };
  }

  // ---------------------------------------------------------------------------
  // Environment
  // ---------------------------------------------------------------------------

  const STATUS_TONE = { SUCCEEDED: "ok", RUNNING: "changing", ACCEPTED: "changing", FAILED: "danger", BLOCKED: "danger", HEALTH_GATE_FAILED: "danger" };

  function status_label(status)
  {
    const s = String(status || "-").replace(/_/g, " ").toLowerCase();
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  function operation_item(op)
  {
    const level = op.target_level === "awake" ? "AWAKE" : op.target_level ? `ASLEEP:${op.target_level}` : null;
    const target = op.action === "SLEEP" && level ? ` to ${(TARGET_LABEL[level] || op.target_level).toLowerCase()}` : "";
    const mc = op.plan && op.plan.model_check;
    const stage_text = (s) =>
    {
      const parts = [];
      if (s.terraform)
      {
        parts.push(`terraform ${Object.entries(s.terraform).map(([k, v]) => `${k}=${v}`).join(" ")}`);
      }
      if (s.drivers.length)
      {
        parts.push(s.drivers.join(", "));
      }
      return `${s.name}: ${parts.join("; ")}`;
    };
    return html`<details class="op"><summary>
        <span class="small nowrap">${when(op.requested_at)}</span>
        <span><strong>${status_label(op.action)}</strong>${target}</span>
        <span class="small muted hide-sm">${SOURCE_LABEL[op.source] || String(op.source || "").toLowerCase()}</span>
        <span class="small muted hide-sm">${duration(op.started_at || op.requested_at, op.finished_at)}</span>
        <span>${pill({ text: status_label(op.status), tone: STATUS_TONE[op.status] || "neutral" })}</span>
      </summary>
      <div class="detail">
        <div class="small mono muted">${op.operation_id}</div>
        ${op.error ? html`<div class="error-text">${op.error.code || "Error"}: ${op.error.message || op.error.detail || ""}</div>` : ""}
        ${mc ? html`<div class="small">Model check ${mc.passed ? "passed" : "failed"}: ${mc.states_explored} states explored.</div>` : ""}
        ${op.plan ? html`<ol class="stages">${op.plan.stages.map((s) => html`<li>${stage_text(s)}</li>`)}${op.plan.health ? html`<li>health gate, then DNS to the application</li>` : ""}</ol>` : html`<div class="small muted">No plan recorded.</div>`}
      </div></details>`;
  }

  async function environment_view(env_id)
  {
    const path = `/v1/environments/${encodeURIComponent(env_id)}`;
    mount(view, html`<div id="env-body"><p class="muted">Loading...</p></div>`);
    const open_details = new Set();
    const draw = async () =>
    {
      const [env, ops] = await Promise.all([api("GET", path), api("GET", `${path}/operations`)]);
      const node = $("env-body");
      if (!node)
      {
        return false;
      }
      node.querySelectorAll("details.op[open]").forEach((d) => open_details.add(d.dataset.id));
      const state = env_state(env);
      const items = ops.items || [];
      const active = items.find((o) => o.operation_id === env.active_operation_id);
      const busy = Boolean(env.active_operation_id);
      const instances = env.instances || {};
      const names = env.resources ? env.resources.map((r) => r.name) : resource_names(instances);
      const classes = Object.fromEntries((env.resources || []).map((r) => [r.name, r.billing_class]));
      const reason = env.blocked_reason || {};
      mount(node, html`<div class="crumbs"><a href="#/">Environments</a> / <a href="#/lease/${encodeURIComponent(env.lease_id)}">Lease</a> / Environment</div>
        <div class="page-head"><div><h1>${env.name}</h1><p class="sub mono">${env.environment_id}</p></div>
          <div class="btn-row">${env.url ? html`<a class="btn" href="${env.url}" target="_blank" rel="noopener noreferrer">Public URL</a>` : html`<span class="tag" title="This blueprint has no public URL">Private</span>`}${env.app_url ? html`<a class="btn" href="${env.app_url}" target="_blank" rel="noopener noreferrer">Application</a>` : ""}</div></div>
        ${env.blocked ? html`<div class="notice tone-danger" role="alert"><strong>Blocked: ${reason.code || "unknown reason"}</strong>${reason.detail || "An administrator must investigate and resolve this Environment."}</div>` : ""}
        <div class="grid-2">
          <div class="panel"><div class="panel-head"><h2>State</h2>${pill(state, true)}</div>
            <dl class="facts">
              <dt>Target</dt><dd>${env.desired ? `${TARGET_LABEL[env.desired] || env.desired}${SOURCE_LABEL[env.desired_source] ? ` (${SOURCE_LABEL[env.desired_source]})` : ""}` : "-"}</dd>
              <dt>Next change</dt><dd>${next_text(env.next_change) || "None scheduled"}</dd>
              <dt>Awake since</dt><dd>${env.actual === "AWAKE" ? when(env.awake_since) : "-"}</dd>
              <dt>Last activity</dt><dd>${env.last_activity_at ? `${when(env.last_activity_at)}, ${ago(env.last_activity_at)}` : "-"}</dd>
              <dt>Checked</dt><dd>${env.observed_at ? `${when(env.observed_at)}, ${ago(env.observed_at)}` : "Not yet"}</dd>
            </dl>
            ${active ? html`<div class="banner"><strong>${OPERATION_LABEL[active.action] || status_label(active.action)}</strong><span class="muted">started ${when(active.started_at || active.requested_at)}, running ${duration(active.started_at || active.requested_at, new Date().toISOString())}</span></div>` : ""}
          </div>
          <div class="panel"><div class="panel-head"><h2>Actions</h2></div>
            <div class="action-list">${["wake", "sleep", "hibernate"].map((name) =>
            {
              const a = (env.actions || {})[name] || {};
              return html`<div class="action">${action_button(env, name, name === "wake" ? "primary" : "")}<span class="why">${a.allowed ? ACTION_COPY[name].hint(env) : `Unavailable: ${reason_text(name, a.reason).toLowerCase()}.`}</span></div>`;
            })}</div>
          </div>
        </div>
        <div class="panel"><div class="panel-head"><h2>Resources</h2><span class="hint">Observed in AWS ${ago(env.observed_at)}</span></div>
          ${names.length ? html`<div class="table-wrap"><table class="resource-table"><thead><tr><th>Instance</th><th>Billing class</th><th>State</th></tr></thead><tbody>
            ${names.map((n) => html`<tr><td>${n}</td><td class="muted">${CLASS_LABEL[classes[n]] || classes[n] || "-"}</td><td>${pill({ text: RESOURCE_LABEL[instances[n]] || instances[n], tone: RESOURCE_TONE[instances[n]] || "neutral" })}</td></tr>`)}
          </tbody></table></div>` : html`<p class="muted">Not observed yet.</p>`}
        </div>
        <div class="panel"><div class="panel-head"><h2>Operations</h2><span class="hint">Most recent first</span></div>
          ${items.length ? html`<div class="op-list">${items.map(operation_item)}</div>` : html`<p class="muted">No operations yet.</p>`}
          ${refreshed_line(busy)}
        </div>`);
      node.querySelectorAll("details.op").forEach((d, i) =>
      {
        d.dataset.id = items[i].operation_id;
        d.open = open_details.has(d.dataset.id);
        d.addEventListener("toggle", () =>
        {
          if (d.open)
          {
            open_details.add(d.dataset.id);
          }
          else
          {
            open_details.delete(d.dataset.id);
          }
        });
      });
      return busy;
    };
    try
    {
      poller.start(draw, await draw());
    }
    catch (err)
    {
      mount(view, error_notice(err));
    }
  }

  // ---------------------------------------------------------------------------
  // Compose
  // ---------------------------------------------------------------------------

  const BASE_BLUEPRINT = {
    ics_version: "0.1",
    blueprint: {
      name: "web-db-custom",
      version: "1.0.0",
      owner: "org",
      summary: "Compose example",
      exposure: "public",
      classification: { category: "web" },
    },
    parameters: { size: { type: "string", enum: ["small", "medium"], default: "small" } },
    instances: {
      network: { component: "aws-network-basic@1.0.0" },
      egress: { component: "aws-nat-egress@1.0.0" },
      database: { component: "aws-rds-postgres@1.0.0", parameters: { size: "${param.size}" } },
      app: { component: "aws-ec2-docker-app@1.0.0", parameters: { size: "${param.size}" } },
      entry: { component: "aws-alb-https-entry@1.0.0" },
    },
    bindings: [
      { from: "egress.net", to: "network.net" },
      { from: "database.net", to: "network.net" },
      { from: "app.net", to: "network.net" },
      { from: "app.egress", to: "egress.egress" },
      { from: "app.db", to: "database.db" },
      { from: "app.workload", to: "sys.lease_app" },
      { from: "entry.net", to: "network.net" },
      { from: "entry.backend", to: "app.http" },
      { from: "sys.dns", to: "entry.public" },
    ],
    supported_levels: ["awake", "deep", "hibernate"],
  };

  const EXAMPLES = [
    { id: "valid", label: "Valid: web-db", make: (b) => b },
    { id: "no-db", label: "Missing database binding", make: (b) => ({ ...b, bindings: b.bindings.filter((x) => x.from !== "app.db") }) },
    { id: "type", label: "Port type mismatch", make: (b) => ({ ...b, bindings: b.bindings.map((x) => (x.from === "entry.backend" ? { ...x, to: "database.db" } : x)) }) },
    { id: "shallow", label: "Unsafe level: shallow", make: (b) => ({ ...b, supported_levels: ["awake", "shallow", "deep", "hibernate"] }) },
    { id: "worker", label: "Valid: private worker", make: private_worker },
    { id: "private-url", label: "Private, but binds a URL", make: (b) => ({ ...b, blueprint: { ...b.blueprint, exposure: "none" } }) },
  ];

  // A worker: no load balancer and no URL; the application uses the optional ports of 1.1.0.
  function private_worker(b)
  {
    const instances = { ...b.instances, app: { ...b.instances.app, component: "aws-ec2-docker-app@1.1.0" } };
    delete instances.entry;
    return {
      ...b,
      blueprint: { ...b.blueprint, name: "worker-custom", exposure: "none", classification: { category: "worker" } },
      instances,
      bindings: b.bindings.filter((x) => !x.from.startsWith("entry.") && x.from !== "sys.dns"),
    };
  }

  function highlight_json(text)
  {
    const re = /("(?:\\.|[^"\\])*")(\s*:)?|(-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|\b(true|false|null)\b/g;
    let out = "";
    let last = 0;
    let m;
    while ((m = re.exec(text)) !== null)
    {
      out += escape_html(text.slice(last, m.index));
      if (m[1])
      {
        out += `<span class="${m[2] ? "j-key" : "j-str"}">${escape_html(m[1])}</span>${m[2] ? escape_html(m[2]) : ""}`;
      }
      else if (m[3])
      {
        out += `<span class="j-num">${m[3]}</span>`;
      }
      else
      {
        out += `<span class="j-lit">${m[4]}</span>`;
      }
      last = re.lastIndex;
    }
    return `${out}${escape_html(text.slice(last))}\n`;
  }

  function compose_view()
  {
    mount(view, html`<div class="page-head"><div><h1>Compose</h1><p class="sub">Check a blueprint before it is used: composition rules C1 to C6 and M1, then model checking of every level transition under every interleaving. Nothing is deployed.</p></div></div>
      <div class="panel">
        <div class="examples"><span class="label">Examples</span>${EXAMPLES.map((e) => html`<button type="button" class="btn sm" data-example="${e.id}">${e.label}</button>`)}</div>
        <div class="editor"><div class="gutter" id="cm-gutter" aria-hidden="true"></div>
          <div class="code"><pre id="cm-pre" aria-hidden="true"></pre><textarea id="cm-text" spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="Blueprint JSON"></textarea></div></div>
        <p class="editor-status" id="cm-status" role="status"></p>
        <br>
        <div class="form-actions"><button type="button" class="btn primary" id="cm-check">Check blueprint</button></div>
      </div>
      <div id="cm-result"></div>`);
    const text = $("cm-text");
    const pre = $("cm-pre");
    const gutter = $("cm-gutter");
    let parsed = null;
    const sync_scroll = () =>
    {
      pre.scrollTop = text.scrollTop;
      pre.scrollLeft = text.scrollLeft;
      gutter.scrollTop = text.scrollTop;
    };
    const sync = () =>
    {
      pre.innerHTML = highlight_json(text.value);
      const lines = text.value.split("\n").length;
      gutter.textContent = Array.from({ length: lines }, (_, i) => i + 1).join("\n");
      sync_scroll();
      try
      {
        parsed = JSON.parse(text.value);
        $("cm-status").textContent = `Valid JSON, ${lines} lines.`;
        $("cm-status").className = "editor-status muted";
        $("cm-check").disabled = false;
      }
      catch (e)
      {
        parsed = null;
        $("cm-status").textContent = `Invalid JSON: ${e.message}`;
        $("cm-status").className = "editor-status error-text";
        $("cm-check").disabled = true;
      }
    };
    text.addEventListener("input", sync);
    text.addEventListener("scroll", sync_scroll);
    text.addEventListener("keydown", (event) =>
    {
      if (event.key === "Tab" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey)
      {
        event.preventDefault();
        const s = text.selectionStart;
        text.setRangeText("  ", s, text.selectionEnd, "end");
        sync();
      }
    });
    const load = (id) =>
    {
      const example = EXAMPLES.find((e) => e.id === id);
      text.value = JSON.stringify(example.make(structuredClone(BASE_BLUEPRINT)), null, 2);
      text.scrollTop = 0;
      sync();
      $("cm-result").innerHTML = "";
    };
    view.querySelectorAll("[data-example]").forEach((b) => { b.onclick = () => load(b.dataset.example); });
    load("valid");

    $("cm-check").onclick = async () =>
    {
      if (!parsed)
      {
        return;
      }
      const button = $("cm-check");
      button.disabled = true;
      mount($("cm-result"), html`<div class="panel muted">Checking...</div>`);
      try
      {
        mount($("cm-result"), compose_result(await api("POST", "/v1/blueprints/validate", parsed)));
      }
      catch (err)
      {
        mount($("cm-result"), error_notice(err));
      }
      finally
      {
        button.disabled = false;
      }
    };
  }

  function compose_result(r)
  {
    const composition = r.composition || [];
    const checks = r.checks || [];
    const summary = r.states_explored ? `${r.states_explored} states explored.` : composition.length ? "Composition failed; model checking did not run." : "";
    return html`<div class="panel">
      <div class="verdict">${pill({ text: r.passed ? "Pass" : "Fail", tone: r.passed ? "ok" : "danger" }, true)}<span class="muted">${summary}</span></div>
      ${composition.length ? html`<div class="table-wrap"><table><thead><tr><th>Rule</th><th>Finding</th></tr></thead><tbody>
        ${composition.map((c) => html`<tr><td class="mono">${c.code}</td><td class="error-text">${c.message}</td></tr>`)}</tbody></table></div>` : ""}
      ${checks.length ? html`<div class="table-wrap"><table><thead><tr><th>Rule</th><th>Check</th><th>Result</th></tr></thead><tbody>
        ${checks.map((c) => html`<tr><td class="mono">${c.code}</td><td>${c.name}${c.detail ? html`<div class="error-text">${c.detail.rule}: ${c.detail.message}</div>${(c.detail.trace || []).length ? html`<div class="trace">${c.detail.trace.join("\n")}</div>` : ""}` : ""}</td>
          <td>${pill({ text: c.passed ? "Pass" : "Fail", tone: c.passed ? "ok" : "danger" })}</td></tr>`)}</tbody></table></div>` : ""}
    </div>`;
  }

  // ---------------------------------------------------------------------------
  // Admin
  // ---------------------------------------------------------------------------

  async function admin_view(c)
  {
    if (!is_admin(c))
    {
      mount(view, html`<div class="panel"><h1>Not available</h1><p class="muted">The admin page is for administrators.</p></div>`);
      return;
    }
    mount(view, html`<div class="page-head"><div><h1>Admin</h1><p class="sub">Blocked Environments, and tagged resources that belong to no live Environment.</p></div></div>
      <div class="panel"><div class="panel-head"><h2>Blocked Environments</h2></div><div id="admin-blocked" class="muted">Loading...</div></div>
      <div class="panel"><div class="panel-head"><h2>Orphaned resources</h2><span class="hint">Reported by the hourly scan; never deleted automatically.</span></div><div id="admin-orphans" class="muted">Loading...</div></div>`);
    try
    {
      const blocked = (await api("GET", "/v1/admin/blocked")).items || [];
      const blocked_node = $("admin-blocked");
      mount(blocked_node, blocked.length ? html`<div class="table-wrap"><table><thead><tr><th>Environment</th><th>Reason</th><th>Checked</th><th>Resolve</th></tr></thead><tbody>
        ${blocked.map((e) => html`<tr><td><a class="env-name" href="#/environment/${encodeURIComponent(e.environment_id)}">${e.name}</a><span class="env-id">${e.environment_id}</span></td>
          <td><strong>${(e.blocked_reason || {}).code || "-"}</strong><div class="small muted">${String((e.blocked_reason || {}).detail || "").slice(0, 300)}</div></td>
          <td class="small nowrap">${ago(e.observed_at)}</td>
          <td><form class="form" data-resolve="${e.environment_id}" novalidate><div class="field"><input name="note" placeholder="What was fixed" aria-label="Resolution note"></div><div><button class="btn sm" type="submit">Retry</button></div><p class="error-text form-error small"></p></form></td></tr>`)}
      </tbody></table></div>` : html`<p class="muted">None.</p>`);
      blocked_node.classList.remove("muted");
      view.querySelectorAll("form[data-resolve]").forEach((form) =>
      {
        form.onsubmit = async (event) =>
        {
          event.preventDefault();
          const note = form.elements.note.value.trim();
          if (note.length < 4)
          {
            show_form_error(form, new Error("Describe what was fixed, in at least 4 characters."));
            return;
          }
          try
          {
            await api("POST", `/v1/admin/environments/${encodeURIComponent(form.dataset.resolve)}/resolve`, { action: "retry", note });
            toast("Retry requested.", "ok");
            route();
          }
          catch (err)
          {
            show_form_error(form, err);
          }
        };
      });
      const orphans = (await api("GET", "/v1/admin/orphans")).items || [];
      const orphans_node = $("admin-orphans");
      mount(orphans_node, orphans.length ? html`<div class="table-wrap"><table><thead><tr><th>Resource</th><th>env_id tag</th><th>First seen</th></tr></thead><tbody>
        ${orphans.map((o) => html`<tr><td class="mono small">${o.resource_arn}</td><td class="mono small">${o.env_id_tag}</td><td class="small nowrap">${when(o.first_seen)}</td></tr>`)}</tbody></table></div>` : html`<p class="muted">None.</p>`);
      orphans_node.classList.remove("muted");
    }
    catch (err)
    {
      mount(view, error_notice(err));
    }
  }

  // ---------------------------------------------------------------------------
  // Routing
  // ---------------------------------------------------------------------------

  const TITLES = { home: "Environments", new: "New Lease", compose: "Compose", admin: "Admin", lease: "Lease", environment: "Environment" };
  const NAV_TARGET = { home: "#/", lease: "#/", environment: "#/", new: "#/new", compose: "#/compose", admin: "#/admin" };

  function route()
  {
    poller.stop();
    const c = claims();
    $("nav").hidden = !c;
    $("sign-out").hidden = !c;
    $("nav-admin").hidden = !is_admin(c);
    $("who").textContent = c ? c.email || "" : "";
    if (!c)
    {
      document.title = "Sign in - InfraFlow";
      signin_view();
      return;
    }
    const hash = location.hash || "#/";
    let page = "home";
    let arg = null;
    let m;
    if (hash === "#/new")
    {
      page = "new";
    }
    else if (hash === "#/compose")
    {
      page = "compose";
    }
    else if (hash === "#/admin")
    {
      page = "admin";
    }
    else if ((m = hash.match(/^#\/lease\/([^/?]+)$/)))
    {
      page = "lease";
      arg = decodeURIComponent(m[1]);
    }
    else if ((m = hash.match(/^#\/environment\/([^/?]+)$/)))
    {
      page = "environment";
      arg = decodeURIComponent(m[1]);
    }
    document.title = `${TITLES[page]} - InfraFlow`;
    document.querySelectorAll("#nav a").forEach((a) =>
    {
      if (a.getAttribute("href") === NAV_TARGET[page])
      {
        a.setAttribute("aria-current", "page");
      }
      else
      {
        a.removeAttribute("aria-current");
      }
    });
    view.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    if (page === "new")
    {
      return new_lease_view();
    }
    if (page === "compose")
    {
      return compose_view();
    }
    if (page === "admin")
    {
      return admin_view(c);
    }
    if (page === "lease")
    {
      return lease_view(arg);
    }
    if (page === "environment")
    {
      return environment_view(arg);
    }
    return home_view();
  }

  $("sign-out").onclick = () =>
  {
    session.clear();
    session_expired = false;
    location.hash = "#/";
    route();
  };
  window.addEventListener("hashchange", route);
  route();
})();
