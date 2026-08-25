# ETL Pipeline Planning Document

## 1. Goal

Build a small, production-grade ETL pipeline that:

1. Extracts Ducks Unlimited university chapter data from the public ArcGIS REST API.
2. Filters it to configured states (the task requires California, but the state list should be configurable).
3. Loads the data into a Postgres table using a slowly-changing-dimension Type 2 (SCD2) pattern.
4. Runs inside a Docker container with a single Python entry point.
5. Can be developed locally using Docker Compose and tested with a separate local Postgres container.
6. Is deployed to AWS using Terraform (ECR + Lambda container image on a daily EventBridge schedule + CloudWatch logging + a small RDS Postgres instance).
7. Has a CI/CD pipeline that builds, tests and deploys the image.

## 2. Data source

The dataset is served from an ArcGIS Online hosted feature service. The discovered endpoint is:

```text
https://services2.arcgis.com/5I7u4SJE1vUr79JC/arcgis/rest/services/UniversityChapters_Public/FeatureServer/0
```

The pipeline will query it with `where=State='CA'` (or `State IN ('CA','OR','WA')` when configured) and request the fields:

- `ChapterID` -> `chapter_id`
- `University_Chapter` -> `chapter_name`
- `City` -> `city`
- `State` -> `state`
- `geometry.x`, `geometry.y` -> `coordinates` (stored as a `POINT(x y)` string)

The URL, layer id, field mappings and target states will all live in config, so the code does not hard-code the source.

## 3. Design principles

- **Config-driven**: one Pydantic `Settings` object reads environment variables and supplies sensible static defaults.
- **Small, flat codebase**: keep the number of files low; do not split into a package-per-function micro-structure.
- **One-line docstrings** on every function.
- **Typed arguments** on every function.
- **Minimal inline comments**: code should be readable by itself; comments only where the intent is non-obvious.
- **Single entry point**: `etl/main.py` exposes a `lambda_handler(event, context)` function that is used by both AWS Lambda and the local Docker Compose run. A small `__main__.py` module calls `lambda_handler({}, None)` so `python -m etl` also uses the same entry point.
- **AWS cost awareness**: use a Lambda container image triggered once per day by EventBridge rather than an always-provisioned Fargate task. RDS is created at the smallest `db.t4g.micro` size, which is currently AWS Free Tier eligible for PostgreSQL (subject to AWS Free Tier terms and credits).

## 4. Proposed repository layout

```text
.
├── .github/
│   └── workflows/
│       ├── ci.yml                 # run lint + unit tests on PRs
│       └── deploy.yml             # build image, push to ECR, terraform apply
├── docker-compose.yml             # ETL container only; joins separate Postgres network
├── local_postgres/
│   └── docker-compose.yml         # Postgres only, creates shared network for local dev/tests
├── infrastructure/
│   ├── backend.tf                 # S3 backend for Terraform state (commented example)
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── terraform.tfvars.example
├── etl/
│   ├── __init__.py
│   ├── main.py                    # single entry point / orchestration
│   ├── config.py                  # Pydantic Settings
│   ├── models.py                  # Pydantic row model + SQLAlchemy ORM model
│   ├── extract.py                 # HTTP fetch from ArcGIS
│   ├── transform.py               # normalisation, filtering, row hashing
│   ├── load.py                    # SQLAlchemy SCD2 upsert logic
│   └── exceptions.py              # small custom exception hierarchy
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # shared fixtures (settings, in-memory engine, mock responses)
│   ├── test_extract.py
│   ├── test_transform.py
│   └── test_load.py
├── Dockerfile
├── requirements.txt
├── .pre-commit-config.yaml        # runs ruff check before commits
├── .dockerignore
├── .env.example                   # example local environment variables
├── README.md                      # setup, usage, architecture, cost/network warnings and delivery notes
└── planning.md                    # this file
```

## 5. Components

### 5.1 Config (`etl/config.py`)

A `Settings` class (Pydantic `BaseSettings` via `pydantic-settings`) exposes:

