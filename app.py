import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import requests
import os
import time
from datetime import datetime
from io import BytesIO

# ===========================================================
# PAGE CONFIG
# ===========================================================

st.set_page_config(page_title="Health Risk Dashboard", layout="wide")
st.title("🏥 Health Risk Analysis Dashboard")

# ===========================================================
# KEYWORDS
# ===========================================================

symptoms          = ["fever", "fatigue", "pain", "chills", "nausea", "weak", "headache"]
worsening_words   = ["worse", "getting worse", "not improving", "deteriorating"]
duration_words    = ["days", "weeks", "months", "still", "since"]
treatment_failure = ["not working", "no effect", "antibiotics aren't working", "not helping"]
positive_words    = ["better", "improving", "recovered"]

def quality_check(text, selftext="x"):
    has_symptom = any(w in text for w in symptoms)
    has_context = any(w in text for w in duration_words + worsening_words + treatment_failure)
    long_enough = len(text) > 60
    not_removed = selftext not in ["[removed]", "[deleted]", ""]
    return has_symptom and has_context and long_enough

# ===========================================================
# FETCH FUNCTIONS
# ===========================================================

def fetch_reddit(target=100):
    subreddits = [
        "AskDocs", "DiagnoseMe", "medical_advice",
        "Longcovid", "covidlonghaulers", "cfs",
        "Fibromyalgia", "chronicpain"
    ]
    session = requests.Session()
    session.headers.update({"User-Agent": "HealthRiskScraper/1.0"})
    posts = []
    for sub in subreddits:
        if len(posts) >= target:
            break
        try:
            url = f"https://www.reddit.com/r/{sub}/search.json?q=fever+fatigue&sort=new&limit=25&restrict_sr=1"
            r = session.get(url, timeout=10)
            time.sleep(1.5)
            if r.status_code == 429:
                time.sleep(10)
                r = session.get(url, timeout=10)
            if r.status_code != 200:
                continue
            for post in r.json().get("data", {}).get("children", []):
                if len(posts) >= target:
                    break
                p        = post.get("data", {})
                title    = p.get("title", "")
                selftext = p.get("selftext", "")
                if selftext in ["[removed]", "[deleted]", ""]:
                    continue
                full_text = (title + " " + selftext).strip().lower()
                if quality_check(full_text, selftext):
                    posts.append({
                        "date":   pd.to_datetime(p.get("created_utc", 0), unit='s').strftime("%Y-%m-%d"),
                        "source": "Reddit",
                        "title":  title,
                        "text":   full_text,
                        "url":    "https://reddit.com" + p.get("permalink", "")
                    })
        except Exception as e:
            st.warning(f"Reddit r/{sub} error: {e}")
    return posts


def fetch_openfda(target=100):
    searches = [
        "patient.reaction.reactionmeddrapt:fever",
        "patient.reaction.reactionmeddrapt:fatigue",
        "patient.reaction.reactionmeddrapt:pyrexia",
        "patient.reaction.reactionmeddrapt:chills",
        "patient.reaction.reactionmeddrapt:asthenia",
    ]
    posts = []
    for search in searches:
        if len(posts) >= target:
            break
        try:
            url = f"https://api.fda.gov/drug/event.json?search={search}&limit=25"
            r = requests.get(url, timeout=12)
            time.sleep(1)
            if r.status_code != 200:
                continue
            for result in r.json().get("results", []):
                if len(posts) >= target:
                    break
                reactions  = result.get("patient", {}).get("reaction", [])
                drugs      = result.get("patient", {}).get("drug", [])
                reaction_text = ", ".join([rx.get("reactionmeddrapt", "").lower() for rx in reactions])
                drug_text     = ", ".join([d.get("medicinalproduct", "").lower() for d in drugs])
                serious       = result.get("serious", 0)
                full_text = (
                    f"patient reported reactions: {reaction_text}. "
                    f"drugs taken: {drug_text}. "
                    f"outcome: {'serious' if serious == 1 else 'non-serious'}. "
                    f"duration unknown since months of treatment."
                )
                receipt_date = result.get("receiptdate", "20240101")
                try:
                    date_str = datetime.strptime(receipt_date, "%Y%m%d").strftime("%Y-%m-%d")
                except:
                    date_str = "2024-01-01"
                has_symptom = any(w in full_text for w in symptoms + ["pyrexia", "asthenia", "malaise", "myalgia"])
                if has_symptom and len(full_text) > 60:
                    posts.append({
                        "date":   date_str,
                        "source": "OpenFDA",
                        "title":  f"FDA report: {reaction_text[:80]}",
                        "text":   full_text,
                        "url":    "https://open.fda.gov/apis/drug/event/"
                    })
        except Exception as e:
            st.warning(f"OpenFDA error: {e}")
    return posts


