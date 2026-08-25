# Ducks Unlimited University Chapter ETL

A small, config-driven ETL pipeline that extracts Ducks Unlimited university chapter data from a public ArcGIS REST API, filters it to configured states, and loads it into a Postgres table using a slowly-changing-dimension Type 2 (SCD2) pattern.

## Architecture

- **Extract**: queries the ArcGIS feature service with pagination and retries.
- **Transform**: normalises the API response into a typed row model and computes a lower-cased MD5 row hash.
- **Load**: uses SQLAlchemy to upsert rows into Postgres, closing old history rows when the hash changes.
- **Runtime**: the same container image runs locally and as an AWS Lambda function.

## Local development

### 1. Start Postgres

The ETL expects a running Postgres database. A separate compose file is provided for this for local testing:

```bash
docker compose -f local_postgres/docker-compose.yml up -d
```

This creates a Docker network called `du-postgres` that the ETL container will join if using the local `docker-compose.yml` file.

### 2. Configure environment variables

Copy the example file and adjust if needed:

```bash
cp .env.example .env
```

`.env.example` is configured for running outside Docker (`POSTGRES_HOST=localhost`). This will also work if using the local postgres docker compose provided due to the isolated network.

### 3. Run the ETL outside Docker

Use the project virtual environment:

```bash
.venv/bin/python -m etl
```

### 4. Run the ETL inside Docker

Build and run the ETL container. It joins the `du-postgres` network and connects to Postgres by service name (`db`):

```bash
docker compose up --build
```

### 5. Inspect the data

```bash
docker compose -f local_postgres/docker-compose.yml exec db \
  psql -U etl -d du_chapters -c 'SELECT * FROM university_chapters;'
```

### 6. Stop Postgres

```bash
docker compose -f local_postgres/docker-compose.yml down
```

### 7. Run the tests

The test suite requires a running Postgres database and installs `pytest` and `responses` from `requirements.txt`:

```bash
.venv/bin/pytest tests/ -v
```

### 8. Run the linter

```bash
.venv/bin/ruff check .
```

### 9. Install pre-commit hooks (optional)

```bash
.venv/bin/pre-commit install
```

This runs `ruff check .` automatically before each commit.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `POSTGRES_HOST` | Postgres host (`localhost` for local venv, RDS endpoint in AWS). |
| `POSTGRES_PORT` | Postgres port. |
| `POSTGRES_DB` | Database name. |
| `POSTGRES_USER` | Database user. Only used when `DB_SECRET_ARN` is not set. |
| `POSTGRES_PASSWORD` | Database password. Only used when `DB_SECRET_ARN` is not set. |
| `DB_SECRET_ARN` | Optional AWS Secrets Manager ARN for RDS credentials. |
| `SOURCE_URL` | ArcGIS feature service base URL. |
| `TARGET_STATES` | JSON list of states to filter, e.g. `["CA"]`. |
| `ARCGIS_PAGE_SIZE` | Page size for ArcGIS API requests. |
| `REQUEST_TIMEOUT` | HTTP request timeout in seconds. |
| `LOG_LEVEL` | Python log level. |

## AWS Secrets Manager credentials

For AWS deployments, set `DB_SECRET_ARN` to the ARN of a secret in Secrets Manager. The secret must contain JSON with `username` and `password` keys. It can also optionally override `host`, `port`, and `dbname`:

```json
{
  "username": "etl",
  "password": "super-secret-password",
  "host": "mydb.cluster-xxx.eu-west-1.rds.amazonaws.com",
  "port": "5432",
  "dbname": "du_chapters"
}
```

