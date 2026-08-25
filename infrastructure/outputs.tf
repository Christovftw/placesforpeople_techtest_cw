output "ecr_repository_url" {
  description = "URL of the ECR repository for the ETL image."
  value       = aws_ecr_repository.etl.repository_url
}

output "lambda_function_arn" {
  description = "ARN of the ETL Lambda function."
  value       = aws_lambda_function.etl.arn
}

output "rds_endpoint" {
  description = "Endpoint of the RDS PostgreSQL instance."
  value       = aws_db_instance.etl.endpoint
}

output "secrets_manager_arn" {
  description = "ARN of the Secrets Manager secret containing DB credentials."
  value       = aws_secretsmanager_secret.db_credentials.arn
}
