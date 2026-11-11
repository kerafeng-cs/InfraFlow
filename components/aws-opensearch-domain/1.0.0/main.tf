# Class hourly_no_data: an OpenSearch domain is billed per instance hour and cannot be stopped,
# so sleep removes it and the index is lost (data class ephemeral). This suits a search sandbox
# whose index is rebuilt from a source of truth after each wake. Creating a domain takes
# 15 to 20 minutes.
#
# A domain in a VPC requires the service-linked role AWSServiceRoleForAmazonOpenSearchService,
# which the runner creates once per account.

locals {
  instance_type = {
    small  = "t3.small.search"
    medium = "t3.medium.search"
  }
  # t3.small does not support encryption at rest
  encrypt_at_rest = var.size != "small"
  # Domain names are 3 to 28 characters
  domain_name = substr("${var.name_prefix}-search", 0, 28)
}

data "aws_vpc" "this" {
  id = var.vpc_id
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# Clients are admitted by the VPC CIDR, so the domain does not depend on its clients.
resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-search"
  description = "OpenSearch for ${var.name_prefix}"
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name_prefix}-search" }
}

resource "aws_vpc_security_group_ingress_rule" "https_from_vpc" {
  security_group_id = aws_security_group.this.id
  cidr_ipv4         = data.aws_vpc.this.cidr_block
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_opensearch_domain" "this" {
  domain_name    = local.domain_name
  engine_version = "OpenSearch_2.17"

  cluster_config {
    instance_type          = local.instance_type[var.size]
    instance_count         = 1
    zone_awareness_enabled = false
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = 10
  }

  vpc_options {
    subnet_ids         = [var.subnet_ids[0]]
    security_group_ids = [aws_security_group.this.id]
  }

  encrypt_at_rest {
    enabled = local.encrypt_at_rest
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  # Network access is limited by the VPC and the security group; any principal inside may query.
  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = "*" }
      Action    = "es:ESHttp*"
      Resource  = "arn:aws:es:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:domain/${local.domain_name}/*"
    }]
  })

  tags = { Name = "${var.name_prefix}-search" }
}

# Clients read the address when they start, so it is not a Terraform input of theirs.
resource "aws_ssm_parameter" "endpoint" {
  name  = "/infraflow/env/${var.env_id}/search_endpoint"
  type  = "String"
  value = "https://${aws_opensearch_domain.this.endpoint}"
}