When `DB_SECRET_ARN` is set, the pipeline fetches connection details from Secrets Manager at runtime. Any keys present in the secret override the corresponding environment variables (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`). For local development, leave `DB_SECRET_ARN` unset and use the `POSTGRES_*` environment variables instead.

## AWS deployment note

The Terraform infrastructure will deploy the ETL as a Lambda container image, create a small RDS Postgres instance, and schedule the function daily via EventBridge Scheduler. The current local setup uses a shared Docker network for simplicity; the AWS deployment uses a publicly accessible RDS instance to keep costs low. This is a cost-conscious demo pattern and is **not** a full production network design.

To deploy this project you need an AWS account and a user/role with sufficient permissions to create ECR, Lambda, RDS, Secrets Manager, CloudWatch, EventBridge Scheduler, SNS and IAM resources. Terraform state is stored in an S3 backend configured in `infrastructure/backend.tf`. The bucket name is a literal value in that file — Terraform backend blocks cannot reference variables — and the bucket must exist before running `terraform init`. State is encrypted at rest (`encrypt = true`) and uses the S3 lockfile for state locking (`use_lockfile = true`).

### RDS public access warning (demo only)

Because the Lambda function runs outside the VPC, its outbound connections to the RDS public endpoint originate from unpredictable AWS-managed IP addresses, so no fixed CIDR can be whitelisted. The RDS security group therefore allows inbound PostgreSQL traffic from `0.0.0.0/0`. The database is still protected by:

- **Credentials**: the master password is generated by Terraform and stored in AWS Secrets Manager; it is never hard-coded or exposed as a plain output.
- **TLS**: RDS PostgreSQL supports SSL/TLS, encrypting connections in transit.

Even with those protections, exposing port 5432 to the entire internet would **not** be acceptable in production. The production pattern is Lambda attached to private subnets reaching RDS via security-group-to-security-group rules, with a NAT Gateway or VPC endpoints for egress.

### Bootstrapping: Terraform and the ECR image URI (first deploy)

The Lambda resource requires the container image to already exist in ECR, but the ECR repository is created by the same `terraform apply` — a chicken-and-egg problem. The repository URL also cannot be known in advance because it contains the AWS account ID: `<account-id>.dkr.ecr.<region>.amazonaws.com/du-university-chapters-etl`. The clean workaround is a targeted first apply — do **not** let a full `apply` fail just to discover the URL, as that leaves the stack half-created for no benefit:

```bash
cd infrastructure

# 1. Create only the ECR repository
terraform apply -target=aws_ecr_repository.etl

# 2. Read the generated repository URL
terraform output ecr_repository_url

# 3. Build and push the image (run from the repository root)
cd ../
aws ecr get-login-password --region eu-north-1 | \
  docker login --username AWS --password-stdin <repository-url>
docker buildx build --platform linux/amd64 --provenance=false -t <repository-url>:latest --push .

# 4. Set the terraform.tfvars variable `image_uri` with the correct value, replacing the placeholder
image_uri = "123456789012.dkr.ecr.eu-north-1.amazonaws.com/du-university-chapters-etl"

# 5. Apply the full stack with the real image URI from the infrastructure/ directory
cd infrastructure
terraform apply
```

This bootstrap is only needed once: the repository persists across deploys, so later applies reuse the same URL. Remember to replace the placeholder account ID (`123456789012`) in `terraform.tfvars` with the real one. In a larger setup the cleaner long-term pattern is to manage the ECR repository in its own Terraform root module/state, since its lifecycle is independent of the application infrastructure.

### CI/CD pipelines

GitHub Actions workflows live in `.github/workflows/`:

- `ci.yml` — on pull requests and pushes to `main`: lints with `ruff check .` and runs the test suite against a Postgres 16 service container.
- `deploy.yml` — on pushes to `main` (and manual dispatch): authenticates to AWS via OIDC (no long-lived keys), ensures the ECR repository exists, builds and pushes the image tagged with the Git SHA, then runs `terraform apply` with the new image URI.

### Bootstrapping: GitHub Actions CI/CD (one-time AWS setup)

The deploy workflow authenticates via OIDC and requires four one-time setup steps in the AWS account:

1. **Create the S3 state bucket** (must exist before any `terraform init`; public access is blocked and encryption is on by default, and versioning is recommended for state recovery):

   ```bash
   aws s3api create-bucket --bucket techtest-p4p-cw --region eu-north-1 \
     --create-bucket-configuration LocationConstraint=eu-north-1
   aws s3api put-bucket-versioning --bucket techtest-p4p-cw \
     --versioning-configuration Status=Enabled
   ```

2. **Create the IAM OIDC identity provider** (once per AWS account; no certificate thumbprint is needed — AWS validates it automatically):

   ```bash
   aws iam create-open-id-connect-provider \
     --url https://token.actions.githubusercontent.com \
     --client-id-list sts.amazonaws.com
   ```

3. **Create the IAM deploy role** the workflow assumes: trusted entity type *Web identity* for that provider, audience `sts.amazonaws.com`, and a trust policy condition scoping the subject to this repository:

   ```json
   "Condition": {
     "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
     "StringLike":   { "token.actions.githubusercontent.com:sub": "repo:<owner>/<repo>:*" }
   }
   ```

   Use `StringLike` with a trailing `:*` so the condition covers the `sub` claim formats emitted by both older and newer repositories (repositories created after mid-July 2026 can include `@<org-id>`/`@<repo-id>` suffixes). Avoid naming the role `GitHubActions`, which is a known issue with the `configure-aws-credentials` action. For the demo, `PowerUserAccess` + `IAMFullAccess` is pragmatic (Terraform creates IAM roles, which `PowerUserAccess` excludes); production should use a least-privilege policy covering ECR, Lambda, RDS, Secrets Manager, CloudWatch, EventBridge Scheduler, SNS, EC2, IAM pass-role and the S3 state bucket.

4. **Set the GitHub repository variable** `AWS_DEPLOY_ROLE_ARN` to the role ARN (*Settings → Secrets and variables → Actions → Variables*).

Once these are in place, a push to `main` (or *Actions → Deploy → Run workflow*) runs the full deploy, including the ECR bootstrap above.

## Notes

- The `TARGET_STATES` environment variable is created as a list of values to allow this to expand into the future if more states were required, even though only one state is required at this point in time.
- Pagination has been introduced to allow the application code to scale as appropriate, this is based on the specifications available at the ArcGIS REST Services Directory here: https://services2.arcgis.com/5I7u4SJE1vUr79JC/arcgis/rest/services/UniversityChapters_Public/FeatureServer/0 . Strictly speaking, it is unnecessary for this specific task.
- The shim in `__main__.py` is there for brevity, it could in theory be removed but it makes the pipeline easier to invoke locally with `python -m etl` in the virtual environment.
- The Secrets Manager secret created by Terraform is configured with `recovery_window_in_days = 0`, meaning it is permanently deleted immediately on `terraform destroy` with no recovery window. This has been done deliberately for the purposes of this demo so that `terraform destroy` tears everything down cleanly and the secret name can be reused on re-deploy. In a production deployment this would not be acceptable.
- The Lambda failure alarm publishes to an SNS topic that deliberately has no subscriptions in this demo. In a production environment you would subscribe to the topic (for example email or Slack) to get alerts on failures, or use an external monitoring platform such as Datadog that integrates with the wider corporate structure.