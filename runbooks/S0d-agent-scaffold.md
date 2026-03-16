# Runbook: S0d — LangGraph Agent Scaffold

**Phase:** Pre-Work · Step 4 of 4
**Estimated time:** ~3–4h (including environment issues)
**Pause point:** Smoke test completes — agent creates a file, commits it, polls CI until green, prints `✓ Smoke test passed.`
**Machine:** MIDDLEEARTH (WSL2)

---

## Overview

Builds the autonomous agent that runs Phases 1–13. A LangGraph state machine running on MIDDLEEARTH orchestrates four specialist roles — Coder, CI Watcher, Tester, Documenter — using Claude Sonnet 4.6 as the reasoning brain via the Anthropic API, and Qwen2.5-Coder 14B on ARRAKIS for bulk code generation. All shell commands execute inside a sandboxed Docker container bind-mounted to the repo. GitHub authentication uses a GitHub App so the agent commits as a named actor (`cloud-ref-agent`) with auditable, scoped permissions. Git operations (add, commit, push) are handled entirely by the orchestrator — Claude never issues git commands directly.

**Connects to:** S0c (self-hosted runner) is complete, llama-server is running on ARRAKIS. Phase 1 follows once the smoke test passes.

---

## Architecture

```
MIDDLEEARTH (WSL2)
└── agent/ (Python, LangGraph)
    ├── orchestrator.py       # LangGraph state machine — routes between nodes
    ├── nodes/
    │   ├── coder.py          # Calls Qwen for bulk code generation (scaffolded)
    │   ├── ci_watcher.py     # CI polling specialist (scaffolded)
    │   ├── tester.py         # Test runner specialist (scaffolded)
    │   └── documenter.py     # Runbook writer specialist (scaffolded)
    ├── tools/
    │   ├── shell.py          # Runs commands in the sandbox container
    │   ├── files.py          # Read/write files in the repo
    │   └── github.py         # GitHub App auth, API polling, log retrieval
    ├── llm/
    │   ├── claude_client.py  # Anthropic API (Sonnet 4.6) — orchestration + docs
    │   └── qwen_client.py    # llama-server on ARRAKIS — code generation
    ├── state.py              # LangGraph state schema
    ├── config.py             # Env vars, model names, retry limits
    └── smoke_test.py         # End-to-end verification

Sandbox container (Docker on MIDDLEEARTH)
└── ubuntu:24.04
    ├── /repo                      (bind-mounted from ~/cloud-reference-arch)
    ├── /home/user/.gitconfig      (bind-mounted temp file with GitHub App token)
    ├── dotnet 8, terraform, tflocal, git, aws cli
    └── Runs as host user UID:GID — no root-owned files written to repo
```

---

## Cost Profile

| Metric | Value |
|---|---|
| Smoke test (clean run) | ~$0.03 |
| Estimated cost per simple task | $0.15–0.30 |
| Estimated cost per medium task | $0.40–0.80 |
| Estimated cost per complex task + debug loop | $0.80–1.50 |
| **Estimated total, all 13 phases** | **$40–80** |

Cost is dominated by debugging loops on CI failures. Message history truncation (`MAX_HISTORY_MESSAGES = 6`) and tool result truncation (3,000 chars) keep per-iteration token counts bounded.

---

## Prerequisites

- S0a, S0b, S0c complete
- `llama-server` running on ARRAKIS: `curl http://ARRAKIS:8080/health` → `{"status":"ok"}`
- Docker running on MIDDLEEARTH WSL2 **without sudo** (see Docker Fix section)
- Anthropic API key with credits added **before** key creation (see Step 2)
- GitHub App created and installed on the repo (Step 1)

---

## Docker Fix (WSL2 + Snap)

Docker installed via snap requires specific steps. The standard `systemctl enable docker` approach does not work — snap manages its own service and has no systemd unit.

```bash
# Create group and add user
sudo groupadd docker 2>/dev/null || true
sudo usermod -aG docker $USER

# Close this terminal. Open a NEW WSL2 terminal tab.
# newgrp only patches the current shell — a new terminal is required.
```

In the new terminal:

```bash
sudo adduser $USER docker
sudo snap connect docker:home

# Fix socket ownership (snap race condition)
sudo chown root:docker /var/run/docker.sock

# Make permanent via daemon config
sudo tee /var/snap/docker/current/config/daemon.json > /dev/null << 'EOF'
{
    "group": "docker"
}
EOF
sudo snap restart docker
```

**If socket stays `root:root` after all of the above** — replace snap Docker with apt Docker:

```bash
sudo snap remove docker

sudo apt update && sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin
sudo usermod -aG docker $USER
sudo service docker start
```

Close terminal, open new one, verify:

```bash
groups                        # docker must appear
docker run --rm hello-world   # must succeed without sudo
ls -la /var/run/docker.sock   # must show root:docker
```

---

## Step 1 — Create the GitHub App

The agent commits code, reads CI logs, and polls run status. A GitHub App scopes these permissions precisely and appears in the repo audit log as `cloud-ref-agent`.

