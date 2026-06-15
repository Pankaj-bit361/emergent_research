# Raw Playbook Dump: fal.ai

**Query:** "fal.ai for AI model inference in a FastAPI app. Image generation (FLUX) and video."

**Has VERIFIED label:** ✅ YES (looks hand-curated)

## ⚠️ Explicit warnings
> "It does not use or support EMERGENT_LLM_KEY."
> "It requires FAL.AI credentials: FAL_KEY"

## Credentials
- `FAL_KEY` from https://fal.ai/dashboard/keys

## Install
```bash
pip install fal-client python-dotenv
```

## Core code
```python
import fal_client

@app.post("/generate_image_async")
async def generate_image_async(payload: PromptRequest):
    handler = await fal_client.submit_async(
        "fal-ai/flux/dev",
        arguments={"prompt": payload.prompt}
    )
    # Optional: log progress events
    # async for event in handler.iter_events(with_logs=True):
    #     print(event)
    result = await handler.get()
    return {"success": True, "data": result}
```

## Model used in example
`fal-ai/flux/dev` (FLUX dev model for image gen)

## React frontend
```jsx
const response = await fetch("/generate_image_async", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt })
});
const data = await response.json();
if (data.success && data.data.images?.length) {
    setImageUrl(data.data.images[0].url);
}
```

## Response shape
- `result.images[0].url` — direct URL to generated image
- Stored on fal.ai's CDN

## MongoDB integration (optional)
```python
collection.insert_one({"prompt": payload.prompt, "result": result})
```

## Quality assessment
🥈 Hand-curated. Bug: response formatting had escaped `{{` braces (Python f-string artifacts). Content is correct but presentation messy.
