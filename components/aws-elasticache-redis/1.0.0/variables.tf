variable "name_prefix" {
  type = string
}

variable "env_id" {
  type        = string
  description = "Used to build the SSM path /infraflow/env/<env_id>/cache_endpoint"
}

# Requires port "net" (net.vpc/v1, when: present)
variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnets"
}

variable "size" {
  type    = string
  default = "small"

  validation {
    condition     = contains(["small", "medium"], var.size)
    error_message = "size must be small or medium."
  }
}
