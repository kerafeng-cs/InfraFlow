# Extractable components

Current app has no component module boundary; these are extractable design patterns only.

## AppRail
- Source: `web/index.html`, `web/style.css`
- Category: layout
- Props: active route, signed-in user, navigation visibility
- Hardcoded: InfraFlow text mark, navigation labels

## PageHeader
- Source: `web/app.js`, `.page-intro` in `web/style.css`
- Category: basic
- Props: title, summary, breadcrumb

## StatusBadge
- Source: `badge` in `web/app.js`, `.badge` in `web/style.css`
- Category: basic
- Props: status value

## StatusAxis
- Source: `environmentView` in `web/app.js`, `.state-grid` in `web/style.css`
- Category: basic
- Props: label, value, source, observed time

## EnvironmentRow
- Source: `environmentsView` and `leaseView` in `web/app.js`
- Category: basic
- Props: environment, lease, detail URL

## ReviewBox
- Source: `createView` and `leaseView` in `web/app.js`, `.review-box` in `web/style.css`
- Category: basic
- Props: content, confirmation state
