import json
from langgraph.graph import StateGraph, END
from agent.state import AgentState
from agent.tools.shell import run_in_sandbox
from agent.tools.files import read_file, write_file, list_directory
from agent.tools.github import poll_until_complete, get_run_logs
from agent.llm.claude_client import call as claude_call
from agent.llm.qwen_client import call_with_tools as qwen_call
from agent.config import MAX_RETRIES, MAX_TASK_COST_USD, MAX_HISTORY_MESSAGES
import logging
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool registry — shared between Claude and Qwen
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "run_shell",
        "description": (
            "Run a shell command in the sandbox container for building, testing, or linting. "
            "Use for dotnet, terraform, mkdir, cat, grep, etc. "
            "Never use for git commands — git is handled by the orchestrator."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read a file from the repository",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to a file in the repository, creating directories as needed",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "list_directory",
        "description": "List all files under a directory in the repository",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}}
        }
    },
    {
        "name": "step_complete",
        "description": (
            "Signal that this execution step is done. "
            "Include a brief summary of what was done and the result."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "success": {"type": "boolean"}
            },
            "required": ["summary", "success"]
        }
    }
]

# ---------------------------------------------------------------------------
# Tool execution — shared between both tiers
# ---------------------------------------------------------------------------

def execute_tool(tool_name: str, tool_input: dict, state: AgentState) -> tuple[str, AgentState]:
    """Execute a tool call. Returns (result_string, updated_state)."""

    if tool_name == "run_shell":
        cmd = tool_input["command"].strip().lower()
        if any(f"git {sub}" in cmd for sub in ["add", "commit", "push", "pull", "log", "reset"]):
            return (
                "ERROR: git commands are handled by the orchestrator. "
                "Use step_complete when your work is done.",
                state
            )
        code, stdout, stderr = run_in_sandbox(tool_input["command"])
        result = stdout + (f"\nSTDERR: {stderr}" if stderr else "")
        if code != 0:
            result = f"EXIT {code}\n{result}"
        return result, state

    elif tool_name == "read_file":
        try:
            return read_file(tool_input["path"]), state
        except Exception as e:
            return f"ERROR reading file: {e}", state

    elif tool_name == "write_file":
        write_file(tool_input["path"], tool_input["content"])
        return f"Written: {tool_input['path']}", state

    elif tool_name == "list_directory":
        return "\n".join(list_directory(tool_input.get("path", "."))), state

    elif tool_name == "step_complete":
        return f"__STEP_COMPLETE__:{tool_input['success']}:{tool_input['summary']}", state

    return f"Unknown tool: {tool_name}", state

# ---------------------------------------------------------------------------
# Qwen executor — runs one step, returns a summary of what happened
# ---------------------------------------------------------------------------

QWEN_SYSTEM_PROMPT = """You are an autonomous software engineer executing a specific step in a larger task.
You have tools to read/write files and run shell commands.

The repository is mounted at /repo. All file paths are relative to the repo root.
Execute the step completely, verify your work, then call step_complete with a summary.
Never use git commands — call step_complete when your step is done."""


def run_qwen_step(step: str, state: AgentState) -> tuple[str, AgentState]:
    """
    Execute one step using Qwen with tool use.
    Returns (summary_of_what_happened, updated_state).
    """
    messages = [{"role": "user", "content": f"Execute this step:\n{step}"}]

    for _ in range(10):  # max 10 tool calls per step
        text, tool_calls = qwen_call(QWEN_SYSTEM_PROMPT, messages, TOOLS)

        if not tool_calls:
            # Qwen responded with text only — treat as step complete
            return text or "Step complete (no tool calls)", state

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
        step_summary = None
        for tc in tool_calls:
            result, state = execute_tool(tc["name"], tc["input"], state)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": result[:3000]
            })
            if result.startswith("__STEP_COMPLETE__"):
                parts = result.split(":", 2)
                success = parts[1] == "True"
                step_summary = parts[2] if len(parts) > 2 else "Step complete"
                print(f"  [qwen] step_complete: {step_summary[:80]}", flush=True)

        messages.append({"role": "user", "content": tool_results})

        if step_summary is not None:
            return step_summary, state

    return "Step reached max tool calls without completing", state

# ---------------------------------------------------------------------------
# Claude planner/reviewer prompts
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """You are a senior software architect planning work for an autonomous coding agent.

Given a task description and the current repository state, produce a precise ordered list of steps.
Each step must be self-contained and executable by a junior developer with no additional context.
Steps should be concrete: specify exact file paths, exact commands to run, exact package versions.

Respond ONLY with a JSON object in this exact format:
{
  "steps": [
    "Step 1: exact description",
    "Step 2: exact description"
  ],
  "ready_to_commit": false,
  "commit_message": null
}

When all work is complete and verified, set ready_to_commit to true and provide a commit_message.
If you need the executor to verify something before you can decide, set ready_to_commit to false
and include a verification step."""

