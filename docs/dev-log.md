# Dev Log — Cloud Reference Architecture

---

## 2026-03-14

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
