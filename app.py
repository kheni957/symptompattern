
#HealthWatch — Patient Signal Monitor
#Full implementation: DB layer, fetch engines (Reddit + Mock), AI analysis (Claude + heuristics)

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import requests
import sqlite3
import json
import re
import time
import os
import random
from datetime import datetime, timedelta
from io import BytesIO
from collections import Counter
from abc import ABC, abstractmethod
streastreamlit 
# ===========================================================
# CONFIG
# ===========================================================

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "healthwatch.db")

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-4-20250514"

# Keywords that trigger heuristic safety / PII flags
SAFETY_KEYWORDS = [
    "hospitalized", "hospitalised", "ER", "emergency", "overdose",
    "suicide", "suicidal", "self-harm", "died", "death", "fatal",
    "anaphylaxis", "seizure", "stroke", "heart attack", "chest pain",
    "stopped breathing", "unconscious", "allergic reaction",
]
PII_PATTERNS = [
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",   # email
    r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",                        # phone
    r"\b\d{3}-\d{2}-\d{4}\b",                                     # SSN
    r"\b(?:my name is|I am|I'm)\s+[A-Z][a-z]+ [A-Z][a-z]+",      # name disclosure
]

# ===========================================================
# DATABASE LAYER
# ===========================================================

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                keywords    TEXT DEFAULT '[]',   -- JSON array
                sources     TEXT DEFAULT '[]',   -- JSON array
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS signals (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id    INTEGER NOT NULL REFERENCES projects(id),
                source        TEXT,
                post_id       TEXT,
                author        TEXT,
                title         TEXT,
                body          TEXT,
                url           TEXT,
                fetched_at    TEXT DEFAULT (datetime('now')),

                -- Analysis fields
                sentiment     TEXT,   -- Positive / Negative / Neutral
                risk_level    TEXT,   -- High / Medium / Low
                safety_flag   INTEGER DEFAULT 0,   -- 1 = flagged
                pii_flagged   INTEGER DEFAULT 0,   -- 1 = flagged
                adverse_event TEXT,   -- extracted AE description
                topics        TEXT,   -- JSON array of topic tags
                summary       TEXT,
                analyzed_by   TEXT    -- 'claude' or 'heuristic'
            );

            CREATE TABLE IF NOT EXISTS source_engines (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                name   TEXT UNIQUE NOT NULL,
                config TEXT DEFAULT '{}'   -- JSON config blob
            );

            -- Seed default engines if table is empty
            INSERT OR IGNORE INTO source_engines (name, config) VALUES
                ('Reddit', '{"base_url": "https://www.reddit.com/search.json", "limit": 25}'),
                ('Mock',   '{"posts_per_keyword": 5}');
        """)


def get_projects() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_project(project_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return dict(row) if row else None


def create_project(name: str, description: str, keywords: list[str], sources: list[str]) -> int:
    if not name.strip():
        raise ValueError("Project name cannot be empty.")
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM projects WHERE name=?", (name.strip(),)
        ).fetchone()
        if existing:
            raise ValueError(f"A project named '{name.strip()}' already exists. Choose a different name.")
        cur = conn.execute(
            "INSERT INTO projects (name, description, keywords, sources) VALUES (?,?,?,?)",
            (name.strip(), description, json.dumps(keywords), json.dumps(sources)),
        )
        return cur.lastrowid


def delete_project(project_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM signals  WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id=?",         (project_id,))


def get_signals(project_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE project_id=? ORDER BY fetched_at DESC",
            (project_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_signals(project_id: int, signals: list[dict]):
    """Upsert signals by (project_id, post_id, source)."""
    with get_conn() as conn:
        for s in signals:
            conn.execute("""
                INSERT INTO signals
                    (project_id, source, post_id, author, title, body, url,
                     sentiment, risk_level, safety_flag, pii_flagged,
                     adverse_event, topics, summary, analyzed_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT DO NOTHING
            """, (
                project_id,
                s.get("source"),
                s.get("post_id"),
                s.get("author"),
                s.get("title"),
                s.get("body"),
                s.get("url"),
                s.get("sentiment"),
                s.get("risk_level"),
                int(s.get("safety_flag", 0)),
                int(s.get("pii_flagged", 0)),
                s.get("adverse_event"),
                json.dumps(s.get("topics", [])),
                s.get("summary"),
                s.get("analyzed_by"),
            ))


def get_source_engines() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM source_engines").fetchall()
    return [dict(r) for r in rows]


# ===========================================================
# FETCH ENGINES
# ===========================================================

class BaseEngine(ABC):
    """Abstract base class for all data-source engines."""

    @abstractmethod
    def fetch(self, keywords: list[str]) -> list[dict]:
        """Return a list of raw post dicts."""
        ...


class RedditEngine(BaseEngine):
    """
    Fetches posts from Reddit using the public search JSON endpoint.
    No API key required — uses Reddit's unauthenticated search endpoint.
    Rate-limited: sleeps 1 s between keyword queries.
    """

    BASE_URL = "https://www.reddit.com/search.json"
    HEADERS  = {"User-Agent": "HealthWatch/1.0 (patient-signal-monitor)"}

    def __init__(self, limit: int = 25):
        self.limit = limit

    def fetch(self, keywords: list[str]) -> list[dict]:
        posts = []
        for kw in keywords:
            try:
                params = {
                    "q":     kw,
                    "sort":  "new",
                    "limit": self.limit,
                    "type":  "link",
                }
                resp = requests.get(
                    self.BASE_URL,
                    params=params,
                    headers=self.HEADERS,
                    timeout=10,
                )
                resp.raise_for_status()
                children = resp.json().get("data", {}).get("children", [])
                for child in children:
                    d = child.get("data", {})
                    posts.append({
                        "source":  "Reddit",
                        "post_id": d.get("id", ""),
                        "author":  d.get("author", "[deleted]"),
                        "title":   d.get("title", ""),
                        "body":    d.get("selftext", ""),
                        "url":     f"https://reddit.com{d.get('permalink', '')}",
                        "subreddit": d.get("subreddit", ""),
                        "score":   d.get("score", 0),
                    })
                time.sleep(1)   # be polite to Reddit
            except Exception as exc:
                st.warning(f"Reddit fetch failed for '{kw}': {exc}")
        return posts


class MockEngine(BaseEngine):
    """
    Generates realistic-looking synthetic posts for demo / offline use.
    Useful when you don't want to hit any real APIs.
    """

    TEMPLATES = [
        "Has anyone else experienced {symptom} after taking {drug}? It's been {days} days.",
        "My doctor prescribed {drug} last week and now I have {symptom}. Should I be worried?",
        "Sharing my experience with {drug} — {symptom} started on day {days}.",
        "Warning: {drug} gave me terrible {symptom}. Ended up in the ER.",
        "Anyone on {drug} notice {symptom}? Looking for advice.",
        "Week {days} on {drug}: feeling great, no issues at all.",
        "Finally {drug} is working for me! No {symptom} this time.",
        "Switched from {drug} to a generic — {symptom} is much better now.",
    ]
    DRUGS    = ["metformin","atorvastatin","lisinopril","omeprazole","ibuprofen",
                "sertraline","amoxicillin","levothyroxine","prednisone","gabapentin"]
    SYMPTOMS = ["nausea","fatigue","headache","dizziness","rash","joint pain",
                "insomnia","dry mouth","weight gain","shortness of breath"]

    def __init__(self, posts_per_keyword: int = 5):
        self.ppk = posts_per_keyword

    def fetch(self, keywords: list[str]) -> list[dict]:
        posts = []
        for kw in keywords:
            for i in range(self.ppk):
                body = random.choice(self.TEMPLATES).format(
                    drug=random.choice(self.DRUGS),
                    symptom=random.choice(self.SYMPTOMS),
                    days=random.randint(1, 30),
                )
                posts.append({
                    "source":  "Mock",
                    "post_id": f"mock_{kw}_{i}_{random.randint(1000,9999)}",
                    "author":  f"user_{random.randint(100,999)}",
                    "title":   f"[{kw}] {body[:60]}",
                    "body":    body,
                    "url":     "",
                })
        return posts


def get_engine(source_name: str) -> BaseEngine:
    """Factory: return the correct engine for a source name."""
    engines = {
        "Reddit": RedditEngine(limit=25),
        "Mock":   MockEngine(posts_per_keyword=5),
    }
    engine = engines.get(source_name)
    if engine is None:
        raise ValueError(f"Unknown source engine: '{source_name}'")
    return engine


# ===========================================================
# ANALYSIS — HEURISTICS
# ===========================================================

def heuristic_analyze(post: dict) -> dict:
    """
    Fast rule-based analysis.  Used as a fallback when Claude is unavailable
    and as a pre-filter before calling the API.
    """
    text = f"{post.get('title','')} {post.get('body','')}".lower()

    # Safety flag
    safety_flag = any(kw.lower() in text for kw in SAFETY_KEYWORDS)

    # PII flag
    full_text   = f"{post.get('title','')} {post.get('body','')}"
    pii_flagged = any(re.search(pat, full_text, re.IGNORECASE) for pat in PII_PATTERNS)

    # Sentiment (very simple positive/negative word count)
    pos_words = ["better","improved","great","good","helped","relief","works","effective","love"]
    neg_words = ["worse","terrible","awful","pain","side effect","stopped","dangerous","horrible","sick"]
    pos = sum(1 for w in pos_words if w in text)
    neg = sum(1 for w in neg_words if w in text)
    if neg > pos:
        sentiment = "Negative"
    elif pos > neg:
        sentiment = "Positive"
    else:
        sentiment = "Neutral"

    # Risk level
    if safety_flag or neg >= 3:
        risk_level = "High"
    elif neg >= 1 or pii_flagged:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    # Topic tags
    topics = []
    topic_map = {
        "side effect":   ["side effect","adverse","reaction"],
        "dosage":        ["dose","dosage","mg","milligram","how much"],
        "efficacy":      ["works","effective","helped","relief","better"],
        "discontinuation":["stopped","quit","discontinued","switched"],
        "safety":        SAFETY_KEYWORDS,
    }
    for tag, kws in topic_map.items():
        if any(k.lower() in text for k in kws):
            topics.append(tag)

    # Adverse event extraction (naive)
    ae_match = re.search(
        r"(experienced?|developed?|noticed?|got|having?)\s+([\w\s]{3,40})",
        text, re.IGNORECASE
    )
    adverse_event = ae_match.group(2).strip().title() if ae_match else ""

    return {
        **post,
        "sentiment":    sentiment,
        "risk_level":   risk_level,
        "safety_flag":  safety_flag,
        "pii_flagged":  pii_flagged,
        "topics":       topics,
        "adverse_event": adverse_event,
        "summary":      (post.get("body") or post.get("title") or "")[:200],
        "analyzed_by":  "heuristic",
    }


# ===========================================================
# ANALYSIS — CLAUDE API
# ===========================================================

ANALYSIS_SYSTEM_PROMPT = """You are a pharmacovigilance analyst. Analyze the social media post below and return ONLY valid JSON (no markdown, no explanation) with these exact keys:

{
  "sentiment":     "Positive" | "Negative" | "Neutral",
  "risk_level":    "High" | "Medium" | "Low",
  "safety_flag":   true | false,
  "pii_flagged":   true | false,
  "adverse_event": "<brief description or empty string>",
  "topics":        ["<tag>", ...],
  "summary":       "<1-sentence neutral summary>"
}

Rules:
- safety_flag = true if the post describes a serious/life-threatening event, hospitalisation, or suicidal ideation
- pii_flagged = true if the post contains an email, phone number, full name, or other identifying info
- risk_level High = serious AE or safety flag; Medium = non-serious AE or symptom report; Low = general discussion
- topics may include: side effect, efficacy, dosage, discontinuation, safety, mental health, drug interaction
"""


def claude_analyze(post: dict, api_key: str) -> dict:
    """
    Call the Claude API to analyze a post.
    Returns enriched post dict, or falls back to heuristics on error.
    """
    text = f"Title: {post.get('title','')}\n\nBody: {post.get('body','')}"
    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 512,
        "system":     ANALYSIS_SYSTEM_PROMPT,
        "messages":   [{"role": "user", "content": text}],
    }
    headers = {
        "x-api-key":         api_key,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    try:
        resp = requests.post(CLAUDE_API_URL, json=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
        # Strip markdown fences if present
        raw = re.sub(r"^```json\s*|```$", "", raw, flags=re.MULTILINE).strip()
        result = json.loads(raw)
        return {
            **post,
            "sentiment":    result.get("sentiment", "Neutral"),
            "risk_level":   result.get("risk_level", "Low"),
            "safety_flag":  bool(result.get("safety_flag", False)),
            "pii_flagged":  bool(result.get("pii_flagged", False)),
            "adverse_event": result.get("adverse_event", ""),
            "topics":       result.get("topics", []),
            "summary":      result.get("summary", ""),
            "analyzed_by":  "claude",
        }
    except Exception as exc:
        st.warning(f"Claude analysis failed ({exc}), falling back to heuristics.")
        return heuristic_analyze(post)


def analyze_batch(posts: list[dict], api_key: str | None = None) -> list[dict]:
    """
    Analyze a batch of posts.
    Uses Claude if api_key provided, heuristics otherwise.
    Shows a progress bar in the Streamlit UI.
    """
    results = []
    bar = st.progress(0, text="Analysing posts…")
    n   = len(posts)
    for i, post in enumerate(posts):
        if api_key:
            results.append(claude_analyze(post, api_key))
            time.sleep(0.3)   # gentle rate limiting
        else:
            results.append(heuristic_analyze(post))
        bar.progress((i + 1) / max(n, 1), text=f"Analysing {i+1}/{n}")
    bar.empty()
    return results


# ===========================================================
# APP UI
# ===========================================================

init_db()
st.set_page_config(page_title="HealthWatch", layout="wide", page_icon="🏥")

st.markdown("""<style>
.safety-flag{background:#ff000022;border-left:4px solid red;padding:8px;border-radius:4px;margin:4px 0}
.pii-flag{background:#ff990022;border-left:4px solid orange;padding:8px;border-radius:4px;margin:4px 0}
</style>""", unsafe_allow_html=True)

st.sidebar.image("https://img.icons8.com/color/96/stethoscope.png", width=60)
st.sidebar.title("HealthWatch")
st.sidebar.markdown("*Real-Time Patient Signal Monitor*")
st.sidebar.markdown("---")

# Optional Claude API key in sidebar
with st.sidebar.expander("🔑 Claude API Key (optional)"):
    api_key_input = st.text_input(
        "Anthropic API Key",
        type="password",
        placeholder="sk-ant-…",
        help="Leave blank to use heuristic-only analysis.",
    )
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigate",
    ["🏠 Dashboard", "📁 Projects", "🔍 Run Analysis", "📊 Signals & Trends", "⚙️ Admin"],
)

# ── DASHBOARD ───────────────────────────────────────────────
if page == "🏠 Dashboard":
    st.title("🏥 HealthWatch — Patient Signal Monitor")
    st.markdown("Real-time social listening for adverse events, treatment signals & patient safety.")

    projects = get_projects()
    if not projects:
        st.info("👈 Create your first project in **📁 Projects** to get started.")
    else:
        all_signals = []
        for p in projects:
            all_signals.extend(get_signals(p["id"]))

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("📁 Projects",    len(projects))
        c2.metric("📨 Total Signals", len(all_signals))
        c3.metric("🔴 High Risk",   sum(1 for s in all_signals if s.get("risk_level") == "High"))
        c4.metric("⚠️ Safety Flags", sum(1 for s in all_signals if s.get("safety_flag") == 1))
        c5.metric("🔒 PII",          sum(1 for s in all_signals if s.get("pii_flagged") == 1))

        if all_signals:
            st.markdown("---")
            st.subheader("Recent High-Risk Signals")
            high_risk = [s for s in all_signals if s.get("risk_level") == "High"][:10]
            for s in high_risk:
                with st.expander(f"🔴 {s.get('title','(no title)')[:80]}"):
                    st.write(s.get("summary") or s.get("body","")[:300])
                    cols = st.columns(4)
                    cols[0].write(f"**Source:** {s.get('source')}")
                    cols[1].write(f"**Sentiment:** {s.get('sentiment')}")
                    cols[2].write(f"**AE:** {s.get('adverse_event') or '—'}")
                    cols[3].write(f"**By:** {s.get('analyzed_by')}")
                    if s.get("url"):
                        st.markdown(f"[View original post]({s['url']})")


# ── PROJECTS ────────────────────────────────────────────────
elif page == "📁 Projects":
    st.title("📁 Project Management")
    available_sources = [e["name"] for e in get_source_engines()]

    with st.form("create_project_form"):
        st.subheader("Create New Project")
        name         = st.text_input("Project Name *")
        description  = st.text_area("Description", height=80)
        keywords_raw = st.text_input("Keywords * (comma-separated)", placeholder="metformin, diabetes, side effects")
        sources      = st.multiselect("Data Sources", available_sources, default=["Mock"])
        submitted    = st.form_submit_button("➕ Create Project")
        if submitted:
            if not name.strip():
                st.error("Project name is required.")
            elif not keywords_raw.strip():
                st.error("At least one keyword is required.")
            else:
                kws = [k.strip() for k in keywords_raw.split(",") if k.strip()]
                try:
                    pid = create_project(name, description, kws, sources)
                    st.success(f"✅ Project **{name}** created (ID: {pid})")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    st.markdown("---")
    st.subheader("Existing Projects")
    projects = get_projects()
    if not projects:
        st.info("No projects yet.")
    else:
        for p in projects:
            with st.expander(f"📁 {p['name']}  (ID {p['id']})"):
                cols = st.columns([2, 2, 1])
                cols[0].write(f"**Keywords:** {', '.join(json.loads(p.get('keywords','[]')))}")
                cols[1].write(f"**Sources:** {', '.join(json.loads(p.get('sources','[]')))}")
                signals = get_signals(p["id"])
                cols[2].write(f"**Signals:** {len(signals)}")
                if st.button(f"🗑️ Delete project {p['id']}", key=f"del_{p['id']}"):
                    delete_project(p["id"])
                    st.rerun()


# ── RUN ANALYSIS ────────────────────────────────────────────
elif page == "🔍 Run Analysis":
    st.title("🔍 Run Analysis")

    projects = get_projects()
    if not projects:
        st.warning("No projects found. Create one first in 📁 Projects.")
    else:
        project_names = {p["name"]: p for p in projects}
        selected_name = st.selectbox("Select Project", list(project_names.keys()))
        project       = project_names[selected_name]
        keywords      = json.loads(project.get("keywords", "[]"))
        sources       = json.loads(project.get("sources", "[]"))

        st.markdown(f"**Keywords:** {', '.join(keywords)}  |  **Sources:** {', '.join(sources)}")

        use_claude = bool(api_key_input)
        if use_claude:
            st.success("✅ Claude API key detected — using AI analysis.")
        else:
            st.info("ℹ️ No API key — using heuristic analysis. Add your key in the sidebar for AI-powered results.")

        if st.button("🚀 Fetch & Analyse"):
            all_posts = []
            with st.status("Fetching posts…", expanded=True) as status:
                for src in sources:
                    st.write(f"Fetching from **{src}**…")
                    try:
                        engine = get_engine(src)
                        fetched = engine.fetch(keywords)
                        st.write(f"→ {len(fetched)} posts retrieved from {src}")
                        all_posts.extend(fetched)
                    except Exception as e:
                        st.error(f"Engine error for {src}: {e}")
                status.update(label=f"Fetched {len(all_posts)} posts total.", state="complete")

            if all_posts:
                analyzed = analyze_batch(all_posts, api_key=api_key_input or None)
                save_signals(project["id"], analyzed)
                st.success(f"✅ Saved {len(analyzed)} signals for project **{selected_name}**.")

                # Quick summary
                high = sum(1 for a in analyzed if a.get("risk_level") == "High")
                flags = sum(1 for a in analyzed if a.get("safety_flag"))
                st.metric("High-risk signals", high)
                st.metric("Safety flags",      flags)
            else:
                st.warning("No posts were fetched. Check keywords and sources.")


# ── SIGNALS & TRENDS ────────────────────────────────────────
elif page == "📊 Signals & Trends":
    st.title("📊 Signals & Trends")

    projects = get_projects()
    if not projects:
        st.stop()

    project_names = {p["name"]: p for p in projects}
    selected_name = st.selectbox("Project", list(project_names.keys()))
    project       = project_names[selected_name]
    signals       = get_signals(project["id"])

    if not signals:
        st.info("No signals yet. Run an analysis first.")
        st.stop()

    df = pd.DataFrame(signals)
    # Parse topics from JSON string back to list if needed
    if "topics" in df.columns:
        df["topics"] = df["topics"].apply(
            lambda t: json.loads(t) if isinstance(t, str) else (t or [])
        )

    # ── Filters
    with st.expander("🔽 Filters", expanded=False):
        fc1, fc2, fc3 = st.columns(3)
        risk_filter   = fc1.multiselect("Risk Level",  ["High","Medium","Low"], default=["High","Medium","Low"])
        sent_filter   = fc2.multiselect("Sentiment",   ["Positive","Negative","Neutral"],
                                        default=["Positive","Negative","Neutral"])
        source_filter = fc3.multiselect("Source",
                                        df["source"].dropna().unique().tolist(),
                                        default=df["source"].dropna().unique().tolist())
        safety_only   = st.checkbox("Show safety-flagged only")
        pii_only      = st.checkbox("Show PII-flagged only")

    mask = (
        df["risk_level"].isin(risk_filter) &
        df["sentiment"].isin(sent_filter) &
        df["source"].isin(source_filter)
    )
    if safety_only: mask &= df["safety_flag"] == 1
    if pii_only:    mask &= df["pii_flagged"] == 1
    filtered = df[mask]

    st.markdown(f"**{len(filtered)} signals** match current filters.")

    # ── Charts
    col1, col2, col3 = st.columns(3)

    with col1:
        rc = filtered["risk_level"].value_counts()
        fig, ax = plt.subplots(figsize=(3.5, 3))
        colors = {"High": "#e74c3c", "Medium": "#f39c12", "Low": "#2ecc71"}
        ax.pie(rc, labels=rc.index, autopct="%1.0f%%",
               colors=[colors.get(k, "#999") for k in rc.index])
        ax.set_title("Risk Levels")
        st.pyplot(fig, use_container_width=True)
        plt.close()

    with col2:
        sc = filtered["sentiment"].value_counts()
        fig, ax = plt.subplots(figsize=(3.5, 3))
        ax.bar(sc.index, sc.values,
               color=["#2ecc71" if s=="Positive" else "#e74c3c" if s=="Negative" else "#95a5a6"
                      for s in sc.index])
        ax.set_title("Sentiment")
        ax.set_ylabel("Count")
        st.pyplot(fig, use_container_width=True)
        plt.close()

    with col3:
        all_topics = [t for row in filtered["topics"] for t in (row if isinstance(row, list) else [])]
        tc = Counter(all_topics).most_common(8)
        if tc:
            fig, ax = plt.subplots(figsize=(3.5, 3))
            labels, vals = zip(*tc)
            ax.barh(labels, vals, color="#3498db")
            ax.set_title("Top Topics")
            ax.invert_yaxis()
            st.pyplot(fig, use_container_width=True)
            plt.close()

    # ── Data table
    st.markdown("---")
    st.subheader("Signal Table")
    display_cols = ["source","title","sentiment","risk_level","safety_flag","pii_flagged","adverse_event","analyzed_by"]
    available    = [c for c in display_cols if c in filtered.columns]
    st.dataframe(
        filtered[available].reset_index(drop=True),
        use_container_width=True,
        height=400,
    )

    # ── CSV download
    csv = filtered.drop(columns=["id","project_id"], errors="ignore").to_csv(index=False)
    st.download_button("⬇️ Download CSV", csv, "signals.csv", "text/csv")


# ── ADMIN ───────────────────────────────────────────────────
elif page == "⚙️ Admin":
    st.title("⚙️ Admin")

    st.subheader("Registered Source Engines")
    for e in get_source_engines():
        with st.expander(f"🔧 {e['name']}"):
            try:
                cfg = json.loads(e.get("config", "{}"))
            except Exception:
                cfg = {}
            st.json(cfg)

    st.markdown("---")
    st.subheader("Database Stats")
    with get_conn() as conn:
        n_proj = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        n_sig  = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        n_high = conn.execute("SELECT COUNT(*) FROM signals WHERE risk_level='High'").fetchone()[0]
        n_flag = conn.execute("SELECT COUNT(*) FROM signals WHERE safety_flag=1").fetchone()[0]

    cols = st.columns(4)
    cols[0].metric("Projects", n_proj)
    cols[1].metric("Signals",  n_sig)
    cols[2].metric("High Risk", n_high)
    cols[3].metric("Safety Flagged", n_flag)

    st.markdown("---")
    st.subheader("⚠️ Danger Zone")
    if st.button("🗑️ Clear ALL signals (keep projects)"):
        with get_conn() as conn:
            conn.execute("DELETE FROM signals")
        st.success("All signals deleted.")
        st.rerun()
