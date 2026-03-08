import streamlit as st
import requests
import json
import csv
import io
import os
import time
from urllib.parse import quote
from dotenv import load_dotenv
load_dotenv()

# ─────────────────────────────────────────────
# Persistence helpers
# ─────────────────────────────────────────────
DATA_DIR   = os.path.expanduser("~/n5h/data")
NOTES_FILE = os.path.join(DATA_DIR, "notes.json")
SAVES_FILE = os.path.join(DATA_DIR, "saved_searches.json")
os.makedirs(DATA_DIR, exist_ok=True)

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

def load_saved_searches():
    if os.path.exists(SAVES_FILE):
        with open(SAVES_FILE) as f:
            return json.load(f)
    return []

def persist_search(role, candidates):
    saves = load_saved_searches()
    saves.insert(0, {
        "id": str(time.time()),
        "role": role,
        "timestamp": time.strftime("%d %b %Y %H:%M"),
        "count": len(candidates),
        "candidates": candidates,
    })
    saves = saves[:10]   # keep last 10
    with open(SAVES_FILE, "w") as f:
        json.dump(saves, f, indent=2)

# Read from Streamlit secrets (cloud) or .env (local)
def _secret(key):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key)

GITHUB_TOKEN = _secret("GITHUB_TOKEN")
OPENAI_API_KEY = _secret("OPENAI_API_KEY")

