# Integration Playbook Expert v2 — Output Analysis

Ran the `integration_playbook_expert_v2` subagent **9 times** with diverse integration requests on `claude-opus-4-7` (the main agent model). This is what we learned about how it actually behaves.

---

## ⚠️ Bug discovered: "VERIFIED" label is broken

**5 of 9 playbooks contained this contradiction:**
```
Summary: **VERIFIED_PLAYBOOK**
DISCLAIMER: This is a newly created playbook based on deep research. 
It has not been verified through testing...
```

The classifier labels a playbook as VERIFIED, but the disclaimer body explicitly says it's UNVERIFIED. This means **the verified/unverified flag is unreliable** — agents downstream that branch on this label may run untested code.

| Playbook | Verified label? | Actually verified? |
|---|---|---|
| Stripe | (no label, polished) | ✅ Yes — hand-curated playbook |
| Razorpay | "VERIFIED_PLAYBOOK" | ❌ No — disclaimer contradicts |
| SendGrid | "VERIFIED_PLAYBOOK" | ❌ No — disclaimer contradicts |
| Resend | (no label) | ✅ Yes — hand-curated, terse |
| ElevenLabs | "VERIFIED_PLAYBOOK" | ❌ No — disclaimer contradicts |
| Twilio SMS | "VERIFIED_PLAYBOOK" | ❌ No — disclaimer contradicts |
| fal.ai | "VERIFIED PLAYBOOK" | ✅ Yes — looks hand-curated |
| Object storage | (no label) | ✅ Yes — Emergent-native, polished |
| Emergent Google Auth | (no label) | ✅ Yes — Emergent-native, polished |

**Pattern:** The truly hand-curated playbooks (Stripe, Resend, fal.ai, Object storage, Google Auth) **don't carry the "VERIFIED" stamp** but ARE the verified ones. The auto-generated ones from deep-research stamp themselves "VERIFIED" but include the disclaimer. **The label is inverted.**

---

## 📊 Per-integration key facts

### 1. **Stripe** — `STRIPE_API_KEY=sk_test_emergent` (PRE-SET!)
- Uses custom `emergentintegrations.payments.stripe.checkout` library — NOT raw Stripe SDK
- Key already in env (`sk_test_emergent`); explicit instruction: *"Do not ask user for the stripe key"*
- Supports crypto payments via `payment_methods=["card","crypto"]` (currency must be `usd`)
- **MANDATORY**: Create `payment_transactions` MongoDB collection BEFORE redirect
- **MANDATORY**: Frontend polls payment status (no webhook required)
- **SECURITY**: Backend defines all amounts (frontend sends `package_id` only, never amount)

### 2. **Razorpay** — User must provide keys
- Standard `razorpay` Python SDK + `react-razorpay` npm package
- Required: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`
- Amounts in **paise** (multiply rupees by 100)
- Includes split-payments example (Linked Accounts)
- Receipt field ≤ 40 chars limit

### 3. **SendGrid** — User must provide keys
- Standard `sendgrid` Python SDK
- Required: `SENDGRID_API_KEY` (Full Access), `SENDER_EMAIL` (verified)
- Detailed unit test scaffolding using `pytest` + `unittest.mock`
- Includes complete React form component with `react-hook-form`
- Recommends `BackgroundTasks` for async sending
- Includes complete production deployment checklist (SPF/DKIM/DMARC, IP rotation)

### 4. **Resend** — User must provide keys (much terser playbook)
- `resend>=2.0.0` pip package
- Required: `RESEND_API_KEY` (starts with `re_`), `SENDER_EMAIL` (default `onboarding@resend.dev`)
- **Async pattern**: Always wrap sync SDK in `asyncio.to_thread(resend.Emails.send, ...)`
- Test mode: Emails only go to verified addresses
- Cleaner, more focused playbook (no React frontend bloat)

### 5. **ElevenLabs** — User must provide keys
- `from elevenlabs import ElevenLabs` SDK
- Required: `ELEVENLABS_API_KEY`
- **Explicit warning**: "EMERGENT LLM KEY is not applicable for Eleven Labs"
- Correct method names emphasized:
  - ✅ `client.text_to_speech.convert(...)` (not `.generate()`)
  - ✅ `client.speech_to_text.convert(...)` (not `.transcribe()`)
- Models: `eleven_multilingual_v2` (TTS), `scribe_v1` (STT)
- Supports streaming via `client.text_to_speech.stream(...)`
- Includes voice cloning via `client.voices.ivc.create(...)`

### 6. **Twilio SMS** — User must provide keys
- Standard `twilio` Python SDK
- Required: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE` (VA...)
- Uses **Twilio Verify API** for OTP (not raw SMS) — manages OTP generation server-side
- E.164 format mandatory (`+14155552671`)
- Includes optional MongoDB integration for verification history

