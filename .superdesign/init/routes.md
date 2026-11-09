# Routes

Hash router in `web/app.js`:

- `#/`: Environments overview, `environmentsView`
- `#/leases`: Lease list, `dashboard`
- `#/lease/{id}`: Lease detail, `leaseView`
- `#/environment/{id}`: Environment detail, `environmentView`
- `#/new`: Create Lease, `createView`
- `#/compose`: Blueprint checker, `composeView`
- `#/admin`: Admin Workbench, `adminView`
- `sleep.html?host={host}`: Public Wake surface, `web/sleep.js`

## Full router source — web/app.js

```javascript
  // ---------------- routing ----------------
  function route() {
    clearInterval(pollTimer);
    const c = claims();
    document.body.classList.toggle("signed-out", !c);
    document.getElementById("who").textContent = c ? `${c.email || ""} (${c["custom:org_id"] || "org_default"})` : "";
    document.getElementById("logout").hidden = !c;
    document.querySelector(".primary-nav").hidden = !c;
    if (!c) { document.title = "Sign in · InfraFlow"; return loginView(); }
    const h = location.hash || "#/";
    document.querySelectorAll(".primary-nav a").forEach((a) => {
      const selected = h === a.getAttribute("href") || (h.startsWith("#/?") && a.getAttribute("href") === "#/") || (h.startsWith("#/lease/") && a.getAttribute("href") === "#/leases") || (h.startsWith("#/environment/") && a.getAttribute("href") === "#/");
      if (selected) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.title = h.startsWith("#/lease/") ? "Lease · InfraFlow" : h.startsWith("#/environment/") ? "Environment · InfraFlow" : `${h === "#/new" ? "Create Lease" : h === "#/admin" ? "Admin" : h === "#/compose" ? "Blueprint check" : h === "#/leases" ? "Leases" : "Environments"} · InfraFlow`;
    let m;
    if (h === "#/new") return createView();
    if (h === "#/leases") return dashboard();
    if (h === "#/compose") return composeView();
    if (h === "#/admin") return adminView();
    if ((m = h.match(/^#\/environment\/(.+)$/))) return environmentView(decodeURIComponent(m[1]));
    if ((m = h.match(/^#\/lease\/(.+)$/))) return leaseView(m[1]);
    return environmentsView();
  }
  document.getElementById("logout").onclick = () => { store.clear(); route(); };
  window.addEventListener("hashchange", route);
  route();
})();
```
