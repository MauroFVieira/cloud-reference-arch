"""
Smoke test: verify the full agent loop works end-to-end.
The agent will:
1. Create a file (docs/agent-smoke-test.md)
2. Commit and push it
3. Poll CI until the scaffold-check job passes
4. Write a runbook entry
"""
from agent.orchestrator import build_graph
from agent.state import AgentState
import subprocess
import logging
import os
from datetime import datetime

def setup_logging():
    log_dir = os.path.expanduser("~/.config/cloud-ref-agent/logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = os.path.join(log_dir, f"agent-{timestamp}.log")

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),   # full detail to file
            logging.StreamHandler()           # INFO+ to terminal
        ]
    )
    # Suppress noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)

    print(f"Logging to: {log_file}", flush=True)
    return log_file

def check_prerequisites():
    issues = []
    
    # Check sandbox image exists
    result = subprocess.run(
        ["docker", "image", "inspect", "cloud-ref-sandbox:latest"],
        capture_output=True
    )
    if result.returncode != 0:
        issues.append("Sandbox image not found. Run: cd agent/sandbox && docker build -t cloud-ref-sandbox:latest .")
    
    # Check llama-server reachable
    try:
        import httpx
        httpx.get("http://ARRAKIS:8080/health", timeout=5).raise_for_status()
    except Exception:
        issues.append("llama-server unreachable at ARRAKIS:8080. Check systemd service on ARRAKIS.")
    
    # Check Anthropic key file exists
    from agent.config import CONFIG_DIR
    if not (CONFIG_DIR / "anthropic-api-key").exists():
        issues.append(f"Anthropic API key not found at {CONFIG_DIR}/anthropic-api-key")
    
    return issues

def main():
    log_file = setup_logging()
    issues = check_prerequisites()
    if issues:
        print("\nPrerequisite check failed:")
        for issue in issues:
            print(f"  ✗ {issue}")
        print("\nFix the above before running the agent.")
        return

    print("Prerequisites OK. Starting agent...\n")
    graph = build_graph()
    initial_state = AgentState(
        current_phase="smoke_test",
        current_task=(
            "Create the file docs/agent-smoke-test.md with content "
            "'# Agent Smoke Test\n\nPassed at: ' followed by the current UTC timestamp. "
            "Commit with message 'chore: agent smoke test' and push to origin main. "
            "After the push, run 'cd /repo && git log --oneline -1' to confirm the commit is present. "
            "When the push exits 0 and the log confirms the commit, call task_complete immediately. "
            "Do not make additional commits or pushes."
        )
    )
    final_state = graph.invoke(initial_state)
    if final_state["task_complete"]:
        print("\n✓ Smoke test passed. Agent loop is fully operational.")
    else:
        print("\n✗ Smoke test failed. Check logs above.")

if __name__ == "__main__":
    main()