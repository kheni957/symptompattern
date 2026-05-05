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

## Data Sources

| Source | Type |
|--------|------|
| Medical Sciences Stack Exchange | People Q&A health forum |
| PubMed | Biomedical research abstracts |
| OpenFDA | FDA adverse event reports |
| ClinicalTrials | Completed clinical studies |
| MedlinePlus | NIH health topics |
| Reddit | Patient forums (local deployment only) |
| Twitter / X | Real-time posts (API key required) |

> ⚠️ Reddit is supported in local deployment only. On the cloud version, use Medical Sciences Stack Exchange as the people forum source.

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

**3. Run the app:**

```bash
streamlit run healthwatch.py
```

---

## Optional: Enable Claude AI Analysis

By default the app runs in heuristic mode (free, no key needed). To enable Claude AI:

1. Remove the `#` before `anthropic>=0.25.0` in `requirements.txt` and re-run `pip install -r requirements.txt`
2. Get an API key from [console.anthropic.com](https://console.anthropic.com)
3. Paste it into the Anthropic API Key field in the sidebar and check **Enable Claude AI Analysis**

---

## Quick Start

1. Go to **📁 Projects** → create a project with keywords (e.g. `ibuprofen, side effects, pain`)
2. Select your data sources
3. Go to **🔍 Run Analysis** → click **Start Fetch & Analysis**
4. View results, charts, and safety alerts in **📊 Signals & Trends**
5. Download the full CSV with risk score breakdown

---

## Troubleshooting

**No signals found** — use broader, single-word keywords like `ibuprofen` rather than phrases

**Reddit returns 0 posts** — Reddit is local only; use Medical Sciences Stack Exchange on the cloud version

**MedlinePlus warning** — occasional network issue; the app skips it automatically and retries next run

**Claude AI greyed out** — install the `anthropic` package first (see above)

**Database errors** — delete `healthwatch.db` and restart the app