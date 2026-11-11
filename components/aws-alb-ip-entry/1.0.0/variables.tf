variable "name_prefix" {
  type = string
}

# Requires port "net"
variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

# Requires port "workload" (workload.container/v1): the Lease application settings
variable "target_port" {
  type = number
}

variable "health_path" {
  type = string
}

# Shared wildcard certificate. Null when there is no domain: only HTTP on port 80.
variable "certificate_arn" {
  type    = string
  default = null
}