REVIEWER_SYSTEM_PROMPT = """You are a senior software architect reviewing the results of executed steps.

You will receive the original task, the steps that were executed, and their results.
Decide what to do next:
- If more work is needed, provide the next steps
- If all work is complete and verified, set ready_to_commit to true
- If something is irrecoverably broken, set needs_human to true

Respond ONLY with a JSON object in this exact format:
{
  "steps": [],
  "ready_to_commit": false,
  "commit_message": null,
  "needs_human": false,
  "human_reason": null
}"""

# ---------------------------------------------------------------------------
# Claude planner call — returns structured JSON
# ---------------------------------------------------------------------------

def call_claude_planner(system: str, messages: list[dict], state: AgentState) -> tuple[dict, AgentState]:
    """
    Call Claude as a planner/reviewer. Returns parsed JSON response and updated state.
    Claude responds with text only (no tool use) — just structured JSON.
    """
    text, _, usage = claude_call(system, messages)

    # Track cost
    state = state.model_copy(update={
        "accumulated_cost_usd": state.accumulated_cost_usd + usage["cost_usd"]
    })
    logger.info(f"Claude planner cost this call: ${usage['cost_usd']:.4f} "
                f"(total: ${state.accumulated_cost_usd:.4f})")

    # Parse JSON — strip markdown fences if present
    clean = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(clean), state
    except json.JSONDecodeError:
        logger.error(f"Claude returned non-JSON: {text[:200]}")
        return {
            "steps": [],
            "ready_to_commit": False,
            "needs_human": True,
            "human_reason": f"Claude returned unparseable response: {text[:200]}"
        }, state

# ---------------------------------------------------------------------------
# Critic node — unchanged, uses Claude
# ---------------------------------------------------------------------------

CRITIC_SYSTEM_PROMPT = (
    "You are a code reviewer. Identify ambiguities, missing prerequisites, and likely failure "
    "modes in the task description. Be concise. Respond in plain text."
)

def critic_node(state: AgentState) -> AgentState:
    """Pre-flight critic: reviews the task before work begins."""
    file_tree = "\n".join(list_directory("."))
    user_message = (
        f"Task: {state.current_task}\n\n"
        f"Repository file tree:\n{file_tree}"
    )
    logger.info("Critic node: reviewing task description...")
    text, _, usage = claude_call(
        CRITIC_SYSTEM_PROMPT,
        [{"role": "user", "content": user_message}]
    )
    state = state.model_copy(update={
        "accumulated_cost_usd": state.accumulated_cost_usd + usage["cost_usd"]
    })
    logger.info(f"Critic feedback: {text[:200]}...")
    print(f"  [critic] {text[:200]}...", flush=True)
    existing = state.error_message or ""
    separator = "\n\n" if existing else ""
    return state.model_copy(update={
        "error_message": existing + separator + f"[Critic]\n{text}"
    })

# ---------------------------------------------------------------------------
# Agent node — two-tier: Claude plans, Qwen executes, Claude reviews
# ---------------------------------------------------------------------------

def agent_node(state: AgentState) -> AgentState:
    """
    Two-tier agent loop:
    1. Claude produces a plan (list of steps) as JSON
    2. Qwen executes each step using tools
    3. Claude reviews results and either plans more steps or signals completion
    """
    # Build initial planning context
    file_tree = "\n".join(list_directory("."))
    planner_messages = [{
        "role": "user",
        "content": (
            f"Task: {state.current_task}\n\n"
            f"Current repository state:\n{file_tree}\n\n"
            + (f"Critic notes:\n{state.error_message}\n\n" if state.error_message else "")
            + (f"Previous CI failure:\n{state.ci_logs[-3000:]}\n\n" if state.ci_logs else "")
            + "Produce the first set of steps."
        )
    }]

    execution_history = []  # accumulates (step, result) pairs for the reviewer

    for planning_round in range(8):  # max planning rounds per task
        # Check cost ceiling
        if state.accumulated_cost_usd > MAX_TASK_COST_USD:
            logger.warning(f"Cost ceiling reached: ${state.accumulated_cost_usd:.2f}")
            return state.model_copy(update={
                "needs_human": True,
                "error_message": f"Cost ceiling reached: ${state.accumulated_cost_usd:.2f} > ${MAX_TASK_COST_USD}"
            })

        # Claude produces steps
        print(f"  [claude] planning round {planning_round + 1}...", flush=True)
        plan, state = call_claude_planner(PLANNER_SYSTEM_PROMPT, planner_messages, state)

        if plan.get("needs_human"):
            return state.model_copy(update={
                "needs_human": True,
                "error_message": plan.get("human_reason", "Claude requested human input")
            })

        if plan.get("ready_to_commit"):
            # Claude is satisfied — hand off to orchestrator for commit
            commit_message = plan.get("commit_message", "chore: task complete")
            logger.info(f"Claude ready to commit: {commit_message}")
            return _do_commit(commit_message, state)

        steps = plan.get("steps", [])
        if not steps:
            logger.warning("Claude returned empty steps and not ready_to_commit")
            return state.model_copy(update={
                "needs_human": True,
                "error_message": "Claude returned no steps and did not signal completion"
            })

        print(f"  [claude] produced {len(steps)} steps", flush=True)
        for i, step in enumerate(steps):
            logger.info(f"  Step {i+1}/{len(steps)}: {step[:80]}")

        # Qwen executes each step
        step_results = []
        for i, step in enumerate(steps):
            print(f"  [qwen] executing step {i+1}/{len(steps)}: {step[:60]}...", flush=True)
            logger.info(f"Qwen executing: {step[:100]}")
            summary, state = run_qwen_step(step, state)
            step_results.append({"step": step, "result": summary})
            logger.info(f"Qwen result: {summary[:100]}")

        execution_history.extend(step_results)

        # Build reviewer context — trim to last 5 rounds to control token use
        recent_history = execution_history[-10:]
        history_text = "\n".join(
            f"Step: {r['step']}\nResult: {r['result']}\n"
            for r in recent_history
        )

        # Claude reviews results
        planner_messages = [{
            "role": "user",
            "content": (
                f"Task: {state.current_task}\n\n"
                f"Steps executed and their results:\n{history_text}\n\n"
                f"Current repository state:\n{'\n'.join(list_directory('.'))}\n\n"
                "Review the results and decide what to do next."
            )
        }]

    # Exceeded max planning rounds
    return state.model_copy(update={
        "needs_human": True,
        "error_message": f"Exceeded maximum planning rounds ({8}) without completing task"
    })


