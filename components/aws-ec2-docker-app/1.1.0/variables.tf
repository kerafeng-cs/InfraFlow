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

# Requires port "db" (db.postgres/v1, when: serving, optional)
variable "db_enabled" {
  type        = bool
  description = "Whether the db port is bound; set by the compiler"
}

variable "db_host" {
  type    = string
  default = null
}

variable "db_port" {
  type    = number
  default = null
}

variable "db_name" {
  type    = string
  default = null
}

variable "db_user" {
  type    = string
  default = null
}

variable "db_password_param" {
  type    = string
  default = null
}

variable "db_security_group_id" {
  type    = string
  default = null
}

# Requires port "cache" (cache.redis/v1, when: serving, optional).
# The address is read from SSM Parameter Store when the container starts.
variable "cache_enabled" {
  type        = bool
  description = "Whether the cache port is bound; set by the compiler"
}

# Requires port "queue" (queue.sqs/v1, when: serving, optional)
variable "queue_enabled" {
  type        = bool
  description = "Whether the queue port is bound; set by the compiler"
}

variable "queue_url" {
  type    = string
  default = null
}

variable "queue_arn" {
  type    = string
  default = null
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
