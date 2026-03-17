import anthropic
from agent.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def call(system: str, messages: list[dict]) -> tuple[str, list[dict], dict]:
    """
    Call Claude as a planner/reviewer — text responses only, no tool use.
    Claude produces structured JSON plans; Qwen executes the tools.

    Returns (text_response, tool_calls, usage).
    tool_calls is always empty — Claude no longer calls tools directly.
    usage contains input_tokens, output_tokens, cost_usd.
    """
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=system,
        messages=messages
    )

    text = ""
    for block in response.content:
        if block.type == "text":
            text += block.text

    usage = {
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cost_usd": (
            response.usage.input_tokens  * 3 +
            response.usage.output_tokens * 15
        ) / 1_000_000
    }

    return text, [], usage