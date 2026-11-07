#!/bin/bash
# Runs in CodeBuild for ONE Terraform stage of a lifecycle plan:
#   compile the root module -> init (S3 with use_lockfile) -> plan -out -> Plan Validator -> apply exactly plan.out
set -euo pipefail

WORK=/tmp/work
OUT="$WORK/env"
CODE="$WORK/code"
export PYTHONPATH="$CODE"
CLI="python3 -m infraflow.cli --catalog $CODE/infraflow/catalog.json"
ART="s3://$ARTIFACT_BUCKET/ops/$OPERATION_ID/${CODEBUILD_BUILD_NUMBER:-local}"

echo "== operation $OPERATION_ID env $ENV_ID mode $MODE allowed $ALLOWED_INSTANCES"

HASH=$($CLI compile --blueprint "$BLUEPRINT" --components-rel ../components --out "$OUT" --providers \
  --region "$AWS_REGION" --env-id "$ENV_ID" --lease-id "$LEASE_ID" --org-id "$ORG_ID" \
  --state-bucket "$STATE_BUCKET" --state-key "$TF_STATE_KEY")
echo "compiled_hash $HASH"
printf '%s' "$TF_VARS_JSON" > "$OUT/stage.auto.tfvars.json"

cd "$OUT"
terraform init -input=false -no-color
if [ "$MODE" = "destroy" ]; then
  terraform plan -destroy -input=false -no-color -out=plan.out
else
  terraform plan -input=false -no-color -out=plan.out
fi
terraform show -json plan.out > plan.json

# Snapshots taken by THIS operation (recorded in DynamoDB by the driver), for Validator rule V3
SNAPS=$(aws dynamodb get-item --table-name "$OPERATIONS_TABLE" \
  --key "{\"operation_id\":{\"S\":\"$OPERATION_ID\"}}" --query 'Item.snapshots.M' --output json || echo null)
SNAP_INSTANCES=$(python3 -c 'import json,sys; d=json.loads(sys.argv[1] or "null") or {}; print(json.dumps(sorted(d)))' "$SNAPS")

EXTRA=()
[ "${ALLOW_DATA_LOSS:-false}" = "true" ] && EXTRA+=(--allow-data-loss)
[ "$MODE" != "destroy" ] && EXTRA+=(--expected-hash "$HASH")

set +e
$CLI validate-plan plan.json --blueprint "$BLUEPRINT" --env-id "$ENV_ID" \
  --allowed "$ALLOWED_INSTANCES" --snapshots "$SNAP_INSTANCES" "${EXTRA[@]}" > validation.json
RC=$?
set -e
cat validation.json
aws s3 cp plan.json "$ART/plan.json" --only-show-errors || true
aws s3 cp validation.json "$ART/validation.json" --only-show-errors || true
if [ $RC -ne 0 ]; then
  echo "PLAN_UNSAFE: rejected by the Plan Validator; not applying."
  exit 3
fi

terraform apply -input=false -no-color plan.out
terraform output -json > outputs.json || echo '{}' > outputs.json
aws s3 cp outputs.json "$ART/outputs.json" --only-show-errors || true
echo "== done"
