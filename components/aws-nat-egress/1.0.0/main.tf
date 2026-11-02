# Lớp hourly_no_data: NAT Gateway và Elastic IP tính tiền theo giờ, không có trạng thái stop.
# Ngủ = xóa cả component (egress_present = false); thức = tạo lại.

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

# Route nằm trong route table do network sở hữu, nhưng thuộc vòng đời của egress:
# egress biến mất thì route cũng biến mất, không để lại route trỏ vào NAT đã xóa.
resource "aws_route" "private_default" {
  route_table_id         = var.private_route_table_id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this.id
}
