# Runbook: Phase 1b — Terraform Modules (S3 + DynamoDB against LocalStack)

**Phase:** 1 · Sub-phase b
**Estimated time:** ~2h (manual)
**Pause point:** `tflocal apply` and `tflocal destroy` both exit 0 in CI on the self-hosted runner
**Machine:** DISCWORLD (CI execution) · MIDDLEEARTH (repo)

---

## Overview

Writes the first Terraform modules targeting LocalStack — an S3 bucket and a DynamoDB table. Adds a CI job that runs `tflocal init → apply → assert resources exist → destroy` on the self-hosted runner on DISCWORLD, where LocalStack is reachable. All files are placed manually; no agent involvement is needed for this phase. This is the first end-to-end test of the IaC pipeline: code in repo → CI on DISCWORLD → LocalStack executes it → assertions confirm correctness.

**Connects to:** Phase 1a (LocalStack running). Phase 2 (PostgreSQL) follows; the Terraform patterns established here are reused for every subsequent AWS resource.

---

## Prerequisites

- Phase 1a complete: LocalStack health check passing on DISCWORLD
- Self-hosted runner `DISCWORLD` showing `Idle` in GitHub (S0c complete)
- `LOCALSTACK_AUTH_TOKEN` secret added to GitHub Actions (Phase 1a, Step 5)
- Terraform 1.14+, `tflocal`, and AWS CLI v2 installed on DISCWORLD

### Install Terraform on DISCWORLD

The HashiCorp apt repository can be unreliable on some Linux configurations. The zip installer is simpler and more reliable:

```bash
TERRAFORM_VERSION=1.14.7
wget https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip
unzip terraform_${TERRAFORM_VERSION}_linux_amd64.zip
sudo mv terraform /usr/local/bin/
rm terraform_${TERRAFORM_VERSION}_linux_amd64.zip
terraform version
```

> **Note:** If you prefer the apt route, the gpg step requires `--batch --yes` flags to avoid hanging: `wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg`. Even with that fix, apt may refuse to read the repo on some machines — the zip install avoids both issues entirely.

### Install tflocal on DISCWORLD

Install with `sudo` so the binary lands in `/usr/local/bin` and is available system-wide, including to the GitHub Actions runner process:

```bash
sudo pip install terraform-local --break-system-packages
tflocal version
```

> **Note:** Installing without `sudo` places the binary in `~/.local/bin`, which is not on PATH for the runner. Since tflocal is a project-wide tool, system-wide install is correct. It does not need to be installed in CI — the runner uses the system installation.

### Install AWS CLI v2 on DISCWORLD

The AWS CLI is used in CI assertion steps to verify that resources actually exist in LocalStack after `terraform apply`. Install once system-wide:

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip awscliv2.zip
sudo ./aws/install
rm -rf awscliv2.zip aws/
aws --version
```

> **Note:** Same reasoning as tflocal — install once on DISCWORLD, do not install in CI. The runner picks it up from the system PATH.

---

## Architecture Decision

**`tflocal` over raw Terraform with provider overrides** — `tflocal` is a thin wrapper that automatically injects `endpoint` overrides for every AWS provider resource, pointing them at LocalStack. The alternative — manually specifying `endpoint` on every resource — creates a maintenance burden and makes the HCL diverge from what would be used against real AWS. With `tflocal`, the Terraform code is identical for local and AWS; only the command changes (`tflocal` vs `terraform`).

**Local state for Phase 1** — Terraform remote state (S3 + DynamoDB lock table) is a real AWS concern set up manually before AWS deployment. For local development against LocalStack, local state files are sufficient and simpler. The `terraform.tfstate` file is gitignored.

**Separate `modules/` directories** — each AWS service gets its own module. This mirrors how production Terraform projects are organized and makes each module independently testable and reusable.

**Tools installed system-wide on DISCWORLD, not in CI** — Terraform, tflocal, and the AWS CLI are all installed once on the runner machine rather than being downloaded on every CI run. This avoids `sudo: no tty present` errors in headless runners, reduces job duration, and keeps CI steps free of package management noise. This pattern applies to all subsequent phases.

---

## Repository Changes

### Directory structure added

```
infra/terraform/
├── main.tf                   # Root module: calls child modules
├── variables.tf              # Input variables (region, environment, project name)
├── outputs.tf                # Output values (bucket name, table name)
├── terraform.tfvars          # Local variable values (gitignored)
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

  # LocalStack credentials — tflocal injects the endpoint automatically.
  # When targeting real AWS, remove these lines and the skip_* flags below.
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

