terraform {
  required_version = ">= 1.10"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
  }
  # The first deployment keeps state locally because the bucket does not exist yet. Afterwards,
  # move it to S3: add backend "s3" { bucket = <output state_bucket>, key = "platform/terraform.tfstate",
  # region = "ap-southeast-1", use_lockfile = true } and run `terraform init -migrate-state`.
}

provider "aws" {
  region  = var.region
  profile = var.profile

  default_tags {
    tags = {
      "infraflow:component" = "platform"
      "infraflow:stage"     = var.stage
    }
  }
}

data "aws_caller_identity" "me" {}
data "aws_region" "current" {}

locals {
  account = data.aws_caller_identity.me.account_id
  region  = data.aws_region.current.region
  p       = "${var.prefix}-${var.stage}"
}
