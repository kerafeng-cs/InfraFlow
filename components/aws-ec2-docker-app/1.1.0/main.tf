# Class stoppable: an EC2 instance in a private subnet running the tenant's Docker image.
# Sleep stops it and wake starts it (drivers). Terraform only creates and removes it.

locals {
  instance_type = {
    small  = "t3.small"
    medium = "t3.medium"
  }
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# ---------- IAM: read this Environment's configuration, plus SSM Session Manager ----------
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

resource "aws_iam_role" "app" {
  name = "${var.name_prefix}-app"
  path = "/infraflow/env/"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "read_env_params" {
  name = "read-env-params"
  role = aws_iam_role.app.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter/infraflow/env/${var.env_id}/*"
      },
      {
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = "*"
        Condition = {
          StringEquals = { "kms:ViaService" = "ssm.${data.aws_region.current.region}.amazonaws.com" }
        }
      }
    ]
  })
}

# Send and consume messages of this Environment's queue only
resource "aws_iam_role_policy" "queue" {
  count = var.queue_enabled ? 1 : 0
  name  = "queue"
  role  = aws_iam_role.app.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes", "sqs:GetQueueUrl"
      ]
      Resource = var.queue_arn
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.name_prefix}-app"
  path = "/infraflow/env/"
  role = aws_iam_role.app.name
}

# ---------- Security group ----------
resource "aws_security_group" "app" {
  name        = "${var.name_prefix}-app"
  description = "Application for ${var.name_prefix}"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-app" }
}

# Egress: pull the image (through NAT), call SSM, reach the database and the cache
resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# The rule admitting the app to the database follows the app's lifecycle, not the database's
resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  count                        = var.db_enabled ? 1 : 0
  security_group_id            = var.db_security_group_id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = var.db_port
  to_port                      = var.db_port
}

# ---------- EC2 ----------
resource "aws_instance" "app" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = local.instance_type[var.size]
  subnet_id              = var.subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.app.name

  # The container sits one network hop behind the host, so it needs a hop limit of 2
  # to reach the instance role credentials.
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 30
  }

  # The script runs on EVERY boot (systemd), so after any number of stop/start cycles
  # the instance reads the password from SSM again and restarts the container.
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    region            = data.aws_region.current.region
    app_image         = var.app_image
    app_port          = var.app_port
    env_id            = var.env_id
    db_enabled        = var.db_enabled
    db_host           = var.db_enabled ? var.db_host : ""
    db_port           = var.db_enabled ? var.db_port : 0
    db_name           = var.db_enabled ? var.db_name : ""
    db_user           = var.db_enabled ? var.db_user : ""
    db_password_param = var.db_enabled ? var.db_password_param : ""
    cache_enabled     = var.cache_enabled
    queue_enabled     = var.queue_enabled
    queue_url         = var.queue_enabled ? var.queue_url : ""
  })

  tags = { Name = "${var.name_prefix}-app" }

  lifecycle {
    # The "latest" AMI changes over time; that alone must not replace the instance (convergence).
    ignore_changes = [ami]
  }
}
