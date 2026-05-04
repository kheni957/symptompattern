import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import requests
import sqlite3
import json
import re
import time
import os
from datetime import datetime
from io import BytesIO
from collections import Counter

# ===========================================================
# DATABASE
# ===========================================================

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "healthwatch.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,
            description TEXT,
            keywords    TEXT,
            sources     TEXT,
            latency     TEXT    DEFAULT 'daily',
            created_at  TEXT    DEFAULT CURRENT_TIMESTAMP,
            active      INTEGER DEFAULT 1
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id        INTEGER,
            date              TEXT,
            source            TEXT,
            title             TEXT,
            text              TEXT,
            url               TEXT,
            sentiment         TEXT,
            sentiment_score   REAL,
            risk_level        TEXT,
            risk_score        INTEGER,
            risk_reason       TEXT,
            entities          TEXT,
            pii_flagged       INTEGER DEFAULT 0,
            pii_details       TEXT,
            safety_flag       INTEGER DEFAULT 0,
            safety_reason     TEXT,
            confidence        REAL,
            fetched_at        TEXT    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS source_engines (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            engine_type TEXT,
            config      TEXT,
            active      INTEGER DEFAULT 1
        )
    """)
    for name, etype, config in [
        ("Reddit",  "api", json.dumps({"base_url": "https://www.reddit.com",          "requires_key": False})),
        ("OpenFDA", "api", json.dumps({"base_url": "https://api.fda.gov",             "requires_key": False})),
        ("PubMed",  "api", json.dumps({"base_url": "https://eutils.ncbi.nlm.nih.gov", "requires_key": False})),
        ("Twitter", "api", json.dumps({"base_url": "https://api.twitterapi.io",       "requires_key": True})),
    ]:
        c.execute("INSERT OR IGNORE INTO source_engines (name, engine_type, config) VALUES (?,?,?)", (name, etype, config))
    conn.commit()
    conn.close()

def create_project(name, description, keywords, sources, latency="daily"):
    conn = get_conn()
    conn.execute("INSERT INTO projects (name, description, keywords, sources, latency) VALUES (?,?,?,?,?)",
                 (name, description, json.dumps(keywords), json.dumps(sources), latency))
    conn.commit(); conn.close()

def get_projects():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM projects WHERE active=1 ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_project(pid, name, description, keywords, sources, latency):
    conn = get_conn()
    conn.execute("UPDATE projects SET name=?, description=?, keywords=?, sources=?, latency=? WHERE id=?",
                 (name, description, json.dumps(keywords), json.dumps(sources), latency, pid))
    conn.commit(); conn.close()

def delete_project(pid):
    conn = get_conn()
    conn.execute("UPDATE projects SET active=0 WHERE id=?", (pid,))
    conn.commit(); conn.close()

def save_signals(project_id, signals):
    conn = get_conn()
    for s in signals:
        conn.execute("""
            INSERT INTO signals (project_id, date, source, title, text, url,
                sentiment, sentiment_score, risk_level, risk_score, risk_reason,
                entities, pii_flagged, pii_details, safety_flag, safety_reason, confidence)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (project_id, s.get("date"), s.get("source"), s.get("title"), s.get("text"), s.get("url"),
              s.get("sentiment"), s.get("sentiment_score"), s.get("risk_level"), s.get("risk_score"),
              s.get("risk_reason"), json.dumps(s.get("entities", [])),
              int(s.get("pii_flagged", 0)), s.get("pii_details", ""),
              int(s.get("safety_flag", 0)), s.get("safety_reason", ""), s.get("confidence", 0.0)))
    conn.commit(); conn.close()

def get_signals(project_id, limit=500):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM signals WHERE project_id=? ORDER BY fetched_at DESC LIMIT ?",
                        (project_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_source_engines():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM source_engines WHERE active=1").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_source_engine(name, engine_type, config):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO source_engines (name, engine_type, config) VALUES (?,?,?)",
                 (name, engine_type, json.dumps(config)))
    conn.commit(); conn.close()

# ===========================================================
# ENGINES
# ===========================================================

class BaseEngine:
    name = "base"
    def fetch(self, keywords, target=50): raise NotImplementedError
    def _quality_check(self, text, keywords):
        text = text.lower()
        return any(kw.lower() in text for kw in keywords) and len(text) > 60

class RedditEngine(BaseEngine):
    name = "Reddit"
    SUBREDDITS = ["AskDocs","DiagnoseMe","medical_advice","Longcovid",
                  "covidlonghaulers","cfs","Fibromyalgia","chronicpain",
                  "lupus","autoimmune","Lyme","ehlersdanlos","POTS"]
    def fetch(self, keywords, target=70):
        query   = "+".join(keywords[:3])
        session = requests.Session()
        session.headers.update({"User-Agent": "HealthWatchScraper/1.0"})
        posts   = []
        for sub in self.SUBREDDITS:
            if len(posts) >= target: break
            try:
                url = f"https://www.reddit.com/r/{sub}/search.json?q={query}&sort=new&limit=25&restrict_sr=1"
                r   = session.get(url, timeout=10); time.sleep(1.5)
                if r.status_code == 429: time.sleep(10); r = session.get(url, timeout=10)
                if r.status_code != 200: continue
                for post in r.json().get("data",{}).get("children",[]):
                    if len(posts) >= target: break
                    p = post.get("data",{})
                    title    = p.get("title","")
                    selftext = p.get("selftext","")
                    if selftext in ["[removed]","[deleted]",""]: continue
                    full_text = (title+" "+selftext).strip()
                    if self._quality_check(full_text, keywords):
                        posts.append({"date": pd.to_datetime(p.get("created_utc",0), unit='s').strftime("%Y-%m-%d"),
                                      "source": self.name, "title": title, "text": full_text,
                                      "url": "https://reddit.com"+p.get("permalink","")})
            except: continue
        return posts

