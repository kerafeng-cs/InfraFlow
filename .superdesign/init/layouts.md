# Layouts

`web/index.html` is the management shell: brand, navigation, account, and main region. `web/sleep.html` is the separate public shell.

## Management shell — web/index.html

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#10233e">
  <title>InfraFlow</title>
  <link rel="stylesheet" href="style.css">
  <script src="config.js"></script>
</head>
<body>
  <a class="skip-link" href="#view">Skip to main content</a>
  <header class="app-header">
    <a class="brand" href="#/" aria-label="InfraFlow home"><span class="brand-mark" aria-hidden="true">I</span>InfraFlow</a>
    <nav class="primary-nav" aria-label="Primary navigation" hidden><a href="#/">Environments</a><a href="#/leases">Leases</a><a href="#/new">Create Lease</a><a href="#/compose">Blueprint check</a><a href="#/admin">Admin</a></nav>
    <div class="header-user"><span id="who" class="muted"></span><button id="logout" hidden>Sign out</button></div>
  </header>
  <main id="view"></main>
  <script src="app.js"></script>
</body>
</html>

```

## Public shell — web/sleep.html

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#f6f8fb">
  <title>Environment asleep</title>
  <link rel="stylesheet" href="style.css">
  <script src="config.js"></script>
</head>
<body>
  <main class="sleep-page">
    <div class="panel sleep-panel">
      <span class="sleep-icon" aria-hidden="true">↗</span>
      <p class="eyebrow">InfraFlow · environment access</p>
      <h1 id="title" class="page-title">Environment</h1>
      <p id="state" role="status" aria-live="polite">Loading status…</p>
      <button id="wake" class="primary" hidden>Wake up</button>
      <ol id="steps" class="sleep-steps" aria-label="Wake progress"></ol>
      <p id="note" class="muted" role="status" aria-live="polite"></p>
    </div>
  </main>
  <script src="sleep.js"></script>
</body>
</html>

```