| Field | Source | Example |
|-------|--------|---------|
| `source_url` | static default | ArcGIS feature server query URL |
| `target_states` | static default / env | `["CA"]` |
| `arcgis_page_size` | static default | `1000` |
| `postgres_host` | env | `localhost` / `db` / `mydb.cluster-xxx.eu-west-1.rds.amazonaws.com` |
| `postgres_port` | env | `5432` |
| `postgres_db` | env | `du_chapters` |
| `postgres_user` | env | `etl` |
| `postgres_password` | env / secret | `***` |
| `db_secret_arn` | env | Secrets Manager ARN used by Lambda at runtime |
| `request_timeout` | static default | `30` |
| `log_level` | env | `INFO` |

`target_states` is defined as a list even though it currently contains only `"CA"`, so additional states such as `"OR"` or `"WA"` can be added later without a code change. A comment in `config.py` will make this intent explicit.

**What is `db_secret_arn`?**  
ARN stands for *Amazon Resource Name* — a unique identifier for an AWS resource. The `db_secret_arn` is the ARN of the secret stored in AWS Secrets Manager that contains the RDS username and password. Lambda uses `boto3` to retrieve the secret value by this ARN at runtime, so credentials never need to be stored in environment variables or in the container image.

Environment variables are loaded automatically; `.env` files are supported in local development.

### 5.2 Data models (`etl/models.py`)

- `ChapterRow` (Pydantic): validates `chapter_id`, `chapter_name`, `city`, `state`, `coordinates`.
- `UniversityChapter` (SQLAlchemy declarative): maps the target table, including SCD2 metadata columns.

### 5.3 Extract (`etl/extract.py`)

Functions:

```text
fetch_page(url: str, states: list[str], offset: int, page_size: int, timeout: int) -> dict
fetch_all_chapters(url: str, states: list[str], page_size: int, timeout: int) -> dict
```

- `fetch_page` builds an ArcGIS `query` request with `where State IN (...)`, `resultOffset` and `resultRecordCount`, returning one page.
- `fetch_all_chapters` loops over pages until no more features are returned and merges them into a single response.
- `fetch_page` is decorated with a retry policy from `tenacity` (initial config: 3 attempts, exponential backoff starting at 2 seconds, capping at 10 seconds) so transient network errors do not fail the run.
- Both functions use `requests` with the supplied timeout and raise `ExtractionError` on HTTP errors, timeouts or non-JSON responses.

### 5.4 Transform (`etl/transform.py`)

Functions:

```text
normalise_features(raw: dict) -> list[ChapterRow]
hash_row(row: ChapterRow) -> str
```

- `normalise_features` converts ArcGIS `features[].attributes/geometry` into `ChapterRow` objects and filters to the configured states.
- `hash_row` lower-cases every business value, builds a canonical JSON representation of the row (excluding SCD2 metadata), and returns an MD5 digest. This hash is used to detect changes.

### 5.5 Load (`etl/load.py`)

Functions:

```text
build_engine(settings: Settings) -> Engine
ensure_table(engine: Engine) -> None
load_chapters(session: Session, rows: list[ChapterRow]) -> None
```

- `load_chapters` performs SCD2 upserts inside one transaction:
  1. Query current rows for all incoming `chapter_id`s (`valid_to IS NULL` / `is_current = True`).
  2. For each incoming row:
     - If no current row exists, insert a new current row.
     - If a current row exists and the hash differs, close the old row (`valid_to = now`, `is_current = False`) and insert a new current row.
     - If the hash matches, do nothing.

### 5.6 Entry point (`etl/main.py`)

```text
lambda_handler(event: dict, context: Any) -> None
```

- `lambda_handler()` is the single entry point used by both AWS Lambda and the local Docker Compose run.
- It loads config, creates the SQLAlchemy engine, ensures the table exists, extracts, transforms and loads.
- `etl/__main__.py` simply calls `lambda_handler({}, None)`, so `python -m etl` behaves the same way as an AWS invocation.

On any `ETLError` the handler raises, so AWS treats the invocation as failed and Docker Compose returns a non-zero exit code.

The Docker image uses:

```dockerfile
CMD ["etl.main.lambda_handler"]
```

For local Docker Compose runs the command is overridden to `python -m etl`, which still invokes `lambda_handler()`.

## 6. SCD Type 2 table design

