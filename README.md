# HealthWatch — Patient Signal Monitor

Real-Time Social Listening for Patient Experience & Safety Signals

---

## Requirements

- Python 3.9 or higher
- pip

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

| Source | Type | API Key Required | Deployment |
|--------|------|-----------------|------------|
| Reddit | Patient forums | No | Local only |
| PubMed | Biomedical research abstracts | No | Local & Cloud |
| OpenFDA | FDA adverse event reports | No | Local & Cloud |
| ClinicalTrials | Completed clinical studies | No | Local & Cloud |
| MedlinePlus | NIH health topics | No | Local & Cloud |
| Medical Sciences Stack Exchange | People Q&A health forum | No | Local & Cloud |
| Twitter / X | Real-time patient posts | Yes — twitterapi.io | Local & Cloud |

> ⚠️ **Reddit is for local deployment only.** Reddit blocks requests from cloud servers. When using the hosted app, use **Medical Sciences Stack Exchange** as your people forum source alongside PubMed and OpenFDA.

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
2. Select data sources:
   - **Local:** Reddit + OpenFDA recommended for starters
   - **Cloud:** Medical Sciences Stack Exchange + OpenFDA + PubMed recommended
3. Go to **🔍 Run Analysis** → select your project → click **Start Fetch & Analysis**
4. View results in **📊 Signals & Trends**

---

## CSV Upload (Offline Analysis)

Go to **🔍 Run Analysis → Upload CSV tab** to analyse your own data without fetching live sources. The CSV needs at least a title and body column — all other columns are optional.

---

## Troubleshooting

**App won't start** — make sure all packages installed without errors: `pip install -r requirements.txt`

**No signals found** — try broader keywords (single words like `ibuprofen` work better than phrases)

**Reddit returns 0 posts** — Reddit is only supported in local deployment; switch to Medical Sciences Stack Exchange on the cloud version. If running locally, Reddit rate-limits aggressively — wait 60 seconds and try again

**PubMed returns 0 posts** — NCBI rate-limits to ~3 requests/second; wait 60 seconds and retry with simpler keywords

**MedlinePlus warning on startup** — occasional DNS/network issue on MedlinePlus's server; the app will skip it automatically and retry next run

**Twitter returns 0 posts** — check that your twitterapi.io key is entered in the sidebar; if rate-limited, wait a few minutes

**Claude AI option greyed out** — the `anthropic` package is not installed; follow the Claude AI setup steps above

**Database errors** — delete `healthwatch.db` and restart