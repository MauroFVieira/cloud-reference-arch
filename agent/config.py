import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / ".config/cloud-ref-agent/.env")

# Command timeouts (seconds) — review logs after each phase to tighten these
TIMEOUTS = {
    "git":        30,    # commit, push, pull
    "dotnet":    360,    # build, test, restore
    "terraform":  90,    # init, apply, destroy
    "docker":    180,    # docker build inside sandbox
    "default":    60,
}

# Paths
CONFIG_DIR = Path.home() / ".config" / "cloud-ref-agent"
REPO_ROOT  = Path.home() / "cloud-reference-arch"

# Anthropic
ANTHROPIC_API_KEY = (CONFIG_DIR / "anthropic-api-key").read_text().strip()
CLAUDE_MODEL      = "claude-sonnet-4-6"

# Qwen (local)
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "http://ARRAKIS:8080").strip()
QWEN_MODEL    = "qwen2.5-coder"

# GitHub App
GITHUB_APP_ID          = int(os.getenv("GITHUB_APP_ID", "0").strip())
GITHUB_INSTALLATION_ID = int(os.getenv("GITHUB_INSTALLATION_ID", "0").strip())
GITHUB_PRIVATE_KEY     = (CONFIG_DIR / "private-key.pem").read_text().strip()
GITHUB_REPO            = os.getenv("GITHUB_REPO", "YOUR_USERNAME/cloud-reference-arch").strip()

# Agent behaviour
MAX_TASK_COST_USD = 0.50   # abort and request human input if exceeded
MAX_RETRIES       = 3      # fix attempts before pausing for human input
POLL_INTERVAL     = 30     # seconds between CI status checks
SANDBOX_IMAGE     = "cloud-ref-sandbox:latest"