# Raw Playbook Dump: OpenAI GPT-5.2 (Universal LLM Playbook)

**Query:** "OpenAI GPT-5.2 text generation in a FastAPI app. Multi-turn conversation."

**Has VERIFIED label:** No (hand-curated, polished)

## EMERGENT_LLM_KEY revealed
```
EMERGENT_LLM_KEY=sk-emergent-82e533cA90256248a8
```
Same key works for OpenAI, Anthropic, AND Gemini.

## Default model when user doesn't specify
`gpt-5.4` by OpenAI (the "recommended" tag).

## SDK
```python
from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone
```

## Basic streaming (DEFAULT — always use this)
```python
chat = LlmChat(
    api_key="your-api-key",  # EMERGENT_LLM_KEY or user's own
    session_id="unique-session-id",
    system_message="You are a helpful assistant."
)

async for event in chat.stream_message(UserMessage(text="Hello")):
    if isinstance(event, TextDelta):
        yield event.content   # SSE / WebSocket
    elif isinstance(event, StreamDone):
        break
```

## Provider switching
```python
chat.with_model("openai", "gpt-5.4")
chat.with_model("anthropic", "claude-sonnet-4-6")
chat.with_model("gemini", "gemini-3-flash-preview")
```

## Available models (COMPLETE LIST)

### OpenAI
```
gpt-5.5
gpt-5.4         #recommended
gpt-5.4-mini
gpt-5.2
gpt-5.1
gpt-5
gpt-5-mini
gpt-5-nano
gpt-4.1
gpt-4.1-mini
gpt-4.1-nano
gpt-4o
gpt-4o-mini
o4-mini
o3
o3-mini
o3-pro
o1
```

### Anthropic
```
claude-opus-4-8
claude-opus-4-7
claude-sonnet-4-6              #recommended
claude-opus-4-6
claude-sonnet-4-5-20250929
claude-haiku-4-5-20251001
claude-opus-4-5-20251101
```

### Gemini
```
gemini-3.5-flash
gemini-3.1-pro-preview         #recommended
gemini-3-flash-preview
gemini-2.5-pro
gemini-2.5-flash
gemini-2.5-flash-image
gemini-2.5-flash-lite
```

## Non-streaming (only for explicit opt-out)
```python
response = await chat.send_message(UserMessage(text="..."))
messages = await chat.get_messages()
```

## SSE with proxy buffering disabled
```python
return StreamingResponse(
    event_generator(),
    media_type="text/event-stream",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
)
```

## Task budgets (Anthropic Opus 4.7 ONLY)
- Default: 200,000 tokens per task
- Minimum: 20,000 tokens (below returns 400)
- Not available on OpenAI, Gemini, or other Claude models

```python
chat = (
    LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id="...",
        system_message="...",
        custom_headers={"anthropic-beta": "task-budgets-2026-03-13"},
    )
    .with_model("anthropic", "claude-opus-4-7")
    .with_params(
        extra_body={
            "output_config": {
                "task_budget": {"type": "tokens", "total": 200000},
                "effort": "high",
            },
        },
        max_tokens=64000,
    )
)
```

## Adaptive thinking (Opus 4.7 only, opt-in)
```python
extra_body={
    "output_config": {...},
    "thinking": {"type": "adaptive"},   # Off by default
}
```

## Effort levels
`"low"`, `"medium"`, `"high"` (default), `"xhigh"` (Opus 4.7 only), `"max"`

## Quality assessment
🥇 Best-in-class. Comprehensive, polished, real models list. The flagship hand-curated playbook.
