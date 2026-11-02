variable "name_prefix" {
  type = string
}

# Cổng requires "net" (net.vpc/v1, when: present)
variable "public_subnet_ids" {
  description = "Public subnet; NAT đặt ở subnet đầu tiên (AZ a)"
  type        = list(string)
}

variable "private_route_table_id" {
  description = "Route table của private subnet, nơi thêm route 0.0.0.0/0 -> NAT"
  type        = string
}
