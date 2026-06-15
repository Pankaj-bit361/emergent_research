# Raw Playbook Dump: Resend

**Query:** "Resend email API in a FastAPI app. Transactional emails."

**Has VERIFIED label:** No (hand-curated, terse)

## Credentials
- `RESEND_API_KEY` (starts with `re_`) — Resend Dashboard → API Keys
- `SENDER_EMAIL` — default `onboarding@resend.dev` (testing only)

## Install
```bash
pip install resend>=2.0.0
```

## Setup
```python
# /app/backend/.env
RESEND_API_KEY=re_your_api_key_here
SENDER_EMAIL=onboarding@resend.dev
```

## Core code (async pattern)
```python
import asyncio
import resend

@router.post("/send-email")
async def send_email(request: EmailRequest):
    params = {
        "from": SENDER_EMAIL,
        "to": [request.recipient_email],
        "subject": request.subject,
        "html": request.html_content
    }
    # Wrap sync SDK in thread to keep FastAPI non-blocking
    email = await asyncio.to_thread(resend.Emails.send, params)
    return {"status": "success", "email_id": email.get("id")}
```

## Key best practices
1. Non-blocking: `asyncio.to_thread(resend.Emails.send, params)`
2. HTML rules: inline CSS only, tables for layout, no external fonts
3. Testing mode: emails only go to verified addresses
4. MongoDB ID handling: query with `{"_id": 0}` projection, use own `id` field as UUID string
5. Always restart backend after .env changes: `sudo supervisorctl restart backend`

## Quality assessment
🥇 Polished, terse, focused. ~2,000 chars total. Best of the email playbooks. No bloat.
