variable "name_prefix" {
  type = string
}

variable "env_id" {
  type        = string
  description = "Dùng để đặt đường dẫn SSM /infraflow/env/<env_id>/..."
}

# Cổng requires "net" (net.vpc/v1, when: present)
variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnet ở 2 AZ"
}

# Không dùng trong web-db: luật cho phép app vào 5432 do component app tạo
# (luật thuộc vòng đời của app, tránh phụ thuộc vòng database <-> app).
variable "client_security_group_ids" {
  type    = list(string)
  default = []
}

variable "size" {
  type    = string
  default = "small"

  validation {
    condition     = contains(["small", "medium"], var.size)
    error_message = "size phải là small hoặc medium."
  }
}

variable "db_name" {
  type    = string
  default = "app"
}

variable "db_user" {
  type    = string
  default = "app"
}

# Dùng khi Hibernate: khôi phục từ snapshot (tầng 3, chưa dùng bây giờ)
variable "restore_from_snapshot" {
  type    = string
  default = null
}
