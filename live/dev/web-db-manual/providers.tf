terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  # Local state for this manually operated environment. Platform-managed environments
  # use the S3 backend with use_lockfile.
}

provider "aws" {
  region  = "ap-southeast-1"
  profile = "infraflow"

  # Every resource carries the ownership tags checked by Plan Validator rules V5 and V6
  default_tags {
    tags = {
      "infraflow:managed"  = "true"
      "infraflow:env_id"   = "dev-demo-qa"
      "infraflow:lease_id" = "dev-demo"
      "infraflow:org_id"   = "org_dev"
    }
  }
}
