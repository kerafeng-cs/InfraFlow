# Class hourly_no_data: a NAT Gateway and its Elastic IP are billed per hour and cannot be stopped.
# Sleep removes the whole component (egress_present = false); wake recreates it.

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "${var.name_prefix}-nat-eip"
  }
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = var.public_subnet_ids[0]

  tags = {
    Name = "${var.name_prefix}-nat"
  }
}

# The route lives in a route table owned by network but follows the egress lifecycle:
# when egress is removed the route goes with it, leaving no route to a deleted NAT.
resource "aws_route" "private_default" {
  route_table_id         = var.private_route_table_id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this.id
}
