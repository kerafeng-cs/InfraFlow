data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ---------- API: reads and writes control data and invokes the controller. NO infrastructure permissions. ----------
resource "aws_iam_role" "api" {
  name               = "${local.p}-api"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "api_logs" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "api" {
  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan"], Resource = local.table_access },
      { Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.controller.arn },
    ]
  })
}

# ---------- Controller and drivers: observe and act on resources tagged by InfraFlow ----------
resource "aws_iam_role" "ops" {
  name               = "${local.p}-ops"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "ops_logs" {
  role       = aws_iam_role.ops.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "ops" {
  role = aws_iam_role.ops.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan"], Resource = local.table_access },
      { Effect = "Allow", Action = ["states:StartExecution"], Resource = local.state_machine_arn },
      { Effect = "Allow", Action = ["states:DescribeExecution"], Resource = "arn:aws:states:${local.region}:${local.account}:execution:${local.p}-lifecycle:*" },
      {
        Effect = "Allow"
        Action = ["ec2:DescribeVpcs", "ec2:DescribeNatGateways", "ec2:DescribeInstances", "ec2:DescribeInstanceStatus",
          "rds:DescribeDBInstances", "rds:DescribeDBSnapshots", "elasticloadbalancing:Describe*",
        "tag:GetResources", "cloudwatch:GetMetricStatistics"]
        Resource = "*"
      },
      # Start, stop and snapshot only resources managed by InfraFlow
      {
        Effect    = "Allow"
        Action    = ["ec2:StartInstances", "ec2:StopInstances"]
        Resource  = "*"
        Condition = { StringEquals = { "aws:ResourceTag/infraflow:managed" = "true" } }
      },
      {
        Effect    = "Allow"
        Action    = ["rds:StartDBInstance", "rds:StopDBInstance", "rds:CreateDBSnapshot"]
        Resource  = "*"
        Condition = { StringEquals = { "aws:ResourceTag/infraflow:managed" = "true" } }
      },
      { Effect = "Allow", Action = ["rds:CreateDBSnapshot", "rds:AddTagsToResource"], Resource = "arn:aws:rds:${local.region}:${local.account}:snapshot:*" },
      ], var.hosted_zone_id == null ? [] : [
      { Effect = "Allow", Action = ["route53:ChangeResourceRecordSets", "route53:ListResourceRecordSets"], Resource = "arn:aws:route53:::hostedzone/${var.hosted_zone_id}" },
    ])
  })
}

# ---------- Step Functions executor ----------
resource "aws_iam_role" "sfn" {
  name = "${local.p}-executor"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "states.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "sfn" {
  role = aws_iam_role.sfn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "lambda:InvokeFunction", Resource = [aws_lambda_function.drivers.arn, aws_lambda_function.controller.arn] },
      { Effect = "Allow", Action = ["codebuild:StartBuild", "codebuild:StopBuild", "codebuild:BatchGetBuilds"], Resource = aws_codebuild_project.tf.arn },
      {
        Effect   = "Allow"
        Action   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
        Resource = "arn:aws:events:${local.region}:${local.account}:rule/StepFunctionsGetEventForCodeBuildStartBuildRule"
      },
    ]
  })
}

# ---------- CodeBuild: runs Terraform for Environments (trusted runner) ----------
resource "aws_iam_role" "codebuild" {
  name = "${local.p}-tf-runner"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "codebuild.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "codebuild" {
  role = aws_iam_role.codebuild.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "*" },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"], Resource = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*", aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"] },
      { Effect = "Allow", Action = ["dynamodb:GetItem"], Resource = aws_dynamodb_table.operations.arn },
      # Resource types from the Resource Type Registry (ics/registry.yaml), limited to the region
      {
        Effect    = "Allow"
        Action    = ["ec2:*", "elasticloadbalancing:*", "rds:*", "ssm:GetParameter", "ssm:GetParameters", "ssm:PutParameter", "ssm:DeleteParameter", "ssm:DescribeParameters", "ssm:AddTagsToResource", "ssm:ListTagsForResource", "ssm:RemoveTagsFromResource", "kms:Decrypt"]
        Resource  = "*"
        Condition = { StringEquals = { "aws:RequestedRegion" = local.region } }
      },
      # IAM only under path /infraflow/env/ (the app role and instance profile)
      {
        Effect   = "Allow"
        Action   = ["iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole", "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListInstanceProfilesForRole", "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile", "iam:GetInstanceProfile", "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile", "iam:TagInstanceProfile", "iam:PassRole"]
        Resource = ["arn:aws:iam::${local.account}:role/infraflow/env/*", "arn:aws:iam::${local.account}:instance-profile/infraflow/env/*"]
      },
      { Effect = "Allow", Action = ["iam:CreateServiceLinkedRole"], Resource = "*", Condition = { StringLike = { "iam:AWSServiceName" = ["elasticloadbalancing.amazonaws.com", "rds.amazonaws.com"] } } },
    ]
  })
}

# ---------- EventBridge Scheduler invokes the controller ----------
resource "aws_iam_role" "scheduler" {
  name = "${local.p}-scheduler"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "scheduler.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.controller.arn }]
  })
}
