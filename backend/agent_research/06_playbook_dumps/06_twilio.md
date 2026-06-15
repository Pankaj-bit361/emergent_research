# Raw Playbook Dump: Twilio SMS

**Query:** "Twilio SMS in a FastAPI app. Send transactional SMS (OTP, alerts, notifications)."

**Has VERIFIED label:** ✅ YES (classifier bug)

## Credentials
- `TWILIO_ACCOUNT_SID` (Twilio Console)
- `TWILIO_AUTH_TOKEN` (Twilio Console)
- `TWILIO_VERIFY_SERVICE` (VA... from Twilio Console → Verify services)

## Key insight: Uses Verify API, NOT raw SMS
The playbook uses Twilio Verify (managed OTP service) rather than the raw Messages API. Twilio handles OTP generation server-side.

## Install
```bash
pip install fastapi uvicorn twilio python-dotenv pytest
```

## OTP send
```python
from twilio.rest import Client
client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))

@app.post("/send-otp")
async def send_otp(request: PhoneRequest):
    verification = client.verify.services(os.getenv("TWILIO_VERIFY_SERVICE")) \
        .verifications.create(to=request.phone_number, channel="sms")
    return {"status": verification.status}
```

## OTP verify
```python
@app.post("/verify-otp")
async def verify_otp(request: VerifyRequest):
    check = client.verify.services(os.getenv("TWILIO_VERIFY_SERVICE")) \
        .verification_checks.create(to=request.phone_number, code=request.code)
    return {"valid": check.status == "approved"}
```

## Phone number format
- E.164 only: `+14155552671`
- Validate before sending; recommends Twilio's Lookup API for validation

## React frontend pattern
Two-step form: phone input → OTP input → verify.

## Notes
- Test with numbers registered in your Twilio account during development
- `httpx` recommended for async HTTP from FastAPI routes
- Includes optional MongoDB integration storing verification history

## Quality assessment
🥉 Auto-generated. Uses Verify (good choice) but verbose.
