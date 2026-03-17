import httpx
import uuid
import json
import re
from agent.config import QWEN_BASE_URL, QWEN_MODEL


def generate_code(prompt: str, max_tokens: int = 2048) -> str:
    """
    Plain code generation — no tool use.
    Returns the generated text.
    """
    response = httpx.post(
        f"{QWEN_BASE_URL}/v1/chat/completions",
        json={
            "model": QWEN_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.2
        },
        timeout=300
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _parse_tool_calls(content: str) -> tuple[str, list[dict]]:
    """
    Parse Qwen's native tool call format from message content.

    Qwen embeds tool calls as:
        <tools>
        {"name": "tool_name", "arguments": {...}}
        </tools>

    Multiple tool calls may appear in a single response, each in its own <tools> block.
    Returns (text_without_tool_tags, list_of_tool_calls).
    """
    tool_calls = []
    pattern = re.compile(r"<tools>\s*(.*?)\s*</tools>", re.DOTALL)

    for match in pattern.finditer(content):
        raw = match.group(1).strip()
        try:
            parsed = json.loads(raw)
            tool_calls.append({
                "name":  parsed.get("name", ""),
                "input": parsed.get("arguments", parsed.get("parameters", {})),
                "id":    str(uuid.uuid4())
            })
        except json.JSONDecodeError:
            # Malformed tool call — skip it
            pass

    # Remove all <tools>...</tools> blocks from the text
    clean_text = pattern.sub("", content).strip()
    return clean_text, tool_calls


def call_with_tools(system: str, messages: list[dict], tools: list[dict]) -> tuple[str, list[dict]]:
    """
    Call Qwen with tool use.
    llama.cpp passes Qwen's native <tools> format through in the content field.

    Tool definitions are injected into the system prompt in the format Qwen expects.
    Returns (text_response, tool_calls) where tool_calls is:
      [{"name": str, "input": dict, "id": str}]
    """
    # Build tool descriptions for the system prompt in Qwen's expected format
    tool_descriptions = json.dumps(
        [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}})
            }
            for t in tools
        ],
        indent=2
    )

    augmented_system = (
        f"{system}\n\n"
        f"You have access to the following tools:\n{tool_descriptions}\n\n"
        "To call a tool, respond with:\n"
        "<tools>\n"
        '{"name": "tool_name", "arguments": {"param": "value"}}\n'
        "</tools>\n"
        "You may call multiple tools by including multiple <tools> blocks.\n"
        "After calling tools and receiving results, continue working toward completing the step."
    )

    full_messages = [{"role": "system", "content": augmented_system}] + messages

    response = httpx.post(
        f"{QWEN_BASE_URL}/v1/chat/completions",
        json={
            "model": QWEN_MODEL,
            "messages": full_messages,
            "max_tokens": 2048,
            "temperature": 0.1
        },
        timeout=300
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"].get("content") or ""
    text, tool_calls = _parse_tool_calls(content)
    return text, tool_calls