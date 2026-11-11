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
  description = "Private subnets; the instance is placed in the one in the volume's Availability Zone"
}

# Requires port "volume" (storage.ebs/v1, when: present)
variable "volume_id" {
  type = string
}

variable "volume_availability_zone" {
  type = string
}

# Requires port "workload" (workload.container/v1): the Lease application settings
variable "app_image" {
  type = string
}

variable "app_port" {
  type = number
}
