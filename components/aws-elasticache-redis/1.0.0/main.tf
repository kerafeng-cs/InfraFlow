locals {
  node_type = {
    small  = "cache.t4g.micro"
    medium = "cache.t4g.small"
  }
}

data "aws_vpc" "this" {
  id = var.vpc_id
}

# Clients are admitted by the VPC CIDR rather than by their security group, so the cache
# does not depend on its clients and no dependency cycle appears.
resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-redis"
  description = "Redis for ${var.name_prefix}"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-redis" }
}

resource "aws_vpc_security_group_ingress_rule" "from_vpc" {
  security_group_id = aws_security_group.this.id
  cidr_ipv4         = data.aws_vpc.this.cidr_block
  ip_protocol       = "tcp"
  from_port         = 6379
  to_port           = 6379
}

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name_prefix}-redis"
  subnet_ids = var.subnet_ids
}

resource "aws_elasticache_cluster" "this" {
  cluster_id           = "${var.name_prefix}-redis"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = local.node_type[var.size]
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.this.name
  security_group_ids   = [aws_security_group.this.id]

  snapshot_retention_limit = 0
  apply_immediately        = true

  tags = { Name = "${var.name_prefix}-redis" }
}

# Clients read the address when they start, so it is not a Terraform input of theirs.
resource "aws_ssm_parameter" "endpoint" {
  name  = "/infraflow/env/${var.env_id}/cache_endpoint"
  type  = "String"
  value = "${aws_elasticache_cluster.this.cache_nodes[0].address}:${aws_elasticache_cluster.this.port}"
}
