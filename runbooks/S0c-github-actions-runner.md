# Runbook: S0c — GitHub Actions Self-Hosted Runner

**Phase:** Pre-Work · Step 3 of 3
**Estimated time:** ~30 min
**Pause point:** Runner shows `Idle` in GitHub → Settings → Actions → Runners
**Machine:** DISCWORLD (Linux)

---

## Overview

Installs and registers a GitHub Actions self-hosted runner on DISCWORLD.
GitHub-hosted runners have no access to the local network, so any CI job that
needs to reach services on the LAN — LocalStack, PostgreSQL, integration test
containers — must run on this runner instead. DISCWORLD is the right host because
it already runs LocalStack and the full service stack that those jobs depend on.

The runner coexists with all other services on DISCWORLD. It is idle between CI
runs and consumes negligible resources when not executing a job.

**Connects to:** S0b (llama.cpp) is complete. Phase 1 follows.

---

## Prerequisites

- DISCWORLD terminal open (SSH or direct)
- GitHub repository created and accessible (S0a complete)
- `curl` and `tar` available on DISCWORLD: `curl --version && tar --version`

---

## Architecture Decision

**Self-hosted runner on DISCWORLD, not MIDDLEEARTH or ARRAKIS** — DISCWORLD runs
LocalStack and all dependent services. Jobs that need LocalStack must be co-located
with it, or at minimum on the same LAN with the services already running. DISCWORLD
is the natural host. MIDDLEEARTH runs the agent orchestrator and K3s — adding a
runner there mixes concerns. ARRAKIS runs inference — no reason to add CI overhead.

**Self-hosted runner alongside GitHub-hosted runners, not replacing them** — jobs
that don't need LAN access (build, unit tests, Docker build, push to GHCR) run
faster and more reliably on GitHub-hosted runners. The self-hosted runner is used
only when LAN access is required:

| Job type | Runner |
|---|---|
| Build, unit tests, Docker build, push to GHCR | `ubuntu-latest` (GitHub-hosted) |
| Terraform plan against LocalStack | `[self-hosted, linux, discworld]` |
| Integration tests against real containers | `[self-hosted, linux, discworld]` |
| Newman API tests | `[self-hosted, linux, discworld]` |
| Playwright E2E tests | `[self-hosted, linux, discworld]` |

---

## Step-by-Step

### Step 1 — Generate the runner token on GitHub

1. Go to your repository on GitHub
2. Click **Settings** → **Actions** → **Runners** (left sidebar)
3. Click **New self-hosted runner**
4. Select **Linux** as the operating system and **x64** as the architecture
5. GitHub displays a set of commands including a `--token` argument — copy that
   token value. It is valid for **1 hour** from generation.

Do not run the commands shown on the GitHub page — follow the steps below instead,
which add labels and configure the service correctly.

---

### Step 2 — Download the runner on DISCWORLD

GitHub shows the exact latest version on the runner registration page. Use the
version string shown there. The commands below use `2.317.0` as a placeholder —
replace it with whatever GitHub shows.

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.317.0/actions-runner-linux-x64-2.317.0.tar.gz
tar xzf actions-runner-linux-x64.tar.gz
```

---

### Step 3 — Configure the runner

```bash
./config.sh \
  --url https://github.com/YOUR_USERNAME/cloud-reference-arch \
  --token YOUR_RUNNER_TOKEN \
  --name DISCWORLD \
  --labels self-hosted,linux,discworld \
  --work _work \
  --unattended
```

Replace `YOUR_USERNAME` with your GitHub username and `YOUR_RUNNER_TOKEN` with
the token copied in Step 1.

The `--labels` flag sets the labels that CI workflow files use to route jobs to
this runner. `self-hosted` and `linux` are conventional; `discworld` is a
project-specific label that makes targeting unambiguous.

Expected output ending with:

```
√ Runner successfully added
√ Runner connection is good
```

---

### Step 4 — Install and start as a systemd service

```bash
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
```

Status should show `active (running)`.

The service name follows the pattern `actions.runner.USERNAME.REPO.DISCWORLD` —
you can also check it with:

```bash
sudo systemctl status "actions.runner.*"
```

---

## How to Verify

1. Go to your repository on GitHub → **Settings** → **Actions** → **Runners**
2. DISCWORLD should appear in the list with a green **Idle** badge

**Pause point reached** when the green `Idle` badge is visible.

You can also verify the service is running on DISCWORLD:

```bash
sudo ./svc.sh status
# or
sudo systemctl status "actions.runner.*"
```

---

## How CI Jobs Target This Runner

Jobs that need LAN access use the `discworld` label:

```yaml
jobs:
  integration-tests:
    runs-on: [self-hosted, linux, discworld]
    steps:
      - uses: actions/checkout@v4
      - name: Run integration tests
        run: dotnet test tests/integration/
```

Jobs that don't need LAN access continue using GitHub-hosted runners:

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
```

This routing is wired up properly in Phase 12. For now the runner just needs to
be registered and idle.

---

## Automated Tests

No automated tests for this step. Verification is the `Idle` status in GitHub
and a passing job routed to the runner, which will happen naturally in Phase 1
when the first LocalStack-dependent CI job is added.

---

## Common Failures

| Error | Cause | Fix |
|---|---|---|
| `config.sh: Permission denied` | Script not executable | `chmod +x config.sh svc.sh` |
| `Invalid token` during config | Token expired (1h limit) | Go back to GitHub → Settings → Actions → Runners → New self-hosted runner to generate a fresh token |
| `svc.sh: must run as sudo` | Service install requires root | Prefix with `sudo`: `sudo ./svc.sh install` |
| Runner registers but shows `Offline` immediately | Service not started | `sudo ./svc.sh start` then check status |
| Runner shows `Offline` after DISCWORLD reboot | Service not enabled for autostart | `sudo ./svc.sh install` re-registers the systemd unit correctly; verify with `sudo systemctl is-enabled "actions.runner.*"` |
| Job queued but never picked up | Runner is offline or labels don't match | Check runner status in GitHub UI; verify `runs-on` labels match exactly |

---

## AWS Equivalent

Not applicable — the self-hosted runner is a LAN-only concern. When deploying to
real AWS, Terraform-dependent CI jobs run against real AWS endpoints and no longer
need LAN access. The self-hosted runner remains in use throughout local development
but is not part of the AWS deployment pipeline.

---

## Further Reading

- [About self-hosted runners](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/about-self-hosted-runners)
- [Adding self-hosted runners](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/adding-self-hosted-runners)
- [Using self-hosted runners in a workflow](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/using-self-hosted-runners-in-a-workflow)
