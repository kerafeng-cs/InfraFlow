# ---------- Management console and sleeping page: private S3 behind CloudFront (OAC) ----------
resource "aws_s3_bucket" "site" {
  bucket_prefix = "${local.p}-site-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${local.p}-site"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_200"

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "site"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "site"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled (small site, frequent changes)
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.site.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.site.arn } }
    }]
  })
}

locals {
  site_files = {
    "index.html" = "text/html; charset=utf-8"
    "sleep.html" = "text/html; charset=utf-8"
    "app.js"     = "application/javascript; charset=utf-8"
    "sleep.js"   = "application/javascript; charset=utf-8"
    "style.css"  = "text/css; charset=utf-8"
  }
}

resource "aws_s3_object" "site" {
  for_each     = local.site_files
  bucket       = aws_s3_bucket.site.id
  key          = each.key
  source       = "${path.module}/../web/${each.key}"
  etag         = filemd5("${path.module}/../web/${each.key}")
  content_type = each.value
}

resource "aws_s3_object" "config" {
  bucket       = aws_s3_bucket.site.id
  key          = "config.js"
  content_type = "application/javascript; charset=utf-8"
  content = "window.INFRAFLOW = ${jsonencode({
    apiUrl   = aws_apigatewayv2_api.this.api_endpoint
    region   = local.region
    clientId = aws_cognito_user_pool_client.web.id
    stage    = var.stage
  })};\n"
}
