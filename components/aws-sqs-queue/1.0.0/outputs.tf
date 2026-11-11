# Provides port "queue" (queue.sqs/v1)
output "queue_url" { value = aws_sqs_queue.this.url }
output "queue_arn" { value = aws_sqs_queue.this.arn }