1. **github.com → Settings → Developer settings → GitHub Apps → New GitHub App**
2. Set:
   - **Name:** `cloud-ref-agent` (globally unique — add a suffix if taken)
   - **Homepage URL:** `https://github.com/YOUR_USERNAME/cloud-reference-arch`
   - **Webhook:** uncheck "Active"
3. **Repository permissions:**
   - Contents: **Read & write**
   - Actions: **Read**
   - Metadata: **Read** (mandatory)
4. **Where can this app be installed:** Only on this account
5. Click **Create GitHub App**
6. Click **Generate a private key** → save the `.pem` to `~/.config/cloud-ref-agent/private-key.pem`
7. Note the **App ID** shown on the settings page
8. Click **Install App** → your account → select `cloud-reference-arch` only → Install
9. Note the **Installation ID** from the URL after install: `github.com/settings/installations/XXXXXXX`

To confirm the correct installation ID at any time:

```bash
python3 - << 'EOF'
import jwt, time, httpx
from pathlib import Path
key = Path.home() / ".config/cloud-ref-agent/private-key.pem"
now = int(time.time())
token = jwt.encode({"iat": now-60, "exp": now+600, "iss": "YOUR_APP_ID"}, key.read_text(), algorithm="RS256")
resp = httpx.get("https://api.github.com/app/installations",
    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
for i in resp.json():
    print(f"ID: {i['id']}  account: {i['account']['login']}")
EOF
```

---

## Step 2 — Get an Anthropic API Key

> **Critical:** Add billing credits **before** generating the API key. Keys created before credits are added enter a broken state where they return `400 credit balance too low` even after top-up, and show "last used: never" indefinitely. Generate a new key after confirming credits — it will work immediately.

1. **console.anthropic.com → Plans & Billing** — confirm credits are showing
2. **API Keys → Create Key** — name it `cloud-ref-agent`
3. Copy immediately (not shown again)
4. `echo "sk-ant-..." > ~/.config/cloud-ref-agent/anthropic-api-key`

---

## Step 3 — Python environment

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv
python3 -m venv ~/venvs/agent
source ~/venvs/agent/bin/activate
pip install \
  langgraph==0.2.* langchain-core anthropic \
  PyJWT cryptography httpx pydantic python-dotenv
