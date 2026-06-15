# Raw Playbook Dump: ElevenLabs (TTS + STT + Voice Cloning)

**Query:** "ElevenLabs text-to-speech voice generation in a FastAPI app."

**Has VERIFIED label:** ✅ YES (classifier bug)

## ⚠️ Explicit warning
> "EMERGENT LLM KEY is not applicable for Eleven Labs"

## Credentials
- `ELEVENLABS_API_KEY` from https://elevenlabs.io/app/settings/api-keys

## SDK
```python
from elevenlabs import ElevenLabs
from elevenlabs.client import AsyncElevenLabs

client = ElevenLabs(api_key="YOUR_API_KEY")

# Async version
async def get_tts_client() -> AsyncElevenLabs:
    return AsyncElevenLabs(api_key=settings.ELEVEN_API_KEY, timeout=30.0, max_retries=3)
```

## Correct method names (CRITICAL)
```python
# ❌ Wrong - audio_generator = client.generate()
# ✅ Correct - client.text_to_speech.convert()

# ❌ Wrong - transcription = client.transcribe()
# ✅ Correct - client.speech_to_text.convert()
```

## Models
- **TTS:** `eleven_multilingual_v2`
- **STT:** `scribe_v1`

## TTS endpoint
```python
audio_generator = eleven_client.text_to_speech.convert(
    text=request.text,
    voice_id=request.voice_id,
    model_id="eleven_multilingual_v2",
    voice_settings=VoiceSettings(
        stability=request.stability,
        similarity_boost=request.similarity_boost,
        style=request.style,
        use_speaker_boost=request.use_speaker_boost
    )
)
audio_data = b"".join(chunk for chunk in audio_generator)
audio_b64 = base64.b64encode(audio_data).decode()
```

## STT endpoint
```python
transcription_response = eleven_client.speech_to_text.convert(
    file=io.BytesIO(audio_content),
    model_id="scribe_v1"
)
transcribed_text = transcription_response.text
```

## Voice Cloning (IVC)
```python
voice = await client.voices.ivc.create(
    name=voice_name,
    files=[await process_upload(f) for f in files],
    description=description
)
```

## Streaming TTS
```python
audio_stream = eleven_client.text_to_speech.stream(
    text=request.text,
    voice_id=request.voice_id,
    model="eleven_multilingual_v2",
    voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.5)
)
async for chunk in audio_stream:
    audio_data += chunk
```

## Recommended dependencies
```bash
pip install elevenlabs fastapi motor pydantic ffmpeg-python python-multipart
```

## Quality assessment
🥈 Hand-curated for ElevenLabs SDK quirks (method names). Auto-generated for support/monitoring sections (Prometheus, Grafana — overkill).
