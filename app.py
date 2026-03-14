import streamlit as st
import requests
import json
import csv
import io
import os
import time
from datetime import datetime
from urllib.parse import quote
from dotenv import load_dotenv
load_dotenv()

# ─────────────────────────────────────────────
# Paths & Constants
# ─────────────────────────────────────────────
DATA_DIR      = os.path.expanduser("~/n5h/data")
NOTES_FILE    = os.path.join(DATA_DIR, "notes.json")
SAVES_FILE    = os.path.join(DATA_DIR, "saved_searches.json")
CACHE_FILE    = os.path.join(DATA_DIR, "profile_cache.json")
PIPELINE_FILE = os.path.join(DATA_DIR, "pipeline.json")
os.makedirs(DATA_DIR, exist_ok=True)

CACHE_TTL = 86400  # 24 hours

POPULAR_LANGUAGES = [
    "Python", "JavaScript", "TypeScript", "Go", "Rust", "Java",
    "C++", "C", "Ruby", "PHP", "Swift", "Kotlin", "Scala",
    "R", "Julia", "Solidity", "Dart", "Elixir", "Haskell", "Shell",
]

PIPELINE_STAGES = ["New", "Contacted", "Replied", "Hired", "Archived"]

STAGE_STYLE = {
    "New":       ("#9ca3af", "rgba(156,163,175,0.08)"),
    "Contacted": ("#60a5fa", "rgba(96,165,250,0.08)"),
    "Replied":   ("#a78bfa", "rgba(167,139,250,0.08)"),
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
def load_notes():
    if os.path.exists(NOTES_FILE):
        with open(NOTES_FILE) as f:
            return json.load(f)
    return {}

def persist_note(username, text):
    notes = load_notes()
    if text.strip():
        notes[username] = text.strip()
    elif username in notes:
        del notes[username]
    with open(NOTES_FILE, "w") as f:
        json.dump(notes, f, indent=2)

# ─────────────────────────────────────────────
# Saved Searches
# ─────────────────────────────────────────────
def load_saved_searches():
    if os.path.exists(SAVES_FILE):
        with open(SAVES_FILE) as f:
            return json.load(f)
    return []

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
    with open(SAVES_FILE, "w") as f:
        json.dump(saves, f, indent=2)

# ─────────────────────────────────────────────
# Profile Cache
# ─────────────────────────────────────────────
def _load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

def get_user_profile_cached(username):
    cache = _load_cache()
    entry = cache.get(username)
    if entry and time.time() - entry.get("ts", 0) < CACHE_TTL:
        return entry["data"]
    profile = _fetch_user_profile(username)
    if profile:
        cache[username] = {"ts": time.time(), "data": profile}
        if len(cache) > 500:
            for k in sorted(cache, key=lambda k: cache[k].get("ts", 0))[:100]:
                del cache[k]
        _save_cache(cache)
    return profile

# ─────────────────────────────────────────────
# Pipeline CRM
# ─────────────────────────────────────────────
def load_pipeline():
    if os.path.exists(PIPELINE_FILE):
        try:
            with open(PIPELINE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def update_pipeline(username, stage):
    pipeline = load_pipeline()
    if stage == "New":
        pipeline.pop(username, None)
    else:
        pipeline[username] = {"stage": stage, "updated": time.strftime("%d %b %Y")}
    with open(PIPELINE_FILE, "w") as f:
        json.dump(pipeline, f, indent=2)

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

_PLACEHOLDER    = {"your_github_token_here", "your_openai_api_key_here", "", None}
GITHUB_TOKEN_OK = GITHUB_TOKEN not in _PLACEHOLDER
OPENAI_KEY_OK   = OPENAI_API_KEY not in _PLACEHOLDER

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
</style>
"""

# ─────────────────────────────────────────────
# GitHub API
# ─────────────────────────────────────────────
def search_users_direct(query, max_results=30):
    url = "https://api.github.com/search/users"
    params = {"q": query, "sort": "followers", "order": "desc", "per_page": min(max_results, 30)}
    r = requests.get(url, headers=HEADERS, params=params)
    if r.status_code == 200:
        return r.json().get("items", []), None
    try:
        msg = r.json().get("message", r.text)
    except Exception:
        msg = r.text
    return [], f"GitHub API error {r.status_code}: {msg}"

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

def get_user_languages(username):
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
# Batch AI Scorer
# ─────────────────────────────────────────────
def score_candidates_batch(candidates, role):
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

    prompt = (
        f"Score each developer 0.0-10.0 for fit as: {role}\n"
        "Criteria: language match, repo relevance, seniority signals, bio alignment.\n\n"
        + "\n".join(lines)
        + '\n\nReply ONLY with a JSON array in the same order:\n[{"i":0,"score":7.5,"reason":"one sentence max 12 words"},...]'
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max(200, len(candidates) * 35),
            temperature=0.2,
        )
        raw  = resp.choices[0].message.content.strip()
        data = json.loads(raw[raw.find("[") : raw.rfind("]") + 1])
        return {item["i"]: (round(float(item["score"]), 1), item.get("reason", "")) for item in data}, None
    except Exception as e:
        err = str(e)
        if "insufficient_quota" in err or "429" in err:
            return {}, "quota"
        return {}, err

# ─────────────────────────────────────────────
# Outreach Generator
# ─────────────────────────────────────────────
def generate_outreach(profile, role, repos):
    from openai import OpenAI
    client    = OpenAI(api_key=OPENAI_API_KEY)
    name      = profile.get("name") or profile.get("login")
    bio       = profile.get("bio") or "N/A"
    repo_names = ", ".join([r["name"] for r in repos[:3]]) if repos else "various open source projects"
    prompt = f"""You are a senior technical recruiter at a top-tier tech staffing agency.
Write a short, personalised cold outreach message to a developer you found on GitHub.
Developer profile:
- Name: {name}
- Bio: {bio}
- Notable repositories: {repo_names}
- Public repos: {profile.get("public_repos", 0)}
- Followers: {profile.get("followers", 0)}
Role we are hiring for: {role}
Instructions:
- Open by referencing ONE specific piece of their actual work
- Briefly describe the opportunity in 1 sentence
- Keep total message under 100 words
- Tone: warm, genuine, peer-to-peer
- End with a soft call to action
- Do NOT use placeholders like [Company Name]"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
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
def render_candidate(c, idx, role_query, pipeline):
    profile     = c["profile"]
    username    = profile["login"]
    user_repos  = c.get("user_repos", [])
    languages   = c.get("languages", [])
    score       = c.get("score")
    reason      = c.get("reason", "")
    contributor = c.get("contributor", {})
    stage       = pipeline.get(username, {}).get("stage", "New")

    with st.container():
        col_avatar, col_info, col_action = st.columns([1, 4, 2])

        with col_avatar:
            if profile.get("avatar_url"):
                st.image(profile["avatar_url"], width=72)
            st.markdown(score_badge(score), unsafe_allow_html=True)
            if reason:
                st.caption(reason)
            st.markdown(pipeline_badge(stage), unsafe_allow_html=True)

        with col_info:
            name      = profile.get("name") or username
            otw_badge = (
                ' <span style="background:#16a34a22;color:#4ade80;font-size:0.7rem;'
                'font-weight:700;padding:3px 8px;border-radius:20px;border:1px solid #16a34a66;'
                'vertical-align:middle;">🟢 OPEN TO WORK</span>'
                if profile.get("hireable") else ""
            )
            st.markdown(f"### [{name}](https://github.com/{username}){otw_badge}", unsafe_allow_html=True)
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
            # Pipeline selector
            current_idx = PIPELINE_STAGES.index(stage) if stage in PIPELINE_STAGES else 0
            new_stage   = st.selectbox("Pipeline", PIPELINE_STAGES, index=current_idx, key=f"pipe_{username}_{idx}")
            if new_stage != stage:
                update_pipeline(username, new_stage)
                st.rerun()

            # LinkedIn
            li_name = quote(profile.get("name") or username)
            st.markdown(
                f'<a href="https://www.linkedin.com/search/results/people/?keywords={li_name}" '
                f'target="_blank" style="display:block;text-align:center;padding:8px 12px;'
                f'background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.12);'
                f'border-radius:8px;color:#d0d0d0;text-decoration:none;font-size:0.85rem;'
                f'font-weight:600;margin-bottom:8px;">🔗 Search LinkedIn</a>',
                unsafe_allow_html=True,
            )

            # Outreach — st.code gives a built-in copy button
            if st.button("✉️ Generate Outreach", key=f"outreach_{username}_{idx}"):
                with st.spinner("Writing…"):
                    st.session_state[f"msg_{username}"] = generate_outreach(profile, role_query, user_repos)
            if f"msg_{username}" in st.session_state:
                st.code(st.session_state[f"msg_{username}"], language=None)

            # Notes
            existing_note = st.session_state["notes"].get(username, "")
            new_note = st.text_area("📝 Notes", value=existing_note, height=70,
                                    key=f"note_{username}_{idx}", placeholder="Private notes…")
            if st.button("💾 Save note", key=f"save_note_{username}_{idx}"):
                persist_note(username, new_note)
                st.session_state["notes"][username] = new_note
                st.toast("Note saved!", icon="📝")

    st.divider()

# ─────────────────────────────────────────────
# App Layout
# ─────────────────────────────────────────────
st.set_page_config(page_title="N5H", page_icon="🔍", layout="wide")
st.markdown(PREMIUM_CSS, unsafe_allow_html=True)
st.title("🔍 N5H")
st.caption("Open to work? EW")
st.divider()

if "notes" not in st.session_state:
    st.session_state["notes"] = load_notes()

# ── Sidebar ───────────────────────────────────
filter_langs     = []
filter_location  = ""
filter_min_score = 0.0
sort_by          = "Score"
filter_open_only = False
hide_archived    = False
hide_contacted   = False

with st.sidebar:
    st.markdown("### ⚙️ Status")
    if GITHUB_TOKEN_OK:
        st.success("✅ GitHub connected")
    else:
        st.error("❌ GitHub token missing")
    if OPENAI_KEY_OK:
        st.success("✅ OpenAI connected")
    else:
        st.error("❌ OpenAI key missing")
    st.divider()

    # Pipeline summary
    pipeline_data = load_pipeline()
    if pipeline_data:
        st.markdown("### 📊 Pipeline")
        stage_counts = {}
        for v in pipeline_data.values():
            s = v.get("stage", "New")
            stage_counts[s] = stage_counts.get(s, 0) + 1
        for s in PIPELINE_STAGES[1:]:
            count = stage_counts.get(s, 0)
            if count:
                colour, _ = STAGE_STYLE[s]
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;padding:4px 0;'
                    f'color:{colour};font-size:0.85rem;"><span>{s}</span><strong>{count}</strong></div>',
                    unsafe_allow_html=True,
                )
        st.divider()

    # Filters
    if "results" in st.session_state and st.session_state["results"]:
        st.markdown("### 🎛️ Filters")
        all_langs = sorted({l for c in st.session_state["results"] for l in c.get("languages", [])})
        filter_open_only = st.toggle("🟢 Open to work only",      value=False)
        hide_contacted   = st.toggle("👻 Hide already contacted", value=False)
        hide_archived    = st.toggle("🗂️ Hide archived",          value=True)
        filter_langs     = st.multiselect("Language", all_langs)
        filter_location  = st.text_input("Location contains", placeholder="e.g. London")
        has_scores = any(c["score"] is not None for c in st.session_state["results"])
        if has_scores:
            filter_min_score = st.slider("Min score", 0.0, 10.0, 0.0, 0.5)
        sort_by = st.selectbox("Sort by", ["Score", "Followers", "Contributions", "Account Age"])
        st.divider()

    # Saved searches
    saves = load_saved_searches()
    if saves:
        st.markdown("### 💾 Saved Searches")
        for s in saves[:5]:
            if st.button(
                f"**{s['role'][:28]}**\n{s['timestamp']} · {s['count']} candidates",
                key=f"load_{s['id']}", use_container_width=True,
            ):
                st.session_state["results"]     = s["candidates"]
                st.session_state["loaded_role"] = s["role"]
                st.rerun()
        st.divider()

    st.markdown("**How it works**")
    st.markdown("1. Set filters & describe the role")
    st.markdown("2. N5H finds developers on GitHub")
    st.markdown("3. AI scores all candidates in one batch")
    st.markdown("4. Track pipeline · save · export CSV")

# ── Search Mode ───────────────────────────────
search_mode = st.radio(
    "mode", ["👤 User Search", "📁 Repo Search"],
    horizontal=True, label_visibility="collapsed",
)
st.markdown("")

search_clicked    = False
role_query        = ""
max_candidates    = 10
sel_languages     = []
location_query    = ""
company_query     = ""
seniority         = "Any"
min_followers_val = 0

# ── User Search ───────────────────────────────
if search_mode == "👤 User Search":
    r1a, r1b = st.columns([4, 1])
    with r1a:
        role_query = st.text_input("Role / Keywords", placeholder='e.g. "machine learning" OR "full stack" OR "react"')
    with r1b:
        max_candidates = st.selectbox("Candidates", [10, 20, 30], index=0)

    r2a, r2b, r2c, r2d = st.columns([2, 2, 1, 1])
    with r2a:
        location_query = st.text_input("Location", placeholder="e.g. San Francisco")
    with r2b:
        company_query = st.text_input("Company", placeholder="e.g. Google")
    with r2c:
        seniority = st.selectbox("Seniority", list(SENIORITY_MAP.keys()))
    with r2d:
        min_followers_val = st.number_input("Min followers", min_value=0, value=0, step=50)
    sel_languages = []

    def build_user_query():
        parts = []
        if role_query.strip():
            parts.append(role_query.strip())
        if location_query.strip():
            loc = location_query.strip()
            # Quote multi-word locations for GitHub search
            if " " in loc:
                parts.append(f'location:"{loc}"')
            else:
                parts.append(f"location:{loc}")
        if SENIORITY_MAP[seniority]:
            parts.append(SENIORITY_MAP[seniority])
        elif min_followers_val > 0:
            parts.append(f"followers:>{min_followers_val}")
        parts.append("type:user")
        return " ".join(parts)

    preview = build_user_query()
    if preview.strip() != "type:user":
        st.caption(f"Query: `{preview}`")

    search_clicked = st.button("🔍 Find Candidates", type="primary", use_container_width=True)

    if search_clicked:
        if not GITHUB_TOKEN_OK or not OPENAI_KEY_OK:
            st.error("Missing API keys — add them to `~/n5h/.env`")
            st.stop()
        final_query = build_user_query()
        if final_query.strip() == "type:user":
            st.warning("Add at least one filter to search.")
            st.stop()

        with st.spinner("Searching GitHub users…"):
            users, api_err = search_users_direct(final_query, max_candidates)
        if api_err:
            st.error(api_err)
            st.stop()
        if not users:
            st.warning("No users found. Try broader filters.")
            st.stop()

        st.markdown(f"### Fetching {len(users)} profiles…")
        prog = st.progress(0)
        candidates = []
        company_matches = []
        for i, user in enumerate(users):
            username = user["login"]
            profile  = get_user_profile_cached(username)
            if not profile:
                prog.progress((i + 1) / len(users))
                continue
            user_repos = get_user_repos(username)
            languages  = get_user_languages(username)
            entry = {
                "contributor": {"contributions": 0, "login": username},
                "profile":     profile,
                "user_repos":  user_repos,
                "languages":   languages,
                "score":       None,
                "reason":      "",
            }
            candidates.append(entry)
            # Track company matches separately (soft filter)
            if company_query.strip():
                company = (profile.get("company") or "").lower().strip("@ ")
                if company_query.lower().strip() in company:
                    company_matches.append(entry)
            prog.progress((i + 1) / len(users))
            time.sleep(0.1)
        prog.empty()

        # If company filter was set and got matches, use those; otherwise show all
        if company_query.strip() and company_matches:
            candidates = company_matches
        elif company_query.strip() and not company_matches:
            st.info(f"ℹ️ No exact \"{company_query}\" matches — showing all {len(candidates)} candidates.")

        if not candidates:
            st.warning("No candidates after filtering. Try broader search.")
            st.stop()

        score_label = role_query or ", ".join(sel_languages) or "the role"
        st.markdown(f"### Scoring {len(candidates)} candidates in one batch…")
        scores, score_err = score_candidates_batch(candidates, score_label)
        if score_err == "quota":
            st.warning("⚠️ OpenAI quota exceeded — candidates shown unscored.")
        elif score_err:
            st.warning(f"Scoring issue: {score_err}")

        for i, c in enumerate(candidates):
            if i in scores:
                c["score"], c["reason"] = scores[i]

        candidates.sort(key=lambda x: (x["score"] is not None, x["score"] or 0), reverse=True)
        st.session_state["results"]     = candidates
        st.session_state["loaded_role"] = score_label

# ── Repo Search ───────────────────────────────
else:
    col1, col2 = st.columns([4, 1])
    with col1:
        role_query = st.text_input(
            "Describe the role",
            placeholder="e.g. Senior ML Engineer specialising in PyTorch and CUDA",
        )
    with col2:
        max_candidates = st.selectbox("Candidates", [10, 20, 30], index=0)

    search_clicked = st.button("🔍 Find Candidates", type="primary", use_container_width=True)

    if search_clicked:
        if not role_query:
            st.warning("Please enter a role description first.")
            st.stop()
        if not GITHUB_TOKEN_OK or not OPENAI_KEY_OK:
            st.error("Missing API keys — add them to `~/n5h/.env`")
            st.stop()

        with st.spinner("Searching GitHub for the most relevant repositories…"):
            repos, api_err = search_repos(role_query, max_repos=4)
        if api_err:
            st.error(api_err)
            st.stop()
        if not repos:
            st.error("No repositories found. Try a different search term.")
            st.stop()

        with st.expander(f"📁 {len(repos)} repositories analysed", expanded=False):
            for repo in repos:
                st.markdown(
                    f"**[{repo['full_name']}]({repo['html_url']})** "
                    f"⭐ {repo['stargazers_count']:,}  —  {(repo.get('description') or '')[:120]}"
                )

        st.markdown("### Finding top contributors…")
        prog = st.progress(0)
        all_contributors, seen = [], set()
        per_repo = max(5, max_candidates // len(repos) + 3)
        for i, repo in enumerate(repos):
            for c in get_contributors(repo["owner"]["login"], repo["name"], per_repo):
                if c.get("login") not in seen and c.get("type") == "User":
                    seen.add(c["login"])
                    all_contributors.append(c)
            prog.progress((i + 1) / len(repos))
            time.sleep(0.3)
        prog.empty()
        all_contributors = all_contributors[:max_candidates]

        if not all_contributors:
            st.warning("No contributors found.")
            st.stop()

        st.markdown("### Fetching profiles…")
        fetch_prog = st.progress(0)
        candidates = []
        for i, contributor in enumerate(all_contributors):
            username = contributor["login"]
            profile  = get_user_profile_cached(username)
            if not profile:
                fetch_prog.progress((i + 1) / len(all_contributors))
                continue
            user_repos = get_user_repos(username)
            languages  = get_user_languages(username)
            candidates.append({
                "contributor": contributor,
                "profile":     profile,
                "user_repos":  user_repos,
                "languages":   languages,
                "score":       None,
                "reason":      "",
            })
            fetch_prog.progress((i + 1) / len(all_contributors))
            time.sleep(0.15)
        fetch_prog.empty()

        st.markdown(f"### Scoring {len(candidates)} candidates in one batch…")
        scores, score_err = score_candidates_batch(candidates, role_query)
        if score_err == "quota":
            st.warning("⚠️ OpenAI quota exceeded — candidates shown unscored.")
        elif score_err:
            st.warning(f"Scoring issue: {score_err}")

        for i, c in enumerate(candidates):
            if i in scores:
                c["score"], c["reason"] = scores[i]

        candidates.sort(key=lambda x: (x["score"] is not None, x["score"] or 0), reverse=True)
        st.session_state["results"]     = candidates
        st.session_state["loaded_role"] = role_query

# ── Results ───────────────────────────────────
if "results" in st.session_state and st.session_state["results"]:
    role_query_active = st.session_state.get("loaded_role", "")
    scored_candidates = st.session_state["results"]
    pipeline          = load_pipeline()

    # Apply filters
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
        display = [c for c in display if filter_location.lower() in (c["profile"].get("location") or "").lower()]
    if filter_min_score > 0:
        display = [c for c in display if (c["score"] or 0) >= filter_min_score]

    # Sort
    if sort_by == "Followers":
        display = sorted(display, key=lambda c: c["profile"].get("followers", 0), reverse=True)
    elif sort_by == "Contributions":
        display = sorted(display, key=lambda c: c.get("contributor", {}).get("contributions", 0), reverse=True)
    elif sort_by == "Account Age":
        display = sorted(display, key=lambda c: account_age_days(c["profile"]), reverse=True)

    # Header
    res_col, save_col, csv_col = st.columns([3, 1, 1])
    with res_col:
        st.success(f"✅ **{len(display)} candidates** for: _{role_query_active}_")
    with save_col:
        if st.button("💾 Save Search", use_container_width=True):
            persist_search(role_query_active, scored_candidates)
            st.toast("Search saved!", icon="💾")
    with csv_col:
        st.download_button(
            label="⬇️ Export CSV",
            data=build_csv(display, role_query_active),
            file_name="n5h_candidates.csv",
            mime="text/csv",
            use_container_width=True,
        )
    st.divider()

    if not display:
        st.warning("No candidates match the current filters.")
    else:
        for idx, c in enumerate(display):
            render_candidate(c, idx, role_query_active, pipeline)
