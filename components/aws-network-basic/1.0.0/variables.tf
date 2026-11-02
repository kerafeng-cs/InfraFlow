variable "name_prefix" {
  type        = string
  description = "Tiền tố tên tài nguyên, ví dụ dev-demo-qa"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}