def fetch_pubmed(target=100):
    queries = [
        "persistent+fever+fatigue",
        "low+grade+fever+chronic+fatigue",
        "post+viral+fatigue+fever",
        "fever+fatigue+treatment",
        "fever+fatigue+weeks",
        "fever+fatigue+pain+weeks",
        "chronic+fever+fatigue+syndrome",
        "unexplained+fever+fatigue",
    ]
    posts = []
    for query in queries:
        if len(posts) >= target:
            break
        try:
            search_url = (
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
                f"?db=pubmed&term={query}&retmax=15&retmode=json"
            )
            r = requests.get(search_url, timeout=10)
            time.sleep(0.4)
            if r.status_code != 200:
                continue
            ids = r.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                continue
            fetch_url = (
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
                f"?db=pubmed&id={','.join(ids)}&rettype=abstract&retmode=text"
            )
            r2 = requests.get(fetch_url, timeout=10)
            time.sleep(0.4)
            if r2.status_code != 200:
                continue
            for article in r2.text.strip().split("\n\n\n"):
                if len(posts) >= target:
                    break
                text  = article.strip().lower()
                lines = [l.strip() for l in article.split("\n") if l.strip()]
                title = lines[0][:120] if lines else "PubMed Abstract"
                has_symptom = any(w in text for w in symptoms + ["pyrexia", "malaise", "myalgia", "asthenia"])
                if has_symptom and len(text) > 60:
                    posts.append({
                        "date":   datetime.now().strftime("%Y-%m-%d"),
                        "source": "PubMed",
                        "title":  title,
                        "text":   text,
                        "url":    "https://pubmed.ncbi.nlm.nih.gov/"
                    })
        except Exception as e:
            st.warning(f"PubMed error: {e}")
    return posts

# ===========================================================
# RISK FUNCTIONS
# ===========================================================

def detect_symptoms(text):          return any(w in text for w in symptoms)
def detect_worsening(text):         return any(w in text for w in worsening_words)
def detect_duration(text):          return any(w in text for w in duration_words)
def detect_treatment_failure(text): return any(w in text for w in treatment_failure)
def detect_positive(text):          return any(w in text for w in positive_words)

def calculate_risk(row):
    score = 0
    if row['symptom']:           score += 1
    if row['duration']:          score += 1
    if row['worsening']:         score += 2
    if row['treatment_failure']: score += 2
    if row['positive']:          score -= 1
    return score

def classify_risk(score):
    if score <= 1:   return "Low"
    elif score <= 3: return "Medium"
    else:            return "High"

def generate_explanation(row):
    reasons = []
    if row['symptom']:           reasons.append("Symptoms detected (+1)")
    if row['duration']:          reasons.append("Long duration mentioned (+1)")
    if row['worsening']:         reasons.append("Condition worsening (+2)")
    if row['treatment_failure']: reasons.append("Treatment not effective (+2)")
    if row['positive']:          reasons.append("Signs of improvement (-1)")
    return "; ".join(reasons) if reasons else "No significant indicators"

def risk_meaning(level):
    if level == "Low":      return "Mild condition, monitor symptoms"
    elif level == "Medium": return "Moderate concern, consider medical advice"
    else:                   return "High risk, seek medical attention"

