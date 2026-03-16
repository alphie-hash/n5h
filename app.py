import streamlit as st
import requests
import json
import csv
import io
import os
import time
import hashlib
import base64
from datetime import datetime
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from cryptography.fernet import Fernet
from dotenv import load_dotenv
load_dotenv()

# ─────────────────────────────────────────────
# Encryption helpers — encrypt/decrypt data files at rest
# ─────────────────────────────────────────────
def _get_encryption_key():
    """Derive a Fernet key from APP_PASSWORD (or a dedicated ENCRYPTION_KEY env var)."""
    secret = os.getenv("ENCRYPTION_KEY") or os.getenv("APP_PASSWORD", "alphieisdaddy")
    # Derive a 32-byte key using SHA-256, then base64 encode for Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return key

_fernet = Fernet(_get_encryption_key())

def _read_json_encrypted(filepath):
    """Read a JSON file, decrypting if encrypted, falling back to plaintext."""
    if not os.path.exists(filepath):
        return None
    with open(filepath, "rb") as f:
        raw = f.read()
    if not raw:
        return None
    # Try to decrypt first (encrypted files start with 'gAAAAA')
    try:
        decrypted = _fernet.decrypt(raw)
        return json.loads(decrypted.decode("utf-8"))
    except Exception:
        pass
    # Fall back to plaintext JSON (for migration of existing unencrypted files)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None

def _write_json_encrypted(filepath, data):
    """Write a JSON file encrypted at rest."""
    plaintext = json.dumps(data, indent=2).encode("utf-8")
    encrypted = _fernet.encrypt(plaintext)
    with open(filepath, "wb") as f:
        f.write(encrypted)

# ─────────────────────────────────────────────
# Paths & Constants
# ─────────────────────────────────────────────
DATA_DIR      = os.path.expanduser("~/n5h/data")
NOTES_FILE    = os.path.join(DATA_DIR, "notes.json")
SAVES_FILE    = os.path.join(DATA_DIR, "saved_searches.json")
CACHE_FILE    = os.path.join(DATA_DIR, "profile_cache.json")
PIPELINE_FILE = os.path.join(DATA_DIR, "pipeline.json")
PROJECTS_FILE = os.path.join(DATA_DIR, "projects.json")
CONTACTS_FILE = os.path.join(DATA_DIR, "connections.json")
CONNECTION_CSVS = [
    os.path.join(DATA_DIR, "kush_connections.csv"),
    os.path.join(DATA_DIR, "yash_connections.csv"),
    os.path.join(DATA_DIR, "inferra_pipeline.csv"),
]
os.makedirs(DATA_DIR, exist_ok=True)

CACHE_TTL = 86400  # 24 hours

POPULAR_LANGUAGES = [
    "Python", "JavaScript", "TypeScript", "Go", "Rust", "Java",
    "C++", "C", "Ruby", "PHP", "Swift", "Kotlin", "Scala",
    "R", "Julia", "Solidity", "Dart", "Elixir", "Haskell", "Shell",
]

PIPELINE_STAGES = ["New", "Contacted", "Replied", "Interview", "Hired", "Archived"]

STAGE_STYLE = {
    "New":       ("#9ca3af", "rgba(156,163,175,0.08)"),
    "Contacted": ("#60a5fa", "rgba(96,165,250,0.08)"),
    "Replied":   ("#a78bfa", "rgba(167,139,250,0.08)"),
    "Interview": ("#f59e0b", "rgba(245,158,11,0.08)"),
    "Hired":     ("#4ade80", "rgba(74,222,128,0.08)"),
    "Archived":  ("#f87171", "rgba(248,113,113,0.08)"),
}

SENIORITY_MAP = {
    "Any":    "",
    "Junior": "followers:10..300",
    "Mid":    "followers:300..3000",
    "Senior": "followers:>3000",
}

# ─────────────────────────────────────────────
# Notes
# ─────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def _load_notes_cached(mtime):
    return _read_json_encrypted(NOTES_FILE) or {}

def load_notes():
    mtime = os.path.getmtime(NOTES_FILE) if os.path.exists(NOTES_FILE) else 0
    return _load_notes_cached(mtime)

def persist_note(username, text):
    notes = load_notes()
    if text.strip():
        notes[username] = text.strip()
    elif username in notes:
        del notes[username]
    _write_json_encrypted(NOTES_FILE, notes)

# ─────────────────────────────────────────────
# Saved Searches
# ─────────────────────────────────────────────
def load_saved_searches():
    return _read_json_encrypted(SAVES_FILE) or []

def persist_search(label, candidates):
    saves = load_saved_searches()
    saves.insert(0, {
        "id":        str(time.time()),
        "role":      label,
        "timestamp": time.strftime("%d %b %Y %H:%M"),
        "count":     len(candidates),
        "candidates": candidates,
    })
    saves = saves[:10]
    _write_json_encrypted(SAVES_FILE, saves)

# ─────────────────────────────────────────────
# Profile Cache
# ─────────────────────────────────────────────
def _load_cache():
    return _read_json_encrypted(CACHE_FILE) or {}

def _save_cache(cache):
    _write_json_encrypted(CACHE_FILE, cache)

def get_user_profile_cached(username):
    cache = _load_cache()
    entry = cache.get(username)
    if entry and time.time() - entry.get("ts", 0) < CACHE_TTL:
        return entry["data"]
    profile = _fetch_user_profile(username)
    if profile:
        cache[username] = {"ts": time.time(), "data": profile}
        if len(cache) > 2000:
            for k in sorted(cache, key=lambda k: cache[k].get("ts", 0))[:500]:
                del cache[k]
        _save_cache(cache)
    return profile

# ─────────────────────────────────────────────
# Pipeline CRM — Multi-Project
# ─────────────────────────────────────────────
def _migrate_legacy_pipeline():
    """One-time migration: pipeline.json → projects.json."""
    if os.path.exists(PIPELINE_FILE) and not os.path.exists(PROJECTS_FILE):
        old_data = _read_json_encrypted(PIPELINE_FILE) or {}
        data = {
            "_version": 2,
            "_active": "Default",
            "projects": {
                "Default": {"created": time.strftime("%d %b %Y"), "candidates": old_data}
            }
        }
        _write_json_encrypted(PROJECTS_FILE, data)

@st.cache_data(ttl=10, show_spinner=False)
def _load_projects_cached(mtime):
    return _read_json_encrypted(PROJECTS_FILE)

def _save_projects(data):
    _write_json_encrypted(PROJECTS_FILE, data)

def load_projects():
    _migrate_legacy_pipeline()
    mtime = os.path.getmtime(PROJECTS_FILE) if os.path.exists(PROJECTS_FILE) else 0
    data = _load_projects_cached(mtime)
    if not data:
        data = {
            "_version": 2, "_active": "Default",
            "projects": {"Default": {"created": time.strftime("%d %b %Y"), "job_description": "", "candidates": {}}}
        }
        _save_projects(data)
    # Backfill job_description for existing projects that lack it
    changed = False
    for pname, pdata in data.get("projects", {}).items():
        if "job_description" not in pdata:
            pdata["job_description"] = ""
            changed = True
    if changed:
        _save_projects(data)
    return data

def get_active_project_name(data):
    return data.get("_active", "Default")

def get_active_pipeline(data):
    """Returns candidates dict for active project — drop-in for old load_pipeline()."""
    name = get_active_project_name(data)
    project = data.get("projects", {}).get(name)
    if not project:
        return {}
    return project.get("candidates", {})

def load_pipeline():
    """Backward-compat wrapper — returns active project's pipeline."""
    return get_active_pipeline(load_projects())

def update_pipeline(username, stage, project_name=None):
    """Update candidate stage within a specific project (or active project)."""
    data = load_projects()
    target = project_name or get_active_project_name(data)
    project = data["projects"].setdefault(target, {"created": time.strftime("%d %b %Y"), "candidates": {}})
    if stage == "New":
        project["candidates"].pop(username, None)
    else:
        project["candidates"][username] = {"stage": stage, "updated": time.strftime("%d %b %Y")}
    _save_projects(data)

def get_candidate_projects(username):
    """Return list of (project_name, stage) for a candidate across all projects."""
    data = load_projects()
    result = []
    for pname, pdata in data.get("projects", {}).items():
        cand = pdata.get("candidates", {}).get(username)
        if cand:
            result.append((pname, cand.get("stage", "New")))
    return result

def create_project(name, job_description=""):
    data = load_projects()
    if name.strip() and name not in data["projects"]:
        data["projects"][name] = {
            "created": time.strftime("%d %b %Y"),
            "job_description": job_description,
            "candidates": {},
        }
    data["_active"] = name
    _save_projects(data)

def update_project_jd(name, jd):
    """Update the job description for a project."""
    data = load_projects()
    if name in data["projects"]:
        data["projects"][name]["job_description"] = jd
        _save_projects(data)

def set_active_project(name):
    data = load_projects()
    if name in data["projects"]:
        data["_active"] = name
        _save_projects(data)

def delete_project(name):
    data = load_projects()
    if name in data["projects"] and len(data["projects"]) > 1:
        del data["projects"][name]
        if data["_active"] == name:
            data["_active"] = next(iter(data["projects"]))
        _save_projects(data)

# ─────────────────────────────────────────────
# Connections / My Network
# ─────────────────────────────────────────────
def _get(row, *keys, default=""):
    """Try multiple column names, return first non-empty value."""
    for k in keys:
        v = row.get(k, "").strip() if k in row else ""
        if v:
            return v
    return default

def parse_connections_csv_file(filepath):
    """Parse a CSV file from disk into connection dicts."""
    try:
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            return _parse_csv_rows(csv.DictReader(f))
    except Exception:
        return []

def parse_connections_csv_bytes(file_bytes):
    """Parse uploaded CSV bytes into connection dicts."""
    text = file_bytes.decode("utf-8", errors="ignore")
    return _parse_csv_rows(csv.DictReader(io.StringIO(text)))

def _parse_csv_rows(reader):
    connections = []
    for row in reader:
        # Build name from NAME or First+Last or PROFILE
        name = _get(row, "NAME", "Name", "PROFILE", "name", "Full Name")
        if not name:
            first = _get(row, "First Name", "first name", "First", "FIRST NAME")
            last  = _get(row, "Last Name", "last name", "Last", "LAST NAME")
            name = f"{first} {last}".strip()
        if not name:
            continue

        # Location: combine CITY + STATE, or use CITY alone
        city  = _get(row, "CITY", "City", "city", "location", "Location")
        state = _get(row, "STATE", "State", "state", "MEGA")
        location = f"{city}, {state}" if city and state else city or state

        connections.append({
            "name":         name,
            "email":        _get(row, "EMAIL", "Email", "email", "GMAIL", "PERSONAL"),
            "phone":        _get(row, "PHONE", "Phone", "phone", "mobile"),
            "location":     location,
            "title":        _get(row, "TITLE", "Title", "title", "position", "Position"),
            "company":      _get(row, "COMPANY", "Company", "company"),
            "linkedin_url": _get(row, "URL", "Url", "url", "LinkedIn URL", "LINKEDIN"),
            "owner":        _get(row, "OWNER", "Owner"),
            "relationship": _get(row, "RELATIONSHIP", "Relationship"),
            "tier":         _get(row, "PROFILE", "Tier", "tier"),  # WORLD-CLASS, STRONG, MAYBE
            "pipeline":     _get(row, "PIPELINE 1", "STAGE", "Pipeline", "pipeline"),
            "category":     _get(row, "CATEGORY", "Category"),
            "connected":    _get(row, "CONNECTED", "Connected On"),
        })
    return connections

@st.cache_data(ttl=300, show_spinner=False)
def _load_connections_cached(cache_mtime):
    """Load connections from disk. cache_mtime param busts the cache when file changes."""
    data = _read_json_encrypted(CONTACTS_FILE)
    if data:
        return data
    # Auto-import from bundled CSVs on first run
    all_conns = []
    for csv_path in CONNECTION_CSVS:
        if os.path.exists(csv_path):
            all_conns.extend(parse_connections_csv_file(csv_path))
    if all_conns:
        all_conns = _dedupe_connections(all_conns)
        save_connections(all_conns)
    return all_conns

