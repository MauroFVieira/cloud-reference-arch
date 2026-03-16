import subprocess
import tempfile
import os
import time
import logging
from pathlib import Path
from agent.config import SANDBOX_IMAGE, REPO_ROOT, TIMEOUTS
from agent.tools.github import _get_installation_token
from agent.config import GITHUB_REPO

logger = logging.getLogger(__name__)

def _write_gitconfig(token: str) -> str:
    """
    Write a temporary .gitconfig with credentials and safe.directory.
    Returns the path to the temp file.
    """
    owner_repo = GITHUB_REPO  # e.g. MauroFVieira/cloud-reference-arch
    content = f"""[user]
    name = cloud-ref-agent
    email = agent@cloud-ref.local
[safe]
    directory = /repo
[url "https://x-access-token:{token}@github.com/"]
    insteadOf = https://github.com/
[url "https://x-access-token:{token}@github.com/"]
    insteadOf = git@github.com:
"""
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.gitconfig', delete=False)
    tmp.write(content)
    tmp.flush()
    return tmp.name

def run_in_sandbox(command: str, timeout: int | None = None) -> tuple[int, str, str]:
    if timeout is None:
        cmd_lower = command.strip().split()[0].lower()
        timeout = (
            TIMEOUTS["git"]       if "git" in cmd_lower else
            TIMEOUTS["dotnet"]    if "dotnet" in cmd_lower else
            TIMEOUTS["terraform"] if "tflocal" in cmd_lower or "terraform" in cmd_lower else
            TIMEOUTS["docker"]    if "docker" in cmd_lower else
            TIMEOUTS["default"]
        )

    token = _get_installation_token()
    gitconfig_path = _write_gitconfig(token)

    try:
        docker_cmd = [
            "docker", "run", "--rm",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--env", "HOME=/home/user",
            "-v", f"{REPO_ROOT}:/repo",
            "-v", f"{gitconfig_path}:/home/user/.gitconfig:ro",
            "--network", "host",
            SANDBOX_IMAGE,
            "bash", "-c", command
        ]

        safe_command = command[:120] + ("..." if len(command) > 120 else "")
        logger.info(f"SANDBOX >>> {safe_command}")
        print(f"  [sandbox] {safe_command}", flush=True)

        start = time.monotonic()
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        elapsed = time.monotonic() - start
        logger.info(f"SANDBOX <<< exit={result.returncode} in {elapsed:.1f}s")
        print(f"  [sandbox] exit={result.returncode} in {elapsed:.1f}s", flush=True)

        if result.stdout.strip():
            preview = result.stdout.strip()[:200]
            logger.debug(f"SANDBOX stdout: {preview}")
            print(f"  [sandbox] stdout: {preview}", flush=True)
        if result.stderr.strip():
            preview = result.stderr.strip()[:200]
            logger.debug(f"SANDBOX stderr: {preview}")
            print(f"  [sandbox] stderr: {preview}", flush=True)

        return result.returncode, result.stdout, result.stderr

    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        msg = f"Command timed out after {elapsed:.0f}s (limit={timeout}s): {safe_command}"
        logger.error(msg)
        print(f"  [sandbox] TIMEOUT after {elapsed:.0f}s", flush=True)
        return 1, "", msg

    finally:
        os.unlink(gitconfig_path)   # always clean up the temp file