def _do_commit(commit_message: str, state: AgentState) -> AgentState:
    """Perform git add, commit, push and return updated state with SHA."""
    code, stdout, stderr = run_in_sandbox(
        f"cd /repo && git add -A && git commit -m '{commit_message}'"
    )
    if code != 0:
        if "nothing to commit" in stdout + stderr:
            logger.info("Nothing to commit — working tree already clean")
        else:
            logger.error(f"Commit failed: {stderr}")
            return state.model_copy(update={
                "needs_human": True,
                "error_message": f"Commit failed: {stderr}"
            })

    code, stdout, stderr = run_in_sandbox("cd /repo && git push")
    if code != 0:
        return state.model_copy(update={
            "needs_human": True,
            "error_message": f"Push failed: {stderr}"
        })

    _, sha_out, _ = run_in_sandbox("cd /repo && git rev-parse HEAD")
    sha = sha_out.strip()
    logger.info(f"Committed and pushed: {sha[:7]}")
    print(f"  [git] pushed {sha[:7]}", flush=True)
    return state.model_copy(update={"last_commit_sha": sha, "task_complete": True})

# ---------------------------------------------------------------------------
# CI watcher, routing, documenter, human checkpoint — unchanged
# ---------------------------------------------------------------------------

def ci_watcher_node(state: AgentState) -> AgentState:
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
    return "agent"


def documenter_node(state: AgentState) -> AgentState:
    """Claude writes the runbook entry — this is reasoning+prose, always Claude."""
    text, _, usage = claude_call(
        "You are a technical writer. Write a concise runbook entry in markdown for the task "
        "that was just completed. Include: what was built, key commands, and how to verify it works.",
        [{"role": "user", "content": f"Task completed: {state.current_task}"}]
    )
    state = state.model_copy(update={
        "accumulated_cost_usd": state.accumulated_cost_usd + usage["cost_usd"]
    })
    # Write the runbook entry directly — no tool loop needed
    import re
    safe_phase = re.sub(r"[^a-z0-9-]", "-", state.current_phase.lower())
    runbook_path = f"runbooks/{safe_phase}.md"
    write_file(runbook_path, text)

    # Commit the runbook
    run_in_sandbox(f"cd /repo && git add '{runbook_path}' && git commit -m 'docs: runbook for {state.current_phase}'")
    run_in_sandbox("cd /repo && git push")

    return state.model_copy(update={"task_complete": True})


def human_checkpoint_node(state: AgentState) -> AgentState:
    print("\n" + "=" * 60, flush=True)
    print("AGENT PAUSED — HUMAN INPUT REQUIRED")
    print(f"Phase:  {state.current_phase}")
    print(f"Task:   {state.current_task}")
    print(f"Reason: {state.error_message or 'Max retries reached'}")
    print(f"Cost so far: ${state.accumulated_cost_usd:.2f}")
    print("=" * 60)
    print("Fix the issue, then return to THIS terminal and press Enter.")
    print("Waiting...", flush=True)
    input()
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
        "agent":            "agent",
        "documenter":       "documenter",
        "human_checkpoint": "human_checkpoint"
    })
    graph.add_edge("documenter", END)
    graph.add_edge("human_checkpoint", "agent")
    return graph.compile()