def load_connections():
    mtime = os.path.getmtime(CONTACTS_FILE) if os.path.exists(CONTACTS_FILE) else 0
    return _load_connections_cached(mtime)

def _dedupe_connections(connections):
    seen = set()
    unique = []
    for c in connections:
        key = c.get("name", "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(c)
    return unique

def save_connections(connections):
    _write_json_encrypted(CONTACTS_FILE, connections)

# Location aliases — common abbreviations map to full names for fuzzy matching
LOCATION_ALIASES = {
    "sf": ["san francisco", "sf", "bay area"],
    "san francisco": ["san francisco", "sf", "bay area"],
    "bay area": ["san francisco", "sf", "bay area", "oakland", "san jose", "palo alto", "mountain view", "sunnyvale", "berkeley", "fremont"],
    "nyc": ["new york", "nyc", "brooklyn", "manhattan"],
    "new york": ["new york", "nyc", "brooklyn", "manhattan"],
    "la": ["los angeles", "la", "santa monica", "pasadena", "hollywood"],
    "los angeles": ["los angeles", "la", "santa monica", "pasadena", "hollywood"],
    "dc": ["washington", "dc", "d.c."],
    "washington": ["washington", "dc", "d.c."],
    "london": ["london", "uk", "united kingdom"],
    "seattle": ["seattle", "wa", "washington"],
    "austin": ["austin", "tx", "texas"],
    "chicago": ["chicago", "il"],
    "boston": ["boston", "ma", "cambridge"],
    "denver": ["denver", "co", "colorado", "boulder"],
    "toronto": ["toronto", "on", "ontario"],
    "berlin": ["berlin", "germany"],
    "bangalore": ["bangalore", "bengaluru", "india"],
}

def _location_matches(profile_location, query_loc):
    """Fuzzy location match — checks aliases and substring."""
    if not profile_location or not query_loc:
        return False
    prof_lower = profile_location.lower()
    q_lower = query_loc.lower().strip()
    # Direct substring match
    if q_lower in prof_lower:
        return True
    # Normalized match: strip spaces/punctuation
    prof_norm = prof_lower.replace(" ", "").replace(",", "").replace("-", "").replace(".", "")
    q_norm = q_lower.replace(" ", "").replace(",", "").replace("-", "").replace(".", "")
    if q_norm in prof_norm:
        return True
    # Check aliases — try exact key, then normalized key
    aliases = LOCATION_ALIASES.get(q_lower, [])
    if not aliases:
        for key, vals in LOCATION_ALIASES.items():
            if key.replace(" ", "") == q_norm:
                aliases = vals
                break
    if aliases:
        return any(alias in prof_lower for alias in aliases)
    return False

def search_connections(connections, query="", location="", company="", title=""):
    results = connections
    if query.strip():
        q_lower = query.lower().strip()
        # Remove noise words for keyword matching
        _noise = {"a", "an", "the", "of", "for", "in", "at", "to", "and", "or", "with", "on"}
        # Phase 1: exact phrase match (highest quality)
        phrase_matches = []
        # Phase 2: multi-word phrase chunks (2-3 word combos)
        chunk_matches = []
        # Phase 3: keyword match (any meaningful keyword)
        keyword_matches = []

        # Build meaningful keywords (drop noise words)
        all_words = [w for w in q_lower.split() if w.strip()]
        meaningful = [w for w in all_words if w not in _noise and len(w) > 1]

        # Build 2-word and 3-word phrase chunks from the query
        chunks_2 = [f"{all_words[i]} {all_words[i+1]}" for i in range(len(all_words)-1)]
        chunks_3 = [f"{all_words[i]} {all_words[i+1]} {all_words[i+2]}" for i in range(len(all_words)-2)]
        phrase_chunks = chunks_3 + chunks_2  # prioritise longer chunks

        seen = set()
        for c in results:
            haystack = " ".join([
                c.get("name", ""), c.get("email", ""),
                c.get("title", ""), c.get("company", ""),
                c.get("bio", ""), c.get("skills", ""),
                c.get("category", ""),
            ]).lower()
            cid = id(c)
            # Exact phrase
            if q_lower in haystack:
                phrase_matches.append(c)
                seen.add(cid)
                continue
            # Multi-word chunk match
            chunk_hit = any(ch in haystack for ch in phrase_chunks)
            if chunk_hit and cid not in seen:
                chunk_matches.append(c)
                seen.add(cid)
                continue
            # Keyword match — require ALL meaningful keywords (not any)
            if meaningful and all(kw in haystack for kw in meaningful) and cid not in seen:
                keyword_matches.append(c)
                seen.add(cid)

        results = phrase_matches + chunk_matches + keyword_matches

    if location.strip():
        results = [c for c in results if _location_matches(c.get("location", ""), location)]
    if company.strip():
        comp = company.lower().strip()
        results = [c for c in results if comp in c.get("company", "").lower()]
    if title.strip():
        t = title.lower().strip()
        results = [c for c in results if t in c.get("title", "").lower()]
    return results

def find_connection_match(connections, name="", email=""):
    if not connections:
        return None
    name_lower = (name or "").lower().strip()
    email_lower = (email or "").lower().strip()
    for c in connections:
        if email_lower and email_lower == c.get("email", "").lower().strip():
            return c
        if name_lower and name_lower == c.get("name", "").lower().strip():
            return c
    return None

def connection_badge():
    return (
        ' <span style="background:#2563eb22;color:#60a5fa;font-size:0.7rem;'
        'font-weight:700;padding:3px 8px;border-radius:20px;border:1px solid #2563eb66;'
        'vertical-align:middle;">🔗 IN YOUR NETWORK</span>'
    )

def pipeline_badge(stage):
    colour, bg = STAGE_STYLE.get(stage, ("#9ca3af", "rgba(156,163,175,0.08)"))
    return (
        f'<span style="background:{bg};color:{colour};font-size:0.65rem;font-weight:700;'
        f'padding:3px 9px;border-radius:20px;border:1px solid {colour}55;letter-spacing:0.06em;">'
        f'{stage.upper()}</span>'
    )

# ─────────────────────────────────────────────
# Secrets
# ─────────────────────────────────────────────
def _secret(key):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key)

GITHUB_TOKEN   = _secret("GITHUB_TOKEN")
OPENAI_API_KEY = _secret("OPENAI_API_KEY")
PROXYCURL_API_KEY = _secret("PROXYCURL_API_KEY")

_PLACEHOLDER    = {"your_github_token_here", "your_openai_api_key_here", "", None}
GITHUB_TOKEN_OK = GITHUB_TOKEN not in _PLACEHOLDER
OPENAI_KEY_OK   = OPENAI_API_KEY not in _PLACEHOLDER
PROXYCURL_OK    = PROXYCURL_API_KEY not in _PLACEHOLDER

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept":        "application/vnd.github.v3+json",
}

# ─────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────
PREMIUM_CSS = """
<style>
  [data-testid="stAppViewContainer"] {
    background-color: #0c0c0c;
    background-image:
      repeating-linear-gradient(112deg,transparent 0px,transparent 38px,rgba(255,255,255,0.018) 38px,rgba(255,255,255,0.018) 39px,transparent 39px,transparent 78px,rgba(255,255,255,0.012) 78px,rgba(255,255,255,0.012) 79px),
      repeating-linear-gradient(-22deg,transparent 0px,transparent 55px,rgba(255,255,255,0.014) 55px,rgba(255,255,255,0.014) 56px,transparent 56px,transparent 110px,rgba(255,255,255,0.009) 110px,rgba(255,255,255,0.009) 111px),
      repeating-linear-gradient(67deg,transparent 0px,transparent 70px,rgba(255,255,255,0.01) 70px,rgba(255,255,255,0.01) 71px),
      radial-gradient(ellipse at 20% 25%,rgba(255,255,255,0.04) 0%,transparent 50%),
      radial-gradient(ellipse at 80% 70%,rgba(255,255,255,0.03) 0%,transparent 45%),
      radial-gradient(ellipse at 55% 50%,rgba(255,255,255,0.015) 0%,transparent 60%),
      radial-gradient(ellipse at 10% 80%,rgba(255,255,255,0.025) 0%,transparent 35%),
      radial-gradient(ellipse at 90% 10%,rgba(255,255,255,0.02) 0%,transparent 40%);
  }
  [data-testid="stHeader"] { background: transparent; }
  [data-testid="stSidebar"] {
    background: rgba(10,10,10,0.85) !important;
    backdrop-filter: blur(12px);
    border-right: 1px solid rgba(255,255,255,0.07) !important;
  }
  h1 {
    font-size: 2.8rem !important; font-weight: 800 !important; letter-spacing: -1px;
    background: linear-gradient(135deg, #ffffff 0%, #c0c0c0 60%, #888888 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  }
  [data-testid="stCaptionContainer"] p { color: #888 !important; font-size: 1rem !important; letter-spacing: 0.04em; font-style: italic; }
  hr { border-color: rgba(255,255,255,0.07) !important; margin: 1rem 0 !important; }
  [data-testid="stTextInput"] input {
    background: rgba(255,255,255,0.04) !important; border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 10px !important; color: #e8e8e8 !important; font-size: 0.95rem !important;
    padding: 12px 16px !important; backdrop-filter: blur(8px);
  }
  [data-testid="stTextInput"] input:focus { border-color: rgba(255,255,255,0.35) !important; box-shadow: 0 0 0 3px rgba(255,255,255,0.06) !important; }
  [data-testid="stSelectbox"] > div > div { background: rgba(255,255,255,0.04) !important; border: 1px solid rgba(255,255,255,0.1) !important; border-radius: 10px !important; color: #e8e8e8 !important; }
  [data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #2a2a2a, #111111) !important;
    border: 1px solid rgba(255,255,255,0.2) !important; border-radius: 10px !important;
    color: #ffffff !important; font-weight: 700 !important; font-size: 1rem !important;
    letter-spacing: 0.05em !important; padding: 14px !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.1), 0 4px 12px rgba(0,0,0,0.4) !important;
    transition: all 0.2s !important;
  }
  [data-testid="stButton"] > button[kind="primary"]:hover { background: linear-gradient(135deg, #3a3a3a, #1a1a1a) !important; border-color: rgba(255,255,255,0.35) !important; transform: translateY(-1px) !important; }
  [data-testid="stButton"] > button:not([kind="primary"]) { background: rgba(255,255,255,0.05) !important; border: 1px solid rgba(255,255,255,0.12) !important; border-radius: 8px !important; color: #d0d0d0 !important; font-weight: 600 !important; transition: all 0.2s !important; }
  [data-testid="stButton"] > button:not([kind="primary"]):hover { background: rgba(255,255,255,0.1) !important; border-color: rgba(255,255,255,0.3) !important; }
  [data-testid="stContainer"] > div { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 16px; padding: 20px !important; margin-bottom: 4px; backdrop-filter: blur(10px); transition: border-color 0.2s, background 0.2s; }
  [data-testid="stContainer"] > div:hover { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.15); }
  [data-testid="stMarkdownContainer"] h3 a { color: #f0f0f0 !important; text-decoration: none !important; font-weight: 700; }
  [data-testid="stMarkdownContainer"] h3 a:hover { color: #ffffff !important; text-decoration: underline !important; }
  [data-testid="stMetricLabel"] p { color: #666 !important; font-size: 0.7rem !important; text-transform: uppercase; letter-spacing: 0.08em; }
  [data-testid="stMetricValue"] { color: #e0e0e0 !important; font-size: 1.3rem !important; font-weight: 700 !important; }
  code { background: rgba(255,255,255,0.07) !important; color: #c8c8c8 !important; border-radius: 5px !important; padding: 2px 7px !important; font-size: 0.8rem !important; border: 1px solid rgba(255,255,255,0.1) !important; }
  textarea { background: rgba(255,255,255,0.04) !important; border: 1px solid rgba(255,255,255,0.1) !important; border-radius: 8px !important; color: #e0e0e0 !important; font-size: 0.85rem !important; }
  [data-testid="stAlert"] { border-radius: 10px !important; border: none !important; }
  [data-testid="stProgressBar"] > div { background: linear-gradient(90deg, #555, #aaa) !important; border-radius: 99px; }
  [data-testid="stProgressBar"] { background: rgba(255,255,255,0.08) !important; border-radius: 99px; }
  [data-testid="stExpander"] { background: rgba(255,255,255,0.03) !important; border: 1px solid rgba(255,255,255,0.07) !important; border-radius: 10px !important; }
  [data-testid="stImage"] img { border-radius: 50% !important; border: 2px solid rgba(255,255,255,0.15) !important; }
  [data-testid="stDownloadButton"] > button { background: rgba(255,255,255,0.05) !important; border: 1px solid rgba(255,255,255,0.12) !important; border-radius: 8px !important; color: #d0d0d0 !important; font-weight: 600 !important; width: 100%; }
  [data-testid="stDownloadButton"] > button:hover { background: rgba(255,255,255,0.09) !important; border-color: rgba(255,255,255,0.3) !important; }
  /* Mobile responsive — stack columns vertically */
  @media (max-width: 768px) {
    [data-testid="stHorizontalBlock"] { flex-direction: column !important; }
    [data-testid="stHorizontalBlock"] > div { width: 100% !important; flex: none !important; }
  }
  /* Clean sidebar project buttons */
  [data-testid="stSidebar"] [data-testid="stButton"] > button {
    text-align: left !important; padding-left: 16px !important;
  }
</style>
"""

