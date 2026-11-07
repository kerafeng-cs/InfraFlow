variable "name_prefix" {
  type = string
}

variable "env_id" {
  type        = string
  description = "Used to build the SSM path /infraflow/env/<env_id>/..."
}

# Requires port "net" (net.vpc/v1, when: present)
variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnets in two Availability Zones"
}

# Unused in web-db: the rule admitting the app on 5432 is created by the app component,
# so it follows the app's lifecycle and avoids a database <-> app dependency cycle.
variable "client_security_group_ids" {
  type    = list(string)
  default = []
}

variable "size" {
  type    = string
  default = "small"

  validation {
    condition     = contains(["small", "medium"], var.size)
    error_message = "size must be small or medium."
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

# Used by hibernate: restore from a snapshot
variable "restore_from_snapshot" {
  type    = string
  default = null
}
