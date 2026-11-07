# InfraFlow Component Standard (ICS) v0.1

ICS defines how infrastructure is packaged so that InfraFlow can put it to sleep safely. A **component** is a Terraform module plus a manifest (`component.yaml`) that declares how the module is billed, what it provides and requires, and how each lifecycle action is performed. A **blueprint** composes components into an environment.

InfraFlow does not generate resource logic. The compiler only generates deterministic wiring between certified components, and every transition is executed by Terraform and by a closed set of drivers.

## Registries

`ics/registry.yaml` holds three closed registries. Extending any of them requires a new version of the standard.

| Registry | Content |
|---|---|
| Port types | Typed interfaces and their attributes, for example `db.postgres/v1: [host, port, name, user, password_param, security_group_id]`. |
| Resource types | Every Terraform resource type a component may contain, with the billing class it forces (`aws_nat_gateway` forces `hourly_no_data`, `aws_db_instance` forces `data`). |
| Drivers | The AWS actions InfraFlow implements: describe, start, stop, snapshot, health checks, DNS. Components cannot add drivers. |

It also maps each billing class to its valid states:

| Class | States |
|---|---|
| `free` | ABSENT, PRESENT |
| `stoppable` | ABSENT, RUNNING, STOPPED |
| `hourly_no_data` | ABSENT, PRESENT |
| `data` | ABSENT, RUNNING, STOPPED, SNAPSHOTTED |

## Component manifest

Abbreviated from `components/aws-ec2-docker-app/1.0.0/component.yaml`:

```yaml
component:
  name: aws-ec2-docker-app
  version: 1.0.0
  billing_class: stoppable
  data_class: none
  resource_types: [aws_instance, aws_security_group, ...]
  primary_resource: aws_instance.app
  system_inputs: [name_prefix, env_id]
provides:
  - port: http
    type: http.backend/v1
    attributes: { instance_id: instance_id, port: port, health_path: health_path, security_group_id: security_group_id }
requires:
  - port: egress
    type: net.egress/v1
    when: serving          # needs NAT to pull the image, reads no values from it
  - port: db
    type: db.postgres/v1
    when: serving
    inputs: { host: db_host, port: db_port, ... }
outputs:
  instance_id: { stable: true }
lifecycle:
  presence_variable: present
  actions:
    observe: { driver: ec2_instance.describe }
    start:   { driver: ec2_instance.start }
    stop:    { driver: ec2_instance.stop }
  levels: { awake: RUNNING, shallow: STOPPED, deep: STOPPED, hibernate: ABSENT }
  serving_states: [RUNNING]
```

| Field | Meaning |
|---|---|
| `billing_class` | One of the four classes. Must agree with the resource types (S5). |
| `data_class`, `data_resource_types` | Whether the component holds data, and which resources hold it. Data resources are protected by A4, V3 and V4. |
| `resource_types` | Exhaustive list of resource types in the module (S4). |
| `system_inputs` | Platform variables the module receives: `name_prefix`, `env_id`, `certificate_arn`. |
| `provides[].attributes` | Maps each attribute of the port type to a module output. |
| `requires[].when` | `present`: the dependency must exist while this component exists. `serving`: the dependency must serve while this component serves. |
| `requires[].inputs` | Maps port attributes to module variables. Reading inputs from a provider also implies a `present` dependency on it. |
| `outputs[].stable` | Whether the value survives Sleep and Wake. Driver targets must be stable outputs. |
| `lifecycle.presence_variable` | The boolean variable that creates or removes the component. |
| `lifecycle.restore_variable` | For `data` components that support SNAPSHOTTED: the variable that restores from a snapshot. |
| `lifecycle.levels` | The component state at each level. |
| `lifecycle.serving_states` | States in which the component serves. |

## Blueprint

```yaml
instances:
  network:  { component: aws-network-basic@1.0.0 }
  database: { component: aws-rds-postgres@1.0.0, parameters: { size: "${param.size}" } }
  app:      { component: aws-ec2-docker-app@1.0.0, parameters: { size: "${param.size}" } }
  ...
bindings:
  - { from: app.db,        to: database.db }      # requires side -> provides side
  - { from: app.workload,  to: sys.lease_app }    # application settings from the Lease
  - { from: sys.dns,       to: entry.public }     # the environment URL
supported_levels: [awake, deep, hibernate]
```

Two system ports exist: `sys.lease_app` provides `workload.container/v1` (image, port, health path) from the Lease, and `sys.dns` requires the `http.public/v1` port that the environment URL points to.

## Checks

### Static component checks

| Check | Statement |
|---|---|
| S1 | The manifest has every required field, a valid name, a semantic version and a known billing class. |
| S4 | The resource types in the Terraform source equal the declared `resource_types`. |
| S5 | Every resource type is in the Registry; a type that forces a billing class matches the component's class; data-holding types are declared with a data class. |
| S6 | Every level uses a state valid for the class; the `awake` state is a serving state; the required drivers and `restore_variable` are declared. |
| S7 | Port types exist, mapped attributes belong to the port type, `when` is `present` or `serving`, and driver targets are stable outputs. |
| F | The source contains no `provider` block and no module from an external source. |

S2 (Terraform `validate` on the module) runs in CI. S8 (conformance tests against a real account) is not automated.

### Composition checks

| Check | Statement |
|---|---|
| C1 | Every binding refers to existing instances and ports; every required port has exactly one binding. |
| C2 | Bound ports have the same type; `sys.dns` binds to `http.public/v1`. |
| C3 | The dependency graph is acyclic. |
| C4 | Exactly one binding targets `sys.dns`. |
| C5 | Every referenced component exists in the catalog. |
| C6 | Every instance supports every level the blueprint declares. |

### Model checks

C7, C8 and RESCUE are described in [architecture.md](architecture.md#model-checking). They run in CI for every blueprint in the catalog and synchronously when a blueprint is submitted to `POST /v1/blueprints/validate`.

## Compiler

`python -m infraflow.cli compile` turns a blueprint into a Terraform root module:

- each instance becomes `module "<instance>"` with `count = var.<instance>_present ? 1 : 0`;
- module inputs are wired from provider outputs according to the bindings;
- `<instance>_present` variables have no default, so a missing value fails instead of removing infrastructure;
- the output `compiled_hash` identifies the compiler version, catalog and blueprint, and is checked by V9.

The output is byte-for-byte deterministic; `services/tests/test_ics.py` compares it with `live/dev/web-db-manual/main.tf`.

## Writing a component

1. Write the Terraform module without `provider` blocks, using only Registry resource types. Set only the `Name` tag; ownership tags (`infraflow:managed`, `infraflow:env_id`, `infraflow:lease_id`, `infraflow:org_id`) come from the provider's `default_tags`.
2. Name resources `${var.name_prefix}-<suffix>` so drivers can locate them.
3. Declare the manifest. Put security group rules that admit a client into the client's component, so that the rule follows the client's lifecycle and no dependency cycle appears.
4. Run `python -m infraflow.cli check` and `python -m infraflow.cli bundle`, then commit the regenerated `services/infraflow/catalog.json`.
