variable "name_prefix" {
  type = string
}

# Requires port "net" (net.vpc/v1, when: present)
variable "public_subnet_ids" {
  description = "Public subnets; NAT Gateways are placed in the first one, or one in each"
  type        = list(string)
}

variable "private_route_table_ids" {
  description = "Route tables of the private subnets, one per AZ, that receive the 0.0.0.0/0 route"
  type        = list(string)
}

variable "availability" {
  type        = string
  default     = "single"
  description = "single: one Availability Zone; multi: two (higher cost)"

  validation {
    condition     = contains(["single", "multi"], var.availability)
    error_message = "availability must be single or multi."
  }
}
