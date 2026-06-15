# Raw Playbook Dump: Object Storage (Emergent-managed)

**Query:** "Object/file storage for an Emergent app. Store user-uploaded files."

**Has VERIFIED label:** No (hand-curated, polished)

## Storage URL
```
https://integrations.emergentagent.com/objstore/api/v1/storage
```

## Credentials
- Uses `EMERGENT_LLM_KEY` (from .env, get from Emergent dashboard)
- Auth via session-scoped `storage_key` from `/init`

## Init pattern (ONCE at startup)
```python
STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_NAME = "your-app-name"  # Prefix all paths
storage_key = None  # Module-level, reused globally

def init_storage():
    global storage_key
    if storage_key:
        return storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    resp.raise_for_status()
    storage_key = resp.json()["storage_key"]
    return storage_key
```

## Upload (PUT)
```python
def put_object(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=120
    )
    resp.raise_for_status()
    return resp.json()  # {"path": "...", "size": 123, "etag": "..."}
```

## Download (GET)
```python
def get_object(path: str) -> tuple[bytes, str]:
    key = init_storage()
    resp = requests.get(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key}, timeout=60
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")
```

## Path convention
```
{app_name}/uploads/{user_id}/{uuid}.{ext}
```
- No leading slash
- UUID filenames to prevent collisions
- Store original filename in DB, not path

## FastAPI integration
```python
@app.on_event("startup")
async def startup():
    init_storage()

@api_router.post("/upload")
async def upload(file: UploadFile = File(...)):
    ext = file.filename.split(".")[-1] if "." in file.filename else "bin"
    path = f"{APP_NAME}/uploads/{user_id}/{uuid.uuid4()}.{ext}"
    data = await file.read()
    result = put_object(path, data, file.content_type or "application/octet-stream")
    await db.files.insert_one({
        "id": str(uuid.uuid4()),
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": file.content_type,
        "size": result["size"],
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    return result
```

## Frontend image display (CRITICAL pattern)
`<img src>` cannot pass Authorization headers. Two options:

### Option 1: Query param auth
```javascript
<img src={`${API}/files/${id}?auth=${token}`} />
```

### Option 2: Fetch as blob (more secure)
```javascript
const response = await axios.get(`${API}/files/${id}/download`, {
    headers: { Authorization: `Bearer ${token}` },
    responseType: 'blob'
});
const blobUrl = URL.createObjectURL(response.data);
// <img src={blobUrl} />
// Cleanup: URL.revokeObjectURL(blobUrl) on unmount
```

## Hard constraints
- ❌ No delete API — implement soft-delete in DB (`is_deleted: true`)
- ❌ No rename — upload to new path + update DB
- ❌ No presigned URLs — all access through your backend
- 📦 One bucket per user — use app-name prefix to isolate
- 📋 Max list results: 1000
- 🔁 Init once — `storage_key` is session-scoped

## Status codes
- `403`: Invalid/expired storage_key → re-init
- `404`: Object path doesn't exist
- `409`: Already exists → use UUID paths
- `429`: Rate limited → exponential backoff

## Content-Type lookup
```python
MIME_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "pdf": "application/pdf",
    "json": "application/json", "csv": "text/csv", "txt": "text/plain"
}
```

## Quality assessment
🥇 Best-in-class. Polished, Emergent-native, no bloat. ~3,500 chars.
