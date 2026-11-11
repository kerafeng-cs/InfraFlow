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
  description = "Private subnets for the tasks"
}

# Requires port "target" (lb.target/v1, when: present)
variable "target_group_arn" {
  type = string
}

variable "alb_security_group_id" {
  type = string
}

# Requires port "workload" (workload.container/v1): the Lease application settings
variable "app_image" {
  type = string
}

variable "app_port" {
  type = number
}
