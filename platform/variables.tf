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
  description = "dev or prod"
  type        = string
  default     = "dev"
}

variable "terraform_version" {
  description = "Terraform version used in CodeBuild"
  type        = string
  default     = "1.10.5"
}

# Domain name (optional). Without one, the environment URL is the sleeping page on CloudFront,
# which redirects to the ALB address while the environment is awake.
variable "domain" {
  type    = string
  default = null
}

variable "hosted_zone_id" {
  type    = string
  default = null
}

variable "certificate_arn" {
  description = "Wildcard ACM certificate *.domain in ap-southeast-1 for the Environment ALBs"
  type        = string
  default     = null
}

variable "default_org_id" {
  type    = string
  default = "org_default"
}
