locals {
  instance_class = {
    small  = "db.t4g.micro"
    medium = "db.t4g.small"
  }
}

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "aws_ssm_parameter" "db_password" {
  name  = "/infraflow/env/${var.env_id}/db_password"
  type  = "SecureString"
  value = random_password.db.result
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db"
  subnet_ids = var.subnet_ids

  tags = { Name = "${var.name_prefix}-db" }
}

resource "aws_security_group" "db" {
  name        = "${var.name_prefix}-db"
  description = "PostgreSQL for ${var.name_prefix}"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-db" }

  lifecycle {
    # Security group descriptions are immutable in EC2. Ignoring edits ensures that a wording
    # change never replaces the group attached to a database that holds data.
    ignore_changes = [description]
  }
}

resource "aws_vpc_security_group_ingress_rule" "from_clients" {
  for_each = toset(var.client_security_group_ids)

  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-db"
  engine         = "postgres"
  engine_version = "16"
  instance_class = local.instance_class[var.size]

  allocated_storage = 20
  storage_type      = "gp3"
  multi_az          = false

  db_name  = var.restore_from_snapshot == null ? var.db_name : null
  username = var.db_user
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  snapshot_identifier = var.restore_from_snapshot

  # The snapshot driver creates and verifies a snapshot before deletion,
  # so Terraform does not take a final snapshot of its own.
  skip_final_snapshot      = true
  deletion_protection      = false
  backup_retention_period  = 0
  delete_automated_backups = true
  apply_immediately        = true

  tags = { Name = "${var.name_prefix}-db" }

  lifecycle {
    # Changing snapshot_identifier after a restore would make Terraform delete and
    # recreate the database. Ignored here; Plan Validator rule V4 blocks it as well.
    ignore_changes = [snapshot_identifier]
  }
}
