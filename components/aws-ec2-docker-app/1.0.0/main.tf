# Lớp stoppable: EC2 chạy Docker image của khách ở private subnet.
# Ngủ = stop (driver), thức = start (driver). Terraform chỉ tạo/xóa.

locals {
  instance_type = {
    small  = "t3.small"
    medium = "t3.medium"
  }
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# ---------- IAM: đọc cấu hình của chính Environment + SSM Session Manager ----------
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
  description = "App cua ${var.name_prefix}"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-app" }
}

# Ra ngoài: tải image (qua NAT), gọi SSM, nói chuyện với database
resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# Luật cho phép app vào database nằm trong vòng đời của app (không phải của database)
resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
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

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 30
  }

  # Script chạy ở MỖI lần khởi động (systemd), nên stop/start bao nhiêu lần
  # ứng dụng vẫn đọc lại mật khẩu từ SSM và chạy lại container.
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    region            = data.aws_region.current.region
    app_image         = var.app_image
    app_port          = var.app_port
    db_host           = var.db_host
    db_port           = var.db_port
    db_name           = var.db_name
    db_user           = var.db_user
    db_password_param = var.db_password_param
  })

  tags = { Name = "${var.name_prefix}-app" }

  lifecycle {
    # AMI "latest" đổi theo thời gian; không được vì thế mà thay máy (P1 hội tụ).
    ignore_changes = [ami]
  }
}
