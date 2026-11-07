# Provides port "db" (db.postgres/v1)
output "db_identifier"     { value = aws_db_instance.this.identifier }
output "endpoint_address"  { value = aws_db_instance.this.address }
output "endpoint_port"     { value = aws_db_instance.this.port }
output "db_name"           { value = var.db_name }
output "db_user"           { value = var.db_user }
output "password_ssm_name" { value = aws_ssm_parameter.db_password.name }
output "security_group_id" { value = aws_security_group.db.id }
