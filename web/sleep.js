// Sleeping page. Uses the public API only; the only action it can request is a wake.
(function ()
{
  "use strict";

  const cfg = window.INFRAFLOW || {};
  const host = new URLSearchParams(location.search).get("host") || location.hostname.split(".")[0];
  const $ = (id) => document.getElementById(id);
  let timer = null;

  const STATES = {
    AWAKE: ["Awake", "ok", "The application is ready. Redirecting."],
    WAKING: ["Waking up", "changing", "This usually takes 10 to 20 minutes. The page redirects when the application passes its health check."],
    SLEEPING: ["Going to sleep", "changing", "The environment is going to sleep. It can be woken again once this finishes."],
    PREPARED: ["Asleep", "sleep", "The environment is asleep. Wake it to use the application."],
    BLOCKED: ["Unavailable", "danger", "The environment needs attention from an administrator."],
    REQUESTED: ["Preparing", "changing", "The environment is being prepared."],
  };

  function describe(availability)
  {
    if (STATES[availability])
    {
      return STATES[availability];
    }
    if (String(availability).startsWith("ASLEEP"))
    {
      return ["Asleep", "sleep", "The environment is asleep. Wake it to use the application."];
    }
    return [availability || "Unknown", "neutral", ""];
  }

  function show(text, tone, message)
  {
    const node = $("state");
    node.textContent = text;
    node.className = `pill tone-${tone}`;
    $("message").textContent = message;
  }

  function later(ms)
  {
    clearTimeout(timer);
    timer = setTimeout(status, ms);
  }

  async function status()
  {
    let response;
    let body;
    try
    {
      response = await fetch(`${cfg.apiUrl}/v1/public/status?host=${encodeURIComponent(host)}`);
      body = await response.json();
    }
    catch (e)
    {
      show("Unavailable", "neutral", "The status service could not be reached. Retrying.");
      $("wake").hidden = true;
      later(20000);
      return;
    }
    if (!response.ok)
    {
      show("Not found", "neutral", (body.error && body.error.message) || "This environment does not exist or has expired.");
      $("wake").hidden = true;
      return;
    }
    $("title").textContent = `${body.lease_name} / ${body.environment_name}`;
    document.title = `${body.environment_name} - InfraFlow`;
    const [text, tone, message] = describe(body.availability);
    show(text, tone, message);
    $("wake").hidden = !body.can_wake;
    const stages = (body.progress && body.progress.stages) || [];
    $("steps").hidden = !stages.length;
    $("steps").replaceChildren(...stages.map((s) =>
    {
      const li = document.createElement("li");
      li.textContent = s;
      return li;
    }));
    if (body.availability === "AWAKE" && body.app_url)
    {
      location.replace(body.app_url);
      return;
    }
    later(body.availability === "WAKING" || body.availability === "SLEEPING" ? 5000 : 20000);
  }

  $("wake").onclick = async () =>
  {
    const button = $("wake");
    button.disabled = true;
    $("note").textContent = "";
    try
    {
      const response = await fetch(`${cfg.apiUrl}/v1/public/wake`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ host }),
      });
      if (!response.ok)
      {
        const body = await response.json().catch(() => ({}));
        $("note").textContent = (body.error && body.error.message) || "The wake request was not accepted.";
      }
    }
    catch (e)
    {
      $("note").textContent = "The request could not be sent. Check your connection and try again.";
    }
    button.disabled = false;
    status();
  };

  status();
})();