class OpenFDAEngine(BaseEngine):
    name = "OpenFDA"
    def fetch(self, keywords, target=70):
        medical_terms = keywords + ["pyrexia","asthenia","malaise","myalgia"]
        searches = [f"patient.reaction.reactionmeddrapt:{kw.replace(' ','+')}" for kw in keywords[:5]]
        posts    = []
        for search in searches:
            if len(posts) >= target: break
            try:
                r = requests.get(f"https://api.fda.gov/drug/event.json?search={search}&limit=25", timeout=12)
                time.sleep(1)
                if r.status_code != 200: continue
                for result in r.json().get("results",[]):
                    if len(posts) >= target: break
                    reactions     = result.get("patient",{}).get("reaction",[])
                    drugs         = result.get("patient",{}).get("drug",[])
                    reaction_text = ", ".join([rx.get("reactionmeddrapt","").lower() for rx in reactions])
                    drug_text     = ", ".join([d.get("medicinalproduct","").lower() for d in drugs])
                    serious       = result.get("serious",0)
                    full_text     = (f"patient reported reactions: {reaction_text}. drugs taken: {drug_text}. "
                                     f"outcome: {'serious adverse event' if serious==1 else 'non-serious'}. "
                                     f"duration unknown since months of treatment.")
                    receipt_date  = result.get("receiptdate","20240101")
                    try:    date_str = datetime.strptime(receipt_date,"%Y%m%d").strftime("%Y-%m-%d")
                    except: date_str = "2024-01-01"
                    if any(w in full_text.lower() for w in medical_terms) and len(full_text)>60:
                        posts.append({"date": date_str, "source": self.name,
                                      "title": f"FDA report: {reaction_text[:80]}",
                                      "text": full_text, "url": "https://open.fda.gov/apis/drug/event/"})
            except: continue
        return posts

class PubMedEngine(BaseEngine):
    name = "PubMed"
    def fetch(self, keywords, target=60):
        base  = "+".join(keywords[:3])
        posts = []
        for q in [base, base+"+chronic", base+"+treatment", base+"+weeks", base+"+syndrome"]:
            if len(posts) >= target: break
            try:
                r = requests.get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={q}&retmax=15&retmode=json", timeout=10)
                time.sleep(0.4)
                if r.status_code != 200: continue
                ids = r.json().get("esearchresult",{}).get("idlist",[])
                if not ids: continue
                r2 = requests.get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={','.join(ids)}&rettype=abstract&retmode=text", timeout=10)
                time.sleep(0.4)
                if r2.status_code != 200: continue
                for article in r2.text.strip().split("\n\n\n"):
                    if len(posts) >= target: break
                    text  = article.strip()
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    title = lines[0][:120] if lines else "PubMed Abstract"
                    if self._quality_check(text, keywords) and len(text)>60:
                        posts.append({"date": datetime.now().strftime("%Y-%m-%d"), "source": self.name,
                                      "title": title, "text": text, "url": "https://pubmed.ncbi.nlm.nih.gov/"})
            except: continue
        return posts

class TwitterEngine(BaseEngine):
    name = "Twitter"
    def __init__(self, api_key=""):
        self.api_key = api_key
    def fetch(self, keywords, target=50):
        if not self.api_key: return []
        posts = []
        try:
            r = requests.get("https://api.twitterapi.io/twitter/tweet/advanced_search",
                             headers={"X-API-Key": self.api_key},
                             params={"query": " OR ".join([f'"{kw}"' for kw in keywords[:4]])+" lang:en",
                                     "queryType": "Latest", "count": min(target,100)}, timeout=15)
            if r.status_code != 200: return []
            for tweet in r.json().get("tweets", r.json().get("data",[])):
                if len(posts) >= target: break
                text = tweet.get("text", tweet.get("full_text",""))
                if self._quality_check(text, keywords):
                    try:    date_str = pd.to_datetime(tweet.get("created_at","")).strftime("%Y-%m-%d")
                    except: date_str = datetime.now().strftime("%Y-%m-%d")
                    posts.append({"date": date_str, "source": self.name, "title": text[:100],
                                  "text": text, "url": f"https://twitter.com/i/web/status/{tweet.get('id','')}"})
        except: pass
        return posts

ENGINES = {"Reddit": RedditEngine, "OpenFDA": OpenFDAEngine, "PubMed": PubMedEngine, "Twitter": TwitterEngine}

def get_engine(name, **kwargs):
    cls = ENGINES.get(name)
    if cls: return cls(**kwargs)
    raise ValueError(f"Unknown engine: {name}")

# ===========================================================
# ANALYSIS
# ===========================================================

POS_WORDS = ["better","improving","improved","recovered","recovery","relief",
             "resolved","cured","healed","responding","working","effective","helpful","hopeful"]
NEG_WORDS = ["worse","worsening","pain","suffering","horrible","terrible","awful",
             "failed","not working","not helping","no effect","scared","worried",
             "hopeless","desperate","exhausted","unbearable","severe","deteriorating",
             "not improving","still sick","no answers","frustrated"]

def analyze_sentiment(text):
    text_l    = text.lower()
    pos_count = sum(1 for w in POS_WORDS if w in text_l)
    neg_count = sum(1 for w in NEG_WORDS if w in text_l)
    total     = pos_count + neg_count
    if total == 0: return {"sentiment":"Neutral","sentiment_score":0.0,"confidence":0.4}
    score = (pos_count - neg_count) / total
    label = "Positive" if score>0.1 else ("Negative" if score<-0.1 else "Neutral")
    return {"sentiment":label,"sentiment_score":round(score,3),"confidence":round(min(0.4+total*0.05,0.9),2)}

DRUG_TERMS      = ["ibuprofen","paracetamol","acetaminophen","amoxicillin","doxycycline",
                   "azithromycin","metformin","prednisone","prednisolone","augmentin",
                   "cephalexin","ciprofloxacin","metronidazole","tylenol","motrin",
                   "aspirin","naproxen","hydroxychloroquine","remicade","humira",
                   "antibiotics","antibiotic","nsaids","antihistamine"]
CONDITION_TERMS = ["fever","fatigue","covid","long covid","fibromyalgia","lupus",
                   "lyme disease","pots","mcas","eds","cfs","me/cfs","chronic fatigue",
                   "arthritis","thyroid","hypothyroidism","anemia","infection",
                   "pneumonia","bronchitis","sinusitis","appendicitis","gastritis",
                   "diverticulitis","endometriosis","mono","mononucleosis","sepsis"]
SYMPTOM_TERMS   = ["fever","fatigue","chills","nausea","vomiting","headache",
                   "body aches","muscle pain","joint pain","weakness","dizziness",
                   "shortness of breath","chest pain","rash","swollen lymph nodes",
                   "night sweats","weight loss","brain fog","palpitations"]
PII_PATTERNS    = {"email":r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
                   "phone":r'\b(\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
                   "ssn":r'\b\d{3}-\d{2}-\d{4}\b',
                   "full_name":r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',
                   "age_gender":r'\b\d{1,3}[MFmf]\b'}
SAFETY_KW       = ["hospitalized","hospitalised","emergency","icu","seizure","overdose",
                   "anaphylaxis","allergic reaction","suicidal","self harm","heart attack",
                   "stroke","organ failure","sepsis","coma","died","death",
                   "life threatening","ambulance"]
