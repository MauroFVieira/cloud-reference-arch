import time
import jwt
import httpx
from datetime import datetime, timezone
from agent.config import (
    GITHUB_APP_ID, GITHUB_INSTALLATION_ID,
    GITHUB_PRIVATE_KEY, GITHUB_REPO, POLL_INTERVAL
)

def _generate_jwt() -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {"iat": now - 60, "exp": now + 600, "iss": str(GITHUB_APP_ID)}
    return jwt.encode(payload, GITHUB_PRIVATE_KEY, algorithm="RS256")

def _get_installation_token() -> str:
    app_jwt = _generate_jwt()
    resp = httpx.post(
        f"https://api.github.com/app/installations/{GITHUB_INSTALLATION_ID}/access_tokens",
        headers={"Authorization": f"Bearer {app_jwt}", "Accept": "application/vnd.github+json"}
    )
    resp.raise_for_status()
    return resp.json()["token"]

def get_headers() -> dict:
    token = _get_installation_token()
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

def get_latest_run_for_commit(commit_sha: str) -> dict | None:
    headers = get_headers()
    resp = httpx.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs",
        headers=headers,
        params={"per_page": 10}
    )
    resp.raise_for_status()
    for run in resp.json()["workflow_runs"]:
        if run["head_sha"] == commit_sha:
            return run
    return None

def poll_until_complete(commit_sha: str) -> dict:
    """Block until the CI run for this commit finishes. Returns the completed run."""
    print(f"Polling CI for commit {commit_sha[:7]}...", flush=True)
    while True:
        run = get_latest_run_for_commit(commit_sha)
        if run is None:
            print("  No run found yet, waiting...", flush=True)
            time.sleep(POLL_INTERVAL)
            continue
        status = run["status"]
        conclusion = run.get("conclusion")
        print(f"  Run {run['id']}: status={status}, conclusion={conclusion}", flush=True)
        if status == "completed":
            return run
        time.sleep(POLL_INTERVAL)

def get_run_logs(run_id: int) -> str:
    """Fetch and return the text logs for a completed run."""
    headers = get_headers()
    # Get jobs for this run
    jobs_resp = httpx.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}/jobs",
        headers=headers
    )
    jobs_resp.raise_for_status()
    log_parts = []
    for job in jobs_resp.json()["jobs"]:
        log_parts.append(f"=== Job: {job['name']} ({job['conclusion']}) ===")
        # Fetch per-job logs
        log_resp = httpx.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/jobs/{job['id']}/logs",
            headers=headers,
            follow_redirects=True
        )
        if log_resp.status_code == 200:
            log_parts.append(log_resp.text[-8000:])  # last 8k chars per job
    return "\n".join(log_parts)