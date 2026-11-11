# Class stoppable: a GPU instance that runs the Lease's container with access to the GPUs and
# to the data volume mounted at /data. It has no inbound rules; users reach the container
# (for example JupyterLab) with SSM port forwarding to app_port.
#
# New AWS accounts often have a quota of 0 vCPUs for G instances
# ("Running On-Demand G and VT instances"); request an increase before the first wake.

locals {
  instance_type = {
    small  = "g4dn.xlarge"
    medium = "g4dn.2xlarge"
  }
}

data "aws_ssm_parameter" "dlami" {
  name = "/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-amazon-linux-2023/latest/ami-id"
}

data "aws_region" "current" {}

data "aws_subnet" "private" {
  for_each = toset(var.subnet_ids)
  id       = each.value
}

locals {
  # The instance must be in the Availability Zone of the volume it attaches
  subnet_id = one([for s in data.aws_subnet.private : s.id if s.availability_zone == var.volume_availability_zone])
}

resource "aws_iam_role" "workbench" {
  name = "${var.name_prefix}-workbench"
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
  role       = aws_iam_role.workbench.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "workbench" {
  name = "${var.name_prefix}-workbench"
  path = "/infraflow/env/"
  role = aws_iam_role.workbench.name
}

resource "aws_security_group" "workbench" {
  name        = "${var.name_prefix}-workbench"
  description = "GPU workbench for ${var.name_prefix}"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-workbench" }
}

resource "aws_vpc_security_group_egress_rule" "workbench_all" {
  security_group_id = aws_security_group.workbench.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_instance" "workbench" {
  ami                    = data.aws_ssm_parameter.dlami.value
  instance_type          = local.instance_type[var.size]
  subnet_id              = local.subnet_id
  vpc_security_group_ids = [aws_security_group.workbench.id]
  iam_instance_profile   = aws_iam_instance_profile.workbench.name

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 100
  }

  # Runs on every boot: waits for the data volume, mounts it at /data and starts the container.
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    app_image = var.app_image
    app_port  = var.app_port
    env_id    = var.env_id
    volume_id = var.volume_id
  })

  tags = { Name = "${var.name_prefix}-workbench" }

  lifecycle {
    ignore_changes = [ami]
  }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = var.volume_id
  instance_id = aws_instance.workbench.id

  # Detach cleanly when the workbench is removed before the volume is snapshotted
  stop_instance_before_detaching = true
}
