# Class hourly_no_data: NAT Gateways and their Elastic IPs are billed per hour and cannot be stopped.
# Sleep removes the whole component; wake recreates it.
# availability = single: one NAT in the first AZ serves both private subnets.
# availability = multi:  one NAT per AZ, so losing an AZ does not cut the other one off.

locals {
  nat_count = var.availability == "multi" ? 2 : 1
}

resource "aws_eip" "nat" {
  count  = local.nat_count
  domain = "vpc"

  tags = { Name = "${var.name_prefix}-nat-eip" }
}

resource "aws_nat_gateway" "this" {
  count         = local.nat_count
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = var.public_subnet_ids[count.index]

  tags = { Name = "${var.name_prefix}-nat" }
}

# The routes live in route tables owned by network but follow the egress lifecycle:
# when egress is removed the routes go with it, leaving no route to a deleted NAT.
resource "aws_route" "private_default" {
  count                  = length(var.private_route_table_ids)
  route_table_id         = var.private_route_table_ids[count.index]
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[min(count.index, local.nat_count - 1)].id
}
