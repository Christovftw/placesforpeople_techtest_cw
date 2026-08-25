variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "eu-north-1"
}

variable "image_uri" {
  description = "Full ECR image URI (including tag) for the Lambda container. The image must already exist in ECR before Terraform applies."
  type        = string
}

variable "db_name" {
  description = "Name of the PostgreSQL database created on the RDS instance."
  type        = string
  default     = "du_chapters"
}

variable "db_username" {
  description = "Master username for the RDS PostgreSQL instance."
  type        = string
  default     = "etl"
}

