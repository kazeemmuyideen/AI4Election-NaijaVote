"""NaijaVote civic API. Data is only shown as authoritative when its source is recorded."""
from __future__ import annotations

import csv
import hashlib
import hmac
import json
import math
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DATABASE_PATH", str(ROOT / "data" / "naijavote.db")))
INEC_URL = "https://cvr.inecnigeria.org/pu"
SOURCES = {
    "INEC": "https://www.inecnigeria.org/voters/education",
    "INEC polling unit locator": INEC_URL,
    "INEC accessibility guidance": "https://www.inecnigeria.org/",
    "NiMet": "https://nimet.gov.ng/weatherapi.php",
    "NIHSA": "https://nihsa.gov.ng/",
}

FAQ: list[dict[str, Any]] = [
    {"id":"pvc", "keywords":["pvc","card","bring","document","vote"], "question":"What do I need to bring to vote?", "answer":"Bring your Permanent Voter’s Card (PVC). INEC’s official guidance should be checked for the election you plan to attend.", "source":"INEC", "source_url":SOURCES["INEC"], "language":"en"},
    {"id":"hours", "keywords":["time","when","open","close","hours","schedule"], "question":"What time does voting happen?", "answer":"INEC’s published election-day guidance says polling units open at 8:30 AM and voting closes at 2:30 PM; voters already in the queue by closing time are allowed to vote. Check the notice for your specific election in case its schedule differs.", "source":"INEC voter education", "source_url":SOURCES["INEC"], "language":"en"},
    {"id":"secret", "keywords":["secret","privacy","ballot","private"], "question":"Is my vote secret?", "answer":"Yes. Mark your ballot privately in the voting cubicle. Do not show or photograph your marked ballot.", "source":"INEC voter education", "source_url":SOURCES["INEC"], "language":"en"},
    {"id":"priority", "keywords":["priority","elderly","old","pregnant","nursing","breastfeeding","queue"], "question":"Who can receive priority access?", "answer":"INEC’s election guidelines provide priority access for persons with disabilities, visibly pregnant women, nursing or breastfeeding mothers, and elderly voters. Ask an official at your polling unit for the priority queue and confirm current procedures with INEC.", "source":"INEC election guidelines", "source_url":"https://www.inecnigeria.org/elections/guidelines", "language":"en"},
    {"id":"disability", "keywords":["disability","disabled","pwd","wheelchair","blind","accessibility","assistance"], "question":"Can I get assistance to vote?", "answer":"Voters with disabilities can request assistance at the polling unit. Ask an INEC official about the current procedure and available accessibility arrangements for your location.", "source":"INEC", "source_url":SOURCES["INEC"], "language":"en"},
    {"id":"locate", "keywords":["polling unit","where vote","location","find my","ward","lga"], "question":"How do I find my polling unit?", "answer":"Use INEC’s official polling-unit locator and check the polling-unit details on your PVC. This service does not have a verified nationwide polling-unit register loaded yet.", "source":"INEC polling unit locator", "source_url":INEC_URL, "language":"en"},
    {"id":"weather", "keywords":["weather","flood","rain","heat","route","safe"], "question":"How should I plan around weather?", "answer":"Check current alerts from NiMet and NIHSA before travelling, then follow local emergency guidance. This service does not have a live forecast feed or verified polling-unit route data connected yet.", "source":"NiMet", "source_url":SOURCES["NiMet"], "language":"en"},
]

