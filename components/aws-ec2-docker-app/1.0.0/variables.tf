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
    error_message = "size must be small or medium."
  }
}

# Requires port "net" (net.vpc/v1, when: present)
variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnets; the instance is placed in the first one"
}

# Requires port "db" (db.postgres/v1, when: serving)
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

# Requires port "workload" (workload.container/v1): the Lease application settings
variable "app_image" {
  type = string
}

variable "app_port" {
  type = number
}

variable "app_health_path" {
  type = string
}
