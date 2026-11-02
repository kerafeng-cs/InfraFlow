output "site_url" {
  value = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "api_url" {
  value = aws_apigatewayv2_api.this.api_endpoint
}

output "user_pool_id" {
  value = aws_cognito_user_pool.this.id
}

output "web_client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "state_bucket" {
  value = aws_s3_bucket.state.id
}

output "artifact_bucket" {
  value = aws_s3_bucket.artifacts.id
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.lifecycle.arn
}

output "codebuild_project" {
  value = aws_codebuild_project.tf.name
}
