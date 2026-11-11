variable "name_prefix" {
  type = string
}

# Requires port "net" (net.vpc/v1, when: present)
variable "subnet_ids" {
  type        = list(string)
  description = "Private subnets; the volume is created in the Availability Zone of the first one"
}

variable "size" {
  type    = string
  default = "small"

  validation {
    condition     = contains(["small", "medium"], var.size)
    error_message = "size must be small or medium."
  }
}

variable "restore_from_snapshot" {
  type        = string
  default     = null
  description = "Snapshot to restore from after hibernation; set by the controller"
}
