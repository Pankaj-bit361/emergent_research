# Raw Playbook Dump: Sora 2 (Video Generation)

**Query:** "Sora 2 video generation. FastAPI backend."

**Has VERIFIED label:** No (hand-curated)

## Uses universal EMERGENT_LLM_KEY ✅

## Models
- `sora-2` (default) — standard quality, faster
- `sora-2-pro` — higher quality, slower

## SDK
```python
from emergentintegrations.llm.openai.video_generation import OpenAIVideoGeneration
```

## Core code
```python
import os
from dotenv import load_dotenv

load_dotenv()

def generateVideo(prompt, output_path='/app/sora2_test_video.mp4',
                  model="sora-2", size="1280x720", duration=4):
    video_gen = OpenAIVideoGeneration(api_key=os.environ['EMERGENT_LLM_KEY'])
    video_bytes = video_gen.text_to_video(
        prompt=prompt,
        model=model,
        size=size,
        duration=duration,
        max_wait_time=600  # 10 minutes
    )
    if video_bytes:
        video_gen.save_video(video_bytes, output_path)
        return output_path
    return None
```

## Supported video sizes
- `1280x720` — Standard HD (default)
- `1792x1024` — Widescreen
- `1024x1792` — Portrait/vertical
- `1024x1024` — Square

## Supported durations
- `4` seconds (default, fastest)
- `8` seconds
- `12` seconds (longest)

## Wait times
- Default `max_wait_time = 600` (10 min)
- Recommended for 12s or sora-2-pro: 900 (15 min)
- Typical generation: 2-5 min

## Common issues + fixes
1. **EMERGENT_LLM_KEY not set** → check `load_dotenv()` called before `os.getenv()`
2. **Generation timeout** → increase `max_wait_time`, try sora-2 instead of sora-2-pro
3. **Invalid size/duration** → use only supported values
4. **Download fails** → check network, retry, increase `max_wait_time`

## Quality assessment
🥇 Hand-curated, terse, complete. ~2,500 chars.
