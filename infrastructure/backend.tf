# Terraform state backend configuration.

terraform {
  backend "s3" {
    bucket       = "techtest-p4p-cw"
    key          = "du-university-chapters-etl/terraform.tfstate"
    region       = "eu-north-1"
    encrypt      = true
    use_lockfile = true
  }
}
