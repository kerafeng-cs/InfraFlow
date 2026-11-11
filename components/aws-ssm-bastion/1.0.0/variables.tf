variable "name_prefix" {
  type = string
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

variable "db_port" {
  type    = number
  default = null
}

variable "db_security_group_id" {
  type    = string
  default = null
}