SYMPTOM_KW      = ["fever","fatigue","pain","chills","nausea","weak","headache"]
WORSENING_KW    = ["worse","getting worse","not improving","deteriorating"]
DURATION_KW     = ["days","weeks","months","still","since"]
FAILURE_KW      = ["not working","no effect","not helping","antibiotics aren't working"]
POSITIVE_KW     = ["better","improving","recovered"]

def extract_entities(text):
    t = text.lower()
    entities = {"drugs":      [d for d in DRUG_TERMS      if d in t],
                "conditions": [c for c in CONDITION_TERMS if c in t],
                "symptoms":   [s for s in SYMPTOM_TERMS   if s in t]}
    ages = re.findall(r'\b(\d{1,2})[mf]\b|\b(\d{1,3})\s*(?:year[s]?\s*old|yo)\b', t)
    entities["ages"] = list(set([a[0] or a[1] for a in ages if any(a)]))
    return entities

def detect_pii(text):
    found = {}
    for label, pattern in PII_PATTERNS.items():
        matches = re.findall(pattern, text)
        if matches: found[label] = [m for m in matches if m] if not isinstance(matches[0], str) else matches
    return {"pii_flagged": len(found)>0, "pii_details": json.dumps(found) if found else ""}

def score_risk(text):
    t            = text.lower()
    has_symptom  = any(w in t for w in SYMPTOM_KW)
    has_duration = any(w in t for w in DURATION_KW)
    has_worsen   = any(w in t for w in WORSENING_KW)
    has_failure  = any(w in t for w in FAILURE_KW)
    has_positive = any(w in t for w in POSITIVE_KW)
    score, reasons = 0, []
    if has_symptom:  score+=1; reasons.append("Symptoms detected (+1)")
    if has_duration: score+=1; reasons.append("Long duration (+1)")
    if has_worsen:   score+=2; reasons.append("Condition worsening (+2)")
    if has_failure:  score+=2; reasons.append("Treatment not effective (+2)")
    if has_positive: score-=1; reasons.append("Signs of improvement (-1)")
    level   = "Low" if score<=1 else ("Medium" if score<=3 else "High")
    meaning = {"Low":"Mild condition, monitor symptoms",
               "Medium":"Moderate concern, consider medical advice",
               "High":"High risk, seek medical attention"}[level]
    confidence = round(min(0.5+sum([has_symptom,has_duration,has_worsen,has_failure])*0.12, 0.95), 2)
    return {"risk_score":score,"risk_level":level,"risk_reason":"; ".join(reasons) or "No indicators",
            "risk_meaning":meaning,"confidence":confidence}

def detect_safety(text):
    t = text.lower()
    triggered = [kw for kw in SAFETY_KW if kw in t]
    return {"safety_flag": len(triggered)>0, "safety_reason": ", ".join(triggered)}

def analyze_post(post):
    text = post.get("text","")
    return {**post, **analyze_sentiment(text), "entities": json.dumps(extract_entities(text)),
            **detect_pii(text), **score_risk(text), **detect_safety(text)}

def analyze_batch(posts):
    return [analyze_post(p) for p in posts]

def aggregate_stats(signals):
    if not signals: return {}
    df = pd.DataFrame(signals)
    stats = {"total": len(df),
             "high_risk":      int((df["risk_level"]=="High").sum()),
             "medium_risk":    int((df["risk_level"]=="Medium").sum()),
             "low_risk":       int((df["risk_level"]=="Low").sum()),
             "safety_flags":   int(df["safety_flag"].sum()) if "safety_flag" in df else 0,
             "pii_flags":      int(df["pii_flagged"].sum()) if "pii_flagged" in df else 0,
             "avg_confidence": round(float(df["confidence"].mean()), 2) if "confidence" in df else 0,
             "sentiment_dist": df["sentiment"].value_counts().to_dict() if "sentiment" in df else {},
             "source_dist":    df["source"].value_counts().to_dict() if "source" in df else {},
             "risk_dist":      df["risk_level"].value_counts().to_dict() if "risk_level" in df else {}}
    all_c, all_d, all_s = [], [], []
    for row in signals:
        try:
            ents = json.loads(row.get("entities","{}"))
            all_c.extend(ents.get("conditions",[])); all_d.extend(ents.get("drugs",[])); all_s.extend(ents.get("symptoms",[]))
        except: pass
    stats["top_conditions"] = dict(Counter(all_c).most_common(10))
    stats["top_drugs"]      = dict(Counter(all_d).most_common(10))
    stats["top_symptoms"]   = dict(Counter(all_s).most_common(10))
    return stats

# ===========================================================
# APP
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

page = st.sidebar.radio("Navigate", ["🏠 Dashboard","📁 Projects","🔍 Run Analysis","📊 Signals & Trends","⚙️ Admin"])

# ── DASHBOARD ────────────────────────────────────────────────
if page == "🏠 Dashboard":
    st.title("🏥 HealthWatch — Patient Signal Monitor")
    st.markdown("Real-time social listening for adverse events, treatment signals & patient safety.")
    st.markdown("---")
    projects = get_projects()
    if not projects:
        st.info("👈 No projects yet. Go to **Projects** to create your first monitoring project.")
    else:
        all_signals = []
        for p in projects: all_signals.extend(get_signals(p["id"]))
        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("📁 Projects",      len(projects))
        c2.metric("📨 Total Signals", len(all_signals))
        c3.metric("🔴 High Risk",     sum(1 for s in all_signals if s.get("risk_level")=="High"))
        c4.metric("⚠️ Safety Flags",  sum(1 for s in all_signals if s.get("safety_flag")==1))
        c5.metric("🔒 PII Detected",  sum(1 for s in all_signals if s.get("pii_flagged")==1))
        st.markdown("---")
        st.subheader("📁 Active Projects")
        for p in projects:
            kws    = json.loads(p.get("keywords","[]"))
            srcs   = json.loads(p.get("sources","[]"))
            sigs   = get_signals(p["id"])
            high   = sum(1 for s in sigs if s.get("risk_level")=="High")
            safety = sum(1 for s in sigs if s.get("safety_flag")==1)
            with st.expander(f"**{p['name']}** — {len(sigs)} signals | 🔴 {high} high | ⚠️ {safety} safety"):
                c1,c2,c3 = st.columns(3)
                c1.markdown(f"**Keywords:** {', '.join(kws)}")
                c2.markdown(f"**Sources:** {', '.join(srcs)}")
                c3.markdown(f"**Latency:** `{p.get('latency','daily')}`")

