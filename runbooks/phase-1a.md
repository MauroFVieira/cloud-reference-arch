# Runbook: Phase 1a — Docker Compose & LocalStack

**Phase:** 1 · Sub-phase a
**Estimated time:** ~1 hour
**Pause point:** `curl http://DISCWORLD:4566/_localstack/health` returns `running` for all configured services, verified from MIDDLEEARTH
**Machine:** DISCWORLD (setup) · MIDDLEEARTH (verification)

---

## Overview

Installs Docker on DISCWORLD and brings up LocalStack via Docker Compose. LocalStack is the local emulator for AWS services — every phase from here through Phase 13 depends on it. Once this sub-phase is complete, the entire LAN can reach AWS-compatible S3, DynamoDB, SQS, Secrets Manager, Cognito, and API Gateway endpoints at `http://DISCWORLD:4566`.

**Connects to:** S0c (self-hosted runner) is complete. Phase 1b (Terraform modules) follows immediately.

---

## Prerequisites

- DISCWORLD terminal open (SSH or direct)
- MIDDLEEARTH WSL2 terminal open for verification
- Free LocalStack account with Auth Token: [app.localstack.cloud](https://app.localstack.cloud) → Account → Auth Token
- Monorepo cloned on DISCWORLD (or at minimum `infra/docker/` directory created)

---

## Architecture Decision

**LocalStack CE over alternatives (Moto, fake-s3, etc.)** — LocalStack emulates the full AWS API surface in a single container with a single endpoint. Moto is Python-only; fake-s3 is S3-only. LocalStack supports every service used in this project and its endpoint URL override pattern (`AWSSDK_ENDPOINT_URL`) works identically with all SDK languages and Terraform.

**DISCWORLD as the LocalStack host** — DISCWORLD runs all stateful services. MIDDLEEARTH runs the agent orchestrator and K3s; adding LocalStack there would mix concerns and consume RAM needed for K3s in later phases. ARRAKIS runs inference and messaging. LocalStack belongs with the service stack.

**Docker Compose over bare Docker** — Compose adds a named volume for LocalStack state persistence across container restarts and makes the service trivially reproducible. All subsequent service additions (PostgreSQL, MongoDB, Redis, etc.) will be added to the same Compose file.

**Services enabled now:** `s3,dynamodb,sqs,secretsmanager,cognito-idp,apigateway` — the full set needed across all 13 phases. Enabling them upfront avoids restarting LocalStack between phases.

---

## Step-by-Step

### Step 1 — Install Docker on DISCWORLD

```bash
# Check if already installed
docker --version

# If not installed:
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker run --rm hello-world
```

Expected: `Hello from Docker!` message confirms Docker is working.

---

### Step 2 — Create the Docker Compose file

In the monorepo at `infra/docker/localstack.docker-compose.yml`:

```yaml
services:
  localstack:
    image: localstack/localstack:3
    container_name: localstack
    ports:
      - "4566:4566"
    environment:
      - SERVICES=s3,dynamodb,sqs,secretsmanager,cognito-idp,apigateway
      - DEBUG=0
      - LOCALSTACK_AUTH_TOKEN=${LOCALSTACK_AUTH_TOKEN}
    volumes:
      - localstack_data:/var/lib/localstack
      - /var/run/docker.sock:/var/run/docker.sock
    restart: unless-stopped

volumes:
  localstack_data:
```

> **Note:** `restart: unless-stopped` ensures LocalStack comes back up after DISCWORLD reboots without manual intervention.

---

### Step 3 — Create `.env.example` in the repo root

This file is committed to the repository. It documents all required environment variables without exposing real values.

```bash
# LocalStack
LOCALSTACK_AUTH_TOKEN=your_localstack_auth_token_here

# AWS SDK endpoint override
# Set to LocalStack for local dev; unset for real AWS
AWSSDK_ENDPOINT_URL=http://DISCWORLD:4566

# AWS credentials (LocalStack accepts any non-empty value)
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
AWS_DEFAULT_REGION=us-east-1
```

---

### Step 4 — Create a local `.env` on DISCWORLD

This file is **not committed** (already in `.gitignore`). It holds real values.

```bash
cd infra/docker
cp ../../.env.example .env
```

Edit `.env` and replace `your_localstack_auth_token_here` with your actual token from [app.localstack.cloud](https://app.localstack.cloud).

---

### Step 5 — Add the LocalStack auth token to GitHub Actions secrets

Required for the CI job added in Phase 1b. Do this once now.

1. Go to your repository on GitHub
2. **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `LOCALSTACK_AUTH_TOKEN`, Value: your actual token
5. Click **Add secret**

---

### Step 6 — Start LocalStack on DISCWORLD

```bash
cd infra/docker
docker compose -f localstack.docker-compose.yml --env-file .env up -d
```

Watch the startup logs to confirm services initialize:

```bash
docker logs -f localstack
```

Wait for output containing:

```
Ready.
```

This typically takes 20–40 seconds on first start (image pull adds time on first run).

---

### Step 7 — Verify from MIDDLEEARTH

Open a WSL2 terminal on MIDDLEEARTH and run:

```bash
curl http://DISCWORLD:4566/_localstack/health | python3 -m json.tool
```

Expected response (all services show `"running"` or `"available"`):

```json
{
  "services": {
    "apigateway": "running",
    "cognito-idp": "running",
    "dynamodb": "running",
    "s3": "running",
    "secretsmanager": "running",
    "sqs": "running"
  },
  "version": "3.x.x"
}
```

**Pause point reached** when all configured services show `running`.

---

### Step 8 — Commit

```bash
git add infra/docker/localstack.docker-compose.yml .env.example
git commit -m "feat(infra): add LocalStack Docker Compose config"
git push
```

Confirm the CI `scaffold-check` job stays green (no new CI logic yet — that's Phase 1b).

---

## How to Verify

| Check | Command | Expected |
|---|---|---|
| Docker running | `docker ps` | `localstack` container listed, status `Up` |
| Health endpoint | `curl http://DISCWORLD:4566/_localstack/health` | All services `running` |
| Volume persists | `docker compose restart` then re-curl health | Still `running` (state preserved) |
| Reachable from MIDDLEEARTH | Run curl from MIDDLEEARTH WSL2 | Same JSON response |

---

## Automated Tests

None in this sub-phase — infrastructure setup only. The first automated verification is the Terraform CI job added in Phase 1b, which creates and destroys real resources against this LocalStack instance.

---

## Common Failures

| Error | Cause | Fix |
|---|---|---|
| `docker: command not found` | Docker not installed | Run the install script in Step 1 |
| `permission denied` on `docker` commands | User not in `docker` group | `sudo usermod -aG docker $USER && newgrp docker` |
| LocalStack exits immediately | Missing or invalid `LOCALSTACK_AUTH_TOKEN` | Check token at app.localstack.cloud; verify `.env` file is in the same directory as the compose file |
| Health check shows service `error` (not `running`) | Service failed to initialize | `docker logs localstack` for details; usually resolves on `docker compose restart` |
| `curl: Could not resolve host: DISCWORLD` from MIDDLEEARTH | Hostname not resolvable on LAN | Use DISCWORLD's IP address instead, or add `DISCWORLD <IP>` to `/etc/hosts` on MIDDLEEARTH |
| Port 4566 refused from MIDDLEEARTH | Firewall blocking | `sudo ufw allow 4566` on DISCWORLD |

---

## AWS Equivalent

LocalStack running at `http://DISCWORLD:4566` emulates the entire set of AWS services used in this project. When deploying to real AWS, `AWSSDK_ENDPOINT_URL` is unset and the SDK resolves to real AWS regional endpoints automatically. No code changes required — only the environment variable changes.

---

## Further Reading

- [LocalStack Docker Compose setup](https://docs.localstack.cloud/getting-started/installation/#docker-compose)
- [LocalStack Auth Token](https://docs.localstack.cloud/getting-started/auth-token/)
- [LocalStack health endpoint](https://docs.localstack.cloud/references/internal-endpoints/)
