locals {
  state_machine_arn = "arn:aws:states:${local.region}:${local.account}:stateMachine:${local.p}-lifecycle"
  common_env = {
    TABLE_PREFIX = local.p
    DOMAIN       = var.domain == null ? "" : var.domain
  }
}

# ---------- Lambda ----------
resource "aws_lambda_function" "api" {
  function_name    = "${local.p}-api"
  role             = aws_iam_role.api.arn
  runtime          = "python3.12"
  handler          = "infraflow.api.handler"
  filename         = data.archive_file.code.output_path
  source_code_hash = data.archive_file.code.output_base64sha256
  timeout          = 29
  memory_size      = 512

  environment {
    variables = merge(local.common_env, {
      CONTROLLER_FUNCTION = "${local.p}-controller"
      SITE_URL            = "https://${aws_cloudfront_distribution.site.domain_name}"
      DEFAULT_ORG_ID      = var.default_org_id
    })
  }
}

resource "aws_lambda_function" "controller" {
  function_name    = "${local.p}-controller"
  role             = aws_iam_role.ops.arn
  runtime          = "python3.12"
  handler          = "infraflow.controller.handler"
  filename         = data.archive_file.code.output_path
  source_code_hash = data.archive_file.code.output_base64sha256
  timeout          = 300
  memory_size      = 512

  environment {
    variables = merge(local.common_env, {
      STATE_MACHINE_ARN = local.state_machine_arn
      CERTIFICATE_ARN   = var.certificate_arn == null ? "" : var.certificate_arn
    })
  }
}

resource "aws_lambda_function" "drivers" {
  function_name    = "${local.p}-drivers"
  role             = aws_iam_role.ops.arn
  runtime          = "python3.12"
  handler          = "infraflow.drivers.handler"
  filename         = data.archive_file.code.output_path
  source_code_hash = data.archive_file.code.output_base64sha256
  timeout          = 900
  memory_size      = 256

  environment {
    variables = merge(local.common_env, {
      HOSTED_ZONE_ID = var.hosted_zone_id == null ? "" : var.hosted_zone_id
      HTTPS          = var.certificate_arn == null ? "false" : "true"
    })
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = toset(["api", "controller", "drivers"])
  name              = "/aws/lambda/${local.p}-${each.key}"
  retention_in_days = 14
}

# ---------- Step Functions: lifecycle executor ----------
resource "aws_sfn_state_machine" "lifecycle" {
  name     = "${local.p}-lifecycle"
  role_arn = aws_iam_role.sfn.arn
  definition = templatefile("${path.module}/executor.asl.json", {
    drivers_arn       = aws_lambda_function.drivers.arn
    controller_arn    = aws_lambda_function.controller.arn
    codebuild_project = aws_codebuild_project.tf.name
  })
}

# ---------- CodeBuild: Terraform runner ----------
resource "aws_cloudwatch_log_group" "codebuild" {
  name              = "/infraflow/${local.p}/tf-runner"
  retention_in_days = 14
}

resource "aws_codebuild_project" "tf" {
  name          = "${local.p}-tf-runner"
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 60

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    type         = "LINUX_CONTAINER"

    environment_variable {
      name  = "ARTIFACT_BUCKET"
      value = aws_s3_bucket.artifacts.id
    }
    environment_variable {
      name  = "STATE_BUCKET"
      value = aws_s3_bucket.state.id
    }
    environment_variable {
      name  = "OPERATIONS_TABLE"
      value = aws_dynamodb_table.operations.name
    }
    environment_variable {
      name  = "TF_VERSION"
      value = var.terraform_version
    }
    # Changes whenever the code or components change, so CodeBuild fetches the new version
    environment_variable {
      name  = "CODE_MD5"
      value = "${data.archive_file.code.output_md5}-${data.archive_file.components.output_md5}"
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = file("${path.module}/buildspec.yml")
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.codebuild.name
    }
  }
}

# ---------- EventBridge Scheduler: reconciliation loop and orphan scanner ----------
resource "aws_scheduler_schedule" "reconcile" {
  name                = "${local.p}-reconcile"
  schedule_expression = "rate(5 minutes)"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.controller.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ mode = "all" })
  }
}

resource "aws_scheduler_schedule" "sweep" {
  name                = "${local.p}-sweep"
  schedule_expression = "rate(1 hour)"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.controller.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ mode = "sweep" })
  }
}