# ─────────────────────────────────────────────
# GitHub API
# ─────────────────────────────────────────────
def search_users_direct(query, max_results=30):
    """Fetch up to max_results users, paginating through GitHub Search API."""
    url = "https://api.github.com/search/users"
    all_items = []
    per_page = min(max_results, 100)  # GitHub allows up to 100 per page
    pages_needed = (max_results + per_page - 1) // per_page  # ceil division
    for page in range(1, pages_needed + 1):
        params = {"q": query, "sort": "followers", "order": "desc",
                  "per_page": per_page, "page": page}
        r = requests.get(url, headers=HEADERS, params=params)
        if r.status_code != 200:
            try:
                msg = r.json().get("message", r.text)
            except Exception:
                msg = r.text
            if all_items:          # partial success — return what we have
                break
            return [], f"GitHub API error {r.status_code}: {msg}"
        items = r.json().get("items", [])
        all_items.extend(items)
        if len(items) < per_page:  # no more pages
            break
        if len(all_items) >= max_results:
            break
        time.sleep(0.05)           # minimal rate-limit courtesy
    return all_items[:max_results], None

def search_repos(query, max_repos=5):
    url = "https://api.github.com/search/repositories"
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": max_repos}
    r = requests.get(url, headers=HEADERS, params=params)
    if r.status_code == 200:
        return r.json().get("items", []), None
    try:
        msg = r.json().get("message", r.text)
    except Exception:
        msg = r.text
    return [], f"GitHub API error {r.status_code}: {msg}"

def get_contributors(owner, repo, max_contributors=15):
    url = f"https://api.github.com/repos/{owner}/{repo}/contributors"
    r = requests.get(url, headers=HEADERS, params={"per_page": max_contributors})
    if r.status_code == 200:
        return r.json()
    return []

def _fetch_user_profile(username):
    r = requests.get(f"https://api.github.com/users/{username}", headers=HEADERS)
    if r.status_code == 200:
        return r.json()
    return None

def get_user_repos(username, max_repos=6):
    r = requests.get(
        f"https://api.github.com/users/{username}/repos",
        headers=HEADERS,
        params={"sort": "stars", "per_page": max_repos},
    )
    if r.status_code == 200:
        return r.json()
    return []

def get_user_languages(username, repos=None):
    if repos is None:
        repos = get_user_repos(username, max_repos=10)
    lang_count = {}
    for repo in repos:
        lang = repo.get("language")
        if lang:
            lang_count[lang] = lang_count.get(lang, 0) + 1
    return [l[0] for l in sorted(lang_count.items(), key=lambda x: x[1], reverse=True)[:5]]

def account_age_days(profile):
    created = profile.get("created_at", "")
    if not created:
        return 0
    try:
        dt = datetime.strptime(created[:10], "%Y-%m-%d")
        return (datetime.utcnow() - dt).days
    except Exception:
        return 0

def fmt_age(profile):
    days = account_age_days(profile)
    if days >= 365:
        return f"{days // 365}y"
    return f"{days // 30}mo" if days >= 30 else f"{days}d"

# ─────────────────────────────────────────────
# JD → Search Keywords Extractor
# ─────────────────────────────────────────────
def extract_search_keywords(job_description):
    """Use AI to extract GitHub-searchable keywords from a job description."""
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = f"""Extract the most important GitHub-searchable keywords from this job description.
Return ONLY a short search query (3-6 words max) that would find matching developers on GitHub.
Focus on: job title, key technical skills, programming languages.
Do NOT include soft skills, company info, or benefits.

Job Description:
{job_description.strip()}

Reply with ONLY the search query, nothing else. Example: "machine learning python pytorch"
"""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0.1,
        )
        return resp.choices[0].message.content.strip().strip('"').strip("'")
    except Exception:
        return ""


def classify_role_and_expand(role_text, job_description=""):
    """Classify if a role is technical (GitHub-searchable) or business/commercial (network-only).
    Also generate expanded search synonyms for network searching."""
    if not OPENAI_KEY_OK:
        return {"type": "technical", "synonyms": [], "network_queries": [role_text]}
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    context = role_text
    if job_description:
        context += "\n\nJD context: " + job_description[:1000]
    prompt = f"""Analyse this role and classify it.

ROLE: {context}

Reply with ONLY a JSON object:
{{
  "type": "technical" or "business",
  "confidence": 0.0-1.0,
  "reason": "one sentence why",
  "network_queries": ["list of 5-10 alternative job title searches to find this person in a LinkedIn/professional network CSV"],
  "synonyms": ["list of related job titles, e.g. Head of Acquisitions -> VP Land, Site Acquisition Manager, Real Estate Director, etc."]
}}

RULES:
- "technical" = roles where the person would likely have a GitHub profile (software engineers, ML engineers, DevOps, data scientists, etc.)
- "business" = roles where GitHub is unlikely (sales, acquisitions, operations, HR, finance, legal, BD, marketing, C-suite, etc.)
- network_queries should be diverse: include abbreviations (VP, SVP, Dir), industry terms, and related titles
- For "Head of Acquisitions for Data Centres": synonyms might include "Site Acquisition", "Land Acquisition", "Real Estate", "Data Center Development", "Infrastructure Development", "VP Real Estate"
"""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.2,
        )
        raw = resp.choices[0].message.content.strip()
        data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        return data
    except Exception:
        return {"type": "technical", "synonyms": [], "network_queries": [role_text]}


# ─────────────────────────────────────────────
# Multi-Query Search Strategy
# ─────────────────────────────────────────────
def extract_roles_from_jd(job_description):
    """Use AI to identify all distinct roles mentioned in a job description."""
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""Analyze this job description / company brief and identify ALL distinct roles being hired for.
For each role, extract: the title, key technical skills, and what to search for on GitHub.

Job Description:
{job_description[:4000]}

Reply with ONLY a JSON array of role objects:
[{{"title": "ML Infrastructure Engineer", "skills": ["vLLM", "TensorRT", "CUDA", "PyTorch"], "search_terms": "ML infrastructure GPU CUDA"}}, ...]

If there is only ONE role, return an array with one object.
If the document describes a company with multiple roles, extract ALL of them (up to 10).
"""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content.strip()
        roles = json.loads(raw[raw.find("["):raw.rfind("]")+1])
        return roles[:10]
    except Exception:
        return []

def generate_search_queries(role, location="", company="", seniority="", job_description="", roles_list=None):
    """Use AI to generate diverse GitHub search queries — handles multi-role JDs."""
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    context = ""
    if role: context += f"Role keywords: {role}\n"
    if location: context += f"Location: {location}\n"
    if company: context += f"Company: {company}\n"
    if seniority and seniority != "Any": context += f"Seniority: {seniority}\n"

    # If we have explicit roles list, format them clearly
    if roles_list and len(roles_list) > 0:
        context += "\n=== ROLES TO SEARCH FOR (generate queries for EVERY role) ===\n"
        for i, r in enumerate(roles_list, 1):
            title = r.get("title", "Unknown")
            skills = r.get("skills", [])
            terms = r.get("search_terms", "")
            context += f"Role {i}: {title} | Skills: {', '.join(skills) if skills else 'N/A'} | Search: {terms}\n"
        context += "=== END ROLES ===\n"
    elif job_description:
        context += f"Job Description (first 3000 chars):\n{job_description[:3000]}\n"

    num_roles = len(roles_list) if roles_list else 1
    min_queries = max(5, num_roles * 3)
    max_queries = max(15, num_roles * 4)

    prompt = f"""Generate GitHub user search queries to find candidates based on this context.
Use GitHub search syntax: type:user, location:"City", followers:>N.

{context}

CRITICAL RULES (GitHub user search only matches bio/name/login text — NOT repo content):
- Each query MUST include type:user
- Each query MUST have only 1-2 keyword terms (besides type:user and location). GitHub search is very literal — fewer keywords = more results.
- GOOD: type:user CUDA GPU — FINDS users with "CUDA" or "GPU" in their bio
- BAD: type:user vLLM CUDA PyTorch ML infrastructure — TOO MANY terms, zero results
- NEVER use more than 2 keywords per query. This is the most important rule.
- For HALF of the queries, include a location filter. For the other half, do NOT include location — cast a wider net.
- Location variations: "San Francisco", "SF", "Bay Area", "California"
- Do NOT add followers:>N unless seniority is explicitly specified
- Use single high-signal keywords per query: "CUDA", "Kubernetes", "security", "DevOps", "ML", "FastAPI", "Terraform", "electrical"
- You MUST generate at least 3 queries for EACH role listed above. Do NOT skip any role.

EXAMPLES of good queries:
- type:user CUDA GPU
- type:user location:"San Francisco" Kubernetes
- type:user ML infrastructure
- type:user location:"Bay Area" security
- type:user DevOps Terraform
- type:user location:"SF" Python FastAPI

Generate between {min_queries} and {max_queries} queries. You MUST cover ALL {num_roles} roles.

Reply with ONLY a JSON array of query strings:
["query1", "query2", ...]"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.7,
        )
        raw = resp.choices[0].message.content.strip()
        queries = json.loads(raw[raw.find("["):raw.rfind("]")+1])
        # Validate: reject any query longer than 200 chars (safety net)
        valid = [q for q in queries if len(q) < 200 and "type:user" in q]
        return valid[:max_queries]
    except Exception:
        return []

# ─────────────────────────────────────────────
# Proxycurl LinkedIn Integration
# ─────────────────────────────────────────────
def search_linkedin_profiles(role, location="", company="", max_results=50):
    """Search LinkedIn via Proxycurl Person Search API."""
    if not PROXYCURL_OK:
        return [], "Proxycurl API key not configured"

    url = "https://nubela.co/proxycurl/api/search/person/"
    headers = {"Authorization": f"Bearer {PROXYCURL_API_KEY}"}
    params = {
        "country": "US",  # default
        "page_size": min(max_results, 100),
    }
    if role:
        params["current_role_title"] = role
    if company:
        params["current_company_name"] = company
    if location:
        params["city"] = location

    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 200:
            data = r.json()
            profiles = data.get("results", [])
            return profiles, None
        return [], f"Proxycurl API error {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return [], str(e)