# ── PROJECTS ────────────────────────────────────────────────
elif page == "📁 Projects":
    st.title("📁 Project Management")
    tab1, tab2 = st.tabs(["➕ Create Project","📋 Existing Projects"])
    available_sources = [e["name"] for e in get_source_engines()]

    with tab1:
        st.subheader("Create New Monitoring Project")
        with st.form("create_project_form"):
            name         = st.text_input("Project Name *",                    placeholder="e.g. Ibuprofen Adverse Events")
            description  = st.text_area("Description",                        placeholder="What are you monitoring?")
            keywords_raw = st.text_input("Keywords (comma-separated) *",      placeholder="fever, fatigue, ibuprofen")
            sources      = st.multiselect("Data Sources *", available_sources, default=["Reddit"])
            latency      = st.selectbox("Fetch Frequency", ["realtime","daily","weekly"])
            if st.form_submit_button("✅ Create Project"):
                if not name or not keywords_raw or not sources:
                    st.error("Please fill in all required fields (*)")
                else:
                    try:
                        create_project(name, description, [k.strip() for k in keywords_raw.split(",") if k.strip()], sources, latency)
                        st.success(f"✅ Project **{name}** created!"); st.rerun()
                    except Exception as e: st.error(f"Error: {e}")

    with tab2:
        projects = get_projects()
        if not projects: st.info("No projects yet.")
        for p in projects:
            kws  = json.loads(p.get("keywords","[]"))
            srcs = json.loads(p.get("sources","[]"))
            with st.expander(f"**{p['name']}** (ID: {p['id']})"):
                col1, col2 = st.columns([3,1])
                with col1:
                    new_name = st.text_input("Name",        value=p["name"],             key=f"n_{p['id']}")
                    new_desc = st.text_area("Description",  value=p.get("description",""),key=f"d_{p['id']}")
                    new_kw   = st.text_input("Keywords",    value=", ".join(kws),         key=f"k_{p['id']}")
                    new_src  = st.multiselect("Sources",    available_sources,
                                              default=[s for s in srcs if s in available_sources], key=f"s_{p['id']}")
                    new_lat  = st.selectbox("Latency",      ["realtime","daily","weekly"],
                                            index=["realtime","daily","weekly"].index(p.get("latency","daily")),
                                            key=f"l_{p['id']}")
                with col2:
                    if st.button("💾 Save",   key=f"save_{p['id']}"):
                        update_project(p["id"], new_name, new_desc, [k.strip() for k in new_kw.split(",")], new_src, new_lat)
                        st.success("Saved!"); st.rerun()
                    if st.button("🗑️ Delete", key=f"del_{p['id']}"):
                        delete_project(p["id"]); st.warning("Deleted."); st.rerun()

# ── RUN ANALYSIS ────────────────────────────────────────────
elif page == "🔍 Run Analysis":
    st.title("🔍 Fetch & Analyze")
    projects = get_projects()
    if not projects:
        st.warning("Create a project first.")
    else:
        project_names = {p["name"]: p for p in projects}
        project       = project_names[st.selectbox("Select Project", list(project_names.keys()))]
        keywords      = json.loads(project.get("keywords","[]"))
        sources       = json.loads(project.get("sources","[]"))
        st.markdown(f"**Keywords:** `{', '.join(keywords)}`  |  **Sources:** `{', '.join(sources)}`")

        twitter_key = ""
        if "Twitter" in sources:
            twitter_key = st.text_input("Twitter API Key (twitterapi.io)", type="password")

        cols    = st.columns(len(sources))
        targets = {}
        defaults = {"Reddit":70,"OpenFDA":70,"PubMed":60,"Twitter":50}
        for i, src in enumerate(sources):
            with cols[i]: targets[src] = st.slider(f"{src} posts", 10, 100, defaults.get(src,50), key=f"t_{src}")

        if st.button("🚀 Fetch & Analyze Now", type="primary"):
            all_posts = []
            progress  = st.progress(0)
            status    = st.empty()
            for i, src in enumerate(sources):
                status.text(f"Fetching from {src}...")
                try:
                    kwargs = {"api_key": twitter_key} if src == "Twitter" else {}
                    engine = get_engine(src, **kwargs)
                    posts  = engine.fetch(keywords, target=targets.get(src,50))
                    all_posts.extend(posts)
                    status.text(f"✅ {src}: {len(posts)} posts")
                except Exception as e: st.warning(f"⚠️ {src} failed: {e}")
                progress.progress((i+1)/len(sources))

            if all_posts:
                status.text("🧠 Running analysis pipeline...")
                analyzed = analyze_batch(all_posts)
                save_signals(project["id"], analyzed)
                progress.progress(1.0); status.text("")
                st.success(f"✅ Fetched and analyzed **{len(analyzed)}** signals!")
                df = pd.DataFrame(analyzed)
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("Total",        len(df))
                c2.metric("🔴 High Risk", int((df["risk_level"]=="High").sum()))
                c3.metric("⚠️ Safety",    int(df["safety_flag"].sum()))
                c4.metric("🔒 PII",       int(df["pii_flagged"].sum()))
            else:
                st.error("No posts fetched.")

