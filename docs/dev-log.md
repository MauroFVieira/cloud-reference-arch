# Dev Log — Cloud Reference Architecture

---

## 2026-03-16

### S0d · LangGraph Agent Scaffold ✅

| | |
|---|---|
| **Status** | Done |
| **Duration** | ~4h (environment issues) |
| **Pause point reached** | Smoke test green — one commit pushed to remote, CI passed, documenter wrote runbook entry |
| **API cost (smoke test, clean run)** | $0.03 |
| **Machine** | MIDDLEEARTH (WSL2) |

**What was done:**
- Created GitHub App `cloud-ref-agent` with Contents R/W + Actions Read permissions; generated private key
- Provisioned Anthropic API key (second key — first was created before credits, entered broken state)
- Set up Python venv with LangGraph, anthropic, PyJWT, httpx
- Built sandbox Docker image (`ubuntu:24.04` + .NET 8 + Terraform + tflocal + AWS CLI)
- Wrote full agent scaffold: `orchestrator.py`, `state.py`, `config.py`, `smoke_test.py`, `tools/`, `llm/`, `nodes/`
- Smoke test passed on final run: file written, committed, pushed, CI polled to green, runbook entry committed ✅

**Issues encountered and resolved:**

| Issue | Resolution |
|---|---|
| Docker installed via snap — `systemctl enable docker` failed | Replaced snap Docker with apt Docker (snap socket race condition never resolved) |
| `docker.sock` owned by `root:root` despite `--group docker` flag on dockerd | snap bug; resolved by switching to apt Docker which creates socket correctly |
| `400 credit balance too low` on first API key | Key created before credits were added; generated new key after confirming billing — worked immediately |
| `messages.N.content.0: Input should be a valid dictionary` | `None` entry in content_blocks list when Claude returned tool calls with no text; fixed with conditional block construction |
| `git push` timeout (300s) | Sandbox container had no git credentials; fixed by injecting GitHub App token via mounted `.gitconfig` with URL rewrite |
| Agent looping / double commits | Claude issuing git commands independently; fixed by blocking git in `execute_tool` and routing all commits through `task_complete` handler |
| Files written as root in repo | `docker run` without `--user` flag; fixed with `--user $(uid):$(gid)` and `/home/user` directory in image |
| `fatal: dubious ownership at /repo` | `safe.directory` not persisting across container runs; fixed by baking into Dockerfile |
| `httpx.InvalidURL: '\r' at position 50` | CRLF line endings in `.env` file from Windows editing; fixed with `sed -i 's/\r//'` |
| `TypeError: Issuer (iss) must be a string` | `GITHUB_APP_ID` cast to int; fixed with `str()` in JWT payload |
| `401 Unauthorized` on installations endpoint | Installation ID had CRLF; resolved after `.env` fix |
| Enter at human checkpoint did nothing | User pressed Enter in new terminal, not original agent terminal; added explicit "return to THIS terminal" message |

**Architecture decisions confirmed during implementation:**
- Git owned entirely by orchestrator — Claude never calls git commands; only `task_complete` triggers a commit
- GitHub App token injected per-run via temp `.gitconfig` mounted into sandbox — no persistent secrets in container
- Message history capped at 6 exchanges + initial task message — reduces cost from ~$0.17/run to ~$0.03/run
- Tool results truncated to 3,000 chars — prevents large build outputs from bloating context

**Actual vs predicted cost:**
- Original estimate: $7–15 total for all 13 phases
- Revised estimate after debugging runs: $40–80 total
- Clean smoke test: $0.03 (in line with revised per-task estimate)
- Debugging iterations before fixes: $0.17, $0.05, $0.03 (decreasing as bugs resolved)

**Runbook:** `runbooks/S0d-agent-scaffold.md`

---

## 2026-03-15

### Phase 1b · Terraform Modules (S3 + DynamoDB) 🔧

| | |
|---|---|
| **Status** | CI run in progress — awaiting final green |
| **Duration** | ~2h (manual, no agent) |
| **Machine** | DISCWORLD (CI execution) · MIDDLEEARTH (repo) |

**What was done:**
- Installed Terraform `1.14.7` via direct zip download — apt repo approach abandoned
  - `gpg --dearmor` pipe hung with default flags; resolved with `--batch --yes`, but apt subsequently refused to read the HashiCorp repo
  - Zip install from `releases.hashicorp.com` worked cleanly; binary moved to `/usr/local/bin/`
- Installed `tflocal` with `sudo pip install terraform-local --break-system-packages`
  - Installing without `sudo` placed the binary in `~/.local/bin`, not on PATH for the runner; `sudo` installs to `/usr/local/bin` instead
- Installed AWS CLI v2 system-wide on DISCWORLD
  - Required for CI assertion steps (`aws s3api head-bucket`, `aws dynamodb describe-table`)
  - `aws: command not found` surfaced mid-CI; resolved by installing via official zip installer
- All IaC files created and placed in the repo manually (no agent involvement)
- `ci.yml` updated incrementally across multiple pushes as issues surfaced:
  - Removed `Install tflocal` step (sudo without terminal error)
  - Removed `Install AWS CLI` step (same reason)
