variable "name_prefix" {
  type = string
}

variable "env_id" {
  type        = string
  description = "Used to build the SSM path /infraflow/env/<env_id>/search_endpoint"
}

# Requires port "net" (net.vpc/v1, when: present)
variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnets; the single node is placed in the first one"
}

variable "size" {
  type    = string
  default = "small"

  validation {
    condition     = contains(["small", "medium"], var.size)
    error_message = "size must be small or medium."
  }
}
