import json
from langgraph.graph import StateGraph, END
from agent.state import AgentState
from agent.tools.shell import run_in_sandbox
from agent.tools.files import read_file, write_file, list_directory
from agent.tools.github import poll_until_complete, get_run_logs
from agent.llm.claude_client import call as claude_call
from agent.config import MAX_RETRIES, MAX_TASK_COST_USD
import logging
import time

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an autonomous software engineer working on a cloud reference architecture project.
You have access to tools to read/write files and run shell commands for building and testing.

The repository is at /repo inside the sandbox. All file paths are relative to the repo root.
When you write code, verify it compiles or passes linting using run_shell (dotnet build, etc).

IMPORTANT: Never use run_shell for git commands (git add, git commit, git push, git log).
Git is handled by the orchestrator. Your job is to write correct files and call task_complete.

When all files are written and verified, call task_complete with the commit message and list of files changed.
When you cannot proceed after repeated failures, call request_human_input with a clear reason."""

def execute_tool(tool_name: str, tool_input: dict, state: AgentState) -> tuple[str, AgentState]:
    """Returns (result_string, updated_state)."""
    if tool_name == "run_shell":
        # Block git commands — Claude should not be doing these
        cmd = tool_input["command"].strip().lower()
        if any(cmd.startswith(f"git {sub}") for sub in ["add", "commit", "push", "pull", "log", "reset"]):
            return "ERROR: git commands are handled by the orchestrator. Write your files and call task_complete.", state
        code, stdout, stderr = run_in_sandbox(tool_input["command"])
        result = stdout + (f"\nSTDERR: {stderr}" if stderr else "")
        if code != 0:
            result = f"EXIT {code}\n{result}"
        return result, state

    elif tool_name == "read_file":
        return read_file(tool_input["path"]), state

    elif tool_name == "write_file":
        write_file(tool_input["path"], tool_input["content"])
        return f"Written: {tool_input['path']}", state

    elif tool_name == "list_directory":
        return "\n".join(list_directory(tool_input.get("path", "."))), state

    elif tool_name == "task_complete":
        commit_message = tool_input.get("commit_message", "chore: task complete")
        files_changed  = tool_input.get("files_changed", [])

        # Stage only the files Claude says it changed
        files_arg = " ".join(f'"{f}"' for f in files_changed) if files_changed else "-A"
        code, stdout, stderr = run_in_sandbox(
            f"cd /repo && git add {files_arg} && git commit -m '{commit_message}'"
        )
        if code != 0:
            # Nothing to commit is fine — already committed
            if "nothing to commit" in stdout + stderr:
                logger.info("Nothing to commit — already clean")
            else:
                logger.error(f"git commit failed: {stderr}")
                return f"git commit failed: {stderr}", state

        # Push
        code, stdout, stderr = run_in_sandbox("cd /repo && git push")
        if code != 0:
            logger.error(f"git push failed: {stderr}")
            return f"git push failed: {stderr}", state

        # Capture the SHA for ci_watcher
        _, sha_out, _ = run_in_sandbox("cd /repo && git rev-parse HEAD")
        sha = sha_out.strip()
        logger.info(f"Committed and pushed: {sha[:7]}")

        return "__TASK_COMPLETE__", state.model_copy(update={"last_commit_sha": sha})

    elif tool_name == "request_human_input":
        return f"__NEEDS_HUMAN__: {tool_input['reason']}", state

    return f"Unknown tool: {tool_name}", state

MAX_HISTORY_MESSAGES = 6   # keep last N messages in the rolling window

CRITIC_SYSTEM_PROMPT = (
    "You are a code reviewer. Identify ambiguities, missing prerequisites, and likely failure "
    "modes in the task description. Be concise."
)

def critic_node(state: AgentState) -> AgentState:
    """Pre-flight critic: reviews the task description before the agent begins work."""
    # Build the repo file tree
    file_tree = "\n".join(list_directory("."))

    user_message = (
        f"Task: {state.current_task}\n\n"
        f"Repository file tree:\n{file_tree}"
    )

    logger.info("Critic node: reviewing task description...")
    text, _, _ = claude_call(
        CRITIC_SYSTEM_PROMPT,
        [{"role": "user", "content": user_message}]
    )

    # Append the critic's feedback to error_message for visibility
    existing = state.error_message or ""
    separator = "\n\n" if existing else ""
    updated_error = existing + separator + f"[Critic]\n{text}"

    logger.info(f"Critic feedback: {text[:200]}...")
    return state.model_copy(update={"error_message": updated_error})

def agent_node(state: AgentState) -> AgentState:
    """Core agent loop: Claude reasons, calls tools, we execute them, repeat."""
    messages = [
        {"role": "user", "content": f"Current task: {state.current_task}"}
    ]
    if state.ci_logs:
        messages[0]["content"] += f"\n\nCI failure logs:\n{state.ci_logs[-4000:]}"

    while True:
        logger.info(f"Calling Claude (messages={len(messages)})...")
        print(f"  [claude] sending ({len(messages)} messages in history)...", flush=True)
        t0 = time.monotonic()
        text, tool_calls, usage = claude_call(SYSTEM_PROMPT, messages)
        elapsed = time.monotonic() - t0
        logger.info(f"Claude responded in {elapsed:.1f}s — tools={[tc['name'] for tc in tool_calls]}")
        print(f"  [claude] responded in {elapsed:.1f}s — calling: {[tc['name'] for tc in tool_calls]}", flush=True)
        state = state.model_copy(update={
            "accumulated_cost_usd": state.accumulated_cost_usd + usage["cost_usd"]
        })
        if state.accumulated_cost_usd > MAX_TASK_COST_USD:
            return state.model_copy(update={
                "needs_human": True,
                "error_message": f"Cost ceiling reached: ${state.accumulated_cost_usd:.2f} > ${MAX_TASK_COST_USD}"
            })
        if not tool_calls:
            break

        content_blocks = []
        if text:
            content_blocks.append({"type": "text", "text": text})
        for tc in tool_calls:
            content_blocks.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc["input"]
            })
        messages.append({"role": "assistant", "content": content_blocks})

        tool_results = []
        for tc in tool_calls:
            result, state = execute_tool(tc["name"], tc["input"], state)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": result[:3000]
            })
            if result == "__TASK_COMPLETE__":
                return state.model_copy(update={"task_complete": True})
            if result.startswith("__NEEDS_HUMAN__"):
                return state.model_copy(update={
                    "needs_human": True,
                    "error_message": result
                })

        messages.append({"role": "user", "content": tool_results})

        # Trim history: keep the initial task message + last MAX_HISTORY_MESSAGES
        if len(messages) > MAX_HISTORY_MESSAGES + 1:
            messages = [messages[0]] + messages[-(MAX_HISTORY_MESSAGES):]

    return state

def ci_watcher_node(state: AgentState) -> AgentState:
    """Poll CI until complete, then fetch logs if it failed."""
    if not state.last_commit_sha:
        return state
    run = poll_until_complete(state.last_commit_sha)
    conclusion = run.get("conclusion", "failure")
    logs = None
    if conclusion != "success":
        logs = get_run_logs(run["id"])
    return state.model_copy(update={
        "ci_run_id": run["id"],
        "ci_status": conclusion,
        "ci_logs": logs
    })

def route_after_ci(state: AgentState) -> str:
    if state.needs_human:
        return "human_checkpoint"
    if state.ci_status == "success":
        return "documenter"
    if state.retry_count >= MAX_RETRIES:
        return "human_checkpoint"
    return "agent"  # fix and retry

def documenter_node(state: AgentState) -> AgentState:
    _, tool_calls, _ = claude_call(
        "You are a technical writer. Write a concise runbook entry for the task that was just completed.",
        [{"role": "user", "content": (
            f"Task completed: {state.current_task}\n"
            "Write the runbook entry now using write_file to save it under runbooks/."
            "When done, call task_complete with an appropriate commit message."
        )}]
    )
    for tc in tool_calls:
        result, state = execute_tool(tc["name"], tc["input"], state)
    return state.model_copy(update={"task_complete": True})

def human_checkpoint_node(state: AgentState) -> AgentState:
    print("\n" + "=" * 60)
    print("AGENT PAUSED — HUMAN INPUT REQUIRED")
    print(f"Phase:  {state.current_phase}")
    print(f"Task:   {state.current_task}")
    print(f"Reason: {state.error_message or 'Max retries reached'}")
    print("=" * 60)
    input("Press Enter when ready to continue, or Ctrl+C to stop...")
    print("Resuming agent...", flush=True)
    return state.model_copy(update={"needs_human": False, "retry_count": 0, "ci_logs": None})

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("critic", critic_node)
    graph.add_node("agent", agent_node)
    graph.add_node("ci_watcher", ci_watcher_node)
    graph.add_node("documenter", documenter_node)
    graph.add_node("human_checkpoint", human_checkpoint_node)

    graph.set_entry_point("critic")
    graph.add_edge("critic", "agent")
    graph.add_edge("agent", "ci_watcher")
    graph.add_conditional_edges("ci_watcher", route_after_ci, {
        "agent":             "agent",
        "documenter":        "documenter",
        "human_checkpoint":  "human_checkpoint"
    })
    graph.add_edge("documenter", END)
    graph.add_edge("human_checkpoint", "agent")
    return graph.compile()
