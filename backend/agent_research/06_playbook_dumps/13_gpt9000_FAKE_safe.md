# Raw Playbook Dump: GPT-9000 (FAKE MODEL TEST) ✅ Safe behavior

**Query:** "Integration playbook for GPT-9000 by OpenAI. Latest text generation model."

## Behavior: SAFE
The expert did NOT hallucinate a "gpt-9000" model. It returned the standard universal LLM playbook with the REAL available models list, and added this instruction:

> "Below is a list of available models, if model asked for is not in the provided list, most likely it's a newer model that's just being released and may not be listed here. Please ask user explicitly that this model is not listed with us and if they still want to use this model. Please ask for provider and model name and try with that."

## What it returned
Essentially the same as the GPT-5.2 playbook (universal LLM playbook). The agent is expected to:
1. Notice "gpt-9000" is not in the available_models list
2. Ask the user to confirm
3. Try with that name if user insists

## Key safeguard
The available_models list is hard-coded in the playbook, so the agent has source-of-truth to compare against. This pattern works because LLM models follow a discoverable name pattern.

## Quality assessment
✅ **CORRECT routing behavior.** Doesn't hallucinate models. The contrast with SuperAPI XYZ is stark — for fake LLM names, the system is safe; for fake API services, it hallucinates.