@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def init_db() -> None:
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS polling_units (
          id TEXT PRIMARY KEY, state TEXT NOT NULL, lga TEXT NOT NULL, ward TEXT NOT NULL,
          name TEXT NOT NULL, code TEXT NOT NULL, latitude REAL, longitude REAL,
          accessibility TEXT NOT NULL DEFAULT 'unknown', source TEXT NOT NULL,
          source_url TEXT NOT NULL, verified_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS pu_search ON polling_units(state, lga, ward);
        CREATE TABLE IF NOT EXISTS hazard_reports (
          id TEXT PRIMARY KEY, state TEXT NOT NULL, lga TEXT, ward TEXT,
          latitude REAL, longitude REAL, hazard TEXT NOT NULL, severity INTEGER NOT NULL,
          details TEXT NOT NULL, source TEXT NOT NULL, source_url TEXT NOT NULL,
          observed_at TEXT NOT NULL, expires_at TEXT
        );
        CREATE INDEX IF NOT EXISTS hazard_area ON hazard_reports(state, lga, ward);
        CREATE TABLE IF NOT EXISTS knowledge (
          id TEXT PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL,
          language TEXT NOT NULL, keywords TEXT NOT NULL, source TEXT NOT NULL,
          source_url TEXT NOT NULL, verified_at TEXT NOT NULL
        );
        """)
        for item in FAQ:
            con.execute("INSERT OR IGNORE INTO knowledge VALUES(?,?,?,?,?,?,?,?)", (item['id'],item['question'],item['answer'],item['language'],json.dumps(item['keywords']),item['source'],item['source_url'],"2026-11-09"))

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield

app = FastAPI(title="NaijaVote Navigators API", version="1.0.0", description="Nonpartisan civic information, verified polling units, and source-backed climate risk data.", lifespan=lifespan)
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET","POST"], allow_headers=["Content-Type","X-Twilio-Signature"])

class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    language: str = Field(default="en", pattern="^(en|pcm|ha|ig|yo)$")

class UnitUpload(BaseModel):
    state: str; lga: str; ward: str; name: str; code: str
    latitude: float | None = None; longitude: float | None = None
    accessibility: str = "unknown"; source: str; source_url: str
    verified_at: str

class HazardUpload(BaseModel):
    state: str; lga: str | None = None; ward: str | None = None
    latitude: float | None = None; longitude: float | None = None
    hazard: str; severity: int = Field(ge=0, le=100); details: str
    source: str; source_url: str; observed_at: str; expires_at: str | None = None

class KnowledgeUpload(BaseModel):
    id: str = Field(min_length=2,max_length=100)
    question: str = Field(min_length=5,max_length=1000)
    answer: str = Field(min_length=5,max_length=5000)
    language: str = Field(pattern="^(en|pcm|ha|ig|yo)$")
    keywords: list[str] = Field(min_length=1,max_length=30)
    source: str = Field(min_length=2,max_length=200)
    source_url: str
    verified_at: str

def _match(query: str, keywords: list[str]) -> int:
    q = query.casefold()
    return sum(3 if key in q else 0 for key in keywords)

def _grounded_answer(query: str) -> dict[str, Any]:
    with db() as con:
        rows = con.execute("SELECT * FROM knowledge").fetchall()
    ranked = sorted((( _match(query, json.loads(row['keywords'])), row) for row in rows), key=lambda x:x[0], reverse=True)
    if not ranked or ranked[0][0] == 0:
        return {"answer":"I don’t have a verified answer for that question yet. Please check INEC’s official voter education information or contact an INEC office.", "confidence":"low", "citations":[{"title":"INEC voter education","url":SOURCES['INEC']}], "language":"en"}
    score,row = ranked[0]
    return {"answer":row['answer'], "confidence":"high" if score >= 3 else "medium", "citations":[{"title":row['source'],"url":row['source_url'],"verified_at":row['verified_at']}], "language":row['language']}

@app.get("/api/health")
def health():
    with db() as con:
        counts={t:con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("polling_units","hazard_reports","knowledge")}
    return {"status":"ok","data":counts,"integrations":{"inec_directory":counts['polling_units']>0,"nimet":bool(os.getenv('NIMET_API_KEY') and os.getenv('NIMET_ENDPOINT')),"nihsa_feed":bool(os.getenv('NIHSA_FEED_URL')),"llm":bool(os.getenv('LLM_API_KEY')),"whatsapp":bool(os.getenv('TWILIO_AUTH_TOKEN'))}}

@app.get("/api/config")
def config():
    return {"languages":[{"code":"en","name":"English"},{"code":"pcm","name":"Nigerian Pidgin"},{"code":"ha","name":"Hausa"},{"code":"ig","name":"Igbo"},{"code":"yo","name":"Yorùbá"}],"official_locator":INEC_URL,"features":{"voice_input":True,"voice_output":True,"live_weather":bool(os.getenv('NIMET_API_KEY')),"polling_unit_lookup":True}}

@app.post("/api/ask")
async def ask(payload: AskRequest):
    result=_grounded_answer(payload.question)
    if payload.language != "en" and result.get("language") != payload.language:
        key=os.getenv("LLM_API_KEY"); endpoint=os.getenv("LLM_BASE_URL","https://api.openai.com/v1/chat/completions"); model=os.getenv("LLM_MODEL","gpt-4o-mini")
        if key:
            language_names={"pcm":"Nigerian Pidgin","ha":"Hausa","ig":"Igbo","yo":"Yorùbá"}
            prompt=("Translate the answer below into "+language_names[payload.language]+". Preserve its meaning exactly. Do not add, omit, or infer civic instructions. Return only the translation.\n\n"+result['answer'])
            try:
                if not endpoint.startswith("https://"): raise ValueError("Translation endpoint must use HTTPS")
                async with httpx.AsyncClient(timeout=20) as client:
                    response=await client.post(endpoint,headers={"Authorization":f"Bearer {key}"},json={"model":model,"temperature":0,"messages":[{"role":"user","content":prompt}]}); response.raise_for_status()
                translated=response.json()["choices"][0]["message"]["content"].strip()
                if translated: result['answer']=translated; result['language']=payload.language
                else: raise ValueError("empty translation")
            except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError):
                result['requested_language']=payload.language
                result['notice']='A translated answer is temporarily unavailable. English source text is shown to avoid inventing civic guidance.'
        else:
            result['requested_language']=payload.language
            result['notice']='Verified language translation is not configured. English source text is shown to avoid inventing civic guidance.'
    return result

@app.get("/api/polling-units")
def polling_units(state: str, lga: str = "", ward: str = "", q: str = "", limit: int = Query(default=20, ge=1, le=100)):
    clauses=["state LIKE ?"]; args=[f"%{state}%"]
    if lga: clauses.append("(lga LIKE ? OR ward LIKE ?)"); args.extend([f"%{lga}%",f"%{lga}%"])
    if ward: clauses.append("ward LIKE ?"); args.append(f"%{ward}%")
    if q: clauses.append("(name LIKE ? OR code LIKE ?)"); args.extend([f"%{q}%",f"%{q}%"])
    with db() as con: rows=con.execute(f"SELECT * FROM polling_units WHERE {' AND '.join(clauses)} ORDER BY lga,ward,name LIMIT ?",(*args,limit)).fetchall()
    return {"results":[dict(r) for r in rows],"count":len(rows),"source":"source-attributed local register","official_locator":INEC_URL,"notice":None if rows else "No verified polling units were found in the local data. Use INEC’s official locator for your assigned unit."}

@app.get("/api/risk")
def risk(state: str, lga: str = "", ward: str = ""):
    clauses=["state LIKE ?"]; args=[f"%{state}%"]
    for col,val in (("lga",lga),("ward",ward)):
        if val: clauses.append(f"({col} IS NULL OR {col} LIKE ?)"); args.append(f"%{val}%")
    now=datetime.now(timezone.utc).isoformat()
    with db() as con: rows=con.execute(f"SELECT * FROM hazard_reports WHERE {' AND '.join(clauses)} AND (expires_at IS NULL OR expires_at > ?)",(*args,now)).fetchall()
    alerts=[dict(r) for r in rows]
    score=max((r['severity'] for r in alerts),default=None)
    return {"state":state,"risk_score":score,"risk_level":("high" if score>=70 else "moderate" if score>=35 else "low") if score is not None else "unknown","alerts":alerts,"source_status":"connected" if alerts else "no verified local alerts","note":"Risk scores reflect only current imported official alerts; no alert does not mean no hazard.","sources":[{"title":"NiMet weather API","url":SOURCES['NiMet']},{"title":"NIHSA flood information","url":SOURCES['NIHSA']}]}

def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius=6371.0
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return radius*2*math.atan2(math.sqrt(a),math.sqrt(1-a))

@app.get("/api/polling-units/{unit_id}/risk")
def unit_risk(unit_id: str):
    now=datetime.now(timezone.utc).isoformat()
    with db() as con:
        unit=con.execute("SELECT * FROM polling_units WHERE id=?",(unit_id,)).fetchone()
        if not unit: raise HTTPException(404,"Polling unit not found in verified local data")
        if unit['latitude'] is None or unit['longitude'] is None:
            return {"polling_unit":unit['name'],"risk_level":"unknown","risk_score":None,"alerts":[],"note":"This polling unit has no verified coordinates in the local register."}
        hazards=con.execute("SELECT * FROM hazard_reports WHERE state LIKE ? AND latitude IS NOT NULL AND longitude IS NOT NULL AND (expires_at IS NULL OR expires_at > ?)",(f"%{unit['state']}%",now)).fetchall()
    radius=float(os.getenv("RISK_PROXIMITY_KM","10"))
    nearby=[]
    for hazard in hazards:
        km=distance_km(unit['latitude'],unit['longitude'],hazard['latitude'],hazard['longitude'])
        if km<=radius:
            alert=dict(hazard); alert['distance_km']=round(km,1); nearby.append(alert)
    nearby.sort(key=lambda item:item['distance_km'])
    score=max((item['severity'] for item in nearby),default=None)
    return {"polling_unit":unit['name'],"risk_level":("high" if score>=70 else "moderate" if score>=35 else "low") if score is not None else "unknown","risk_score":score,"proximity_radius_km":radius,"alerts":nearby,"note":"Only current geolocated reports within the configured proximity radius are included. Unknown means no matching report is available; it does not mean safe."}

@app.get("/api/weather/{state}")
async def weather(state: str):
    key=os.getenv("NIMET_API_KEY"); endpoint=os.getenv("NIMET_ENDPOINT")
    if not key or not endpoint: return {"available":False,"message":"NiMet API access is not configured.","source":SOURCES['NiMet']}
    if not endpoint.startswith("https://"): raise HTTPException(500,"NIMET_ENDPOINT must use HTTPS")
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response=await client.get(endpoint,params={"state":state},headers={"x-api-key":key}); response.raise_for_status()
        return {"available":True,"data":response.json(),"source":SOURCES['NiMet'],"retrieved_at":datetime.now(timezone.utc).isoformat()}
    except (httpx.HTTPError,ValueError) as exc:
        return JSONResponse(status_code=502,content={"available":False,"message":"NiMet could not provide an update right now.","source":SOURCES['NiMet']})

def _require_admin(request: Request):
    token=os.getenv("ADMIN_API_TOKEN")
    if not token or token=="replace-with-a-long-random-secret": raise HTTPException(503,"Set a unique ADMIN_API_TOKEN before using admin routes")
    if not hmac.compare_digest(request.headers.get("authorization", "").removeprefix("Bearer "),token):
        raise HTTPException(401,"Valid admin bearer token required")

@app.post("/api/admin/polling-units")
def add_unit(payload: UnitUpload, request: Request):
    _require_admin(request)
    if not payload.source_url.startswith("https://"): raise HTTPException(400,"source_url must be HTTPS")
    identity=f"{payload.state}|{payload.lga}|{payload.ward}|{payload.code}"
    uid=hashlib.sha256(identity.casefold().encode()).hexdigest()[:24]
    with db() as con:
        con.execute("INSERT OR REPLACE INTO polling_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(uid,payload.state,payload.lga,payload.ward,payload.name,payload.code,payload.latitude,payload.longitude,payload.accessibility,payload.source,payload.source_url,payload.verified_at))
    return {"id":uid,"status":"saved"}

@app.post("/api/admin/hazards")
def add_hazard(payload: HazardUpload, request: Request):
    _require_admin(request)
    if not payload.source_url.startswith("https://"): raise HTTPException(400,"source_url must be HTTPS")
    identity=f"{payload.state}|{payload.lga}|{payload.ward}|{payload.hazard}|{payload.observed_at}"
    uid=hashlib.sha256(identity.casefold().encode()).hexdigest()[:24]
    with db() as con:
        con.execute("INSERT OR REPLACE INTO hazard_reports VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(uid,payload.state,payload.lga,payload.ward,payload.latitude,payload.longitude,payload.hazard,payload.severity,payload.details,payload.source,payload.source_url,payload.observed_at,payload.expires_at))
    return {"id":uid,"status":"saved"}

@app.post("/api/admin/import-polling-units")
async def import_units(request: Request):
    _require_admin(request)
    body=await request.body()
    if len(body)>20_000_000: raise HTTPException(413,"CSV exceeds 20 MB")
    try:
        reader=csv.DictReader(body.decode("utf-8-sig").splitlines())
        needed={"state","lga","ward","name","code","source","source_url","verified_at"}
        if not needed.issubset(set(reader.fieldnames or [])): raise ValueError(f"Required CSV columns: {', '.join(sorted(needed))}")
        items=[]
        for row in reader:
            for key in ("latitude","longitude","accessibility"):
                if row.get(key)=="": row[key]=None if key!="accessibility" else "unknown"
            p=UnitUpload(**row); identity=f"{p.state}|{p.lga}|{p.ward}|{p.code}"; uid=hashlib.sha256(identity.casefold().encode()).hexdigest()[:24]
            items.append((uid,p.state,p.lga,p.ward,p.name,p.code,p.latitude,p.longitude,p.accessibility,p.source,p.source_url,p.verified_at))
    except (UnicodeDecodeError,ValueError,TypeError) as exc: raise HTTPException(400,str(exc)) from exc
    with db() as con: con.executemany("INSERT OR REPLACE INTO polling_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",items)
    return {"imported":len(items)}

@app.post("/api/admin/knowledge")
def add_knowledge(payload: KnowledgeUpload, request: Request):
    _require_admin(request)
    if not payload.source_url.startswith("https://"): raise HTTPException(400,"source_url must be HTTPS")
    with db() as con:
        con.execute("INSERT OR REPLACE INTO knowledge VALUES(?,?,?,?,?,?,?,?)",(payload.id,payload.question,payload.answer,payload.language,json.dumps([x.casefold() for x in payload.keywords]),payload.source,payload.source_url,payload.verified_at))
    return {"id":payload.id,"status":"saved"}

@app.post("/api/webhooks/whatsapp")
async def whatsapp(request: Request):
    form=await request.form()
    token=os.getenv("TWILIO_AUTH_TOKEN")
    signature=request.headers.get("X-Twilio-Signature", "")
    if not token: raise HTTPException(503,"WhatsApp webhook is not configured")
    signed=os.getenv("TWILIO_WEBHOOK_URL",str(request.url))
    signed+= ''.join(key+str(form.get(key,"")) for key in sorted(form.keys()))
    expected=__import__('base64').b64encode(hmac.new(token.encode(),signed.encode(),hashlib.sha1).digest()).decode()
    if not hmac.compare_digest(signature,expected): raise HTTPException(403,"Invalid provider signature")
    incoming=str(form.get("Body", "")).strip(); sender=str(form.get("From", ""))
    if not incoming: return Response(content="<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Message>Please send a civic question. For official information, visit inecnigeria.org.</Message></Response>",media_type="application/xml")
    result=_grounded_answer(incoming)
    reply=f"{result['answer']} Source: {result['citations'][0]['url']}"
    xml=f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Message>{reply.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')}</Message></Response>"
    return Response(content=xml,media_type="application/xml")

@app.post("/api/admin/sync-nihsa")
async def sync_nihsa(request: Request):
    _require_admin(request)
    feed=os.getenv("NIHSA_FEED_URL")
    if not feed: raise HTTPException(503,"Configure an authorized NIHSA_FEED_URL first")
    headers={}
    if os.getenv("NIHSA_API_TOKEN"): headers["Authorization"]=f"Bearer {os.getenv('NIHSA_API_TOKEN')}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response=await client.get(feed,headers=headers); response.raise_for_status(); data=response.json()
        if not isinstance(data,list): raise ValueError("Expected a JSON array of normalized hazard reports")
        imported=0
        for raw in data:
            report=HazardUpload(**raw)
            hostname=urlparse(report.source_url).hostname or ""
            if not (hostname=="nihsa.gov.ng" or hostname.endswith(".nihsa.gov.ng")):
                raise ValueError("Each report must cite an official NIHSA source URL")
            identity=f"{report.state}|{report.lga}|{report.ward}|{report.hazard}|{report.observed_at}"
            uid=hashlib.sha256(identity.casefold().encode()).hexdigest()[:24]
            with db() as con: con.execute("INSERT OR REPLACE INTO hazard_reports VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(uid,report.state,report.lga,report.ward,report.latitude,report.longitude,report.hazard,report.severity,report.details,report.source,report.source_url,report.observed_at,report.expires_at))
            imported+=1
        return {"imported":imported,"source":"NIHSA authorized feed"}
    except (httpx.HTTPError,ValueError,TypeError) as exc: raise HTTPException(502,f"NIHSA feed could not be normalized: {exc}") from exc

@app.get("/", include_in_schema=False)
def frontend(): return FileResponse(ROOT / "index.html")

@app.get("/styles.css", include_in_schema=False)
def stylesheet(): return FileResponse(ROOT / "styles.css", media_type="text/css")

@app.get("/app.js", include_in_schema=False)
def frontend_script(): return FileResponse(ROOT / "app.js", media_type="application/javascript")

@app.get("/sw.js", include_in_schema=False)
def service_worker(): return FileResponse(ROOT / "sw.js", media_type="application/javascript")

@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest(): return FileResponse(ROOT / "manifest.webmanifest", media_type="application/manifest+json")

@app.get("/favicon.svg", include_in_schema=False)
def icon(): return FileResponse(ROOT / "favicon.svg", media_type="image/svg+xml")

