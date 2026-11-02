# Cổng "provides" của component, kiểu net.vpc/v1 (IC mục 4.3)
output "vpc_id"                 { value = aws_vpc.this.id }
output "public_subnet_ids"      { value = aws_subnet.public[*].id }
output "private_subnet_ids"     { value = aws_subnet.private[*].id }
output "private_route_table_id" { value = aws_route_table.private.id }
output "azs"                    { value = local.azs }