```text
university_chapters
  - id            SERIAL NOT NULL
  - chapter_id    TEXT NOT NULL
  - chapter_name  TEXT NOT NULL
  - city          TEXT NOT NULL
  - state         TEXT NOT NULL
  - coordinates   TEXT NOT NULL
  - row_hash      TEXT NOT NULL
  - valid_from    TIMESTAMP WITH TIME ZONE NOT NULL
  - valid_to      TIMESTAMP WITH TIME ZONE NULL
  - is_current    BOOLEAN NOT NULL DEFAULT TRUE

PRIMARY KEY (id, chapter_id)
```

The `row_hash` lets the pipeline detect any business change without comparing each column individually.

**Indexes**: only the primary key and the SCD2 lookup on `(chapter_id, is_current)` are defined now. Additional indexes for common query patterns should be added once those patterns are known; creating them prematurely is avoided to keep storage and write costs minimal.

## 7. Testing strategy

- **Framework**: `pytest`.
- **HTTP mocking**: `responses` library (or `unittest.mock` if dependency count is a concern).
- **DB tests**: tests connect to a real Postgres database (the same one started by `local_postgres/docker-compose.yml`). SQLAlchemy is used to create a fresh test schema at the start of each test run and roll back between tests.
- **Coverage rule**: every function in `extract.py`, `transform.py` and `load.py` gets at least two tests:
  1. A success / happy-path test.
  2. An error / negative test.

A comment in the test configuration and a note in the `README.md` will make it clear that a running Postgres database is required for the test suite.

Example test pairs:

- `fetch_page`: returns one page on 200; retries and succeeds after a transient failure; raises `ExtractionError` after retries are exhausted.
- `fetch_all_chapters`: concatenates multiple pages; raises `ExtractionError` when any page fails.
- `normalise_features`: returns filtered `ChapterRow` list; raises `TransformationError` on missing geometry.
- `hash_row`: returns the same hash for identical rows; returns different hashes for differing rows.
- `load_chapters`: inserts new rows; closes old rows and inserts new ones when the hash changes.

## 8. Docker & local development

### 8.1 Application image (`Dockerfile`)

- Based on `public.ecr.aws/lambda/python:3.14` so the same image can run as a Lambda function (Python 3.14 is the latest generally available Lambda Python runtime at the time of writing).
- Installs dependencies from `requirements.txt`.
- Copies `etl/` and sets `CMD ["etl.main.lambda_handler"]`.

### 8.2 ETL local testing stack (`docker-compose.yml`)

Runs the ETL container only. It connects to a Postgres container started separately via `local_postgres/docker-compose.yml` by joining the external `du-postgres` Docker network.

- Service `etl`: builds the app image, sets `POSTGRES_HOST=db`, joins the `du-postgres` network, overrides the Lambda CMD to `python -m etl`, runs once and exits.

### 8.3 Postgres-only stack (`local_postgres/docker-compose.yml`)

- Service `db`: Postgres 16 image with healthcheck, exposed on port `5432`, attached to a named network `du-postgres`.
- Used both for local venv runs (`POSTGRES_HOST=localhost`) and as the target for the ETL container (`POSTGRES_HOST=db`).

## 9. Terraform infrastructure

Resources (minimal, default VPC):

- `aws_ecr_repository` (private) for the Lambda image.
- `aws_cloudwatch_log_group` for Lambda logs.
- `aws_iam_role` / policies for Lambda execution (CloudWatch logs) and Secrets Manager read access.
- `aws_lambda_function` with `package_type = Image`.
- `aws_scheduler_schedule` (with its own IAM role/policy) for the daily schedule.
- `aws_sns_topic` + `aws_cloudwatch_metric_alarm` for Lambda failure alerting.
- `aws_secretsmanager_secret` + `aws_secretsmanager_secret_version` for the DB username and password.
- `aws_db_instance` (PostgreSQL `db.t4g.micro`, 20 GB storage, single-AZ, no Multi-AZ).
- `aws_db_subnet_group` and `aws_security_group` for RDS.

**Why `aws_db_subnet_group` and `aws_security_group` are needed**

- `aws_db_subnet_group` tells RDS which VPC subnets the database instances can be placed in. Even when using the default VPC, RDS requires an explicit subnet group so it knows which availability zones are available for the instance.
- `aws_security_group` acts as a virtual firewall for the database. It controls which IP addresses or other security groups are allowed to connect to Postgres on port 5432. This is required to restrict database access to the Lambda function or to a trusted CIDR block, rather than leaving it open to the internet.

