# Runbook: Phase 1b — Terraform Modules (S3 + DynamoDB against LocalStack)

**Phase:** 1 · Sub-phase b
**Estimated time:** 2–4h (agent-driven, unattended)
**Pause point:** `tflocal apply` and `tflocal destroy` both exit 0 in CI on the self-hosted runner
**Machine:** DISCWORLD (CI execution) · MIDDLEEARTH (code authoring, agent)

---

## Overview

Writes the first Terraform modules targeting LocalStack — an S3 bucket and a DynamoDB table. Adds a CI job that runs `tflocal init → apply → assert resources exist → destroy` on the self-hosted runner on DISCWORLD, where LocalStack is reachable. This is the first end-to-end test of the full loop: agent writes IaC → CI runs it → LocalStack executes it → tests confirm correctness.

**Connects to:** Phase 1a (LocalStack running). Phase 2 (PostgreSQL) follows; the Terraform patterns established here are reused for every subsequent AWS resource.

---

## Prerequisites

- Phase 1a complete: LocalStack health check passing on DISCWORLD
- Self-hosted runner `DISCWORLD` showing `Idle` in GitHub (S0c complete)
- `LOCALSTACK_AUTH_TOKEN` secret added to GitHub Actions (Phase 1a, Step 5)
- Terraform 1.8+ and `tflocal` installed on DISCWORLD

### Install Terraform and tflocal on DISCWORLD

```bash
# Terraform
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install -y terraform

# tflocal (LocalStack Terraform wrapper)
pip install terraform-local --break-system-packages

# Verify
terraform version
tflocal version
```

---

## Architecture Decision

**`tflocal` over raw Terraform with provider overrides** — `tflocal` is a thin wrapper that automatically injects `endpoint` overrides for every AWS provider resource, pointing them at LocalStack. The alternative — manually specifying `endpoint` on every resource — creates a maintenance burden and makes the HCL diverge from what would be used against real AWS. With `tflocal`, the Terraform code is identical for local and AWS; only the command changes (`tflocal` vs `terraform`).

**Local state for Phase 1** — Terraform remote state (S3 + DynamoDB lock table) is a real AWS concern set up manually before AWS deployment. For local development against LocalStack, local state files are sufficient and simpler. The `terraform.tfstate` file is gitignored.

**Separate `modules/` directories** — each AWS service gets its own module. This mirrors how production Terraform projects are organized and makes each module independently testable and reusable.

---

## Repository Changes

### Directory structure added

```
infra/terraform/
├── main.tf              # Root module: calls child modules
├── variables.tf         # Input variables (region, endpoint URL)
├── outputs.tf           # Output values (bucket name, table name)
├── terraform.tfvars     # Local variable values (gitignored)
├── terraform.tfvars.example  # Committed placeholder
└── modules/
    ├── s3/
    │   ├── main.tf
    │   ├── variables.tf
    │   └── outputs.tf
    └── dynamodb/
        ├── main.tf
        ├── variables.tf
        └── outputs.tf
```

---

## Terraform Code

### `infra/terraform/variables.tf`

```hcl
variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (local, staging, production)"
  type        = string
  default     = "local"
}

variable "project_name" {
  description = "Project name prefix for all resources"
  type        = string
  default     = "cloud-ref"
}
```

### `infra/terraform/main.tf`

```hcl
terraform {
  required_version = ">= 1.8"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # LocalStack override — tflocal injects endpoint automatically.
  # When targeting real AWS, these are omitted (or env vars are unset).
  access_key = "test"
  secret_key = "test"

  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}

module "s3" {
  source       = "./modules/s3"
  project_name = var.project_name
  environment  = var.environment
}

module "dynamodb" {
  source       = "./modules/dynamodb"
  project_name = var.project_name
  environment  = var.environment
}
```

### `infra/terraform/outputs.tf`

```hcl
output "s3_bucket_name" {
  description = "Name of the S3 bucket"
  value       = module.s3.bucket_name
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB table"
  value       = module.dynamodb.table_name
}
```

### `infra/terraform/terraform.tfvars.example`

```hcl
aws_region   = "us-east-1"
environment  = "local"
project_name = "cloud-ref"
```

### `infra/terraform/modules/s3/main.tf`

```hcl
resource "aws_s3_bucket" "main" {
  bucket = "${var.project_name}-${var.environment}-bucket"

  tags = {
    Environment = var.environment
    Project     = var.project_name
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket_versioning" "main" {
  bucket = aws_s3_bucket.main.id
  versioning_configuration {
    status = "Enabled"
  }
}
```

### `infra/terraform/modules/s3/variables.tf`

```hcl
variable "project_name" { type = string }
variable "environment"  { type = string }
```

### `infra/terraform/modules/s3/outputs.tf`

```hcl
output "bucket_name" {
  value = aws_s3_bucket.main.id
}

output "bucket_arn" {
  value = aws_s3_bucket.main.arn
}
```

### `infra/terraform/modules/dynamodb/main.tf`

```hcl
resource "aws_dynamodb_table" "main" {
  name         = "${var.project_name}-${var.environment}-table"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"

  attribute {
    name = "PK"
    type = "S"
  }

  tags = {
    Environment = var.environment
    Project     = var.project_name
    ManagedBy   = "terraform"
  }
}
```

### `infra/terraform/modules/dynamodb/variables.tf`