# ── SIGNALS & TRENDS ────────────────────────────────────────
elif page == "📊 Signals & Trends":
    st.title("📊 Signals & Trend Analysis")
    projects = get_projects()
    if not projects: st.warning("No projects found."); st.stop()
    project_names = {p["name"]: p for p in projects}
    project  = project_names[st.selectbox("Select Project", list(project_names.keys()))]
    signals  = get_signals(project["id"])
    if not signals: st.info("No signals yet. Run analysis first."); st.stop()

    df    = pd.DataFrame(signals)
    stats = aggregate_stats(signals)

    st.markdown("---")
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("Total",           stats["total"])
    c2.metric("🔴 High",         stats["high_risk"])
    c3.metric("🟡 Medium",       stats["medium_risk"])
    c4.metric("🟢 Low",          stats["low_risk"])
    c5.metric("⚠️ Safety Flags", stats["safety_flags"])
    c6.metric("🔒 PII",          stats["pii_flags"])

    st.markdown("---")
    st.subheader("🔎 Filter Signals")
    col_a, col_b, col_c = st.columns(3)
    with col_a: risk_filter   = st.multiselect("Risk Level", ["Low","Medium","High"], default=["Low","Medium","High"])
    with col_b: source_filter = st.multiselect("Source",     df["source"].unique().tolist(), default=df["source"].unique().tolist())
    with col_c:
        show_safety = st.checkbox("⚠️ Safety flags only", False)
        show_pii    = st.checkbox("🔒 PII flagged only",  False)

    fdf = df[df["risk_level"].isin(risk_filter) & df["source"].isin(source_filter)]
    if show_safety: fdf = fdf[fdf["safety_flag"]==1]
    if show_pii:    fdf = fdf[fdf["pii_flagged"]==1]

    display_cols = [c for c in ["date","source","title","sentiment","risk_level","risk_score","confidence","risk_reason","safety_flag","pii_flagged"] if c in fdf.columns]
    st.dataframe(fdf[display_cols], use_container_width=True, height=300)
    st.download_button("📥 Download CSV", fdf.to_csv(index=False).encode(), "signals.csv", "text/csv")

    # Safety flags
    safety_df = df[df["safety_flag"]==1]
    if not safety_df.empty:
        st.markdown("---"); st.subheader("⚠️ Safety & Adverse Event Flags")
        for _, row in safety_df.iterrows():
            st.markdown(f'<div class="safety-flag"><b>{str(row.get("title",""))[:80]}</b><br>'
                        f'Source: {row.get("source","")} | Date: {row.get("date","")} | Risk: {row.get("risk_level","")}<br>'
                        f'Reason: {row.get("safety_reason","")}</div>', unsafe_allow_html=True)

    # PII flags
    pii_df = df[df["pii_flagged"]==1]
    if not pii_df.empty:
        st.markdown("---"); st.subheader("🔒 PII / PHI Detected")
        for _, row in pii_df.iterrows():
            st.markdown(f'<div class="pii-flag"><b>{str(row.get("title",""))[:80]}</b><br>'
                        f'Source: {row.get("source","")} | Date: {row.get("date","")}<br>'
                        f'PII: {row.get("pii_details","")}</div>', unsafe_allow_html=True)

    # Charts
    st.markdown("---"); st.subheader("📈 Trend Analysis")
    fig = plt.figure(figsize=(20,16))
    gs  = gridspec.GridSpec(3, 3, figure=fig, hspace=0.5, wspace=0.4)

    # Chart 1: Risk trend
    ax1 = fig.add_subplot(gs[0,:])
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df_t = df.dropna(subset=["date"]).sort_values("date").copy()
        df_t.set_index("date", inplace=True)
        weekly   = df_t["risk_score"].resample("W").mean()
        smoothed = weekly.rolling(window=3, min_periods=1).mean()
        ax1.fill_between(weekly.index, 0, 1, alpha=0.08, color="green",  label="Low zone")
        ax1.fill_between(weekly.index, 1, 3, alpha=0.08, color="orange", label="Medium zone")
        ax1.fill_between(weekly.index, 3, 6, alpha=0.08, color="red",    label="High zone")
        ax1.plot(weekly.index,   weekly.values,   "o-", color="steelblue",  lw=1.5, ms=4, label="Weekly avg")
        ax1.plot(smoothed.index, smoothed.values, "-",  color="darkorange", lw=2.5,       label="Smoothed")
        ax1.axhline(y=1, color="green", ls="--", lw=0.8, alpha=0.5)
        ax1.axhline(y=3, color="red",   ls="--", lw=0.8, alpha=0.5)
        ax1.set_title("Risk Score Trend Over Time", fontweight="bold", fontsize=13)
        ax1.set_ylabel("Avg Risk Score"); ax1.set_ylim(0,6); ax1.legend(fontsize=9)

    # Chart 2: Risk pie
    ax2 = fig.add_subplot(gs[1,0])
    counts = df["risk_level"].value_counts()
    cmap   = {"Low":"#4CAF50","Medium":"#FF9800","High":"#F44336"}
    ax2.pie(counts.values, labels=counts.index, autopct="%1.1f%%",
            colors=[cmap.get(l,"grey") for l in counts.index], startangle=140, textprops={"fontsize":10})
    ax2.set_title("Risk Distribution", fontweight="bold")

    # Chart 3: Sentiment
    ax3 = fig.add_subplot(gs[1,1])
    if "sentiment" in df.columns:
        sent = df["sentiment"].value_counts()
        sc   = {"Positive":"#4CAF50","Neutral":"#2196F3","Negative":"#F44336"}
        ax3.bar(sent.index, sent.values, color=[sc.get(s,"grey") for s in sent.index], edgecolor="white")
        ax3.set_title("Sentiment Distribution", fontweight="bold"); ax3.set_ylabel("Count")
        for rect in ax3.patches:
            h = rect.get_height()
            if h > 0: ax3.text(rect.get_x()+rect.get_width()/2., h+0.3, f"{int(h)}", ha="center", fontsize=9, fontweight="bold")

    # Chart 4: Source breakdown
    ax4 = fig.add_subplot(gs[1,2])
    if "source" in df.columns:
        src_c = df["source"].value_counts()
        ax4.barh(src_c.index, src_c.values, color="steelblue", edgecolor="white")
        ax4.set_title("Posts by Source", fontweight="bold"); ax4.set_xlabel("Count")

    # Chart 5: Top symptoms
    ax5 = fig.add_subplot(gs[2,0])
    if stats.get("top_symptoms"):
        ax5.barh(list(stats["top_symptoms"].keys())[:8], list(stats["top_symptoms"].values())[:8], color="coral", edgecolor="white")
        ax5.set_title("Top Symptoms", fontweight="bold"); ax5.set_xlabel("Mentions")

    # Chart 6: Top conditions
    ax6 = fig.add_subplot(gs[2,1])
    if stats.get("top_conditions"):
        ax6.barh(list(stats["top_conditions"].keys())[:8], list(stats["top_conditions"].values())[:8], color="mediumpurple", edgecolor="white")
        ax6.set_title("Top Conditions", fontweight="bold"); ax6.set_xlabel("Mentions")

    # Chart 7: Top drugs
    ax7 = fig.add_subplot(gs[2,2])
    if stats.get("top_drugs"):
        ax7.barh(list(stats["top_drugs"].keys())[:8], list(stats["top_drugs"].values())[:8], color="mediumseagreen", edgecolor="white")
        ax7.set_title("Top Drugs Mentioned", fontweight="bold"); ax7.set_xlabel("Mentions")

    st.pyplot(fig)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    st.download_button("📥 Download Dashboard PNG", buf.getvalue(), "dashboard.png", "image/png")