def enrich_with_linkedin(github_username, name=""):
    """Try to find a LinkedIn profile for a GitHub user."""
    if not PROXYCURL_OK:
        return None
    url = "https://nubela.co/proxycurl/api/linkedin/profile/resolve"
    headers = {"Authorization": f"Bearer {PROXYCURL_API_KEY}"}
    params = {}
    if name:
        params["first_name"] = name.split()[0] if " " in name else name
        if " " in name:
            params["last_name"] = name.split()[-1]

    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            return r.json().get("url")
    except Exception:
        pass
    return None

# ─────────────────────────────────────────────
# PDF Text Extraction
# ─────────────────────────────────────────────
def extract_text_from_pdf(file_bytes):
    """Extract text from a PDF file using PyPDF2."""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except Exception as e:
        return f"[PDF extraction error: {e}]"

# ─────────────────────────────────────────────
# Batch AI Scorer
# ─────────────────────────────────────────────
def score_candidates_batch(candidates, role, job_description=""):
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    lines = []
    for i, c in enumerate(candidates):
        p     = c["profile"]
        name  = p.get("name") or p.get("login")
        bio   = p.get("bio") or "N/A"
        langs = ", ".join(c.get("languages", [])) or "N/A"
        repos = "; ".join(
            f"{r['name']}: {r.get('description') or ''}"
            for r in c.get("user_repos", [])[:3]
        ) or "N/A"
        lines.append(
            f"[{i}] {p['login']} | {name} | bio:{bio} | langs:{langs} | "
            f"repos:{repos} | pubRepos:{p.get('public_repos', 0)} | followers:{p.get('followers', 0)}"
        )

    # Build scoring prompt — use full JD if provided
    if job_description and job_description.strip():
        jd_block = (
            f"ROLES BEING HIRED: {role}\n\n"
            f"FULL JOB DESCRIPTION / 1-PAGER:\n{job_description.strip()}\n\n"
            "Score each developer 0.0-10.0 based on how well they match ANY of the roles in the job description above.\n"
            "A candidate only needs to be a strong fit for ONE of the listed roles to score highly.\n"
            "Criteria: required skills match, experience level, repo relevance, language fit, "
            "domain expertise alignment with the JD.\n"
            "Weight heavily: specific technical skills mentioned in the JD, relevant project experience, seniority signals.\n"
            "In the conclusion, specify WHICH role(s) they best fit.\n\n"
        )
    else:
        jd_block = (
            f"Score each developer 0.0-10.0 for fit as: {role}\n"
            "Criteria: language match, repo relevance, seniority signals, bio alignment.\n\n"
        )

    prompt = (
        jd_block
        + "\n".join(lines)
        + '\n\nReply ONLY with a JSON array in the same order:\n[{"i":0,"score":7.5,"reason":"one sentence max 12 words","conclusion":"2-3 sentence analysis of how this person\'s specific skills and experience connect to the role requirements."},...]'
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max(200, len(candidates) * 80),
            temperature=0.2,
        )
        raw  = resp.choices[0].message.content.strip()
        data = json.loads(raw[raw.find("[") : raw.rfind("]") + 1])
        return {item["i"]: (round(float(item["score"]), 1), item.get("reason", ""), item.get("conclusion", "")) for item in data}, None
    except Exception as e:
        err = str(e)
        if "insufficient_quota" in err or "429" in err:
            return {}, "quota"
        return {}, err

