"""
Agent phase runner.

Usage:
  python -m agent.run --list          # list available phases
  python -m agent.run 2a              # run a phase by key
  python -m agent.run --task "..."    # run a one-off custom task string
"""
import argparse
import os
import logging
from datetime import datetime
from pathlib import Path

PHASES_DIR = Path(__file__).parent / "phases"


def setup_logging():
    log_dir = Path.home() / ".config/cloud-ref-agent/logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = log_dir / f"agent-{timestamp}.log"
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    print(f"Logging to: {log_file}", flush=True)
    return log_file


def list_phases():
    if not PHASES_DIR.exists():
        print("No phases directory found. Create agent/phases/ and add .txt files.")
        return
    files = sorted(PHASES_DIR.glob("*.txt"))
    if not files:
        print("No phase files found in agent/phases/")
        return
    print("Available phases:")
    for f in files:
        first_line = f.read_text().splitlines()[0][:80]
        print(f"  {f.stem}: {first_line}...")


def load_phase(key: str) -> str | None:
    path = PHASES_DIR / f"{key}.txt"
    if not path.exists():
        return None
    return path.read_text().strip()


def check_prerequisites():
    from agent.smoke_test import check_prerequisites as _check
    return _check()


def main():
    parser = argparse.ArgumentParser(description="Run an agent phase or custom task")
    parser.add_argument("phase", nargs="?", help="Phase key matching a file in agent/phases/ e.g. 2a, 2b")
    parser.add_argument("--task", help="Custom task string (overrides phase file)")
    parser.add_argument("--list", action="store_true", help="List available phases and exit")
    args = parser.parse_args()

    if args.list:
        list_phases()
        return

    if not args.phase and not args.task:
        parser.print_help()
        return

    log_file = setup_logging()

    issues = check_prerequisites()
    if issues:
        print("\nPrerequisite check failed:")
        for issue in issues:
            print(f"  ✗ {issue}")
        return

    if args.task:
        task = args.task
        phase_key = "custom"
    else:
        task = load_phase(args.phase)
        phase_key = args.phase
        if not task:
            print(f"No phase file found for '{args.phase}'.")
            print(f"Expected: {PHASES_DIR / args.phase}.txt")
            print("Run with --list to see available phases.")
            return

    print(f"Starting phase: {phase_key}\n", flush=True)

    from agent.orchestrator import build_graph
    from agent.state import AgentState

    graph = build_graph()
    state = AgentState(
        current_phase=phase_key,
        current_task=task
    )
    final = graph.invoke(state)

    if final["task_complete"]:
        print(f"\n✓ Phase {phase_key} complete.")
        print(f"  Full log: {log_file}")
    else:
        print(f"\n✗ Phase {phase_key} did not complete cleanly.")
        print(f"  Full log: {log_file}")


if __name__ == "__main__":
    main()
