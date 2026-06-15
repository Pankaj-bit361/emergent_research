# Raw Playbook Dump: Gemini Nano Banana (Image Generation)

**Query:** "Gemini image generation using Nano Banana model. FastAPI backend."

**Has VERIFIED label:** No (hand-curated)

## Uses universal EMERGENT_LLM_KEY ✅

## Available models
```
gemini:
  - gemini-3.1-flash-image-preview   # Default/Latest Nano Banana
  - gemini-3-pro-image-preview
```

## SDK
```python
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
```

## Basic text-to-image
```python
import base64
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("EMERGENT_LLM_KEY")

chat = LlmChat(api_key=api_key, session_id="unique", system_message="You are helpful")
chat.with_model("gemini", "gemini-3.1-flash-image-preview").with_params(modalities=["image", "text"])

msg = UserMessage(text="Create a picture of a cat under the gemini constellation")
text, images = await chat.send_message_multimodal_response(msg)

for i, img in enumerate(images):
    print(f"Image {i}: {img['mime_type']}")
    image_bytes = base64.b64decode(img['data'])
    with open(f"generated_image_{i}.png", "wb") as f:
        f.write(image_bytes)
```

## Image editing with reference
```python
with open("cat_image.jpg", "rb") as f:
    image_base_64 = base64.b64encode(f.read()).decode('utf-8')

chat = LlmChat(api_key=api_key, ...).with_model("gemini", "gemini-3.1-flash-image-preview")
chat.with_params(modalities=["image", "text"])

msg = UserMessage(
    text="Use the cat in this image and place it on Mars orbit with stars",
    file_contents=[ImageContent(image_base_64)]
)
text, images = await chat.send_message_multimodal_response(msg)
```

## Critical warning
> **NEVER log, print, or display complete base64 image strings.** Only print the first 10 characters (e.g., `data:image...`). Logging full base64 will cause context window limit errors and consume excessive tokens.

## Response format
- Images returned as base64-encoded strings in a list of dicts
- Each dict: `{"mime_type": "image/png", "data": "<base64>"}`

## Quality assessment
🥇 Hand-curated, focused. Critical anti-pattern (base64 logging) clearly called out.
