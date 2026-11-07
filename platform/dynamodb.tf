# Control data. PAY_PER_REQUEST costs almost nothing when idle.

resource "aws_dynamodb_table" "leases" {
  name         = "${local.p}-leases"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "lease_id"

  attribute {
    name = "lease_id"
    type = "S"
  }
  attribute {
    name = "org_id"
    type = "S"
  }
  global_secondary_index {
    name            = "org_id"
    hash_key        = "org_id"
    projection_type = "ALL"
  }
  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "environments" {
  name         = "${local.p}-environments"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "environment_id"

  attribute {
    name = "environment_id"
    type = "S"
  }
  attribute {
    name = "lease_id"
    type = "S"
  }
  attribute {
    name = "host"
    type = "S"
  }
  global_secondary_index {
    name            = "lease_id"
    hash_key        = "lease_id"
    projection_type = "ALL"
  }
  global_secondary_index {
    name            = "host"
    hash_key        = "host"
    projection_type = "ALL"
  }
  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "operations" {
  name         = "${local.p}-operations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "operation_id"

  attribute {
    name = "operation_id"
    type = "S"
  }
  attribute {
    name = "environment_id"
    type = "S"
  }
  attribute {
    name = "requested_at"
    type = "S"
  }
  global_secondary_index {
    name            = "environment_id"
    hash_key        = "environment_id"
    range_key       = "requested_at"
    projection_type = "ALL"
  }
}

resource "aws_dynamodb_table" "state_log" {
  name         = "${local.p}-state-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "environment_id"
  range_key    = "at_instance"

  attribute {
    name = "environment_id"
    type = "S"
  }
  attribute {
    name = "at_instance"
    type = "S"
  }
}

resource "aws_dynamodb_table" "idempotency" {
  name         = "${local.p}-idempotency"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "scope_key"

  attribute {
    name = "scope_key"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_dynamodb_table" "orphans" {
  name         = "${local.p}-orphans"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "resource_arn"

  attribute {
    name = "resource_arn"
    type = "S"
  }
}

locals {
  tables = [
    aws_dynamodb_table.leases.arn, aws_dynamodb_table.environments.arn, aws_dynamodb_table.operations.arn,
    aws_dynamodb_table.state_log.arn, aws_dynamodb_table.idempotency.arn, aws_dynamodb_table.orphans.arn,
  ]
  table_access = concat(local.tables, [for t in local.tables : "${t}/index/*"])
}