Networking choice for cost minimisation:

- Place the RDS instance in the default VPC with `publicly_accessible = true` and a security group that allows ingress from `0.0.0.0/0`, because the Lambda runs outside the VPC and has no predictable egress IP. Access is protected by the generated credentials and TLS; this is demo-only.
- Run the Lambda function outside the VPC so it can reach Secrets Manager and ECR without NAT Gateway or VPC endpoint charges.
- This is acceptable for a short-lived demo/take-home task but would be replaced by private subnets + NAT Gateway or VPC endpoints in a real production environment.

Variables:

- `aws_region`
- `image_uri` (ECR image URI with tag)
- `db_name`, `db_username`
- `schedule_expression` (default `rate(1 day)`)
- `lambda_memory_size` / `lambda_timeout` (default `128` MB / `60` seconds)

Outputs:

- ECR repository URL.
- Lambda function ARN.
- RDS endpoint.
- Secrets Manager ARN.

## 10. CI/CD pipeline

### 10.1 CI (`ci.yml`)

Triggered on pull requests and pushes to `main`:

1. Set up Python 3.14.
2. Start a Postgres service container for the test suite.
3. Install dev dependencies.
4. Run `ruff check .` and `pytest`.

### 10.2 Deploy (`deploy.yml`)

Triggered only on pushes to `main`:

1. Configure AWS credentials via OIDC (no long-lived keys).
2. Log in to Amazon ECR.
3. Build and push the image tagged with the Git SHA.
4. Run `terraform apply` with the new image URI; Terraform creates/updates the RDS instance, secret and Lambda function.

## 11. Pre-commit

A `.pre-commit-config.yaml` file will be added that runs `ruff check .`. This mirrors the lint step in CI so issues are caught before a push. `black` is not included because `ruff` covers the linting needs for this small project.

## 12. Dependencies

A single frozen `requirements.txt` holds both runtime and dev/test dependencies (not worth splitting at this scale). Runtime highlights:

- `pydantic`
- `pydantic-settings`
- `sqlalchemy`
- `psycopg2-binary`
- `requests`
- `tenacity` (retry decorator for API calls)
- `boto3` (used by Lambda to retrieve the DB secret from Secrets Manager)

Dev/test tooling in the same file: `pytest`, `responses` (HTTP mocking), `ruff` (linting), `pre-commit`.

## 13. Risks, assumptions and open decisions

- **API shape**: the ArcGIS field names and geometry structure were discovered by inspecting the service. If the layer changes, only config/field mappings need updating.
- **Pagination**: the pipeline implements ArcGIS `resultOffset` / `resultRecordCount` pagination from the start so it is safe if the state list grows.
- **Postgres in AWS**: Terraform now creates a new RDS PostgreSQL instance (`db.t4g.micro`, 20 GB, single-AZ). `db.t4g.micro` and `db.t3.micro` are currently AWS Free Tier eligible for PostgreSQL, subject to AWS Free Tier limits and credits. Always confirm pricing before deploying.
- **Secrets**: the DB username and password are generated by Terraform and stored in AWS Secrets Manager. Lambda reads the secret at runtime via `boto3`; the password is never passed as a plain Terraform output or Lambda environment variable.
- **Networking / cost trade-off**: to avoid NAT Gateway and VPC endpoint charges, RDS is placed in the default VPC with `publicly_accessible = true` and ingress open to `0.0.0.0/0` (the Lambda runs outside the VPC, so its egress IPs cannot be whitelisted). Access relies on the generated credentials and TLS. This is a pragmatic, low-cost setup for a take-home task but is **not** a production security pattern. The `README.md` carries a clear warning to this effect.
- **Idempotency**: SCD2 means re-running the pipeline with unchanged data is a no-op, and changed data creates a new history row rather than overwriting history.
- **Delivery**: the final codebase will be delivered in a Git repo and collaborator access granted to `Andrew-data-eng` on GitHub/GitLab as requested in the brief.
- **Walkthrough readiness**: the `README.md` will include concise copy/paste commands for running the pipeline locally and inspecting the deployed AWS resources, so it can be demonstrated easily.
- **Monitoring**: logs go to stdout/CloudWatch. Failure is signalled via a non-zero exit code or raised exception so both Docker Compose and AWS mark the run as failed.
