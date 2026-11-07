# Deployment

All commands assume a POSIX shell (Linux, macOS or WSL), an AWS CLI profile named `infraflow` with credentials for an IAM user (never the root user), and region `ap-southeast-1`.

## 1. Development setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r services/requirements-dev.txt
cd services && python -m unittest discover -s tests -t .
```

After changing a component or blueprint, regenerate the catalog bundle and the compiled development root module, and commit both:

```bash
cd services
python -m infraflow.cli check
python -m infraflow.cli bundle
python -m infraflow.cli compile --components-rel ../../../components --out ../live/dev/web-db-manual --levels
```

Run `terraform fmt -recursive components platform` before committing. Do not format `live/`; its `main.tf` is compiler output and is compared byte for byte by a test.

## 2. Demo application image

The default workload is `ghcr.io/kerafeng-cs/infraflow-demo-app:1`, built from `apps/demo-app` by the `demo-app` workflow on every push to `main` that changes that directory. Instances pull it anonymously, so the GHCR package must be public (package settings, Change visibility). A Lease can use any other image that follows the [workload contract](../apps/demo-app/README.md#contract).

## 3. Operating an environment without the platform

`live/dev/web-db-manual` is a compiled root module with local state. The local executor runs the same planner, model checker, Plan Validator and drivers as the platform, with Terraform as a subprocess.

```bash
cd live/dev/web-db-manual && terraform init && cd ../../../services
python -m infraflow.local status --dir ../live/dev/web-db-manual
python -m infraflow.local go awake --dir ../live/dev/web-db-manual   # 10 to 20 minutes; prints the application URL
python -m infraflow.local go deep  --dir ../live/dev/web-db-manual
```

Each `go` observes AWS, plans, model-checks, and then for each stage runs `terraform plan -out`, the Plan Validator, `terraform apply plan.out` and the drivers. Return the environment to `deep` at the end of every session; NAT Gateway and the load balancer are billed per hour.

## 4. Platform

```bash
cd platform
terraform init
terraform apply          # about 5 minutes; prints site_url, api_url, user_pool_id
```

Optional variables: `domain`, `hosted_zone_id` and `certificate_arn` (a wildcard ACM certificate in `ap-southeast-1`) give every Environment a stable `https://<env>.<domain>` URL. Without them, the Environment URL is the sleeping page on CloudFront, which redirects to the load balancer address while the Environment is awake.

The first apply keeps platform state locally. To move it to the created bucket, add an `s3` backend using the `state_bucket` output with `use_lockfile = true` and run `terraform init -migrate-state`.

Create the first user:

```bash
POOL=$(terraform output -raw user_pool_id)
aws cognito-idp admin-create-user --profile infraflow --user-pool-id "$POOL" \
  --username admin@example.com \
  --user-attributes Name=email,Value=admin@example.com Name=email_verified,Value=true Name=custom:org_id,Value=org_example \
  --temporary-password '<temporary password>'
aws cognito-idp admin-add-user-to-group --profile infraflow --user-pool-id "$POOL" \
  --username admin@example.com --group-name infraflow_admins
```

Open `site_url`, sign in, set a new password, and create a Lease. Keep Lease and Environment names short (for example `acme` and `qa`): resource names derive from them and an ALB name is limited to 32 characters.

## 5. Cost

The platform is serverless and costs close to nothing while no Environment is awake. By the unit-price estimates in `services/infraflow/cost.py`, a small `web-db` Environment costs about 0.16 USD per hour awake and under 0.01 USD per hour in `deep` (storage only). The console shows, for each Lease, the estimated cost of running always on, of stopping only EC2 and RDS on the schedule, and of the transitions InfraFlow actually performed. Actual cost is available in Cost Explorer filtered by the `infraflow:env_id` tag.

## 6. Security rules

- Never commit `terraform.tfstate`, plan files or `.env` files; the database password is in the state.
- Do not create access keys for the root user. If a key leaks, deactivate it, delete it, and create a new one.
- The API role has no infrastructure permissions. The controller and drivers can start, stop and snapshot only resources tagged `infraflow:managed=true`. CodeBuild is limited to the Registry resource types in the platform region, and to IAM entities under the `/infraflow/env/` path.