### 7. **fal.ai** — User must provide keys
- `fal-client` pip package
- Required: `FAL_KEY`
- **Explicit warning**: "It does not use or support EMERGENT_LLM_KEY"
- Pattern: `await fal_client.submit_async("fal-ai/flux/dev", arguments={...}); result = await handler.get()`
- Model used in example: `fal-ai/flux/dev` (image gen)
- Get keys: https://fal.ai/dashboard/keys
- Response formatting was buggy (missing markdown), but content valid

### 8. **Object/file storage** — Uses `EMERGENT_LLM_KEY` ✅
- **Emergent-native** — endpoint at `https://integrations.emergentagent.com/objstore/api/v1/storage`
- Auth via `EMERGENT_LLM_KEY` + a session-scoped `storage_key`
- Pattern: `init_storage()` once at startup → reuse `storage_key` globally
- Path convention: `{app_name}/uploads/{user_id}/{uuid}.{ext}`
- **Constraints**: No delete API (soft-delete in DB), no rename, no presigned URLs
- Max 1000 list results, must use prefix filtering
- Frontend image display: use blob fetch with auth header (img src can't carry headers)
- Status codes: 403 (re-init), 404 (path mismatch), 409 (exists), 429 (backoff)

### 9. **Emergent Google Auth** — No API key needed
- Redirect URL: `https://auth.emergentagent.com/?redirect={your_redirect}`
- Session exchange endpoint: `GET https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data`
  - Header: `X-Session-ID: <session_id>`
  - Returns `{id, email, name, picture, session_token}`
- Session token valid 7 days, stored in httpOnly cookie
- **CRITICAL**: redirect URL MUST be derived from `window.location.origin` — NEVER hardcoded
- Session_id arrives in URL fragment (`#session_id=...`) NOT query params
- Race-condition pattern: check `location.hash` synchronously during render, not in `useEffect`
- Includes full testing playbook with mongosh commands for test user creation

---

## 🔑 Key/credential patterns observed

| Pattern | Integrations |
|---|---|
| **Uses Emergent's pre-set key** (already in env) | Stripe (`sk_test_emergent`) |
| **Uses `EMERGENT_LLM_KEY`** for auth | Object storage |
| **No credentials needed** (Emergent-managed) | Google Auth |
| **User must obtain own key** | Razorpay, SendGrid, Resend, ElevenLabs, Twilio, fal.ai |
| **Explicit "Emergent key NOT applicable"** | ElevenLabs, fal.ai |

---

## 📐 Playbook structure patterns

### Type A — Hand-curated, polished, terse
*(Stripe, Resend, Object storage, Google Auth)*
- No "VERIFIED" stamp
- Tight Emergent-specific guidance
- Custom internal SDKs (`emergentintegrations.*`) used where applicable
- Explicit anti-pattern warnings
- ~2-4k chars

### Type B — Auto-generated via deep research
*(Razorpay, SendGrid, ElevenLabs, Twilio)*
- "VERIFIED_PLAYBOOK" stamp (which is misleading)
- "DISCLAIMER: ... not been verified through testing"
- Generic best practices, often includes React frontend, CSS, pytest scaffolds
- ~8-20k chars
- Sometimes includes inappropriate content (e.g., Hashicorp Vault for SMS app)

### Type C — Hybrid
*(fal.ai, partly)*
- Has both verified+disclaimer wording but content is hand-curated
- Smaller, focused

---

## 🧠 Meta-conclusions

1. **The classifier is broken**: "VERIFIED_PLAYBOOK" stamp appears to indicate the OPPOSITE of verified — only auto-generated playbooks carry it. Manual playbooks omit the stamp.

2. **Emergent has its own SDK** (`emergentintegrations`) that wraps several services:
   - `emergentintegrations.payments.stripe.checkout` for Stripe
   - `emergentintegrations.llm.chat` for LLMs (Claude/GPT/Gemini)
   - Object storage at `integrations.emergentagent.com/objstore/api/v1/storage`
   - Google Auth at `auth.emergentagent.com` + `demobackend.emergentagent.com/auth/v1/...`

3. **EMERGENT_LLM_KEY scope**: text LLMs + image gen + Sora 2 video + Whisper + **object storage**. NOT for ElevenLabs, fal.ai, Stripe, payment providers, email, SMS.

4. **Pre-set keys**: Stripe is the only integration with an Emergent-provided test key (`sk_test_emergent`) baked into the env.

5. **Quality variance is huge**: Polished playbooks are 2-4k chars and laser-focused. Auto-generated ones are 10-20k chars with often-irrelevant content (CSS for SMS apps, Prometheus configs for email, etc.). Trust the small, focused playbooks more than the verbose ones.

6. **All playbooks include the same preamble** about `emergentintegrations` library — that's a fixed wrapper text injected by the expert.

---

## 💰 Cost note

Each subagent call billed ~$0.50-$1.50 based on response size and reasoning depth. 9 calls = roughly $5-10 estimated cost.

---

*Generated: 2026-02 — by E1/Claude Opus 4.7 in conversation with the user*
