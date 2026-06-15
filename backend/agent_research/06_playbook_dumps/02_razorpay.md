# Raw Playbook Dump: Razorpay

**Query:** "Razorpay payment gateway in a FastAPI + React app. Standard checkout flow for India."

**Has VERIFIED label:** ✅ YES (but disclaimer says UNVERIFIED — classifier bug)

**Disclaimer extracted:** *"This is a newly created playbook based on deep research. It has not been verified through testing and should be implemented with caution."*

## Required credentials
- `RAZORPAY_KEY_ID` (Razorpay Dashboard)
- `RAZORPAY_KEY_SECRET` (Razorpay Dashboard)
- `RAZORPAY_WEBHOOK_SECRET` (for webhook verification)

## Install
```bash
pip install fastapi uvicorn motor python-dotenv razorpay pydantic
npm install react-razorpay axios
```

## Backend
```python
import razorpay
client = razorpay.Client(auth=(env('RAZORPAY_KEY_ID'), env('RAZORPAY_KEY_SECRET')))

@app.post("/create-order")
async def create_order(order: PaymentOrder):
    razor_order = client.order.create({
        "amount": order.amount,   # in PAISE (multiply rupees * 100)
        "currency": "INR",
        "payment_capture": 1
    })
    await db.insert_one({"order_id": razor_order["id"], "status": "created"})
    return razor_order
```

## Split payments (Linked Accounts)
```python
transfer = client.payment.transfer(payment_id, {
    "transfers": [
        {"account": "acc_LinkedAccount1", "amount": 5000, "currency": "INR"},
        {"account": "acc_LinkedAccount2", "amount": 5000, "currency": "INR"}
    ]
})
```

## React frontend
```jsx
import { useRazorpay } from 'react-razorpay';
const [Razorpay] = useRazorpay();

const options = {
  key: process.env.RAZORPAY_KEY_ID,
  amount: response.data.amount,
  currency: "INR",
  order_id: response.data.id,
  handler: async (res) => { /* on success */ }
};
new Razorpay(options).open();
```

## Webhook verification
```python
client.utility.verify_webhook_signature(
    payload.decode(), signature, env('RAZORPAY_WEBHOOK_SECRET')
)
```

## Constraints noted
- Amounts in **paise** (× 100)
- Receipt field ≤ 40 chars
- Test card: 4111 1111 1111 1111
- Webhook tester: https://webhook.site/

## Quality assessment
🥉 Auto-generated, includes irrelevant "Hashicorp Vault" suggestion for key rotation. Bloated.