def process(df):
    df['text'] = df['text'].astype(str).str.lower()
    df['symptom']           = df['text'].apply(detect_symptoms)
    df['duration']          = df['text'].apply(detect_duration)
    df['worsening']         = df['text'].apply(detect_worsening)
    df['treatment_failure'] = df['text'].apply(detect_treatment_failure)
    df['positive']          = df['text'].apply(detect_positive)
    df['risk_score']        = df.apply(calculate_risk, axis=1)
    df['risk_level']        = df['risk_score'].apply(classify_risk)
    df['risk_reason']       = df.apply(generate_explanation, axis=1)
    df['risk_meaning']      = df['risk_level'].apply(risk_meaning)
    return df

# ===========================================================
# SIDEBAR — choose mode
# ===========================================================

st.sidebar.title("⚙️ Data Source")
mode = st.sidebar.radio("Choose how to load data:", [
    "📡 Fetch live from Reddit / OpenFDA / PubMed",
    "📂 Load from saved CSV file"
])

df = None

# ── Mode 1: Fetch live ─────────────────────────────────────
if mode == "📡 Fetch live from Reddit / OpenFDA / PubMed":
    st.sidebar.markdown("---")
    r_target  = st.sidebar.slider("Reddit posts",  10, 100, 70)
    fda_target= st.sidebar.slider("OpenFDA posts", 10, 100, 70)
    pm_target = st.sidebar.slider("PubMed posts",  10, 100, 60)

    if st.sidebar.button("🚀 Fetch Data Now"):
        with st.spinner("Fetching from Reddit..."):
            reddit_posts = fetch_reddit(r_target)
        with st.spinner("Fetching from OpenFDA..."):
            fda_posts = fetch_openfda(fda_target)
        with st.spinner("Fetching from PubMed..."):
            pubmed_posts = fetch_pubmed(pm_target)

        all_posts = reddit_posts + fda_posts + pubmed_posts
        df = pd.DataFrame(all_posts).drop_duplicates(subset=['text']).reset_index(drop=True)
        st.session_state['df'] = df
        st.success(f"✅ Fetched {len(df)} posts total")

    elif 'df' in st.session_state:
        df = st.session_state['df']

# ── Mode 2: Load from CSV ──────────────────────────────────
else:
    st.sidebar.markdown("---")
    file_path = st.sidebar.text_input(
        "Paste your CSV file path here:",
        value=r"C:\Users\khenu\PycharmProjects\PythonProject5\combined_data.csv"
    )
    if st.sidebar.button("📂 Load CSV"):
        try:
            df = pd.read_csv(file_path)
            st.session_state['df'] = df
            st.success(f"✅ Loaded {len(df)} rows")
        except Exception as e:
            st.error(f"❌ Could not load file: {e}")

    elif 'df' in st.session_state:
        df = st.session_state['df']

# ===========================================================
# DASHBOARD — shown once data is loaded
# ===========================================================

