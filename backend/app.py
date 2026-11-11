"""NaijaVote civic API. Data is only shown as authoritative when its source is recorded."""
from __future__ import annotations

import csv
import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

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

DECLINE_ANSWER = (
    "I don’t have a verified answer for that question yet. "
    "Please check INEC’s official voter education information or contact an INEC office."
)

ASK_RATE_LIMIT = int(os.getenv("ASK_RATE_LIMIT_PER_MINUTE", "60"))
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: dict[str, list[float]] = {}


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 date/datetime into an aware UTC datetime, or None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _is_active(expires_at: str | None, observed_at: str | None = None) -> bool:
    """A report is current when its timestamps are valid and it is not expired or future-dated."""
    now = datetime.now(timezone.utc)
    if observed_at:
        observed = _parse_datetime(observed_at)
        if observed is None or observed > now:
            return False
    if not expires_at:
        return False
    parsed = _parse_datetime(expires_at)
    return parsed is not None and parsed > now


def _iso_datetime(value: str) -> str:
    """Validate/normalize an ISO-8601 value to a UTC ISO string."""
    parsed = _parse_datetime(value)
    if parsed is None:
        raise ValueError("must be an ISO-8601 date or datetime")
    return parsed.isoformat()


def _https_url(value: str) -> str:
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
    except ValueError:
        raise ValueError("must be an absolute HTTPS URL") from None
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise ValueError("must be an absolute HTTPS URL")
    return value