# ── ADMIN ───────────────────────────────────────────────────
elif page == "⚙️ Admin":
    st.title("⚙️ Admin — Source Engine Management")
    st.subheader("Registered Source Engines")
    for e in get_source_engines():
        cfg = json.loads(e.get("config","{}"))
        with st.expander(f"**{e['name']}** ({e['engine_type']})"):
            st.json(cfg)

    st.markdown("---")
    st.subheader("➕ Register New Source Engine")
    with st.form("add_engine"):
        eng_name  = st.text_input("Engine Name", placeholder="e.g. CustomForum")
        eng_type  = st.selectbox("Engine Type",  ["api","scraper","rss"])
        eng_url   = st.text_input("Base URL",    placeholder="https://example.com")
        eng_key   = st.checkbox("Requires API Key")
        eng_notes = st.text_area("Notes / Config")
        if st.form_submit_button("➕ Register Engine") and eng_name and eng_url:
            add_source_engine(eng_name, eng_type, {"base_url":eng_url,"requires_key":eng_key,"notes":eng_notes})
            st.success(f"✅ Engine **{eng_name}** registered!"); st.rerun()

    st.markdown("---")
    st.subheader("ℹ️ System Info")
    st.markdown(f"- **DB Path:** `{DB_PATH}`")
    st.markdown(f"- **Available engines:** {', '.join(ENGINES.keys())}")
    st.markdown(f"- **Version:** 1.0.0")

st.set_page_config(page_title="HealthWatch", layout="wide", page_icon="🏥")

# Custom CSS
st.markdown("""
<style>
    .metric-card {
        background: #1e1e2e; border-radius: 10px;
        padding: 15px; text-align: center;
    }
    .high-risk   { color: #F44336; font-weight: bold; }
    .medium-risk { color: #FF9800; font-weight: bold; }
    .low-risk    { color: #4CAF50; font-weight: bold; }
    .safety-flag { background: #ff000022; border-left: 4px solid red; padding: 8px; border-radius: 4px; }
    .pii-flag    { background: #ff990022; border-left: 4px solid orange; padding: 8px; border-radius: 4px; }
</style>
""", unsafe_allow_html=True)

# ===========================================================
# SIDEBAR NAVIGATION
# ===========================================================

st.sidebar.image("https://img.icons8.com/color/96/stethoscope.png", width=60)
st.sidebar.title("HealthWatch")
st.sidebar.markdown("*Real-Time Patient Signal Monitor*")
st.sidebar.markdown("---")

page = st.sidebar.radio("Navigate", [
    "🏠 Dashboard",
    "📁 Projects",
    "🔍 Run Analysis",
    "📊 Signals & Trends",
    "⚙️  Admin"
])

# ===========================================================
# PAGE 1 — DASHBOARD
# ===========================================================

if page == "🏠 Dashboard":
    st.title("🏥 HealthWatch — Patient Signal Monitor")
    st.markdown("Real-time social listening for adverse events, treatment signals & patient safety.")
    st.markdown("---")

    projects = get_projects()
    if not projects:
        st.info("👈 No projects yet. Go to **Projects** to create your first monitoring project.")
    else:
        # Global stats across all projects
        all_signals = []
        for p in projects:
            all_signals.extend(get_signals(p["id"]))

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("📁 Projects",       len(projects))
        col2.metric("📨 Total Signals",  len(all_signals))
        col3.metric("🔴 High Risk",      sum(1 for s in all_signals if s.get("risk_level") == "High"))
        col4.metric("⚠️ Safety Flags",   sum(1 for s in all_signals if s.get("safety_flag") == 1))
        col5.metric("🔒 PII Detected",   sum(1 for s in all_signals if s.get("pii_flagged") == 1))

        st.markdown("---")
        st.subheader("📁 Active Projects")

        for p in projects:
            sigs   = get_signals(p["id"])
            kws    = json.loads(p.get("keywords", "[]"))
            srcs   = json.loads(p.get("sources",  "[]"))
            high   = sum(1 for s in sigs if s.get("risk_level") == "High")
            safety = sum(1 for s in sigs if s.get("safety_flag") == 1)

            with st.expander(f"**{p['name']}** — {len(sigs)} signals | 🔴 {high} high risk | ⚠️ {safety} safety flags"):
                c1, c2, c3 = st.columns(3)
                c1.markdown(f"**Keywords:** {', '.join(kws)}")
                c2.markdown(f"**Sources:** {', '.join(srcs)}")
                c3.markdown(f"**Latency:** `{p.get('latency','daily')}`")
                if p.get("description"):
                    st.markdown(f"*{p['description']}*")


# ===========================================================
# PAGE 2 — PROJECTS
# ===========================================================

