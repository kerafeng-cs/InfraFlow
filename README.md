# InfraFlow

InfraFlow puts entire non-production environments on AWS to sleep and wakes them on demand, without losing data and without breaking the environment's URL.

A typical staging environment (VPC, NAT Gateway, load balancer, application server, database) is billed around the clock but used during working hours. Stopping individual instances does not remove the hourly charges for NAT and the load balancer, and deleting resources by hand risks the database. InfraFlow treats the environment as one unit: it knows how each resource is billed, which resources depend on which, and in what order they can be removed, stopped, restored and started safely.

## How it works

| Concept | Meaning |
|---|---|
| Billing class | How a resource is billed: `free`, `stoppable` (EC2), `hourly_no_data` (NAT, ALB), `data` (RDS). The class determines what sleeping means for that resource. |
| Level | A named target for the whole environment: `awake`, `deep` (stop compute, delete hourly resources), `hibernate` (snapshot the database, delete everything billable). |
| Desired State | A pure function of the Lease (schedule, idle policy, manual overrides, expiry) and the current time. |
| Reconciliation | The controller compares Desired State with the state observed in AWS, plans the transition, model-checks the plan, and executes it. |
| Sleeping page | While asleep, the environment URL serves a static page that reports progress and lets visitors request a wake. DNS switches back to the application only after the health check passes. |

Every plan is checked before execution: all interleavings of its parallel steps are explored, and the plan is rejected if any reachable state would serve traffic on a stopped dependency, delete data without a verified snapshot, or route users to an unhealthy application. Terraform plans are then validated against the component manifests before `apply`. See [docs/architecture.md](docs/architecture.md).

## Repository layout

```
apps/demo-app/   Reference workload: Node.js and PostgreSQL, used to verify data across Sleep and Wake
components/      Terraform components with their InfraFlow manifests (component.yaml)
blueprints/      Environment blueprints composed from components, classified by category
ics/             Component standard registries and negative examples
services/        Python core: model, planner, model checker, compiler, Plan Validator,
                 controller, drivers, API; CodeBuild runner; tests
platform/        Terraform for the InfraFlow platform itself (serverless)
web/             Management console and sleeping page (static)
live/dev/        Compiled root module for a manually operated development environment
docs/            Architecture, component standard, deployment, acceptance criteria
```

## Blueprints

| Blueprint | Category | Exposure | Data | Use |
|---|---|---|---|---|
| `web-db` | web | public URL | persistent | Web application with PostgreSQL behind an ALB |
| `web-db-cache` | web | public URL | persistent | Adds a Redis cache, removed in deep sleep |
| `web-only` | web | public URL | stateless | Frontend or API preview without a database |
| `web-ecs` | web | public URL | stateless | Container on ECS Fargate behind an ALB |
| `worker-db` | worker | private | persistent | Batch or ETL jobs with PostgreSQL |
| `worker-cache` | worker | private | ephemeral | Queue consumers and test runners with Redis |
| `queue-worker` | worker | private | retained | Worker on an SQS queue whose messages wait while it sleeps |
| `postgres-sandbox` | data | private | persistent | PostgreSQL reached through SSM port forwarding |
| `search-sandbox` | data | private | ephemeral | OpenSearch domain, reindexed after each wake |
| `ml-workbench` | ml | private | persistent | NVIDIA GPU instance with a data volume snapshotted on hibernation |

Exposure, data and hourly cost are derived from the components, not declared; see [Classification](docs/component-standard.md#classification). Private environments are reached with SSM Session Manager port forwarding; see [Private environments](docs/deployment.md#7-private-environments).

## Quick start

Requirements: Python 3.12, Terraform 1.10 or later, AWS CLI v2, Node.js 22.18 or later (demo app only).

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r services/requirements-dev.txt

cd services
python -m unittest discover -s tests -t .      # unit and end-to-end tests, no AWS access
python -m infraflow.cli check                  # static, composition and model checks for the catalog
python -m infraflow.cli catalog                # classification and estimated hourly cost per blueprint
python -m infraflow.cli plan --from deep --to awake
```

Run a real environment from a workstation, without deploying the platform:

```bash
cd services
python -m infraflow.local status --dir ../live/dev/web-db-manual
python -m infraflow.local go awake --dir ../live/dev/web-db-manual
python -m infraflow.local go deep  --dir ../live/dev/web-db-manual
```

Deploying the platform and creating Leases is described in [docs/deployment.md](docs/deployment.md).

## Documentation

- [Architecture](docs/architecture.md): state model, safety properties, control loop, platform services.
- [Component standard](docs/component-standard.md): manifests, ports, registries and the checks applied to them.
- [Deployment](docs/deployment.md): platform deployment, first Lease, local operation, cost notes.
- [Acceptance criteria](docs/acceptance-criteria.md): failure scenarios and how each is handled.

## Scope

InfraFlow currently manages environments it creates itself from certified blueprints, in a single AWS account and region (`ap-southeast-1`). Registering existing environments is not supported.
