# ETL Pipeline TODO

Remaining items from `planning.md`:

1. ~~Terraform infrastructure (`infrastructure/`)~~ ✅
   - `backend.tf` — example S3 backend for Terraform state
   - `main.tf` — AWS resources (ECR, Lambda, EventBridge, RDS, IAM, Secrets Manager, security groups)
   - `variables.tf` — input variables
   - `outputs.tf` — outputs
   - `terraform.tfvars.example` — example variable values

2. ~~GitHub Actions (`.github/workflows/`)~~ ✅
   - `ci.yml` — run `ruff check .` and `pytest` on PRs and pushes to `main`
   - `deploy.yml` — build/push Docker image to ECR and run `terraform apply` on pushes to `main`