# ─────────────────────────────────────────────
# Outreach Generator
# ─────────────────────────────────────────────
def generate_outreach(profile, role, repos, job_description=""):
    from openai import OpenAI
    client    = OpenAI(api_key=OPENAI_API_KEY)
    name      = profile.get("name") or profile.get("login")
    first     = name.split()[0] if name and " " in name else name
    bio       = profile.get("bio") or "N/A"
    company   = profile.get("company") or "N/A"
    location  = profile.get("location") or "N/A"
    repo_details = []
    for r in repos[:5]:
        desc = r.get("description") or ""
        lang = r.get("language") or ""
        stars = r.get("stargazers_count", 0)
        repo_details.append(f"{r['name']} ({lang}, {stars}★): {desc}")
    repo_str = "\n".join(repo_details) if repo_details else "N/A"
    prompt = f"""You are Alphie, an intern at Number Five House (N5H), drafting a cold outreach email to a developer found on GitHub. You work for Lucas Partington who leads recruiting at N5H. N5H builds teams for world-class tech ventures.

CANDIDATE PROFILE:
- Name: {name}
- Bio: {bio}
- Company: {company}
- Location: {location}
- Followers: {profile.get("followers", 0)}
- Public repos: {profile.get("public_repos", 0)}
- Top repositories:
{repo_str}

ROLE WE ARE SOURCING FOR: {role}
"""
    if job_description and job_description.strip():
        prompt += f"\nFULL JOB DESCRIPTION:\n{job_description.strip()}\n"
    prompt += """
OUTREACH FORMULA (follow this structure exactly):

1. SUBJECT LINE: Short, specific to their work — not generic.

2. INTRO: "Hi {first}," then:
   "My name is Alphie. I'm an intern working for Lucas Partington at Number Five House (N5H). We build teams for world-class tech ventures."

3. GOLDEN NUGGETS: Prove you deeply read their profile. Reference 1-2 HIGHLY SPECIFIC things from their repos, bio, or work. Name actual repo names, technologies, or patterns you noticed in their code. Be specific like "I've been looking at your work on [repo] — specifically how you [technical detail]". NEVER be generic like "You have a great background in X."

4. THE HOOK: Pitch the opportunity and why it's compelling. Connect it to what makes this venture exciting. Frame the mission, not just the job title.

5. WHY YOU: Connect their golden nuggets directly to the problem. Frame them as an essential system owner, not just an employee.

6. CTA: End with exactly:
   "Lucas Partington would love 15 mins to discuss. The easiest next step is to book time w/ Lucas. Or WhatsApp: +14155199582.

   Thanks,
   Alphie"

STRICT VOCABULARY RULES:
- NEVER use: "founding crew", "zero-to-one leader", "exciting opportunity", "passionate about", "rockstar", "ninja"
- USE INSTEAD: "core crew", "ground-up engineering leader"
- Tone: approachable, professional, intern-like warmth, genuine curiosity
- Total message: under 200 words
- Do NOT use any placeholders like [Company Name] — if venture details are unknown, describe the opportunity based on the role"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
    )
    return resp.choices[0].message.content

# ─────────────────────────────────────────────
# Score Badge
# ─────────────────────────────────────────────
def score_badge(score):
    if score is None:
        return (
            '<div style="display:inline-block;background:#1e1e2e;color:#4b5563;'
            'font-size:0.75rem;font-weight:600;padding:8px 14px;border-radius:12px;'
            'border:1px solid #2a2a3e;text-align:center;min-width:72px;">N/A</div>'
        )
    colour, glow = (
        ("#22c55e", "rgba(34,197,94,0.2)")   if score >= 7.0 else
        ("#f59e0b", "rgba(245,158,11,0.2)")  if score >= 4.0 else
        ("#ef4444", "rgba(239,68,68,0.2)")
    )
    return (
        f'<div style="display:inline-block;background:{colour}18;color:{colour};'
        f'font-size:1.5rem;font-weight:800;padding:8px 16px;border-radius:12px;'
        f'border:1px solid {colour}40;box-shadow:0 0 16px {glow};line-height:1;'
        f'text-align:center;min-width:72px;">{score}'
        f'<br><span style="font-size:0.6rem;font-weight:500;opacity:0.7;letter-spacing:0.05em;">/ 10</span></div>'
    )

# ─────────────────────────────────────────────
# CSV Export
# ─────────────────────────────────────────────
def build_csv(candidates, role):
    pipeline = load_pipeline()
    output   = io.StringIO()
    writer   = csv.writer(output)
    writer.writerow([
        "Rank", "Name", "GitHub", "Pipeline Stage", "Score", "Score Reason",
        "Bio", "Location", "Company", "Languages", "Public Repos", "Followers",
        "Contributions", "Account Created", "Top Repos", "Role Searched",
    ])
    for rank, c in enumerate(candidates, 1):
        p     = c["profile"]
        stage = pipeline.get(p["login"], {}).get("stage", "New")
        writer.writerow([
            rank,
            p.get("name") or p.get("login"),
            f"https://github.com/{p['login']}",
            stage,
            c["score"] if c["score"] is not None else "N/A",
            c.get("reason", ""),
            (p.get("bio") or "").replace("\n", " "),
            p.get("location") or "",
            (p.get("company") or "").strip("@"),
            ", ".join(c.get("languages", [])),
            p.get("public_repos", 0),
            p.get("followers", 0),
            c.get("contributor", {}).get("contributions", 0),
            (p.get("created_at") or "")[:10],
            ", ".join([r["name"] for r in c.get("user_repos", [])[:3]]),
            role,
        ])
    return output.getvalue().encode("utf-8")

# ─────────────────────────────────────────────
# Candidate Renderer
# ─────────────────────────────────────────────
def render_candidate(c, idx, role_query, pipeline, connections=None, project_name=None, project_jd=""):
    profile     = c["profile"]
    username    = profile["login"]
    user_repos  = c.get("user_repos", [])
    languages   = c.get("languages", [])
    score       = c.get("score")
    reason      = c.get("reason", "")
    conclusion  = c.get("conclusion", "")
    contributor = c.get("contributor", {})
    stage       = pipeline.get(username, {}).get("stage", "New")
    _pname      = project_name or get_active_project_name(load_projects())

    with st.container():
        col_avatar, col_info, col_action = st.columns([1, 4, 2])

        with col_avatar:
            if profile.get("avatar_url"):
                st.image(profile["avatar_url"], width=72)
            st.markdown(score_badge(score), unsafe_allow_html=True)
            if reason:
                st.caption(reason)
            if conclusion:
                st.markdown(
                    f'<div style="font-size:0.75rem;color:#9ca3af;line-height:1.4;'
                    f'margin:6px 0;padding:6px 8px;background:rgba(255,255,255,0.03);'
                    f'border-radius:8px;border-left:2px solid rgba(255,255,255,0.15);">'
                    f'{conclusion}</div>',
                    unsafe_allow_html=True)
            st.markdown(pipeline_badge(stage), unsafe_allow_html=True)

        with col_info:
            name      = profile.get("name") or username
            # Source badge
            _source = c.get("source", "github")
            if _source == "network":
                source_badge = (
                    ' <span style="background:rgba(168,85,247,0.12);color:#a855f7;font-size:0.6rem;'
                    'font-weight:700;padding:2px 7px;border-radius:12px;border:1px solid rgba(168,85,247,0.3);'
                    'vertical-align:middle;letter-spacing:0.03em;">NETWORK</span>'
                )
            else:
                source_badge = (
                    ' <span style="background:rgba(255,255,255,0.06);color:#9ca3af;font-size:0.6rem;'
                    'font-weight:700;padding:2px 7px;border-radius:12px;border:1px solid rgba(255,255,255,0.12);'
                    'vertical-align:middle;letter-spacing:0.03em;">GITHUB</span>'
                )
            otw_badge = (
                ' <span style="background:#16a34a22;color:#4ade80;font-size:0.7rem;'
                'font-weight:700;padding:3px 8px;border-radius:20px;border:1px solid #16a34a66;'
                'vertical-align:middle;">🟢 OPEN TO WORK</span>'
                if profile.get("hireable") else ""
            )
            net_badge = ""
            conn_match = None
            if connections:
                conn_match = find_connection_match(
                    connections,
                    name=profile.get("name") or "",
                    email=profile.get("email") or "",
                )
                if conn_match:
                    net_badge = connection_badge()
            linkedin_url = conn_match.get("linkedin_url") if conn_match else None
            if linkedin_url:
                st.markdown(
                    f'<h3 style="margin:0;padding:0;"><a href="{linkedin_url}" target="_blank" '
                    f'style="color:#60a5fa;text-decoration:none;">{name} '
                    f'<span style="font-size:0.6em;vertical-align:middle;">🔗</span></a>'
                    f'{source_badge}{otw_badge}{net_badge}</h3>',
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<h3 style="margin:0;padding:0;"><a href="https://github.com/{username}" target="_blank" '
                    f'style="color:#e0e0e0;text-decoration:none;">{name}</a>'
                    f'{source_badge}{otw_badge}{net_badge}</h3>',
                    unsafe_allow_html=True)
            if conn_match:
                conn_details = []
                if conn_match.get("title"):   conn_details.append(conn_match["title"])
                if conn_match.get("company"): conn_details.append(conn_match["company"])
                if conn_match.get("phone"):   conn_details.append(f"📞 {conn_match['phone']}")
                if conn_match.get("email"):   conn_details.append(f"✉️ {conn_match['email']}")
                if conn_details:
                    st.caption("**From your network:** " + "  ·  ".join(conn_details))
            if profile.get("bio"):
                st.caption(profile["bio"])

            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Repos",     profile.get("public_repos", 0))
            s2.metric("Followers", profile.get("followers", 0))
            s3.metric("Contribs",  contributor.get("contributions", 0))
            s4.metric("Acc. Age",  fmt_age(profile))

            meta = []
            if profile.get("location"): meta.append(f"📍 {profile['location']}")
            if profile.get("company"):  meta.append(f"🏢 {profile['company'].strip('@')}")
            if meta:
                st.caption("  ·  ".join(meta))

            contact = []
            if profile.get("email"):
                contact.append(f"✉️ [{profile['email']}](mailto:{profile['email']})")
            if profile.get("twitter_username"):
                contact.append(f"𝕏 [@{profile['twitter_username']}](https://x.com/{profile['twitter_username']})")
            if profile.get("blog"):
                blog = profile["blog"]
                if not blog.startswith("http"):
                    blog = "https://" + blog
                contact.append(f"🔗 [{profile['blog']}]({blog})")
            if contact:
                st.markdown("  ·  ".join(contact))

            if languages:
                st.markdown("**Languages:** " + "  ".join([f"`{l}`" for l in languages]))
            if user_repos:
                repo_links = "  ".join(
                    [f"[{r['name']}](https://github.com/{username}/{r['name']})" for r in user_repos[:3]]
                )
                st.markdown(f"**Top repos:** {repo_links}")

        with col_action:
            # Show which projects this candidate is in
            in_projects = get_candidate_projects(username)
            if in_projects:
                tags = "  ".join([f"`{pn}: {ps}`" for pn, ps in in_projects])
                st.markdown(f"📁 {tags}", help="Projects this candidate is in")

            # Check if candidate is already in this project
            _in_current_project = stage != "New"

            if _in_current_project:
                # Already in project — show stage management
                st.markdown(
                    f'<span style="background:#22c55e18;color:#22c55e;font-size:0.72rem;font-weight:700;'
                    f'padding:3px 10px;border-radius:20px;border:1px solid #22c55e40;">'
                    f'✅ In {_pname}</span>', unsafe_allow_html=True)
                current_idx = PIPELINE_STAGES.index(stage) if stage in PIPELINE_STAGES else 0
                new_stage = st.selectbox("Stage", PIPELINE_STAGES[1:],
                                         index=max(0, current_idx - 1),
                                         key=f"pipe_{_pname}_{username}_{idx}")
                if new_stage != stage:
                    update_pipeline(username, new_stage, project_name=_pname)
                    st.rerun()
                # Remove from project
                if st.button("❌ Remove", key=f"rmpipe_{_pname}_{username}_{idx}", use_container_width=True):
                    update_pipeline(username, "New", project_name=_pname)
                    st.toast(f"Removed from {_pname}", icon="🗑️")
                    st.rerun()
            else:
                # NOT in project — ONE-CLICK add, defaults to "Contacted"
                if st.button(f"➕ Add to {_pname}", key=f"addbtn_{_pname}_{username}_{idx}",
                             type="primary", use_container_width=True):
                    update_pipeline(username, "Contacted", project_name=_pname)
                    st.toast(f"Added to {_pname}!", icon="✅")
                    st.rerun()

            # Add to other projects — tucked in expander (Change 5)
            proj_data = load_projects()
            proj_names = list(proj_data.get("projects", {}).keys())
            other_projects = [p for p in proj_names if p != _pname]
            if other_projects:
                with st.expander("More…", expanded=False):
                    add_proj = st.selectbox("Add to project", ["—"] + other_projects, key=f"copyproj_{_pname}_{username}_{idx}")
                    if add_proj != "—":
                        if st.button(f"Add to {add_proj}", key=f"copybtn_{_pname}_{username}_{idx}", use_container_width=True):
                            update_pipeline(username, "Contacted", project_name=add_proj)
                            st.toast(f"Added to {add_proj}", icon="📁")
                        st.rerun()

            # LinkedIn
            li_url_direct = conn_match.get("linkedin_url") if conn_match else None
            if li_url_direct:
                st.markdown(
                    f'<a href="{li_url_direct}" target="_blank" style="display:block;text-align:center;padding:8px 12px;'
                    f'background:rgba(10,102,194,0.15);border:1px solid rgba(10,102,194,0.4);'
                    f'border-radius:8px;color:#60a5fa;text-decoration:none;font-size:0.85rem;'
                    f'font-weight:600;margin-bottom:8px;">🔗 View LinkedIn</a>',
                    unsafe_allow_html=True,
                )
            else:
                li_name = quote(profile.get("name") or username)
                st.markdown(
                    f'<a href="https://www.linkedin.com/search/results/people/?keywords={li_name}" '
                    f'target="_blank" style="display:block;text-align:center;padding:8px 12px;'
                    f'background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.12);'
                    f'border-radius:8px;color:#d0d0d0;text-decoration:none;font-size:0.85rem;'
                    f'font-weight:600;margin-bottom:8px;">🔍 Search LinkedIn</a>',
                    unsafe_allow_html=True,
                )

            # Outreach
            if st.button("✉️ Generate Outreach", key=f"outreach_{_pname}_{username}_{idx}"):
                with st.spinner("Writing…"):
                    st.session_state[f"msg_{username}"] = generate_outreach(profile, role_query, user_repos, project_jd)
            if f"msg_{username}" in st.session_state:
                st.code(st.session_state[f"msg_{username}"], language=None)

            # Notes
            existing_note = st.session_state["notes"].get(username, "")
            new_note = st.text_area("📝 Notes", value=existing_note, height=70,
                                    key=f"note_{_pname}_{username}_{idx}", placeholder="Private notes…")
            if st.button("💾 Save note", key=f"save_{_pname}_{username}_{idx}"):
                persist_note(username, new_note)
                st.session_state["notes"][username] = new_note
                st.toast("Note saved!", icon="📝")

    st.divider()

# ─────────────────────────────────────────────
# App Layout
# ─────────────────────────────────────────────
st.set_page_config(page_title="N5H", page_icon="🔍", layout="wide")
st.markdown(PREMIUM_CSS, unsafe_allow_html=True)

# ── Password Gate with Rate Limiting ──────────
APP_PASSWORD = os.getenv("APP_PASSWORD", "alphieisdaddy")
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 300  # 5-minute lockout after max attempts

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "login_attempts" not in st.session_state:
    st.session_state["login_attempts"] = 0
if "lockout_until" not in st.session_state:
    st.session_state["lockout_until"] = 0

if not st.session_state["authenticated"]:
    st.title("🔒 N5H")
    st.caption("Enter password to continue")

    # Check lockout
    now = time.time()
    if st.session_state["lockout_until"] > now:
        remaining = int(st.session_state["lockout_until"] - now)
        mins, secs = divmod(remaining, 60)
        st.error(f"🚫 Too many failed attempts. Locked out for **{mins}m {secs}s**.")
        st.caption("Refresh the page to try again after the lockout expires.")
        st.stop()

    pwd = st.text_input("Password", type="password", placeholder="Enter password…")
    attempts_left = MAX_LOGIN_ATTEMPTS - st.session_state["login_attempts"]
    if st.session_state["login_attempts"] > 0:
        st.caption(f"⚠️ {attempts_left} attempt{'s' if attempts_left != 1 else ''} remaining")

    if st.button("Login", type="primary", use_container_width=True):
        if pwd == APP_PASSWORD:
            st.session_state["authenticated"] = True
            st.session_state["login_attempts"] = 0
            st.session_state["lockout_until"] = 0
            st.rerun()
        else:
            st.session_state["login_attempts"] += 1
            if st.session_state["login_attempts"] >= MAX_LOGIN_ATTEMPTS:
                st.session_state["lockout_until"] = time.time() + LOCKOUT_SECONDS
                st.error(f"🚫 Account locked for {LOCKOUT_SECONDS // 60} minutes after {MAX_LOGIN_ATTEMPTS} failed attempts.")
            else:
                st.error("Wrong password")
            st.rerun()
    st.stop()


# ══════════════════════════════════════════════
# AUTHENTICATED — Project-Centric Workspace
# ══════════════════════════════════════════════

if "notes" not in st.session_state:
    st.session_state["notes"] = load_notes()
if "current_project" not in st.session_state:
    _init_proj = load_projects()
    _last_active = _init_proj.get("_active")
    if _last_active and _last_active in _init_proj.get("projects", {}):
        st.session_state["current_project"] = _last_active
    else:
        st.session_state["current_project"] = None

# ─────────────────────────────────────────────
# Helper: project-scoped session key
# ─────────────────────────────────────────────
def _pk(key):
    """Return a session-state key scoped to the current project."""
    pn = st.session_state.get("current_project") or "_global"
    return f"{pn}::{key}"

# ─────────────────────────────────────────────
# SIDEBAR — always visible
# ─────────────────────────────────────────────
with st.sidebar:
    # ── Project list — clean, minimal ──
    projects_data = load_projects()
    project_names = list(projects_data.get("projects", {}).keys())

    st.markdown("### Projects")

    # Home button
    if st.button("🏠 Home", use_container_width=True,
                 type="primary" if st.session_state["current_project"] is None else "secondary"):
        st.session_state["current_project"] = None
        st.rerun()

    # List each project — clean names, active one highlighted
    for pn in project_names:
        is_active = (pn == st.session_state["current_project"])
        btn_label = f"{'▸ ' if is_active else '   '}{pn}"
        if st.button(btn_label, key=f"sb_proj_{pn}", use_container_width=True,
                     type="primary" if is_active else "secondary"):
            st.session_state["current_project"] = pn
            set_active_project(pn)
            st.rerun()

    # Quick-create project
    with st.expander("➕ New Project", expanded=False):
        _new_name = st.text_input("Project name", key="sb_new_proj", placeholder="e.g. Inferra")
        if st.button("Create", key="sb_create_proj", use_container_width=True):
            if _new_name.strip():
                create_project(_new_name.strip())
                st.session_state["current_project"] = _new_name.strip()
                st.rerun()

    st.divider()

    # ── Network — compact ──
    existing_connections = load_connections()
    if existing_connections:
        st.caption(f"📇 {len(existing_connections):,} connections")
    with st.expander("Upload CSV", expanded=not bool(existing_connections)):
        uploaded_files = st.file_uploader("CSVs", type=["csv"], label_visibility="collapsed", accept_multiple_files=True)
        if uploaded_files:
            existing_set = {(c["name"].lower(), c["email"].lower()) for c in existing_connections}
            total_added = 0
            for uploaded in uploaded_files:
                new_connections = parse_connections_csv_bytes(uploaded.read())
                for c in new_connections:
                    key = (c["name"].lower(), c["email"].lower())
                    if key not in existing_set:
                        existing_connections.append(c)
                        existing_set.add(key)
                        total_added += 1
            if total_added > 0:
                save_connections(existing_connections)
                st.toast(f"Added {total_added:,} new connections", icon="📇")
                st.rerun()
            elif uploaded_files:
                st.info("All already loaded.")

    # ── Settings — minimal ──
    with st.expander("⚙️", expanded=False):
        _status = []
        _status.append("✅ GitHub" if GITHUB_TOKEN_OK else "❌ GitHub")
        _status.append("✅ OpenAI" if OPENAI_KEY_OK else "❌ OpenAI")
        if PROXYCURL_OK:
            _status.append("✅ Proxycurl")
        st.caption(" · ".join(_status))
        if existing_connections:
            if st.button("Clear connections", use_container_width=True):
                save_connections([])
                st.rerun()

    # ── Post-search filters (moved from prominent sidebar to here) ──
    _rk = _pk("results")
    filter_langs = []
    filter_location = ""
    filter_company = ""
    filter_company_select = []
    filter_min_score = 0.0
    sort_by = "Score"
    filter_open_only = False
    hide_archived = False
    hide_contacted = False

    if _rk in st.session_state and st.session_state[_rk]:
        st.markdown("### 🎛️ Refine Results")
        _all_langs = sorted({l for c in st.session_state[_rk] for l in c.get("languages", [])})
        _all_companies = sorted({
            (c["profile"].get("company") or "").strip("@ ").strip()
            for c in st.session_state[_rk]
            if (c["profile"].get("company") or "").strip()
        })
        filter_open_only = st.toggle("🟢 Open to work only", value=False)
        hide_contacted = st.toggle("👻 Hide already contacted", value=False)
        hide_archived = st.toggle("🗂️ Hide archived", value=True)
        filter_langs = st.multiselect("Language", _all_langs)
        filter_location = st.text_input("📍 Location contains", placeholder="e.g. San Francisco")
        filter_company = st.text_input("🏢 Company contains", placeholder="e.g. Meta")
        if _all_companies:
            filter_company_select = st.multiselect("🏢 Or pick companies", _all_companies)
        _has_scores = any(c["score"] is not None for c in st.session_state[_rk])
        if _has_scores:
            filter_min_score = st.slider("Min score", 0.0, 10.0, 0.0, 0.5)
        sort_by = st.selectbox("Sort by", ["Score", "Followers", "Contributions", "Account Age"])
        st.divider()

# ═════════════════════════════════════════════
# MAIN CONTENT AREA
# ═════════════════════════════════════════════

if st.session_state["current_project"] is None:
    # ─────────────────────────────────────────
    # PROJECT HOME — List all projects
    # ─────────────────────────────────────────
    st.title("N5H")
    st.caption("Developer sourcing, simplified.")

    # Quick create — one line
    _qc1, _qc2 = st.columns([3, 1])
    with _qc1:
        new_proj_name = st.text_input("New project", placeholder="e.g. Inferra", label_visibility="collapsed")
    with _qc2:
        if st.button("+ Create", type="primary", use_container_width=True):
            if new_proj_name.strip():
                create_project(new_proj_name.strip())
                st.session_state["current_project"] = new_proj_name.strip()
                st.rerun()

    st.divider()

    # ── Project cards grid ──
    projects_data = load_projects()
    project_names = list(projects_data.get("projects", {}).keys())

    if project_names:
        for pi, pname in enumerate(project_names):
            pdata = projects_data["projects"][pname]
            p_count = len(pdata.get("candidates", {}))
            p_jd = pdata.get("job_description", "")
            p_created = pdata.get("created", "")
            # Stage counts
            _sc = {}
            for _cv in pdata.get("candidates", {}).values():
                _ss = _cv.get("stage", "New")
                _sc[_ss] = _sc.get(_ss, 0) + 1
            stage_pills = ""
            for _sn in PIPELINE_STAGES[1:-1]:  # skip New and Archived
                _cnt = _sc.get(_sn, 0)
                if _cnt:
                    _clr, _ = STAGE_STYLE[_sn]
                    stage_pills += (
                        f'<span style="background:{_clr}15;color:{_clr};font-size:0.65rem;'
                        f'font-weight:600;padding:2px 8px;border-radius:12px;'
                        f'border:1px solid {_clr}30;margin-right:4px;">'
                        f'{_sn} {_cnt}</span>'
                    )
            jd_status = f'<span style="color:#22c55e;font-size:0.7rem;">📋 JD loaded</span>' if p_jd else '<span style="color:#6b7280;font-size:0.7rem;">No JD</span>'

            with st.container():
                _c1, _c2, _c3 = st.columns([4, 2, 1])
                with _c1:
                    st.markdown(
                        f'<div style="margin:0;">'
                        f'<span style="font-size:1.15rem;font-weight:700;color:#f0f0f0;">{pname}</span>'
                        f'<span style="color:#60a5fa;font-size:0.8rem;font-weight:600;margin-left:10px;">'
                        f'{p_count} candidates</span></div>'
                        f'<div style="margin:4px 0;">{stage_pills}</div>'
                        f'<div style="display:flex;gap:12px;align-items:center;margin-top:2px;">'
                        f'{jd_status}'
                        f'<span style="color:#4b5563;font-size:0.65rem;">{p_created}</span></div>',
                        unsafe_allow_html=True)
                with _c2:
                    if st.button("Open", key=f"home_open_{pi}", type="primary", use_container_width=True):
                        st.session_state["current_project"] = pname
                        set_active_project(pname)
                        st.rerun()
                with _c3:
                    if len(project_names) > 1:
                        if st.button("🗑️", key=f"home_del_{pi}", use_container_width=True, help="Delete project"):
                            delete_project(pname)
                            st.rerun()

else:
    # ─────────────────────────────────────────
    # PROJECT WORKSPACE — the LinkedIn Recruiter experience
    # ─────────────────────────────────────────
    _proj_name = st.session_state["current_project"]
    _proj_data_all = load_projects()

    # Handle deleted project
    if _proj_name not in _proj_data_all.get("projects", {}):
        st.session_state["current_project"] = None
        st.rerun()

    _proj = _proj_data_all["projects"][_proj_name]
    _proj_jd = _proj.get("job_description", "")
    _proj_pipeline = _proj.get("candidates", {})

    # ── Clean header — one line, no clutter ──
    _jd_tag = f'<span style="color:#22c55e;font-size:0.75rem;font-weight:600;margin-left:8px;">JD loaded</span>' if _proj_jd.strip() else '<span style="color:#f59e0b;font-size:0.75rem;font-weight:600;margin-left:8px;">No JD</span>'
    st.markdown(
        f'<div style="display:flex;align-items:baseline;gap:0;margin-bottom:-8px;">'
        f'<h1 style="margin:0;padding:0;">{_proj_name}</h1>'
        f'<span style="color:#4b5563;font-size:0.8rem;margin-left:12px;">'
        f'{len(_proj_pipeline)} candidates</span>{_jd_tag}</div>',
        unsafe_allow_html=True)

    # ── Inner tabs: Search | Pipeline | JD ──
    ws_tab_search, ws_tab_pipeline, ws_tab_jd = st.tabs(["🔍 Search", "📊 Pipeline", "📋 Job Description"])

    # ══════════════════════════════════════════
    # TAB: JD (edit job description)
    # ══════════════════════════════════════════
    with ws_tab_jd:
        if _proj_jd.strip():
            st.success(f"JD loaded — {len(_proj_jd):,} characters")
        else:
            st.info("No JD attached yet. Paste one below to enable AI-powered search and scoring.")
        _edit_jd = st.text_area("Job Description", value=_proj_jd, height=300, key=f"edit_jd_{_proj_name}",
                                placeholder="Paste the full JD, company brief, or 1-pager here…")
        _edit_jd_file = st.file_uploader("Or upload PDF/TXT", type=["pdf", "txt"], key=f"edit_jd_file_{_proj_name}")
        if _edit_jd_file:
            if _edit_jd_file.name.lower().endswith(".pdf"):
                _extracted = extract_text_from_pdf(_edit_jd_file.read())
                if _extracted and not _extracted.startswith("[PDF"):
                    _edit_jd = _extracted
            else:
                _edit_jd = _edit_jd_file.read().decode("utf-8", errors="ignore")
        if st.button("Save JD", key=f"save_jd_{_proj_name}", type="primary", use_container_width=True):
            update_project_jd(_proj_name, _edit_jd)
            st.toast("Job description saved!", icon="📋")
            st.rerun()

    # ══════════════════════════════════════════
    # TAB: SEARCH (within project workspace)
    # ══════════════════════════════════════════
    with ws_tab_search:
        # Clean search bar — one row
        _s1, _s2, _s3, _s4 = st.columns([3, 1.5, 1.5, 1])
        with _s1:
            _extra_input = st.text_input("Search", placeholder="Extra keywords (or leave blank to use JD)", key=f"extra_search_{_proj_name}", label_visibility="collapsed")
        with _s2:
            location_query = st.text_input("Location", placeholder="Location", key=f"loc_{_proj_name}", label_visibility="collapsed")
        with _s3:
            company_query = st.text_input("Company", placeholder="Company", key=f"comp_{_proj_name}", label_visibility="collapsed")
        with _s4:
            max_candidates = st.selectbox("Max", [50, 100, 250, 500, 1000], index=1, key=f"maxc_{_proj_name}", label_visibility="collapsed")

        # Hidden refinements
        with st.expander("More filters", expanded=False):
            _rf1, _rf2 = st.columns(2)
            with _rf1:
                seniority = st.selectbox("Seniority", list(SENIORITY_MAP.keys()), key=f"sen_{_proj_name}")
            with _rf2:
                min_followers_val = st.number_input("Min followers", min_value=0, value=0, step=50, key=f"fol_{_proj_name}")

        # Combine: project JD + extra input
        _all_jd_parts = []
        if _proj_jd.strip():
            _all_jd_parts.append(_proj_jd.strip())
        if _extra_input.strip():
            _all_jd_parts.append(_extra_input.strip())
        job_description = "\n\n".join(_all_jd_parts)
        _jd_file_text = ""

        role_query = ""
        sel_languages = []

        def build_user_query(include_location=True):
            parts = []
            if role_query.strip():
                parts.append(role_query.strip())
            if include_location and location_query.strip():
                loc = location_query.strip()
                loc_lower = loc.lower().replace(" ", "")
                loc_map = {
                    "sf": "San Francisco", "sanfrancisco": "San Francisco",
                    "bayarea": "San Francisco", "bay area": "San Francisco",
                    "nyc": "New York", "newyork": "New York",
                    "la": "Los Angeles", "losangeles": "Los Angeles",
                    "dc": "Washington DC", "washingtondc": "Washington DC",
                    "chi": "Chicago",
                }
                gh_loc = loc_map.get(loc_lower, loc_map.get(loc.lower(), loc))
                parts.append(f'location:"{gh_loc}"')
            if SENIORITY_MAP.get(seniority, ""):
                parts.append(SENIORITY_MAP[seniority])
            elif min_followers_val > 0:
                parts.append(f"followers:>{min_followers_val}")
            parts.append("type:user")
            return " ".join(parts)

        search_clicked = st.button("🔍 Find Candidates", type="primary", use_container_width=True, key=f"search_btn_{_proj_name}")

        if search_clicked:
            if not GITHUB_TOKEN_OK or not OPENAI_KEY_OK:
                st.error("Missing API keys — add them to `~/n5h/.env`")
                st.stop()

            roles_found = []
            if job_description.strip():
                with st.spinner("🤖 Analyzing job description — extracting roles & keywords…"):
                    roles_found = extract_roles_from_jd(job_description)
                    if roles_found:
                        role_titles = [r.get("title", "") for r in roles_found if r.get("title")]
                        st.info(f"🎯 Found **{len(roles_found)} role{'s' if len(roles_found) > 1 else ''}** in JD: {', '.join(role_titles)}")
                        all_terms = []
                        for r in roles_found:
                            t = r.get("search_terms", "") or r.get("title", "")
                            if t:
                                all_terms.append(t)
                        role_query = " | ".join(all_terms) if all_terms else roles_found[0].get("title", "")
                    else:
                        extracted = extract_search_keywords(job_description)
                        if extracted:
                            role_query = extracted
                            st.info(f"🔍 Searching for: **{extracted}** (extracted from JD)")

            if not role_query.strip() and not job_description.strip():
                st.warning("Add a job description to this project, or type search terms above.")
                st.stop()

            # ── Smart role classification: technical vs business ──
            _role_class = classify_role_and_expand(role_query, job_description)
            _role_type = _role_class.get("type", "technical")
            _net_queries = _role_class.get("network_queries", [])
            _synonyms = _role_class.get("synonyms", [])
            _skip_github = False

            if _role_type == "business":
                st.info(
                    f"💼 **Business role detected** — {_role_class.get('reason', 'not typically found on GitHub')}. "
                    f"Prioritising your network. Also searching: {', '.join(_synonyms[:5])}"
                )
                _skip_github = True  # Skip GitHub for pure business roles

            # Store expanded queries for network search later
            st.session_state["_net_expanded_queries"] = _net_queries + _synonyms

            if not _skip_github:
                with st.spinner(f"🤖 Generating search queries for {len(roles_found) if roles_found else 1} role{'s' if len(roles_found) != 1 else ''}…"):
                    ai_queries = generate_search_queries(
                        role_query, location_query, company_query, seniority, job_description,
                        roles_list=roles_found if roles_found else None
                    )
            else:
                ai_queries = []  # No GitHub search for business roles
            if not ai_queries and not _skip_github:
                ai_queries = [build_user_query()]

            if ai_queries:
                with st.expander(f"🔎 Running {len(ai_queries)} search queries", expanded=False):
                    for qi, q in enumerate(ai_queries, 1):
                        st.markdown(f"**Query {qi}:** `{q}`")

            per_query_limit = 200
            all_users = []
            seen_logins = set()
            candidates = []

            if ai_queries and not _skip_github:
                def _run_query(query):
                    results, err = search_users_direct(query, per_query_limit)
                    if err and not results:
                        return [], err
                    return results, None

                with st.spinner(f"Searching GitHub with {len(ai_queries)} queries…"):
                    query_errors = []
                    with ThreadPoolExecutor(max_workers=min(15, len(ai_queries))) as executor:
                        futures = {executor.submit(_run_query, q): q for q in ai_queries}
                        for future in as_completed(futures):
                            users_batch, err = future.result()
                            if err:
                                query_errors.append(err)
                            for u in users_batch:
                                if u["login"] not in seen_logins:
                                    seen_logins.add(u["login"])
                                    all_users.append(u)
                    if query_errors and not all_users and not _skip_github:
                        st.error(f"All queries failed: {query_errors[0]}")

                st.info(f"Found **{len(all_users)}** unique GitHub candidates across {len(ai_queries)} queries")

            linkedin_profiles = []
            if PROXYCURL_OK:
                with st.spinner("🔍 Searching LinkedIn via Proxycurl…"):
                    li_results, li_err = search_linkedin_profiles(
                        role_query, location_query, company_query, max_results=50
                    )
                    if li_err:
                        st.caption(f"LinkedIn search note: {li_err}")
                    if li_results:
                        linkedin_profiles = li_results
                        st.info(f"🔗 Found {len(li_results)} LinkedIn profiles")

            if all_users:
                # Cap users to fetch — GitHub API can't handle thousands of concurrent requests
                fetch_limit = min(len(all_users), max(max_candidates * 3, 300), 1500)
                users = all_users[:fetch_limit]
                if len(all_users) > fetch_limit:
                    st.caption(f"ℹ️ Fetching top {fetch_limit} of {len(all_users)} candidates (sorted by GitHub relevance)")

                st.markdown(f"### ⚡ Fetching {len(users)} profiles…")
                prog = st.progress(0)
                cache = _load_cache()

                def _fetch_one(user):
                    username = user["login"]
                    try:
                        entry = cache.get(username)
                        if entry and time.time() - entry.get("ts", 0) < CACHE_TTL:
                            profile = entry["data"]
                        else:
                            profile = _fetch_user_profile(username)
                            if profile:
                                cache[username] = {"ts": time.time(), "data": profile}
                        if not profile:
                            return None
                        user_repos = get_user_repos(username)
                        languages = get_user_languages(username, repos=user_repos)
                        return {
                            "contributor": {"contributions": 0, "login": username},
                            "profile": profile,
                            "user_repos": user_repos,
                            "languages": languages,
                            "score": None,
                            "reason": "",
                            "conclusion": "",
                        }
                    except Exception:
                        return None

                done = 0
                with ThreadPoolExecutor(max_workers=15) as executor:
                    futures = {executor.submit(_fetch_one, u): u for u in users}
                    for future in as_completed(futures):
                        done += 1
                        prog.progress(done / len(users))
                        try:
                            result = future.result()
                        except Exception:
                            result = None
                        if result:
                            result["source"] = "github"
                            candidates.append(result)
                prog.empty()
                _save_cache(cache)

            total_fetched = len(candidates)

            if location_query.strip():
                filtered = [c for c in candidates
                            if _location_matches(c["profile"].get("location", ""), location_query)]
                if filtered:
                    candidates = filtered
                    st.info(f"📍 {len(filtered)} of {total_fetched} profiles match location \"{location_query}\"")
                else:
                    st.warning(f"⚠️ No profiles matched location \"{location_query}\" — showing all.")

            if company_query.strip():
                comp_q = company_query.lower().strip()
                filtered = [c for c in candidates
                            if comp_q in (c["profile"].get("company") or "").lower().strip("@ ")
                            or comp_q in (c["profile"].get("bio") or "").lower()]
                if filtered:
                    st.info(f"🏢 {len(filtered)} profiles match company \"{company_query}\"")
                    candidates = filtered

            candidates = candidates[:max_candidates]

            # ── Merge network connections into results ──
            _net_conns_for_merge = load_connections()
            if _net_conns_for_merge:
                # Use expanded queries from AI classification for broader network search
                _expanded = st.session_state.get("_net_expanded_queries", [])
                _net_keyword = role_query or (_extra_input.strip()[:100] if _extra_input.strip() else "")

                # Run multiple search passes: original query + each synonym/expanded query
                _all_net_matches = []
                _seen_net_names = set()

                # Pass 1: Original query
                for _qry in [_net_keyword] + _expanded:
                    if not _qry.strip():
                        continue
                    _batch = search_connections(_net_conns_for_merge, _qry, location_query, company_query, "")
                    for _nc in _batch:
                        _nk = _nc.get("name", "").lower()
                        if _nk and _nk not in _seen_net_names:
                            _seen_net_names.add(_nk)
                            _all_net_matches.append(_nc)

                _net_matches = _all_net_matches
                _net_cap = 200 if _skip_github else 50  # More network results when GitHub is skipped

                # Deduplicate: skip network matches already in GitHub results by name
                _gh_names = {(c["profile"].get("name") or "").lower() for c in candidates}
                _gh_logins = {c["profile"]["login"].lower() for c in candidates}
                _added_net = 0
                for _nc in _net_matches[:_net_cap]:
                    _nc_name = _nc.get("name", "").lower()
                    if _nc_name in _gh_names or not _nc_name:
                        continue
                    # Create pseudo-candidate dict so render_candidate works
                    _nc_login = f"conn_{_nc_name.replace(' ', '_')}"
                    if _nc_login in _gh_logins:
                        continue
                    _pseudo = {
                        "profile": {
                            "login": _nc_login,
                            "name": _nc.get("name", ""),
                            "bio": _nc.get("title", ""),
                            "company": _nc.get("company", ""),
                            "location": _nc.get("location", ""),
                            "email": _nc.get("email", ""),
                            "avatar_url": "",
                            "html_url": _nc.get("linkedin_url", ""),
                            "hireable": False,
                            "followers": 0,
                            "following": 0,
                            "public_repos": 0,
                            "created_at": "",
                            "twitter_username": "",
                            "blog": "",
                        },
                        "user_repos": [],
                        "languages": [],
                        "score": None,
                        "reason": "",
                        "conclusion": "",
                        "source": "network",
                        "contributor": {},
                        "_conn_data": _nc,  # keep original connection data
                    }
                    candidates.append(_pseudo)
                    _added_net += 1
                if _added_net:
                    st.info(f"📇 Also included **{_added_net} matches** from your network")

            if not candidates:
                if _skip_github:
                    st.warning("No matching connections found in your network for this business role. Try uploading more CSVs with relevant contacts.")
                else:
                    st.warning("No candidates after filtering.")
                st.stop()

            score_label = role_query or "the role"
            jd_text = job_description

            SCORE_BATCH = 50
            if len(candidates) <= SCORE_BATCH:
                st.markdown(f"### 🤖 Scoring {len(candidates)} candidates…")
                scores, score_err = score_candidates_batch(candidates, score_label, jd_text)
            else:
                st.markdown(f"### 🤖 Scoring {len(candidates)} candidates in batches of {SCORE_BATCH}…")
                score_prog = st.progress(0)
                scores, score_err = {}, None
                for batch_start in range(0, len(candidates), SCORE_BATCH):
                    batch = candidates[batch_start:batch_start + SCORE_BATCH]
                    batch_scores, err = score_candidates_batch(batch, score_label, jd_text)
                    if err:
                        score_err = err
                        if err == "quota":
                            break
                    for local_i, val in batch_scores.items():
                        scores[batch_start + local_i] = val
                    score_prog.progress(min(1.0, (batch_start + SCORE_BATCH) / len(candidates)))
                score_prog.empty()

            if score_err == "quota":
                st.warning("⚠️ OpenAI quota exceeded — candidates shown unscored.")
            elif score_err:
                st.warning(f"Scoring issue: {score_err}")

            for i, c in enumerate(candidates):
                if i in scores:
                    score_tuple = scores[i]
                    c["score"] = score_tuple[0]
                    c["reason"] = score_tuple[1] if len(score_tuple) > 1 else ""
                    c["conclusion"] = score_tuple[2] if len(score_tuple) > 2 else ""

            candidates.sort(key=lambda x: (x["score"] is not None, x["score"] or 0), reverse=True)
            st.session_state[_pk("results")] = candidates
            st.session_state[_pk("loaded_role")] = score_label
            st.session_state[_pk("res_page")] = 0

            # Auto-save search
            persist_search(f"{_proj_name}: {score_label}", candidates)

        # ── Render search results ──
        _rk = _pk("results")
        if _rk in st.session_state and st.session_state[_rk]:
            role_query_active = st.session_state.get(_pk("loaded_role"), "")
            scored_candidates = st.session_state[_rk]
            pipeline = _proj_pipeline

            display = scored_candidates
            if filter_open_only:
                display = [c for c in display if c["profile"].get("hireable")]
            if hide_contacted:
                display = [c for c in display if pipeline.get(c["profile"]["login"], {}).get("stage", "New") not in ("Contacted", "Replied", "Hired")]
            if hide_archived:
                display = [c for c in display if pipeline.get(c["profile"]["login"], {}).get("stage", "New") != "Archived"]
            if filter_langs:
                display = [c for c in display if any(l in c.get("languages", []) for l in filter_langs)]
            if filter_location:
                display = [c for c in display if _location_matches(c["profile"].get("location", ""), filter_location)]
            if filter_company:
                comp_q = filter_company.lower().strip()
                display = [c for c in display
                            if comp_q in (c["profile"].get("company") or "").lower().strip("@ ")
                            or comp_q in (c["profile"].get("bio") or "").lower()]
            if filter_company_select:
                sel_lower = {co.lower() for co in filter_company_select}
                display = [c for c in display
                            if (c["profile"].get("company") or "").strip("@ ").strip().lower() in sel_lower]
            if filter_min_score > 0:
                display = [c for c in display if (c["score"] or 0) >= filter_min_score]

            if sort_by == "Followers":
                display = sorted(display, key=lambda c: c["profile"].get("followers", 0), reverse=True)
            elif sort_by == "Contributions":
                display = sorted(display, key=lambda c: c.get("contributor", {}).get("contributions", 0), reverse=True)
            elif sort_by == "Account Age":
                display = sorted(display, key=lambda c: account_age_days(c["profile"]), reverse=True)

            res_col, csv_col = st.columns([4, 1])
            with res_col:
                st.success(f"✅ **{len(display)} candidates** for: _{role_query_active}_ → Adding to **{_proj_name}**")
            with csv_col:
                st.download_button(
                    label="⬇️ Export CSV",
                    data=build_csv(display, role_query_active),
                    file_name=f"n5h_{_proj_name.replace(' ','_')}_candidates.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            st.divider()

            if not display:
                st.warning("No candidates match the current filters.")
            else:
                all_connections = load_connections()
                res_page_size = 25
                _rpk = _pk("res_page")
                res_total_pages = max(1, (len(display) + res_page_size - 1) // res_page_size)
                if _rpk not in st.session_state:
                    st.session_state[_rpk] = 0
                st.session_state[_rpk] = min(st.session_state[_rpk], res_total_pages - 1)
                res_current = st.session_state[_rpk]
                res_start = res_current * res_page_size
                res_end = min(res_start + res_page_size, len(display))

                if res_total_pages > 1:
                    rp1, rp2, rp3 = st.columns([1, 2, 1])
                    with rp1:
                        if st.button("◀ Prev", disabled=res_current == 0, key=f"rp_{_proj_name}", use_container_width=True):
                            st.session_state[_rpk] -= 1
                            st.rerun()
                    with rp2:
                        st.markdown(f"<div style='text-align:center;padding:8px;color:#aaa;font-size:0.9rem;'>"
                                   f"Page {res_current + 1} of {res_total_pages} · {res_start + 1}–{res_end} of {len(display)}</div>",
                                   unsafe_allow_html=True)
                    with rp3:
                        if st.button("Next ▶", disabled=res_current >= res_total_pages - 1, key=f"rn_{_proj_name}", use_container_width=True):
                            st.session_state[_rpk] += 1
                            st.rerun()

                for idx, c in enumerate(display[res_start:res_end], start=res_start):
                    render_candidate(c, idx, role_query_active, pipeline, all_connections,
                                     project_name=_proj_name, project_jd=_proj_jd)

                if res_total_pages > 1:
                    brp1, brp2, brp3 = st.columns([1, 2, 1])
                    with brp1:
                        if st.button("◀ Previous", disabled=res_current == 0, key=f"rpb_{_proj_name}", use_container_width=True):
                            st.session_state[_rpk] -= 1
                            st.rerun()
                    with brp2:
                        st.markdown(f"<div style='text-align:center;padding:8px;color:#666;font-size:0.85rem;'>"
                                   f"Page {res_current + 1} / {res_total_pages}</div>", unsafe_allow_html=True)
                    with brp3:
                        if st.button("Next ▶", disabled=res_current >= res_total_pages - 1, key=f"rnb_{_proj_name}", use_container_width=True):
                            st.session_state[_rpk] += 1
                            st.rerun()

        # Network results are now merged into the main results list above

    # ══════════════════════════════════════════
    # TAB: PIPELINE (within project workspace)
    # ══════════════════════════════════════════
    with ws_tab_pipeline:
        # Build lookups
        _conn_lookup = {}
        try:
            _all_conns = load_connections()
            for _c in _all_conns:
                _ckey = f"conn_{_c.get('name','').lower().replace(' ','_')}"
                _conn_lookup[_ckey] = _c
        except Exception:
            pass

        _search_lookup = {}
        _srk = _pk("results")
        for _sr in st.session_state.get(_srk, []):
            _login = _sr.get("profile", {}).get("login", "")
            if _login:
                _search_lookup[_login] = _sr

        candidates_in_project = _proj_pipeline

        # Helper to resolve candidate info
        def _resolve_cand(cand_key):
            info = {"name": cand_key, "title": "", "company": "", "location": "",
                    "linkedin_url": "", "email": "", "avatar_url": "", "score": None, "conclusion": ""}
            if cand_key in _conn_lookup:
                c = _conn_lookup[cand_key]
                info.update({"name": c.get("name", cand_key), "title": c.get("title", ""),
                             "company": c.get("company", ""), "location": c.get("location", ""),
                             "linkedin_url": c.get("linkedin_url", ""), "email": c.get("email", "")})
            elif cand_key in _search_lookup:
                sr = _search_lookup[cand_key]
                p = sr.get("profile", {})
                info.update({"name": p.get("name") or p.get("login", cand_key),
                             "title": p.get("bio", ""), "company": (p.get("company") or "").strip("@ "),
                             "location": p.get("location", ""), "avatar_url": p.get("avatar_url", ""),
                             "email": p.get("email", ""), "score": sr.get("score"),
                             "conclusion": sr.get("conclusion", "")})
            elif cand_key.startswith("conn_"):
                info["name"] = cand_key[5:].replace("_", " ").title()
            return info

        st.markdown(
            f'<h2 style="margin:0 0 8px 0;">📊 Pipeline · '
            f'<span style="color:#6b7280;font-size:0.75em;">'
            f'{len(candidates_in_project)} candidates</span></h2>',
            unsafe_allow_html=True)

        if not candidates_in_project:
            st.info("No candidates yet. Use **Search** to find and add candidates.")
        else:
            # Group by stage
            stage_groups = {s: [] for s in PIPELINE_STAGES[1:]}
            for cand_key, cand_data in candidates_in_project.items():
                stage = cand_data.get("stage", "Contacted")
                if stage not in stage_groups:
                    stage_groups[stage] = []
                stage_groups[stage].append((cand_key, cand_data))

            # ── KANBAN BOARD ──
            KANBAN_STAGES = ["Contacted", "Replied", "Interview", "Hired"]
            kanban_cols = st.columns(len(KANBAN_STAGES))

            for col_idx, stage_name in enumerate(KANBAN_STAGES):
                colour, bg = STAGE_STYLE.get(stage_name, ("#9ca3af", "rgba(156,163,175,0.08)"))
                cands_in_stage = stage_groups.get(stage_name, [])

                with kanban_cols[col_idx]:
                    # Column header
                    st.markdown(
                        f'<div style="background:{bg};border-top:3px solid {colour};'
                        f'padding:8px 10px;border-radius:8px;margin-bottom:8px;text-align:center;">'
                        f'<span style="font-weight:700;color:{colour};font-size:0.85rem;">'
                        f'{stage_name}</span>'
                        f'<span style="color:#6b7280;font-size:0.75rem;margin-left:6px;">'
                        f'({len(cands_in_stage)})</span></div>',
                        unsafe_allow_html=True)

                    if not cands_in_stage:
                        st.markdown(
                            '<div style="text-align:center;padding:20px;color:#4b5563;'
                            'font-size:0.75rem;font-style:italic;">Empty</div>',
                            unsafe_allow_html=True)

                    for ci, (cand_key, cand_data) in enumerate(cands_in_stage):
                        info = _resolve_cand(cand_key)
                        name = info["name"]
                        updated = cand_data.get("updated", "")

                        # Compact Kanban card
                        with st.container():
                            # Source indicator
                            _is_network = cand_key.startswith("conn_")
                            _src_tag = (
                                '<span style="color:#a855f7;font-size:0.55rem;font-weight:700;">NET</span> '
                                if _is_network else
                                '<span style="color:#6b7280;font-size:0.55rem;font-weight:700;">GH</span> '
                            )
                            # Name (linked)
                            if info["linkedin_url"]:
                                st.markdown(
                                    f'{_src_tag}<a href="{info["linkedin_url"]}" target="_blank" '
                                    f'style="color:#60a5fa;text-decoration:none;font-weight:700;font-size:0.85rem;">'
                                    f'{name} 🔗</a>', unsafe_allow_html=True)
                            elif cand_key in _search_lookup:
                                st.markdown(
                                    f'{_src_tag}<a href="https://github.com/{cand_key}" target="_blank" '
                                    f'style="color:#60a5fa;text-decoration:none;font-weight:700;font-size:0.85rem;">'
                                    f'{name}</a>', unsafe_allow_html=True)
                            else:
                                st.markdown(f"{_src_tag}**{name}**", unsafe_allow_html=True)

                            # Quick details
                            _parts = []
                            if info["title"]:
                                _parts.append(info["title"][:40])
                            if info["company"]:
                                _parts.append(info["company"])
                            if _parts:
                                st.markdown(
                                    f'<div style="font-size:0.7rem;color:#9ca3af;line-height:1.3;">'
                                    f'{" · ".join(_parts)}</div>',
                                    unsafe_allow_html=True)

                            # Score badge (inline)
                            if info["score"] is not None:
                                s_color = "#22c55e" if info["score"] >= 7 else "#60a5fa" if info["score"] >= 5 else "#f59e0b" if info["score"] >= 3 else "#ef4444"
                                st.markdown(
                                    f'<span style="background:{s_color}18;color:{s_color};font-size:0.7rem;'
                                    f'font-weight:700;padding:2px 6px;border-radius:6px;">'
                                    f'{info["score"]}/10</span>',
                                    unsafe_allow_html=True)

                            # Move buttons — ◀ ▶
                            stage_idx = KANBAN_STAGES.index(stage_name)
                            btn_l, btn_r, btn_x = st.columns([1, 1, 1])
                            with btn_l:
                                if stage_idx > 0:
                                    prev_stage = KANBAN_STAGES[stage_idx - 1]
                                    if st.button("◀", key=f"kb_l_{_proj_name}_{cand_key}_{ci}",
                                                 help=f"Move to {prev_stage}", use_container_width=True):
                                        update_pipeline(cand_key, prev_stage, project_name=_proj_name)
                                        st.rerun()
                            with btn_r:
                                if stage_idx < len(KANBAN_STAGES) - 1:
                                    next_stage = KANBAN_STAGES[stage_idx + 1]
                                    if st.button("▶", key=f"kb_r_{_proj_name}_{cand_key}_{ci}",
                                                 help=f"Move to {next_stage}", use_container_width=True):
                                        update_pipeline(cand_key, next_stage, project_name=_proj_name)
                                        st.rerun()
                            with btn_x:
                                if st.button("✕", key=f"kb_x_{_proj_name}_{cand_key}_{ci}",
                                             help="Remove", use_container_width=True):
                                    update_pipeline(cand_key, "New", project_name=_proj_name)
                                    st.toast("Removed", icon="🗑️")
                                    st.rerun()

            # ── Archived section (collapsible) ──
            archived = stage_groups.get("Archived", [])
            if archived:
                with st.expander(f"🗂️ Archived ({len(archived)})", expanded=False):
                    for ci, (cand_key, cand_data) in enumerate(archived):
                        info = _resolve_cand(cand_key)
                        arc1, arc2 = st.columns([4, 1])
                        with arc1:
                            st.markdown(f"**{info['name']}** — {info.get('title', '')[:40]}")
                        with arc2:
                            if st.button("Restore", key=f"arc_restore_{_proj_name}_{cand_key}_{ci}", use_container_width=True):
                                update_pipeline(cand_key, "Contacted", project_name=_proj_name)
                                st.rerun()

            st.divider()

            # Export
            proj_csv = io.StringIO()
            pw = csv.writer(proj_csv)
            pw.writerow(["Name", "Stage", "Updated", "Title", "Company", "Location", "Email", "LinkedIn"])
            for cand_key, cand_data in candidates_in_project.items():
                _ci = _resolve_cand(cand_key)
                pw.writerow([_ci["name"], cand_data.get("stage", ""), cand_data.get("updated", ""),
                             _ci["title"], _ci["company"], _ci["location"], _ci["email"], _ci["linkedin_url"]])
            st.download_button(
                f"⬇️ Export {_proj_name} Pipeline",
                proj_csv.getvalue().encode("utf-8"),
                f"n5h_{_proj_name.replace(' ','_')}_pipeline.csv",
                "text/csv",
                use_container_width=True,
            )
