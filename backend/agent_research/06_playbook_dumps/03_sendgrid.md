# Raw Playbook Dump: SendGrid

**Query:** "SendGrid email sending in a FastAPI app. Transactional emails."

**Has VERIFIED label:** ✅ YES (classifier bug — disclaimer says unverified)

## Credentials
- `SENDGRID_API_KEY` — Full Access from SendGrid Dashboard → Settings → API Keys
- `SENDER_EMAIL` — verified sender address

## Install
```bash
pip install python-dotenv sendgrid fastapi uvicorn pydantic-settings
```

## Core code (`backend/app/emails.py`)
```python
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

def send_email(to: str, subject: str, content: str, content_type: str = "html"):
    message = Mail(
        from_email=os.getenv('SENDER_EMAIL'),
        to_emails=to,
        subject=subject,
        html_content=content if content_type == "html" else None,
        plain_text_content=content if content_type == "plain" else None
    )
    sg = SendGridAPIClient(os.getenv('SENDGRID_API_KEY'))
    response = sg.send(message)
    return response.status_code == 202
```

## FastAPI endpoint with BackgroundTasks
```python
@app.post("/api/share-note")
async def share_note_via_email(request: NoteShareRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(send_note_sharing_email, ...)
    return EmailResponse(status="success", message="Queued")
```

## Bloat noted
- Full React `react-hook-form` example (unnecessary)
- Complete CSS file (unnecessary)
- Pytest scaffolding for both backend AND frontend
- SPF/DKIM/DMARC setup instructions
- IP rotation, dedicated IP advice
- ~10k chars total — 5x more than needed

## Production checklist provided
- Domain authentication
- SPF / DKIM / DMARC records
- Event Webhook for delivery monitoring
- Rate limiting + exponential backoff
- Bounce/spam rate monitoring

## Quality assessment
🥉 Heavily auto-generated. Useful core but lots of irrelevant fluff.
