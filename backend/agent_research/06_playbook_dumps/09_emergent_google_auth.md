# Raw Playbook Dump: Emergent Google Auth

**Query:** "Emergent-managed Google Auth (Google social login) in a FastAPI + React app."

**Has VERIFIED label:** No (hand-curated, polished)

## Credentials
- **NONE** — Emergent manages OAuth entirely. No client ID/secret needed.

## Endpoints
- **Redirect to login:** `https://auth.emergentagent.com/?redirect={your_redirect}`
- **Exchange session_id for session_token:** `GET https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data`
  - Header: `X-Session-ID: <session_id>`
  - Returns: `{"id", "email", "name", "picture", "session_token"}`

## Critical rule
> "REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH"

## Login button
```javascript
// MUST derive from window.location.origin
const redirectUrl = window.location.origin + '/dashboard';
window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
```

## After Google auth, user lands at
```
{redirect_url}#session_id={session_id}
```
(in URL **fragment**, NOT query string)

## Backend session exchange (MUST be done server-side)
```python
# DO NOT call /session-data from frontend
response = requests.get(
    "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
    headers={"X-Session-ID": session_id}
)
data = response.json()  # {id, email, name, picture, session_token}
```

## Session storage
- Store `session_token` in DB with **timezone-aware** expiry (7 days)
- Set httpOnly cookie: `path="/", secure=True, samesite="none"`

## User ID pattern (CRITICAL)
Generate own `user_id` field as UUID, exclude MongoDB `_id`:
```python
user_id = f"user_{uuid.uuid4().hex[:12]}"
await db.users.insert_one({
    "user_id": user_id,
    "email": email,
    "name": name,
    "created_at": datetime.now(timezone.utc)
})

# Always exclude _id when querying
user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})

class User(BaseModel):
    user_id: str
    email: str
    name: str
```

## Expiry comparison fix
```python
expires_at = session_doc["expires_at"]
if isinstance(expires_at, str):
    expires_at = datetime.fromisoformat(expires_at)
if expires_at.tzinfo is None:
    expires_at = expires_at.replace(tzinfo=timezone.utc)
if expires_at < datetime.now(timezone.utc):
    raise HTTPException(401, "Session expired")
```

## Race condition: AuthProvider vs AuthCallback
```javascript
useEffect(() => {
    // CRITICAL: If returning from OAuth callback, skip the /me check.
    // AuthCallback will exchange the session_id first.
    if (window.location.hash?.includes('session_id=')) {
      setLoading(false);
      return;
    }
    checkAuth();
}, [checkAuth]);
```

## Routing detection (sync, not in useEffect)
```javascript
function AppRouter() {
  const location = useLocation();
  // Check URL fragment SYNCHRONOUSLY during render
  if (location.hash?.includes('session_id=')) {
    return <AuthCallback />;
  }
  return <Routes>{/* normal */}</Routes>;
}
```

## AuthCallback useRef pattern
Use `useRef` (not `useState`) for the processed flag to prevent StrictMode double-fire:
```javascript
const hasProcessed = useRef(false);
useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;
    // ... exchange session_id ...
}, []);
```

## Testing playbook (mongosh)
```javascript
db.users.insertOne({
  user_id: userId,
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Test User',
  created_at: new Date()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
});
```

## Quality assessment
🥇 Polished, Emergent-native, ~5,000 chars with detailed race-condition fixes that reveal hard-won bugs from past implementations.
