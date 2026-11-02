variable "name_prefix" {
  type = string
}

variable "env_id" {
  type = string
}

variable "size" {
  type    = string
  default = "small"

  validation {
    condition     = contains(["small", "medium"], var.size)
    error_message = "size phải là small hoặc medium."
  }
}

# Cổng requires "net" (net.vpc/v1, when: present)
variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnet; EC2 đặt ở subnet đầu tiên"
}

# Cổng requires "db" (db.postgres/v1, when: serving)
variable "db_host" {
  type = string
}

variable "db_port" {
  type = number
}

variable "db_name" {
  type = string
}

variable "db_user" {
  type = string
}

variable "db_password_param" {
  type = string
}

variable "db_security_group_id" {
  type = string
}

# Cổng requires "workload" (workload.container/v1) = cấu hình ứng dụng của Lease
variable "app_image" {
  type = string
}

variable "app_port" {
  type = number
}

variable "app_health_path" {
  type = string
}
