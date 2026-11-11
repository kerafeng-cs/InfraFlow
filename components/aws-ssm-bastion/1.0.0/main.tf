# Class stoppable: a t4g.nano with no inbound rules. Operators reach private services with
# SSM Session Manager port forwarding, for example:
#   aws ssm start-session --target <instance_id> \
#     --document-name AWS-StartPortForwardingSessionToRemoteHost \
#     --parameters host=<private host>,portNumber=5432,localPortNumber=5432

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_iam_role" "bastion" {
  name = "${var.name_prefix}-bastion"
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

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.bastion.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "bastion" {
  name = "${var.name_prefix}-bastion"
  path = "/infraflow/env/"
  role = aws_iam_role.bastion.name
}

resource "aws_security_group" "bastion" {
  name        = "${var.name_prefix}-bastion"
  description = "SSM bastion for ${var.name_prefix}"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-bastion" }
}

resource "aws_vpc_security_group_egress_rule" "bastion_all" {
  security_group_id = aws_security_group.bastion.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# The rule admitting the bastion to the database follows the bastion's lifecycle
resource "aws_vpc_security_group_ingress_rule" "db_from_bastion" {
  count                        = var.db_enabled ? 1 : 0
  security_group_id            = var.db_security_group_id
  referenced_security_group_id = aws_security_group.bastion.id
  ip_protocol                  = "tcp"
  from_port                    = var.db_port
  to_port                      = var.db_port
}

resource "aws_instance" "bastion" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = "t4g.nano"
  subnet_id              = var.subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.bastion.id]
  iam_instance_profile   = aws_iam_instance_profile.bastion.name

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
  }

  tags = { Name = "${var.name_prefix}-bastion" }

  lifecycle {
    ignore_changes = [ami]
  }
}
