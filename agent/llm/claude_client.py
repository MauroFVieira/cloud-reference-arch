import anthropic
from agent.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

TOOLS = [
    {
        "name": "run_shell",
        "description": "Run a shell command in the sandbox container. Use for git, dotnet, terraform, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to run"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Read a file from the repository",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from repo root"}
            },
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
            "properties": {
                "path": {"type": "string", "description": "Relative path, defaults to repo root"}
            }
        }
    },
    {
        "name": "task_complete",
        "description": (
            "Signal that all file changes for this task are written and ready. "
            "Call this when files are written and verified. "
            "Do NOT commit or push — the orchestrator handles git. "
            "Do NOT call run_shell for git commands."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "commit_message": {
                    "type": "string",
                    "description": "Conventional commit message for the changes made"
                },
                "files_changed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of relative file paths that were written"
                }
            },
            "required": ["commit_message", "files_changed"]
        }
    },
    {
        "name": "request_human_input",
        "description": "Pause the agent and request human review — use when stuck after max retries or facing an ambiguous failure",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why human input is needed"}
            },
            "required": ["reason"]
        }
    }
]

def call(system: str, messages: list[dict]) -> tuple[str, list[dict]]:
    """
    Send a conversation to Claude Sonnet with tools.
    Returns (text_response, tool_calls).
    tool_calls is a list of {"name": str, "input": dict}.
    """
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=system,
        tools=TOOLS,
        messages=messages
    )
    text = ""
    tool_calls = []
    for block in response.content:
        if block.type == "text":
            text += block.text
        elif block.type == "tool_use":
            tool_calls.append({"name": block.name, "input": block.input, "id": block.id})
    return text, tool_calls