# Page dependencies

Every management route uses `web/index.html` → `web/style.css`, `web/config.js` (runtime generated), `web/app.js`. Route render functions are in the app.js file rather than imported components.

- `#/` Environments: `environmentsView` → API helper, badge, fmt.
- `#/leases` Leases: `dashboard` → API helper, badge, fmt.
- `#/lease/{id}` Lease: `leaseView` → API helper, badge, fmt, insts.
- `#/environment/{id}` Environment: `environmentView` → API helper, badge, fmt.
- `#/new` Create: `createView` → API helper, fmt, toLocalInput.
- `#/compose` Blueprint: `composeView` → API helper.
- `#/admin` Admin: `adminView` → API helper, fmt.
- `sleep.html` Public Wake: `web/sleep.html` → `web/style.css`, `web/config.js`, `web/sleep.js`.

No image or font asset is used. Current brand mark is a styled letter I, not an official uploaded logo.
