"""Thin wrapper for the Claude calls the pipeline makes.

Every call asks for JSON that matches a schema, so the rest of the code
never has to parse free text.
"""

import json

import anthropic

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 6}
# If a safety classifier declines a request, the API re-runs it on Anthropic's
# recommended fallback model instead of returning a refusal.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_PAUSE_RESUMES = 4


class ClaudeError(RuntimeError):
    pass


_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def ask_json(
    *,
    model: str,
    system: str,
    content: str | list,
    schema: dict,
    effort: str = "medium",
    web_search: bool = False,
    max_tokens: int = 16000,
) -> dict:
    messages: list[dict] = [{"role": "user", "content": content}]
    tools = [WEB_SEARCH_TOOL] if web_search else []

    for _ in range(MAX_PAUSE_RESUMES + 1):
        response = client().beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        if response.stop_reason == "pause_turn":
            # A long web search paused the turn; send it back so Claude continues.
            messages.append({"role": "assistant", "content": response.content})
            continue
        break
    else:
        raise ClaudeError("Claude kept pausing; try again or turn off web research")

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ClaudeError(f"Claude declined this request (category: {category})")
    if response.stop_reason == "max_tokens":
        raise ClaudeError("Response was cut off; raise max_tokens")

    texts = [block.text for block in response.content if block.type == "text"]
    if not texts:
        raise ClaudeError("Claude returned no text")
    try:
        return json.loads(texts[-1])
    except json.JSONDecodeError as e:
        raise ClaudeError(f"Claude returned invalid JSON: {e}") from e
