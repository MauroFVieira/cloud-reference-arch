# Agent Phase Files

Each file in this directory defines the task description for one agent phase.

## Naming

Files are named by phase key: `2a.txt`, `2b.txt`, `3.txt`, etc.
The key is passed directly to `python -m agent.run <key>`.

## Format

Plain text. The agent receives the entire file contents as its `current_task`.

Guidelines for writing phase files:
- Start with a one-line summary of what the phase builds
- List every file to be created or modified with its exact path
- Include exact command strings for build/test verification
- Specify the exact verification command that must exit 0 before task_complete
- End with: "Do not add any git commands."
- Do not include git add/commit/push instructions — the orchestrator handles all git operations

## Running a phase

```bash
python -m agent.run --list        # list all available phases
python -m agent.run 2a            # run phase 2a
python -m agent.run --task "..."  # run a one-off custom task
```
