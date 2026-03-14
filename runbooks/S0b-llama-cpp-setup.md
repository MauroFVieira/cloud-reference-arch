# Runbook: S0b — llama.cpp Setup & First Token

**Phase:** Pre-Work · Step 2 of 3
**Estimated time:** 1.5–2h
**Pause point:** First token confirmed via `curl` against `llama-server` on ARRAKIS
**Machines:** ARRAKIS (Linux) · MIDDLEEARTH (WSL2, build only) · DISCWORLD (Linux, build only)

---

## Overview

Builds llama.cpp on all three machines, downloads Qwen2.5-Coder 14B Q4 via the
Hugging Face CLI, and runs `llama-server` directly on ARRAKIS. The HF CLI is
installed and the model is downloaded directly on ARRAKIS — no transfer between
machines needed. The model (~8 GB) fits entirely in ARRAKIS's 12 GB RAM, so no
RPC is used — local memory access consistently outperforms remote memory access
over the LAN. The LangGraph agent on MIDDLEEARTH calls `http://ARRAKIS:8080`.

DISCWORLD is not involved in inference at any point — its RAM is fully reserved
for LocalStack and the service stack.

llama.cpp is still built with `-DLLAMA_RPC=ON` on all machines so the `rpc-server`
binary is available if experimentation is needed later.

**Connects to:** S0a (repo scaffold) is complete. S0c (self-hosted runner) follows.

---

## Prerequisites

- All three machines are on the same LAN and reachable by hostname
- MIDDLEEARTH: WSL2 terminal open
- DISCWORLD and ARRAKIS: SSH or direct terminal access
- Free Hugging Face account with a read-only access token (huggingface.co/settings/tokens)

---

## Architecture Decision

**llama.cpp over alternatives (Ollama, vLLM, etc.)** — llama.cpp runs on CPU-only
hardware, supports RPC for RAM pooling across machines, and exposes an
OpenAI-compatible HTTP API. Ollama does not support RPC. vLLM requires a GPU.

**Qwen2.5-Coder 14B Q4 over 7B** — the 14B produces meaningfully better code
generation results. At ~3–8 tok/s on ARRAKIS the agent still operates efficiently:
it generates code, commits, then waits several minutes for CI — inference speed is
not on the critical path.

**llama-server directly on ARRAKIS, not RPC from MIDDLEEARTH** — the 14B Q4
(~8 GB) fits entirely in ARRAKIS's 12 GB RAM. Testing with RPC confirmed ~0.9 tok/s
due to LAN round-trip overhead on every transformer layer. Running llama-server
locally on ARRAKIS eliminates this overhead entirely. MIDDLEEARTH's stronger CPU
is not an advantage when 100% of model layers are remote — it only handles
coordination, not computation.

**DISCWORLD excluded from inference entirely** — running LocalStack, PostgreSQL,
MongoDB, Redis, and Keycloak simultaneously leaves insufficient RAM headroom to
safely add any inference load.

**Hugging Face CLI over browser download** — the CLI will be reused by the agent
to pull updated or alternative models non-interactively. Installing it now avoids
a second setup step later.

---

## Step-by-Step

### Step 1 — Install build dependencies

Run on **all three machines** (MIDDLEEARTH in WSL2, DISCWORLD and ARRAKIS natively):

```bash
sudo apt update && sudo apt install -y \
  git \
  build-essential \
  cmake \
  curl \
  python3 \
  python3-pip \
  python3-venv
```

---

### Step 2 — Clone and build llama.cpp

Run on **all three machines**:

```bash
git clone https://github.com/ggerganov/llama.cpp.git ~/llama.cpp
cd ~/llama.cpp
cmake -B build -DLLAMA_RPC=ON
cmake --build build --config Release -j$(nproc)
```

The `-DLLAMA_RPC=ON` flag builds both `llama-server` and `rpc-server`.
Build time is roughly 5–10 minutes per machine depending on core count.

Verify the build produced the required binaries:

```bash
ls build/bin/llama-server build/bin/rpc-server
```

Both should be present on all three machines.

---

### Step 3 — Install Hugging Face CLI

Run on **ARRAKIS only**. A virtual environment is used to avoid conflicts with
the system Python.

```bash
python3 -m venv ~/venvs/hf
source ~/venvs/hf/bin/activate
pip install huggingface_hub[cli]
```

Add venv activation to `~/.bashrc` on ARRAKIS so `hf` is always available in
new terminals:

```bash
echo 'source ~/venvs/hf/bin/activate' >> ~/.bashrc
source ~/.bashrc
```

Verify:

```bash
hf --version
```

Log in with your Hugging Face account (read-only token is sufficient):

```bash
hf auth login
```

Paste your access token when prompted. Tokens are at huggingface.co/settings/tokens.

---

### Step 4 — Download the model

Run on **ARRAKIS only**:

```bash
mkdir -p ~/models
hf download \
  bartowski/Qwen2.5-Coder-14B-Instruct-GGUF \
  Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf \
  --local-dir ~/models
```

Downloads a single ~8 GB file with progress shown in the terminal.
Final path on ARRAKIS: `~/models/Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf`

