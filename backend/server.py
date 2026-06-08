from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import uuid
import logging
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal

from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr, ConfigDict

# -------------------- DB --------------------
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# -------------------- App --------------------
app = FastAPI(title="Bloom CRM API")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("crm")

# -------------------- Auth utils --------------------
JWT_ALGO = "HS256"

def jwt_secret() -> str:
    return os.environ["JWT_SECRET"]

def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False

def make_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email,
               "exp": datetime.now(timezone.utc) + timedelta(hours=12),
               "type": "access"}
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGO)

def make_refresh_token(user_id: str) -> str:
    payload = {"sub": user_id,
               "exp": datetime.now(timezone.utc) + timedelta(days=7),
               "type": "refresh"}
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGO)

def set_auth_cookies(resp: Response, access: str, refresh: str):
    resp.set_cookie("access_token", access, httponly=True, secure=False, samesite="lax",
                    max_age=12 * 3600, path="/")
    resp.set_cookie("refresh_token", refresh, httponly=True, secure=False, samesite="lax",
                    max_age=7 * 24 * 3600, path="/")

async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGO])
        if payload.get("type") != "access":
            raise HTTPException(401, "Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
        if not user:
            raise HTTPException(401, "User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")

# -------------------- Models --------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=6)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str = "user"
    created_at: str

class CompanyIn(BaseModel):
    name: str
    industry: Optional[str] = None
    website: Optional[str] = None
    size: Optional[str] = None
    notes: Optional[str] = None

class Company(CompanyIn):
    id: str
    created_at: str

class ContactIn(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    status: Literal["lead", "active", "customer", "inactive"] = "lead"
    tags: List[str] = []
    notes: Optional[str] = None

class Contact(ContactIn):
    id: str
    created_at: str
    lead_score: Optional[int] = None
    score_reasoning: Optional[str] = None

DealStage = Literal["lead", "qualified", "proposal", "negotiation", "won", "lost"]

class DealIn(BaseModel):
    title: str
    value: float = 0
    stage: DealStage = "lead"
    contact_id: Optional[str] = None
    contact_name: Optional[str] = None
    company: Optional[str] = None
    close_date: Optional[str] = None
    probability: int = 20
    notes: Optional[str] = None

class Deal(DealIn):
    id: str
    created_at: str

class TaskIn(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    priority: Literal["low", "medium", "high"] = "medium"
    completed: bool = False
    contact_id: Optional[str] = None
    deal_id: Optional[str] = None

class Task(TaskIn):
    id: str
    created_at: str

class NoteIn(BaseModel):
    contact_id: str
    content: str
    type: Literal["note", "call", "email", "meeting"] = "note"

class Note(NoteIn):
    id: str
    created_at: str
    author: Optional[str] = None

# -------------------- Helpers --------------------
def new_id() -> str:
    return str(uuid.uuid4())

def strip_mongo(doc):
    if doc and "_id" in doc:
        doc.pop("_id", None)
    return doc

# -------------------- Auth Endpoints --------------------
@api.post("/auth/register", response_model=UserOut)
async def register(payload: RegisterIn, response: Response):
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Email already registered")
    user = {
        "id": new_id(),
        "name": payload.name,
        "email": email,
        "password_hash": hash_password(payload.password),
        "role": "user",
        "created_at": now_iso(),
    }
    await db.users.insert_one(user)
    set_auth_cookies(response, make_access_token(user["id"], email), make_refresh_token(user["id"]))
    return UserOut(**{k: v for k, v in user.items() if k != "password_hash"})

@api.post("/auth/login", response_model=UserOut)
async def login(payload: LoginIn, response: Response):
    email = payload.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    set_auth_cookies(response, make_access_token(user["id"], email), make_refresh_token(user["id"]))
    user = strip_mongo(user)
    user.pop("password_hash", None)
    return UserOut(**user)

@api.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}

@api.get("/auth/me", response_model=UserOut)
async def me(current=Depends(get_current_user)):
    return UserOut(**current)

@api.post("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    rt = request.cookies.get("refresh_token")
    if not rt:
        raise HTTPException(401, "No refresh token")
    try:
        payload = jwt.decode(rt, jwt_secret(), algorithms=[JWT_ALGO])
        if payload.get("type") != "refresh":
            raise HTTPException(401, "Invalid token")
        user = await db.users.find_one({"id": payload["sub"]})
        if not user:
            raise HTTPException(401, "User not found")
        set_auth_cookies(response, make_access_token(user["id"], user["email"]), rt)
        return {"ok": True}
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid refresh token")

# -------------------- Companies --------------------
@api.get("/companies", response_model=List[Company])
async def list_companies(current=Depends(get_current_user)):
    rows = await db.companies.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return rows

@api.post("/companies", response_model=Company)
async def create_company(payload: CompanyIn, current=Depends(get_current_user)):
    doc = {"id": new_id(), "created_at": now_iso(), **payload.model_dump()}
    await db.companies.insert_one(doc)
    return strip_mongo(doc)

@api.put("/companies/{cid}", response_model=Company)
async def update_company(cid: str, payload: CompanyIn, current=Depends(get_current_user)):
    res = await db.companies.find_one_and_update(
        {"id": cid}, {"$set": payload.model_dump()}, return_document=True)
    if not res:
        raise HTTPException(404, "Not found")
    return strip_mongo(res)

@api.delete("/companies/{cid}")
async def delete_company(cid: str, current=Depends(get_current_user)):
    r = await db.companies.delete_one({"id": cid})
    return {"deleted": r.deleted_count}

# -------------------- Contacts --------------------
@api.get("/contacts", response_model=List[Contact])
async def list_contacts(current=Depends(get_current_user)):
    rows = await db.contacts.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return rows

@api.get("/contacts/{cid}", response_model=Contact)
async def get_contact(cid: str, current=Depends(get_current_user)):
    row = await db.contacts.find_one({"id": cid}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Not found")
    return row

@api.post("/contacts", response_model=Contact)
async def create_contact(payload: ContactIn, current=Depends(get_current_user)):
    doc = {"id": new_id(), "created_at": now_iso(),
           "lead_score": None, "score_reasoning": None, **payload.model_dump()}
    await db.contacts.insert_one(doc)
    return strip_mongo(doc)

@api.put("/contacts/{cid}", response_model=Contact)
async def update_contact(cid: str, payload: ContactIn, current=Depends(get_current_user)):
    res = await db.contacts.find_one_and_update(
        {"id": cid}, {"$set": payload.model_dump()}, return_document=True)
    if not res:
        raise HTTPException(404, "Not found")
    return strip_mongo(res)

@api.delete("/contacts/{cid}")
async def delete_contact(cid: str, current=Depends(get_current_user)):
    r = await db.contacts.delete_one({"id": cid})
    await db.notes.delete_many({"contact_id": cid})
    return {"deleted": r.deleted_count}

# -------------------- Deals --------------------
@api.get("/deals", response_model=List[Deal])
async def list_deals(current=Depends(get_current_user)):
    rows = await db.deals.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return rows

@api.post("/deals", response_model=Deal)
async def create_deal(payload: DealIn, current=Depends(get_current_user)):
    doc = {"id": new_id(), "created_at": now_iso(), **payload.model_dump()}
    await db.deals.insert_one(doc)
    return strip_mongo(doc)

@api.put("/deals/{did}", response_model=Deal)
async def update_deal(did: str, payload: DealIn, current=Depends(get_current_user)):
    res = await db.deals.find_one_and_update(
        {"id": did}, {"$set": payload.model_dump()}, return_document=True)
    if not res:
        raise HTTPException(404, "Not found")
    return strip_mongo(res)

class StageUpdate(BaseModel):
    stage: DealStage

@api.patch("/deals/{did}/stage", response_model=Deal)
async def update_deal_stage(did: str, payload: StageUpdate, current=Depends(get_current_user)):
    res = await db.deals.find_one_and_update(
        {"id": did}, {"$set": {"stage": payload.stage}}, return_document=True)
    if not res:
        raise HTTPException(404, "Not found")
    return strip_mongo(res)

@api.delete("/deals/{did}")
async def delete_deal(did: str, current=Depends(get_current_user)):
    r = await db.deals.delete_one({"id": did})
    return {"deleted": r.deleted_count}

# -------------------- Tasks --------------------
@api.get("/tasks", response_model=List[Task])
async def list_tasks(current=Depends(get_current_user)):
    rows = await db.tasks.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return rows

@api.post("/tasks", response_model=Task)
async def create_task(payload: TaskIn, current=Depends(get_current_user)):
    doc = {"id": new_id(), "created_at": now_iso(), **payload.model_dump()}
    await db.tasks.insert_one(doc)
    return strip_mongo(doc)

@api.put("/tasks/{tid}", response_model=Task)
async def update_task(tid: str, payload: TaskIn, current=Depends(get_current_user)):
    res = await db.tasks.find_one_and_update(
        {"id": tid}, {"$set": payload.model_dump()}, return_document=True)
    if not res:
        raise HTTPException(404, "Not found")
    return strip_mongo(res)

@api.delete("/tasks/{tid}")
async def delete_task(tid: str, current=Depends(get_current_user)):
    r = await db.tasks.delete_one({"id": tid})
    return {"deleted": r.deleted_count}

# -------------------- Notes --------------------
@api.get("/notes/{contact_id}", response_model=List[Note])
async def list_notes(contact_id: str, current=Depends(get_current_user)):
    rows = await db.notes.find({"contact_id": contact_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return rows

@api.post("/notes", response_model=Note)
async def create_note(payload: NoteIn, current=Depends(get_current_user)):
    doc = {"id": new_id(), "created_at": now_iso(), "author": current.get("name"),
           **payload.model_dump()}
    await db.notes.insert_one(doc)
    return strip_mongo(doc)

@api.delete("/notes/{nid}")
async def delete_note(nid: str, current=Depends(get_current_user)):
    r = await db.notes.delete_one({"id": nid})
    return {"deleted": r.deleted_count}

# -------------------- Dashboard --------------------
@api.get("/dashboard/stats")
async def dashboard_stats(current=Depends(get_current_user)):
    contacts_total = await db.contacts.count_documents({})
    deals = await db.deals.find({}, {"_id": 0}).to_list(2000)
    tasks_open = await db.tasks.count_documents({"completed": False})
    won = [d for d in deals if d["stage"] == "won"]
    pipeline = [d for d in deals if d["stage"] not in ("won", "lost")]
    revenue = sum(d.get("value", 0) for d in won)
    pipeline_value = sum(d.get("value", 0) for d in pipeline)

    stage_breakdown = {}
    for s in ["lead", "qualified", "proposal", "negotiation", "won", "lost"]:
        stage_breakdown[s] = {
            "count": sum(1 for d in deals if d["stage"] == s),
            "value": sum(d.get("value", 0) for d in deals if d["stage"] == s),
        }

    # Revenue trend last 6 months
    months = []
    now = datetime.now(timezone.utc).replace(day=1)
    for i in range(5, -1, -1):
        m = now - timedelta(days=30 * i)
        months.append({"label": m.strftime("%b"), "month": m.strftime("%Y-%m"), "value": 0})
    by_month = {m["month"]: m for m in months}
    for d in won:
        try:
            dt = datetime.fromisoformat(d["created_at"])
            key = dt.strftime("%Y-%m")
            if key in by_month:
                by_month[key]["value"] += d.get("value", 0)
        except Exception:
            pass

    recent = await db.contacts.find({}, {"_id": 0}).sort("created_at", -1).limit(5).to_list(5)

    return {
        "kpis": {
            "revenue": revenue,
            "deals_won": len(won),
            "pipeline_value": pipeline_value,
            "contacts": contacts_total,
            "tasks_open": tasks_open,
        },
        "stage_breakdown": stage_breakdown,
        "revenue_trend": months,
        "recent_contacts": recent,
    }

# -------------------- AI --------------------
class LeadScoreIn(BaseModel):
    contact_id: str

class EmailDraftIn(BaseModel):
    contact_id: Optional[str] = None
    deal_id: Optional[str] = None
    purpose: str = "follow-up"
    tone: str = "friendly professional"
    context: Optional[str] = None

async def _llm_chat(system: str, user_text: str) -> str:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    key = os.environ["EMERGENT_LLM_KEY"]
    chat = LlmChat(
        api_key=key,
        session_id=f"crm-{uuid.uuid4()}",
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-4-5-20250929")
    resp = await chat.send_message(UserMessage(text=user_text))
    return str(resp)

@api.post("/ai/lead-score")
async def ai_lead_score(payload: LeadScoreIn, current=Depends(get_current_user)):
    contact = await db.contacts.find_one({"id": payload.contact_id}, {"_id": 0})
    if not contact:
        raise HTTPException(404, "Contact not found")
    deals = await db.deals.find({"contact_id": payload.contact_id}, {"_id": 0}).to_list(50)
    notes = await db.notes.find({"contact_id": payload.contact_id}, {"_id": 0}).sort("created_at", -1).limit(10).to_list(10)

    system = (
        "You are a senior sales operations analyst. Given a CRM contact, related deals and notes, "
        "produce a lead score from 0 to 100 and a short reasoning (max 3 sentences). "
        "Respond in STRICT JSON ONLY with the shape: {\"score\": <int>, \"reasoning\": \"<text>\"}. "
        "No prose, no markdown, no backticks."
    )
    user_text = (
        f"Contact:\n{contact}\n\nDeals:\n{deals}\n\nRecent notes:\n{notes}\n\n"
        "Score this lead based on engagement, deal value, status, and recent activity."
    )
    raw = await _llm_chat(system, user_text)
    import json, re
    score = 50
    reasoning = raw.strip()
    try:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = json.loads(m.group(0))
            score = int(data.get("score", 50))
            reasoning = data.get("reasoning", reasoning)
    except Exception as e:
        logger.warning(f"lead-score parse failed: {e}")
    score = max(0, min(100, score))
    await db.contacts.update_one({"id": payload.contact_id},
                                 {"$set": {"lead_score": score, "score_reasoning": reasoning}})
    return {"score": score, "reasoning": reasoning}

@api.post("/ai/email-draft")
async def ai_email_draft(payload: EmailDraftIn, current=Depends(get_current_user)):
    contact = None
    deal = None
    if payload.contact_id:
        contact = await db.contacts.find_one({"id": payload.contact_id}, {"_id": 0})
    if payload.deal_id:
        deal = await db.deals.find_one({"id": payload.deal_id}, {"_id": 0})

    system = (
        "You are an expert B2B sales writer. Draft concise, warm, high-converting emails. "
        "Output a JSON object with keys 'subject' and 'body' ONLY. No markdown, no backticks."
    )
    user_text = (
        f"Purpose: {payload.purpose}\nTone: {payload.tone}\n"
        f"Sender: {current.get('name','Sales')}\n"
        f"Contact: {contact}\nDeal: {deal}\n"
        f"Additional context: {payload.context or 'none'}\n"
        "Return JSON: {\"subject\": \"...\", \"body\": \"...\"}"
    )
    raw = await _llm_chat(system, user_text)
    import json, re
    subject = "Following up"
    body = raw.strip()
    try:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = json.loads(m.group(0))
            subject = data.get("subject", subject)
            body = data.get("body", body)
    except Exception as e:
        logger.warning(f"email-draft parse failed: {e}")
    return {"subject": subject, "body": body}

# -------------------- Seeding --------------------
async def seed_admin():
    email = os.environ.get("ADMIN_EMAIL", "admin@crm.com").lower()
    pw = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": email})
    if not existing:
        await db.users.insert_one({
            "id": new_id(),
            "name": "Admin",
            "email": email,
            "password_hash": hash_password(pw),
            "role": "admin",
            "created_at": now_iso(),
        })
        logger.info(f"Seeded admin user {email}")
    elif not verify_password(pw, existing["password_hash"]):
        await db.users.update_one({"email": email},
                                  {"$set": {"password_hash": hash_password(pw)}})

async def seed_demo_data():
    if await db.contacts.count_documents({}) > 0:
        return
    companies = [
        {"id": new_id(), "name": "Northwind Studio", "industry": "Design Agency",
         "website": "northwind.studio", "size": "11-50", "notes": "Boutique design studio",
         "created_at": now_iso()},
        {"id": new_id(), "name": "Acme Robotics", "industry": "Manufacturing",
         "website": "acme.io", "size": "200-500", "notes": "Industrial automation",
         "created_at": now_iso()},
        {"id": new_id(), "name": "Lumen Health", "industry": "Healthcare",
         "website": "lumenhealth.co", "size": "51-200", "notes": "Telehealth platform",
         "created_at": now_iso()},
        {"id": new_id(), "name": "Orbit Labs", "industry": "SaaS",
         "website": "orbitlabs.dev", "size": "11-50", "notes": "Developer tools",
         "created_at": now_iso()},
    ]
    await db.companies.insert_many(companies)

    contacts_seed = [
        ("Mira Patel", "mira@northwind.studio", "Creative Director", "Northwind Studio", "active",
         ["design", "priority"], "Met at conference. Interested in Pro plan."),
        ("Daniel Reyes", "daniel@acme.io", "Head of Procurement", "Acme Robotics", "lead",
         ["enterprise"], "Sent intro deck last week."),
        ("Sophie Lin", "sophie@lumenhealth.co", "VP Marketing", "Lumen Health", "customer",
         ["expansion"], "Upsell opportunity in Q2."),
        ("Theo Nakamura", "theo@orbitlabs.dev", "CTO", "Orbit Labs", "active",
         ["technical"], "Evaluating API integration."),
        ("Aisha Okafor", "aisha@northwind.studio", "Studio Manager", "Northwind Studio", "lead",
         ["referral"], "Referred by Mira."),
        ("Jonas Weber", "jonas@acme.io", "VP Engineering", "Acme Robotics", "inactive",
         [], "Went quiet after Q4."),
    ]
    contact_docs = []
    for n, e, t, c, s, tg, nt in contacts_seed:
        contact_docs.append({
            "id": new_id(), "name": n, "email": e, "phone": None, "title": t,
            "company": c, "status": s, "tags": tg, "notes": nt,
            "lead_score": None, "score_reasoning": None, "created_at": now_iso(),
        })
    await db.contacts.insert_many(contact_docs)

    deals_seed = [
        ("Pro Plan – Northwind", 18000, "proposal", contact_docs[0], 60),
        ("Enterprise pilot – Acme", 92000, "qualified", contact_docs[1], 35),
        ("Lumen expansion", 48000, "negotiation", contact_docs[2], 75),
        ("Orbit API license", 24000, "lead", contact_docs[3], 20),
        ("Northwind add-on", 6000, "won", contact_docs[0], 100),
        ("Acme retainer", 15000, "lost", contact_docs[5], 0),
        ("Lumen multi-seat", 32000, "won", contact_docs[2], 100),
    ]
    deal_docs = []
    for title, val, stage, c, prob in deals_seed:
        deal_docs.append({
            "id": new_id(), "title": title, "value": val, "stage": stage,
            "contact_id": c["id"], "contact_name": c["name"], "company": c["company"],
            "close_date": None, "probability": prob, "notes": None,
            "created_at": now_iso(),
        })
    await db.deals.insert_many(deal_docs)

    tasks_seed = [
        ("Send proposal to Mira", "Include case studies", "high", False, contact_docs[0]["id"]),
        ("Follow-up call with Daniel", None, "medium", False, contact_docs[1]["id"]),
        ("Quarterly review – Lumen", "Prep deck", "high", False, contact_docs[2]["id"]),
        ("Send pricing sheet to Theo", None, "low", True, contact_docs[3]["id"]),
        ("Reconnect with Jonas", "Has been quiet", "medium", False, contact_docs[5]["id"]),
    ]
    task_docs = []
    for t, d, p, done, cid in tasks_seed:
        task_docs.append({
            "id": new_id(), "title": t, "description": d, "due_date": None,
            "priority": p, "completed": done, "contact_id": cid, "deal_id": None,
            "created_at": now_iso(),
        })
    await db.tasks.insert_many(task_docs)

    notes_seed = [
        (contact_docs[0]["id"], "Demo went well. Mira wants pricing by Friday.", "meeting"),
        (contact_docs[0]["id"], "Sent proposal v2 with annual discount.", "email"),
        (contact_docs[1]["id"], "Daniel asked about security compliance.", "call"),
        (contact_docs[2]["id"], "Sophie excited about new dashboard features.", "call"),
    ]
    note_docs = []
    for cid, content, ntype in notes_seed:
        note_docs.append({
            "id": new_id(), "contact_id": cid, "content": content, "type": ntype,
            "author": "Admin", "created_at": now_iso(),
        })
    await db.notes.insert_many(note_docs)
    logger.info("Seeded demo data")

@app.on_event("startup")
async def on_start():
    await db.users.create_index("email", unique=True)
    await db.contacts.create_index("id", unique=True)
    await db.deals.create_index("id", unique=True)
    await db.companies.create_index("id", unique=True)
    await db.tasks.create_index("id", unique=True)
    await db.notes.create_index("id", unique=True)
    await seed_admin()
    await seed_demo_data()

@app.on_event("shutdown")
async def on_stop():
    client.close()

@api.get("/")
async def root():
    return {"message": "Bloom CRM API"}

app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