_PLACEHOLDER = {"your_github_token_here", "your_openai_api_key_here", "", None}
GITHUB_TOKEN_OK = GITHUB_TOKEN not in _PLACEHOLDER
OPENAI_KEY_OK = OPENAI_API_KEY not in _PLACEHOLDER

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# ─────────────────────────────────────────────
# Marble CSS
# ─────────────────────────────────────────────
PREMIUM_CSS = """
<style>
  /* ── Marble background ── */
  [data-testid="stAppViewContainer"] {
    background-color: #0c0c0c;
    background-image:
      repeating-linear-gradient(
        112deg,
        transparent 0px, transparent 38px,
        rgba(255,255,255,0.018) 38px, rgba(255,255,255,0.018) 39px,
        transparent 39px, transparent 78px,
        rgba(255,255,255,0.012) 78px, rgba(255,255,255,0.012) 79px
      ),
      repeating-linear-gradient(
        -22deg,
        transparent 0px, transparent 55px,
        rgba(255,255,255,0.014) 55px, rgba(255,255,255,0.014) 56px,
        transparent 56px, transparent 110px,
        rgba(255,255,255,0.009) 110px, rgba(255,255,255,0.009) 111px
      ),
      repeating-linear-gradient(
        67deg,
        transparent 0px, transparent 70px,
        rgba(255,255,255,0.01) 70px, rgba(255,255,255,0.01) 71px
      ),
      radial-gradient(ellipse at 20% 25%, rgba(255,255,255,0.04) 0%, transparent 50%),
      radial-gradient(ellipse at 80% 70%, rgba(255,255,255,0.03) 0%, transparent 45%),
      radial-gradient(ellipse at 55% 50%, rgba(255,255,255,0.015) 0%, transparent 60%),
      radial-gradient(ellipse at 10% 80%, rgba(255,255,255,0.025) 0%, transparent 35%),
      radial-gradient(ellipse at 90% 10%, rgba(255,255,255,0.02) 0%, transparent 40%);
  }

  [data-testid="stHeader"] { background: transparent; }

  /* ── Sidebar ── */
  [data-testid="stSidebar"] {
    background: rgba(10,10,10,0.85) !important;
    backdrop-filter: blur(12px);
    border-right: 1px solid rgba(255,255,255,0.07) !important;
  }

  /* ── Title ── */
  h1 {
    font-size: 2.8rem !important;
    font-weight: 800 !important;
    letter-spacing: -1px;
    background: linear-gradient(135deg, #ffffff 0%, #c0c0c0 60%, #888888 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  /* ── Tagline ── */
  [data-testid="stCaptionContainer"] p {
    color: #888 !important;
    font-size: 1rem !important;
    letter-spacing: 0.04em;
    font-style: italic;
  }

  /* ── Divider ── */
  hr {
    border-color: rgba(255,255,255,0.07) !important;
    margin: 1rem 0 !important;
  }

  /* ── Input ── */
  [data-testid="stTextInput"] input {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 10px !important;
    color: #e8e8e8 !important;
    font-size: 0.95rem !important;
    padding: 12px 16px !important;
    backdrop-filter: blur(8px);
  }
  [data-testid="stTextInput"] input:focus {
    border-color: rgba(255,255,255,0.35) !important;
    box-shadow: 0 0 0 3px rgba(255,255,255,0.06) !important;
  }

  /* ── Select ── */
  [data-testid="stSelectbox"] > div > div {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 10px !important;
    color: #e8e8e8 !important;
  }

  /* ── Primary button ── */
  [data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #2a2a2a, #111111) !important;
    border: 1px solid rgba(255,255,255,0.2) !important;
    border-radius: 10px !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    font-size: 1rem !important;
    letter-spacing: 0.05em !important;
    padding: 14px !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.1), 0 4px 12px rgba(0,0,0,0.4) !important;
    transition: all 0.2s !important;
  }
  [data-testid="stButton"] > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #3a3a3a, #1a1a1a) !important;
    border-color: rgba(255,255,255,0.35) !important;
    transform: translateY(-1px) !important;
  }

  /* ── Secondary buttons ── */
  [data-testid="stButton"] > button:not([kind="primary"]) {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 8px !important;
    color: #d0d0d0 !important;
    font-weight: 600 !important;
    transition: all 0.2s !important;
  }
  [data-testid="stButton"] > button:not([kind="primary"]):hover {
    background: rgba(255,255,255,0.1) !important;
    border-color: rgba(255,255,255,0.3) !important;
  }

  /* ── Candidate cards ── */
  [data-testid="stContainer"] > div {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 16px;
    padding: 20px !important;
    margin-bottom: 4px;
    backdrop-filter: blur(10px);
    transition: border-color 0.2s, background 0.2s;
  }
  [data-testid="stContainer"] > div:hover {
    background: rgba(255,255,255,0.05);
    border-color: rgba(255,255,255,0.15);
  }

  /* ── Candidate name links ── */
  [data-testid="stMarkdownContainer"] h3 a {
    color: #f0f0f0 !important;
    text-decoration: none !important;
    font-weight: 700;
  }
  [data-testid="stMarkdownContainer"] h3 a:hover {
    color: #ffffff !important;
    text-decoration: underline !important;
  }

  /* ── Metrics ── */
  [data-testid="stMetricLabel"] p {
    color: #666 !important;
    font-size: 0.7rem !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  [data-testid="stMetricValue"] {
    color: #e0e0e0 !important;
    font-size: 1.3rem !important;
    font-weight: 700 !important;
  }

  /* ── Language tags ── */
  code {
    background: rgba(255,255,255,0.07) !important;
    color: #c8c8c8 !important;
    border-radius: 5px !important;
    padding: 2px 7px !important;
    font-size: 0.8rem !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
  }

  /* ── Text area ── */
  textarea {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 8px !important;
    color: #e0e0e0 !important;
    font-size: 0.85rem !important;
  }

  /* ── Alerts ── */
  [data-testid="stAlert"] {
    border-radius: 10px !important;
    border: none !important;
  }

  /* ── Progress bar ── */
  [data-testid="stProgressBar"] > div {
    background: linear-gradient(90deg, #555, #aaa) !important;
    border-radius: 99px;
  }
  [data-testid="stProgressBar"] {
    background: rgba(255,255,255,0.08) !important;
    border-radius: 99px;
  }

  /* ── Expander ── */
  [data-testid="stExpander"] {
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 10px !important;
  }

  /* ── Avatar ── */
  [data-testid="stImage"] img {
    border-radius: 50% !important;
    border: 2px solid rgba(255,255,255,0.15) !important;
  }

  /* ── Download button ── */
  [data-testid="stDownloadButton"] > button {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 8px !important;
    color: #d0d0d0 !important;
    font-weight: 600 !important;
    width: 100%;
  }
  [data-testid="stDownloadButton"] > button:hover {
    background: rgba(255,255,255,0.09) !important;
    border-color: rgba(255,255,255,0.3) !important;
  }
</style>
"""

