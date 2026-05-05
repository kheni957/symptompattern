# HealthWatch — Patient Signal Monitor
Real-Time Social Listening for Patient Experience & Safety Signals

---

## The Problem
When patients experience side effects, adverse reactions, or treatment failures, they often share these experiences online — on forums, Q&A sites, and social platforms — long before they report them to a doctor or regulator. This real-world signal gets lost in the noise.

Healthcare teams, researchers, and pharmacovigilance professionals have no easy way to monitor these conversations at scale, identify emerging safety patterns, or flag urgent cases that need attention.

---

## What HealthWatch Does
HealthWatch is a web app that continuously monitors patient discussions across multiple online sources and automatically analyses them for health and safety signals.

You give it a set of keywords (e.g. a drug name, condition, or symptom), and it:

- **Fetches posts** from medical forums, Q&A communities, research databases, and adverse event reports
- **Analyses each post** for sentiment (positive/negative/neutral), risk level (Low/Medium/High scored 0–100), safety keywords, and PII/PHI detection
- **Extracts entities** — drugs mentioned, conditions, symptoms, durations
- **Flags safety concerns** automatically — posts mentioning hospitalisation, overdose, seizures, fatal outcomes, and similar triggers are highlighted immediately
- **Detects PII** — personally identifiable information (emails, phone numbers, national IDs across multiple countries) is flagged to protect patient privacy
- **Identifies trends** — volume spikes, topic drift, drug-event signal patterns, and escalation across time
- **Exports results** as a CSV — including a full risk score breakdown column showing exactly what contributed to each post's score (e.g. `+40 safety keyword; +15 worsening; +5 symptom present`)

Analysis runs in two modes — a free built-in heuristic engine, or optionally Claude AI for deeper natural language understanding.

---

## Installation

**1. Save these two files in the same folder:**
- `healthwatch.py`
- `requirements.txt`

**2. Install dependencies:**

```bash
pip install -r requirements.txt
```

`requirements.txt` contents:
```
streamlit>=1.32.0
pandas>=2.0.0
matplotlib>=3.7.0
requests>=2.31.0
beautifulsoup4>=4.12.0
python-dotenv>=1.0.0
# anthropic>=0.25.0
```

> **To enable Claude AI Analysis:** open `requirements.txt`, remove the `#` at the start of the `anthropic` line, then re-run:
> ```bash
> pip install -r requirements.txt
> ```

---

## Running the App

```bash
streamlit run healthwatch.py
```

The app will open automatically in your browser at `http://localhost:8501`.

---

## Fresh Start (Recommended on First Run)

If you have a leftover `healthwatch.db` from a previous session, delete it before starting:

**Mac / Linux:**
```bash
rm healthwatch.db
streamlit run healthwatch.py
```

**Windows:**
```bash
del healthwatch.db
streamlit run healthwatch.py
```

The database is recreated automatically on startup.

---

## Data Sources

| Source | Type | API Key Required |
|--------|------|-----------------|
| Reddit | Patient forums | No |
| PubMed | Biomedical research abstracts | No |
| OpenFDA | FDA adverse event reports | No |
| ClinicalTrials | Completed clinical studies | No |
| MedlinePlus | NIH health topics | No |
| Twitter / X | Real-time patient posts | Yes — twitterapi.io |

Reddit, PubMed, OpenFDA, ClinicalTrials, and MedlinePlus are all free with no account needed. Twitter requires a key from [twitterapi.io](https://twitterapi.io) (see below).

---

## Optional: Twitter / X

To enable Twitter as a data source:

1. Sign up at [twitterapi.io](https://twitterapi.io) and copy your API key
2. Paste it into the **🐦 Twitter / X** field in the sidebar

The key is session-only and never saved to disk. If no key is entered, Twitter is simply skipped during fetches.

---

## Optional: Claude AI Analysis

By default the app runs in **heuristic mode** (free, no key needed).

To enable Claude AI-powered analysis:

1. Open `requirements.txt` and remove the `#` before `anthropic>=0.25.0`
2. Run `pip install -r requirements.txt`
3. Get an API key from [console.anthropic.com](https://console.anthropic.com)
4. Paste it into the **Anthropic API Key** field in the sidebar
5. Check **Enable Claude AI Analysis**

The key is session-only and never saved to disk.

---

## Getting Started

1. Go to **📁 Projects** → create a project with keywords (e.g. `ibuprofen, side effects, pain`)
2. Select data sources (Reddit + OpenFDA recommended for starters; add PubMed for broader coverage)
3. Go to **🔍 Run Analysis** → select your project → click **Start Fetch & Analysis**
4. View results in **📊 Signals & Trends**

---

## CSV Upload (Offline Analysis)

Go to **🔍 Run Analysis → Upload CSV tab** to analyse your own data without fetching live sources. The CSV needs at least a title and body column — all other columns are optional.

---

## Troubleshooting

**App won't start** — make sure all packages installed without errors: `pip install -r requirements.txt`

**No signals found** — try broader keywords (single words like `ibuprofen` work better than phrases)

**Reddit returns 0 posts** — Reddit rate-limits aggressively; wait 60 seconds and try again

**PubMed returns 0 posts** — NCBI rate-limits to ~3 requests/second; wait 60 seconds and retry with simpler keywords

**Twitter returns 0 posts** — check that your twitterapi.io key is entered in the sidebar; if rate-limited, wait a few minutes

**Claude AI option greyed out** — the `anthropic` package is not installed; follow the Claude AI setup steps above

**Database errors** — delete `healthwatch.db` and restart