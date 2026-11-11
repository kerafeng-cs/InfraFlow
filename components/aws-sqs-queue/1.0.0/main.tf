# Class free: SQS charges per request, so the queue stays in place at every level and the
# messages wait for the worker to wake. They expire after the retention period and are
# deleted with the queue when the Lease is reclaimed.

resource "aws_sqs_queue" "dead_letter" {
  name                      = "${var.name_prefix}-queue-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "this" {
  name                       = "${var.name_prefix}-queue"
  message_retention_seconds  = 1209600
  visibility_timeout_seconds = 300
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 5
  })
}
