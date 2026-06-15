# Raw Playbook Dump: Stripe

**Query:** "Integration playbook for Stripe payments in a FastAPI + React app. Standard checkout flow."

**Has VERIFIED label:** No (hand-curated)

**Key facts:**
- Pre-set Emergent key: `STRIPE_API_KEY=sk_test_emergent`
- Library: `from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionResponse, CheckoutStatusResponse, CheckoutSessionRequest`
- Webhook endpoint: `/api/webhook/stripe`
- Supports crypto: `payment_methods=["card", "crypto"]` (currency must be `usd`)
- MANDATORY: `payment_transactions` MongoDB collection
- MANDATORY: Frontend polling (no webhook required for testing)

## Core code

```python
host_url = str(http_request.base_url)
webhook_url = f"{host_url}/api/webhook/stripe"
stripe_checkout = StripeCheckout(api_key=api_key, webhook_url=webhook_url)

# Custom amount
checkoutrequest = CheckoutSessionRequest(
    amount=amount, currency=currency,
    success_url=success_url, cancel_url=cancel_url, metadata=metadata
)
session: CheckoutSessionResponse = await stripe_checkout.create_checkout_session(checkoutrequest)

# Get status (polling)
status: CheckoutStatusResponse = await stripe_checkout.get_checkout_status(session_id)

# Handle webhook
webhook_response = await stripe_checkout.handle_webhook(
    request_body_bytes, request.headers.get("Stripe-Signature")
)
```

## CheckoutSessionRequest model

```python
amount: Optional[float]          # in dollars (1.00, NOT 1)
currency: str = "usd"
stripe_price_id: Optional[str]    # alternative to amount
quantity: int = 1
success_url: Optional[str]        # ?session_id={CHECKOUT_SESSION_ID}
cancel_url: Optional[str]
metadata: Optional[Dict[str, str]]
payment_methods: List[str] = ["card"]  # or ["card", "crypto"] / ["crypto"]
```

## Security mandates
- ❌ NEVER accept amounts from frontend
- ✅ Backend defines FIXED packages, frontend sends `package_id`
- ✅ Build success_url from frontend origin (window.location.origin)
- ✅ Create payment_transactions DB entry BEFORE redirect
- ✅ Update entry only ONCE per session (idempotency)

## Crypto activation
1. Stripe Dashboard → Settings → Payment methods → Crypto → Turn on
2. Available only for selected US users
3. Currency MUST be `usd` when crypto enabled
