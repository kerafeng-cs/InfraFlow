variable "name_prefix" {
  type = string
}

# Cổng requires "net"
variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

# Cổng requires "backend" (http.backend/v1, when: serving)
variable "target_instance_id" {
  type = string
}

variable "target_port" {
  type = number
}

variable "health_path" {
  type = string
}

variable "target_security_group_id" {
  type = string
}

# Chứng chỉ wildcard dùng chung. Chưa có tên miền thì để null: chỉ mở HTTP 80.
variable "certificate_arn" {
  type    = string
  default = null
}
