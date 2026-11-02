// Sleeping page: chỉ dùng API công khai (IC mục 7). Không có quyền nào ngoài yêu cầu đánh thức.
(function () {
  const cfg = window.INFRAFLOW || {};
  const host = new URLSearchParams(location.search).get("host") || location.hostname.split(".")[0];
  const $ = (id) => document.getElementById(id);
  let timer = null;

  async function status() {
    const r = await fetch(`${cfg.apiUrl}/v1/public/status?host=${encodeURIComponent(host)}`);
    const b = await r.json();
    if (!r.ok) { $("state").textContent = b.error ? b.error.message : "Không tải được trạng thái"; $("wake").hidden = true; return; }
    $("title").textContent = `${b.lease_name} / ${b.environment_name}`;
    const label = { AWAKE: "Đang thức", WAKING: "Đang thức dậy…", SLEEPING: "Đang đi ngủ…", BLOCKED: "Tạm khóa, cần quản trị viên xử lý",
                    PREPARED: "Đang ngủ", REQUESTED: "Đang chuẩn bị" }[b.availability] || (b.availability.startsWith("ASLEEP") ? "Đang ngủ" : b.availability);
    $("state").textContent = label;
    $("wake").hidden = !b.can_wake;
    $("steps").innerHTML = b.progress ? b.progress.stages.map((s) => `<li>${s}</li>`).join("") : "";
    $("note").textContent = b.availability === "WAKING" ? "Thường mất 5–15 phút. Trang sẽ tự chuyển khi ứng dụng sẵn sàng." : "";
    if (b.availability === "AWAKE" && b.app_url) { location.href = b.app_url; return; }
    clearTimeout(timer);
    timer = setTimeout(status, b.availability === "WAKING" || b.availability === "SLEEPING" ? 5000 : 20000);
  }

  $("wake").onclick = async () => {
    $("wake").disabled = true;
    const r = await fetch(`${cfg.apiUrl}/v1/public/wake`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ host }) });
    if (!r.ok) { const b = await r.json(); $("note").textContent = b.error ? b.error.message : "Lỗi"; }
    $("wake").disabled = false;
    status();
  };
  status();
})();
