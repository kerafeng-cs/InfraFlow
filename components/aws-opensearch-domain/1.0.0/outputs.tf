# Provides port "search" (search.opensearch/v1)
output "endpoint" { value = "https://${aws_opensearch_domain.this.endpoint}" }
output "security_group_id" { value = aws_security_group.this.id }