elif page == "📁 Projects":
    st.title("📁 Project Management")
    tab1, tab2 = st.tabs(["➕ Create Project", "📋 Existing Projects"])

    available_sources = [e["name"] for e in get_source_engines()]

    with tab1:
        st.subheader("Create New Monitoring Project")
        with st.form("create_project_form"):
            name        = st.text_input("Project Name *", placeholder="e.g. Ibuprofen Adverse Events")
            description = st.text_area("Description",     placeholder="What are you monitoring?")
            keywords_raw= st.text_input("Keywords (comma-separated) *",
                                         placeholder="fever, fatigue, ibuprofen, pain")
            sources     = st.multiselect("Data Sources *", available_sources, default=["Reddit"])
            latency     = st.selectbox("Fetch Frequency", ["realtime", "daily", "weekly"])
            submitted   = st.form_submit_button("✅ Create Project")

            if submitted:
                if not name or not keywords_raw or not sources:
                    st.error("Please fill in all required fields (*)")
                else:
                    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
                    try:
                        create_project(name, description, keywords, sources, latency)
                        st.success(f"✅ Project **{name}** created!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

    with tab2:
        projects = get_projects()
        if not projects:
            st.info("No projects yet.")
        for p in projects:
            kws  = json.loads(p.get("keywords", "[]"))
            srcs = json.loads(p.get("sources",  "[]"))
            with st.expander(f"**{p['name']}** (ID: {p['id']})"):
                col1, col2 = st.columns([3, 1])
                with col1:
                    new_name   = st.text_input("Name",        value=p["name"],        key=f"n_{p['id']}")
                    new_desc   = st.text_area("Description",  value=p.get("description",""), key=f"d_{p['id']}")
                    new_kw     = st.text_input("Keywords",    value=", ".join(kws),   key=f"k_{p['id']}")
                    new_src    = st.multiselect("Sources",    available_sources,
                                                default=[s for s in srcs if s in available_sources],
                                                key=f"s_{p['id']}")
                    new_lat    = st.selectbox("Latency",      ["realtime","daily","weekly"],
                                              index=["realtime","daily","weekly"].index(p.get("latency","daily")),
                                              key=f"l_{p['id']}")
                with col2:
                    if st.button("💾 Save", key=f"save_{p['id']}"):
                        update_project(p["id"], new_name, new_desc,
                                       [k.strip() for k in new_kw.split(",")],
                                       new_src, new_lat)
                        st.success("Saved!")
                        st.rerun()
                    if st.button("🗑️ Delete", key=f"del_{p['id']}"):
                        delete_project(p["id"])
                        st.warning("Deleted.")
                        st.rerun()


# ===========================================================
# PAGE 3 — RUN ANALYSIS
# ===========================================================

elif page == "🔍 Run Analysis":
    st.title("🔍 Fetch & Analyze")

    projects = get_projects()
    if not projects:
        st.warning("Create a project first.")
    else:
        project_names = {p["name"]: p for p in projects}
        selected_name = st.selectbox("Select Project", list(project_names.keys()))
        project       = project_names[selected_name]
        keywords      = json.loads(project.get("keywords", "[]"))
        sources       = json.loads(project.get("sources",  "[]"))

        st.markdown(f"**Keywords:** `{', '.join(keywords)}`")
        st.markdown(f"**Sources:** `{', '.join(sources)}`")

        # Twitter API key (optional)
        twitter_key = ""
        if "Twitter" in sources:
            twitter_key = st.text_input("Twitter API Key (twitterapi.io)", type="password")

        col1, col2, col3 = st.columns(3)
        targets = {}
        for src in sources:
            with col1 if src == sources[0] else col2 if src == sources[1] else col3:
                targets[src] = st.slider(f"{src} posts", 10, 100,
                                          {"Reddit": 70, "OpenFDA": 70, "PubMed": 60, "Twitter": 50}.get(src, 50),
                                          key=f"t_{src}")

        if st.button("🚀 Fetch & Analyze Now", type="primary"):
            all_posts = []
            progress  = st.progress(0)
            status    = st.empty()

            for i, src in enumerate(sources):
                status.text(f"Fetching from {src}...")
                try:
                    kwargs = {"api_key": twitter_key} if src == "Twitter" else {}
                    engine = get_engine(src, **kwargs)
                    posts  = engine.fetch(keywords, target=targets.get(src, 50))
                    all_posts.extend(posts)
                    status.text(f"✅ {src}: {len(posts)} posts fetched")
                except Exception as e:
                    st.warning(f"⚠️ {src} failed: {e}")
                progress.progress((i + 1) / len(sources))

            if all_posts:
                status.text("🧠 Running analysis pipeline...")
                analyzed = analyze_batch(all_posts)
                save_signals(project["id"], analyzed)
                progress.progress(1.0)
                status.text("")

                st.success(f"✅ Fetched and analyzed **{len(analyzed)}** signals!")

                # Quick summary
                df = pd.DataFrame(analyzed)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total",        len(df))
                c2.metric("🔴 High Risk", int((df["risk_level"] == "High").sum()))
                c3.metric("⚠️ Safety",    int(df["safety_flag"].sum()))
                c4.metric("🔒 PII",       int(df["pii_flagged"].sum()))
            else:
                st.error("No posts fetched. Check your sources and keywords.")


# ===========================================================
# PAGE 4 — SIGNALS & TRENDS
# ===========================================================

elif page == "📊 Signals & Trends":
    st.title("📊 Signals & Trend Analysis")

    projects = get_projects()
    if not projects:
        st.warning("No projects found. Create one first.")
        st.stop()

    project_names = {p["name"]: p for p in projects}
    selected_name = st.selectbox("Select Project", list(project_names.keys()))
    project       = project_names[selected_name]
    signals       = get_signals(project["id"])

    if not signals:
        st.info("No signals yet. Run analysis first.")
        st.stop()

    df = pd.DataFrame(signals)
    stats = aggregate_stats(signals)

    # ── Top metrics ────────────────────────────────────────
    st.markdown("---")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total Signals",   stats["total"])
    c2.metric("🔴 High Risk",    stats["high_risk"])
    c3.metric("🟡 Medium Risk",  stats["medium_risk"])
    c4.metric("🟢 Low Risk",     stats["low_risk"])
    c5.metric("⚠️ Safety Flags", stats["safety_flags"])
    c6.metric("🔒 PII Detected", stats["pii_flags"])

    # ── Filters ────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🔎 Filter Signals")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        risk_filter   = st.multiselect("Risk Level", ["Low","Medium","High"], default=["Low","Medium","High"])
    with col_b:
        source_filter = st.multiselect("Source", df["source"].unique().tolist(), default=df["source"].unique().tolist())
    with col_c:
        show_safety   = st.checkbox("⚠️ Safety flags only", False)
        show_pii      = st.checkbox("🔒 PII flagged only",  False)

    fdf = df[df["risk_level"].isin(risk_filter) & df["source"].isin(source_filter)]
    if show_safety: fdf = fdf[fdf["safety_flag"] == 1]
    if show_pii:    fdf = fdf[fdf["pii_flagged"] == 1]

    # ── Signals table ──────────────────────────────────────
    display_cols = ["date", "source", "title", "sentiment", "risk_level",
                    "risk_score", "confidence", "risk_reason", "safety_flag", "pii_flagged"]
    display_cols = [c for c in display_cols if c in fdf.columns]

    def color_risk(val):
        colors = {"High": "background-color:#ff000033",
                  "Medium": "background-color:#ff990033",
                  "Low": "background-color:#00ff0022"}
        return colors.get(val, "")

    styled = fdf[display_cols].style.applymap(color_risk, subset=["risk_level"])
    st.dataframe(styled, use_container_width=True, height=300)

    # Download
    st.download_button("📥 Download CSV", fdf.to_csv(index=False).encode(), "signals.csv", "text/csv")

    # ── Safety flags ───────────────────────────────────────
    safety_df = df[df["safety_flag"] == 1]
    if not safety_df.empty:
        st.markdown("---")
        st.subheader("⚠️ Safety & Adverse Event Flags")
        for _, row in safety_df.iterrows():
            st.markdown(f"""
            <div class="safety-flag">
            <b>{row.get('title','')[:80]}</b><br>
            Source: {row.get('source','')} | Date: {row.get('date','')} | Risk: {row.get('risk_level','')}<br>
            Reason: {row.get('safety_reason','')}
            </div>
            """, unsafe_allow_html=True)
            st.markdown("")

    # ── PII flags ──────────────────────────────────────────
    pii_df = df[df["pii_flagged"] == 1]
    if not pii_df.empty:
        st.markdown("---")
        st.subheader("🔒 PII / PHI Detected")
        for _, row in pii_df.iterrows():
            st.markdown(f"""
            <div class="pii-flag">
            <b>{row.get('title','')[:80]}</b><br>
            Source: {row.get('source','')} | Date: {row.get('date','')}<br>
            PII Types: {row.get('pii_details','')}
            </div>
            """, unsafe_allow_html=True)
            st.markdown("")

    # ── Charts ─────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📈 Trend Analysis")

    fig = plt.figure(figsize=(20, 16))
    gs  = gridspec.GridSpec(3, 3, figure=fig, hspace=0.5, wspace=0.4)

    # Chart 1: Risk trend over time (full width)
    ax1 = fig.add_subplot(gs[0, :])
    if "date" in df.columns:
        df["date"]   = pd.to_datetime(df["date"], errors="coerce")
        df_t         = df.dropna(subset=["date"]).sort_values("date").copy()
        df_t.set_index("date", inplace=True)
        weekly       = df_t["risk_score"].resample("W").mean()
        smoothed     = weekly.rolling(window=3, min_periods=1).mean()
        ax1.fill_between(weekly.index, 0, 1, alpha=0.08, color="green",  label="Low zone")
        ax1.fill_between(weekly.index, 1, 3, alpha=0.08, color="orange", label="Medium zone")
        ax1.fill_between(weekly.index, 3, 6, alpha=0.08, color="red",    label="High zone")
        ax1.plot(weekly.index,   weekly.values,   "o-", color="steelblue",  lw=1.5, ms=4, label="Weekly avg")
        ax1.plot(smoothed.index, smoothed.values, "-",  color="darkorange", lw=2.5, label="Smoothed")
        ax1.axhline(y=1, color="green", ls="--", lw=0.8, alpha=0.5)
        ax1.axhline(y=3, color="red",   ls="--", lw=0.8, alpha=0.5)
        ax1.set_title("Risk Score Trend Over Time", fontweight="bold", fontsize=13)
        ax1.set_ylabel("Avg Risk Score"); ax1.set_ylim(0, 6)
        ax1.legend(fontsize=9)

    # Chart 2: Risk distribution pie
    ax2 = fig.add_subplot(gs[1, 0])
    counts = df["risk_level"].value_counts()
    cmap   = {"Low": "#4CAF50", "Medium": "#FF9800", "High": "#F44336"}
    ax2.pie(counts.values, labels=counts.index, autopct="%1.1f%%",
            colors=[cmap.get(l,"grey") for l in counts.index],
            startangle=140, textprops={"fontsize": 10})
    ax2.set_title("Risk Distribution", fontweight="bold")

    # Chart 3: Sentiment distribution
    ax3 = fig.add_subplot(gs[1, 1])
    if "sentiment" in df.columns:
        sent = df["sentiment"].value_counts()
        sent_colors = {"Positive": "#4CAF50", "Neutral": "#2196F3", "Negative": "#F44336"}
        ax3.bar(sent.index, sent.values,
                color=[sent_colors.get(s,"grey") for s in sent.index], edgecolor="white")
        ax3.set_title("Sentiment Distribution", fontweight="bold")
        ax3.set_ylabel("Count")
        for rect in ax3.patches:
            h = rect.get_height()
            ax3.text(rect.get_x() + rect.get_width()/2., h+0.3, f"{int(h)}",
                     ha="center", fontsize=9, fontweight="bold")

    # Chart 4: Source breakdown
    ax4 = fig.add_subplot(gs[1, 2])
    if "source" in df.columns:
        src_counts = df["source"].value_counts()
        ax4.barh(src_counts.index, src_counts.values, color="steelblue", edgecolor="white")
        ax4.set_title("Posts by Source", fontweight="bold")
        ax4.set_xlabel("Count")

    # Chart 5: Top symptoms
    ax5 = fig.add_subplot(gs[2, 0])
    top_symptoms = stats.get("top_symptoms", {})
    if top_symptoms:
        ax5.barh(list(top_symptoms.keys())[:8], list(top_symptoms.values())[:8],
                 color="coral", edgecolor="white")
        ax5.set_title("Top Symptoms", fontweight="bold")
        ax5.set_xlabel("Mentions")

    # Chart 6: Top conditions
    ax6 = fig.add_subplot(gs[2, 1])
    top_conditions = stats.get("top_conditions", {})
    if top_conditions:
        ax6.barh(list(top_conditions.keys())[:8], list(top_conditions.values())[:8],
                 color="mediumpurple", edgecolor="white")
        ax6.set_title("Top Conditions", fontweight="bold")
        ax6.set_xlabel("Mentions")

    # Chart 7: Top drugs
    ax7 = fig.add_subplot(gs[2, 2])
    top_drugs = stats.get("top_drugs", {})
    if top_drugs:
        ax7.barh(list(top_drugs.keys())[:8], list(top_drugs.values())[:8],
                 color="mediumseagreen", edgecolor="white")
        ax7.set_title("Top Drugs Mentioned", fontweight="bold")
        ax7.set_xlabel("Mentions")

    st.pyplot(fig)

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    st.download_button("📥 Download Dashboard PNG", buf.getvalue(), "dashboard.png", "image/png")


# ===========================================================
# PAGE 5 — ADMIN
# ===========================================================

elif page == "⚙️  Admin":
    st.title("⚙️ Admin — Source Engine Management")

    # Existing engines
    st.subheader("Registered Source Engines")
    engines = get_source_engines()
    for e in engines:
        cfg = json.loads(e.get("config","{}"))
        with st.expander(f"**{e['name']}** ({e['engine_type']})"):
            st.json(cfg)
            st.markdown(f"Requires API Key: `{cfg.get('requires_key', False)}`")

    st.markdown("---")

    # Add new engine
    st.subheader("➕ Register New Source Engine")
    with st.form("add_engine"):
        eng_name    = st.text_input("Engine Name",     placeholder="e.g. CustomForum")
        eng_type    = st.selectbox("Engine Type",      ["api", "scraper", "rss"])
        eng_url     = st.text_input("Base URL",        placeholder="https://example.com")
        eng_key     = st.checkbox("Requires API Key")
        eng_notes   = st.text_area("Notes / Config",   placeholder="Any extra config info")
        submitted   = st.form_submit_button("➕ Register Engine")
        if submitted and eng_name and eng_url:
            add_source_engine(eng_name, eng_type, {
                "base_url": eng_url,
                "requires_key": eng_key,
                "notes": eng_notes
            })
            st.success(f"✅ Engine **{eng_name}** registered!")
            st.rerun()

    st.markdown("---")
    st.subheader("ℹ️ System Info")
    st.markdown(f"- **DB Path:** `healthwatch.db`")
    st.markdown(f"- **Available engines:** {', '.join(ENGINES.keys())}")
    st.markdown(f"- **Version:** 1.0.0")