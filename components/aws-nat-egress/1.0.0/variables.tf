variable "name_prefix" {
  type = string
}

# Requires port "net" (net.vpc/v1, when: present)
variable "public_subnet_ids" {
  description = "Public subnets; the NAT Gateway is placed in the first one"
  type        = list(string)
}

variable "private_route_table_id" {
  description = "Route table of the private subnets that receives the 0.0.0.0/0 -> NAT route"
  type        = string
}
