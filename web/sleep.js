// Sleeping page. Uses the public API only; the only permitted action is a wake request.
(function () {
  const cfg = window.INFRAFLOW || {};
  const host = new URLSearchParams(location.search).get("host") || location.hostname.split(".")[0];
  const $ = (id) => document.getElementById(id);
  let timer = null;

  async function status() {
    try {
    const r = await fetch(`${cfg.apiUrl}/v1/public/status?host=${encodeURIComponent(host)}`);
    const b = await r.json();
    if (!r.ok) { $("state").textContent = b.error ? b.error.message : "Could not load the status"; $("wake").hidden = true; clearTimeout(timer); timer = setTimeout(status, 20000); return; }
    $("title").textContent = `${b.lease_name} / ${b.environment_name}`;
    const label = { AWAKE: "Awake", WAKING: "Waking up...", SLEEPING: "Going to sleep...", BLOCKED: "Blocked; an administrator must resolve it",
                    PREPARED: "Asleep", REQUESTED: "Preparing" }[b.availability] || (b.availability.startsWith("ASLEEP") ? "Asleep" : b.availability);
    $("state").textContent = label;
    $("wake").hidden = !b.can_wake;
    $("steps").replaceChildren(...(b.progress ? b.progress.stages : []).map((s) => { const li = document.createElement("li"); li.textContent = s; return li; }));
    $("note").textContent = b.availability === "WAKING" ? "Wake is in progress. This page will redirect after the application is verified ready." : "";
    if (b.availability === "AWAKE" && b.app_url) { location.href = b.app_url; return; }
    clearTimeout(timer);
    timer = setTimeout(status, b.availability === "WAKING" || b.availability === "SLEEPING" ? 5000 : 20000);
    } catch (e) { $("state").textContent = "Status is temporarily unavailable."; $("wake").hidden = true; clearTimeout(timer); timer = setTimeout(status, 20000); }
  }

  $("wake").onclick = async () => {
    $("wake").disabled = true;
    try {
      const r = await fetch(`${cfg.apiUrl}/v1/public/wake`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ host }) });
      if (!r.ok) { const b = await r.json(); $("note").textContent = b.error ? b.error.message : "Wake request was not accepted."; }
      else $("note").textContent = "Wake request received. Checking progress…";
    } catch (e) { $("note").textContent = "Could not send the request. Check your connection and try again."; }
    finally { $("wake").disabled = false; status(); }
  };
  status();
})();