```hcl
variable "project_name" { type = string }
variable "environment"  { type = string }
```

### `infra/terraform/modules/dynamodb/outputs.tf`

```hcl
output "table_name" {
  value = aws_dynamodb_table.main.name
}

output "table_arn" {
  value = aws_dynamodb_table.main.arn
}
```

---

## CI Workflow

Added to `.github/workflows/ci.yml` as a new job:

```yaml
  terraform-localstack:
    name: Terraform plan/apply/destroy (LocalStack)
    runs-on: [self-hosted, linux, discworld]
    needs: scaffold-check

    env:
      AWS_ACCESS_KEY_ID: test
      AWS_SECRET_ACCESS_KEY: test
      AWS_DEFAULT_REGION: us-east-1
      LOCALSTACK_AUTH_TOKEN: ${{ secrets.LOCALSTACK_AUTH_TOKEN }}

    defaults:
      run:
        working-directory: infra/terraform

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Install tflocal
        run: pip install terraform-local --break-system-packages --quiet

      - name: Copy tfvars
        run: cp terraform.tfvars.example terraform.tfvars

      - name: Init
        run: tflocal init

      - name: Validate
        run: tflocal validate

      - name: Apply
        run: tflocal apply -auto-approve

      - name: Assert S3 bucket exists
        run: |
          BUCKET_NAME=$(tflocal output -raw s3_bucket_name)
          aws --endpoint-url=http://localhost:4566 s3api head-bucket --bucket "$BUCKET_NAME"
          echo "✓ S3 bucket $BUCKET_NAME exists"

      - name: Assert DynamoDB table exists
        run: |
          TABLE_NAME=$(tflocal output -raw dynamodb_table_name)
          aws --endpoint-url=http://localhost:4566 dynamodb describe-table --table-name "$TABLE_NAME" --query "Table.TableStatus" --output text
          echo "✓ DynamoDB table $TABLE_NAME exists"

      - name: Destroy
        if: always()
        run: tflocal destroy -auto-approve
```

> **Note:** `if: always()` on the destroy step ensures resources are cleaned up even if an assertion fails. This prevents stale LocalStack state from polluting subsequent runs.

---

## How to Verify

| Check | What to look for |
|---|---|
| GitHub Actions → CI job `terraform-localstack` | All steps green, including Assert steps |
| Apply output | Shows `aws_s3_bucket.main` and `aws_dynamodb_table.main` created |
| Assert S3 | Prints `✓ S3 bucket cloud-ref-local-bucket exists` |
| Assert DynamoDB | Prints table status `ACTIVE` and `✓` confirmation |
| Destroy output | Shows both resources destroyed, `Destroy complete! Resources: 2 destroyed.` |
| State after destroy | No resources in LocalStack; `tflocal state list` returns empty |

**Pause point reached** when the full job — init → validate → apply → assert × 2 → destroy — completes with green checkmarks.

---

## Manual Verification (optional, run from DISCWORLD)

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
tflocal init
tflocal apply -auto-approve

# Check S3
aws --endpoint-url=http://localhost:4566 s3 ls

# Check DynamoDB
aws --endpoint-url=http://localhost:4566 dynamodb list-tables

# Clean up
tflocal destroy -auto-approve
```

---

## Automated Tests

The CI job itself is the automated test for this phase. The assertion steps act as integration tests: they call the LocalStack API directly (via the AWS CLI) to confirm the resources Terraform reported creating actually exist and are accessible.

---

## Common Failures

| Error | Cause | Fix |
|---|---|---|
| `tflocal: command not found` in CI | pip install didn't add to PATH | Use `python3 -m pip install terraform-local` or add `~/.local/bin` to PATH |
| `Error: Failed to query available provider packages` | No internet on self-hosted runner | Terraform providers need to download on first `init`; check runner network access |
| `head-bucket: 404` on assert | Apply succeeded but bucket name mismatch | Check `tflocal output s3_bucket_name` matches what the assert step is using |
| `Destroy` step skipped when apply fails | `if: always()` missing | Ensure the destroy step has `if: always()` |
| `credential` errors in Terraform | `skip_*` flags missing from provider config | Confirm `skip_credentials_validation`, `skip_metadata_api_check`, `skip_requesting_account_id` are all `true` in `main.tf` |
| LocalStack not reachable from CI job | Runner not on DISCWORLD, or LocalStack stopped | Confirm job uses `runs-on: [self-hosted, linux, discworld]`; `docker ps` on DISCWORLD to confirm LocalStack is running |

---

## AWS Equivalent

When deploying to real AWS:

- Replace `tflocal` with `terraform`
- Remove `access_key = "test"`, `secret_key = "test"`, and the three `skip_*` flags from the provider block
- Add the remote state backend to `main.tf` (S3 bucket + DynamoDB lock table, created manually in the one-time AWS setup)
- The module code itself (`modules/s3/`, `modules/dynamodb/`) is **identical** — no changes required

The CI job for AWS deployments would use `terraform plan` (not apply) as a dry-run gate, with actual apply triggered manually or on merge to main.

---

## Further Reading

- [tflocal (LocalStack Terraform wrapper)](https://github.com/localstack/terraform-local)
- [Terraform AWS provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [Terraform module structure](https://developer.hashicorp.com/terraform/language/modules/develop/structure)
- [LocalStack Terraform guide](https://docs.localstack.cloud/user-guide/integrations/terraform/)