If the download is interrupted, re-run the same command — it resumes automatically.

---

### Step 5 — Start llama-server on ARRAKIS

Run on **ARRAKIS**:

```bash
~/llama.cpp/build/bin/llama-server \
  --model ~/models/Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf \
  --host 0.0.0.0 \
  --port 8080 \
  --ctx-size 4096
```

Expected output while loading:

```
llama_model_load: loading model from ...
...
main: server is listening on 0.0.0.0:8080
```

Wait for the `server is listening` line before proceeding to Step 6.

---

### Step 6 — Verify: first token

Run from **MIDDLEEARTH** (WSL2) to confirm the server is reachable over the LAN:

```bash
curl http://ARRAKIS:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-coder",
    "messages": [{"role": "user", "content": "Reply with one word: ready"}],
    "max_tokens": 5
  }'
```

Expected response:

```json
{
  "choices": [{
    "message": { "role": "assistant", "content": "Ready" }
  }]
}
```

**Pause point reached** when a valid JSON response with content is returned.

Note the `predicted_per_second` figure from the response's `timings` field —
record it in the dev log as your performance baseline.

---

### Step 7 — Make llama-server persistent (recommended)

To avoid manually restarting the server after a reboot, add a systemd service on
**ARRAKIS**. Replace `YOUR_USER` with the actual username:

```bash
sudo tee /etc/systemd/system/llama-server.service > /dev/null << 'EOF'
[Unit]
Description=llama.cpp Server
After=network.target

[Service]
ExecStart=/home/YOUR_USER/llama.cpp/build/bin/llama-server --model /home/YOUR_USER/models/Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf --host 0.0.0.0 --port 8080 --ctx-size 4096
Restart=on-failure
User=YOUR_USER

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable llama-server
sudo systemctl start llama-server
sudo systemctl status llama-server
```

Status output should show `active (running)`.

---

## How to Verify

| Check | Command | Expected |
|---|---|---|
| Binaries exist (all machines) | `ls ~/llama.cpp/build/bin/llama-server ~/llama.cpp/build/bin/rpc-server` | Both paths print |
| Model file present on ARRAKIS | `ls -lh ~/models/Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf` | ~8 GB file |
| Server health | `curl http://ARRAKIS:8080/health` | `{"status":"ok"}` |
| Inference working | Full curl in Step 7 from MIDDLEEARTH | Valid JSON with content |
| Token speed acceptable | `predicted_per_second` in timings | >1 tok/s (expect 3–8) |

---

## Automated Tests

None for this step — it is infrastructure setup, not application code. Verification
is manual via the curl commands above. The agent will exercise the API on every
code generation task starting from Phase 1.

---

## Common Failures

| Error | Cause | Fix |
|---|---|---|
| `rpc-server: not found` after build | RPC flag missing from cmake | Rebuild: `cmake -B build -DLLAMA_RPC=ON` then `cmake --build build --config Release -j$(nproc)` |
| `hf: command not found` | venv not activated | `source ~/venvs/hf/bin/activate` or open a new terminal (if added to `.bashrc`) |
| Download fails partway | Network interruption | Re-run the same `hf download` command — it resumes from where it stopped |

| `curl` from MIDDLEEARTH returns nothing | llama-server still loading, or firewall | Wait for `server is listening`; if already up, `sudo ufw allow 8080` on ARRAKIS |
| Token generation slow (~0.9 tok/s) | RPC overhead if accidentally using RPC | Confirm llama-server is running on ARRAKIS directly with no `--rpc` flag |
| Token generation slow due to swap | Model + services exceeding ARRAKIS RAM | Check `htop` on ARRAKIS; reduce `--ctx-size` to `2048` and restart |

---

## Downgrading to 7B

If the 14B causes memory pressure on ARRAKIS once services are running, the
downgrade path is:

1. Download the 7B model directly on ARRAKIS:
   ```bash
   hf download \
     Qwen/Qwen2.5-Coder-7B-Instruct-GGUF \
     qwen2.5-coder-7b-instruct-q4_k_m.gguf \
     --local-dir ~/models
   ```
2. Restart `llama-server` on ARRAKIS with the new `--model` path
3. Alternatively, run `llama-server` on MIDDLEEARTH instead (7B fits in its 16 GB RAM),
   installing the HF CLI there using the same venv approach as Step 3
4. Update the agent's `LLAMA_BASE_URL` env var to point to whichever host is serving

---

## AWS Equivalent

Not applicable — the LLM stack is local only and is not deployed to AWS. The agent
calls `http://ARRAKIS:8080` regardless of whether the application stack is pointing
at LocalStack or real AWS.

---

## Further Reading

- [llama.cpp server documentation](https://github.com/ggerganov/llama.cpp/blob/master/examples/server/README.md)
- [llama.cpp RPC mode documentation](https://github.com/ggerganov/llama.cpp/blob/master/docs/rpc.md)
- [Hugging Face CLI reference](https://huggingface.co/docs/huggingface_hub/en/guides/cli)
- [Qwen2.5-Coder 14B GGUF model card](https://huggingface.co/bartowski/Qwen2.5-Coder-14B-Instruct-GGUF)