echo 'source ~/venvs/agent/bin/activate' >> ~/.bashrc
```

---

## Step 4 — Install agent source files

Extract `agent-scaffold.zip` into `~/cloud-reference-arch/`. The zip extracts to an `agent-scaffold/agent/` subdirectory — move its contents to `~/cloud-reference-arch/agent/`:

```bash
cd ~
unzip agent-scaffold.zip
cp -r agent-scaffold/agent/* ~/cloud-reference-arch/agent/
rm -rf agent-scaffold/
```

Verify structure:

```bash
ls ~/cloud-reference-arch/agent/
# config.py  llm/  nodes/  orchestrator.py  sandbox/  smoke_test.py  state.py  tools/
```

---

## Step 5 — Build the sandbox Docker image

```bash
cd ~/cloud-reference-arch/agent/sandbox
docker build -t cloud-ref-sandbox:latest .
```

First build takes 5–10 minutes (downloads .NET, Terraform, AWS CLI). Subsequent builds use the layer cache.

Verify:

```bash
docker run --rm cloud-ref-sandbox:latest dotnet --version   # 8.0.x
docker run --rm cloud-ref-sandbox:latest terraform version  # 1.14.7
docker run --rm cloud-ref-sandbox:latest git --version      # 2.x
```

---

## Step 6 — Environment configuration

```bash
mkdir -p ~/.config/cloud-ref-agent
cat > ~/.config/cloud-ref-agent/.env << 'EOF'
GITHUB_APP_ID=your_app_id_here
GITHUB_INSTALLATION_ID=your_installation_id_here
GITHUB_REPO=YOUR_USERNAME/cloud-reference-arch
QWEN_BASE_URL=http://ARRAKIS:8080
EOF
```

> **WSL2 warning:** If this file is created or edited in Windows (Notepad, VS Code), run `sed -i 's/\r//' ~/.config/cloud-ref-agent/.env` to strip CRLF line endings. CRLF embeds `\r` into variable values, causing `httpx.InvalidURL` errors during GitHub API calls.

Load before running:

```bash
export $(cat ~/.config/cloud-ref-agent/.env | xargs)
```

---

## Step 7 — Run the smoke test

```bash
source ~/venvs/agent/bin/activate
export $(cat ~/.config/cloud-ref-agent/.env | xargs)
cd ~/cloud-reference-arch
python -m agent.smoke_test
```

Expected terminal output:

```
Logging to: ~/.config/cloud-ref-agent/logs/agent-TIMESTAMP.log
Prerequisites OK. Starting agent...

  [claude] sending (1 messages in history)...
  [claude] 2.5s — calling: ['write_file']
  [sandbox] ...
  [claude] sending (3 messages in history)...
  [claude] 1.8s — calling: ['task_complete']
  [sandbox] cd /repo && git add "docs/agent-smoke-test.md" && git commit -m '...'
  [sandbox] exit=0 in 0.5s
  [sandbox] cd /repo && git push origin main
  [sandbox] exit=0 in 2.1s
  [git] pushed abc1234
Polling CI for commit abc1234...
  Run 12345678: status=in_progress, conclusion=None
  Run 12345678: status=completed, conclusion=success
  [claude] sending (1 messages in history)...
  [git] pushed def5678

✓ Smoke test passed. Agent loop is fully operational.
  Full log: ~/.config/cloud-ref-agent/logs/agent-TIMESTAMP.log
```

**Pause point reached** when `✓ Smoke test passed.` appears and the commit is visible on GitHub.

> The CI poll step takes as long as the GitHub Actions run (~1–2 minutes). The agent prints a status line every 30 seconds. It is not stuck — do not interrupt.

> If the agent pauses for human input, press Enter in the **original terminal** (the one where you ran `python -m agent.smoke_test`). Pressing Enter in any other terminal has no effect.

---

## Key Design Decisions

**Git handled by orchestrator, not Claude** — Claude never issues git commands. The `task_complete` tool signals readiness; the orchestrator performs `git add`, `commit`, and `push` exactly once per task. This eliminates the double-commit pattern that occurs when Claude independently commits and then commits again after verifying.

**GitHub App token injected via mounted `.gitconfig`** — a temporary `.gitconfig` is written with the installation token as a URL rewrite rule and mounted read-only into every container. Every sandbox run has valid credentials without SSH keys or persistent credential storage. The temp file is deleted after every `docker run` call.

**`--user $(uid):$(gid)` on docker run** — the container runs as your host user so all files written to the bind-mounted repo are owned by you. Without this, Docker writes files as root, causing git ownership warnings and requiring `sudo chown` after every run.

**`safe.directory` baked into the image** — the Dockerfile sets `git config --global --add safe.directory /repo` at build time. The mounted `.gitconfig` overrides identity and credentials at runtime but the safe.directory setting persists across all container runs.

**Message history truncation** — `agent_node` keeps the initial task message plus the last `MAX_HISTORY_MESSAGES` (6) exchanges. Tool results are truncated to 3,000 characters. This bounds token cost per task regardless of iteration count.

---

## Common Failures

| Error | Cause | Fix |
|---|---|---|
| `Unit docker.service does not exist` | Docker installed via snap — no systemd unit | Use `sudo snap restart docker`; do not use `systemctl` |
| `docker.sock` owned by `root:root` after group add | Snap socket race condition | `sudo chown root:docker /var/run/docker.sock && sudo snap restart docker`; make permanent via `daemon.json` in `/var/snap/docker/current/config/` |
| `snap "docker" has no plug named "docker-executables"` | Plug removed in newer snap versions | Skip that command; only `sudo snap connect docker:home` is needed |
| Socket stays `root:root` despite all snap fixes | Persistent snap bug on some Ubuntu configs | Replace snap Docker with apt Docker (see Docker Fix section) |
| `400 credit balance too low` | API key created before credits were added | Generate a new key after confirming credits; old keys do not recover |
| Key shows "last used: never" after topping up | Same broken key state | New key required |
| `httpx.InvalidURL: Invalid non-printable ASCII '\r'` | CRLF line endings in `.env` | `sed -i 's/\r//' ~/.config/cloud-ref-agent/.env` |
| `TypeError: Issuer (iss) must be a string` | `GITHUB_APP_ID` passed as int to JWT | Fixed in `github.py` — `str(GITHUB_APP_ID)` used in payload |
| `401 Unauthorized` on installations endpoint | Wrong installation ID, or CRLF in the value | List installations via `/app/installations`; strip CRLF |
| `messages.N.content: Input should be a valid dictionary` | `None` in content blocks list | Fixed in `orchestrator.py` — blocks built conditionally |
| Agent double-commits same file | Claude issuing git commands before `task_complete` | Fixed — git blocked in `execute_tool`; all commits go through `task_complete` handler |
| Files written as root in repo | `docker run` missing `--user` flag | Fixed in `shell.py` — `--user $(uid):$(gid)` on every run |
| `fatal: detected dubious ownership at '/repo'` | `safe.directory` not set in container | Fixed — baked into Dockerfile |
| `git push` times out (300s) | Missing credentials — hangs on auth prompt | Fixed — token injected via mounted `.gitconfig` URL rewrite |
| Enter key does nothing at human checkpoint | Pressing Enter in wrong terminal | Return to the original terminal running the agent |
| Sandbox image missing at startup | Not built, or built before docker group fix | `cd agent/sandbox && docker build -t cloud-ref-sandbox:latest .` |

---

## AWS Equivalent

Not applicable — the agent stack is local only and is not deployed to AWS. It calls `http://ARRAKIS:8080` and `api.anthropic.com` regardless of whether the application stack targets LocalStack or real AWS.

---

## Further Reading

- [LangGraph documentation](https://langchain-ai.github.io/langgraph/)
- [Anthropic tool use guide](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- [Anthropic prompt caching](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)
- [GitHub Apps documentation](https://docs.github.com/en/apps)
- [llama.cpp server OpenAI compatibility](https://github.com/ggerganov/llama.cpp/blob/master/examples/server/README.md#openai-compatible-api)