Added to `.github/workflows/ci.yml` as a new job. Terraform, tflocal, and the AWS CLI are all pre-installed on DISCWORLD — no install steps needed in CI.

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

> **Note:** `if: always()` on the destroy step ensures resources are cleaned up even if an assertion fails, preventing stale LocalStack state from polluting subsequent runs.

---

## Commit and Push

Copy all files from the zip into the repo, then commit and push from the repo root on MIDDLEEARTH:

```bash
git add \
  .env.example \
  .github/workflows/ci.yml \
  infra/terraform/

git commit -m "feat(infra): Terraform modules for S3 and DynamoDB against LocalStack"
git push
```

This triggers the CI pipeline. Navigate to the **Actions** tab on GitHub to watch the run. The `terraform-localstack` job will be queued behind `scaffold-check` and will pick up on the DISCWORLD self-hosted runner.

> **Note:** `terraform.tfstate`, `terraform.tfstate.backup`, and `infra/terraform/.terraform/` are all gitignored and should not appear in `git status`. If they do, check that the root `.gitignore` from S0a is present and correct.

---

## How to Verify

| Check | What to look for |
|---|---|
| GitHub Actions → CI job `terraform-localstack` | All steps green, including both Assert steps |
| Apply output | Shows `aws_s3_bucket.main` and `aws_dynamodb_table.main` created |
| Assert S3 | Prints `✓ S3 bucket cloud-ref-local-bucket exists` |
| Assert DynamoDB | Prints table status `ACTIVE` and `✓` confirmation |
| Destroy output | `Destroy complete! Resources: 2 destroyed.` |

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

The CI job itself is the automated test for this phase. The assertion steps act as integration tests: they call the LocalStack API directly via the AWS CLI to confirm the resources Terraform reported creating actually exist and are accessible.

---

## Common Failures

| Error | Cause | Fix |
|---|---|---|
| `tflocal: command not found` in CI | Installed without `sudo`, landed in `~/.local/bin` | Reinstall with `sudo pip install terraform-local --break-system-packages` |
| `aws: command not found` in CI | AWS CLI not installed on DISCWORLD | Install AWS CLI v2 system-wide (see Prerequisites) |
| `sudo: no tty present` in CI | Attempting a `sudo` command in a headless runner | Install tools system-wide on DISCWORLD before CI runs, not inside CI steps |
| `Error: Failed to query available provider packages` | No internet on self-hosted runner during `init` | Terraform downloads the AWS provider on first `init`; check runner outbound network access |
| `head-bucket: 404` on Assert S3 | Bucket name mismatch | Check `tflocal output s3_bucket_name` matches the name used in the assert step |
| `Destroy` step skipped when apply fails | `if: always()` missing | Ensure the destroy step has `if: always()` |
| `credential` errors in Terraform | `skip_*` flags missing from provider config | Confirm all three `skip_*` flags are `true` in `infra/terraform/main.tf` |
| LocalStack not reachable from CI job | Runner not on DISCWORLD, or LocalStack stopped | Confirm `runs-on: [self-hosted, linux, discworld]`; run `docker ps` on DISCWORLD |

---

## AWS Equivalent

When deploying to real AWS:

- Replace `tflocal` with `terraform`
- Remove `access_key = "test"`, `secret_key = "test"`, and the three `skip_*` flags from the provider block
- Add the remote state backend to `main.tf` (S3 bucket + DynamoDB lock table, created in the one-time manual AWS setup)
- The module code itself (`modules/s3/`, `modules/dynamodb/`) is **identical** — no changes required

The CI job for AWS deployments uses `terraform plan` as a dry-run gate on every push, with actual `apply` triggered on merge to main.

---

## Further Reading

- [tflocal (LocalStack Terraform wrapper)](https://github.com/localstack/terraform-local)
- [Terraform AWS provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [Terraform module structure](https://developer.hashicorp.com/terraform/language/modules/develop/structure)
- [LocalStack Terraform guide](https://docs.localstack.cloud/user-guide/integrations/terraform/)
- [AWS CLI v2 installation](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