- Committing IaC files together with `runbooks/phase-1b.md` to trigger the next CI run

**Lessons learned:**
- Phase 1b required no agent — the IaC is fully specified in the runbook and straightforward to place manually
- Incomplete prerequisite instructions (missing AWS CLI, wrong install method for tflocal) caused the 2h duration; runbook has been updated to reflect the correct steps
- Pattern established: install all CI tools system-wide on DISCWORLD once; never install inside CI steps

**Runbook:** `runbooks/phase-1b.md`

---

### Phase 1a · Docker Compose & LocalStack ✅

| | |
|---|---|
| **Status** | Done |
| **Duration** | 30 min |
| **Pause point reached** | `curl http://DISCWORLD:4566/_localstack/health` returning `running` for all active services, verified from MIDDLEEARTH |
| **Machine** | DISCWORLD (setup) · MIDDLEEARTH (verification) |

**What was done:**
- Installed Docker on DISCWORLD
- Created `infra/docker/localstack.docker-compose.yml` with LocalStack CE 3, named volume for state persistence, `restart: unless-stopped`
- Created `.env.example` in repo root (committed); `.env` with real token on DISCWORLD (gitignored)
- Added `LOCALSTACK_AUTH_TOKEN` as a GitHub Actions repository secret
- Started LocalStack via Docker Compose; health check confirmed from MIDDLEEARTH ✅

**Observations:**
- `cognito-idp` does not appear in the LocalStack CE health response — not listed as running or disabled
- Decision: drop `cognito-idp` from the `SERVICES` env var; use **Keycloak exclusively** for authentication throughout the project (Phases 5+). LocalStack Cognito will not be used. The cloud-parity story for auth becomes: Keycloak locally → real AWS Cognito for AWS deployments (configured via Terraform, not emulated locally)
- All other configured services (`s3`, `dynamodb`, `sqs`, `secretsmanager`, `apigateway`) confirmed running ✅

**Runbook:** `runbooks/phase-1a.md`

---

## 2026-03-14

### S0c · GitHub Actions Self-Hosted Runner ✅

| | |
|---|---|
| **Status** | Done |
| **Duration** | 20 min |
| **Pause point reached** | Runner showing `Idle` in GitHub → Settings → Actions → Runners |
| **Machine** | DISCWORLD (Linux) |

**What was done:**
- Downloaded and extracted GitHub Actions runner on DISCWORLD
- Configured runner with name `DISCWORLD` and labels `self-hosted,linux,discworld`
- Installed and started as a systemd service
- Runner confirmed `Idle` in GitHub ✅

**Runbook:** `runbooks/S0c-github-actions-runner.md`

---

### S0b · llama.cpp Setup & First Token ✅

| | |
|---|---|
| **Status** | Done |
| **Duration** | 3h (local delays downloading and starting the language model) |
| **Pause point reached** | First token confirmed via `curl` from MIDDLEEARTH against `llama-server` on ARRAKIS |
| **Machines** | ARRAKIS (llama-server) · MIDDLEEARTH + DISCWORLD (build only) |

**What was done:**
- Built llama.cpp with `-DLLAMA_RPC=ON` on all three machines
- Installed Hugging Face CLI in a venv on ARRAKIS (`~/venvs/hf`)
- Downloaded Qwen2.5-Coder 14B Q4 directly on ARRAKIS (`~/models/Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf`, ~8 GB)
- Confirmed 14B fits entirely in ARRAKIS's 12 GB RAM — no RPC needed
- RPC via MIDDLEEARTH tested and discarded: measured ~0.9 tok/s due to LAN round-trip overhead
- `llama-server` running directly on ARRAKIS on port 8080
- First token confirmed from MIDDLEEARTH via `curl http://ARRAKIS:8080` — baseline: ~1.6 tok/s predicted, ~1.0 tok/s prompt (to be revisited once full service stack is running on ARRAKIS)
- `llama-server` configured as a systemd service on ARRAKIS

**Runbook:** `runbooks/S0b-llama-cpp-setup.md`

---

### S0a · GitHub Repository & Monorepo Scaffold ✅

| | |
|---|---|
| **Status** | Done |
| **Duration** | 50 min |
| **Pause point reached** | First green CI run on GitHub Actions |
| **Machine** | MIDDLEEARTH (WSL2) |

**What was done:**
- Created public GitHub repository `cloud-reference-arch`
- Pushed full monorepo directory structure (13 directories across `src/`, `infra/`, `tests/`, `agent/`, `runbooks/`, `docs/`)
- Added root `.gitignore` covering .NET, Node, Terraform, secrets, OS files
- Added root `README.md` with phase table and stack reference
- Added `.gitkeep` files to all empty directories
- Created `.github/workflows/ci.yml` with `scaffold-check` job
- First CI run green ✅

**Runbook:** `runbooks/S0a-github-repo-scaffold.md`

---

<!-- New entries go above this line, most recent first -->