def _like(value: str) -> str:
    """Escape LIKE wildcards so user input cannot match every row."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _check_rate_limit(request: Request) -> None:
    if ASK_RATE_LIMIT <= 0:
        return
    now = time.monotonic()
    key = request.client.host if request.client else "unknown"
    with _RATE_LOCK:
        bucket = _RATE_BUCKETS.setdefault(key, [])
        bucket[:] = [stamp for stamp in bucket if stamp > now - 60]
        if len(bucket) >= ASK_RATE_LIMIT:
            raise HTTPException(429, "Too many questions. Please wait a minute and try again.")
        bucket.append(now)


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
    con = sqlite3.connect(DB_PATH, timeout=10)
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
        con.execute("PRAGMA journal_mode=WAL")
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

app = FastAPI(title="NaijaVote Navigators API", version="1.1.0", description="Nonpartisan civic information, verified polling units, and source-backed climate risk data.", lifespan=lifespan)
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET","POST"], allow_headers=["Authorization","Content-Type","X-Twilio-Signature"])

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=(self)")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
        response.headers.setdefault("Content-Security-Policy", CSP)
    return response

class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=2, max_length=1000)
    language: str = Field(default="en", pattern="^(en|pcm|ha|ig|yo)$")

class UnitUpload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    state: str = Field(min_length=1, max_length=100)
    lga: str = Field(min_length=1, max_length=100)
    ward: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    code: str = Field(min_length=1, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    accessibility: str = "unknown"
    source: str = Field(min_length=1, max_length=200)
    source_url: str
    verified_at: str

    @model_validator(mode="after")
    def _coordinates_are_paired(self) -> "UnitUpload":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self

    @field_validator("source_url")
    @classmethod
    def _check_source_url(cls, value: str) -> str:
        return _https_url(value)

    @field_validator("verified_at")
    @classmethod
    def _check_verified_at(cls, value: str) -> str:
        return _iso_datetime(value)

class HazardUpload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    state: str = Field(min_length=1, max_length=100)
    lga: str | None = None
    ward: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    hazard: str = Field(min_length=1, max_length=100)
    severity: int = Field(ge=0, le=100)
    details: str = Field(min_length=1, max_length=5000)
    source: str = Field(min_length=1, max_length=200)
    source_url: str
    observed_at: str
    expires_at: str

    @model_validator(mode="after")
    def _validate_coordinates_and_expiry(self) -> "HazardUpload":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        if self.expires_at:
            observed = _parse_datetime(self.observed_at)
            expires = _parse_datetime(self.expires_at)
            if observed is not None and expires is not None and expires <= observed:
                raise ValueError("expires_at must be later than observed_at")
        return self

    @field_validator("source_url")
    @classmethod
    def _check_source_url(cls, value: str) -> str:
        return _https_url(value)

    @field_validator("observed_at")
    @classmethod
    def _check_observed_at(cls, value: str) -> str:
        return _iso_datetime(value)

    @field_validator("expires_at")
    @classmethod
    def _check_expires_at(cls, value: str) -> str:
        return _iso_datetime(value)

class KnowledgeUpload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: str = Field(min_length=2,max_length=100)
    question: str = Field(min_length=5,max_length=1000)
    answer: str = Field(min_length=5,max_length=5000)
    language: str = Field(pattern="^(en|pcm|ha|ig|yo)$")
    keywords: list[str] = Field(min_length=1,max_length=30)
    source: str = Field(min_length=2,max_length=200)
    source_url: str
    verified_at: str

    @field_validator("keywords")
    @classmethod
    def _check_keywords(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("keywords must not be empty")
        return cleaned

    @field_validator("source_url")
    @classmethod
    def _check_source_url(cls, value: str) -> str:
        return _https_url(value)

    @field_validator("verified_at")
    @classmethod
    def _check_verified_at(cls, value: str) -> str:
        return _iso_datetime(value)

def _match(query: str, keywords: list[str]) -> int:
    """Score keyword hits on whole words/phrases, not substrings."""
    q = query.casefold()
    score = 0
    for key in keywords:
        key = str(key).casefold().strip()
        if key and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", q):
            score += 3
    return score

def _grounded_answer(query: str, language: str = "en") -> dict[str, Any]:
    with db() as con:
        rows = con.execute("SELECT * FROM knowledge").fetchall()

    def best(candidates: list[sqlite3.Row]) -> tuple[int, sqlite3.Row] | None:
        ranked = sorted(((_match(query, json.loads(row['keywords'])), row) for row in candidates), key=lambda x: x[0], reverse=True)
        return ranked[0] if ranked and ranked[0][0] > 0 else None

    match = best([row for row in rows if row['language'] == language])
    if match is None and language != "en":
        match = best([row for row in rows if row['language'] == "en"])
    if match is None:
        return {"answer": DECLINE_ANSWER, "confidence": "low", "citations": [{"title": "INEC voter education", "url": SOURCES['INEC']}], "language": "en"}
    score, row = match
    return {"answer": row['answer'], "confidence": "high" if score >= 6 else "medium", "citations": [{"title": row['source'], "url": row['source_url'], "verified_at": row['verified_at']}], "language": row['language']}

@app.get("/api/health")
def health():
    with db() as con:
        counts={t:con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("polling_units","hazard_reports","knowledge")}
    return {"status":"ok","data":counts,"integrations":{"inec_directory":counts['polling_units']>0,"open_meteo":True,"nimet":bool(os.getenv('NIMET_API_KEY') and os.getenv('NIMET_ENDPOINT')),"nihsa_feed":bool(os.getenv('NIHSA_FEED_URL')),"llm":bool(os.getenv('LLM_API_KEY')),"whatsapp":bool(os.getenv('TWILIO_AUTH_TOKEN'))}}

@app.get("/api/config")
def config():
    return {"languages":[{"code":"en","name":"English"},{"code":"pcm","name":"Nigerian Pidgin"},{"code":"ha","name":"Hausa"},{"code":"ig","name":"Igbo"},{"code":"yo","name":"Yorùbá"}],"official_locator":INEC_URL,"features":{"voice_input":True,"voice_output":True,"live_weather":True,"weather_provider":"Open-Meteo (third-party; not NiMet)","polling_unit_lookup":True}}

@app.post("/api/ask")
async def ask(payload: AskRequest, request: Request):
    _check_rate_limit(request)
    result = await run_in_threadpool(_grounded_answer, payload.question, payload.language)
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
            except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError,AttributeError):
                result['requested_language']=payload.language
                result['notice']='A translated answer is temporarily unavailable. English source text is shown to avoid inventing civic guidance.'
        else:
            result['requested_language']=payload.language
            result['notice']='Verified language translation is not configured. English source text is shown to avoid inventing civic guidance.'
    return result

@app.get("/api/polling-units")
def polling_units(
    state: str = Query(min_length=1, max_length=100), lga: str = "", ward: str = "",
    q: str = "", limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    state=state.strip()
    if not state: raise HTTPException(422,"State must not be empty")
    clauses=["state LIKE ? ESCAPE '\\'"]; args=[f"%{_like(state)}%"]
    if lga: clauses.append("(lga LIKE ? ESCAPE '\\' OR ward LIKE ? ESCAPE '\\')"); args.extend([f"%{_like(lga)}%",f"%{_like(lga)}%"])
    if ward: clauses.append("ward LIKE ? ESCAPE '\\'"); args.append(f"%{_like(ward)}%")
    if q: clauses.append("(name LIKE ? ESCAPE '\\' OR code LIKE ? ESCAPE '\\')"); args.extend([f"%{_like(q)}%",f"%{_like(q)}%"])
    effective_clauses,effective_args=list(clauses),list(args)
    with db() as con:
        loaded_states=[row[0] for row in con.execute("SELECT DISTINCT state FROM polling_units ORDER BY state").fetchall()]
        total=con.execute(f"SELECT count(*) FROM polling_units WHERE {' AND '.join(effective_clauses)}",effective_args).fetchone()[0]
        ward_fallback=False
        if total==0 and lga and ward:
            effective_clauses=[clause for clause in clauses if not clause.startswith("ward LIKE")]
            effective_args=args[:-1]
            total=con.execute(f"SELECT count(*) FROM polling_units WHERE {' AND '.join(effective_clauses)}",effective_args).fetchone()[0]
            ward_fallback=total>0
        rows=con.execute(
            f"SELECT * FROM polling_units WHERE {' AND '.join(effective_clauses)} ORDER BY lga,ward,name LIMIT ? OFFSET ?",
            (*effective_args,limit,offset),
        ).fetchall()
    notice=None
    if total==0:
        matched_state=any(state.casefold() in item.casefold() or item.casefold() in state.casefold() for item in loaded_states)
        if matched_state:
            notice=f"No local polling units matched this search in {state}. Confirm the LGA or ward, or use INEC’s official locator."
        else:
            coverage=(f"The local directory currently covers {len(loaded_states)} of 37 states/FCT"
                      + (f" ({', '.join(loaded_states)}). " if loaded_states else ". "))
            notice=f"No local polling-unit records are loaded for {state} yet. {coverage}Use INEC’s official locator for your assigned unit."
    elif ward_fallback:
        notice=f"No local registration area matched ‘{ward}’ in {lga}. Showing records from the LGA; check your PVC or INEC’s official locator to confirm your assigned unit."
    return {"results":[dict(r) for r in rows],"count":len(rows),"total_count":total,"limit":limit,"offset":offset,"source":"source-attributed local register","coverage":{"loaded_states":loaded_states,"loaded_state_count":len(loaded_states),"total_states_and_fct":37},"official_locator":INEC_URL,"notice":notice}

@app.get("/api/risk")
def risk(state: str = Query(min_length=1, max_length=100), lga: str = "", ward: str = ""):
    state=state.strip()
    if not state: raise HTTPException(422,"State must not be empty")
    clauses=["state LIKE ? ESCAPE '\\'"]; args=[f"%{_like(state)}%"]
    for col,val in (("lga",lga),("ward",ward)):
        if val: clauses.append(f"({col} IS NULL OR {col} LIKE ? ESCAPE '\\')"); args.append(f"%{_like(val)}%")
    with db() as con: rows=con.execute(f"SELECT * FROM hazard_reports WHERE {' AND '.join(clauses)}",(*args,)).fetchall()
    alerts=[dict(r) for r in rows if _is_active(r['expires_at'], r['observed_at'])]
    score=max((r['severity'] for r in alerts),default=None)
    return {"state":state,"risk_score":score,"risk_level":("high" if score>=70 else "moderate" if score>=35 else "low") if score is not None else "unknown","alerts":alerts,"source_status":"connected" if alerts else "no verified local alerts","note":"Risk scores reflect only current imported official alerts; no alert does not mean no hazard.","sources":[{"title":"NiMet weather API","url":SOURCES['NiMet']},{"title":"NIHSA flood information","url":SOURCES['NIHSA']}]}

def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius=6371.0
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    a=min(1.0,max(0.0,a))
    return radius*2*math.atan2(math.sqrt(a),math.sqrt(1-a))

@app.get("/api/polling-units/{unit_id}/risk")
def unit_risk(unit_id: str):
    with db() as con:
        unit=con.execute("SELECT * FROM polling_units WHERE id=?",(unit_id,)).fetchone()
        if not unit: raise HTTPException(404,"Polling unit not found in verified local data")
        if unit['latitude'] is None or unit['longitude'] is None:
            return {"polling_unit":unit['name'],"risk_level":"unknown","risk_score":None,"alerts":[],"note":"This polling unit has no verified coordinates in the local register."}
        hazards=con.execute("SELECT * FROM hazard_reports WHERE state LIKE ? ESCAPE '\\' AND latitude IS NOT NULL AND longitude IS NOT NULL",(f"%{_like(unit['state'])}%",)).fetchall()
    radius=float(os.getenv("RISK_PROXIMITY_KM","10"))
    nearby=[]
    for hazard in hazards:
        if not _is_active(hazard['expires_at'], hazard['observed_at']):
            continue
        km=distance_km(unit['latitude'],unit['longitude'],hazard['latitude'],hazard['longitude'])
        if km<=radius:
            alert=dict(hazard); alert['distance_km']=round(km,1); nearby.append(alert)
    nearby.sort(key=lambda item:item['distance_km'])
    score=max((item['severity'] for item in nearby),default=None)
    return {"polling_unit":unit['name'],"risk_level":("high" if score>=70 else "moderate" if score>=35 else "low") if score is not None else "unknown","risk_score":score,"proximity_radius_km":radius,"alerts":nearby,"note":"Only current geolocated reports within the configured proximity radius are included. Unknown means no matching report is available; it does not mean safe."}

WEATHER_LOCATIONS = {
    "abia": (5.532, 7.486, "Umuahia"), "adamawa": (9.204, 12.495, "Yola"),
    "akwa ibom": (5.051, 7.933, "Uyo"), "anambra": (6.210, 7.074, "Awka"),
    "bauchi": (10.310, 9.844, "Bauchi"), "bayelsa": (4.926, 6.267, "Yenagoa"),
    "benue": (7.732, 8.539, "Makurdi"), "borno": (11.833, 13.150, "Maiduguri"),
    "cross river": (4.958, 8.326, "Calabar"), "delta": (5.532, 5.898, "Asaba"),
    "ebonyi": (6.264, 8.013, "Abakaliki"), "edo": (6.335, 5.603, "Benin City"),
    "ekiti": (7.623, 5.221, "Ado-Ekiti"), "enugu": (6.458, 7.546, "Enugu"),
    "gombe": (10.290, 11.168, "Gombe"), "imo": (5.489, 7.026, "Owerri"),
    "jigawa": (12.000, 8.516, "Dutse"), "kaduna": (10.523, 7.438, "Kaduna"),
    "kano": (12.002, 8.592, "Kano"), "katsina": (12.990, 7.601, "Katsina"),
    "kebbi": (12.453, 4.197, "Birnin Kebbi"), "kogi": (7.802, 6.734, "Lokoja"),
    "kwara": (8.496, 4.542, "Ilorin"), "lagos": (6.524, 3.379, "Ikeja"),
    "nasarawa": (8.537, 8.522, "Lafia"), "niger": (9.616, 6.547, "Minna"),
    "ogun": (7.147, 3.361, "Abeokuta"), "ondo": (7.252, 5.210, "Akure"),
    "osun": (7.782, 4.541, "Oshogbo"), "oyo": (7.377, 3.947, "Ibadan"),
    "plateau": (9.929, 8.892, "Jos"), "rivers": (4.815, 7.050, "Port Harcourt"),
    "sokoto": (13.062, 5.243, "Sokoto"), "taraba": (8.892, 11.359, "Jalingo"),
    "yobe": (11.748, 11.966, "Damaturu"), "zamfara": (12.170, 6.664, "Gusau"),
    "fct": (9.058, 7.495, "Abuja"), "abuja": (9.058, 7.495, "Abuja"),
    "federal capital territory": (9.058, 7.495, "Abuja"),
}

@app.get("/api/weather/{state}")
async def weather(state: str):
    location=WEATHER_LOCATIONS.get(state.strip().casefold())
    if not location:
        raise HTTPException(404,"Weather is available for Nigerian states and the FCT only")
    latitude,longitude,city=location
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response=await client.get("https://api.open-meteo.com/v1/forecast",params={
                "latitude":latitude,"longitude":longitude,
                "current":"temperature_2m,precipitation,weather_code",
                "daily":"temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                "forecast_days":3,"timezone":"Africa/Lagos",
            })
            response.raise_for_status(); data=response.json()
        return {"available":True,"provider":"Open-Meteo","official":False,
                "location":city,"state":state,"data":data,
                "source":"https://open-meteo.com/","attribution":"Third-party forecast only; official weather and emergency alerts are separate.",
                "retrieved_at":datetime.now(timezone.utc).isoformat()}
    except (httpx.HTTPError,ValueError) as exc:
        return JSONResponse(status_code=502,content={"available":False,"provider":"Open-Meteo",
            "message":"The third-party forecast is temporarily unavailable. Check official weather guidance.",
            "source":"https://open-meteo.com/"})

@app.get("/api/polling-units/{unit_id}/weather")
async def polling_unit_weather(unit_id: str):
    with db() as con:
        unit=con.execute("SELECT id,state,lga,ward,latitude,longitude FROM polling_units WHERE id=?",(unit_id,)).fetchone()
    if not unit:
        raise HTTPException(404,"Polling unit not found in the local register")
    exact=unit["latitude"] is not None and unit["longitude"] is not None
    if exact:
        latitude,longitude=float(unit["latitude"]),float(unit["longitude"])
        location=f"{unit['ward']}, {unit['lga']}"
        location_note="Coordinates from the polling-unit record"
    else:
        fallback=WEATHER_LOCATIONS.get(unit["state"].strip().casefold())
        if not fallback:
            raise HTTPException(404,"Weather is not available for this state")
        latitude,longitude,capital=fallback
        location=f"{capital} (state-capital estimate)"
        location_note="This polling-unit record has no coordinates; showing state-capital conditions."
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response=await client.get("https://api.open-meteo.com/v1/forecast",params={
                "latitude":latitude,"longitude":longitude,
                "current":"temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
                "timezone":"Africa/Lagos",
            })
            response.raise_for_status(); data=response.json()
        return {"available":True,"provider":"Open-Meteo","location":location,
                "location_note":location_note,"current":data.get("current",{}),
                "retrieved_at":datetime.now(timezone.utc).isoformat(),
                "source":"https://open-meteo.com/"}
    except (httpx.HTTPError,ValueError):
        return JSONResponse(status_code=502,content={"available":False,"provider":"Open-Meteo",
            "message":"Current weather is temporarily unavailable. Please try again.",
            "source":"https://open-meteo.com/"})

def require_admin(authorization: str = Header(default="")) -> None:
    token=os.getenv("ADMIN_API_TOKEN")
    if not token or token=="replace-with-a-long-random-secret": raise HTTPException(503,"Set a unique ADMIN_API_TOKEN before using admin routes")
    supplied=authorization[7:] if authorization.startswith("Bearer ") else authorization
    if not hmac.compare_digest(supplied,token):
        raise HTTPException(401,"Valid admin bearer token required")

def _unit_row(p: UnitUpload) -> tuple:
    identity=f"{p.state}|{p.lga}|{p.ward}|{p.code}"
    uid=hashlib.sha256(identity.casefold().encode()).hexdigest()[:24]
    return (uid,p.state,p.lga,p.ward,p.name,p.code,p.latitude,p.longitude,p.accessibility,p.source,p.source_url,p.verified_at)

def _hazard_row(report: HazardUpload) -> tuple:
    identity=f"{report.state}|{report.lga}|{report.ward}|{report.hazard}|{report.observed_at}"
    uid=hashlib.sha256(identity.casefold().encode()).hexdigest()[:24]
    return (uid,report.state,report.lga,report.ward,report.latitude,report.longitude,report.hazard,report.severity,report.details,report.source,report.source_url,report.observed_at,report.expires_at)

@app.post("/api/admin/polling-units", dependencies=[Depends(require_admin)])
def add_unit(payload: UnitUpload):
    row=_unit_row(payload)
    with db() as con:
        con.execute("INSERT OR REPLACE INTO polling_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",row)
    return {"id":row[0],"status":"saved"}

@app.post("/api/admin/hazards", dependencies=[Depends(require_admin)])
def add_hazard(payload: HazardUpload):
    row=_hazard_row(payload)
    with db() as con:
        con.execute("INSERT OR REPLACE INTO hazard_reports VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",row)
    return {"id":row[0],"status":"saved"}

@app.post("/api/admin/import-polling-units", dependencies=[Depends(require_admin)])
async def import_units(request: Request):
    body=await request.body()
    if len(body)>20_000_000: raise HTTPException(413,"CSV exceeds 20 MB")

    def _import() -> int:
        try:
            reader=csv.DictReader(body.decode("utf-8-sig").splitlines())
            needed={"state","lga","ward","name","code","source","source_url","verified_at"}
            if not needed.issubset(set(reader.fieldnames or [])): raise ValueError(f"Required CSV columns: {', '.join(sorted(needed))}")
            items=[]
            for row in reader:
                for key in ("latitude","longitude","accessibility"):
                    if row.get(key)=="": row[key]=None if key!="accessibility" else "unknown"
                items.append(_unit_row(UnitUpload(**row)))
        except (UnicodeDecodeError,ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc
        with db() as con: con.executemany("INSERT OR REPLACE INTO polling_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",items)
        return len(items)

    return {"imported": await run_in_threadpool(_import)}

@app.post("/api/admin/knowledge", dependencies=[Depends(require_admin)])
def add_knowledge(payload: KnowledgeUpload):
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
    incoming=str(form.get("Body", "")).strip()
    if not incoming: return Response(content="<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Message>Please send a civic question. For official information, visit inecnigeria.org.</Message></Response>",media_type="application/xml")
    result=await run_in_threadpool(_grounded_answer, incoming, "en")
    reply=f"{result['answer']} Source: {result['citations'][0]['url']}"
    if len(reply)>1500: reply=reply[:1490]+"…"
    xml=f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Message>{reply.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')}</Message></Response>"
    return Response(content=xml,media_type="application/xml")

@app.post("/api/admin/sync-nihsa", dependencies=[Depends(require_admin)])
async def sync_nihsa():
    feed=os.getenv("NIHSA_FEED_URL")
    if not feed: raise HTTPException(503,"Configure an authorized NIHSA_FEED_URL first")
    if not feed.startswith("https://"): raise HTTPException(500,"NIHSA_FEED_URL must use HTTPS")
    headers={}
    if os.getenv("NIHSA_API_TOKEN"): headers["Authorization"]=f"Bearer {os.getenv('NIHSA_API_TOKEN')}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response=await client.get(feed,headers=headers); response.raise_for_status(); data=response.json()
        if not isinstance(data,list): raise ValueError("Expected a JSON array of normalized hazard reports")
        items=[]
        for raw in data:
            report=HazardUpload(**raw)
            hostname=urlparse(report.source_url).hostname or ""
            if not (hostname=="nihsa.gov.ng" or hostname.endswith(".nihsa.gov.ng")):
                raise ValueError("Each report must cite an official NIHSA source URL")
            items.append(_hazard_row(report))
        def _save() -> None:
            with db() as con: con.executemany("INSERT OR REPLACE INTO hazard_reports VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",items)
        await run_in_threadpool(_save)
        return {"imported":len(items),"source":"NIHSA authorized feed"}
    except (httpx.HTTPError,ValueError,TypeError) as exc: raise HTTPException(502,f"NIHSA feed could not be normalized: {exc}") from exc

@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
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

@app.get("/icon-192.png", include_in_schema=False)
def icon_192(): return FileResponse(ROOT / "icon-192.png", media_type="image/png")

@app.get("/icon-512.png", include_in_schema=False)
def icon_512(): return FileResponse(ROOT / "icon-512.png", media_type="image/png")

