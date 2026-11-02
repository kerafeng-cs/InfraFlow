// Web quản lý InfraFlow. Chỉ gọi API; không gọi AWS trực tiếp (TD mục 6).
(function () {
  "use strict";
  const cfg = window.INFRAFLOW || {};
  const view = document.getElementById("view");
  let pollTimer = null;

  // ---------------- phiên đăng nhập (Cognito USER_PASSWORD_AUTH) ----------------
  const store = {
    get(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* bỏ qua */ } },
    clear() { try { sessionStorage.clear(); } catch (e) { /* bỏ qua */ } },
  };

  async function cognito(target, body) {
    const r = await fetch(`https://cognito-idp.${cfg.region}.amazonaws.com/`, {
      method: "POST",
      headers: { "content-type": "application/x-amz-json-1.1", "x-amz-target": `AWSCognitoIdentityProviderService.${target}` },
      body: JSON.stringify(body),
    });
    const b = await r.json();
    if (!r.ok) throw new Error(b.message || b.__type || "Đăng nhập thất bại");
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
    if (r.status === 401) { store.clear(); route(); throw new Error("Phiên đăng nhập hết hạn"); }
    const text = await r.text();
    const b = text ? JSON.parse(text) : null;
    if (!r.ok) throw new Error((b && b.error && `${b.error.code}: ${b.error.message}`) || r.statusText);
    return b;
  }

  // ---------------- tiện ích ----------------
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (iso) => (iso ? new Date(iso).toLocaleString("vi-VN") : "–");
  const badge = (a) => {
    const k = String(a || "").split(":")[0];
    return `<span class="badge b-${esc(k)}">${esc(a || "–")}</span>`;
  };
  const CLASS = { network: "free", egress: "hourly_no_data", database: "data", app: "stoppable", entry: "hourly_no_data" };
  const insts = (m) => Object.entries(m || {}).map(([k, v]) => `<span class="inst c-${CLASS[k] || ""}">${esc(k)}: ${esc(v)}</span>`).join("");
  const toLocalInput = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  function fail(e) { view.insertAdjacentHTML("afterbegin", `<div class="panel err">${esc(e.message || e)}</div>`); }

  // ---------------- màn hình ----------------
  function loginView() {
    view.innerHTML = `
      <div class="panel" style="max-width:380px;margin:8vh auto">
        <h2>Đăng nhập</h2>
        <label>Email</label><input id="u" type="email" style="width:100%">
        <label>Mật khẩu</label><input id="p" type="password" style="width:100%">
        <div id="np" hidden><label>Mật khẩu mới (lần đầu đăng nhập)</label><input id="p2" type="password" style="width:100%"></div>
        <p class="row"><button class="primary" id="go">Đăng nhập</button></p>
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
          document.getElementById("msg").textContent = "Đặt mật khẩu mới để tiếp tục.";
          return;
        }
        store.set("idToken", r.AuthenticationResult.IdToken);
        location.hash = "#/"; route();
      } catch (e) { document.getElementById("msg").textContent = e.message; }
    };
  }

  async function dashboard() {
    view.innerHTML = `<div class="panel"><div class="row"><h2 style="margin:0">Lease</h2><span class="sp" style="flex:1"></span>
      <a class="btn" href="#/new">+ Tạo Lease</a></div><div id="list" class="muted">Đang tải…</div></div>`;
    try {
      const r = await api("GET", "/v1/leases");
      document.getElementById("list").innerHTML = r.items.length === 0
        ? `<p class="muted">Chưa có Lease nào.</p>`
        : `<table><tr><th>Tên</th><th>Blueprint</th><th>Environment</th><th>Chế độ</th><th>Hết hạn</th></tr>${r.items.map((l) => `
          <tr><td><a href="#/lease/${esc(l.lease_id)}">${esc(l.name)}</a></td><td>${esc(l.blueprint_ref)}</td>
          <td>${l.environments.map((e) => `${esc(e.name)} ${badge(e.availability)}`).join("<br>")}</td>
          <td>${esc(l.mode)}</td><td>${fmt(l.expires_at)}</td></tr>`).join("")}</table>`;
    } catch (e) { fail(e); }
  }

  async function createView() {
    const now = new Date(); const later = new Date(now.getTime() + 30 * 864e5);
    view.innerHTML = `<div class="panel"><h2>Tạo Lease</h2>
      <div class="grid">
        <div><label>Tên Lease (chữ thường, số)</label><input id="name" placeholder="congtyb"></div>
        <div><label>Blueprint</label><select id="bp"></select></div>
        <div><label>Cỡ</label><select id="size"><option>small</option><option>medium</option></select></div>
        <div><label>Environment (cách nhau dấu phẩy)</label><input id="envs" value="dev,qa"></div>
        <div><label>Bắt đầu</label><input id="start" type="datetime-local" value="${toLocalInput(now)}"></div>
        <div><label>Hết hạn</label><input id="end" type="datetime-local" value="${toLocalInput(later)}"></div>
      </div>
      <h3>Ứng dụng (Docker image, linux/amd64)</h3>
      <div class="grid">
        <div><label>Image</label><input id="image" value="public.ecr.aws/nginx/nginx:stable" style="width:100%"></div>
        <div><label>Cổng</label><input id="port" type="number" value="80"></div>
        <div><label>Health path</label><input id="health" value="/"></div>
      </div>
      <h3>Chính sách hoạt động</h3>
      <div class="grid">
        <div><label>Chế độ</label><select id="mode"><option value="schedule">Theo lịch</option><option value="on_demand">Theo yêu cầu</option></select></div>
        <div><label>Giờ thức (giờ Việt Nam)</label><input id="from" value="08:00" size="5"> – <input id="to" value="19:00" size="5"></div>
        <div><label>Ngày (1 = thứ Hai … 7 = Chủ nhật)</label><input id="days" value="1,2,3,4,5"></div>
        <div><label>Ngủ khi rảnh sau (phút, để trống = tắt)</label><input id="idle" type="number" placeholder="ví dụ 90"></div>
      </div>
      <h3>Dữ liệu khi hết hạn</h3>
      <label><input type="checkbox" id="keep" checked> Giữ bản lưu cuối (snapshot cơ sở dữ liệu)</label>
      <p class="row"><button class="primary" id="create">Tạo</button><span id="msg" class="err"></span></p></div>`;
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
        <div class="panel"><div class="row"><h2 style="margin:0">${esc(l.name)}</h2><span class="muted">${esc(l.blueprint_ref)} · ${esc((l.parameters || {}).size)}</span>
          <span style="flex:1"></span><button class="danger" id="reclaim">Thu hồi sớm</button></div>
          <p class="muted">Hiệu lực ${fmt(l.starts_at)} → ${fmt(l.expires_at)} · chế độ <b>${esc(p.mode)}</b>
          ${p.mode === "schedule" ? `${esc((p.schedule || {}).start)}–${esc((p.schedule || {}).end)}` : ""}
          ${p.idle_timeout_minutes ? ` · ngủ khi rảnh ${esc(p.idle_timeout_minutes)} phút` : ""}
          · image <code>${esc((l.app || {}).image)}</code></p>
          <div class="row"><label style="margin:0">Gia hạn tới</label><input type="datetime-local" id="ext">
            <button id="extend">Gia hạn</button>
            <button id="switch">Đổi sang ${p.mode === "schedule" ? "theo yêu cầu" : "theo lịch"}</button></div>
        </div>
        <div class="panel"><h2>Environment</h2><table>
          <tr><th>Tên</th><th>Trạng thái</th><th>URL</th><th>Thành phần</th><th></th></tr>
          ${l.environments.map((e) => `<tr>
            <td><b>${esc(e.name)}</b><br><span class="muted">${esc(e.environment_id)}</span></td>
            <td>${badge(e.availability)}<br><span class="muted">mong muốn: ${esc(e.desired || "–")}</span>
              ${e.blocked_reason ? `<div class="err">${esc(e.blocked_reason.code)}: ${esc(String(e.blocked_reason.detail || "").slice(0, 200))}</div>` : ""}</td>
            <td><a href="${esc(e.url)}" target="_blank">mở</a>${e.app_url ? `<br><a href="${esc(e.app_url)}" target="_blank" class="muted">ứng dụng</a>` : ""}</td>
            <td>${insts(e.instances)}<br><span class="muted">quan sát ${fmt(e.observed_at)}</span></td>
            <td class="row"><button data-wake="${esc(e.environment_id)}">Thức ngay</button><button data-sleep="${esc(e.environment_id)}">Cho ngủ</button>
              <button data-ops="${esc(e.environment_id)}">Lịch sử</button></td></tr>`).join("")}
        </table><div id="ops"></div></div>
        ${cost ? `<div class="panel"><h2>Chi phí ước tính <span class="muted" style="font-size:13px">(${fmt(cost.from)} → ${fmt(cost.to)}, USD)</span></h2>
          <div class="grid"><div><div class="muted">Chạy 24/7</div><div class="kpi">${cost.totals.always_on.toFixed(2)}</div></div>
          <div><div class="muted">Chỉ stop EC2/RDS theo lịch</div><div class="kpi">${cost.totals.stop_only.toFixed(2)}</div></div>
          <div><div class="muted">InfraFlow (thực tế theo nhật ký)</div><div class="kpi">${cost.totals.infraflow.toFixed(2)}</div></div></div></div>` : ""}`;
      bind(l);
    };
    const bind = (l) => {
      view.querySelectorAll("[data-wake]").forEach((b) => (b.onclick = () => act("POST", `/v1/environments/${b.dataset.wake}/wake`, {})));
      view.querySelectorAll("[data-sleep]").forEach((b) => (b.onclick = () => act("POST", `/v1/environments/${b.dataset.sleep}/sleep`, {})));
      view.querySelectorAll("[data-ops]").forEach((b) => (b.onclick = () => showOps(b.dataset.ops)));
      document.getElementById("reclaim").onclick = () => {
        if (confirm(`Thu hồi toàn bộ Lease ${l.name}? Hạ tầng sẽ bị xóa theo chính sách dữ liệu đã chọn.`)) act("POST", `/v1/leases/${id}/reclaim`, { confirm: true });
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
        document.getElementById("ops").innerHTML = `<h3>Lịch sử thao tác: ${esc(envId)}</h3><table>
          <tr><th>Thời điểm</th><th>Thao tác</th><th>Nguồn</th><th>Kết quả</th><th>Kế hoạch</th></tr>
          ${r.items.map((o) => `<tr><td>${fmt(o.requested_at)}</td><td>${esc(o.action)} → ${esc(o.target_level || "")}</td><td>${esc(o.source)}</td>
            <td>${badge(o.status)}${o.error ? `<div class="err">${esc(o.error.code)}</div>` : ""}</td>
            <td>${o.plan ? o.plan.stages.map((s) => `<div><code>${esc(s.name)}</code> ${s.terraform ? esc(JSON.stringify(s.terraform)) : ""} ${esc(s.drivers.join(", "))}</div>`).join("") +
              (o.plan.model_check ? `<div class="muted">model check: ${o.plan.model_check.passed ? "đạt" : "không đạt"}, ${o.plan.model_check.states_explored} trạng thái</div>` : "") : ""}</td></tr>`).join("")}</table>`;
      } catch (e) { fail(e); }
    };
    await draw();
    pollTimer = setInterval(draw, 10000);
  }

  const SAMPLE = {
    ics_version: "0.1",
    blueprint: { name: "web-db-custom", version: "1.0.0", owner: "org", summary: "Ví dụ Compose" },
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
    view.innerHTML = `<div class="panel"><h2>Compose: kiểm tra một Blueprint</h2>
      <p class="muted">Kiểm tra ghép C1–C6 và model checking (mọi thứ tự xen kẽ của mọi kế hoạch chuyển mức). Thử xóa binding <code>app.db</code> hoặc thêm mức <code>shallow</code>.</p>
      <textarea id="bp" rows="18" style="width:100%;font:12px ui-monospace,monospace">${esc(JSON.stringify(SAMPLE, null, 2))}</textarea>
      <p class="row"><button class="primary" id="check">Kiểm tra</button></p><div id="out"></div></div>`;
    document.getElementById("check").onclick = async () => {
      try {
        const r = await api("POST", "/v1/blueprints/validate", JSON.parse(document.getElementById("bp").value));
        const rows = (r.composition || []).map((c) => `<tr><td>${esc(c.code)}</td><td class="err">${esc(c.message)}</td></tr>`)
          .concat((r.checks || []).map((c) => `<tr><td>${esc(c.code)}</td><td>${c.passed ? "đạt" : `<span class="err">không đạt</span>`} · ${esc(c.name)}
            ${c.detail ? `<pre class="err">${esc(c.detail.rule)}: ${esc(c.detail.message)}\n${esc((c.detail.trace || []).join("\n"))}</pre>` : ""}</td></tr>`));
        document.getElementById("out").innerHTML = `<h3>${r.passed ? "ĐẠT" : "KHÔNG ĐẠT"} ${r.states_explored ? `(${r.states_explored} trạng thái)` : ""}</h3><table>${rows.join("")}</table>`;
      } catch (e) { fail(e); }
    };
  }

  async function adminView() {
    view.innerHTML = `<div class="panel"><h2>Environment BLOCKED</h2><div id="blk">Đang tải…</div></div><div class="panel"><h2>Tài nguyên mồ côi</h2><div id="orp"></div></div>`;
    try {
      const b = await api("GET", "/v1/admin/blocked");
      document.getElementById("blk").innerHTML = b.items.length ? `<table>${b.items.map((e) => `<tr><td>${esc(e.environment_id)}</td>
        <td class="err">${esc(e.blocked_reason && e.blocked_reason.code)}: ${esc(e.blocked_reason && String(e.blocked_reason.detail).slice(0, 300))}</td>
        <td><button data-r="${esc(e.environment_id)}">Gỡ khóa (retry)</button></td></tr>`).join("")}</table>` : `<p class="muted">Không có.</p>`;
      view.querySelectorAll("[data-r]").forEach((x) => (x.onclick = async () => {
        const note = prompt("Ghi chú: đã sửa nguyên nhân gì?"); if (!note) return;
        try { await api("POST", `/v1/admin/environments/${x.dataset.r}/resolve`, { action: "retry", note }); adminView(); } catch (e) { fail(e); }
      }));
      const o = await api("GET", "/v1/admin/orphans");
      document.getElementById("orp").innerHTML = o.items.length ? `<table>${o.items.map((r) => `<tr><td><code>${esc(r.resource_arn)}</code></td><td>${esc(r.env_id_tag)}</td><td>${fmt(r.first_seen)}</td></tr>`).join("")}</table>` : `<p class="muted">Không có.</p>`;
    } catch (e) { fail(e); }
  }

  // ---------------- định tuyến ----------------
  function route() {
    clearInterval(pollTimer);
    const c = claims();
    document.getElementById("who").textContent = c ? `${c.email || ""} · ${c["custom:org_id"] || "org_default"}` : "";
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
