variable "region" {
  type    = string
  default = "ap-southeast-1"
}

variable "profile" {
  type    = string
  default = "infraflow"
}

variable "prefix" {
  type    = string
  default = "infraflow"
}

variable "stage" {
  description = "dev hoặc prod (TD mục 12.1)"
  type        = string
  default     = "dev"
}

variable "terraform_version" {
  description = "Phiên bản Terraform chạy trong CodeBuild"
  type        = string
  default     = "1.9.8"
}

# Tên miền (tùy chọn). Chưa có thì URL môi trường là sleeping page trên CloudFront và
# khi thức sẽ chuyển hướng sang địa chỉ ALB.
variable "domain" {
  type    = string
  default = null
}

variable "hosted_zone_id" {
  type    = string
  default = null
}

variable "certificate_arn" {
  description = "Chứng chỉ ACM wildcard *.domain ở ap-southeast-1 cho ALB của các Environment"
  type        = string
  default     = null
}

variable "default_org_id" {
  type    = string
  default = "org_default"
}
