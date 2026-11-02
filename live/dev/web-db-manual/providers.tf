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
  # Tạm để state ở máy. Việc B sẽ chuyển lên S3 kèm use_lockfile.
}

provider "aws" {
  region  = "ap-southeast-1"
  profile = "infraflow"

  # Gắn tag cho mọi tài nguyên (TD mục 11.1, bất biến 4)
  default_tags {
    tags = {
      "infraflow:managed"  = "true"
      "infraflow:env_id"   = "dev-demo-qa"
      "infraflow:lease_id" = "dev-demo"
      "infraflow:org_id"   = "org_dev"
    }
  }
}
