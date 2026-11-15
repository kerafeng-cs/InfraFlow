output "nat_gateway_id" {
  value = aws_nat_gateway.this[0].id
}

output "public_ip" {
  value = aws_eip.nat[0].public_ip
}