# ─────────────────────────────────────────────
# GitHub helpers
# ─────────────────────────────────────────────
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

def get_user_profile(username):
    r = requests.get(f"https://api.github.com/users/{username}", headers=HEADERS)
    if r.status_code == 200:
        return r.json()
    return None

def get_user_repos(username, max_repos=6):
    r = requests.get(
        f"https://api.github.com/users/{username}/repos",
        headers=HEADERS,
        params={"sort": "stars", "per_page": max_repos}
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
    sorted_langs = sorted(lang_count.items(), key=lambda x: x[1], reverse=True)
    return [l[0] for l in sorted_langs[:5]]

# ─────────────────────────────────────────────
# AI candidate scorer
# ─────────────────────────────────────────────
def score_candidate(profile, role, repos, languages):
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    name = profile.get("name") or profile.get("login")
    bio = profile.get("bio") or "N/A"
    repo_descriptions = "; ".join(
        [f"{r['name']}: {r.get('description') or 'no description'}" for r in repos[:5]]
    ) if repos else "N/A"
    langs = ", ".join(languages) if languages else "N/A"
    prompt = f"""You are a senior technical recruiter scoring a GitHub developer's fit for a role.

Role: {role}

Candidate:
- Name: {name}
- Bio: {bio}
- Languages: {langs}
- Top repos: {repo_descriptions}
- Public repos: {profile.get("public_repos", 0)}
- Followers: {profile.get("followers", 0)}

Score this candidate from 0.0 to 10.0 based on:
1. Language match
2. Repo relevance
3. Activity & seniority
4. Bio alignment

Respond ONLY with valid JSON:
{{"score": <number 0.0-10.0>, "reason": "<one sentence max 15 words>"}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80,
            temperature=0.2
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)
        return round(float(data["score"]), 1), data.get("reason", ""), None
    except Exception as e:
        err = str(e)
        if "insufficient_quota" in err or "429" in err:
            return None, "", "quota"
        return 5.0, "", None

# ─────────────────────────────────────────────
# AI outreach generator
# ─────────────────────────────────────────────
def generate_outreach(profile, role, repos):
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    name = profile.get("name") or profile.get("login")
    bio = profile.get("bio") or "N/A"
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
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200
    )
    return response.choices[0].message.content

# ─────────────────────────────────────────────
# Score badge
# ─────────────────────────────────────────────
def score_badge(score):
    if score is None:
        return (
            '<div style="display:inline-block;background:#1e1e2e;color:#4b5563;'
            'font-size:0.75rem;font-weight:600;padding:8px 14px;border-radius:12px;'
            'border:1px solid #2a2a3e;text-align:center;min-width:72px;">N/A</div>'
        )
    if score >= 7.0:
        colour, glow = "#22c55e", "rgba(34,197,94,0.2)"
    elif score >= 4.0:
        colour, glow = "#f59e0b", "rgba(245,158,11,0.2)"
    else:
        colour, glow = "#ef4444", "rgba(239,68,68,0.2)"
    return (
        f'<div style="'
        f'display:inline-block;'
        f'background:{colour}18;'
        f'color:{colour};'
        f'font-size:1.5rem;'
        f'font-weight:800;'
        f'padding:8px 16px;'
        f'border-radius:12px;'
        f'border:1px solid {colour}40;'
        f'box-shadow:0 0 16px {glow};'
        f'line-height:1;'
        f'text-align:center;'
        f'min-width:72px;'
        f'">{score}<br><span style="font-size:0.6rem;font-weight:500;opacity:0.7;letter-spacing:0.05em;">/ 10</span></div>'
    )

# ─────────────────────────────────────────────
# CSV export
# ─────────────────────────────────────────────
def build_csv(scored_candidates, role):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Rank", "Name", "GitHub", "Score", "Score Reason",
        "Bio", "Location", "Company", "Languages",
        "Public Repos", "Followers", "Contributions", "Top Repos", "Role Searched"
    ])
    for rank, c in enumerate(scored_candidates, 1):
        p = c["profile"]
        writer.writerow([
            rank,
            p.get("name") or p.get("login"),
            f"https://github.com/{p['login']}",
            c["score"] if c["score"] is not None else "N/A",
            c["reason"],
            (p.get("bio") or "").replace("\n", " "),
            p.get("location") or "",
            (p.get("company") or "").strip("@"),
            ", ".join(c["languages"]),
            p.get("public_repos", 0),
            p.get("followers", 0),
            c["contributor"].get("contributions", 0),
            ", ".join([r["name"] for r in c["user_repos"][:3]]),
            role,
        ])
    return output.getvalue().encode("utf-8")

# ─────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────
st.set_page_config(page_title="N5H", page_icon="🔍", layout="wide")
st.markdown(PREMIUM_CSS, unsafe_allow_html=True)

st.title("🔍 N5H")
st.caption("Find your next hire before they start looking.")
st.divider()

# Load persistent data once
if "notes" not in st.session_state:
    st.session_state["notes"] = load_notes()

# Filter defaults (overridden by sidebar widgets when results exist)
filter_langs      = []
filter_location   = ""
filter_min_score  = 0.0
sort_by           = "Score"

with st.sidebar:
    st.markdown("### ⚙️ Status")
    if GITHUB_TOKEN_OK:
        st.success("✅ GitHub connected")
    else:
        st.error("❌ GitHub token missing\n`~/n5h/.env`")
    if OPENAI_KEY_OK:
        st.success("✅ OpenAI connected")
    else:
        st.error("❌ OpenAI key missing\n`~/n5h/.env`")
    st.divider()

    # ── Filters (only after a search) ────────
    if "results" in st.session_state and st.session_state["results"]:
        st.markdown("### 🎛️ Filters")
        all_langs = sorted({
            l for c in st.session_state["results"]
            for l in c.get("languages", [])
        })
        filter_langs = st.multiselect("Language", all_langs)
        filter_location = st.text_input("Location contains", placeholder="e.g. London")
        has_scores = any(c["score"] is not None for c in st.session_state["results"])
        if has_scores:
            filter_min_score = st.slider("Min score", 0.0, 10.0, 0.0, 0.5)
        else:
            filter_min_score = 0.0
        sort_by = st.selectbox("Sort by", ["Score", "Followers", "Contributions"])
        st.divider()

    # ── Saved searches ────────────────────────
    saves = load_saved_searches()
    if saves:
        st.markdown("### 💾 Saved Searches")
        for s in saves[:5]:
            if st.button(f"**{s['role'][:28]}**\n{s['timestamp']} · {s['count']} candidates",
                         key=f"load_{s['id']}", use_container_width=True):
                st.session_state["results"] = s["candidates"]
                st.session_state["loaded_role"] = s["role"]
                st.rerun()
        st.divider()

    st.markdown("**How it works**")
    st.markdown("1. Describe the role")
    st.markdown("2. N5H finds contributors from top GitHub repos")
    st.markdown("3. AI scores & ranks every candidate for fit")
    st.markdown("4. Save, filter, export to CSV")

# Search
col1, col2 = st.columns([4, 1])
with col1:
    role_query = st.text_input(
        "Describe the role",
        placeholder="e.g.  Senior ML Engineer specialising in PyTorch and CUDA"
    )
with col2:
    max_candidates = st.selectbox("Candidates", [10, 20, 30], index=0)

search_clicked = st.button("🔍 Find Candidates", type="primary", use_container_width=True)

# ─────────────────────────────────────────────
# Search & results
# ─────────────────────────────────────────────
if search_clicked:
    if not role_query:
        st.warning("Please enter a role description first.")
        st.stop()
    if not GITHUB_TOKEN_OK or not OPENAI_KEY_OK:
        st.error("Missing API keys — add your real keys to `~/n5h/.env` and restart the app.")
        st.stop()

    with st.spinner("Searching GitHub for the most relevant repositories…"):
        repos, api_err = search_repos(role_query, max_repos=4)

    if api_err:
        st.error(api_err)
        if "401" in api_err:
            st.info("💡 GitHub token invalid or expired — generate a new one at github.com/settings/tokens")
        elif "403" in api_err:
            st.info("💡 GitHub rate limit hit — add a valid token to `~/n5h/.env`")
        st.stop()
    if not repos:
        st.error("No repositories found. Try a different or broader search term.")
        st.stop()

    with st.expander(f"📁 {len(repos)} repositories analysed", expanded=False):
        for repo in repos:
            st.markdown(
                f"**[{repo['full_name']}]({repo['html_url']})** "
                f"⭐ {repo['stargazers_count']:,}  —  {(repo.get('description') or '')[:120]}"
            )

    st.markdown("### Finding top contributors…")
    progress = st.progress(0)
    all_contributors = []
    seen = set()
    per_repo = max(5, max_candidates // len(repos) + 3)
    for i, repo in enumerate(repos):
        contributors = get_contributors(repo["owner"]["login"], repo["name"], per_repo)
        for c in contributors:
            if c.get("login") not in seen and c.get("type") == "User":
                seen.add(c["login"])
                all_contributors.append(c)
        progress.progress((i + 1) / len(repos))
        time.sleep(0.4)
    progress.empty()
    all_contributors = all_contributors[:max_candidates]

    if not all_contributors:
        st.warning("No contributors found. Try a different search.")
        st.stop()

    # Score all candidates
    st.markdown("### Scoring with AI…")
    score_progress = st.progress(0)
    scored_candidates = []
    quota_exceeded = False

    for i, contributor in enumerate(all_contributors):
        username = contributor["login"]
        profile = get_user_profile(username)
        if not profile:
            score_progress.progress((i + 1) / len(all_contributors))
            continue
        user_repos = get_user_repos(username)
        languages = get_user_languages(username)

        if quota_exceeded:
            score, reason = None, ""
        else:
            score, reason, err = score_candidate(profile, role_query, user_repos, languages)
            if err == "quota":
                quota_exceeded = True
                score, reason = None, ""

        scored_candidates.append({
            "contributor": contributor,
            "profile": profile,
            "user_repos": user_repos,
            "languages": languages,
            "score": score,
            "reason": reason,
        })
        score_progress.progress((i + 1) / len(all_contributors))
        time.sleep(0.2)

    score_progress.empty()

    if quota_exceeded:
        st.warning("⚠️ OpenAI quota exceeded — candidates shown unscored. Add credits at **platform.openai.com/settings/billing** to enable AI scoring.")

    # Sort scored ones first, then unscored
    scored_candidates.sort(key=lambda x: (x["score"] is not None, x["score"] or 0), reverse=True)

    # Persist results in session state
    st.session_state["results"] = scored_candidates
    st.session_state["loaded_role"] = role_query

    # Results header + actions
    res_col, save_col, csv_col = st.columns([3, 1, 1])
    with res_col:
        st.success(f"✅ **{len(scored_candidates)} candidates** scored and ranked")
    with save_col:
        if st.button("💾 Save Search", use_container_width=True):
            persist_search(role_query, scored_candidates)
            st.toast("Search saved!", icon="💾")
    with csv_col:
        csv_data = build_csv(scored_candidates, role_query)
        st.download_button(
            label="⬇️ Export CSV",
            data=csv_data,
            file_name="n5h_candidates.csv",
            mime="text/csv",
            use_container_width=True
        )
    st.divider()

    # Apply filters & sort
    display = scored_candidates
    if filter_langs:
        display = [c for c in display if any(l in c.get("languages", []) for l in filter_langs)]
    if filter_location:
        display = [c for c in display
                   if filter_location.lower() in (c["profile"].get("location") or "").lower()]
    if filter_min_score > 0:
        display = [c for c in display if (c["score"] or 0) >= filter_min_score]
    if sort_by == "Followers":
        display = sorted(display, key=lambda c: c["profile"].get("followers", 0), reverse=True)
    elif sort_by == "Contributions":
        display = sorted(display, key=lambda c: c["contributor"].get("contributions", 0), reverse=True)

    if not display:
        st.warning("No candidates match the current filters.")
        st.stop()

    # Render candidates
    for idx, c in enumerate(display):
        profile = c["profile"]
        username = profile["login"]
        user_repos = c["user_repos"]
        languages = c["languages"]
        score = c["score"]
        reason = c["reason"]
        contributor = c["contributor"]

        with st.container():
            col_avatar, col_info, col_action = st.columns([1, 4, 2])

            with col_avatar:
                if profile.get("avatar_url"):
                    st.image(profile["avatar_url"], width=72)
                st.markdown(score_badge(score), unsafe_allow_html=True)
                if reason:
                    st.caption(reason)

            with col_info:
                name = profile.get("name") or username
                st.markdown(f"### [{name}](https://github.com/{username})")
                if profile.get("bio"):
                    st.caption(profile["bio"])
                s1, s2, s3 = st.columns(3)
                s1.metric("Repos", profile.get("public_repos", 0))
                s2.metric("Followers", profile.get("followers", 0))
                s3.metric("Contributions", contributor.get("contributions", 0))
                meta = []
                if profile.get("location"):
                    meta.append(f"📍 {profile['location']}")
                if profile.get("company"):
                    meta.append(f"🏢 {profile['company'].strip('@')}")
                if meta:
                    st.caption("  ·  ".join(meta))
                # Contact & social links
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
                # LinkedIn search link
                li_name = quote(profile.get("name") or username)
                st.markdown(
                    f'<a href="https://www.linkedin.com/search/results/people/?keywords={li_name}" '
                    f'target="_blank" style="display:block;text-align:center;padding:8px 12px;'
                    f'background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.12);'
                    f'border-radius:8px;color:#d0d0d0;text-decoration:none;font-size:0.85rem;'
                    f'font-weight:600;margin-bottom:8px;">🔗 Search LinkedIn</a>',
                    unsafe_allow_html=True
                )
                # Outreach
                role_query_active = st.session_state.get("loaded_role", "")
                btn_key = f"outreach_{username}_{idx}"
                if st.button("✉️ Generate Outreach", key=btn_key):
                    with st.spinner("Writing message…"):
                        message = generate_outreach(profile, role_query_active, user_repos)
                        st.session_state[f"msg_{username}"] = message
                if f"msg_{username}" in st.session_state:
                    st.text_area(
                        "Copy & send:",
                        value=st.session_state[f"msg_{username}"],
                        height=120,
                        key=f"ta_{username}_{idx}"
                    )
                # Notes
                existing_note = st.session_state["notes"].get(username, "")
                new_note = st.text_area(
                    "📝 Notes",
                    value=existing_note,
                    height=80,
                    key=f"note_input_{username}_{idx}",
                    placeholder="Add private notes…"
                )
                if st.button("💾 Save note", key=f"save_note_{username}_{idx}"):
                    persist_note(username, new_note)
                    st.session_state["notes"][username] = new_note
                    st.toast("Note saved!", icon="📝")
        st.divider()

# ── Show results from a loaded saved search ──
if not search_clicked and "results" in st.session_state and st.session_state["results"]:
    role_query = st.session_state.get("loaded_role", "")
    scored_candidates = st.session_state["results"]

    display = scored_candidates
    if filter_langs:
        display = [c for c in display if any(l in c.get("languages", []) for l in filter_langs)]
    if filter_location:
        display = [c for c in display
                   if filter_location.lower() in (c["profile"].get("location") or "").lower()]
    if filter_min_score > 0:
        display = [c for c in display if (c["score"] or 0) >= filter_min_score]
    if sort_by == "Followers":
        display = sorted(display, key=lambda c: c["profile"].get("followers", 0), reverse=True)
    elif sort_by == "Contributions":
        display = sorted(display, key=lambda c: c["contributor"].get("contributions", 0), reverse=True)

    res_col, save_col, csv_col = st.columns([3, 1, 1])
    with res_col:
        st.success(f"✅ **{len(display)} candidates** for: _{role_query}_")
    with save_col:
        if st.button("💾 Save Search", key="save_loaded", use_container_width=True):
            persist_search(role_query, scored_candidates)
            st.toast("Search saved!", icon="💾")
    with csv_col:
        csv_data = build_csv(display, role_query)
        st.download_button(
            label="⬇️ Export CSV",
            data=csv_data,
            file_name="n5h_candidates.csv",
            mime="text/csv",
            use_container_width=True,
            key="csv_loaded"
        )
    st.divider()

    for idx, c in enumerate(display):
        profile = c["profile"]
        username = profile["login"]
        user_repos = c["user_repos"]
        languages  = c["languages"]
        score      = c["score"]
        reason     = c["reason"]
        contributor = c["contributor"]

        with st.container():
            col_avatar, col_info, col_action = st.columns([1, 4, 2])
            with col_avatar:
                if profile.get("avatar_url"):
                    st.image(profile["avatar_url"], width=72)
                st.markdown(score_badge(score), unsafe_allow_html=True)
                if reason:
                    st.caption(reason)
            with col_info:
                name = profile.get("name") or username
                st.markdown(f"### [{name}](https://github.com/{username})")
                if profile.get("bio"):
                    st.caption(profile["bio"])
                s1, s2, s3 = st.columns(3)
                s1.metric("Repos", profile.get("public_repos", 0))
                s2.metric("Followers", profile.get("followers", 0))
                s3.metric("Contributions", contributor.get("contributions", 0))
                meta = []
                if profile.get("location"):
                    meta.append(f"📍 {profile['location']}")
                if profile.get("company"):
                    meta.append(f"🏢 {profile['company'].strip('@')}")
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
                li_name = quote(profile.get("name") or username)
                st.markdown(
                    f'<a href="https://www.linkedin.com/search/results/people/?keywords={li_name}" '
                    f'target="_blank" style="display:block;text-align:center;padding:8px 12px;'
                    f'background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.12);'
                    f'border-radius:8px;color:#d0d0d0;text-decoration:none;font-size:0.85rem;'
                    f'font-weight:600;margin-bottom:8px;">🔗 Search LinkedIn</a>',
                    unsafe_allow_html=True
                )
                btn_key = f"outreach_l_{username}_{idx}"
                if st.button("✉️ Generate Outreach", key=btn_key):
                    with st.spinner("Writing message…"):
                        message = generate_outreach(profile, role_query, user_repos)
                        st.session_state[f"msg_{username}"] = message
                if f"msg_{username}" in st.session_state:
                    st.text_area(
                        "Copy & send:",
                        value=st.session_state[f"msg_{username}"],
                        height=120,
                        key=f"ta_l_{username}_{idx}"
                    )
                existing_note = st.session_state["notes"].get(username, "")
                new_note = st.text_area(
                    "📝 Notes",
                    value=existing_note,
                    height=80,
                    key=f"note_l_{username}_{idx}",
                    placeholder="Add private notes…"
                )
                if st.button("💾 Save note", key=f"save_note_l_{username}_{idx}"):
                    persist_note(username, new_note)
                    st.session_state["notes"][username] = new_note
                    st.toast("Note saved!", icon="📝")
        st.divider()
