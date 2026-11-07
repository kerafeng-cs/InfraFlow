# Provides port "http" (http.backend/v1)
output "instance_id"       { value = aws_instance.app.id }
output "port"              { value = var.app_port }
output "health_path"       { value = var.app_health_path }
output "security_group_id" { value = aws_security_group.app.id }
