# The Real LLM Pipeline — How Prompts Flow

Reverse-engineered from `impl_ato.py` source.

## Phase 1: Sub-agent dispatch (from this container)

When the main LLM decides to call a sub-agent (e.g. `testing_agent_v3`),
this container does:

```python
POST {base_url}/jobs/v0/submit/
Authorization: Bearer {auth_token}
Content-Type: application/json

{
  "payload": {
    "task": [{"message": "<sub-agent prompt>", "triggered_by": "system"}],
    "ato": true,                       # Agent Tool Orchestration
    "proxy_url": "<LLM proxy URL>",
    "expertise_type": "...",
    "request_id": "<uuid>",
    ...
  }
}
```

## Phase 2: Poll for result

```python
GET {proxy_url}/execute/lazy?request_id=<id>&hash=<hash>
Authorization: Bearer {auth_token}

# Returns 409 while computing, 200 when done
# When 409: poll again every poll_timeout seconds
# When 200: response.json() contains the LLM output + tool calls
```

## Phase 3: The mock-LLM bypass (developer mode)

```python
# If mock_llm == True, this header is added:
headers["X_EMERGENT_MOCK_LLM"] = "true"
# Then the LLM proxy returns canned responses instead of calling Claude
```
