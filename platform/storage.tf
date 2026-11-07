# ---------- S3: per-Environment Terraform state and operation artifacts ----------
resource "aws_s3_bucket" "state" {
  bucket_prefix = "${local.p}-tfstate-"
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "${local.p}-artifacts-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "ops-30d"
    status = "Enabled"
    filter {
      prefix = "ops/"
    }
    expiration {
      days = 30
    }
  }
}

# ---------- CodeBuild sources: code.zip (services) and components.zip ----------
data "archive_file" "code" {
  type        = "zip"
  source_dir  = "${path.module}/../services"
  output_path = "${path.module}/.build/code.zip"
  excludes    = ["tests/**", "**/__pycache__/**"]
}

data "archive_file" "components" {
  type        = "zip"
  source_dir  = "${path.module}/../components"
  output_path = "${path.module}/.build/components.zip"
}

resource "aws_s3_object" "code" {
  bucket = aws_s3_bucket.artifacts.id
  key    = "runner/code.zip"
  source = data.archive_file.code.output_path
  etag   = data.archive_file.code.output_md5
}

resource "aws_s3_object" "components" {
  bucket = aws_s3_bucket.artifacts.id
  key    = "runner/components.zip"
  source = data.archive_file.components.output_path
  etag   = data.archive_file.components.output_md5
}
