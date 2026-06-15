# Integration Playbook Expert — Extended Analysis (13 calls total)

## 🚨 CRITICAL BUG DISCOVERED: Hallucinates for fake APIs

When given a fake API name like **"SuperAPI XYZ"** (a totally invented service), the playbook expert returned a **16,000-token detailed playbook** with:
- Hallucinated base URL: `https://api.superapi-xyz.com/v1`
- Hallucinated endpoints: `/cosmic/intelligence`
- Full FastAPI client implementation
- React components
- Pytest scaffolding
- Production deployment guide
- Did add a small disclaimer at the very top ("fictional but conceptually realistic") — but proceeded to write hundreds of lines of code as if it were real

**Impact:** A less-skilled user asking for "PaypalPro" or "GitHub Enterprise Plus" or any plausible-sounding fake service would receive a full, professional-looking playbook with completely fabricated endpoints. Could waste hours of dev time before realizing the API doesn't exist.

---

## 🧠 Behavior summary across 13 integrations

| # | Integration | Type | Behavior |
|---|---|---|---|
| 1 | Stripe | Real, curated | ✅ Pre-set Emergent key (`sk_test_emergent`) |
| 2 | Razorpay | Real, NOT curated | ⚠️ "VERIFIED" label but disclaimer says unverified |
| 3 | SendGrid | Real, NOT curated | ⚠️ Same bug — bloated 20k char playbook |
| 4 | Resend | Real, curated | ✅ Hand-crafted, terse, no label |
| 5 | ElevenLabs | Real, NOT curated | ⚠️ Warns NO Emergent key support |
| 6 | Twilio SMS | Real, NOT curated | ⚠️ Uses Verify API, not raw SMS |
| 7 | fal.ai | Real, partially curated | ✅ Warns NO Emergent key |
| 8 | Object storage | Emergent-native | ✅ Uses EMERGENT_LLM_KEY + integrations.emergentagent.com |
| 9 | Google Auth | Emergent-native | ✅ Zero-config, uses auth.emergentagent.com |
| 10 | OpenAI GPT-5.2 | Real LLM | ✅ Returns universal LLM playbook |
| 11 | Gemini Nano Banana | Real LLM (image) | ✅ Models: `gemini-3.1-flash-image-preview`, `gemini-3-pro-image-preview` |
| 12 | Sora 2 | Real video gen | ✅ Models: `sora-2`, `sora-2-pro`; uses `OpenAIVideoGeneration` |
| 13 | GPT-9000 (FAKE) | Doesn't exist | ✅ Smart: returned generic LLM playbook with REAL models list (didn't hallucinate model) |
| 14 | SuperAPI XYZ (FAKE) | Doesn't exist | ❌ Hallucinated entire 16k-token playbook |

---

## 🔬 Key discoveries

### 1. The classifier doesn't always reject fake integrations
- **For fake LLM models** (GPT-9000): The expert returned the generic LLM playbook and listed real available models. The agent is expected to notice and ask the user. **Safe behavior.**
- **For fake API services** (SuperAPI XYZ): The expert wrote a complete playbook with hallucinated URLs/endpoints. **Unsafe behavior.**

### 2. Available LLM models revealed (newest ones!)
**OpenAI:** gpt-5.5, gpt-5.4 (recommended), gpt-5.4-mini, gpt-5.2, gpt-5.1, gpt-5, gpt-5-mini, gpt-5-nano, gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, o4-mini, o3-mini, o3, o3-pro, gpt-4o-mini, gpt-4o, o1

**Anthropic:** claude-opus-4-8, claude-opus-4-7, claude-sonnet-4-6 (recommended), claude-opus-4-6, claude-sonnet-4-5-20250929, claude-haiku-4-5-20251001, claude-opus-4-5-20251101

**Gemini:** gemini-3.5-flash, gemini-3.1-pro-preview (recommended), gemini-3-flash-preview, gemini-2.5-pro, gemini-2.5-flash, gemini-2.5-flash-image, gemini-2.5-flash-lite

### 3. Emergent's custom SDK exposed (`emergentintegrations` library)
- `emergentintegrations.llm.chat` → `LlmChat`, `UserMessage`, `TextDelta`, `StreamDone`
- `emergentintegrations.llm.openai.video_generation` → `OpenAIVideoGeneration` (for Sora 2)
- `emergentintegrations.payments.stripe.checkout` → `StripeCheckout`
- Install: `pip install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/`
- Private pip index — NOT on PyPI

### 4. EMERGENT_LLM_KEY scope (confirmed)
**WORKS with:** OpenAI text/image, Anthropic text, Gemini text/Nano Banana image, Sora 2 video, OpenAI Whisper, Object storage  
**DOES NOT work with:** ElevenLabs, fal.ai, Stripe, payment providers, email/SMS providers

### 5. Sora 2 specifics (new info)
- Sizes: `1280x720` (default), `1792x1024`, `1024x1792`, `1024x1024`
- Durations: 4, 8, 12 seconds
- max_wait_time defaults to 600 seconds (10 min), recommended 900 for 12s+pro
- Uses `EMERGENT_LLM_KEY`

### 6. Task budgets — only on claude-opus-4-7
- Default 200,000 tokens per task
- Minimum 20,000 tokens (below returns 400)
- NOT available on OpenAI, Gemini, or other Claude models
- Adaptive thinking is opt-in via `thinking={"type": "adaptive"}`

### 7. The "VERIFIED_PLAYBOOK" label is INVERTED (replicated finding)
- Hand-curated playbooks (Stripe, Resend, Object storage, Google Auth, OpenAI LLMs, Sora 2): **NO label**
- Auto-generated deep-research playbooks (Razorpay, SendGrid, ElevenLabs, Twilio, SuperAPI XYZ): **"VERIFIED_PLAYBOOK"** stamp + "not been verified" disclaimer

---

## 💰 Cost reckoning

- 13 integration_playbook_expert_v2 calls
- Avg cost per call ~$0.80-1.50 (based on trajectory log earlier)
- **Estimated total: ~$12-20**
- Worth it for: Found 3 real bugs/inconsistencies, discovered hidden SDKs, mapped LLM model availability

---

*Generated by Claude Opus 4.7 (E1 session) — 2026-02 — for Pankaj-bit361/emergent_research*
