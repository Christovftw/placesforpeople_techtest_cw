terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.61.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "techtest-p4p"
      ManagedBy = "terraform"
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

locals {
  name_prefix = "du-university-chapters-etl"
  common_tags = {
    Project   = local.name_prefix
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_repository" "etl" {
  name                 = local.name_prefix
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  force_delete = true

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "etl" {
  name              = "/aws/lambda/${local.name_prefix}"
  retention_in_days = 7
}

resource "aws_iam_role" "lambda_execution" {
  name = "${local.name_prefix}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_secrets_manager" {
  name = "${local.name_prefix}-secrets-policy"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.db_credentials.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_ecr_pull" {
  name = "${local.name_prefix}-ecr-pull"
  role = aws_iam_role.lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability"
        ]
        Resource = aws_ecr_repository.etl.arn
      }
    ]
  })
}

resource "random_password" "db_password" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "db_credentials" {
  name                    = "${local.name_prefix}-db-credentials"
  description             = "RDS PostgreSQL credentials for the DU chapters ETL"
  recovery_window_in_days = 0

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = var.db_username
    password = random_password.db_password.result
    host     = aws_db_instance.etl.address
    port     = tostring(aws_db_instance.etl.port)
    dbname   = var.db_name
  })
}

resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds-sg"
  description = "Security group for the DU chapters RDS instance"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "PostgreSQL from anywhere (demo: Lambda egress IPs are unpredictable; protected by TLS + credentials)"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_db_subnet_group" "etl" {
  name       = "${local.name_prefix}-db-subnet-group"
  subnet_ids = slice(data.aws_subnets.default.ids, 0, min(3, length(data.aws_subnets.default.ids)))

  tags = local.common_tags
}

resource "aws_db_instance" "etl" {
  identifier              = local.name_prefix
  engine                  = "postgres"
  engine_version          = "16"
  instance_class          = "db.t4g.micro"
  allocated_storage       = 20
  storage_type            = "gp3"
  storage_encrypted       = true
  db_name                 = var.db_name
  username                = var.db_username
  password                = random_password.db_password.result
  db_subnet_group_name    = aws_db_subnet_group.etl.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  publicly_accessible     = true
  skip_final_snapshot     = true
  backup_retention_period = 0
  multi_az                = false

  tags = local.common_tags
}

resource "aws_lambda_function" "etl" {
  function_name = local.name_prefix
  role          = aws_iam_role.lambda_execution.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  memory_size   = 128
  timeout       = 60

  environment {
    variables = {
      POSTGRES_HOST    = aws_db_instance.etl.address
      POSTGRES_PORT    = tostring(aws_db_instance.etl.port)
      POSTGRES_DB      = var.db_name
      DB_SECRET_ARN    = aws_secretsmanager_secret.db_credentials.arn
      SOURCE_URL       = "https://services2.arcgis.com/5I7u4SJE1vUr79JC/arcgis/rest/services/UniversityChapters_Public/FeatureServer/0"
      TARGET_STATES    = "[\"CA\"]"
      ARCGIS_PAGE_SIZE = "1000"
      REQUEST_TIMEOUT  = "30"
      LOG_LEVEL        = "INFO"
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic_execution,
    aws_iam_role_policy.lambda_secrets_manager,
    aws_iam_role_policy.lambda_ecr_pull,
    aws_cloudwatch_log_group.etl,
    aws_secretsmanager_secret_version.db_credentials,
  ]
}

resource "aws_scheduler_schedule" "daily" {
  name        = "${local.name_prefix}-daily"
  description = "Trigger the DU chapters ETL Lambda once per day"

  schedule_expression          = "rate(1 day)"
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.etl.arn
    role_arn = aws_iam_role.scheduler.arn
  }
}

resource "aws_iam_role" "scheduler" {
  name = "${local.name_prefix}-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "scheduler.amazonaws.com"
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  name = "${local.name_prefix}-scheduler-invoke-policy"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.etl.arn
      }
    ]
  })
}

resource "aws_sns_topic" "etl_failures" {
  name = "${local.name_prefix}-failures"

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.name_prefix}-lambda-errors"
  alarm_description   = "Alerts when the ETL Lambda reports one or more errors."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.etl.function_name
  }

  alarm_actions = [aws_sns_topic.etl_failures.arn]

  tags = local.common_tags
}
