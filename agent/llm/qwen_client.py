import httpx
from agent.config import QWEN_BASE_URL, QWEN_MODEL

def generate_code(prompt: str, max_tokens: int = 2048) -> str:
    """
    Call Qwen on ARRAKIS for bulk code generation.
    Returns the generated text. No tool use — pure generation.
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