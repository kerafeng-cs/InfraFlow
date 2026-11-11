# Provides port "public" (http.public/v1)
output "dns_name" { value = aws_lb.this.dns_name }
output "zone_id" { value = aws_lb.this.zone_id }

# Provides port "target" (lb.target/v1)
output "target_group_arn" { value = aws_lb_target_group.app.arn }
output "security_group_id" { value = aws_security_group.alb.id }
