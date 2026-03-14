# Runbook: S0a — GitHub Repository & Monorepo Scaffold

**Phase:** Pre-Work · Step 1 of 3
**Estimated time:** ~1 hour
**Pause point:** First green CI run on GitHub Actions
**Machine:** MIDDLEEARTH (WSL2)

---

## Overview

Creates the public GitHub repository and pushes the monorepo directory structure that all 13 phases will build into. Also establishes the minimal CI workflow that confirms the pipeline triggers correctly on push. This is the foundation everything else depends on — no agent work begins until this step is complete and the first CI run is green.

**Connects to:** Nothing precedes this. S0b (llama.cpp install) follows.

---

## Prerequisites

- Git installed on MIDDLEEARTH (WSL2): `git --version`
- GitHub account with SSH key or HTTPS credentials configured
- WSL2 terminal open on MIDDLEEARTH

---

## Architecture Decision

**Public repository** — required for unlimited free GitHub Actions minutes on GitHub-hosted runners. The repo contains no secrets at any point: all sensitive values go in `.env` files excluded by `.gitignore`, or in GitHub Actions encrypted secrets configured via the UI. There is no security cost to making this repo public.

---

## Step-by-Step

### 1. Create the GitHub repository

1. Go to [github.com](https://github.com) → **New repository** (top-right `+` button)
2. Set the following:
   - **Repository name:** `cloud-reference-arch` (or your preferred name)
   - **Visibility:** `Public` ← required for free CI minutes
   - **Initialize this repository with:** leave all boxes **unchecked** — no README, no .gitignore, no license
3. Click **Create repository**
4. Copy the remote URL shown on the next page (SSH: `git@github.com:USERNAME/cloud-reference-arch.git` or HTTPS: `https://github.com/USERNAME/cloud-reference-arch.git`)

---

### 2. Create the monorepo scaffold on MIDDLEEARTH

Open a WSL2 terminal. Run all commands from your preferred projects directory (e.g. `~/projects`).

```bash
mkdir cloud-reference-arch && cd cloud-reference-arch
git init
git remote add origin <YOUR_REMOTE_URL>
```

Create the full directory structure:

```bash
mkdir -p \
  src/backend \
  src/frontend \
  infra/terraform \
  infra/k8s \
  infra/docker \
  infra/localstack \
  .github/workflows \
  tests/integration \
  tests/e2e \
  tests/load \
  tests/security \
  agent \
  runbooks \
  docs
```

---

### 3. Create the root `.gitignore`

```bash
cat > .gitignore << 'EOF'
# .NET
bin/
obj/
*.user
.vs/
*.suo

# Node
node_modules/
dist/
.env.local
.next/

# Terraform
.terraform/
*.tfstate
*.tfstate.backup
.terraform.lock.hcl
*.tfvars
!*.tfvars.example
override.tf
override.tf.json

# Secrets
.env
.env.aws
!.env.example

# JetBrains / Rider
.idea/

# OS
.DS_Store
Thumbs.db
desktop.ini
EOF
```

---

### 4. Create the root `README.md`

```bash
cat > README.md << 'EOF'
# Cloud Reference Architecture

Production-grade cloud system template built on constrained home hardware.
Local stack → one-command AWS deployment.

## Stack

| Layer | Local | AWS |
|---|---|---|
| Relational DB | PostgreSQL (Docker) | RDS PostgreSQL |
| Document DB | MongoDB (Docker) | DocumentDB |
| Cache | Redis (Docker) | ElastiCache |
| Message Queue | RabbitMQ (Docker) | SQS |
| Event Streaming | Apache Kafka (Docker) | MSK / Kinesis |
| File Storage | LocalStack S3 | S3 |
| Auth | Keycloak + LocalStack Cognito | Cognito |
| Orchestration | K3s | EKS / ECS |
| IaC | Terraform + tflocal | Terraform |
| CI/CD | GitHub Actions | GitHub Actions + ECR |
| Monitoring | Prometheus + Grafana | CloudWatch + Grafana |

## Phases

| # | Phase |
|---|---|
| 1 | Docker + LocalStack + Terraform |
| 2 | PostgreSQL + EF Core |
| 3 | MongoDB |
| 4 | Redis (cache + pub/sub) |
| 5 | Auth (Keycloak + Cognito) |
| 6 | React frontend |
| 7 | File storage (S3) |
| 8 | Message queuing (RabbitMQ + SQS) |
| 9 | Event streaming (Kafka) |
| 10 | Container orchestration (K3s) |
| 11 | Monitoring (Prometheus + Grafana) |
| 12 | CI/CD pipeline |
| 13 | Load, stress & security testing |

See `/runbooks` for per-phase documentation generated during build.

## AWS Deployment

One-time manual setup (~1 hour), then:

```bash
terraform apply       # creates full environment
terraform destroy     # removes everything, billing stops
```

## Local → AWS Switch

```bash
# Local (LocalStack on DISCWORLD)
AWSSDK_ENDPOINT_URL=http://DISCWORLD:4566

# AWS (real endpoints)
# unset AWSSDK_ENDPOINT_URL
```

Same Docker image. Same code. Same Terraform HCL. Only the variable changes.
EOF
```

---

### 5. Add `.gitkeep` files to empty directories

Git does not track empty directories. Add placeholder files so the structure is preserved in the repo:

```bash
find . -type d -not -path './.git/*' | while read dir; do
  [ -z "$(ls -A "$dir")" ] && touch "$dir/.gitkeep"
done
```

> **Note:** The more common `-exec touch {}/.gitkeep \;` form can silently fail in WSL2 depending on how the shell handles the backslash-semicolon terminator when pasted. The `while read` loop avoids this entirely.

Verify the directories are now tracked:

```bash
find . -name '.gitkeep' | sort
```

Expected output:

```
./agent/.gitkeep
./docs/.gitkeep
./infra/docker/.gitkeep
./infra/k8s/.gitkeep
./infra/localstack/.gitkeep
./infra/terraform/.gitkeep
./runbooks/.gitkeep
./src/backend/.gitkeep
./src/frontend/.gitkeep
./tests/e2e/.gitkeep
./tests/integration/.gitkeep
./tests/load/.gitkeep
./tests/security/.gitkeep
```

---

### 6. Create the GitHub Actions CI workflow

```bash
cat > .github/workflows/ci.yml << 'EOF'
name: CI

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main]

jobs:
  scaffold-check:
    name: Verify monorepo structure
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Verify directory structure
        run: |
          DIRS=(
            "src/backend"
            "src/frontend"
            "infra/terraform"
            "infra/k8s"
            "infra/docker"
            "infra/localstack"
            "tests/integration"
            "tests/e2e"
            "tests/load"
            "tests/security"
            "agent"
            "runbooks"
            "docs"
          )

          ALL_OK=true
          for dir in "${DIRS[@]}"; do
            if [ -d "$dir" ]; then
              echo "✓ $dir"
            else
              echo "✗ MISSING: $dir"
              ALL_OK=false
            fi
          done

          if [ "$ALL_OK" = false ]; then
            echo ""
            echo "One or more required directories are missing."
            exit 1
          fi

          echo ""
          echo "All required directories present."
EOF
```

---

### 7. Commit and push

```bash
git add .
git commit -m "chore: initial monorepo scaffold"
git branch -M main
git push -u origin main
```

Expected push output (SSH):

```
Enumerating objects: X, done.
Counting objects: 100% (X/X), done.
Writing objects: 100% (X/X), ...
To git@github.com:USERNAME/cloud-reference-arch.git
 * [new branch]      main -> main
branch 'main' set up to track 'origin/main'.
```

---

## How to Verify

1. Go to your repository on GitHub
2. Click the **Actions** tab
3. You should see one workflow run: **CI** triggered by the push to `main`
4. Click into it → click `scaffold-check` job
5. The **Verify directory structure** step should show all `✓` lines and exit 0
6. The overall run shows a green checkmark ✅

**Pause point reached** when the green checkmark appears.

You can also verify locally:

```bash
# Confirm remote is set correctly
git remote -v

# Confirm one commit on main
git log --oneline

# Confirm working tree is clean
git status
```

---

## Automated Tests

The `scaffold-check` job in `ci.yml` verifies all expected directories exist. It fails fast (non-zero exit) if any are missing, blocking any future jobs that might depend on the structure.

---

## Common Failures

| Error | Cause | Fix |
|---|---|---|
| `push rejected (non-fast-forward)` | GitHub auto-initialized with a README | `git pull origin main --allow-unrelated-histories`, resolve the merge, push again. Better: never check "Initialize" on repo creation. |
| Actions tab shows no runs | Workflow YAML has a syntax error | Check indentation — GitHub Actions is whitespace-sensitive. Validate at [yaml.org/spec](https://yaml.org). |
| `Permission denied (publickey)` | SSH key not added to GitHub | Add key at github.com/settings/keys, or switch remote to HTTPS: `git remote set-url origin https://github.com/USERNAME/REPO.git` |
| `ci.yml` job fails on directory check | A `mkdir -p` command was skipped or typo'd | Re-run the `mkdir -p` block, run `find . -name '.gitkeep' | sort` to verify, commit, push again. |

---

## AWS Equivalent

Not applicable — this step is GitHub only. No AWS resources are created or required.

---

## Further Reading

- [GitHub Actions quickstart](https://docs.github.com/en/actions/quickstart)
- [About GitHub-hosted runners](https://docs.github.com/en/actions/using-github-hosted-runners/about-github-hosted-runners)
- [Monorepo tooling overview](https://monorepo.tools)
- [Checkout action v4](https://github.com/actions/checkout)
