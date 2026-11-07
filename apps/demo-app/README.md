# InfraFlow demo app

Reference workload for the `web-db` blueprint. It replaces the placeholder nginx image so that a Sleep and Wake cycle can be verified end to end: notes written before the environment sleeps must still be present after it wakes, and every process start is recorded as a boot.

## Contract

The application follows the `workload.container/v1` contract used by the `aws-ec2-docker-app` component.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `PORT` | no | `8080` | HTTP listen port |
| `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | yes | | PostgreSQL connection |
| `DB_PORT` | no | `5432` | PostgreSQL port |
| `DB_SSL_MODE` | no | `verify-full` if `DB_CA_FILE` exists, else `require` | `verify-full`, `require` or `disable` |
| `DB_CA_FILE` | no | `/etc/ssl/certs/rds-global-bundle.pem` | CA bundle for `verify-full` |
| `INFRAFLOW_ENV_ID` | no | `local` | Environment identifier shown on the page |

## Endpoints

| Method and path | Response |
|---|---|
| `GET /` | HTML page: notes, runtime information, recent boots |
| `POST /notes` | Form submission; redirects to `/` |
| `GET /api/notes`, `POST /api/notes` | JSON list and create (`{"body": "..."}`) |
| `GET /api/status` | JSON runtime summary |
| `GET /healthz` | `200` when the schema is applied and the database answers within 2 s, otherwise `503` |

The load balancer health check targets `/healthz`. Because it includes a database round trip, a target is reported healthy only when the whole request path works, which is the condition the Wake operation waits for before switching DNS to the application.

## Development

Requires Node.js 22.18 or later (TypeScript is executed directly through type stripping).

```bash
npm install
npm test            # unit tests, no database needed
npm run typecheck
docker compose up --build   # application on http://localhost:8080 with a local PostgreSQL
```

## Image

`.github/workflows/demo-app.yml` builds the image and publishes it to `ghcr.io/<owner>/infraflow-demo-app` on every push to `main` that changes this directory. The package must be public, or the instances need registry credentials, because the instances pull it anonymously.