if df is not None and not df.empty:

    df = process(df)

    # ── Summary metrics ────────────────────────────────────
    st.markdown("---")
    st.subheader("📌 Summary")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Posts",    len(df))
    col2.metric("🔴 High Risk",   int((df['risk_level'] == 'High').sum()))
    col3.metric("🟡 Medium Risk", int((df['risk_level'] == 'Medium').sum()))
    col4.metric("🟢 Low Risk",    int((df['risk_level'] == 'Low').sum()))

    # ── Filters ────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🔎 Filter & Explore")

    col_a, col_b = st.columns(2)
    with col_a:
        risk_filter = st.multiselect("Risk Level", ["Low", "Medium", "High"], default=["Low", "Medium", "High"])
    with col_b:
        if 'source' in df.columns:
            source_filter = st.multiselect("Source", df['source'].unique().tolist(), default=df['source'].unique().tolist())
        else:
            source_filter = None

    filtered_df = df[df['risk_level'].isin(risk_filter)]
    if source_filter and 'source' in df.columns:
        filtered_df = filtered_df[filtered_df['source'].isin(source_filter)]

    cols = ['date', 'source', 'title', 'risk_score', 'risk_level', 'risk_reason', 'risk_meaning'] \
        if 'source' in df.columns else \
        ['date', 'title', 'risk_score', 'risk_level', 'risk_reason', 'risk_meaning']

    st.dataframe(filtered_df[cols], use_container_width=True, height=300)

    st.download_button("📥 Download output.csv",
                       filtered_df.to_csv(index=False).encode('utf-8'),
                       "output.csv", "text/csv")

    # ── Charts ─────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📈 Visualizations")

    fig = plt.figure(figsize=(18, 14))
    fig.suptitle("Health Risk Analysis Dashboard", fontsize=16, fontweight='bold', y=0.98)
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.4, wspace=0.35)

    ax1 = fig.add_subplot(gs[0, :])
    if 'date' in df.columns:
        df['date']    = pd.to_datetime(df['date'], errors='coerce')
        df_sorted     = df.dropna(subset=['date']).sort_values('date').copy()
        df_sorted.set_index('date', inplace=True)
        weekly        = df_sorted['risk_score'].resample('W').mean()
        smoothed      = weekly.rolling(window=3, min_periods=1).mean()
        ax1.fill_between(weekly.index, 0, 1, alpha=0.08, color='green',  label='Low zone')
        ax1.fill_between(weekly.index, 1, 3, alpha=0.08, color='orange', label='Medium zone')
        ax1.fill_between(weekly.index, 3, 6, alpha=0.08, color='red',    label='High zone')
        ax1.plot(weekly.index,   weekly.values,   'o-', color='steelblue',  linewidth=1.5, markersize=4, label='Weekly avg')
        ax1.plot(smoothed.index, smoothed.values, '-',  color='darkorange', linewidth=2.5, label='Smoothed trend')
        ax1.axhline(y=1, color='green', linestyle='--', linewidth=0.8, alpha=0.5)
        ax1.axhline(y=3, color='red',   linestyle='--', linewidth=0.8, alpha=0.5)
        ax1.set_xlabel("Date"); ax1.set_ylabel("Avg Risk Score")
        ax1.set_title("Risk Trend Over Time (Weekly)", fontweight='bold')
        ax1.legend(fontsize=9); ax1.set_ylim(0, 6)

    ax2 = fig.add_subplot(gs[1, 0])
    counts     = df['risk_level'].value_counts()
    colors_map = {'Low': '#4CAF50', 'Medium': '#FF9800', 'High': '#F44336'}
    wedges, texts, autotexts = ax2.pie(
        counts.values, labels=counts.index, autopct='%1.1f%%',
        colors=[colors_map.get(l, 'grey') for l in counts.index],
        startangle=140, textprops={'fontsize': 11}
    )
    for at in autotexts: at.set_fontweight('bold')
    ax2.set_title("Risk Level Distribution", fontweight='bold')

    ax3 = fig.add_subplot(gs[1, 1])
    ax3.hist(df['risk_score'],
             bins=range(int(df['risk_score'].min()), int(df['risk_score'].max()) + 2),
             color='steelblue', edgecolor='white', linewidth=0.8, rwidth=0.8)
    ax3.axvspan(df['risk_score'].min() - 0.5, 1.5, alpha=0.08, color='green')
    ax3.axvspan(1.5, 3.5,                           alpha=0.08, color='orange')
    ax3.axvspan(3.5, df['risk_score'].max() + 0.5,  alpha=0.08, color='red')
    ax3.set_xlabel("Risk Score"); ax3.set_ylabel("Number of Posts")
    ax3.set_title("Risk Score Distribution", fontweight='bold')
    for rect in ax3.patches:
        h = rect.get_height()
        if h > 0:
            ax3.text(rect.get_x() + rect.get_width()/2., h + 0.3, f'{int(h)}',
                     ha='center', va='bottom', fontsize=9, fontweight='bold')

    st.pyplot(fig)

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches='tight')
    st.download_button("📥 Download Dashboard PNG", buf.getvalue(), "risk_dashboard.png", "image/png")

else:
    st.info("👈 Use the sidebar to fetch live data or load a CSV file.")